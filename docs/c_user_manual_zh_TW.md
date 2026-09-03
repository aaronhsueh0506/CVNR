# NR C Library 使用手冊（繁體中文）

這份手冊寫給**使用這個 library 的整合者**：什麼時候呼叫哪個函式、每個參數怎麼設。
不談演算法推導、不談內部實作。所有數值都直接讀自現行原始碼（header 預設值、
`mmse_lsa_validate_config()` 的檢查、config constructor），或由實際建置後執行程式量得。

原始碼位置一律以 repository 相對路徑表示（例如 `c_impl/include/mmse_lsa_denoiser.h`）。

---

## 0. 交付範圍與檔案清單

### 0.1 這個 library 是什麼

- 單聲道、**頻域**、逐 hop 的雜訊抑制（noise reduction）library。
- 只實作**一套演算法**：MMSE-LSA / OM-LSA（MCRA 噪聲估計 + Bayesian SPP 軟判決）。
  沒有第二種模式、沒有可切換的演算法家族。
- 輸入與輸出都是 `Complex[n_freqs]` 頻譜。**framing、window、FFT、IFFT、overlap-add
  全部由呼叫端負責**，library 不碰 PCM。
- 只有 float32 實作；沒有定點（fixed-point）版本，原始碼中沒有任何 `USE_FIXED_POINT` 路徑。
- 提供 heap 與 caller-owned static memory 兩條建構路徑，兩條都永遠編譯進同一份 archive。

### 0.2 這個 library 不是什麼（scope boundary）

- **不做** acoustic echo cancellation、dereverb、AGC、風切抑制、beamforming、多聲道處理。
- **不做**取樣率轉換、不讀寫檔案、不配置也不管理 PCM ring / window / OLA buffer。
- Python tree 裡的其他 variant（`denoisers/v1_spectral_subtraction.py`、
  `denoisers/v2_wiener.py`、`denoisers/v3_spp_mmse.py`、`denoisers/v3_3_pmmse.py`）
  **是研究用程式碼，C 端沒有任何對應實作**。不要以為 C library 可以切到那些模式。
- `config/*.yaml`（`v1_config.yaml`、`v2_config.yaml`、`v3_2_config.yaml`、
  `v3_3_config.yaml`、`v3_config.yaml`）**只給 Python 用**。C library 不讀任何設定檔，
  它唯一的參數入口就是 `MmseLsaConfig` 這個 struct。

### 0.3 交付檔案

需要 include 的 public header：

| 檔案 | 內容 | 是否要直接 include |
|---|---|---|
| `c_impl/include/mmse_lsa_denoiser.h` | 建構／處理／reset／查詢 API、`MmseLsaDebugStatus` | 是 |
| `c_impl/include/mmse_lsa_types.h` | `MmseLsaConfig`、`MmseLsaNrMode`、config constructor、`mmse_lsa_validate_config()` | 是（`mmse_lsa_denoiser.h` 已自動含入） |
| `../audio_common/include/fft_wrapper.h` | `Complex`、`FftHandle`、`fft_*` | 是（`mmse_lsa_denoiser.h` 已自動含入，見第 6 節） |
| `../audio_common/include/mem_align.h` | `ALIGN16` 等對齊巨集 | 否（由 `fft_wrapper.h` 帶入） |

連結需要的 archive：

| 檔案 | 內容 |
|---|---|
| `libmmse_lsa.a` | denoiser + MCRA + SPP core（本 repo 建置產生） |
| `libaudio_common.a` | FFT backend 與 fast math（`../audio_common` 建置產生） |

`libmmse_lsa.a` **不含** FFT，兩個 archive 必須一起連結。

隨附的執行檔（皆為示範／驗證用途，不是 library 的一部分）：

| 執行檔 | 用途 |
|---|---|
| `denoise_wav` | 完整的時域 wrapper 範例：讀 WAV → framing/FFT/NR/IFFT/OLA → 寫 WAV |
| `denoise_mem` | static memory 路徑（`_get_mem_size` + `_init`）示範 runner |
| `test_config_validation` | config 驗證與對齊防護的回歸測試 |
| `test_config_parity` | 印出各 grid × strength 的正規 config |

`make publish` 產出的 release 內容為 `libmmse_lsa.a` 與 `denoise_wav`；header 請直接從
source tree 取用。

### 0.4 內部子模組

`c_impl/include/mcra_noise_estimator.h` 與 `c_impl/include/spp_estimator.h`
是 denoiser 內部擁有的子模組介面，**整合者不應直接呼叫**（denoiser 會自行建立、驅動與釋放
它們；這兩個 header 也有數個宣告在 archive 中並不存在，直接呼叫會得到 link error）。

---

## 1. Quick start

### 1.1 最短的可編譯整合

以下整份程式碼可存成 `nr_stream.c`，直接編譯通過（已用
`-std=gnu99 -Wall -Wextra -Werror` 對現行 header 實際編譯驗證）。
上層每次餵入一個 `hop_size` 的 float PCM block、取回同長度的輸出。

```c
/* nr_stream.c -- minimal streaming wrapper around the NR C library. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "fft_wrapper.h"          /* audio_common: Complex, FftHandle, fft_*  */
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef struct {
    MmseLsaConfig    cfg;
    MmseLsaDenoiser *nr;
    FftHandle       *fft;
    float           *window;    /* [frame_size] sqrt(periodic Hann)          */
    float           *analysis;  /* [frame_size] rolling analysis frame       */
    float           *ola;       /* [frame_size] overlap-add accumulator      */
    float           *time_buf;  /* [fft_size]   FFT time-domain buffer       */
    Complex         *spectrum;  /* [fft_size/2 + 1]                          */
} NrStream;

void nr_stream_destroy(NrStream *s);

/* Returns 0 on success, -1 on failure (nothing is left allocated on -1). */
int nr_stream_init(NrStream *s, int sample_rate,
                   MmseLsaNrMode mode, int stationary)
{
    int n, n_freqs;

    if (!s) return -1;
    memset(s, 0, sizeof(*s));

    /* 1. config: preset on the default grid for this sample rate. */
    s->cfg = mmse_lsa_config_for_mode(sample_rate, mode);
    if (stationary) mmse_lsa_apply_stationary(&s->cfg);

    /* 2. validate before create (tells you the config itself was rejected). */
    if (!mmse_lsa_validate_config(&s->cfg)) return -1;

    n_freqs     = s->cfg.fft_size / 2 + 1;
    s->window   = (float *)malloc((size_t)s->cfg.frame_size * sizeof(float));
    s->analysis = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->ola      = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->time_buf = (float *)calloc((size_t)s->cfg.fft_size,   sizeof(float));
    s->spectrum = (Complex *)malloc((size_t)n_freqs * sizeof(Complex));

    /* 3. create denoiser + FFT. */
    s->nr  = mmse_lsa_create(&s->cfg);
    s->fft = fft_create(s->cfg.fft_size);

    if (!s->window || !s->analysis || !s->ola || !s->time_buf ||
        !s->spectrum || !s->nr || !s->fft) {
        nr_stream_destroy(s);
        return -1;
    }

    for (n = 0; n < s->cfg.frame_size; ++n) {
        float hann = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * (float)n /
                                        (float)s->cfg.frame_size);
        s->window[n] = sqrtf(hann);
    }
    return 0;
}

/* One hop in, one hop out: input[cfg.hop_size], output[cfg.hop_size]. */
int nr_stream_process(NrStream *s, const float *input, float *output)
{
    int n, frame, hop;

    if (!s || !s->nr || !input || !output) return -1;
    frame = s->cfg.frame_size;
    hop   = s->cfg.hop_size;

    /* slide the analysis frame by one hop, append the new hop */
    memmove(s->analysis, s->analysis + hop,
            (size_t)(frame - hop) * sizeof(float));
    memcpy(s->analysis + frame - hop, input, (size_t)hop * sizeof(float));

    /* analysis window; frame_size == fft_size, so no zero padding */
    for (n = 0; n < frame; ++n)
        s->time_buf[n] = s->analysis[n] * s->window[n];

    fft_forward(s->fft, s->time_buf, s->spectrum);   /* distinct buffers */
    if (mmse_lsa_process(s->nr, s->spectrum, s->spectrum) != 0)  /* in place */
        return -1;
    fft_inverse(s->fft, s->spectrum, s->time_buf);   /* distinct buffers */

    /* synthesis window + overlap-add */
    for (n = 0; n < frame; ++n)
        s->ola[n] += s->time_buf[n] * s->window[n];

    memcpy(output, s->ola, (size_t)hop * sizeof(float));
    memmove(s->ola, s->ola + hop, (size_t)(frame - hop) * sizeof(float));
    memset(s->ola + frame - hop, 0, (size_t)hop * sizeof(float));
    return 0;
}

/* Call at every stream boundary / scene change -- the library never does. */
void nr_stream_reset(NrStream *s)
{
    if (!s || !s->nr) return;
    mmse_lsa_reset(s->nr);
    memset(s->analysis, 0, (size_t)s->cfg.frame_size * sizeof(float));
    memset(s->ola,      0, (size_t)s->cfg.frame_size * sizeof(float));
}

void nr_stream_destroy(NrStream *s)
{
    if (!s) return;
    mmse_lsa_destroy(s->nr);
    fft_destroy(s->fft);
    free(s->window);
    free(s->analysis);
    free(s->ola);
    free(s->time_buf);
    free(s->spectrum);
    memset(s, 0, sizeof(*s));
}

/* ---- usage ------------------------------------------------------------- */
int nr_stream_demo(const float *pcm, int n_samples, float *out)
{
    NrStream s;
    int i, hop;

    if (nr_stream_init(&s, 16000, MMSE_LSA_NR_BALANCED, 0) != 0)
        return -1;

    hop = s.cfg.hop_size;                  /* never hard-code the hop */
    for (i = 0; i + hop <= n_samples; i += hop) {
        if (nr_stream_process(&s, pcm + i, out + i) != 0) {
            nr_stream_destroy(&s);
            return -1;
        }
    }

    nr_stream_destroy(&s);
    return 0;
}
```

### 1.2 呼叫順序

1. **建 config**：`mmse_lsa_config_for_mode()`（預設 grid）或
   `mmse_lsa_config_for_mode_grid()`（指定 grid）。要 stationary 就再套
   `mmse_lsa_apply_stationary()`。
2. **驗證**：`mmse_lsa_validate_config()`。這是唯一能在建構前知道 config 被拒絕的方式。
3. **建構**：`mmse_lsa_create()`（heap）或 `mmse_lsa_get_mem_size()` + `mmse_lsa_init()`
   （caller-owned memory）。同時自備 `FftHandle`。
4. **每個 hop**：analysis window → `fft_forward()` → `mmse_lsa_process()` →
   `fft_inverse()` → synthesis window → overlap-add。
5. **串流邊界**：`mmse_lsa_reset()`，並自行清掉呼叫端的 analysis / OLA buffer。
6. **結束**：`mmse_lsa_destroy()` + `fft_destroy()`。

尺寸一律從 config 或 query API 取得（`cfg.hop_size`、`mmse_lsa_get_n_freqs()`…），
**不要硬編任何 hop / n_freqs 常數**。

### 1.3 兩個永久行為契約

這兩點是這個 library 對使用者的長期承諾，不是版本花絮，整合時必須先接受。

**契約 A — 這是 streaming API，開頭的幾個 frame 一定沒有降噪效果。**

C library 只能往前走。初始化期間它會**直接 pass-through**（每個 bin 的 gain 恆為 `1.0`，
輸出與輸入逐 sample 相同），同時累積噪聲統計，累滿之後**一次性**完成噪聲估計初始化。
它**先天無法**像 offline/batch 實作那樣「回頭用最終的 noise PSD 重算前 N 個 frame」。

- pass-through 的長度就是 `config.num_init_frames` 個 frame；預設約 200 ms
  （各 grid 的實際 frame 數見 4.2 節）。
- 消費端必須預期開頭這段音訊實質上是未處理的；不要把它當成 bug，也不要用縮短
  `num_init_frames` 以外的方式去「修」它。
- 開頭這段最好是**只有背景噪聲、沒有目標語音**，否則初始噪聲估計會被語音污染。
- `mmse_lsa_is_initialized()` 會在初始化完成後回傳 `true`；在那之前輸出等同 bypass。

**契約 B — library 永遠不會自動 reset。**

每一次 `mmse_lsa_process()` / `mmse_lsa_process_gain()` 都是**接續既有狀態**繼續跑。
沒有任何輸入條件會讓它自己清空狀態。`mmse_lsa_reset()` 的所有權在呼叫端：

- 換一條新的音訊串流、換檔案、換裝置、場景切換、串流中斷後重連 —— 呼叫端**必須**自己呼叫
  `mmse_lsa_reset()`，否則新串流會沿用上一條串流的噪聲模型。
- reset 之後狀態回到全新的初始化階段：**接下來的 `num_init_frames` 個 frame 會再次
  pass-through**（契約 A 重新套用一次）。
- reset 只清 library 內部狀態，**不會**清呼叫端的 analysis frame 與 OLA buffer，那兩塊要自己清。

### 1.4 in-place 與 aliasing 規則

`mmse_lsa_process(self, spectrum_in, spectrum_out)`：

- `spectrum_out == spectrum_in`（**完全同一個指標**）是明確支援的 in-place 用法。
- `spectrum_out` 與 `spectrum_in` **完全不相交**也支援。
- 「部分重疊」的兩個不同指標**不支援**，不要這樣用。
- 兩個 buffer 都必須是 `n_freqs` 個 `Complex`。

注意這與 FFT 層的規則**相反**：`fft_forward()` / `fft_inverse()` 的輸入輸出帶 `restrict`，
**任何重疊都是未定義行為**（見第 6 節）。

### 1.5 static memory 路徑（caller-owned memory）

不需要任何編譯開關；heap 路徑與 static 路徑永遠同時存在於同一份 library，用哪一條取決於
你呼叫哪個函式。

```c
#include <stdint.h>
#include "fft_wrapper.h"
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

/* 實務上可換成 linker section 或平台自有的 memory pool；起始位址必須 16-byte 對齊。 */
static uint8_t nr_pool[64 * 1024]  __attribute__((aligned(16)));
static uint8_t fft_pool[16 * 1024] __attribute__((aligned(16)));

int create_static_nr(MmseLsaConfig *cfg,
                     MmseLsaDenoiser **nr, FftHandle **fft)
{
    size_t nr_need, fft_need;

    if (!cfg || !nr || !fft) return -1;
    *cfg = mmse_lsa_config_for_mode(16000, MMSE_LSA_NR_BALANCED);
    if (!mmse_lsa_validate_config(cfg)) return -1;

    nr_need  = mmse_lsa_get_mem_size(cfg);      /* 0 == config 被拒絕 */
    fft_need = fft_get_mem_size(cfg->fft_size); /* 0 == fft_size 被拒絕 */
    if (nr_need == 0 || fft_need == 0) return -1;
    if (nr_need > sizeof(nr_pool) || fft_need > sizeof(fft_pool)) return -1;

    *nr  = mmse_lsa_init(nr_pool,  sizeof(nr_pool),  cfg);
    *fft = fft_init(fft_pool, sizeof(fft_pool), cfg->fft_size);
    if (!*nr || !*fft) return -1;
    return 0;
}
```

規則：

- pool 起始位址**必須 16-byte 對齊**；未對齊時 `mmse_lsa_init()` / `fft_init()` 回傳 `NULL`
  （不會寫入你的 buffer）。
- `mem_size` 小於 `_get_mem_size()` 的需求時回傳 `NULL`。
- 需求量只跟 config 有關，可在啟動時算一次；**config 改了就要重新查詢**。
- 對 static instance 呼叫 `mmse_lsa_destroy()` 是真正的 no-op，呼叫幾次都安全；pool 的生命
  週期完全由呼叫端管理。
- window、OLA、PCM ring、application scratch **不包含**在 `mmse_lsa_get_mem_size()` 裡，要自己算。
- 上例中 pool 的大小是示範值。實際需求請用 4.2 節的量測表對照，並**在程式裡用
  `_get_mem_size()` 的回傳值檢查**，不要把數字寫死。

### 1.6 只要 gain、不要套用：`mmse_lsa_process_gain()`

當 NR 是串接鏈的一環（例如上游有其他抑制模組、下游還要再合併一次增益）時，用這支 API：
它照常更新內部狀態並算出 per-bin gain，但**不會**把 gain 套到頻譜上。

```c
#include "fft_wrapper.h"
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

/* gain_out 長度必須是 mmse_lsa_get_n_freqs(nr)；extra_noise_psd 可為 NULL。 */
int nr_gain_only(MmseLsaDenoiser *nr, const Complex *spectrum_in,
                 const float *extra_noise_psd, float *gain_out)
{
    return mmse_lsa_process_gain(nr, spectrum_in, extra_noise_psd, gain_out);
}
```

- `extra_noise_psd`：長度 `n_freqs` 的額外噪聲 PSD，**必須與 `|spectrum_in|²` 同一個線性尺度**。
  傳 `NULL` 時行為與純噪聲版本完全相同。
- `gain_out`：可傳 `NULL` 省掉一次複製，之後用 `mmse_lsa_get_gain()` 讀同一份結果。
- 回傳的 gain 是線性值，範圍 `[g_min, 1]`（`g_min` 由 `g_min_db` 決定）。
- 契約 A／B 同樣適用：初始化期間這支 API 一樣回傳全 `1.0` 的 gain，而且一樣不會自動 reset。

### 1.7 查詢與診斷 API

| 函式 | 用途 | 什麼時候呼叫 |
|---|---|---|
| `mmse_lsa_get_hop_size()` / `mmse_lsa_get_frame_size()` / `mmse_lsa_get_n_freqs()` | 取得實際尺寸 | 配置 buffer 時；避免硬編 |
| `mmse_lsa_get_latency()` | 頻域 core 本身的延遲 | 一律回 `0`；**不含**呼叫端 framing／OLA 的延遲，整體延遲要自己算 |
| `mmse_lsa_is_initialized()` | 初始化 pass-through 是否結束 | 想知道輸出何時開始真的有降噪時 |
| `mmse_lsa_get_spp()` / `mmse_lsa_get_noise_psd()` / `mmse_lsa_get_gain()` | 讀最近一個 frame 的 per-bin 陣列 | 除錯／視覺化 |
| `mmse_lsa_debug_status()` | 一次取得聚合狀態（見下） | 板上監看，建議每秒一次 |

`mmse_lsa_debug_status()` 填入 `MmseLsaDebugStatus`：`initialized`、`mean_gain_db`、
`min_gain_db`、`mean_spp`、`noise_floor_db`。它是唯讀的，不會擾動任何處理狀態；不呼叫就
完全沒有成本。

per-bin 查詢回傳的是 instance 內部的唯讀記憶體：**不要修改、不要 free**，並且要在下一次
`process` / `reset` / `destroy` 之前讀完或複製走。

執行緒：每個 instance 都有狀態，**同一個 instance 不可被多個 thread 同時呼叫**；不同
instance 之間不共用可變狀態，可各自在不同 thread 使用。多條串流請各建一個 instance。

---

## 2. 建置與連結

建置 archive（在 repo 根目錄執行）：

```bash
make -C c_impl lib                       # 預設 BACKEND=ne10：NEON backend（目標平台交付組合）
make -C c_impl BACKEND=kiss lib          # 可攜、逐位元可重現的參考 backend（顯式指定）
make -C c_impl                           # 加建 denoise_wav
make -C c_impl mem                       # 加建 denoise_mem（static memory 示範）
make -C c_impl debug                     # standard math、關閉最佳化開關
make -C c_impl WERROR=1                  # 對本 repo 原始碼開 -Werror
make -C c_impl EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"   # 較小的 MCRA 初始化記憶體
make -C c_impl clean
```

取得產出路徑：

```bash
make -s -C c_impl print-lib-path   # libmmse_lsa.a 的絕對路徑
make -s -C c_impl print-bin-dir    # 執行檔所在目錄
make -C c_impl publish             # 穩定的 dist/<backend>/current/ 交付路徑
```

驗證：

```bash
make -C c_impl test-config
make -C c_impl test-config-parity
```

連結你自己的程式（預設 NE10 backend 含 C++ TU，用 C++ driver 連結）：

```bash
c++ -std=gnu99 app.c \
   -Ic_impl/include -I../audio_common/include \
   $(make -s -C c_impl print-lib-path) \
   $(make -s -C ../audio_common print-lib-path) \
   -lm -o app
```

換成可攜、逐位元可重現的參考 backend 時，兩個 `print-lib-path` 都要帶 `BACKEND=kiss`；
KISS backend 純 C，可改回 `cc` driver 連結：

```bash
cc -std=gnu99 app.c \
   -Ic_impl/include -I../audio_common/include \
   $(make -s -C c_impl BACKEND=kiss print-lib-path) \
   $(make -s -C ../audio_common BACKEND=kiss print-lib-path) \
   -lm -o app
```

執行隨附的 wrapper 範例：

```bash
./denoise_wav noisy.wav clean.wav
./denoise_wav noisy.wav clean.wav --nr-mode mild
./denoise_wav noisy.wav clean.wav --nr-mode balanced --stationary
./denoise_wav noisy.wav clean.wav --fft-size 512      # 指定 grid，見 4.1 節
./denoise_wav input.wav copy.wav --bypass
./denoise_wav noisy.wav clean.wav --debug             # 每秒印一行狀態
```

---

## 3. 錯誤語意表

這份程式碼混用了數種回傳慣例，以下是**每支函式實際的**行為。

| 函式 | 成功時 | 失敗／邊界時 |
|---|---|---|
| `mmse_lsa_create(config)` | 回傳非 `NULL` handle | 回傳 `NULL`：`config == NULL`、config 未通過驗證、記憶體配置失敗 |
| `mmse_lsa_get_mem_size(config)` | 回傳需求 byte 數（> 0） | 回傳 **`0`**：`config == NULL`、config 未通過驗證、尺寸計算溢位 |
| `mmse_lsa_init(mem, mem_size, config)` | 回傳指向 `mem` 內部的 handle | 回傳 `NULL`：`mem == NULL`、`mem` 未 16-byte 對齊、`mem_size` 不足、config 未通過驗證 |
| `mmse_lsa_destroy(self)` | `void` | `self == NULL` 安靜跳過；static instance 為 no-op 且可重複呼叫；**heap instance 只能呼叫一次** |
| `mmse_lsa_process(...)` | 回傳 `0` | 回傳 `-1`：`self` / `spectrum_in` / `spectrum_out` 任一為 `NULL` |
| `mmse_lsa_process_gain(...)` | 回傳 `0` | 回傳 `-1`：`self` 或 `spectrum_in` 為 `NULL`。`extra_noise_psd` 與 `gain_out` 為 `NULL` 是合法用法，不是錯誤 |
| `mmse_lsa_reset(self)` | `void` | `self == NULL` **安靜 no-op**，沒有任何回報 |
| `mmse_lsa_get_hop_size()` / `get_frame_size()` / `get_n_freqs()` | 回傳正整數 | handle 為 `NULL` 時回傳 **`0`** |
| `mmse_lsa_get_latency()` | 一律回傳 `0` | handle 為 `NULL` 也回傳 `0`。`0` 是正常值，**不是**錯誤碼 |
| `mmse_lsa_is_initialized()` | `true` / `false` | handle 為 `NULL` 時回傳 `false` |
| `mmse_lsa_get_spp()` / `get_noise_psd()` / `get_gain()` | 回傳唯讀陣列指標，並在 `n_freqs != NULL` 時寫入長度 | handle 為 `NULL` 時回傳 `NULL` 並把 `*n_freqs` 設為 `0`。`n_freqs` 本身可以傳 `NULL` |
| `mmse_lsa_debug_status(self, out)` | `void`，填滿 `*out` | `out == NULL` 時**什麼都不做**；`self == NULL` 時把 `*out` **全部歸零**（不會寫入 NaN） |
| `mmse_lsa_validate_config(config)` | 回傳 `true` | 回傳 `false`：`config == NULL`，或任何欄位越界／為 NaN／為 Inf |
| `mmse_lsa_default_config()` / `_for_grid()` / `mmse_lsa_config_for_mode()` / `_for_mode_grid()` | 以值回傳 `MmseLsaConfig` | **沒有錯誤回傳值**。傳入不支援的 sample rate 時會產生一個 `fft_size == 0` 的無效 config，必須靠 `mmse_lsa_validate_config()` 才會發現 |
| `mmse_lsa_apply_stationary(config)` | `void`，就地修改 | **沒有 `NULL` 檢查**，傳 `NULL` 會直接解參考造成當機 |
| `mmse_lsa_default_fft_size(sample_rate)` | 回傳預設 FFT 尺寸 | 不支援的 sample rate 回傳 **`0`** |
| `mmse_lsa_retime_alpha()` / `_alpha_ref()` | 回傳換算後的係數 | 參數越界時**原封不動回傳輸入值**，不報錯 |
| `mmse_lsa_retime_frames()` / `_frames_ref()` | 回傳換算後的 frame 數 | 參數無效或結果溢位時回傳 **`0`** |

要點：

- **`mmse_lsa_validate_config()` 是呼叫端唯一能得知「config 為什麼被拒絕」的手段。**
  `create` / `init` / `get_mem_size` 三支都會在內部再驗一次，但它們只會回 `NULL` / `0`，
  無法區分是 config 不合法還是記憶體不足。請在建構前自己先驗一次。
- config constructor 全部沒有錯誤通道；「不支援的 sample rate」要到 validate 才會現形。
- 幾支 `void` 函式（`reset`、`destroy`、`debug_status`）在收到 `NULL` 時是安靜跳過的，
  不要用它們來偵測狀態。

---

## 4. Config 欄位參考

`MmseLsaConfig`（`c_impl/include/mmse_lsa_types.h`）共 27 個可設定欄位，以下全部列出。
「預設值」欄若標示為**依 grid 而定**，代表 constructor 會依實際 hop 換算，實測值見 4.2 節。

**通則**：instance 建立後，改動你手上那份 `MmseLsaConfig` 不會有任何效果（內部已經複製並
衍生出尺寸與狀態）。要換 sample rate、grid、`L` 或 `num_init_frames`，必須 destroy 後重建。

### 4.1 Grid 欄位（4 個）

| 欄位 | 意義 | 合法範圍 | 預設 |
|---|---|---|---|
| `sample_rate` | 取樣率 | 只接受 `8000` / `16000` / `48000` | 由 constructor 參數指定 |
| `fft_size` | 轉換長度 | 2 的次方、`<= 8192`，且必須與 `sample_rate` 組成下表的合法 grid | 見下表 |
| `frame_size` | analysis frame 長度 | **必須等於 `fft_size`**（不做 zero padding） | 等於 `fft_size` |
| `hop_size` | 每次前進的樣本數 | **必須等於 `frame_size / 2`**（固定 50% overlap） | `fft_size / 2` |

合法 grid（實測 `mmse_lsa_validate_config()`，其餘組合一律被拒）：

| sample_rate | fft_size = frame_size | hop_size | hop 長度 | n_freqs | 狀態 |
|---:|---:|---:|---:|---:|---|
| 8000 | 128 | 64 | 8.000 ms | 65 | 預設 |
| 8000 | 256 | 128 | 16.000 ms | 129 | 支援的替代 grid |
| 16000 | 256 | 128 | 8.000 ms | 129 | 預設 |
| 16000 | 512 | 256 | 16.000 ms | 257 | 支援的替代 grid |
| 48000 | 1024 | 512 | 10.667 ms | 513 | 唯一 grid |

要用替代 grid，改用 `mmse_lsa_config_for_mode_grid(sample_rate, fft_size, mode)`。
**何時改**：hop 越短延遲越低、每秒運算次數越多；hop 越長頻率解析度越好、延遲越高。
除此之外沒有理由動它。

### 4.2 依 grid 換算的預設值（實測）

以下為 `balanced` preset 在各 grid 上的實際值（由建置後執行程式印出，非手算）：

| 欄位 | 8k/128 | 8k/256 | 16k/256 | 16k/512 | 48k/1024 |
|---|---:|---:|---:|---:|---:|
| `alpha_xi` | 0.959166 | 0.920000 | 0.959166 | 0.920000 | 0.945929 |
| `alpha_s` | 0.959796 | 0.921208 | 0.959796 | 0.921208 | 0.946757 |
| `alpha_d` | 0.921954 | 0.850000 | 0.921954 | 0.850000 | 0.897317 |
| `alpha_p` | 0.275946 | 0.076146 | 0.275946 | 0.076146 | 0.179652 |
| `alpha_g` | 0.902789 | 0.815028 | 0.902789 | 0.815028 | 0.872532 |
| `alpha_attack` | 0.547723 | 0.300000 | 0.547723 | 0.300000 | 0.448140 |
| `alpha_decay` | 0.902789 | 0.815028 | 0.902789 | 0.815028 | 0.872532 |
| `L` | 64 | 32 | 64 | 32 | 48 |
| `num_init_frames` | 25 | 13 | 25 | 13 | 19 |
| `scene_change_min_frames` | 7 | 4 | 7 | 4 | 5 |

換算成時間後，各 grid 的 `L` 都是 512 ms、`num_init_frames` 為 200–208 ms、
`scene_change_min_frames` 為 53–64 ms。**不要把上表任何一個數字寫死在你的程式裡**，
需要時從 config 讀。

與 grid 無關的預設值（`balanced`）：`q = 0.5`、`xi_min_db = -20.0`、`delta_db = 10.0`、
`scene_change_threshold_db = 10.0`、`scene_change_blend = 0.5`、
`scene_change_flatness_threshold = 0.4`、`broadband_threshold = 1.0`、`g_min_db = -30.0`、
`stationary_floor = false`、`stationary_floor_exponent = 1.0`、`stationary_floor_beta = 1.0`、
`scene_change_tonal_veto = false`、`scene_change_lo_flatness_max = 0.4`。

記憶體需求（KISS backend，預設建置參數，實測 byte 數）：

| grid | `mmse_lsa_get_mem_size()` | 加上 `-DUSE_FAST_PERCENTILE` | `fft_get_mem_size()` |
|---|---:|---:|---:|
| 8k/128 | 29 760 | 23 104 | 4 688 |
| 8k/256 | 35 424 | 28 608 | 8 784 |
| 16k/256 | 58 176 | 45 120 | 8 784 |
| 16k/512 | 69 728 | 56 256 | 16 976 |
| 48k/1024 | 183 488 | 144 384 | 33 360 |

需求量同時受 `fft_size`、`L`、`num_init_frames` 與建置參數影響，上表僅供規劃 pool 大小時
估算；**正式程式一律以執行時的 `_get_mem_size()` 回傳值為準**。

### 4.3 SPP 參數（3 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `alpha_xi` | 訊噪比估計的時間平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：輸出更平滑，musical noise 更少，但語音起音較鈍。**調小**：反應更快，容易出現孤立的增益跳動。聽到零星「水聲／音樂噪聲」時先往上調 |
| `q` | 語音先驗機率 | 有限值，**開區間 `(0, 1)`**（`0` 與 `1` 都會被拒） | 0.5 | **調大**（趨近 mild）：更保守、更保語音。**調小**（趨近 aggressive）：抑噪更深、較容易傷語音 |
| `xi_min_db` | 訊噪比下限（dB） | 有限值，`[-80, 80]` | -20.0 | **調低**：殘留底噪更低（更安靜、更容易聽出處理痕跡）。**調高**：保留較多自然底噪。這是 stationary 模式下控制殘留噪聲深度的主要旋鈕 |

### 4.4 MCRA 噪聲估計參數（6 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `alpha_s` | 功率譜的時間平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：噪聲追蹤更穩、對瞬態不敏感。**調小**：反應快但估計抖動。一般不動 |
| `alpha_d` | 噪聲估計的更新慣性 | 有限值，`[0, 1]` | 依 grid | **調大**：噪聲估計更新更慢、更不容易吸收語音（stationary 模式即採此方向）。**調小**：噪聲底變化時追得更快，但較易把語音當成噪聲吃掉 |
| `alpha_p` | 語音存在指示的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：判定更穩定但反應慢。**調小**：反應快但抖。一般不動 |
| `L` | 最小值追蹤視窗長度（frame 數） | `1 ~ 320` | 依 grid（約 512 ms） | **調大**：不容易把持續語音誤當噪聲，但噪聲底上升時追得慢。**調小**：追得快但長句語音可能被當成噪聲。改這個欄位會改變記憶體需求 |
| `delta_db` | 語音判定門檻（dB） | 有限值，`[-80, 80]` | 10.0 | **調高**：更難判定為語音 → 噪聲估計更容易吸收訊號（抑噪深、傷語音風險高）。**調低**：更容易判定為語音 → 噪聲估計更保守 |
| `num_init_frames` | 初始化 pass-through 的 frame 數 | `1 ~ 200` | 依 grid（200–208 ms） | **調大**：初始噪聲估計更可靠，但開頭未處理的時間更長。**調小**：更快進入處理狀態，但初始估計較差。與契約 A 直接相關；改這個欄位會改變記憶體需求 |

### 4.5 場景變化偵測參數（5 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `scene_change_threshold_db` | 觸發場景變化判定的門檻（dB） | 有限值，`[-80, 80]` | 10.0 | **調低**：更容易判定為場景變化（噪聲底變化時追得快，但誤判也多）。**調高**：更保守 |
| `scene_change_min_frames` | 需連續成立幾個 frame 才確認 | `>= 0`（只檢查非負，無上限） | 依 grid（53–64 ms） | **調大**：只有持續的變化才算數，抗誤觸。**調小**：反應快但容易被瞬態誤觸 |
| `scene_change_blend` | 確認場景變化後，**保留**多少舊噪聲底（新噪聲底 = `blend ×` 舊值 + `(1 - blend) ×` 當前觀測值） | 有限值，`[0, 1]` | 0.5 | **調小**（趨近 0）：幾乎整個換成新場景的觀測值，切換快但誤判時風險高。**調大**（趨近 1）：幾乎不動，`1.0` 等同關閉這條路徑 |
| `scene_change_flatness_threshold` | 高頻頻譜平坦度門檻 | 有限值，`[0, 1]` | 0.4 | **調高**：只有很「像噪聲」的頻譜才會被當成場景變化，音樂／語音較不會誤觸。**調低**：較寬鬆 |
| `broadband_threshold` | 寬頻場景重置的啟用門檻 | 有限值，`[0, 1]`；**`1.0` 代表關閉** | 1.0（關閉） | 需要在寬頻噪聲突然出現後快速追上時，設成 `< 1.0`（越小越早介入）。不需要就維持 `1.0` |

### 4.6 增益參數（4 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `g_min_db` | 增益下限（**振幅** dB，`/20` 換算） | 有限值，`[-80, 80]` | -30.0 | **調低**：殘留噪聲更少、聽感更「乾淨」，但處理痕跡與語音損傷風險增加。**調高**：留更多底噪、語音更自然。這是控制抑噪深度最直接的旋鈕，也是四個 strength preset 的主要差異 |
| `alpha_g` | 增益平滑係數 | 有限值，`[0, 1]` | 依 grid | **在目前的 C 實作中這個欄位不影響輸出**（詳見下方註記）。要改變增益平滑請改 `alpha_attack` / `alpha_decay` |
| `alpha_attack` | 增益「上升」方向的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調小**：增益回升快，語音起音更清楚，但較容易讓噪聲短暫漏出。**調大**：起音較鈍但更平順 |
| `alpha_decay` | 增益「下降」方向的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：增益下降慢，musical noise 明顯減少，語音尾音拖長。**調小**：噪聲收得快但容易產生抖動 |

> **註記（實測）**：`alpha_g` 會被複製進 instance，但目前沒有任何運算使用它；實際的增益平滑
> 完全由 `alpha_attack` 與 `alpha_decay` 決定。各 preset 剛好把 `alpha_g` 與 `alpha_decay`
> 設成相同的值，所以只調 `alpha_g` 看起來「沒有作用」是正常的。想調平滑度請改
> `alpha_decay`（必要時連同 `alpha_attack`）。

### 4.7 內容保留（stationary）疊加參數（5 個）

這五個欄位是與 strength 正交的「內容保留」疊加層，預設全部關閉。正常情況下請整組交給
`mmse_lsa_apply_stationary()` 設定，不要單獨手動打開。

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `stationary_floor` | 是否啟用「只移除穩態噪聲底」的增益下限 | `bool`（不做範圍檢查） | `false` | 由 `mmse_lsa_apply_stationary()` 設為 `true` |
| `stationary_floor_exponent` | 上述下限的陡峭度 | 有限值，`[0.5, 8.0]` | 1.0（stationary 設為 2.0） | **調大**：抑噪更深、內容保留變少。**調小**：保留更多非穩態內容（音樂／瞬態） |
| `stationary_floor_beta` | 上述下限的偏移量 | 有限值，**`> 0` 且 `<= 16.0`** | 1.0 | **調大**：抑噪更深。**調小**：更保守。不確定就維持 1.0 |
| `scene_change_tonal_veto` | 低頻呈現音調性時，否決場景重置 | `bool`（不做範圍檢查） | `false`（stationary 設為 `true`） | 素材含音樂時開啟，可避免音樂被當成場景變化 |
| `scene_change_lo_flatness_max` | 低頻「算不算音調性」的平坦度門檻 | 有限值，`[0, 1]` | 0.4 | 只在 `scene_change_tonal_veto` 為 `true` 時有效。**調高**：更多素材被視為音調性 → 更常否決重置 |

### 4.8 hop 換算輔助函式

如果你在某個 grid 上手調出一組係數，想在另一個 grid 上得到相同的實際時間常數，用
`mmse_lsa_retime_alpha_ref(alpha, sample_rate, hop_size, ref_hop_seconds)`（平滑係數）與
`mmse_lsa_retime_frames_ref(frames, sample_rate, hop_size, ref_hop_seconds)`（frame 計數）；
`mmse_lsa_retime_alpha()` / `mmse_lsa_retime_frames()` 是 10 ms 參考 hop 的簡寫。
兩者在參數無效時**不會報錯**（見第 3 節），呼叫前請自行確認輸入。

---

## 5. 強度 preset 與調參順序

### 5.1 四個 strength preset

用 `mmse_lsa_config_for_mode(sample_rate, mode)` 取得。與 grid 無關的差異：

| Preset | `g_min_db` | `q` | `xi_min_db` | 適用方向 |
|---|---:|---:|---:|---|
| `MMSE_LSA_NR_MILD` | -20.0 | 0.60 | -15.0 | 最保守，優先保留語音細節 |
| `MMSE_LSA_NR_MODERATE` | -25.0 | 0.55 | -18.0 | mild 與 balanced 之間 |
| `MMSE_LSA_NR_BALANCED` | -30.0 | 0.50 | -20.0 | 預設，語音品質與抑噪平衡 |
| `MMSE_LSA_NR_AGGRESSIVE` | -40.0 | 0.35 | -25.0 | 抑噪最深，較可能犧牲語音細節 |

各 preset 另外會覆寫 `alpha_d` / `alpha_g` / `alpha_attack` / `alpha_decay`，實際值依 grid
換算。以預設的 16 kHz / 256 grid 為例（實測）：

| Preset | `alpha_d` | `alpha_g` | `alpha_attack` | `alpha_decay` |
|---|---:|---:|---:|---:|
| `mild` | 0.921954 | 0.959166 | 0.632456 | 0.959166 |
| `moderate` | 0.921954 | 0.959166 | 0.632456 | 0.959166 |
| `balanced` | 0.751759 | 0.902789 | 0.547723 | 0.902789 |
| `aggressive` | 0.707107 | 0.921954 | 0.387298 | 0.938083 |

（`mild` 與 `moderate` 只在 `g_min_db` / `q` / `xi_min_db` 上不同，平滑係數相同。）

### 5.2 stationary 內容保留模式

`mmse_lsa_apply_stationary(&config)` 是疊加在任一 strength preset 之上的**正交**模式，
用於「只削掉穩態噪聲底、盡量保留語音／音樂／瞬態」的素材。它不是第五種 strength preset。

它會就地修改（實測，16 kHz / 256 grid，套用於 `balanced` 之上）：

| 欄位 | 套用後 |
|---|---|
| `stationary_floor` | `true` |
| `stationary_floor_exponent` | 2.0 |
| `stationary_floor_beta` | 1.0 |
| `xi_min_db` | **-22.0（覆寫）** |
| `g_min_db` | **-30.0（覆寫）** |
| `alpha_xi` | 0.959166 |
| `alpha_d` | 0.974679（更慢的噪聲更新） |
| `scene_change_min_frames` | 60（約 480 ms） |
| `scene_change_flatness_threshold` | 0.6 |
| `scene_change_tonal_veto` | `true` |
| `scene_change_lo_flatness_max` | 0.4 |

> **注意（實測）**：`mmse_lsa_apply_stationary()` **會無條件覆寫 `g_min_db` 與 `xi_min_db`**。
> 因此 `mild + stationary`、`moderate + stationary`、`aggressive + stationary` 的
> `g_min_db` 全部都是 -30.0、`xi_min_db` 全部都是 -22.0；strength preset 只有在
> `q` 與四個平滑係數上還保有差異。若你要的是「mild 的增益下限 + stationary 行為」，
> 必須在呼叫 `mmse_lsa_apply_stationary()` **之後**自己把 `g_min_db` 改回去，
> 並重新跑一次 `mmse_lsa_validate_config()`。

呼叫順序固定為：先 `mmse_lsa_config_for_mode()`，再 `mmse_lsa_apply_stationary()`，
最後 `mmse_lsa_validate_config()`。

### 5.3 建議調參順序

由上而下，**一次只動一項**，每動一次就重新聽／重新量測：

1. **先選 strength preset**（`mild` / `moderate` / `balanced` / `aggressive`）。絕大多數需求
   到這一步就結束。
2. **素材含音樂或明顯瞬態** → 疊 `stationary`（注意 5.2 的覆寫行為）。
3. **深度還差一點** → 只動 `g_min_db`（整體殘留噪聲深度）與 `xi_min_db`（殘留底噪的自然度）。
4. **聽到 musical noise／增益抖動** → 提高 `alpha_decay`（必要時連 `alpha_attack`）。
   **不要改 `alpha_g`**，它在目前實作中不影響輸出（見 4.6）。
5. **場景切換追不上／誤觸太多** → 依序考慮 `scene_change_threshold_db`、
   `scene_change_min_frames`、`broadband_threshold`。
6. **最後**才碰 MCRA 核心（`alpha_s` / `alpha_d` / `alpha_p` / `L` / `delta_db`）。
   改 `L` 或 `num_init_frames` 會改變記憶體需求，static memory 整合要重新查詢 pool 大小。

### 5.4 常見症狀對照

| 症狀 | 先確認 | 建議動作 |
|---|---|---|
| 開頭完全沒有降噪 | 是否還在初始化期（`mmse_lsa_is_initialized()`） | 這是契約 A 的正常行為；確認開頭是純噪聲段 |
| 換檔案後沿用了上一檔的噪聲模型 | 是否呼叫了 `mmse_lsa_reset()` | 契約 B：串流邊界必須自己 reset，並清掉呼叫端的 analysis／OLA buffer |
| 語音變悶、細節掉光 | preset 太強、`g_min_db` 太低 | 改 `mild` / `moderate`，或把 `g_min_db` 調高 |
| Musical noise（零星水聲） | 增益變動太快 | 提高 `alpha_decay`；必要時提高 `alpha_xi` |
| 音樂／瞬態被吃掉 | 是否啟用 stationary | 疊 `stationary`；必要時降低 `stationary_floor_exponent` |
| 噪聲底改變後追不上 | 場景偵測太保守 | 降低 `scene_change_threshold_db` 或 `scene_change_min_frames`，或啟用 `broadband_threshold < 1.0` |
| 輸出有週期性音量起伏 | window／OLA 寫錯 | 確認 periodic sqrt-Hann、50% overlap、analysis 與 synthesis 乘同一個 window |
| 當機或頻譜越界 | buffer 長度與 `n_freqs` 不一致 | 尺寸一律由 config／query API 取得，不要硬編 |

本模組不處理 echo、殘響、風切，也不處理與目標語音高度重疊的其他語音／音樂；這些問題無法
靠調低 `g_min_db` 解決。

---

## 6. 依賴附錄：共用 FFT 層

`c_impl/include/mmse_lsa_denoiser.h` **直接 `#include "fft_wrapper.h"`**，這個 header 來自
`../audio_common/include/`。沒有它，NR 的 header 連編譯都過不了；`Complex` 型別、以及
per-hop 必須用到的 FFT，全部由這一層提供。

### 6.1 `Complex`

```c
typedef struct {
    float r;  /* 實部 */
    float i;  /* 虛部 */
} Complex;
```

`mmse_lsa_process()` 的輸入與輸出都是 `Complex[n_freqs]`，其中 `n_freqs == fft_size / 2 + 1`。

### 6.2 需要用到的函式

| 函式 | 用途 | 回傳語意 |
|---|---|---|
| `FftHandle* fft_create(int fft_size)` | 建立 FFT handle（heap） | 失敗回 `NULL`（`fft_size` 不合法或配置失敗） |
| `size_t fft_get_mem_size(int fft_size)` | 查詢 static memory 需求 | **`fft_size` 不合法時回 `0`** |
| `FftHandle* fft_init(void* mem, size_t mem_size, int fft_size)` | 用 caller 提供的記憶體建立 handle | 失敗回 `NULL`：`mem == NULL`、未 16-byte 對齊、`mem_size` 為 0 或不足、`fft_size` 不合法 |
| `void fft_destroy(FftHandle*)` | 釋放 | `NULL` 安全；`fft_init()` 建立的 handle 為真正的 no-op，可重複呼叫；`fft_create()` 建立的 handle **只能呼叫一次** |
| `void fft_forward(FftHandle*, const float* restrict time_in, Complex* restrict freq_out)` | 實數 → 複數頻譜 | `void`；任一參數為 `NULL` 時**安靜跳過**，沒有錯誤回報 |
| `void fft_inverse(FftHandle*, const Complex* restrict freq_in, float* restrict time_out)` | 複數頻譜 → 實數 | 同上。**已內含 1/N 正規化**，forward→inverse 往返為單位增益，因此 sqrt-Hann + 50% overlap 的 OLA 不需要任何額外縮放 |
| `int fft_get_n_freqs(const FftHandle*)` | 取得 `fft_size / 2 + 1` | handle 為 `NULL` 時回 `0` |

`time_in` / `time_out` 的長度為 `fft_size`；`freq_out` / `freq_in` 的長度為 `n_freqs`。

### 6.3 `fft_size` 限制：2 的次方，且落在 `[16, 8192]`

兩個 backend 都會拒絕範圍外的值，包含其他 2 的次方（實測：`8` → `fft_get_mem_size` 回 `0`；
`16384` → `0`；非 2 次方如 `300` → `0`；`16`、`8192` 則正常）。

出貨 grid 的實測需求量（KISS backend）：

| `fft_size` | `fft_get_mem_size()` |
|---:|---:|
| 128 | 4 688 |
| 256 | 8 784 |
| 512 | 16 976 |
| 1024 | 33 360 |

FFT 的 static memory 與 NR 的是**兩塊獨立的 pool**，各自查詢、各自 16-byte 對齊；
`mmse_lsa_get_mem_size()` **不包含** FFT 的需求。

### 6.4 non-aliasing（`restrict`）要求 —— 與 `mmse_lsa_process()` 相反

`fft_forward()` 與 `fft_inverse()` 的輸入與輸出指標都宣告為 `restrict`：

- **兩個 buffer 必須完全不重疊**。任何重疊（包含完全相同的指標）都是**未定義行為**。
- 需要「就地」語意時，請改用 `fft_forward_scratch()` / `fft_inverse_scratch()`：它們允許
  呼叫端的輸入 buffer 在回傳後內容變成未定義，適合傳入本來就要丟棄的 scratch buffer。

對照之下，`mmse_lsa_process()` **明確允許** `spectrum_out == spectrum_in` 的 in-place 呼叫
（見 1.4 節）。兩層的規則不同，不要互相套用：

| | 允許同一個指標 | 允許部分重疊 |
|---|---|---|
| `mmse_lsa_process()` | 是 | 否 |
| `fft_forward()` / `fft_inverse()` | 否 | 否 |

1.1 節的範例正是照這個規則寫的：FFT 的時域 buffer 與頻譜 buffer 始終是兩塊不同的記憶體，
而 `mmse_lsa_process()` 就地作用在頻譜 buffer 上。
