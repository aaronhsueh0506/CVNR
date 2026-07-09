# OMLSA Speech Denoiser — C Implementation (V3-2 主線)

> **Release**: v4.2.0 · Part A Review 修復已同步
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

### 靜態記憶體版本（嵌入式，零 malloc / `USE_EXT_MEM`）

```bash
make mem            # → bin/denoise_mem（範例 example/main_mem.c）
```

`-DUSE_EXT_MEM` 下，denoiser、MCRA、SPP、FFT 的**所有內部狀態都從呼叫端提供的一塊記憶體切出**，
音訊路徑上**完全不呼叫 malloc/free**。用法：先用 `query_memsize()` 問要多少，配一塊
（static 陣列，或 Novatek `hd_common_mem` block），交給 `create(..., mem, size)`：

```c
static uint8_t pool[/* >= mmse_lsa_query_memsize(&cfg) */] __attribute__((aligned(16)));
size_t need = mmse_lsa_query_memsize(&cfg);          // 先問大小
MmseLsaDenoiser* d = mmse_lsa_create(&cfg, pool, sizeof pool);  // 零 malloc
/* ... 每幀 mmse_lsa_process()，音訊路徑無任何配置 ... */
mmse_lsa_destroy(d);                                 // no-op（記憶體由呼叫端持有）
```

演算法與 malloc 版**逐位元相同**（只差配置方式）：`bin/denoise_mem` 輸出與 `bin/denoise_wav`
byte-for-byte 一致，已對 4 個 preset + stationary 驗證。同一機制也覆蓋子模組
`fft_query_memsize`/`mcra_query_memsize`/`spp_query_memsize` + 各自的 `create(..., mem, size)`。
> 目前 `make mem` 為 KISS FFT backend；NE10（`fft_wrapper_ne10.c`）的 ext-mem 變體尚未接（NE10 自行
> 管理 twiddle 配置），但 denoiser/MCRA/SPP 的 ext-mem 路徑與 backend 無關。

> **Note:** v1.3.0 起 `make` 預設啟用 6 個數學等價優化（100% 相關度），不需要手動指定。

## 編譯開關說明

### 預設啟用（v1.3.0 起，數學等價，`make` 即啟用）

| 開關 | 說明 | 效果 | 相關度 |
|------|------|------|--------|
| `USE_FAST_GAIN_SMOOTHING` | 在 log 域直接 clamp，省略 exp→log 轉換 | 每頻點省 ~150 cycles | 100% |
| `USE_SHARED_XI_RATIO` | SPP 和 Gain 共用 v 計算結果 | 每頻點省 1 次除法 | 100% |
| `USE_OPTIMIZED_MIN_BUFFER` | MCRA 最小值緩衝改為連續記憶體佈局 | 改善 cache 效率 | 100% |
| `USE_OPTIMIZED_E1` | E1(v) 指數積分分支重排 + 共用 log10 | 每頻點省 ~50 cycles | 100% |
| `USE_SINGLE_CLAMP` | 移除冗餘的 gain clamp | 每頻點省 ~10 cycles | 100% |
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
| 嵌入式/零 malloc（呼叫端提供記憶體） | `make mem`（`-DUSE_EXT_MEM`） |

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
make clean && make parity CFLAGS="-Wall -Wextra -O2 -std=c99 -I./include -I./example -I./lib/kiss_fft -DUSE_STANDARD_MATH"
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
- **Frame / hop 編譯時固定**：不可在執行時切換 `frame_size` 或 `hop_size`
- **Streaming 語義**：每次呼叫 `mmse_lsa_process()` 輸入 hop_size 樣本，輸出 hop_size 樣本；內部有 50% overlap OLA 緩衝

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
│   ├── mmse_lsa_denoiser.h    # 主要 API
│   ├── mmse_lsa_types.h       # 配置結構和預設值
│   ├── mcra_noise_estimator.h # MCRA 噪聲估計
│   ├── spp_estimator.h        # SPP 估計
│   ├── fft_wrapper.h          # FFT 接口
│   └── fast_math.h            # 快速數學函數 (LUT+Taylor)
├── src/
│   ├── mmse_lsa_denoiser.c    # 主模組（含 MMSE-LSA 增益計算）
│   ├── mcra_noise_estimator.c
│   ├── spp_estimator.c
│   └── fft_wrapper.c
├── lib/
│   └── kiss_fft/              # KISS FFT 庫
├── example/
│   ├── main.c                 # 命令列工具
│   └── wav_io.h               # WAV 讀寫
├── Makefile
├── README.md                  # 本文件
└── CHANGELOG.md               # 改動記錄
```

## 記憶體使用

- **基本使用** (16 kHz, USE_FAST_PERCENTILE)：~50 KB
- **精確 percentile** (`make` 預設不啟用 USE_FAST_PERCENTILE)：+20 KB
- **48 kHz** (n_freqs=513, L=32)：~130 KB；MCRA `min_buffer` 約 ~66 KB
- **v4.2 新增**：Fix #3 加的 `noise_psd_prev` 每實例 +`n_freqs × 4` bytes（16 kHz ~1 KB）


## 參考文獻

1. Ephraim, Y., & Malah, D. (1985). Speech enhancement using a minimum mean-square error log-spectral amplitude estimator. IEEE TASSP.
2. Cohen, I., & Berdugo, B. (2002). Noise estimation by minima controlled recursive averaging. IEEE SAP.
