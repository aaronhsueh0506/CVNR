# NR C Library 使用手冊（繁體中文）

這份手冊寫給**使用這個 library 的整合者**：什麼時候呼叫哪個函式、每個參數怎麼設。
不談演算法推導、不談內部實作。所有數值都直接讀自現行原始碼（header 預設值、
`anr_validate_config()` 的檢查、config constructor），或由實際建置後執行程式量得。

原始碼位置一律以 repository 相對路徑表示（例如 `c_impl/include/anr.h`）。

---

- [NR C Library 使用手冊（繁體中文）](#nr-c-library-使用手冊繁體中文) <!-- split-toc -->
  - [0. 交付範圍與檔案清單](#0-交付範圍與檔案清單) <!-- split-toc -->
    - [0.1 這個 library 是什麼](#01-這個-library-是什麼) <!-- split-toc -->
    - [0.2 這個 library 不是什麼（scope boundary）](#02-這個-library-不是什麼scope-boundary) <!-- split-toc -->
    - [0.3 交付檔案](#03-交付檔案) <!-- split-toc -->
    - [0.4 內部子模組](#04-內部子模組) <!-- split-toc -->
  - [1. Quick start](c_user_manual_zh_TW_01_quick_start.md#1-quick-start) <!-- split-toc -->
    - [1.1 最短的可編譯整合](c_user_manual_zh_TW_01_quick_start.md#11-最短的可編譯整合) <!-- split-toc -->
    - [1.2 呼叫順序](c_user_manual_zh_TW_01_quick_start.md#12-呼叫順序) <!-- split-toc -->
    - [1.3 兩個永久行為契約](c_user_manual_zh_TW_01_quick_start.md#13-兩個永久行為契約) <!-- split-toc -->
    - [1.4 in-place 與 aliasing 規則](c_user_manual_zh_TW_01_quick_start.md#14-in-place-與-aliasing-規則) <!-- split-toc -->
    - [1.5 static memory 路徑（caller-owned memory）](c_user_manual_zh_TW_01_quick_start.md#15-static-memory-路徑caller-owned-memory) <!-- split-toc -->
    - [1.6 只要 gain、不要套用：`anr_process_gain()`](c_user_manual_zh_TW_01_quick_start.md#16-只要-gain不要套用anr_process_gain) <!-- split-toc -->
    - [1.7 查詢與診斷 API](c_user_manual_zh_TW_01_quick_start.md#17-查詢與診斷-api) <!-- split-toc -->
    - [1.8 執行期換強度：`anr_set_mode()` 與 `anr_reconfigure()`](c_user_manual_zh_TW_01_quick_start.md#18-執行期換強度anr_set_mode-與-anr_reconfigure) <!-- split-toc -->
  - [2. 建置與連結](#2-建置與連結) <!-- split-toc -->
  - [3. 錯誤語意表](#3-錯誤語意表) <!-- split-toc -->
  - [4. Config 欄位參考](c_user_manual_zh_TW_02_config_reference.md#4-config-欄位參考) <!-- split-toc -->
    - [4.1 Grid 欄位（4 個）](c_user_manual_zh_TW_02_config_reference.md#41-grid-欄位4-個) <!-- split-toc -->
    - [4.2 依 grid 換算的預設值（實測）](c_user_manual_zh_TW_02_config_reference.md#42-依-grid-換算的預設值實測) <!-- split-toc -->
    - [4.3 SPP 參數（3 個）](c_user_manual_zh_TW_02_config_reference.md#43-spp-參數3-個) <!-- split-toc -->
    - [4.4 MCRA 噪聲估計參數（6 個）](c_user_manual_zh_TW_02_config_reference.md#44-mcra-噪聲估計參數6-個) <!-- split-toc -->
    - [4.5 場景變化偵測參數（5 個）](c_user_manual_zh_TW_02_config_reference.md#45-場景變化偵測參數5-個) <!-- split-toc -->
    - [4.6 增益參數（4 個）](c_user_manual_zh_TW_02_config_reference.md#46-增益參數4-個) <!-- split-toc -->
    - [4.7 hop 換算輔助函式](c_user_manual_zh_TW_02_config_reference.md#47-hop-換算輔助函式) <!-- split-toc -->
    - [4.8 外部（可開放給第三方）與內部（存在但不建議開放）](c_user_manual_zh_TW_02_config_reference.md#48-外部可開放給第三方與內部存在但不建議開放) <!-- split-toc -->
  - [5. 強度 preset 與調參順序](#5-強度-preset-與調參順序) <!-- split-toc -->
    - [5.1 四個 strength preset](#51-四個-strength-preset) <!-- split-toc -->
    - [5.2 建議調參順序](#52-建議調參順序) <!-- split-toc -->
    - [5.3 常見症狀對照](#53-常見症狀對照) <!-- split-toc -->
  - [6. 依賴附錄：共用 FFT 層](#6-依賴附錄共用-fft-層) <!-- split-toc -->
    - [6.1 `Complex`](#61-complex) <!-- split-toc -->
    - [6.2 需要用到的函式](#62-需要用到的函式) <!-- split-toc -->
    - [6.3 `fft_size` 限制：2 的次方，且落在 `[16, 8192]`](#63-fft_size-限制2-的次方且落在-16-8192) <!-- split-toc -->
    - [6.4 non-aliasing（`restrict`）要求 —— 與 `anr_process()` 相反](#64-non-aliasingrestrict要求--與-anr_process-相反) <!-- split-toc -->
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
- Python tree 裡的其他 variant（`python/denoisers/v1_spectral_subtraction.py`、
  `python/denoisers/v2_wiener.py`、`python/denoisers/v3_spp_mmse.py`、`python/denoisers/v3_3_pmmse.py`）
  **是研究用程式碼，C 端沒有任何對應實作**。不要以為 C library 可以切到那些模式。
- `python/config/*.yaml`（`v1_config.yaml`、`v2_config.yaml`、`v3_2_config.yaml`、
  `v3_3_config.yaml`、`v3_config.yaml`）**只給 Python 用**。C library 不讀任何設定檔，
  它唯一的參數入口就是 `AnrConfig` 這個 struct。

### 0.3 交付檔案

需要 include 的 public header：

| 檔案 | 內容 | 是否要直接 include |
|---|---|---|
| `c_impl/include/anr.h` | 建構／處理／reset／查詢 API、`AnrDebugStatus` | 是 |
| `c_impl/include/anr_types.h` | `AnrConfig`、`AnrMode`、config constructor、`anr_validate_config()` | 是（`anr.h` 已自動含入） |
| `../audiolib/common/include/fft_wrapper.h` | `Complex`、`FftHandle`、`fft_*` | 是（`anr.h` 已自動含入，見第 6 節） |
| `../audiolib/common/utility/mem_align.h` | `ALIGN16` 等對齊巨集 | 否（`anr.h`/`anr_types.h` 本身不用到；library 內部實作（`anr.c`/`noise_estimator.c`/`spp_estimator.c`）直接 include；整合者只有自己要操作 `ALIGN16` 時才需要直接 include） |

連結需要的 archive：

| 檔案 | 內容 |
|---|---|
| `libanr.a` | denoiser + MCRA + SPP core（本 repo 建置產生） |
| `libaudio_common.a` | FFT backend 與 fast math（`../audiolib/common` 建置產生） |

`libanr.a` **不含** FFT，兩個 archive 必須一起連結。

隨附的執行檔（皆為示範／驗證用途，不是 library 的一部分）：

| 執行檔 | 用途 |
|---|---|
| `denoise_wav` | 完整的時域 wrapper 範例：讀 WAV → framing/FFT/NR/IFFT/OLA → 寫 WAV |
| `denoise_mem` | static memory 路徑（`_get_mem_size` + `_init`）示範 runner |
| `test_config_validation` | config 驗證與對齊防護的回歸測試（`make test-config`） |
| `test_config_parity` | 印出各 grid × strength 的正規 config（`make test-config-parity`） |
| 其他 `test_*` | `test-reconfigure`、`test-noise-restart`、`test-scene-change`、`test-shared-startup`、`test-api-cpp`、`test-bit-exact`；`make test`／`make test-full` 為彙總 |

`make publish` 產出的 release 內容為 `libanr.a` 與 `denoise_wav`；header 請直接從
source tree 取用。

### 0.4 內部子模組

`c_impl/include/noise_estimator.h` 與 `c_impl/include/spp_estimator.h`
是 denoiser 內部擁有的子模組介面，**整合者不應直接呼叫**（denoiser 會自行建立、驅動與釋放
它們）。

---

## 2. 建置與連結

建置 archive（在 repo 根目錄執行）：

```bash
make -C c_impl lib                       # NE10 FFT（NEON，目標平台交付組合）
make -C c_impl                           # 加建 denoise_wav
make -C c_impl mem                       # 加建 denoise_mem（static memory 示範）
make -C c_impl debug                     # standard math、關閉最佳化開關
make -C c_impl WERROR=1                  # 對本 repo 原始碼開 -Werror
make -C c_impl EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"   # 較小的 MCRA 初始化記憶體
make -C c_impl clean
```

取得產出路徑：

```bash
make -s -C c_impl print-lib-path   # libanr.a 的絕對路徑
make -s -C c_impl print-bin-dir    # 執行檔所在目錄
make -C c_impl publish             # 穩定的 dist/<backend>/current/ 交付路徑
```

驗證：

```bash
make -C c_impl test-config
make -C c_impl test          # 每次改動的驗證:C 測試、pytest(含 Python/C 設定對拍)、parity 子集
make -C c_impl test-full     # 另加兩種 SIMD 的 bit-exact、獨立 config dump 與全部 parity scenario
```

連結你自己的程式（NE10 含 C++ TU，用 C++ driver 連結）：

```bash
c++ -std=gnu99 app.c \
   -Ic_impl/include -I../audiolib/common/include \
   $(make -s -C c_impl print-lib-path) \
   $(make -s -C ../audiolib/common print-lib-path) \
   -lm -o app
```

執行隨附的 wrapper 範例：

```bash
./denoise_wav noisy.wav clean.wav
./denoise_wav noisy.wav clean.wav --nr-mode mild      # 或數字 0|1|2|3 = mild|moderate|balanced|aggressive
./denoise_wav noisy.wav clean.wav --fft-size 512      # 指定 grid，見 4.1 節
./denoise_wav input.wav copy.wav --bypass
./denoise_wav noisy.wav clean.wav --debug             # 每秒印一行狀態
```

---

## 3. 錯誤語意表

這份程式碼混用了數種回傳慣例，以下是**每支函式實際的**行為。

| 函式 | 成功時 | 失敗／邊界時 |
|---|---|---|
| `anr_create(config)` | 回傳非 `NULL` handle | 回傳 `NULL`：`config == NULL`、config 未通過驗證、記憶體配置失敗 |
| `anr_get_mem_size(config)` | 回傳需求 byte 數（> 0） | 回傳 **`0`**：`config == NULL`、config 未通過驗證、尺寸計算溢位 |
| `anr_init(mem, mem_size, config)` | 回傳指向 `mem` 內部的 handle | 回傳 `NULL`：`mem == NULL`、`mem` 未 16-byte 對齊、`mem_size` 不足、config 未通過驗證 |
| `anr_destroy(self)` | `void` | `self == NULL` 安靜跳過；static instance 為 no-op 且可重複呼叫；**heap instance 只能呼叫一次** |
| `anr_process(...)` | 回傳 `0` | 回傳 `-1`：`self` / `spectrum_in` / `spectrum_out` 任一為 `NULL` |
| `anr_process_gain(...)` | 回傳 `0` | 回傳 `-1`：`self` 或 `spectrum_in` 為 `NULL`。`extra_noise_psd` 與 `gain_out` 為 `NULL` 是合法用法，不是錯誤 |
| `anr_reset(self)` | `void` | `self == NULL` **安靜 no-op**，沒有任何回報 |
| `anr_set_mode(self, mode)` | 回傳 `0` | 回傳 `-1`：`self == NULL`、`mode` 超出 enum、組出的 config 被 `anr_reconfigure()` 拒絕；`-1` 時什麼都不寫 |
| `anr_reconfigure(self, target)` | 回傳 `0` | 回傳 `-1`：`self`／`target` 為 `NULL`、`target` 未通過驗證、六個幾何欄位任一與實例不同；`-1` 時什麼都不寫 |
| `anr_get_hop_size()` / `get_frame_size()` / `get_n_freqs()` | 回傳正整數 | handle 為 `NULL` 時回傳 **`0`** |
| `anr_is_initialized()` | `true` / `false` | handle 為 `NULL` 時回傳 `false` |
| `anr_get_speech_protect_frame_threshold()` | 回傳生效的幀級語音閘值 | handle 為 `NULL` 時回傳 `0.0` |
| `anr_get_noise_psd()` / `get_gain()` | 回傳唯讀陣列指標，並在 `n_freqs != NULL` 時寫入長度 | handle 為 `NULL` 時回傳 `NULL` 並把 `*n_freqs` 設為 `0`。`n_freqs` 本身可以傳 `NULL` |
| `anr_debug_status(self, out)` | `void`，填滿 `*out` | `out == NULL` 時**什麼都不做**；`self == NULL` 時把 `*out` **全部歸零**（不會寫入 NaN） |
| `anr_validate_config(config)` | 回傳 `true` | 回傳 `false`：`config == NULL`，或任何欄位越界／為 NaN／為 Inf |
| `anr_default_config()` / `_for_grid()` / `anr_config_for_mode()` / `_for_mode_grid()` | 以值回傳 `AnrConfig` | **沒有錯誤回傳值**。傳入不支援的 sample rate 時會產生一個 `fft_size == 0` 的無效 config，必須靠 `anr_validate_config()` 才會發現 |
| `anr_default_fft_size(sample_rate)` | 回傳預設 FFT 尺寸 | 不支援的 sample rate 回傳 **`0`** |
| `anr_retime_alpha()` / `_alpha_ref()` | 回傳換算後的係數 | 參數越界時**原封不動回傳輸入值**，不報錯 |
| `anr_retime_frames()` / `_frames_ms()` | 回傳換算後的 frame 數 | 參數無效或結果溢位時回傳 **`0`** |

要點：

- **`anr_validate_config()` 是呼叫端唯一能得知「config 為什麼被拒絕」的手段。**
  `create` / `init` / `get_mem_size` 三支都會在內部再驗一次，但它們只會回 `NULL` / `0`，
  無法區分是 config 不合法還是記憶體不足。請在建構前自己先驗一次。
- config constructor 全部沒有錯誤通道；「不支援的 sample rate」要到 validate 才會現形。
- 幾支 `void` 函式（`reset`、`destroy`、`debug_status`）在收到 `NULL` 時是安靜跳過的，
  不要用它們來偵測狀態。

---

## 5. 強度 preset 與調參順序

### 5.1 四個 strength preset

用 `anr_config_for_mode(sample_rate, mode)` 取得。與 grid 無關的差異：

| Preset | `g_min_db` | `q` | `xi_min_db` | `noise_over_subtraction` | 適用方向 |
|---|---:|---:|---:|---:|---|
| `ANR_MODE_MILD` | -20.0 | 0.58 | -10.0 | 1.2 | 最保守，優先保留語音細節 |
| `ANR_MODE_MODERATE` | -23.0 | 0.54 | -10.0 | 1.3 | mild 與 balanced 之間 |
| `ANR_MODE_BALANCED` | -25.0 | 0.52 | -10.0 | 1.4 | 預設，語音品質與抑噪平衡 |
| `ANR_MODE_AGGRESSIVE` | -28.0 | 0.45 | -12.0 | 1.3 | 抑噪最深，較可能犧牲語音細節 |

四個 preset 只覆寫上面四個深度欄位。DD、MCRA tracker、gain attack/decay 與低頻語音
guard 的**設定值**完全共用；以預設 16 kHz / 256 grid 為例，`alpha_d=0.921954`、
`alpha_g=alpha_decay=0.902789`、`alpha_attack=0.387298`。

唯一的例外是幀級語音閘 `speech_protect_frame_threshold`：設定值 `0.55` 著作於 balanced 的
`q = 0.52`，生效值為 `value + (q − 0.52)`，所以隨 preset 的 `q` 自動位移（mild 0.61、
moderate 0.57、balanced 0.55、aggressive 0.48）。理由是純噪聲幀的語音帶 SPP 平均值本來就
落在 `q`；若固定用 0.55，這道閘在 mild 會永遠開著、在 aggressive 會關掉一半。生效值可用
`anr_get_speech_protect_frame_threshold()` 讀回。

### 5.2 建議調參順序

由上而下，**一次只動一項**，每動一次就重新聽／重新量測：

1. **先選 strength preset**（`mild` / `moderate` / `balanced` / `aggressive`）。絕大多數需求
   到這一步就結束。
2. **深度還差一點** → 只動 `g_min_db`（整體殘留噪聲深度）與 `xi_min_db`（殘留底噪的自然度）。
3. **聽到 musical noise／增益抖動** → 提高 `alpha_decay`（必要時連 `alpha_attack`）。
   **不要改 `alpha_g`**，它在目前實作中不影響輸出（見 [4.6](c_user_manual_zh_TW_02_config_reference.md#46-增益參數4-個)）。
4. **場景切換追不上／誤觸太多** → 依序考慮 `scene_change_threshold_db`、
   `scene_change_min_frames`、`broadband_threshold`。
5. **最後**才碰 MCRA 核心（`alpha_s` / `alpha_d` / `alpha_p` / `L` / `delta_db`）。
   改 `L` 或 `num_init_frames` 會改變記憶體需求，static memory 整合要重新查詢 pool 大小。

### 5.3 常見症狀對照

| 症狀 | 先確認 | 建議動作 |
|---|---|---|
| 開頭完全沒有降噪 | 是否還在初始化期（`anr_is_initialized()`） | 這是契約 A 的正常行為；確認開頭是純噪聲段 |
| 換檔案後沿用了上一檔的噪聲模型 | 是否呼叫了 `anr_reset()` | 契約 B：串流邊界必須自己 reset，並清掉呼叫端的 analysis／OLA buffer |
| 語音變悶、細節掉光 | preset 太強、`g_min_db` 太低 | 改 `mild` / `moderate`，或把 `g_min_db` 調高 |
| Musical noise（零星水聲） | 增益變動太快 | 提高 `alpha_decay`；必要時提高 `alpha_xi` |
| 噪聲底改變後追不上 | 場景偵測太保守 | 降低 `scene_change_threshold_db` 或 `scene_change_min_frames`，或啟用 `broadband_threshold < 1.0` |
| 輸出有週期性音量起伏 | window／OLA 寫錯 | 確認 periodic sqrt-Hann、50% overlap、analysis 與 synthesis 乘同一個 window |
| 當機或頻譜越界 | buffer 長度與 `n_freqs` 不一致 | 尺寸一律由 config／query API 取得，不要硬編 |

本模組不處理 echo、殘響、風切，也不處理與目標語音高度重疊的其他語音／音樂；這些問題無法
靠調低 `g_min_db` 解決。

---

## 6. 依賴附錄：共用 FFT 層

`c_impl/include/anr.h` **直接 `#include "fft_wrapper.h"`**，這個 header 來自
`../audiolib/common/include/`。沒有它，NR 的 header 連編譯都過不了；`Complex` 型別、以及
per-hop 必須用到的 FFT，全部由這一層提供。

### 6.1 `Complex`

```c
typedef struct {
    float r;  /* 實部 */
    float i;  /* 虛部 */
} Complex;
```

`anr_process()` 的輸入與輸出都是 `Complex[n_freqs]`，其中 `n_freqs == fft_size / 2 + 1`。

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

FFT 會拒絕範圍外的值，包含其他 2 的次方（實測：`8` → `fft_get_mem_size` 回 `0`；
`16384` → `0`；非 2 次方如 `300` → `0`；`16`、`8192` 則正常）。

出貨 grid 的實測需求量（NE10）：

| `fft_size` | `fft_get_mem_size()` |
|---:|---:|
| 128 | 3 952 |
| 256 | 7 152 |
| 512 | 13 552 |
| 1024 | 26 352 |

FFT 的 static memory 與 NR 的是**兩塊獨立的 pool**，各自查詢、各自 16-byte 對齊；
`anr_get_mem_size()` **不包含** FFT 的需求。

### 6.4 non-aliasing（`restrict`）要求 —— 與 `anr_process()` 相反

`fft_forward()` 與 `fft_inverse()` 的輸入與輸出指標都宣告為 `restrict`：

- **兩個 buffer 必須完全不重疊**。任何重疊（包含完全相同的指標）都是**未定義行為**。
- 需要「就地」語意時，請改用 `fft_forward_scratch()` / `fft_inverse_scratch()`：它們允許
  呼叫端的輸入 buffer 在回傳後內容變成未定義，適合傳入本來就要丟棄的 scratch buffer。

對照之下，`anr_process()` **明確允許** `spectrum_out == spectrum_in` 的 in-place 呼叫
（見 [1.4 節](c_user_manual_zh_TW_01_quick_start.md#14-in-place-與-aliasing-規則)）。兩層的規則不同，不要互相套用：

| | 允許同一個指標 | 允許部分重疊 |
|---|---|---|
| `anr_process()` | 是 | 否 |
| `fft_forward()` / `fft_inverse()` | 否 | 否 |

[1.1 節](c_user_manual_zh_TW_01_quick_start.md#11-最短的可編譯整合)的範例正是照這個規則寫的：FFT 的時域 buffer 與頻譜 buffer 始終是兩塊不同的記憶體，
而 `anr_process()` 就地作用在頻譜 buffer 上。
