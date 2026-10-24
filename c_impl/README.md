# ANR — C Implementation (V3-2 主線)

> NEON 核心與純量版逐位元相同（NaN 結果的 payload 位元除外）；[量測與驗證](../docs/anr_optimization.md)。共用數學函式由 `audiolib/common/utility/fast_math.h` 提供。
> **對應 Python**: `python/denoisers/v3_2_mmse_lsa.py`

C 介面、檔名與 archive 以 ANR 命名；[命名對照](../docs/anr_migration.md)。

基於 Ephraim-Malah 1985 的 MMSE-LSA (Minimum Mean Square Error Log-Spectral Amplitude) 語音降噪演算法 C 實現，搭配 Cohen & Berdugo (2002) MCRA 噪聲估計與 Cohen & Berdugo (2001) Bayesian SPP 軟判決。整體通稱 **OMLSA**。

## 特性

- **Streaming 處理**：以 hop_size 為單位輸入/輸出，適合即時處理
- **MCRA 噪聲估計**：Cohen & Berdugo (2002) 最小值控制遞迴平均
- **SPP 語音存在機率**：Decision Directed 方法（DD term 用**前一幀** `noise_psd`）
- **非對稱增益平滑**：Attack/Decay 分離控制
- **可配置優化開關**：透過編譯開關選擇精度/速度權衡
- **場景轉換偵測**：高頻 gamma + spectral flatness 雙重條件；flatness 閾值可由 `scene_change_flatness_threshold` 調整

## 算法流程

函式庫的範圍是 `Y[k]` → 增益 → `Y[k]×G[k]`；標「呼叫端」的方塊（緩衝、加窗、FFT、IFFT、OLA）由應用自己負責。

```
輸入音頻 (hop_size samples)
        │
        ▼
┌───────────────┐
│ OLA 緩衝(呼叫端)│  ← 累積到 frame_size
└───────┬───────┘
        │
        ▼
┌───────────────┐
│加窗+FFT(呼叫端) │  → 複數頻譜 Y[k]
└───────┬───────┘
        │
        ├─────────────────────┬─────────────────────┐
        │                     │                     │
        ▼                     ▼                     │
   |Y[k]|² (功率譜)      Y[k] (複數頻譜)              │
        │                     │                     │
        │    ┌────────────────┘                     │
        │    │                                      │
        ▼    │                                      │
┌───────────────┐                                   │
│     MCRA      │  ← 最小值追蹤 (Cohen 2002)          │
│  噪聲估計器     │                                   │
└───────┬───────┘                                   │
        │                                           │
        │ noise_psd[k]                              │
        │                                           │
        ▼                                           │
┌───────────────┐                                   │
│      SPP      │  ← Decision Directed 方法          │
│  語音存在機率   │                                   │
└───────┬───────┘                                   │
        │                                           │
        │ spp[k], ξ[k], γ[k]                        │
        │                                           │
        ▼                                           │
┌───────────────┐                                   │
│  MMSE-LSA     │  ← Ephraim-Malah 1985             │
│  增益計算       │                                  │
└───────┬───────┘                                   │
        │                                           │
        │ G[k] (增益)                                │
        │                                           │
        └───────────────────┬───────────────────────┘
                            │
                            ▼
                    Y[k] × G[k] = X̂[k]
                            │
                            ▼
                   ┌────────────────┐
                   │IFFT+加窗(呼叫端)│
                   └───────┬────────┘
                           │
                           ▼
                   ┌───────────────┐
                   │OLA 合成(呼叫端)│
                   └───────┬───────┘
                           │
                           ▼
                   輸出音頻 (hop_size samples)
```

### 模組職責

| 模組 | 輸入 | 輸出 | 功能 |
|------|------|------|------|
| **MCRA** | 功率譜 \|Y\|² | 噪聲 PSD λ_d | 追蹤噪聲底噪（最小值控制遞迴平均）|
| **SPP** | 功率譜、噪聲 PSD | p(H₁), ξ, γ | 判斷當前幀是否有語音 |
| **Gain** | SPP 輸出、噪聲 PSD | G[k] | 計算 MMSE-LSA 頻譜增益 |

## 編譯

### 基本編譯

```bash
make
make SIMD=0  # 強制 NR 與 audiolib 的所有可選 SIMD 路徑走 scalar
```

### 調試版本（關閉所有優化，使用標準數學函數，與 Python 輸出最接近）

```bash
make debug
```

### 全速版本（啟用近似 percentile）

```bash
make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"
```

### 靜態記憶體版本（嵌入式，零 malloc）

```bash
make mem              # → bin/<backend>-<config-hash>/denoise_mem（範例 example/main_mem.c），FFT 為 NE10（ARM NEON）
```

輸出檔案位於依 backend + 編譯參數雜湊命名的 `bin/<backend>-<config-hash>/` 目錄；
用 `make print-bin-dir`（帶上與建置相同的參數）取得確切路徑，或
`make publish` 產出穩定的 `dist/<backend>/current/` 交付路徑。

denoiser、MCRA、SPP、FFT **同時**提供 malloc 路徑（`_create`）與靜態記憶體路徑
（`_get_mem_size` + `_init`，與 AEC 的 `aec_get_mem_size`/`aec_init` 命名一致）。
兩條路徑編進同一份 object，沒有編譯期 `#ifdef` 切換；每個 handle 內有 `is_static` flag
（`_create()` 設 0，`_init()` 設 1），`_destroy()` 靠它決定要不要 free。用法：先用
`_get_mem_size()` 問要多少，配一塊記憶體（static 陣列或呼叫端的 platform block），交給
`_init(mem, size, ...)`：

```c
static uint8_t pool[/* >= anr_get_mem_size(&cfg) */] __attribute__((aligned(16)));
size_t need = anr_get_mem_size(&cfg);              // 先問大小
AnrDenoiser* d = anr_init(pool, sizeof pool, &cfg);  // 零 malloc
/* ... 每幀 anr_process()，音訊路徑無任何配置 ... */
anr_destroy(d);                                     // no-op（記憶體由呼叫端持有）
```

static instance 的 `anr_destroy()` 是 no-op：`AnrDenoiser` 不持有 FFT 或 backend heap 資源
（頻域 I/O 由呼叫端的 `FftHandle` 負責）。`fft_init()` 建立的 handle 其 `fft_destroy()` 同樣是
no-op、可重複呼叫：NE10 的 R2C/C2R twiddle cfg 從呼叫端 pool 切出（`audiolib` 的 vendored NE10
external-memory 初始化 `ne10_fft_init_r2c_float32_ext`），沒有 backend-internal malloc。完整範例見
[`../docs/c_user_manual_zh_TW_01_quick_start.md`](../docs/c_user_manual_zh_TW_01_quick_start.md) §1.5 的 `create_static_nr`。

演算法與 malloc 版使用同一個處理核心（只差配置方式）：實測 `denoise_mem` 輸出與 `denoise_wav` byte-for-byte 一致：`test_wav/wav/babble_0dB.wav`（48 kHz/1024，四個 preset）、
`test_wav/music/fix_gain_noise.wav`（16 kHz，256 與 512 兩個 grid，mild／balanced／aggressive）；其他素材與 grid 未逐一比對。同一機制也覆蓋子模組
`fft_get_mem_size`/`fft_init`、`noise_estimator_get_mem_size`/`noise_estimator_init`、
`spp_get_mem_size`/`spp_init`。

**零 malloc 保證**：malloc 路徑編進同一份 object，所以 `nm` 一定看得到
`malloc`/`calloc`/`free` 符號（來自 `_create()`）。保證的是**靜態路徑在執行期不呼叫任何配置器**：
`_init()` 只做指標運算 + `memset`，連預設的 exact-percentile 初始化也用預先配好的
`percentile_scratch`（in-place quickselect）。`example/main_mem.c` 呼叫 `_init()` 系列，執行期 0 malloc。

**FFT 與 fast_math 來自共用的 `../audiolib/common`**（`make` 產出 `libaudio_common.a`，
`c_impl/Makefile` 直接連結；本 repo 不含 NE10 原始碼副本）。FFT 唯一後端是 NE10；handle、
work buffer、twiddle cfg 都在 pool 內，`fft_init()` 到 `fft_destroy()` 全程零 heap，
**每幀音訊路徑零 malloc**。

> **Note:** `make` 預設啟用 6 個優化開關（近似數學的誤差依核准預算驗收），不需要手動指定。

這裡的「fast math」指 `fast_math.h` 與 `USE_*` 選項的近似函式，並非編譯器
`-ffast-math`；後者會被 Makefile 拒絕。std-math C 對 Python 與出貨 C 對
std-math C 分別用數值容差／核准近似預算驗收，不能將出貨結果宣稱為 Python bit-exact。

### FP-contraction 政策

`-ffp-contract=off -fno-math-errno` 是四個 repo（`audiolib`、`NR/c_impl`、`AEC/c_impl`、
`Audio_ALG/pipelines`）的統一政策，套用到每個 TU（含 vendored 的 NE10）。它附加在
`CFLAGS` 組裝的最後一步，呼叫端的 flag 蓋不掉；Makefile 在 parse time 拒絕
`EXTRA_CFLAGS`（或 `CFLAGS=`）內的 `-Ofast`／`-ffast-math`／`-ffp-contract=<任意值>`
（`FP policy conflict`）。`../audiolib/common/scripts/audit_fp_contract.sh` 反組譯
`anr.o`／`noise_estimator.o`／`spp_estimator.o`，出現 fmadd／fmsub／fnmadd／fnmsub／
fmla／fmls 即失敗；其 header 說明檢查範圍。

## 編譯開關說明

ARM32／ARM64 由編譯器 target 自動選擇，不需要修改原始碼。共用的手寫 DSP NEON
kernel 目前限 AArch64；ARM32 走其 C fallback，即使 FFT 本身可使用 ARM32 NEON。
`SIMD=0` 是 DSP kernel 的純量覆寫，不是 ABI 選擇器。交叉編譯時必須提供同一套
CC／CXX／AR／RANLIB。靜態 pool 的需求與結構布局屬於該次編譯的 ABI，應在目標版本
呼叫 `_get_mem_size()`，不可沿用 ARM64 的固定 byte 數或跨 ABI 複製 handle 記憶體。

ARM32 請用 `EXTRA_CFLAGS=-mfpu=neon-vfpv4`（AArch32 ARMv8 核心用 `-mfpu=neon-fp-armv8`），
不要用單純的 `-mfpu=neon`：沒有硬體 FMA 時，每個明確的 `fmaf()`（含 FFT 功率譜）都會變成
libm 呼叫，位元結果不變但速度慢很多。ARMv7 Advanced SIMD 會把 subnormal 沖為零並以預設
NaN 取代 NaN payload，因此 ARM32 上 `SIMD=1` 與 `SIMD=0` 對這類值可能不同；只有 NE10 NEON
FFT（以及 AEC 在具硬體 FMA 的核心上的 delay matched filter）受影響；NR 本身在 ARM32 為 C。

### 預設啟用（`make` 即啟用）

| 開關 | 說明 | 相關度 |
|------|------|--------|
| `USE_FAST_GAIN_SMOOTHING` | 在 log 域直接 clamp，省略 exp→log 轉換 | 公式等價；fast-math 下不保證 bit-exact |
| `USE_SHARED_XI_RATIO` | SPP 和 Gain 共用 v 計算結果，每頻點省 1 次除法 | 公式等價；≤1 ulp，不保證 bit-exact |
| `USE_OPTIMIZED_MIN_BUFFER` | MCRA 最小值緩衝使用連續記憶體佈局 | 100% |
| `USE_OPTIMIZED_E1` | E1(v) 指數積分分支重排 + 共用 log10 | 100% |
| `USE_SINGLE_CLAMP` | 移除冗餘的 gain clamp；只在 `USE_FAST_GAIN_SMOOTHING` **關閉**時有作用，預設組合下是 no-op | 100% |
| `USE_INCREMENTAL_MIN` | MCRA 增量最小值追蹤（平均 O(1)） | 100% |

### 手動啟用

| 開關 | 說明 | 相關度 |
|------|------|--------|
| `USE_FAST_PERCENTILE` | 使用 mean×0.23 近似目前設定的 30th percentile，只省 `num_init_frames` 個 float 的 percentile scratch（啟動列已與最小值 ring 共用儲存） | 近似模式，需獨立做品質驗證 |

### 調試用

| 開關 | 說明 |
|------|------|
| `USE_STANDARD_MATH` | 使用標準數學函數（expf/logf/sqrtf），`make debug` 自動啟用 |

### 推薦配置

| 場景 | 配置 |
|------|------|
| 調試/驗證 | `make debug` |
| 標準使用 | `make` |
| 嵌入式/最小記憶體 | `make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"` |
| 嵌入式/零 malloc（呼叫端提供記憶體） | `make mem`（`_get_mem_size`/`_init`，見上「靜態記憶體版本」） |

## 實作要點

- **power 域運算**：增益計算在 power 域進行，下游需要的是 magnitude 的平方，所以
  `enhanced_psd[k] = gain[k]² × power[k]`，不需對每個頻點做 `sqrtf`；最終重建用
  `fft_apply_gain(spectrum, gain)` 直接乘複數頻譜。
- **MCRA 增量最小值追蹤**：瓶頸是每幀掃描 ring buffer（L 幀；16 ms 錨點下為 32 幀）找最小值。
  寫入新值 `new_S` 覆蓋舊值 `old_val` 時：`new_S ≤ S_min` → `S_min = new_S`（O(1)）；
  `old_val ≈ S_min` → 重掃描找新 `S_min`（O(L)）；其他情況 `S_min` 不變（O(1)）。
  多數幀只需 O(1)。

## 使用方法

### 命令列工具

```bash
# 執行檔在 bin/<backend>-<config-hash>/（`make -s print-bin-dir` 取得）
denoise_wav input.wav output.wav                     # 預設 balanced
denoise_wav input.wav output.wav --nr-mode moderate  # 強度：mild|moderate|balanced|aggressive（或 0|1|2|3）
denoise_wav input.wav output.wav --bypass            # 不處理，原樣複製
```

**強度軸：**
- `--nr-mode {mild|moderate|balanced|aggressive}`，或同順序的數字 `0|1|2|3`（`anr_config_for_mode`；`anr_nr_mode_from_name()` 兩種寫法都接受）：越強壓越深。
  4 級深度階梯 g_min = −20 / −23 / −25 / −28 dB（振幅 /20）。所有預設共用 `alpha_xi`
  （DD ξ 平滑，壓掉 SPP 抖動＝musical noise；對語音幾乎零成本）。

### 程式碼整合（freq-domain：caller 自備 FFT / 窗 / OLA）

lib 核心 `anr_process()` 是**頻域 API**：吃 `Complex[n_freqs]` 頻譜、吐
`Complex[n_freqs]`（套用 per-bin gain、相位不變）。窗 / rFFT / iFFT / OLA 由
caller 負責（見 `example/main.c` 的完整 freq-domain runner）。

```c
#include "anr.h"
#include "fft_wrapper.h"

// 1. 創建配置 + 降噪器 + FFT handle
AnrConfig config = anr_default_config(16000);
AnrDenoiser* denoiser = anr_create(&config);
FftHandle* fft = fft_create(config.fft_size);
int n_freqs = anr_get_n_freqs(denoiser);   // fft_size/2 + 1

// 2. 每幀：窗 -> rFFT -> anr_process -> iFFT -> 窗 -> OLA
//    （窗 = sqrt(periodic Hann)，50% overlap 即 COLA，無需額外歸一化）
Complex spec_in[n_freqs], spec_out[n_freqs];
fft_forward(fft, windowed_frame /*[fft_size]*/, spec_in);
anr_process(denoiser, spec_in, spec_out);  // gain 套到複數頻譜
fft_inverse(fft, spec_out, time_out /*[fft_size]*/);
// out[start..] += time_out * window;  (overlap-add)

// 3. 清理
anr_destroy(denoiser);
fft_destroy(fft);
```

### 執行期重設定（running instance 上換 tuning）

```c
int anr_reconfigure(AnrDenoiser* self, const AnrConfig* target);
int anr_set_mode(AnrDenoiser* self, AnrMode mode);
```

兩者都不重新配置任何記憶體，所以格點（`sample_rate` / `frame_size` / `hop_size` /
`fft_size`）與兩個決定 pool 大小的欄位（`L`、`num_init_frames`）**必須等於實例當下的
值**，`target` 另外還要完整通過 `anr_validate_config()`。回 `0`，或 `-1`
（NULL、target 無效、幾何不符）；`-1` 時**什麼都不寫**。在兩個 hop 之間呼叫、與
`anr_process()` 序列化；**非 thread-safe**。

**狀態是刻意保留的**：追蹤中的噪聲底、MCRA 最小值追蹤環與它的 scene-change run
length、SPP 的 a-priori-SNR 歷史、增益平滑歷史，全部繼續跑。換強度不是重啟——
把噪聲估計在串流中途丟掉，造成的 artefact 比原本想調掉的東西更糟。真的要重啟請用
`anr_reset()`。

**`anr_reconfigure()` 逐字採用 `target`**：不做 preset 查表、不做 overlay 疊加。
這是刻意的——組態是「preset 加上自己的覆寫」的呼叫端，必須自己重建整份組合再傳進來，
否則那些覆寫會被悄悄還原回 canonical preset 的值。

**`anr_set_mode()` 只適用於組態等於 canonical preset 的實例**：它替該 mode 組出 canonical
組態（`anr_config_for_mode_grid()`，`L` 為函式庫預設）、交給 `anr_reconfigure()`。回 `0`，
或 `-1`（NULL、超出 enum 的 mode、target 被拒）。

> **對疊了自己覆寫的實例，不要用 `anr_set_mode()`。** 以 `anr_config_for_mode_grid()` 建出、
> 沒有改動任何欄位的實例，可以直接用 `anr_set_mode()` 換強度。若建立實例時在 canonical
> preset 上改過欄位，裸的 canonical preset 會把非 pool 欄位的覆寫悄悄還原，而改過 `L` 或
> `num_init_frames` 時整個呼叫會被**拒絕**（pool 大小不符）。這種實例請自己重組
> 完整組態再呼叫 `anr_reconfigure()`。

```c
/* 組態等於 canonical preset：直接換強度，噪聲底與平滑歷史保留 */
if (anr_set_mode(denoiser, ANR_MODE_AGGRESSIVE) != 0) { /* 引數不合法 */ }

/* 自己疊了覆寫的呼叫端：重組整份組態再交出去 */
AnrConfig target = anr_config_for_mode_grid(
    sr, fft_size, ANR_MODE_AGGRESSIVE);
target.noise_over_subtraction = 1.2f;   /* 範例覆寫；每次都要重新疊上去 */
if (anr_reconfigure(denoiser, &target) != 0) { /* 幾何不符或 target 無效 */ }
```

回歸測試：`make test-reconfigure`（`test/test_reconfigure.c`）。

### Python↔C 數值對齊驗證 (parity harness)

`python/tools/parity_nr.py` + `example/parity_runner.c` 提供可重現的埠正確性驗證，
**隔離 FFT 差異**：兩端餵入 byte-identical 的逐幀複數頻譜，只比 gain/SPP/MCRA 運算。

Python dump 可用 `--fft-size` 明確選 grid：A＝16k/256/128、
B＝16k/512/256、C＝48k/1024/512。NRP2 header 記錄輸入 sample rate，
`n_freqs` 決定 FFT size；C runner 從這兩者重建相同 grid。
`compare` 回報絕對 gain 差異的 worst／median／mean；Python/C 比較是
float64／float32 與數學近似的數值容差檢查，不宣稱 bit-exact。

```bash
# 0. 輸出夾（repo 根目錄的 results/，benchmark 工具也寫這裡）
mkdir -p ../results

# 1. Python 端 dump 參考頻譜 + gain
python3 ../python/tools/parity_nr.py dump --wav ../test_wav/wav/babble_10dB.wav --out ../results/parity_in.bin

# 2a. C 端 fast-math（bin 目錄依 build flags 雜湊）
ac=$(make -s --no-print-directory -C ../../audiolib/common print-lib-path)
make DEBUG=0 COMMON_LIB="$ac" parity
bin_dir=$(make -s DEBUG=0 COMMON_LIB="$ac" print-bin-dir)
"$bin_dir/parity_runner" ../results/parity_in.bin ../results/g_fast.bin
python3 ../python/tools/parity_nr.py compare --ref ../results/parity_in.bin --c-gains ../results/g_fast.bin

# 2b. C 端 standard-math（檢查 float32/float64 殘差）
make DEBUG=1 COMMON_LIB="$ac" parity
bin_dir=$(make -s DEBUG=1 COMMON_LIB="$ac" print-bin-dir)
"$bin_dir/parity_runner" ../results/parity_in.bin ../results/g_debug.bin
python3 ../python/tools/parity_nr.py compare --ref ../results/parity_in.bin --c-gains ../results/g_debug.bin
```

NRP2 dump header 會攜帶 `sample_rate`；C 端據此建立完全相同的 signal grid
與 wall-clock-retimed EMA/count。NRP1 header 視為 16 kHz。實測
（48 kHz babble_10dB.wav，3480 幀 × 513 bin）：

| build | worst &#124;Δgain&#124; | median &#124;Δgain&#124; | mean &#124;Δgain&#124; |
|-------|--------------|---------------|-------------|
| standard-math (`-DUSE_STANDARD_MATH`) | 1.192e-5 | 1.490e-8 | 4.593e-8 |
| fast-math (預設) | 7.277e-3 | 1.113e-4 | 2.268e-4 |

上表的 standard-math 使用 `DEBUG=0 EXTRA_CFLAGS=-DUSE_STANDARD_MATH`，
與上方 `DEBUG=1` 指令不同；DEBUG=1 同時關閉六個 production 優化開關。
上表是該素材的實測殘差，不是所有輸入的通用容差上限。standard-math 仍有
float32/float64 誤差；fast-math 另外包含 `fast_exp`（LUT +
Taylor，相對誤差 ≤ 0.39%）與 degree-4 minimax `fast_log`（絕對誤差 < 1e-4），兩者都是
有界的近似（NR 不呼叫 `fast_sqrt`）。

## 使用條件 (Usage Requirements)

- **輸入格式**：單聲道（多聲道自動取第一聲道）、8 / 16 / 48 kHz PCM16 或 32-bit float
- **首 200 ms 需為純噪聲（或無語音）**：用於初始化 MCRA 噪聲底噪，前 `num_init_frames * hop_size` 樣本為 passthrough
- **Frame / hop 於建立後固定**：`frame_size == fft_size`、`hop_size == frame_size/2`，因此不做 zero-padding。`anr_default_config(sample_rate)` 選 8k:128/64、16k:256/128、48k:1024/512；8 kHz 與 16 kHz 分別可用 `anr_default_config_for_grid(8000, 256)`／`anr_default_config_for_grid(16000, 512)` 選較高延遲的 256/128 或 512/256。example runners 也直接使用輸入 rate 對應的 grid；instance 建立後不可中途切換。
- **Streaming 語義**：`anr_process()` 是**頻域 API**——每次呼叫吃 `Complex[n_freqs]` 複數頻譜、
  吐 `Complex[n_freqs]`（套用 per-bin gain、相位不變），lib 核心本身**沒有**內部時域緩衝或 OLA；
  窗函數、rFFT、iFFT、50% overlap-add 全部由 caller 負責（見 `example/main.c` 的完整 freq-domain
  runner，或本文件「程式碼整合」一節）

### 不適用情境（C 端與 Python 完全一致）
- 迴響 / 回聲 → 另配 AEC（`SE/AEC/`）或 dereverb 模組
- 風聲 / 麥克風 buffeting → 統計型單麥 NR 無法處理；建議硬體風罩
- 衝擊 / transient（敲擊、關門、碗盤碰撞）→ MCRA 約 512 ms 的 tracking window 追不上
- 與目標語音頻譜重疊的干擾（其他人語音、音樂、電視）→ SPP 二元假設不適用

## 調參指引 (Quick Tuning)

> **優先使用 strength mode**：呼叫 `anr_config_for_mode(sample_rate, ANR_MODE_MILD | MODERATE | BALANCED | AGGRESSIVE)`，多數情境足矣。

> **⚠ g_min_db 為 audio 振幅 dB（/20 換算 `10^(db/20)`）** — gain 直接乘幅度譜（無 sqrt），故 floor 是
> 振幅量。越負壓越深（-28 ≈ 0.04、-25 ≈ 0.056、-20 ≈ 0.1）。（xi_min_db / delta_db / scene_change 是
> 功率/SNR dB，維持 /10。）

> 四級 strength preset 只是「抑噪深度」的四個點：`g_min_db / q / xi_min_db / noise_over_subtraction`
> 分別為 mild −20/0.58/−10/1.2、moderate −23/0.54/−10/1.3、balanced −25/0.52/−10/1.4、
> aggressive −28/0.45/−12/1.3；DD、MCRA tracker、attack/decay 與 300 Hz 以下的語音 guard 四級共用，
> 換 preset 不會換到不同的時間常數。

| Symptom | 建議動作 |
|---|---|
| 殘留底噪吵 | 換 AGGRESSIVE 模式，或沿深度軸手動：`config.q = 0.45f`、`config.noise_over_subtraction = 1.3f`、`config.g_min_db = -28.0f` |
| 語音變悶 / 細節掉 | 換 MILD 模式，或 `config.q = 0.58f`、`config.g_min_db = -20.0f`、`config.noise_over_subtraction = 1.2f` |
| Musical noise | 提高 `config.alpha_decay`（必要時連同 `alpha_attack`）；`alpha_g` 目前不參與 C 輸出。`xi_min_db` 調高（如 -10 → -8）而非調低 |
| 場景切換慢（開冷氣、進車廂） | `config.scene_change_threshold_db = 7.0f` |
| 場景偵測誤觸發 | `config.scene_change_threshold_db = 12.0f`、`config.scene_change_min_frames = 8` |
| 語音初期被吃掉 | 確認首 200 ms 為純噪聲；若使用場景無法保證，考慮在 caller 端做 VAD gating |

### 不建議在 release 動
- `alpha_xi` / `alpha_s` / `alpha_d` / `L` / `alpha_p` — 內部穩定性依賴這些預設
- `num_init_frames` — 依 grid 換算為約 200 ms（例如 16 kHz/256 為 25 frames），改短會讓底噪估計 under-fit
- 編譯開關：出貨組態即 `make`（啟用 6 個優化開關；其中 fast gain smoothing 在近似數學下不宣稱 bit-exact）

### 當這些都不夠
- 檢查是否屬於「不適用情境」—— 本模組 by design 無法處理風聲 / 衝擊 / 重疊干擾
- 用 `make debug` 重編（標準數學），以 `anr_get_noise_psd()`／`anr_get_gain()` 讀出逐幀值，與 Python 逐幀對比（parity harness 見上）

## 配置參數

> **數值以 [`docs/c_user_manual_zh_TW_02_config_reference.md`](../docs/c_user_manual_zh_TW_02_config_reference.md) §4 為準。**
> 下表只列欄位與用途。多數 EMA 係數與幀數（`alpha_*`、`L`、`num_init_frames`）
> 在建構時會**依實際 hop retime**，所以這裡標的是「調校時的錨點值」，不是
> `anr_default_config_for_grid()` 實際填進 struct 的值——兩者在 16 kHz/256
> 就已經不同。要看實際生效的值，讀該節，或直接印出 config。

| 參數 | 調校錨點 | 說明 |
|------|--------|------|
| `frame_size` | 等於 `fft_size` | 不補零的 2 次方分析窗；8k→128（可選 256）、16k→256（可選 512）、48k→1024 |
| `hop_size` | `frame_size / 2` | 固定 50% overlap |
| `fft_size` | 依 rate/grid 選擇 | 嚴格等於 frame（不將 20 ms frame 補到下一個 2 次方） |
| `alpha_xi` | 0.92 | 先驗 SNR (ξ) DD 平滑 |
| `q` | 0.52 | balanced 語音先驗機率 |
| `xi_min_db` | -10 | balanced 先驗 SNR 下限 (dB) |
| `alpha_s` | 0.95 | MCRA 時間平滑 |
| `alpha_d` | 0.85（16 ms 錨點） | MCRA 噪聲更新率；建構時依 grid retime |
| `L` | 32（16 ms 參考值） | 建構時依 hop retime，使 MCRA window 維持約 512 ms |
| `num_init_frames` | 20（10 ms 參考值） | 建構時依 hop retime，使初始化至少涵蓋 200 ms |
| `scene_change_threshold_db` | 10.0 | 場景轉換高頻 gamma 閾值 (dB) |
| `scene_change_min_frames` | 5 | 場景轉換需連續幀數 |
| `scene_change_blend` | 0.5 | 場景轉換噪聲重置混合比 |
| `scene_change_flatness_threshold` | 0.4 | 場景轉換高頻 spectral flatness 閾值 |
| `g_min_db` | -25.0 | balanced 最小增益（**audio 振幅 dB，/20**；約 0.056 floor） |
| `alpha_g` | 0.88 | C 不讀取（不參與增益運算；平滑改調 `alpha_decay`／`alpha_attack`） |
| `alpha_attack` | 0.15（16 ms 錨點） | 非對稱平滑 Attack；建構時依 grid retime |
| `alpha_decay` | 0.88 | 非對稱平滑 Decay；有自己的預設（與 `alpha_g` 的預設值相同，兩者互相獨立） |

## 延遲

NR 核心本身 0 延遲（增益同 hop 產出）。端到端的框架延遲來自呼叫端的 sqrt-Hann WOLA（50% overlap），
為 **1 個 hop**；實測以 `../docs/c_user_manual_zh_TW_01_quick_start.md` §1.1 的
`nr_stream.c` 流程送入單一脈衝，16 kHz/256 的輸出峰值比輸入晚 128 樣本。

| 採樣率 | frame_size | hop_size | fft_size | 框架延遲（1 hop） |
|--------|-----------|----------|----------|------|
| 8 kHz（預設） | 128 samples | 64 samples | 128 | 8 ms |
| 8 kHz（可選，較高延遲） | 256 samples | 128 samples | 256 | 16 ms |
| 16 kHz（預設） | 256 samples | 128 samples | 256 | 8 ms |
| 16 kHz（可選，較高延遲） | 512 samples | 256 samples | 512 | 16 ms |
| 48 kHz | 1024 samples | 512 samples | 1024 | 10.667 ms |

> **注意**: 初始化幀數會依 hop retime，保證至少約 200 ms；期間音頻 passthrough（gain=1），MCRA 累積噪聲統計。
> 數位靜音幀（所有 bin 恰為 0）不計入這 200 ms。

## 檔案結構

```
c_impl/
├── include/
│   ├── anr.h                  # 主要 API（malloc + 靜態記憶體 create/get_mem_size/init）
│   ├── anr_types.h            # 配置結構和預設值
│   ├── noise_estimator.h      # 噪聲 PSD 追蹤
│   └── spp_estimator.h        # SPP 估計
├── src/
│   ├── anr.c                  # 主模組（含 MMSE-LSA 增益計算）
│   ├── anr_internal.h
│   ├── noise_estimator.c
│   └── spp_estimator.c
├── example/
│   ├── main.c                 # 命令列工具（malloc / heap 路徑）
│   ├── main_mem.c              # 命令列工具（靜態記憶體路徑，見上一節）
│   ├── parity_runner.c         # Python↔C parity harness 的 C 端
│   └── wav_io.h                # WAV 讀寫
├── test/                      # C 測試（make test-* 目標）與 Python/C parity 腳本
├── Makefile
├── README.md                  # 本文件
└── CHANGELOG.md               # 改動記錄

../audiolib/common/                # 共用層（本 repo 之外，siblings 目錄）：
├── include/fft_wrapper.h        #   Complex 型別與 FFT heap/static API；ALIGN16 在 utility/mem_align.h
├── utility/fast_math.h          #   快速數學 (LUT/Taylor exp, minimax log, AArch64 hardware sqrt)
└── lib/ne10/                    #   FFT 後端（NE10）的原始碼；`make lib`
                                  #   產出 bin/<backend>-<config-hash>/libaudio_common.a
                                  #   （`make print-lib-path` 取得確切路徑），c_impl 連結它
```

## 記憶體使用

- **16 kHz/256**（balanced，`make` 預設）：`anr_get_mem_size()` = 45,344 B；加 `-DUSE_FAST_PERCENTILE` 為 45,200 B（只少 percentile scratch，啟動列與最小值 ring 共用同一塊，取兩者較大者）
- **48 kHz/1024**（n_freqs=513，L=48）：144,576 B；MCRA `min_buffer`（`L × n_freqs × 4`）= 98,496 B
- 另需 `fft_get_mem_size()`（256 → 7,152 B；1024 → 26,352 B），各 grid 數值見 `docs/html/nr_c_api.html`


## 參考文獻

1. Ephraim, Y., & Malah, D. (1985). Speech enhancement using a minimum mean-square error log-spectral amplitude estimator. IEEE TASSP.
2. Cohen, I., & Berdugo, B. (2002). Noise estimation by minima controlled recursive averaging. IEEE SAP.
