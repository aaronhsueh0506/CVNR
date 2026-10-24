[索引](c_user_manual_zh_TW.md) | [下一部分](c_user_manual_zh_TW_02_config_reference.md) <!-- split-nav -->
## 1. Quick start

### 1.1 最短的可編譯整合

以下整份程式碼可存成 `nr_stream.c`，以 `-std=gnu99 -Wall -Wextra -Werror` 直接編譯通過。
上層每次餵入一個 `hop_size` 的 float PCM block、取回同長度的輸出。

```c
/* nr_stream.c -- minimal streaming wrapper around the NR C library. */
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "fft_wrapper.h"          /* audiolib: Complex, FftHandle, fft_*  */
#include "anr.h"
#include "anr_types.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef struct {
    AnrConfig    cfg;
    AnrDenoiser *nr;
    FftHandle       *fft;
    float           *window;    /* [frame_size] sqrt(periodic Hann)          */
    float           *analysis;  /* [frame_size] rolling analysis frame       */
    float           *ola;       /* [frame_size] overlap-add accumulator      */
    float           *time_buf;  /* [fft_size]   FFT time-domain buffer       */
    Complex         *spectrum;  /* [fft_size/2 + 1]                          */
} NrStream;

void nr_stream_destroy(NrStream *s);

/* Returns 0 on success, -1 on failure (nothing is left allocated on -1). */
int nr_stream_init(NrStream *s, int sample_rate, AnrMode mode)
{
    int n, n_freqs;

    if (!s) return -1;
    memset(s, 0, sizeof(*s));

    /* 1. config: preset on the default grid for this sample rate. */
    s->cfg = anr_config_for_mode(sample_rate, mode);

    /* 2. validate before create (tells you the config itself was rejected). */
    if (!anr_validate_config(&s->cfg)) return -1;

    n_freqs     = s->cfg.fft_size / 2 + 1;
    s->window   = (float *)malloc((size_t)s->cfg.frame_size * sizeof(float));
    s->analysis = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->ola      = (float *)calloc((size_t)s->cfg.frame_size, sizeof(float));
    s->time_buf = (float *)calloc((size_t)s->cfg.fft_size,   sizeof(float));
    s->spectrum = (Complex *)malloc((size_t)n_freqs * sizeof(Complex));

    /* 3. create denoiser + FFT. */
    s->nr  = anr_create(&s->cfg);
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
    if (anr_process(s->nr, s->spectrum, s->spectrum) != 0)  /* in place */
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
    anr_reset(s->nr);
    memset(s->analysis, 0, (size_t)s->cfg.frame_size * sizeof(float));
    memset(s->ola,      0, (size_t)s->cfg.frame_size * sizeof(float));
}

void nr_stream_destroy(NrStream *s)
{
    if (!s) return;
    anr_destroy(s->nr);
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

    if (nr_stream_init(&s, 16000, ANR_MODE_BALANCED) != 0)
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

1. **建 config**：`anr_config_for_mode()`（預設 grid）或
   `anr_config_for_mode_grid()`（指定 grid）。
2. **驗證**：`anr_validate_config()`。這是唯一能在建構前知道 config 被拒絕的方式。
3. **建構**：`anr_create()`（heap）或 `anr_get_mem_size()` + `anr_init()`
   （caller-owned memory）。同時自備 `FftHandle`。
4. **每個 hop**：analysis window → `fft_forward()` → `anr_process()` →
   `fft_inverse()` → synthesis window → overlap-add。
5. **串流邊界**：`anr_reset()`，並自行清掉呼叫端的 analysis / OLA buffer。
6. **結束**：`anr_destroy()` + `fft_destroy()`。

尺寸一律從 config 或 query API 取得（`cfg.hop_size`、`anr_get_n_freqs()`…），
**不要硬編任何 hop / n_freqs 常數**。

**延遲**：NR 核心本身 0 延遲（增益同 hop 產出）。1.1 的 sqrt-Hann、50% overlap WOLA 為 1 個 hop：
以 1.1 的 `nr_stream.c` 送入單一脈衝，16 kHz/256 的輸出峰值比輸入晚 128 樣本（8 ms）。

**時序圖與外部／內部參數分類**：見 `docs/html/nr.html`（逐層時序圖）、
`docs/html/nr_c_api.html`（呼叫順序與錯誤語意）、`docs/html/nr_c_api_params.html`（外部／內部參數表與函式分級）。

### 1.3 兩個永久行為契約

這兩點是這個 library 對使用者的長期承諾，不是版本花絮，整合時必須先接受。

**契約 A — 這是 streaming API，開頭的幾個 frame 一定沒有降噪效果。**

C library 只能往前走。初始化期間它會**直接 pass-through**（每個 bin 的 gain 恆為 `1.0`，
輸出與輸入逐 sample 相同），同時累積噪聲統計，累滿之後**一次性**完成噪聲估計初始化。
它**先天無法**像 offline/batch 實作那樣「回頭用最終的 noise PSD 重算前 N 個 frame」。

- pass-through 的長度就是 `config.num_init_frames` 個**非全零** frame；預設約 200 ms
  （各 grid 的實際 frame 數見 [4.2 節](c_user_manual_zh_TW_02_config_reference.md#42-依-grid-換算的預設值實測)）。數位靜音 frame（所有 bin 功率恰為 0）回傳 0：初始化前 gain 為 `1.0` 且不計入這個數字；
  初始化後仍照常計算 gain（不會被強制為 `1.0`），只是不推進噪聲底追蹤。第 `num_init_frames` 次呼叫完成初始化，但那一次的 gain 仍是 `1.0`，下一個 frame 才開始抑制。
- 消費端必須預期開頭這段音訊實質上是未處理的；不要把它當成 bug，也不要用縮短
  `num_init_frames` 以外的方式去「修」它。
- 開頭這段最好是**只有背景噪聲、沒有目標語音**，否則初始噪聲估計會被語音污染。
- `anr_is_initialized()` 會在初始化完成後回傳 `true`；在那之前輸出等同 bypass。

**契約 B — library 永遠不會自動 reset。**

每一次 `anr_process()` / `anr_process_gain()` 都是**接續既有狀態**繼續跑。
沒有任何輸入條件會讓它自己清空狀態。`anr_reset()` 的所有權在呼叫端：

- 換一條新的音訊串流、換檔案、換裝置、場景切換、串流中斷後重連 —— 呼叫端**必須**自己呼叫
  `anr_reset()`，否則新串流會沿用上一條串流的噪聲模型。
- reset 之後狀態回到全新的初始化階段：**接下來的 `num_init_frames` 個 frame 會再次
  pass-through**（契約 A 重新套用一次）。
- reset 只清 library 內部狀態，**不會**清呼叫端的 analysis frame 與 OLA buffer，那兩塊要自己清。

### 1.4 in-place 與 aliasing 規則

`anr_process(self, spectrum_in, spectrum_out)`：

- `spectrum_out == spectrum_in`（**完全同一個指標**）是明確支援的 in-place 用法。
- `spectrum_out` 與 `spectrum_in` **完全不相交**也支援。
- 「部分重疊」的兩個不同指標**不支援**，不要這樣用。
- 兩個 buffer 都必須是 `n_freqs` 個 `Complex`。

注意這與 FFT 層的規則**相反**：`fft_forward()` / `fft_inverse()` 的輸入輸出帶 `restrict`，
**任何重疊都是未定義行為**（見[第 6 節](c_user_manual_zh_TW.md#6-依賴附錄共用-fft-層)）。

### 1.5 static memory 路徑（caller-owned memory）

不需要任何編譯開關；heap 路徑與 static 路徑永遠同時存在於同一份 library，用哪一條取決於
你呼叫哪個函式。

```c
#include <stdint.h>
#include "fft_wrapper.h"
#include "anr.h"
#include "anr_types.h"

/* 實務上可換成 linker section 或平台自有的 memory pool；起始位址必須 16-byte 對齊。 */
static uint8_t nr_pool[64 * 1024]  __attribute__((aligned(16)));
static uint8_t fft_pool[16 * 1024] __attribute__((aligned(16)));

int create_static_nr(AnrConfig *cfg,
                     AnrDenoiser **nr, FftHandle **fft)
{
    size_t nr_need, fft_need;

    if (!cfg || !nr || !fft) return -1;
    *cfg = anr_config_for_mode(16000, ANR_MODE_BALANCED);
    if (!anr_validate_config(cfg)) return -1;

    nr_need  = anr_get_mem_size(cfg);      /* 0 == config 被拒絕 */
    fft_need = fft_get_mem_size(cfg->fft_size); /* 0 == fft_size 被拒絕 */
    if (nr_need == 0 || fft_need == 0) return -1;
    if (nr_need > sizeof(nr_pool) || fft_need > sizeof(fft_pool)) return -1;

    *nr  = anr_init(nr_pool,  sizeof(nr_pool),  cfg);
    *fft = fft_init(fft_pool, sizeof(fft_pool), cfg->fft_size);
    if (!*nr || !*fft) return -1;
    return 0;
}
```

規則：

- pool 起始位址**必須 16-byte 對齊**；未對齊時 `anr_init()` / `fft_init()` 回傳 `NULL`
  （不會寫入你的 buffer）。
- `mem_size` 小於 `_get_mem_size()` 的需求時回傳 `NULL`。
- 需求量只跟 config 有關，可在啟動時算一次；**config 改了就要重新查詢**。
- 對 static instance 呼叫 `anr_destroy()` 是真正的 no-op，呼叫幾次都安全；pool 的生命
  週期完全由呼叫端管理。
- window、OLA、PCM ring、application scratch **不包含**在 `anr_get_mem_size()` 裡，要自己算。
- 上例中 pool 的大小是示範值。實際需求請用 [4.2 節](c_user_manual_zh_TW_02_config_reference.md#42-依-grid-換算的預設值實測)的量測表對照，並**在程式裡用
  `_get_mem_size()` 的回傳值檢查**，不要把數字寫死。

### 1.6 只要 gain、不要套用：`anr_process_gain()`

當 NR 是串接鏈的一環（例如上游有其他抑制模組、下游還要再合併一次增益）時，用這支 API：
它照常更新內部狀態並算出 per-bin gain，但**不會**把 gain 套到頻譜上。

```c
#include "fft_wrapper.h"
#include "anr.h"
#include "anr_types.h"

/* gain_out 長度必須是 anr_get_n_freqs(nr)；extra_noise_psd 可為 NULL。 */
int nr_gain_only(AnrDenoiser *nr, const Complex *spectrum_in,
                 const float *extra_noise_psd, float *gain_out)
{
    return anr_process_gain(nr, spectrum_in, extra_noise_psd, gain_out);
}
```

- `extra_noise_psd`：長度 `n_freqs` 的額外噪聲 PSD，**必須與 `|spectrum_in|²` 同一個線性尺度**。
  傳 `NULL` 時行為與純噪聲版本完全相同。
- `gain_out`：可傳 `NULL` 省掉一次複製，之後用 `anr_get_gain()` 讀同一份結果。
- 回傳的 gain 是線性值，範圍 `[g_min, 1]`（`g_min` 由 `g_min_db` 決定）。
- 契約 A／B 同樣適用：初始化期間這支 API 一樣回傳全 `1.0` 的 gain，而且一樣不會自動 reset。

### 1.7 查詢與診斷 API

| 函式 | 用途 | 什麼時候呼叫 |
|---|---|---|
| `anr_get_hop_size()` / `anr_get_frame_size()` / `anr_get_n_freqs()` | 取得實際尺寸 | 配置 buffer 時；避免硬編 |
| `anr_is_initialized()` | 初始化 pass-through 是否結束 | 想知道輸出何時開始真的有降噪時 |
| `anr_get_noise_psd()` / `anr_get_gain()` | 讀最近一個 frame 的 per-bin 陣列 | 除錯／視覺化 |
| `anr_get_speech_protect_frame_threshold()` | 幀級語音閘的生效值（`value + (q − 0.52)`，隨 `anr_reconfigure()` 更新） | 確認 preset 切換後的閘門值 |
| `anr_debug_status()` | 一次取得聚合狀態（見下） | 板上監看，建議每秒一次 |

`anr_debug_status()` 填入 `AnrDebugStatus`：`initialized`、`mean_gain_db`、
`min_gain_db`、`mean_spp`、`noise_floor_db`。它是唯讀的，不會擾動任何處理狀態；不呼叫就
完全沒有成本。

per-bin 查詢回傳的是 instance 內部的唯讀記憶體：**不要修改、不要 free**，並且要在下一次
`process` / `reset` / `destroy` 之前讀完或複製走。

執行緒：每個 instance 都有狀態，**同一個 instance 不可被多個 thread 同時呼叫**；不同
instance 之間不共用可變狀態，可各自在不同 thread 使用。多條串流請各建一個 instance。

### 1.8 執行期換強度：`anr_set_mode()` 與 `anr_reconfigure()`

```c
int anr_reconfigure(AnrDenoiser *self, const AnrConfig *target);
int anr_set_mode(AnrDenoiser *self, AnrMode mode);
```

在 running instance 上換調參欄位，不重建、不重新配置記憶體。回 `0`，或 `-1`（`self`／`target` 為 NULL、
`target` 未通過 `anr_validate_config()`、`mode` 超出 enum、六個幾何欄位任一不符）；`-1` 時**什麼都不寫**。

- **幾何必須相同**：`sample_rate`／`frame_size`／`hop_size`／`fft_size`／`L`／`num_init_frames` 必須等於實例當下的值。
- **狀態刻意保留**：噪聲底、最小值追蹤環與其 scene-change 計數、SPP 先驗 SNR 歷史、增益平滑歷史全部繼續跑。換強度不是重啟；要重啟用 `anr_reset()`。
- **`anr_reconfigure()` 逐字採用 `target`**，不查 preset、不疊覆寫：自己疊了覆寫的呼叫端要重組整份組態。
- **`anr_set_mode()`** 以實例的 grid 組出 canonical 組態（`L` 為函式庫預設）後交給 `anr_reconfigure()`：
  只適用於組態等於 canonical preset 的實例。對疊了覆寫的實例，非 pool 欄位的覆寫會被悄悄還原，
  覆寫 `L` 或 `num_init_frames` 則被拒絕（回 `-1`）。
- 在兩個 hop 之間呼叫，與處理序列化；**非 thread-safe**。
- 改 `cross_band_*` 欄位會重置跨頻先驗狀態；改 `speech_aware_noise_tracking`／`noise_gate_*`／`makeup_*` 會重置共用 frame 狀態。

```c
if (anr_set_mode(nr, ANR_MODE_AGGRESSIVE) != 0) { /* mode 無效或被拒 */ }

AnrConfig t = anr_config_for_mode_grid(sr, fft_size, ANR_MODE_AGGRESSIVE);
t.noise_over_subtraction = 1.2f;                  /* 範例覆寫，每次都要重新疊上去 */
if (anr_reconfigure(nr, &t) != 0) { /* 幾何不符或 t 無效 */ }
```

函式庫沒有 `anr_get_config()`：要「只改一個旋鈕」，必須自己持有一份目前的 `AnrConfig`。
回歸測試：`make -C c_impl test-reconfigure`（`c_impl/test/test_reconfigure.c`）。

---

[索引](c_user_manual_zh_TW.md) | [下一部分](c_user_manual_zh_TW_02_config_reference.md) <!-- split-nav -->
