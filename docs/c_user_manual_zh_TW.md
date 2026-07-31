# NR C User Manual（繁體中文）

本手冊說明 `c_impl/` 內 MMSE-LSA／OMLSA 降噪器的建置、命令列操作與 C 程式整合方式。演算法原理與評測結果請參考專案根目錄的 `README.md` 與 `ALGORITHMS_EXPLANATION.md`。

> 驗證基準：NR commit `461adf2`（`feature/static-memory`，2026-07-10）。若 header 或 Makefile 後續有修改，請以 `c_impl/include/` 與 `c_impl/Makefile` 為最終依據。

## 1. 先理解 API 邊界

`mmse_lsa_process()` 是**頻域 API**，不是 PCM／時域 hop API：

- 每次呼叫輸入一個 `Complex[n_freqs]` 頻譜，輸出套用 NR gain 後的同尺寸頻譜。
- 呼叫端負責 50% overlap framing、sqrt-Hann window、rFFT、iFFT 與 overlap-add（OLA）。
- 每個 instance 的 `frame_size`、`hop_size` 與 `fft_size` 在建立後固定；不能在串流中途修改。
- 可使用同一個 buffer in-place 處理：`spectrum_in == spectrum_out`。

資料流如下：

```text
PCM hop -> rolling frame -> sqrt-Hann -> rFFT
        -> mmse_lsa_process() -> iFFT -> sqrt-Hann -> OLA -> PCM hop
```

若只需要 per-bin gain，或要把 AEC residual echo PSD 當成額外噪聲加入估計，可使用 `mmse_lsa_process_gain()`。這個 API 實作的是 Speex/Habets「echo-as-extra-noise」統一增益公式 ξ = S²/(N² + R²)：把 residual echo PSD R² 併入分母的噪聲項後，一併餵給 SPP／a-priori-SNR 估計，但 MCRA 噪聲追蹤器本身仍只用乾淨功率更新、不會被 R² 污染。典型用法是外接 AEC(linear) → NR → RES 的串接：把 AEC 的 windowed error spectrum 當作 `spectrum_in`（例如 E(f)），並以 `ctx.r2/32768²`（把 Q15 尺度的殘留回聲功率換算成與 `|spectrum_in|²` 相同的線性尺度）當作 `extra_noise_psd` 傳入，再將輸出的 `gain_out` 與下游 AEC3 的 `res_gain` 合併使用；若不需要這個功能，`extra_noise_psd` 傳 `NULL` 即與純噪聲版 NR 行為完全相同。

## 2. 建置

從 NR repo 根目錄執行：

```bash
cd c_impl

make            # bin/<backend>-<config-hash>/denoise_wav：KISS FFT + fast math
make lib        # bin/<backend>-<config-hash>/libmmse_lsa.a
make debug      # standard math，較適合與 Python 對照（DEBUG=1，見下方鍵值目錄說明）
make mem        # bin/<backend>-<config-hash>/denoise_mem：靜態記憶體示範 runner（_get_mem_size/_init）
```

輸出檔案位於依 backend + 編譯參數雜湊命名的 `bin/<backend>-<config-hash>/` 目錄
（round-3 review B01）；用 `make print-bin-dir`（帶上與建置相同的參數）取得確切
路徑，或 `make publish` 產出穩定的 `dist/<backend>/current/` 交付路徑。以下範例
指令為簡潔起見省略此前綴。

FFT 與 fast_math 來自共用的 `../audio_common` layer（`c_impl/Makefile` 會自動先建它的
`libaudio_common.a` 再連結）。backend 以 `BACKEND` 變數選擇——預設 `kiss`（可攜、bit-reproducible、
Python parity 的參考 backend）；嵌入式 deliverable 用 NE10：

```bash
make BACKEND=ne10                 # ARM NEON NE10 backend
make mem BACKEND=ne10             # 靜態記憶體 runner + NE10（此分支實際交付組合）
```

切換 `BACKEND`（或 `EXTRA_CFLAGS`／`WERROR`／`DEBUG`）不需要手動 `make clean`——
`obj/`與`bin/`（round-3 review B01 起兩者皆是）現在依 `<backend>-<config-hash>`
分子目錄存放，每種組合各自獨立，切換後會自動編到新的目錄，不會誤用舊組合殘留
的 `.o` 或誤連結到另一組態的執行檔／archive；不同組合甚至可以在同一份 checkout
裡同時平行建置。

常用 build 選項：

```bash
# 使用標準 expf/logf/sqrtf 等函式
make EXTRA_CFLAGS="-DUSE_STANDARD_MATH"

# 用近似 percentile 減少 MCRA 初始化記憶體與計算量
make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"
```

外部程式連結 static library 的基本命令（同時要連 audio_common 的 archive）：

```bash
cc -std=gnu99 app.c -Ic_impl/include -I../audio_common/include \
   $(make -s -C c_impl print-lib-path) \
   $(make -s -C ../audio_common BACKEND=kiss print-lib-path) -lm -o app
```

若改用 NE10 backend，兩個 `print-lib-path` 呼叫都加上 `BACKEND=ne10`，並用 C++
driver 連結（audio_common 的 NE10 archive 內含一個 C++ TU）或補 `-lc++`。

## 3. 命令列工具

```bash
./bin/denoise_wav noisy.wav clean.wav
./bin/denoise_wav noisy.wav clean.wav --nr-mode mild
./bin/denoise_wav noisy.wav clean.wav --nr-mode moderate
./bin/denoise_wav noisy.wav clean.wav --nr-mode aggressive
./bin/denoise_wav noisy.wav clean.wav --nr-mode balanced --stationary
./bin/denoise_wav input.wav copied.wav --bypass
```

### 3.1 模式

| Mode | `g_min_db` | 適用方向 |
|---|---:|---|
| `mild` | -20 dB | 最保守，優先保留語音細節 |
| `moderate` | -25 dB | mild 與 balanced 之間 |
| `balanced` | -30 dB | 預設，語音品質與抑噪平衡 |
| `aggressive` | -40 dB | 抑噪最深，可能犧牲較多細節 |

`--stationary` 是疊加在 strength mode 上的內容保留模式：只針對穩態噪聲底進行抑制，並使用 tonal veto 降低音樂／瞬態被誤當成場景變化的機率。它不是第五種 strength preset。

### 3.2 WAV contract

- 建議 sample rate：8、16 或 48 kHz。
- 輸入支援 PCM16、PCM32 與 IEEE float32 WAV。
- 多聲道輸入只處理第一聲道。
- `denoise_wav` 輸出單聲道 PCM16 WAV。
- `denoise_wav` 與 library 使用相同的無補零 grid：8 kHz=256/128、16 kHz=512/256、48 kHz=1024/512；16 kHz 另可明確選 256/128。
- `num_init_frames=20` 是舊 10 ms hop 的參考值；建構時會依實際 hop retime，使初始化至少約 200 ms。最好讓開頭包含背景噪聲且沒有目標語音。

產品 callback 必須查詢 config/getter 的實際 `hop_size`，不可假設固定 10 ms。

## 4. Heap C API：完整 streaming wrapper

以下範例可直接存成 `nr_stream.c` 並以 `cc -std=gnu99 -c nr_stream.c -Ic_impl/include` 編譯。上層每次餵入、取出一個 `hop_size` 的 float PCM block；範例內部完成 framing、FFT 與 OLA。

```c
/* NR_STREAM_EXAMPLE_BEGIN */
#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "fft_wrapper.h"
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef struct {
    MmseLsaConfig cfg;
    MmseLsaDenoiser *nr;
    FftHandle *fft;
    float *window;       /* [frame_size] */
    float *analysis;     /* rolling [frame_size] */
    float *ola;          /* [frame_size] */
    float *fft_time;     /* [fft_size] */
    Complex *spectrum;   /* [fft_size / 2 + 1] */
} NrStream;

void nr_stream_destroy(NrStream *s)
{
    if (!s) return;
    mmse_lsa_destroy(s->nr);
    fft_destroy(s->fft);
    free(s->window);
    free(s->analysis);
    free(s->ola);
    free(s->fft_time);
    free(s->spectrum);
    memset(s, 0, sizeof(*s));
}

int nr_stream_init(NrStream *s, int sample_rate,
                   MmseLsaNrMode mode, int stationary)
{
    int n;
    int n_freqs;

    if (!s) return -1;
    memset(s, 0, sizeof(*s));

    s->cfg = mmse_lsa_config_for_mode(sample_rate, mode);
    if (stationary) mmse_lsa_apply_stationary(&s->cfg);

    n_freqs = s->cfg.fft_size / 2 + 1;
    s->window = (float *)malloc((size_t)s->cfg.frame_size * sizeof(float));
    s->analysis = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->ola = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->fft_time = (float *)calloc((size_t)s->cfg.fft_size, sizeof(float));
    s->spectrum = (Complex *)malloc((size_t)n_freqs * sizeof(Complex));
    s->nr = mmse_lsa_create(&s->cfg);
    s->fft = fft_create(s->cfg.fft_size);

    if (!s->window || !s->analysis || !s->ola || !s->fft_time ||
        !s->spectrum || !s->nr || !s->fft) {
        nr_stream_destroy(s);
        return -1;
    }

    for (n = 0; n < s->cfg.frame_size; ++n) {
        float hann = 0.5f - 0.5f * cosf(
            2.0f * (float)M_PI * (float)n / (float)s->cfg.frame_size);
        s->window[n] = sqrtf(hann); /* sqrt(periodic Hann) */
    }
    return 0;
}

int nr_stream_process(NrStream *s, const float *input, float *output)
{
    int n;
    int frame;
    int hop;

    if (!s || !s->nr || !input || !output) return -1;
    frame = s->cfg.frame_size;
    hop = s->cfg.hop_size;

    memmove(s->analysis, s->analysis + hop,
            (size_t)(frame - hop) * sizeof(float));
    memcpy(s->analysis + frame - hop, input, (size_t)hop * sizeof(float));

    memset(s->fft_time, 0, (size_t)s->cfg.fft_size * sizeof(float));
    for (n = 0; n < frame; ++n)
        s->fft_time[n] = s->analysis[n] * s->window[n];

    fft_forward(s->fft, s->fft_time, s->spectrum);
    if (mmse_lsa_process(s->nr, s->spectrum, s->spectrum) < 0)
        return -1;
    fft_inverse(s->fft, s->spectrum, s->fft_time);

    for (n = 0; n < frame; ++n)
        s->ola[n] += s->fft_time[n] * s->window[n];

    memcpy(output, s->ola, (size_t)hop * sizeof(float));
    memmove(s->ola, s->ola + hop,
            (size_t)(frame - hop) * sizeof(float));
    memset(s->ola + frame - hop, 0, (size_t)hop * sizeof(float));
    return 0;
}

void nr_stream_reset(NrStream *s)
{
    if (!s || !s->nr) return;
    mmse_lsa_reset(s->nr);
    memset(s->analysis, 0, (size_t)s->cfg.frame_size * sizeof(float));
    memset(s->ola, 0, (size_t)s->cfg.frame_size * sizeof(float));
}
/* NR_STREAM_EXAMPLE_END */
```

使用方式：

```c
NrStream stream;
if (nr_stream_init(&stream, 16000, MMSE_LSA_NR_BALANCED, 0) != 0)
    return -1;

int hop = stream.cfg.hop_size;
/* 每次準備 float input[hop]，輸出到 float output[hop]。 */
if (nr_stream_process(&stream, input, output) != 0) {
    nr_stream_destroy(&stream);
    return -1;
}

/* 處理另一條獨立串流前： */
nr_stream_reset(&stream);
nr_stream_destroy(&stream);
```

`mmse_lsa_get_latency()` 回報的是頻域 core 本身的 latency，目前為 0；它**不包含**呼叫端的 framing／OLA 延遲。整體延遲必須依上層採用的 buffering 方法另行計算。

## 5. 靜態記憶體（caller-owned memory）：`_get_mem_size()` + `_init()`

靜態記憶體路徑**不再需要任何 compile flag**（舊的 `-DUSE_EXT_MEM` 已移除）。malloc 路徑
（`mmse_lsa_create()`）與靜態路徑（`mmse_lsa_get_mem_size()` + `mmse_lsa_init()`）永遠同時存在於
同一份 library；用哪一條純粹取決於呼叫哪個函式（handle 內部以 runtime `is_static` flag 區分，
`mmse_lsa_destroy()` 對靜態 instance 是 no-op——`MmseLsaDenoiser` 本身不持有 FFT 或其他
backend heap 資源，caller 另外自備的 `FftHandle` 才是需要注意 NE10 例外的地方，見下方
重要規則）。命名與參數順序跟 AEC 的 `aec_get_mem_size()`/`aec_init(mem, size, cfg)` 一致。

隨附的 `bin/denoise_mem` 是示範 runner：它依輸入 sample rate 使用相同的無補零 grid，並以 `MAX_SECONDS=60` 限制 whole-file static I/O buffer。後者是 example 限制，不是 `mmse_lsa_get_mem_size()`／靜態記憶體 core API 的限制；產品應使用自己的固定大小 PCM ring 與 scratch buffer。

```c
#include <stdint.h>
#include "fft_wrapper.h"        /* 由共用的 audio_common 提供 */
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

/* 實務上可換成 linker section 或平台 memory pool。 */
static uint8_t nr_pool[96 * 1024] __attribute__((aligned(16)));
static uint8_t fft_pool[24 * 1024] __attribute__((aligned(16)));

int create_static_nr(MmseLsaConfig *cfg,
                     MmseLsaDenoiser **nr, FftHandle **fft)
{
    size_t nr_need;
    size_t fft_need;

    if (!cfg || !nr || !fft) return -1;
    *cfg = mmse_lsa_default_config(16000);
    nr_need = mmse_lsa_get_mem_size(cfg);
    fft_need = fft_get_mem_size(cfg->fft_size);
    if (nr_need > sizeof(nr_pool) || fft_need > sizeof(fft_pool))
        return -1;

    *nr = mmse_lsa_init(nr_pool, sizeof(nr_pool), cfg);
    *fft = fft_init(fft_pool, sizeof(fft_pool), cfg->fft_size);
    if (!*nr || !*fft) return -1;
    return 0;
}

/* cleanup：兩者都不會釋放 caller pool（nr_pool/fft_pool 生命週期由 caller 管理）。
 * mmse_lsa_destroy(nr) 對靜態 instance 是真正的 no-op（denoiser 不持有額外 heap 資源）。
 * fft_destroy(fft) 在 KISS 與 NE10 兩個 backend 下同樣是真正的 no-op：自 P0001
 * （+P0003 硬化）起，NE10 的 R2C/C2R twiddle cfg 也是由 fft_init() 從 fft_pool 切出
 * （已計入 fft_get_mem_size()），沒有任何 backend-internal malloc；fft_destroy() 對
 * pool-owned handle 一律直接 return，呼叫幾次都安全（idempotent）。 */
void destroy_static_nr(MmseLsaDenoiser *nr, FftHandle *fft)
{
    mmse_lsa_destroy(nr);
    fft_destroy(fft);
}
```

重要規則：

- pool 起始位址必須 16-byte 對齊（`ALIGN16`，定義於 audio_common 的 `mem_align.h`）。
- `_get_mem_size()` 的結果與 config 有關，config 變更後要重新 query。
- KISS 與 NE10 兩個 FFT backend 都能做到所有 NR／MCRA／SPP／FFT state 使用 caller memory。
- 自 P0001（+P0003 硬化）起，`audio_common` 用 vendored 的 `ne10_fft_init_r2c_float32_ext`
  讓 NE10 的 R2C/C2R twiddle cfg 也從 `fft_pool` 切出（已計入 `fft_get_mem_size()`），
  `fft_init()` 到 `fft_destroy()` 全程零 heap；per-hop audio path 本來就不配置。
- window、OLA、PCM ring 與 application scratch 仍由 application 自行配置；它們不包含在 `mmse_lsa_get_mem_size()` 中。

## 6. Lifecycle、回傳值與 query API

典型生命週期：

1. `mmse_lsa_default_config()` 或 `mmse_lsa_config_for_mode()`。
2. 在 create 前完成 config override。
3. `mmse_lsa_create()`；失敗回傳 `NULL`。
4. 每個 hop 做一次 FFT 與 `mmse_lsa_process()`；成功為 0，錯誤為負值。
5. 換獨立音訊串流前呼叫 `mmse_lsa_reset()`，並清除 caller 的 OLA／framing buffer。
6. `mmse_lsa_destroy()`；heap build 會釋放內部資源，external-memory build 不釋放 caller pool。

可查詢：

- 尺寸：`mmse_lsa_get_hop_size()`、`mmse_lsa_get_frame_size()`、`mmse_lsa_get_n_freqs()`。
- 狀態：`mmse_lsa_is_initialized()`。
- 頻域資料：`mmse_lsa_get_spp()`、`mmse_lsa_get_noise_psd()`、`mmse_lsa_get_gain()`。

query 回傳的陣列是 instance 的內部唯讀記憶體。不要修改或釋放；保守做法是在下一次 process／reset／destroy 前讀完或複製。

每個 instance 都是 stateful 且非 thread-safe。同一個 instance 不可由多個 thread 同時 process；多串流請各建一個 instance。

## 7. 重要 config 與調參順序

優先選 preset，不要一開始就改低階係數：

```c
MmseLsaConfig cfg = mmse_lsa_config_for_mode(
    16000, MMSE_LSA_NR_BALANCED);
```

常用欄位：

| 欄位 | 預設 | 說明 |
|---|---:|---|
| `frame_size` | 等於 FFT size | 無補零 analysis frame：8k=256、16k=512（可選256）、48k=1024 |
| `hop_size` | frame / 2 | 50% overlap；不保證固定 10 ms |
| `fft_size` | 等於 frame size | 只接受白名單中的 2 次方 grid |
| `num_init_frames` | 20（10 ms 參考值） | 建構時依 hop retime，至少約 200 ms |
| `g_min_db` | -30 | 振幅 gain floor，使用 `/20` dB 換算 |
| `alpha_g` | 0.88 | gain 平滑；較大通常較少 musical noise |
| `scene_change_threshold_db` | 10 | 場景切換敏感度 |
| `L` | 32（10 ms 參考值） | 建構時依 hop retime，約 320 ms |

不要在 create 後直接改保存於 caller 的 `MmseLsaConfig`，因為 instance 已經複製／衍生內部尺寸與狀態。要換 sample rate、frame、FFT 或 tracking buffer 大小時，destroy 後重新 create。

## 8. Troubleshooting

| 現象 | 先檢查 | 建議 |
|---|---|---|
| 完全沒有降噪 | 是否仍在前 20 個 init frame | 確認開頭噪聲段與 `mmse_lsa_is_initialized()` |
| 語音變悶 | preset 太強、gain floor 太低 | 改 `mild`／`moderate`，再考慮提高 `g_min_db` |
| musical noise | gain 變動過快 | 使用 balanced/mild，或適度提高 `alpha_g` |
| 音樂／瞬態被吃掉 | 統計型 speech/noise 假設不合 | 疊加 `stationary`，或改用更合適的演算法 |
| 場景切換追蹤太慢 | threshold 或 MCRA window 太保守 | 先降低 `scene_change_threshold_db`，避免任意大改多個係數 |
| 輸出有週期性振幅起伏 | window／OLA 錯誤 | 確認 periodic sqrt-Hann、50% overlap、analysis/synthesis 都乘同一 window |
| crash／頻譜越界 | FFT 尺寸與 `n_freqs` 不一致 | 一律由 config／query API 取得尺寸，不要硬編 257 |
| 新檔案沿用上一檔噪聲模型 | 忘記 reset | reset NR 並同時清 caller framing／OLA buffer |

本模組不負責 acoustic echo cancellation、dereverb、風切 buffeting 或與目標語音高度重疊的其他語音／音樂；這些輸入不能只靠調低 `g_min_db` 解決。

目前實作僅有浮點版本；定點化（Q15／Q31 數值格式、gain calculator／SPP／MCRA／FFT 定點化與對應 `USE_FIXED_POINT` 編譯開關）仍在規劃中、尚未實作，詳見 `c_impl/CHANGELOG.md`「尚未實作（階段 C：定點化）」一節。
