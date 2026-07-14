# OMLSA Speech Denoiser — C Implementation (V3-2 主線)

> **Release**: v1.12.2（c_impl）· 移除 `USE_FAST_RECIPROCAL` 編譯開關（維持單一 bit-exact IEEE 除法路徑；`fast_recip`/`fast_div` 也一併從 `audio_common/fast_math.h` 移除）
> **對應 Python**: `denoisers/v3_2_mmse_lsa.py`

基於 Ephraim-Malah 1985 的 MMSE-LSA (Minimum Mean Square Error Log-Spectral Amplitude) 語音降噪演算法 C 實現，搭配 Cohen & Berdugo (2002) MCRA 噪聲估計與 Cohen & Berdugo (2001) Bayesian SPP 軟判決。整體通稱 **OMLSA**。

## 特性

- **Streaming 處理**：以 hop_size 為單位輸入/輸出，適合即時處理
- **MCRA 噪聲估計**：Cohen & Berdugo (2002) 最小值控制遞迴平均
- **SPP 語音存在機率**：Decision Directed 方法（Fix #3: DD term 用**前一幀** `noise_psd`）
- **非對稱增益平滑**：Attack/Decay 分離控制
- **可配置優化開關**：透過編譯開關選擇精度/速度權衡
- **場景轉換偵測**：高頻 gamma + spectral flatness 雙重條件；flatness 閾值現在可由 `scene_change_flatness_threshold` 調整
- **與 Python V3-2 同步**：Part A Review 修復已 port（#1, #3, #6, #9）
- **不含 V4 wind handler**：V4 為 Python-only research 框架，VCTK/DEMAND 驗證未能改善風聲，C 端暫不實作

## 算法流程

```
輸入音頻 (hop_size samples)
        │
        ▼
┌───────────────┐
│   OLA 緩衝     │  ← 累積到 frame_size
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  加窗 + FFT    │  → 複數頻譜 Y[k]
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
                   ┌───────────────┐
                   │  IFFT + 加窗  │ 
                   └───────┬───────┘
                           │
                           ▼
                   ┌───────────────┐
                   │   OLA 合成     │
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
```

### 調試版本（關閉所有優化，使用標準數學函數，與 Python 輸出最接近）

```bash
make debug
```

### 全速版本（啟用近似 percentile，進一步省記憶體）

```bash
make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE"
```

### 靜態記憶體版本（嵌入式，零 malloc）

```bash
make mem              # → bin/denoise_mem（範例 example/main_mem.c），預設 BACKEND=kiss
make mem BACKEND=ne10 # 嵌入式目標的實際 deliverable（ARM NEON）
```

denoiser、MCRA、SPP、FFT 現在**同時**提供 malloc 路徑（`_create`）與靜態記憶體路徑
（`_get_mem_size` + `_init`，跟 AEC 那邊的 `aec_get_mem_size`/`aec_init` 命名慣例一致）——
不再有編譯期 `#ifdef` 二選一，兩條路徑永遠都編進同一份 object，用哪條純粹是「呼叫哪個函式」的
runtime 選擇（每個 handle 內部有一個 `is_static` flag：`_create()` 設 0，`_init()` 設 1，
`_destroy()` 靠它決定要不要真的 free）。用法：先用 `_get_mem_size()` 問要多少，配一塊
（static 陣列，或呼叫端自己的 platform 記憶體 block），交給 `_init(mem, size, ...)`：

```c
static uint8_t pool[/* >= mmse_lsa_get_mem_size(&cfg) */] __attribute__((aligned(16)));
size_t need = mmse_lsa_get_mem_size(&cfg);              // 先問大小
MmseLsaDenoiser* d = mmse_lsa_init(pool, sizeof pool, &cfg);  // 零 malloc
/* ... 每幀 mmse_lsa_process()，音訊路徑無任何配置 ... */
mmse_lsa_destroy(d);                                     // no-op（記憶體由呼叫端持有）
```

`mmse_lsa_destroy()` 在這裡是**真正**的 no-op：`MmseLsaDenoiser` 本身不持有 FFT 或任何
backend heap 資源（頻域 I/O 由呼叫端自己的 `FftHandle` 負責，見下方完整範例），所以
static instance 的 destroy 沒有東西要釋放。但呼叫端另外持有的 `FftHandle`（`fft_init`）
就不一定是 no-op——KISS backend 下確實也是零 malloc/no-op，NE10 backend 下
`fft_init` 會觸發一次 backend-internal 的 twiddle 設定 malloc，該記憶體活在
fft 自己的 pool 之外，必須靠 `fft_destroy()` 釋放；在 fft pool 被釋放/重用前，
`fft_destroy()` 必須恰好呼叫一次（漏呼叫會洩漏，呼叫兩次會 double-free）——細節見下方
backend 差異段落，以及 [`../docs/c_user_manual_zh_TW.md`](../docs/c_user_manual_zh_TW.md)
第 5 節的 `create_static_nr`/`destroy_static_nr` 完整範例。

演算法與 malloc 版**逐位元相同**（只差配置方式）：`bin/denoise_mem` 輸出與 `bin/denoise_wav`
byte-for-byte 一致，已對 4 個 preset + stationary、KISS 與 NE10 兩個 backend 分別驗證
（backend 之間本來就不逐位元相同，只比較同一 backend 內 mem vs malloc）。同一機制也覆蓋子模組
`fft_get_mem_size`/`fft_init`、`mcra_get_mem_size`/`mcra_init`、`spp_get_mem_size`/`spp_init`。

**零 malloc 保證，說法更新**：因為 malloc 路徑永遠都編譯進同一份 object（不再靠 `#ifdef` 拿掉），
用 `nm` 檢查 object 檔**一定會看到** `malloc`/`calloc`/`free` 符號——這些符號來自 `_create()`，
只是靜態路徑（`_init()`）在 runtime 上完全不會走到那幾行。保證因此改寫成：**靜態路徑在執行期不
呼叫任何配置器**（`_init()` 本身只做指標運算 + `memset`；`calloc`/`malloc` 只有透過 `_create()` 才
會被觸發到，`_init()` 的呼叫路徑完全不會經過它們）。連預設的 exact-percentile 初始化也不例外——
MCRA 的 percentile gather/quickselect 用預先配好的 `percentile_scratch`（in-place quickselect，
免複製）。`example/main_mem.c` 本身呼叫 `_init()` 系列，執行期同樣 0 malloc。

**FFT + fast_math 現在來自共用的 `../audio_common`**（`make BACKEND=kiss|ne10` 產出
`libaudio_common.a`，`c_impl/Makefile` 直接連結，不再自帶一份 kiss_fft/NE10 原始碼副本）。
backend 差異：KISS 是 **100% 零 malloc**；NE10 是 **partial**——handle 與 work buffer 從 pool
切出，但 NE10 的 twiddle cfg 仍走它自己的一次性內部 malloc（標準 NE10 無外部記憶體 API），
**每幀音訊路徑仍零 malloc**。此分支已在 arm64（Apple Silicon）上原生編譯 + 驗證 NE10 版
mem==malloc byte-for-byte（NE10 輸出本身跟 KISS 不同屬預期，兩個 backend 不互相比較）。

> **Note:** v1.3.0 起 `make` 預設啟用 6 個數學等價優化（100% 相關度），不需要手動指定。

## 編譯開關說明

### 預設啟用（v1.3.0 起，數學等價，`make` 即啟用）

| 開關 | 說明 | 效果 | 相關度 |
|------|------|------|--------|
| `USE_FAST_GAIN_SMOOTHING` | 在 log 域直接 clamp，省略 exp→log 轉換 | 每頻點省 ~150 cycles | 100% |
| `USE_SHARED_XI_RATIO` | SPP 和 Gain 共用 v 計算結果 | 每頻點省 1 次除法 | 100% |
| `USE_OPTIMIZED_MIN_BUFFER` | MCRA 最小值緩衝改為連續記憶體佈局 | 改善 cache 效率 | 100% |
| `USE_OPTIMIZED_E1` | E1(v) 指數積分分支重排 + 共用 log10 | 每頻點省 ~50 cycles | 100% |
| `USE_SINGLE_CLAMP` | 移除冗餘的 gain clamp（僅在 `USE_FAST_GAIN_SMOOTHING` **關閉**時有作用——預設兩者皆開,此 flag 守的分支不會被編譯,等於 no-op;FAST_GAIN_SMOOTHING 的 log-域 clamp 已結構性避免 double-clamp） | (預設組合下無效果) | 100% |
| `USE_INCREMENTAL_MIN` | MCRA 增量最小值追蹤（O(1) 平均） | 省 ~59K cycles/幀 | 100% |

### 手動啟用

| 開關 | 說明 | 效果 | 相關度 |
|------|------|------|--------|
| `USE_FAST_PERCENTILE` | 使用 mean×0.17 近似 20th percentile | 省 ~20KB 記憶體 | ~99.5% |

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

## 嵌入式優化詳解（v1.3.0）

### 化簡 1：消除 sqrtf — magnitude 到 power 域

`process_frame` 原本每幀對 513 頻點計算 `sqrtf(power[k])` 得到 `magnitude`。
但下游所有使用點都把 magnitude **平方回去**，sqrt 與 ² 互相抵銷：

```
原本（3 步，含 sqrtf）:
  magnitude[k]       = sqrtf(power[k])              // sqrt
  enhanced_mag[k]    = gain[k] * magnitude[k]        // ×
  enhanced_psd[k]    = enhanced_mag[k]²              // ²  ← sqrt 被抵銷

化簡後（1 步，無 sqrtf）:
  enhanced_psd[k]    = gain[k]² × power[k]           // 直接算
```

最終音訊重建用 `fft_apply_gain(spectrum, gain)` 直接乘 complex spectrum，不需要 magnitude。
**magnitude 陣列只在 `#ifdef DEBUG_DUMP` 時計算**。

### 化簡 2：MCRA 增量最小值追蹤

MCRA 噪聲估計的瓶頸是每幀掃描 ring buffer（L=32 幀）找最小值：
513 頻點 × 32 幀 = **16,416 次比較/幀**。

增量追蹤利用 ring buffer 的特性，只在必要時重掃描：

```
寫入新值 new_S 到 ring buffer，覆蓋舊值 old_val：

情況 1: new_S ≤ S_min  →  S_min = new_S          (O(1), ~60% 幀)
情況 2: old_val ≈ S_min  →  重掃描找新 S_min      (O(L), ~5% 幀)
情況 3: 其他            →  S_min 不變              (O(1), ~35% 幀)

平均: ~95% 的幀只需 O(1)，從 61,560 比較降至 ~513 比較
```

### 化簡 3：迴圈合併

**mcra_noise_estimator.c** — 6 個獨立 for-k 迴圈 → 2 個 + 場景偵測：
- Loop A: S 時間平滑 + min buffer 寫入 + min 追蹤
- Loop C: SPP indicator + 噪聲更新
- 場景轉換偵測：高頻 gamma + spectral flatness（迴圈後純量判斷）

**mmse_lsa_denoiser.c** — gain_prev save + enhanced_psd_prev save

純結構重排，改善 cache locality，bit-exact。

### 預估節省量

| 優化 | cycles 節省/幀 |
|------|--------------|
| 預設啟用 6 flag | ~138K |
| 消除 sqrtf (513 次) | ~25K |
| MCRA 迴圈合併 | ~5K |
| 增量 min tracking | ~59K |
| process_frame 迴圈合併 | ~3K |
| **合計** | **~230K** |

以 Cortex-M4F @168MHz 估算：每 20ms 幀可省 ~1.4ms。

## 使用方法

### 命令列工具

```bash
./bin/denoise_wav input.wav output.wav                     # 預設 balanced
./bin/denoise_wav input.wav output.wav --nr-mode moderate  # 強度：mild|moderate|balanced|aggressive
./bin/denoise_wav input.wav output.wav --stationary        # 內容保留模式（見下）
./bin/denoise_wav input.wav output.wav --bypass            # 不處理，原樣複製
```

**兩條正交的模式軸：**
- **強度軸** `--nr-mode {mild|moderate|balanced|aggressive}`（`mmse_lsa_config_for_mode`）：全消，越強壓越深。
  4 級深度階梯 g_min = −20 / −25 / −30 / −40 dB（振幅 /20）。所有預設共用 `alpha_xi=0.92`
  （2026-07 musical-noise fix：DD ξ 平滑，壓掉 SPP 抖動＝musical noise；對語音幾乎零成本）。
- **內容軸** `--stationary`（`mmse_lsa_apply_stationary`，疊在強度 base 上）：ReSpeaker-like，**只**移除穩態
  噪聲底噪，保留非穩態內容（語音／音樂／瞬態）。機制 = Wiener 增益下界 `gain ≥ (ξ/(β+ξ))^p`（p=2）
  + music-aware tonal-veto scene-change。此下界**只在 stationary 生效**（`stationary_floor` 預設 false，
  full 模式完全略過 → 與原 V3-2 byte-identical）。鏡像 Python `core/nr_modes.py` 的 `apply_mode`。

### 程式碼整合（freq-domain：caller 自備 FFT / 窗 / OLA）

lib 核心 `mmse_lsa_process()` 是**頻域 API**：吃 `Complex[n_freqs]` 頻譜、吐
`Complex[n_freqs]`（套用 per-bin gain、相位不變）。窗 / rFFT / iFFT / OLA 由
caller 負責（見 `example/main.c` 的完整 freq-domain runner）。

```c
#include "mmse_lsa_denoiser.h"
#include "fft_wrapper.h"

// 1. 創建配置 + 降噪器 + FFT handle
MmseLsaConfig config = mmse_lsa_default_config(16000);
MmseLsaDenoiser* denoiser = mmse_lsa_create(&config);
FftHandle* fft = fft_create(config.fft_size);
int n_freqs = mmse_lsa_get_n_freqs(denoiser);   // fft_size/2 + 1

// 2. 每幀：窗 -> rFFT -> mmse_lsa_process -> iFFT -> 窗 -> OLA
//    （窗 = sqrt(periodic Hann)，50% overlap 即 COLA，無需額外歸一化）
Complex spec_in[n_freqs], spec_out[n_freqs];
fft_forward(fft, windowed_frame /*[fft_size]*/, spec_in);
mmse_lsa_process(denoiser, spec_in, spec_out);  // gain 套到複數頻譜
fft_inverse(fft, spec_out, time_out /*[fft_size]*/);
// out[start..] += time_out * window;  (overlap-add)

// 3. 清理
mmse_lsa_destroy(denoiser);
fft_destroy(fft);
```

### Python↔C 數值對齊驗證 (parity harness)

`tools/parity_nr.py` + `example/parity_runner.c` 提供可重現的埠正確性驗證，
**隔離 FFT 差異**：兩端餵入 byte-identical 的逐幀複數頻譜，只比 gain/SPP/MCRA 運算。

```bash
# 1. Python 端 dump 參考頻譜 + gain
python3 ../tools/parity_nr.py dump --wav ../test_wav/wav/babble_10dB.wav --out /tmp/parity_in.bin

# 2a. C 端 fast-math
make parity && ./bin/parity_runner /tmp/parity_in.bin /tmp/g_fast.bin
python3 ../tools/parity_nr.py compare --ref /tmp/parity_in.bin --c-gains /tmp/g_fast.bin

# 2b. C 端 standard-math（與 make debug 同旗標）→ 近 bit-exact
make clean && make parity BACKEND=kiss EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
./bin/parity_runner /tmp/parity_in.bin /tmp/g_debug.bin
python3 ../tools/parity_nr.py compare --ref /tmp/parity_in.bin --c-gains /tmp/g_debug.bin
```

實測（babble_10dB.wav，6961 幀 × 257 bin）：

| build | worst &#124;Δgain&#124; | median &#124;Δgain&#124; |
|-------|--------------|---------------|
| standard-math (`-DUSE_STANDARD_MATH`) | 2.9e-5 | 1.5e-8 |
| fast-math (預設) | 3.7e-1 | 1.9e-3 |

standard-math 近 bit-exact ⇒ 埠邏輯正確。fast-math 尾端較大來自 `fast_log`
Taylor 近似（小引數 worst ~0.11），會經遞迴平滑放大；屬 fast-math 固有取捨，非埠 bug。

## 使用條件 (Usage Requirements)

- **輸入格式**：單聲道（多聲道自動取第一聲道）、8 / 16 / 48 kHz PCM16 或 32-bit float
- **首 200 ms 需為純噪聲（或無語音）**：用於初始化 MCRA 噪聲底噪，前 `num_init_frames * hop_size` 樣本為 passthrough
- **Frame / hop 於建立後固定**：`frame_size`、`hop_size` 與 `fft_size` 由 `mmse_lsa_default_config(sample_rate)` 等函式在 runtime 依 `sample_rate` 計算，並非編譯時常數；但一旦 `mmse_lsa_create()` 建立 instance 後即固定，不可在串流中途切換。standalone example CLI runner（`example/main.c`、`example/main_mem.c`）另外把 512/256/512 硬編在程式碼中，僅為範例限制
- **Streaming 語義**：`mmse_lsa_process()` 是**頻域 API**——每次呼叫吃 `Complex[n_freqs]` 複數頻譜、
  吐 `Complex[n_freqs]`（套用 per-bin gain、相位不變），lib 核心本身**沒有**內部時域緩衝或 OLA；
  窗函數、rFFT、iFFT、50% overlap-add 全部由 caller 負責（見 `example/main.c` 的完整 freq-domain
  runner，或本文件「程式碼整合」一節）

### 不適用情境（C 端與 Python 完全一致）
- 迴響 / 回聲 → 另配 AEC（`SE/AEC/`）或 dereverb 模組
- 風聲 / 麥克風 buffeting → 統計型單麥 NR 無法處理；建議硬體風罩
- 衝擊 / transient（敲擊、關門、碗盤碰撞）→ MCRA 320 ms tracking window 追不上
- 與目標語音頻譜重疊的干擾（其他人語音、音樂、電視）→ SPP 二元假設不適用

## 調參指引 (Quick Tuning)

> **優先使用 strength mode**：呼叫 `mmse_lsa_config_for_mode(sample_rate, MMSE_LSA_NR_MILD | MODERATE | BALANCED | AGGRESSIVE)`，多數情境足矣。

> **⚠ g_min_db 為 audio 振幅 dB（/20 換算 `10^(db/20)`）** — gain 直接乘幅度譜（無 sqrt），故 floor 是
> 振幅量。越負壓越深（-40 ≈ 0.01、-30 ≈ 0.032、-20 ≈ 0.1）。（xi_min_db / delta_db / scene_change 是
> 功率/SNR dB，維持 /10。）

| Symptom | 建議動作 |
|---|---|
| 殘留底噪吵 | 換 AGGRESSIVE 模式，或手動 `config.g_min_db = -40.0f`（壓更深） |
| 語音變悶 / 細節掉 | 換 MILD 模式，或 `config.g_min_db = -20.0f`、`config.alpha_g = 0.92f` |
| 音樂 / 非穩態內容被吃掉 | 改用 `--stationary`（只移除穩態底噪，保留音樂／瞬態） |
| Musical noise | `config.alpha_g = 0.92f`、`config.xi_min_db = -25.0f` |
| 場景切換慢（開冷氣、進車廂） | `config.scene_change_threshold_db = 7.0f` |
| 場景偵測誤觸發 | `config.scene_change_threshold_db = 12.0f`、`config.scene_change_min_frames = 8` |
| 語音初期被吃掉 | 確認首 200 ms 為純噪聲；若使用場景無法保證，考慮在 caller 端做 VAD gating |

### 不建議在 release 動
- `alpha_xi` / `alpha_s` / `alpha_d` / `L` / `alpha_p` — 內部穩定性依賴這些預設
- `num_init_frames` — 固定 20，改短會讓底噪估計 under-fit
- 編譯開關：v4.2 recommended configuration 即 `make`（已啟用 6 個 bit-exact 優化）

### 當這些都不夠
- 檢查是否屬於「不適用情境」—— 本模組 by design 無法處理風聲 / 衝擊 / 重疊干擾
- 用 `make debug` 重編並開啟 `DEBUG_DUMP` 輸出 `noise_psd / spp / xi / gamma / gain`，與 Python 逐幀對比
- 若非穩態內容（音樂／人聲）被過度壓抑，改用 `--stationary` 內容保留模式
- 註：舊「V4 OMLSA + wind handler」子系統已整個移除（Python 與 C 皆不再提供；adaptive-q 亦驗證 NO-SHIP）

## 配置參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `frame_size` | `sample_rate × 20 / 1000` | 幀長 (20 ms)，例如 16 kHz → 320 samples |
| `hop_size` | `frame_size / 2` | 幀移 (10 ms)，50% overlap；例如 16 kHz → 160 samples |
| `fft_size` | 自動計算 | 次方 2 且 ≥ frame_size。8 kHz → 256；16 kHz → 512；48 kHz → 1024 |
| `alpha_xi` | 0.92 | 先驗 SNR (ξ) DD 平滑；2026-07 musical-noise fix（was 0.88），全預設共用 |
| `q` | 0.5 | 語音先驗機率 |
| `xi_min_db` | -20 | 先驗 SNR 下限 (dB) |
| `alpha_s` | 0.95 | MCRA 時間平滑 |
| `alpha_d` | 0.7 | MCRA 噪聲更新率 |
| `L` | 32 | MCRA 最小值窗口（320ms 場景追蹤）|
| `num_init_frames` | 20 | 噪聲初始化幀數 |
| `scene_change_threshold_db` | 10.0 | 場景轉換高頻 gamma 閾值 (dB) |
| `scene_change_min_frames` | 5 | 場景轉換需連續幀數 |
| `scene_change_blend` | 0.5 | 場景轉換噪聲重置混合比 |
| `scene_change_flatness_threshold` | 0.4 | 場景轉換高頻 spectral flatness 閾值 (Fix #6 v4.2 新增) |
| `g_min_db` | -30.0 | 最小增益（**audio 振幅 dB，/20**；= 0.032 floor） |
| `alpha_g` | 0.88 | 增益平滑因子 |
| `alpha_attack` | 0.3 | 非對稱平滑 Attack |
| `alpha_decay` | 0.88 | 非對稱平滑 Decay (= alpha_g) |
| `stationary_floor` | false | Wiener 增益下界 `(ξ/(β+ξ))^p`；**僅 `--stationary` 開啟**，full 不受影響 |
| `scene_change_tonal_veto` | false | tonal 低頻（音樂）跳過噪聲底噪重置；僅 stationary |

## 延遲

算法延遲 ≈ `frame_size`（以 samples 計；取 1 幀 + OLA 緩衝）。`frame_size` 固定為 20 ms。

| 採樣率 | frame_size | hop_size | fft_size | 延遲 |
|--------|-----------|----------|----------|------|
| 8 kHz  | 160 samples | 80 samples  | 256  | 20 ms |
| 16 kHz | 320 samples | 160 samples | 512  | 20 ms |
| 48 kHz | 960 samples | 480 samples | 1024 | 20 ms |

> **注意**: 初始化期間（前 20 幀 = 200 ms）音頻 lightweight passthrough（gain=1），MCRA 累積噪聲統計；之後開始正常降噪處理。

## 檔案結構

```
c_impl/
├── include/
│   ├── mmse_lsa_denoiser.h    # 主要 API（malloc + 靜態記憶體 create/get_mem_size/init）
│   ├── mmse_lsa_types.h       # 配置結構和預設值
│   ├── mcra_noise_estimator.h # MCRA 噪聲估計
│   └── spp_estimator.h        # SPP 估計
├── src/
│   ├── mmse_lsa_denoiser.c    # 主模組（含 MMSE-LSA 增益計算）
│   ├── mcra_noise_estimator.c
│   └── spp_estimator.c
├── example/
│   ├── main.c                 # 命令列工具（malloc / heap 路徑）
│   ├── main_mem.c              # 命令列工具（靜態記憶體路徑，見上一節）
│   ├── parity_runner.c         # Python↔C parity harness 的 C 端
│   └── wav_io.h                # WAV 讀寫
├── Makefile
├── README.md                  # 本文件
└── CHANGELOG.md               # 改動記錄

../audio_common/                # 共用層（本 repo 之外，siblings 目錄）：
├── include/fft_wrapper.h        #   Complex 型別、FFT heap+靜態記憶體 API、ALIGN16
├── include/fast_math.h          #   快速數學函數 (LUT+Taylor)
└── lib/{kiss_fft,ne10}/         #   兩個 FFT backend 的原始碼；`make BACKEND=kiss|ne10 lib`
                                  #   產出 bin/<backend>/libaudio_common.a，c_impl 連結它
```

## 記憶體使用

- **基本使用** (16 kHz, USE_FAST_PERCENTILE)：~50 KB
- **精確 percentile** (`make` 預設不啟用 USE_FAST_PERCENTILE)：+20 KB
- **48 kHz** (n_freqs=513, L=32)：~130 KB；MCRA `min_buffer` 約 ~66 KB
- **v4.2 新增**：Fix #3 加的 `noise_psd_prev` 每實例 +`n_freqs × 4` bytes（16 kHz ~1 KB）


## 參考文獻

1. Ephraim, Y., & Malah, D. (1985). Speech enhancement using a minimum mean-square error log-spectral amplitude estimator. IEEE TASSP.
2. Cohen, I., & Berdugo, B. (2002). Noise estimation by minima controlled recursive averaging. IEEE SAP.
