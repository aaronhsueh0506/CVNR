# Changelog

所有重要的改動都會記錄在此文件中。

## [v1.12.2] - 2026-07-13 · 移除 `USE_FAST_RECIPROCAL` 編譯開關

> 承 v1.12.1。`feature/static-memory` 分支。

### 變更

- **移除 `USE_FAST_RECIPROCAL` 編譯開關**：v1.12.1 引入時的 12-file PESQ
  把關數據已證實此旗標在嵌入式目標上安全（mean ΔPESQ **−0.0005**、worst
  **−0.0033**，car_15dB，見上一版本紀錄），但專案決定維持**單一** bit-exact
  IEEE 除法路徑，不保留第二條近似路徑。移除範圍：
  - `src/spp_estimator.c`（`spp_estimate`/`spp_estimate_ex` 兩個函式，共 8 處
    `#ifdef USE_FAST_RECIPROCAL` / `#else` / `#endif` 三明治）、
    `src/mmse_lsa_denoiser.c`（`calculate_gain` 的 `xi_ratio` 重建，1 處）、
    `src/mcra_noise_estimator.c`（`mcra_update` Loop C1 的 `ratio`，1 處）：
    刪除 `#ifdef`/`#else` 兩段落，只保留原本 `#else` 分支的標準除法碼，變成
    無條件執行；不留旗標殘跡。
  - `Makefile`：刪除旗標說明文件區塊（約 10 行）與 `help` target 的兩行
    （build-configuration 範例 + flags 說明）。
  - `README.md`：release 標頭行更新為本版本；「手動啟用」旗標表移除
    `USE_FAST_RECIPROCAL` 那一列。
  - `audio_common/include/fast_math.h`：`fast_recip`/`fast_div` 一併移除
    （標準數學 fallback 區塊 + IEEE bit-trick/Newton-Raphson 實作區塊 +
    檔頭文件條目）——這兩個函式的唯一消費者就是本旗標。全 repo consumer 掃描
    （AEC/NR/Audio_ALG/audio_common 的 `.c`/`.h`/Makefile）僅剩一處文字殘留：
    `Audio_ALG/lib/nr` git submodule 快照仍 pin 在 `f573f48`（本次移除前的
    tip；guarded call site 預設不編譯，非活的 consumer），該 pin 於同一批
    整合改動中前推，之後即無任何殘留。
- **驗證**：`make clean && make && make mem`，`bin/denoise_wav`
  （mild/moderate/balanced/aggressive 4 個 preset + `--stationary`）與
  `bin/denoise_mem`（預設設定）全部跟移除前建置的參考輸出 **byte-for-byte
  相同**（`cmp` 逐一核對）；`audio_common` 移除 `fast_recip`/`fast_div` 後
  （純刪除未使用的 inline 函式，未觸碰任何既有函式簽名）`libaudio_common.a`
  重新 `make clean && make`（kiss + ne10 兩個 backend），NR 端全部設定重跑，
  仍 byte-for-byte 相同。

## [v1.12.1] - 2026-07-13 · `USE_FAST_RECIPROCAL`（預設關）+ 兩個 bit-exact 迴圈合併（預設開）

> 承 v1.12.0。`feature/static-memory` 分支。效能 review 的兩個已核准項目。

### 變更

- **`audio_common/include/fast_math.h` 新增 `fast_recip(x)` / `fast_div(a,b)`**：
  跟既有 `fast_sqrt` 同款式——IEEE 754 bit-trick 種子（magic constant
  `0x7EF477D5`）+ 2 次 Newton-Raphson（`y = y*(2 - x*y)`）。`USE_STANDARD_MATH`
  分支下對應為 `1.0f/x` / `a/b`（除錯用，精確）。實測相對誤差：典型
  ~4e-6（如 x=1.0 時 4.05e-6），對 1e-12~1e12 的寬動態範圍掃描最壞 case
  ~1.2e-5（該範圍已涵蓋本模組實際會用到的 PSD / SNR-ratio 量級）。純標頭新增，
  無任何既有函式簽名變動。
- **NR `USE_FAST_RECIPROCAL`（新編譯開關，預設關）**：把 SPP/Gain/MCRA 熱路徑上
  幾個逐頻點 IEEE 除法換成 `fast_recip`：
  - `spp_estimator.c`：`spp_estimate`/`spp_estimate_ex` 的 `gamma = Y_psd/(noise+eps)`、
    `xi_dd_term1 = enhanced/(noise_dd+eps)`、`v = xi/(1+xi)*gamma`（對 `1+xi` 取一次
    recip）、`spp = 1/(1+prior*...)`（取一次 recip）。
  - `mmse_lsa_denoiser.c` `calculate_gain`：`USE_SHARED_XI_RATIO` 的 `v_in` 重建
    `xi_ratio = v/(gamma+eps)`。
  - `mcra_noise_estimator.c` `mcra_update` Loop C1：`ratio = S/(S_min*delta+eps)`。
  - 所有 epsilon guard（`+1e-10f` 等）在 recip 形式下維持不變（`fast_recip(x+eps)`，
    不是 `fast_recip(x)+eps`）。關閉時（預設）程式碼路徑逐字不變，僅新增
    `#else` 分支，不影響任何既有輸出。
  - **驗證**：關閉旗標（預設）→ `bin/denoise_wav` + `bin/denoise_mem`，4 個
    preset + stationary，跟本次改動前建置的參考輸出 **byte-for-byte 相同**。
    開啟旗標（`EXTRA_CFLAGS="-DUSE_FAST_RECIPROCAL"`）→ 可正常編譯執行，
    16-bit PCM 樣本最大絕對差：mild 17、moderate 12、balanced 24、
    aggressive 33、stationary 12（滿幅 32768 的 ~0.1%，聽感無感知差異預期）。
  - **本機 arm64 (Apple Silicon) 計時**（200× 串接的 test_wav，balanced
    preset，user time 均值）：關閉旗標 ~2.43s、開啟旗標 ~2.55s——在這顆桌機上
    **變慢 ~5%**（硬體 FDIV 在 Apple Silicon 上已經很快且是流水線化的，
    Newton-Raphson 近似的總指令數反而更多）。這與設計預期一致——本旗標的
    真正效益在 FDIV 慢/沒有硬體除法器的嵌入式核心上，不是本開發機；此處計時
    僅供參考存證，不代表目標硬體上的行為。
- **兩個 bit-exact 迴圈合併（無旗標，永遠開啟，byte-for-byte 相同）**：
  1. `mmse_lsa_process`：原本「`memcpy(spectrum_out, spectrum_in)` 再
     `fft_apply_gain(spectrum_out, gain)`」兩步，改成 out-of-place 時直接
     `out[k] = in[k] * gain[k]`（in-place 時——`spectrum_out == spectrum_in`
     ——仍呼叫原本的 `fft_apply_gain`，行為不變）。少寫一次 `spectrum_out`。
  2. DD-state 更新（`gain_prev[k]=g; enhanced_psd_prev[k]=g*g*power[k]`）原本
     是 `mmse_lsa_process`/`mmse_lsa_process_gain` 各自一個獨立的 post-loop
     k-迴圈；現在摺進 `calculate_gain` 自己的 k-迴圈尾端（該迴圈計算完
     `gain_out[k]` 之後，`power[k]` 全程未變，讀後寫沒有 hazard），以及兩個
     函式各自的 init pass-through 迴圈（`gain[k]=1.0f` 時，`gain_prev[k]=1.0f`、
     `enhanced_psd_prev[k]=power[k]`，浮點上跟 `1*1*power` 逐位元相同）。
     原本獨立的 step-3 迴圈整個刪除。
  - **驗證**：兩個合併**個別**驗證 byte-for-byte 相同（先驗第 1 個，通過後再
    加第 2 個，兩者疊加後再驗一次全部通過）——`bin/denoise_wav` +
    `bin/denoise_mem`，4 個 preset + stationary，皆跟本次改動前的參考輸出一致。

### 品質抽樣（開旗標的把關數據，12-file guard: babble/car/street × 0/5/10/15 dB, PESQ-wb/STOI vs clean）

- `USE_FAST_RECIPROCAL` ON vs OFF（C binary, balanced）：**mean ΔPESQ −0.0005，worst −0.0033
  （car_15dB），ΔSTOI ≤ 5e-5** — 感知上等同零損失，嵌入式目標上可直接啟用。

### 驗證總結

- 預設建置（無 `EXTRA_CFLAGS`）：`bin/denoise_wav` + `bin/denoise_mem`（BACKEND=kiss），
  4 個 preset（mild/moderate/balanced/aggressive）+ balanced+stationary，
  **byte-for-byte 相同**於本次改動前建置的參考輸出（sha256 逐一核對）。
- `make debug`、`make parity`（fast-math 與 `-DUSE_STANDARD_MATH` 兩種）、
  `EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"`、`-DUSE_FAST_PERCENTILE -DUSE_FAST_RECIPROCAL`
  組合皆編譯乾淨（`-Wall -Wextra`，零警告）。
- 對本次改動的四個檔案（`Makefile`、`spp_estimator.c`、`mmse_lsa_denoiser.c`、
  `mcra_noise_estimator.c`）grep 掃描：不含任何平台廠商名稱，皆為空。

## [v1.12.0] - 2026-07-13 · 靜態記憶體 API 改名（AEC 慣例）+ 改吃共用 `audio_common`

> 承 v1.11.1。`feature/static-memory` 分支。純改名/重接線，演算法邏輯不變——KISS backend
> 逐位元對照重構前輸出（4 preset + stationary）**byte-for-byte 相同**；static==malloc 在
> KISS 與 NE10 兩個 backend 上分別驗證 byte-for-byte 相同（backend 之間本來就不逐位元相同，
> 屬預期，不互相比較）。

### 變更

- **靜態記憶體 API 改名，對齊 `SE/AEC` 的 `aec_get_mem_size`/`aec_init` 慣例**：
  - `mmse_lsa_query_memsize(cfg)` → `mmse_lsa_get_mem_size(cfg)`；
    `mmse_lsa_create(cfg, mem, size)` → `mmse_lsa_init(mem, size, cfg)`
    （**參數順序改變**：`mem, size` 放前面，設定值放後面，跟 `aec_init(void*, size_t, const AecConfig*)`
    一致）。
  - `mcra_query_memsize(n_freqs, cfg)` → `mcra_get_mem_size(n_freqs, cfg)`；
    `mcra_create(n_freqs, cfg, mem, size)` → `mcra_init(mem, size, n_freqs, cfg)`。
  - `spp_query_memsize(n_freqs)` → `spp_get_mem_size(n_freqs)`；
    `spp_create(n_freqs, cfg, mem, size)` → `spp_init(mem, size, n_freqs, cfg)`。
  - `fft_query_memsize`/`fft_create(size, mem, size)` → `fft_get_mem_size`/`fft_init(mem, size, size)`
    （現由 `audio_common` 提供，見下）。
- **拿掉 `#ifdef USE_EXT_MEM` 編譯期二選一**：malloc 路徑（`_create`）與靜態記憶體路徑
  （`_get_mem_size`/`_init`）現在**永遠都編譯進同一份 object**，用哪條純粹是 runtime 選擇。
  每個 handle（`MmseLsaDenoiser`/`McraNoiseEstimator`/`SppEstimator`）內部加一個 runtime
  `is_static` bool：`_create()` 設 0（heap，擁有自己配的每一塊 buffer）、`_init()` 設 1（靜態，
  buffer 全部活在呼叫端的 pool 裡）。`_destroy()` 開頭 `if (!self) return;`，接著
  `if (self->is_static) return;`（靜態 instance 不釋放任何東西——denoiser 本身沒有內部持有
  FFT handle 之類「該 library 自己該釋放」的資源，已用 grep 覆核），否則走原本的 heap free 序列。
  `_get_mem_size()`/`_init()` 的 bump-allocate 佈局、對齊、每個 `create(...)` 開頭的
  `memset(mem, 0, get_mem_size(...))` 全部維持不變（純改名，非重新設計）。
- **對齊 helper 改用 `audio_common` 的 `ALIGN16(x)`**：刪除 `include/nr_ext_mem.h`
  （`nr_aligned_size()`），所有呼叫點改用 `fft_wrapper.h`（現由 audio_common 提供）的
  `ALIGN16` 巨集——同樣 16-byte 語意，byte-for-byte 相容。
- **改吃共用的 `../audio_common` 層**：刪除本 repo 自帶的 `src/fft_wrapper.c`、
  `src/fft_wrapper_ne10.c`、`include/fft_wrapper.h`、`include/fast_math.h`、`lib/kiss_fft/`。
  `Makefile` 新增 `AC_DIR`（自動找 `../../audio_common` 或
  `../../../../audio_common`，涵蓋被當 git submodule 多一層目錄消費的情況）、
  `BACKEND ?= kiss`（`make BACKEND=ne10` 才是這條分支真正要交付的嵌入式 backend；KISS
  留做預設是因為它是 bit-reproducible 的參考建置 + Python↔C parity backend，讓既有的
  parity/bit-exact gate 不需要額外傳參數就維持決定性）、一個 order-only 的 `ac_lib` 目標
  （每次連結前先跑 `$(MAKE) -C $(AC_DIR) BACKEND=$(BACKEND) lib`，由 audio_common 自己的
  Makefile 決定要不要重建）。`make mem` 拿掉 `-DUSE_EXT_MEM`（已不存在），改成跟 `denoise_wav`
  共用同一份 object 檔（single-compile 仍保留，只是不再需要靠它避免旗標混用）。
- **`example/main_mem.c`**：呼叫點改用新 API；修掉一個潛在的 OLA 緩衝溢位——`g_out_ola` 原本
  宣告 `[MAX_SAMPLES]`，但 OLA 寫入可以到 `out_len - 1`（`out_len` 是「最後一幀的 hop 邊界」，可比
  `n_samples` 多到 `HOP - 1` 個樣本），舊碼只是因為 `MAX_SAMPLES` 剛好整除 `HOP` 才沒露餡；改成
  `[MAX_SAMPLES + FRAME_SIZE]` + runtime `out_len <= 陣列容量` 檢查。Pool 大小從「隨便給的
  512 KB / 64 KB」改成「量出來的需求 + 適度餘裕」並在註解寫明實測數字：denoiser+MCRA+SPP 實測
  72,736 bytes（fft=512，4 個 preset + stationary 都一樣）→ pool 給 96 KB；FFT 實測 16,976 bytes
  (KISS) / 4,160 bytes (NE10) → pool 給 24 KB。Runtime `need > sizeof(pool)` 的 guard 全部保留
  （它們才是真正的安全網）。
- **`c_impl/README.md`**：同步改名；修正一個舊的錯誤說法——舊文件宣稱 `mmse_lsa_process()`
  每次呼叫吃/吐 hop_size 個時域樣本、內部有 50% overlap OLA 緩衝，這是錯的：lib 核心是**頻域
  API**（`Complex[n_freqs]` in/out，相位不變），沒有內部時域緩衝，窗/rFFT/iFFT/OLA 全部由
  caller 負責。另一個修正：`nm` 檢查 `-DUSE_EXT_MEM` object「完全無 malloc 符號」的舊說法已經
  不成立（見上「拿掉 USE_EXT_MEM」——malloc 路徑永遠編譯進去，符號一定在），改寫成「靜態路徑在
  runtime 上不呼叫任何配置器」。
- **`Makefile`：`CFLAGS` 的 `-std=c99` 改成 `-std=gnu99`**（跟 audio_common 自己的 Makefile
  一致）。原因：audio_common 的 NE10 標頭用了 GNU 的 `asm("label")` extension，在嚴格 `-std=c99`
  下編譯期直接報錯（"expected function body after function declarator"）；`gnu99` = C99 +
  GNU extension，語意上是 c99 的超集，對本 repo 自己的程式碼沒有語意差異——KISS backend 已重新
  驗證：全部 preset + stationary 仍然 byte-for-byte 相同（含跟重構前 `-std=c99` 參考輸出比對），
  純粹是前端語言模式旗標，不影響任何輸出數值。

### 驗證

- KISS backend：重構前後輸出 **byte-for-byte 相同**（`bin/denoise_wav` 4 個 preset + stationary，
  用重構前先建好的參考輸出比對）。
- `bin/denoise_mem` == `bin/denoise_wav`（同一 backend 內）**byte-for-byte 相同**：KISS 與 NE10
  分別對 4 個 preset + stationary 驗證（NE10 首次在本 repo 內原生 arm64 編譯 + 執行 + 驗證；
  NE10 輸出跟 KISS 不同屬預期，未互相比較）。
- `make parity BACKEND=kiss EXTRA_CFLAGS="-DUSE_STANDARD_MATH"` 編譯成功。
- 對 `c_impl/{src,include,example,Makefile}` 的 grep 掃描：不含任何平台廠商名稱或其記憶體
  型別字串（本檔案較早的歷史條目除外，不追溯修改），也不含舊的 `USE_EXT_MEM`/
  `nr_ext_mem`/`query_memsize` 字串（同樣排除本 CHANGELOG 的歷史條目）——皆為空。

## [v1.11.1] - 2026-07-10 · 補：exact-percentile 初始化路徑消除 malloc

> 承 v1.11.0。`feature/static-memory` 分支。預設（malloc）build 逐位元不受影響（已驗）。

### 修正

- **`mcra_noise_estimator.c`**：exact-percentile（`#ifndef USE_FAST_PERCENTILE`，即**預設**）的初始化
  `mcra_init_noise()` 原本有兩個 `malloc`（`freq_powers` gather 緩衝 + `calculate_percentile` 內的
  `temp` 複製）——雖只在 init 呼叫一次、非每幀,但破壞「USE_EXT_MEM 完全零 malloc」的保證。
  - 新增 `percentile_scratch`（`[num_init_frames]`）到 struct,create 時一併配（malloc 版 calloc /
    ext-mem 版從 pool 切),`mcra_init_noise` 改用它。
  - `calculate_percentile` 改為 **in-place quickselect**（gather 緩衝每輪重填、可直接被 reorder,故免去
    `temp` 複製）——結果值不變。
- 驗證:
  - `nm` 檢查 `-DUSE_EXT_MEM` 編出的 4 個 NR 模組 object,**完全無 malloc/calloc/realloc/free 符號引用**。
  - byte-identical 不變:ext-mem == malloc（exact-percentile）；且此修正對 malloc build 逐位元無影響（∴ 仍 == main）。
  - ext-mem pool 也少一次 init 配置;`example/main_mem.c` 本來就 0 malloc。

## [v1.11.0] - 2026-07-10 · 靜態記憶體版本（`USE_EXT_MEM`，零 malloc）

> 此版本僅存在於 `feature/static-memory` 分支。預設（malloc）build 逐位元不受影響。

### 新增功能

- **`-DUSE_EXT_MEM` 靜態記憶體模式**：denoiser 及其 MCRA / SPP / FFT 子模組的所有內部狀態改由
  呼叫端提供的**單一記憶體區塊** bump-allocate，音訊路徑上**零 malloc/free**（Novatek 嵌入式契約）。
  - **`include/nr_ext_mem.h`**（新）：共用 16-byte 對齊 bump helper `nr_aligned_size()`。
  - **`mmse_lsa_denoiser.h/.c`**：`mmse_lsa_query_memsize(cfg)` +
    `mmse_lsa_create(cfg, void* mem, size_t)`（含 MCRA/SPP 子區塊）；`mmse_lsa_destroy` 於 ext-mem 下為 no-op。
  - **`mcra_noise_estimator.h/.c`**、**`spp_estimator.h/.c`**、**`fft_wrapper.h/.c`**：各加
    `*_query_memsize()` + `create(..., mem, size)`（FFT 連 KISS twiddle 也就地配置）。malloc 路徑抽出
    `mcra_init_scalars` / `spp_init_scalars` 共用（值不變）。
  - **`example/main_mem.c`**（新）：static-pool 範例（query → static 陣列 → create → 迴圈零 malloc）。
  - **`Makefile`**：`make mem` → `bin/denoise_mem`（單次編譯，避免 `.o` 混旗標）。
- 每個 `create(mem)` 開頭 `memset(mem, 0, query)` → 與 calloc 版逐位元等價。

### 驗證

- `bin/denoise_mem`（static）輸出 == `bin/denoise_wav`（malloc）**byte-for-byte**，涵蓋
  mild/moderate/balanced/aggressive + stationary、兩個測試檔。
- malloc 路徑重構（`init_scalars` 抽出）輸出 == 改動前 main，**byte-for-byte**（未改變原行為）。
- footprint（fft=512）：denoiser+MCRA+SPP ~72.6 KB，FFT ~17 KB。

### FFT backend

- **KISS**：100% 零 malloc（已在 x86 byte-verified）。
- **NE10**（`fft_wrapper_ne10.c`，`make mem NE10_DIR=...`）：**partial** ext-mem——handle + work buffer
  進 pool,NE10 twiddle cfg 維持 create 時一次性內部 malloc（標準 NE10 無外部記憶體 API），每幀路徑零 malloc；
  `fft_destroy` 仍釋放該 cfg。⚠ 未在 x86 編譯驗證,須在 ARM target 上 build + NE10-malloc vs NE10-extmem byte 比對。

## [v1.10.0] - 2026-07-10 · 強度預設 4 級 + musical-noise fix

### 變更

- **`mmse_lsa_types.h`**：
  - `MmseLsaNrMode` 加 `MMSE_LSA_NR_MODERATE`（階梯 mild<moderate<balanced<aggressive，enum 重新編號）。
  - `mmse_lsa_default_config`：`alpha_xi 0.88 → 0.92`（musical-noise fix，全預設共用；stationary 已用 0.92 → 不受影響）。
  - `mmse_lsa_config_for_mode`：新增 MODERATE（g_min −25）；AGGRESSIVE `alpha_g 0.75→0.85` / `alpha_decay 0.85→0.88`
    （深度帶回的 speckle 用下游平滑壓）。全部鏡像 Python `core/nr_strength.py`。
- **`example/main.c`**：`--nr-mode` 加 `moderate`（4 級）。
- **`example/parity_runner.c` + `tools/parity_nr.py`**：加 strength 軸（`[mild|moderate|balanced|aggressive]`）。
- 驗證：4 級 std-math **C↔Python bit-exact**（worst ~1e-5，median ~2e-8）；balanced+stationary 仍 bit-exact。

## [v1.9.0] - 2026-07-05 · stationary 模式 + gain-floor 單位對齊

### 新增功能

- **`--stationary` 內容保留模式**（鏡像 Python `apply_mode`）
  - `include/mmse_lsa_types.h`：新增 `mmse_lsa_apply_stationary(MmseLsaConfig*)`（overlay mutator，疊在
    `--nr-mode` base 上）+ 5 個 config 欄位（`stationary_floor` / `_exponent` / `_beta` /
    `scene_change_tonal_veto` / `_lo_flatness_max`），預設全 off → full 不受影響。
  - `src/mmse_lsa_denoiser.c`：`calculate_gain` 加 Wiener 增益下界 `gain ≥ (ξ/(β+ξ))^p`（p=2 走 `ratio*ratio`
    快路徑），gate 於 `stationary_floor`（**僅 stationary 生效**）。
  - `src/mcra_noise_estimator.c`：tonal-veto scene-change + 新增 `spectral_flatness()` / `mcra_reset_noise_floor()`
    static helper。
  - `example/main.c`：`--stationary` CLI arg；`example/parity_runner.c` + `tools/parity_nr.py`：`--mode` 參數。
  - 驗證：std-math **C↔Python bit-exact**（full worst 6.0e-5 / stationary 1.3e-5，1.79M gain 值）。

### 變更

- **`g_min_db` 改用 audio 振幅 dB（/20）**：`powf(10, g_min_db/20)`（原 /10）。default −30（原 −15）、
  MILD −20、AGGRESSIVE −40；線性 floor 不變（值加倍）。xi_min/delta/scene_change 維持 /10。

## [v1.8.0] - 2026-04-17 · Release (Part A Review)

### 新增功能

**Part A Review 核心修復（與 Python v4.2 同步，雙 branch 皆已套用）**

- **Fix #1** — MCRA 初始化 `S = init_psd`
  - 檔案: `src/mcra_noise_estimator.c` (`mcra_init_noise`)
  - 變更: `self->S[k] = init_psd`（原為 `avg_power`），與 `S_min` 一致；USE_FAST_PERCENTILE 與 exact quickselect 兩條路徑皆修正
  - 影響: 首幀 `S/(S_min·δ)` ratio 不再異常高

- **Fix #3** — SPP Decision-Directed 用前一幀 `noise_psd`
  - 檔案: `src/spp_estimator.c` (`spp_estimate` / `spp_estimate_ex`)、`include/spp_estimator.h` 不變
  - 新增 struct 欄位 `float* noise_psd_prev`
  - `spp_create()` / `spp_init()`(static) 分配記憶體
  - `spp_estimate*()` 內部使用 `noise_psd_prev`（第一個 DD call 後已填入）做 xi_dd_term1 的分母；函式尾端 `memcpy` 儲存當前幀 noise_psd
  - `spp_reset()` / `spp_destroy()` 同步處理
  - 靜態記憶體 branch 的 `spp_get_mem_size()` 新增 `ALIGN16(n_freqs * sizeof(float))` 區塊

- **Fix #6** — Scene change flatness 閾值參數化
  - 檔案: `include/mmse_lsa_types.h`（加 `scene_change_flatness_threshold` 欄位）、`src/mcra_noise_estimator.c`
  - 預設 0.4f；`mcra_create()` / `mcra_init()` 從 config 讀取；`mcra_update()` 內原硬編 `hi_flatness > 0.4f` 改用 struct 欄位

- **Fix #9** — SPP `q` clip
  - 檔案: `src/spp_estimator.c` (`spp_create` / `spp_init`)
  - 在 struct assign 前 clip 到 `(1e-6, 1-1e-6)`，`prior_ratio = (1-q)/q` 移除 `+1e-10` fudge

### 未 port 至 C（N/A 或已正確）
- **#7 periodic window**：C 端原本就用 `cosf(2π·i/N)`（periodic 公式）
- **#5 asymmetric smoothing**：`MmseLsaConfig.alpha_attack / alpha_decay` 早已外露
- **#4 alpha_d shadow bug**：Python loader 特有問題
- **#2 init passthrough / #8 auto reset**：streaming API 語義與 Python batch API 不同，由 caller 負責 reset

### 驗證
- `make clean && make` 兩 branch 皆 build pass
- lib 核心（mmse_lsa_process / mmse_lsa_process_gain）為 freq-domain caller-owns-FFT API；此 bit-exact 驗證針對 lib 核心數值，非 standalone runner
  - ⚠️ 註：此處原述 `bin/denoise_wav` 端到端 bit-exact 已過時——當時 example/main.c 直接把時域 PCM 餵進 freq-domain API（指標型別錯誤），runner 並未真正跑通；example/main.c 已重寫為正確的 freq-domain runner（窗→rFFT→mmse_lsa_process→iFFT→sqrt-Hann OLA），參見 tools/parity_nr 對齊驗證
- vs pre-Part-A：lib 核心輸出差異 −37 dB 相對輸入；init 200 ms passthrough 區 bit-exact（符合 fix 作用範圍）
- vs Python V3-2：對齊後 correlation 0.58、RMS 差 +0.36 dB（符合 `scipy.special.exp1` vs C `exp1_approx` 既有漂移）

### 文檔
- `c_impl/README.md` 更新：加 Part A 說明、靜態記憶體 API 範例、使用條件、調參指引；修正 frame/hop 預設值與延遲表
- `c_impl/PART_A_C_PLAN.md` 新增：C 端 Part A 實作計畫與 audit 紀錄

---

## [v1.7.0] - 2026-03-05

### 新增功能

**FFT 後端：NE10 R2C/C2R 支援（ARM NEON 加速）**

- **檔案**: `src/fft_wrapper.c`（KISS FFT）、`src/fft_wrapper_ne10.c`（NE10）、`Makefile`
- **架構**: 兩個獨立 .c 檔案，Makefile 選擇編譯哪一個
  - `make`（預設）→ `fft_wrapper.c`（KISS FFT C2C，可攜式）
  - `make NE10_DIR=/path/to/ne10` → `fft_wrapper_ne10.c`（NE10 R2C/C2R NEON）
- **API 不變**: `fft_wrapper.h` 公開介面完全不變，呼叫端零修改
- **NE10 使用 R2C/C2R**: 訊號為實數，省去手動 real→complex 複製和共軛對稱重建
- **記憶體節省**: FFT 工作緩衝從 ~16KB 降至 ~6KB（16kHz, fft_size=512）
- **NE10 初始化**: `ne10_init()` 在首次 `fft_create()` 時自動呼叫

## [v1.6.0] - 2026-03-05

### 重大變更 (Breaking Changes)

**同步 Python V3-2 最新參數與功能**

#### 1. 場景轉換偵測（新增）
- **檔案**: `src/mcra_noise_estimator.c`, `include/mmse_lsa_types.h`
- **功能**: MCRA 加入高頻 gamma + spectral flatness 雙重條件場景轉換偵測
- **原理**: Bayesian SPP 依賴 noise_psd，場景轉換後形成 noise_psd→γ→SPP→α̃d→noise_psd 死循環。
  透過偵測高頻段能量突變（gamma > 10dB）且頻譜平坦（flatness > 0.4，噪聲特徵），
  連續 5 幀後部分重置 noise_psd（blend=0.5）+ S_min + min_buffer
- **新增參數**:
  - `scene_change_threshold_db`: 10.0（高頻 gamma 閾值）
  - `scene_change_min_frames`: 5（連續幀數）
  - `scene_change_blend`: 0.5（噪聲重置混合比）
- **效果**: 場景轉換後 SPP 從 ~0.94 恢復至 ~0.57（0.5 秒內），Clean 語音零誤觸發
- **優化**: 使用 fast_log/fast_exp 取代標準庫 logf/expf

#### 2. 參數更新
- **檔案**: `include/mmse_lsa_types.h`
- **改動**:
  - `alpha_s`: 0.7 → **0.95**（更高平滑 → 更穩定功率譜估計）
  - `L`: 5 → **32**（320ms 場景追蹤，搭配場景偵測使用）
  - `g_min_db`: -12.5 → **-15.0**（更深噪聲抑制，PESQ +0.027）
  - `alpha_g`: 0.92 → **0.88**（更快增益響應）
  - `alpha_decay`: 0.92 → **0.88**（與 alpha_g 一致）

#### 3. 移除 Soft VAD
- **檔案**: `src/mmse_lsa_denoiser.c`, `include/mmse_lsa_types.h`, `example/main.c`
- **移除**: `enable_soft_vad`, `vad_freq_low`, `vad_freq_high`, `alpha_vad` 配置
- **移除**: VAD 狀態、初始化、處理、重置邏輯
- **原因**: 實驗證明 VAD 無明顯 PESQ 提升，場景偵測已提供足夠的噪聲追蹤能力

### 文檔更新
- `README.md`: 更新配置參數表對齊實際預設值
- `README.md`: 更新記憶體估算（L=32）
- `README.md`: 移除 VAD 相關說明
- `CHANGELOG.md`: 新增 v1.6.0 記錄

---

## [v1.5.0] - 2026-03-04

### 重大變更 (Breaking Changes)

**同步 Python V3-2 (v4.0) 優化參數**
- **檔案**: `include/mmse_lsa_types.h`
- **改動**: 更新默認配置以匹配 Python v4.0 優化
  - `alpha_s`: 0.8f → 0.7f (更快時間響應，無 PESQ 損失)
  - `L`: 120 → 5 (場景適應時間從 1.2s 降至 50ms，提升 24 倍)
  - `init_percentile`: 20 → 30 (更準確的噪聲初始化)
- **影響**: 與 Python V3-2 (v4.0) 完全一致

**完全移除 Eta 場景轉換偵測**
- **檔案**:
  - `include/mmse_lsa_types.h` - 移除 eta 配置成員
  - `src/mcra_noise_estimator.c` - 移除 eta 計算邏輯
  - `example/main.c` - 移除 eta 配置代碼
- **移除內容**:
  - `MmseLsaConfig` 結構體的 `enable_eta`, `eta_beta_threshold`, `eta_slope` 成員
  - `McraNoiseEstimator` 結構體的 eta 狀態變量（`prev_frame_power`, `energy_smooth`）
  - 能量累加和 eta 計算邏輯
  - 噪聲更新公式中的 eta 乘法
- **原因**:
  - L=5 優化已提供 50ms 快速場景適應，無需 eta 機制
  - 測試證明 eta 導致 PESQ 降低 0.06-0.41（test_wav）
  - eta 收益僅 0.006 PESQ（VCTK/DEMAND），可忽略不計
  - 誤觸發風險大於收益

### 性能提升 (Performance)

- 場景轉換適應時間: 1.2s → 50ms（提升 24 倍）
- MCRA 最小值緩衝記憶體:
  - 16kHz: 240KB → **10KB** (L×513×4 = 5×513×4，節省 96%)
  - 48kHz: 240KB → **10KB** (L×513×4 = 5×513×4，節省 96%)
- 代碼簡化: 移除約 100 行 eta 相關代碼

### 修改詳情

#### 頭文件 (mmse_lsa_types.h)
```c
// 移除:
bool enable_eta;
float eta_beta_threshold;
float eta_slope;

// 更新默認值:
config.alpha_s = 0.7f;  // was 0.8f
config.L = 5;           // was 120
```

#### MCRA 噪聲估計器 (mcra_noise_estimator.c)
```c
// 移除結構體成員:
bool enable_eta;
float eta_beta_threshold;
float eta_slope;
float prev_frame_power;
float energy_smooth;

// 更新初始化百分位數:
float init_psd = avg_power * 0.23f;  // 30th percentile (was 0.17f for 20th)
float init_psd = calculate_percentile(..., 30);  // was 20

// 簡化噪聲更新公式:
float tilde_alpha_d = alpha_d + (1.0f - alpha_d) * spp_for_update[k];
// 移除: * eta
```

#### 示例程序 (main.c)
```c
// 移除:
config.enable_eta = false;

// 添加注釋說明 v4.1 優化:
// v4.1: Eta scene change detection removed (L=5 optimization replaces it)
// v4.0 optimizations (sync with Python V3-2):
// - alpha_s = 0.7 (faster response, no PESQ degradation)
// - L = 5 (50ms scene adaptation)
// - init_percentile = 30th (improved initialization)
```

### 技術細節

**為什麼 L=5 足以替代 Eta？**

1. **追蹤速度**: L=5 的 S_min 追蹤僅需 50ms，遠快於噪聲估計收斂時間（195ms with alpha_d=0.95）
2. **SPP 自動調整**: 場景變化時 SPP 自動降低，噪聲更新自動加速至 alpha_d
3. **Eta 收益極小**: 理論可節省 ~150ms，但實際 PESQ 收益僅 0.006
4. **Eta 風險大**: 無法區分"語音開始"與"場景變化"，誤觸發率高

**測試驗證** (Python 測試結果):
- ✅ L 從 120→5: ΔPESQ = 0.0000 (完全無負面影響)
- ❌ enable_eta: ΔPESQ = -0.06 到 -0.41 (明顯降低性能)

### 文檔更新

- `README.md`: 添加 v4.0/v4.1 同步說明
- 更新配置參數表（alpha_s, L 的默認值和註釋）
- 更新記憶體使用量（MCRA 緩衝從 240KB 降至 10KB）
- 更新迴圈合併說明（移除 eta 能量累加）

---

## [v1.4.0] - 2026-02-03

### Eta 場景轉換偵測修正 (Strategy K)

- **檔案**: `src/mcra_noise_estimator.c`
- **改動**: 將 eta 從 sigmoid 公式改為平滑能量比 + hard threshold
  - 舊: `eta = 0.95 / (1 + exp(slope * (beta - threshold)))` — 上限 0.95 導致語音幀 tilde_alpha_d 下降，噪聲更新速度增加 ~10x
  - 新: 平滑能量 `E_smooth = 0.7 * E_smooth_prev + 0.3 * E_cur`，`beta = E_smooth / E_smooth_prev`
    - `beta > threshold` → `eta = 0.1`（場景突變，加速噪聲更新）
    - `beta <= threshold` → `eta = 1.0`（正常，不干擾 alpha_d）
- **新增**: `energy_smooth` 欄位到 `McraNoiseEstimator` struct
- **驗證** (VCTK/DEMAND 824 files):
  - 舊 eta: PESQ +0.085, STOI -0.068
  - 新 eta: PESQ +0.399, STOI -0.010
  - 不開 eta: PESQ +0.437, STOI -0.007

## [v1.3.0] - 2026-01-29

### 嵌入式優化（階段 A+B）

目標：針對嵌入式/MCU 平台減少計算量，預估節省 ~230K cycles/幀

#### 階段 A：預設啟用 6 個優化 flag
- **檔案**: `Makefile`
- **改動**: 5 個既有數學等價優化 + 1 個新增 (`USE_INCREMENTAL_MIN`) 改為 `make` 預設啟用
- **新增**: `make debug` target（關閉所有優化 + 使用標準數學函數）
- **驗證**: vs 原始 baseline correlation = 0.9999

#### 階段 B1：消除 sqrtf — magnitude → power 域化簡
- **檔案**: `src/mmse_lsa_denoiser.c`
- **改動**: 移除 `process_frame` 中每幀 513 次 `sqrtf(power[k])` → `magnitude[k]`
- **原理**: `magnitude` 下游全部被平方回去（enhanced_psd_prev = enhanced_mag²），sqrt 和 ² 互相抵銷
  - `enhanced_psd_prev[k] = gain² × power[k]`（取代 `(gain × sqrt(power))²`）
  - VAD 能量: `gain² × power`（取代 `enhanced_mag²`）
  - `fft_apply_gain` 直接用 gain × complex spectrum，不需 magnitude
  - magnitude 只在 `#ifdef DEBUG_DUMP` 時計算
- **省**: 513 × sqrtf ≈ 25K cycles/幀

#### 階段 B2：VAD 用 fast_exp_neg 取代 expf
- **檔案**: `src/mmse_lsa_denoiser.c`
- **改動**: `expf(-3.0f * mean_power)` → `fast_exp_neg(3.0f * mean_power)`
- **驗證**: B1+B2 合計 vs 前一步 correlation = 0.99999996

#### 階段 B3：MCRA 迴圈合併（6 → 2 迴圈）
- **檔案**: `src/mcra_noise_estimator.c`
- **改動**: `mcra_update()` 原本 6 個獨立 for-k 迴圈合併為 2 個：
  - Loop A: S 平滑 + min_buffer 寫入 + eta 能量累加 + min 追蹤
  - Loop C: SPP indicator + 噪聲更新
  - eta 場景偵測計算放在兩迴圈之間（純量運算，平滑能量比 + hard threshold）
- **驗證**: bit-exact（純結構重排）

#### 階段 B4：增量最小值追蹤 (USE_INCREMENTAL_MIN)
- **檔案**: `src/mcra_noise_estimator.c`, `Makefile`
- **改動**: MCRA min tracking 從每幀 O(L) 全掃描改為增量式 O(1) 平均
  - 新值 ≤ S_min → 直接更新（O(1)）
  - 被覆蓋舊值 ≈ S_min → 重掃描（O(L)，~5% 發生）
  - 否則 S_min 不變（O(1)）
- **省**: 513 × 120 = 61,560 次比較 → 平均 ~513 次
- **驗證**: bit-exact

#### 階段 B5：process_frame 迴圈合併（3 → 1 迴圈）
- **檔案**: `src/mmse_lsa_denoiser.c`
- **改動**: VAD gain apply + gain_prev save + enhanced_psd_prev save 合併為單一迴圈
- **驗證**: bit-exact

### 全階段驗證結果

| 階段 | vs 前一步 | vs 原始 baseline |
|------|-----------|-----------------|
| A (Makefile flags) | corr = 0.9999 | corr = 0.9999 |
| B1+B2 (sqrtf + VAD) | corr = 0.99999996 | — |
| B3 (MCRA merge) | bit-exact | — |
| B4 (incremental min) | bit-exact | — |
| B5 (frame merge) | bit-exact | — |
| **全部 A+B** | — | **corr = 0.9999** |

### 尚未實作（階段 C：定點化）

以下為規劃中但尚未實作的項目，詳見 plan file。

#### C1. 數值格式選擇
- 音頻樣本: Q15 (int16_t)
- FFT: Q15（CMSIS DSP `arm_rfft_q15()`）
- 功率譜/噪聲 PSD: Q31 (int32_t)
- SNR (gamma, xi): Q8.8 (uint16_t)
- gain / SPP: Q15
- log_gain: Q8.8 (int16_t)

#### C2. 定點化優先順序
1. **gain calculator** — exp/log 最多，改為 LUT + 線性插值（收益最大）
2. **spp_estimator** — 除法改查表倒數，exp(-v) 查表
3. **mcra_noise_estimator** — 只有乘加，改為定點 MAC
4. **FFT** — 用 CMSIS DSP `arm_cfft_q15()` 或定點 KISS FFT 替換

#### C3. 定點化策略
- 逐模組替換，每步驗證 correlation > 99%
- 新增 `USE_FIXED_POINT` 編譯開關
- 新增檔案: `fixed_point_math.h`, `gain_calculator_fixed.c`, `spp_estimator_fixed.c`

---

## [v1.2.0] - 2026-01-27

### 重構

#### 合併 mmse_lsa_gain 到 mmse_lsa_denoiser
- **刪除檔案**: `src/mmse_lsa_gain.c`, `include/mmse_lsa_gain.h`
- **修改檔案**: `src/mmse_lsa_denoiser.c`
- **原因**: 增益計算只被 denoiser 內部使用，合併後更易理解
- **效果**: 減少 2 個檔案，簡化構建流程

### 文檔

#### README 新增算法流程圖
- **檔案**: `README.md`
- **新增**: 完整的 ASCII 流程圖，展示從輸入到輸出的數據流
- **新增**: 模組職責表（MCRA、SPP、Gain）

---

## [v1.1.0] - 2026-01-27

### 新增優化開關

#### USE_FAST_GAIN_SMOOTHING
- **檔案**: `src/mmse_lsa_denoiser.c`（原 `src/mmse_lsa_gain.c`）
- **功能**: 在 log 域直接進行 clamp，避免 exp→log 冗餘轉換
- **原理**:
  ```c
  // 原本：冗餘的 exp→clamp→log
  float gain = fast_exp(log_gain);
  if (gain < g_min) gain = g_min;
  self->log_gain_prev[k] = fast_log(gain);  // 冗餘！

  // 優化後：直接在 log 域處理
  if (log_gain < log_g_min) {
      gain = g_min;
      log_gain_save = log_g_min;
  } else {
      gain = fast_exp(log_gain);
      log_gain_save = log_gain;  // 無需 log()
  }
  ```
- **效果**: 每頻點省 1 次 exp + 1 次 log (~150 cycles)
- **測試**: 與原版相關度 100%

#### USE_SHARED_XI_RATIO
- **檔案**:
  - `include/spp_estimator.h` - 新增 `spp_estimate_ex()`
  - `src/spp_estimator.c` - 實現 `spp_estimate_ex()`
  - `src/mmse_lsa_denoiser.c` - 實現 `calculate_gain_ex()` 內部函數
  - `src/mmse_lsa_denoiser.c` - 使用擴展 API，新增 `v` 緩衝區
- **功能**: SPP 和 Gain 共用 `v = xi/(1+xi) * gamma` 計算結果
- **原理**:
  ```c
  // 原本：SPP 和 Gain 各自計算
  // SPP: float v = xi / (1.0f + xi) * gamma;
  // Gain: float xi_ratio = xi / (1.0f + xi); float v = xi_ratio * gamma;

  // 優化後：SPP 輸出 v，Gain 直接使用
  spp_estimate_ex(..., &v);
  mmse_lsa_gain_calculate_ex(..., v, ...);
  ```
- **效果**: 每頻點省 1 次除法 + 1 次加法
- **測試**: 與原版相關度 100%

#### USE_OPTIMIZED_MIN_BUFFER
- **檔案**: `src/mcra_noise_estimator.c`
- **功能**: 優化 MCRA 最小值追蹤的記憶體佈局
- **原理**:
  ```c
  // 原本：跨步訪問 (stride = n_freqs = 257 floats = 1028 bytes)
  // Layout: [frame_idx * n_freqs + freq_idx]
  for (int l = 0; l < L; l++) {
      val = min_buffer[l * n_freqs + k];  // 跨步 1KB！
  }

  // 優化後：連續訪問同一頻點的所有時間幀
  // Layout: [freq_idx * L + frame_idx]
  float* freq_buf = &min_buffer[k * L];
  for (int l = 0; l < L; l++) {
      val = freq_buf[l];  // 連續訪問
  }
  ```
- **效果**: 改善 cache 效率，預期 MCRA 更新加速 3-5x
- **測試**: 與原版相關度 100%

#### USE_OPTIMIZED_E1
- **檔案**: `include/fast_math.h`
- **功能**: 優化 E1(v) 指數積分的分支順序
- **原理**:
  ```c
  // 原本：依序檢查 v < 0.1, v <= 1.0, v > 1.0
  if (v < 0.1f) { ... }
  else if (v <= 1.0f) { ... }
  else { ... }

  // 優化後：先檢查 v > 1.0（高 SNR 常見情況），再計算 log10
  if (v > 1.0f) {
      return fast_exp(...);
  }
  float log10_v = fast_log10(v);  // 只計算一次
  if (v < 0.1f) { return -2.31f * log10_v - 0.6f; }
  else { return -1.544f * log10_v + 0.166f; }
  ```
- **效果**: 每頻點省 ~50 cycles（分支優化）
- **測試**: 與原版相關度 100%

#### USE_SINGLE_CLAMP
- **檔案**: `src/mmse_lsa_denoiser.c`
- **功能**: 移除冗餘的 clamp 操作
- **原理**:
  ```c
  // 原本：clamp 兩次
  if (gain_mmse < g_min) gain_mmse = g_min;  // 第一次
  if (gain_mmse > 1.0f) gain_mmse = 1.0f;
  // ... SPP weighting + smoothing ...
  if (gain < g_min) gain = g_min;  // 第二次（冗餘）
  if (gain > 1.0f) gain = 1.0f;

  // 優化後：只 clamp 一次（在 gain_mmse）
  // 因為 log-domain 的 SPP 加權和平滑不會讓增益超出範圍
  ```
- **效果**: 每頻點省 ~10 cycles（2 次比較）
- **測試**: 與原版相關度 100%

### 修正

#### FFT size 自動計算（重要）
- **檔案**: `include/mmse_lsa_types.h`
- **問題**: 固定 FFT size=512 在 48kHz 時會導致 buffer overflow（frame_size=960 > fft_size=512）
- **改動**: `mmse_lsa_default_config()` 現在根據 sample_rate 自動計算 FFT size
  ```c
  // frame_size = sample_rate * 20ms / 1000
  // fft_size = next power of 2 >= frame_size
  // 8kHz  → frame=160  → fft=256
  // 16kHz → frame=320  → fft=512
  // 48kHz → frame=960  → fft=1024
  ```
- **影響**: 修復 48kHz 音頻處理的嚴重 bug

#### 參數對齊 Python Optuna-tuned config
- **檔案**: `include/mmse_lsa_types.h`
- **改動**:
  - `alpha_xi`: 0.98 → 0.92
  - `xi_min_db`: -25 → -20
  - `alpha_s`: 0.9 → 0.8
  - `alpha_d`: 0.85 → 0.95
  - `L`: 96 → 120
  - `g_min_db`: -20 → -12.5
  - `alpha_g`: 0.7 → 0.8
- **影響**: 與 Python V3-2 輸出相關度達 **99.9%**（13 個測試檔案平均）

---

## [v1.0.0] - 2026-01-26

### 初始版本

#### 基本功能
- MMSE-LSA 語音降噪完整實現
- Streaming by hop_size 架構
- MCRA 噪聲估計（含最小值追蹤）
- SPP 語音存在機率估計（Decision Directed 方法）
- 非對稱增益平滑（Attack/Decay 分離）

#### 編譯開關
- `USE_STANDARD_MATH` - 使用標準數學函數（調試用）
- `USE_FAST_PERCENTILE` - 使用快速 percentile 近似

#### 數學優化
- `fast_math.h` - LUT + Taylor 展開的 exp/log/sqrt 實現
- 三段近似 E1(v) 指數積分函數

---

## 測試結果

### C vs Python V3-2 相關度（13 個測試檔案，48kHz）

| 噪聲類型 | 0dB | 5dB | 10dB | 15dB |
|----------|-----|-----|------|------|
| babble | 99.65% | 99.87% | 99.95% | 99.98% |
| car | 99.78% | 99.92% | 99.97% | 99.99% |
| street | 99.70% | 99.90% | 99.96% | 99.99% |
| clean | - | - | - | 100.00% |

**平均相關度: 99.90%**

> 注：C 輸出比 Python 延遲 1 hop (480 samples @ 48kHz)，上表已對齊後計算

### 優化開關相關度

| 優化開關 | 與原版相關度 | 備註 |
|---------|------------|------|
| USE_FAST_GAIN_SMOOTHING | 100% | 數學等價 |
| USE_SHARED_XI_RATIO | 100% | 數學等價 |
| USE_OPTIMIZED_MIN_BUFFER | 100% | 只改記憶體佈局 |
| USE_OPTIMIZED_E1 | 100% | 數學等價 |
| USE_SINGLE_CLAMP | 100% | 數學等價 |
| USE_FAST_PERCENTILE | ~99.5% | 近似算法 |
| USE_INCREMENTAL_MIN | 100% | 數學等價（浮點容差比對） |

## 注意事項

1. 多個優化開關可以同時使用（v1.3.0 起全部預設啟用，除 USE_FAST_PERCENTILE）
2. `USE_STANDARD_MATH` 會覆蓋 fast_math.h 中的優化函數
3. `make debug` 可關閉所有優化 + 使用標準數學函數
4. 所有優化都經過相關度測試，確保與原版輸出高度一致
