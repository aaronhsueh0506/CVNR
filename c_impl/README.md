# MMSE-LSA Speech Denoiser (V3-2 C Implementation)

基於 Ephraim-Malah 1985 的 MMSE-LSA (Minimum Mean Square Error Log-Spectral Amplitude) 語音降噪演算法 C 實現。

## 特性

- **Streaming 處理**：以 hop_size 為單位輸入/輸出，適合即時處理
- **MCRA 噪聲估計**：Cohen & Berdugo (2002) 最小值控制遞迴平均
- **SPP 語音存在機率**：Decision Directed 方法
- **非對稱增益平滑**：Attack/Decay 分離控制
- **可配置優化開關**：透過編譯開關選擇精度/速度權衡
- **場景轉換偵測**：高頻 gamma + spectral flatness 雙重條件，自動追蹤噪聲環境變化
- **與 Python V3-2 完全同步**：參數、場景偵測邏輯一致

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
./bin/denoise_wav input.wav output.wav
```

### 程式碼整合

```c
#include "mmse_lsa_denoiser.h"

// 1. 創建配置
MmseLsaConfig config = mmse_lsa_default_config(16000);  // 16kHz

// 2. 初始化降噪器
MmseLsaDenoiser* denoiser = mmse_lsa_create(&config);

// 3. 獲取 hop_size
int hop_size = mmse_lsa_get_hop_size(denoiser);

// 4. 分配緩衝
float* in_buf = malloc(hop_size * sizeof(float));
float* out_buf = malloc(hop_size * sizeof(float));

// 5. 串流處理（每次處理 hop_size 樣本）
while (has_more_samples()) {
    read_samples(in_buf, hop_size);
    mmse_lsa_process(denoiser, in_buf, out_buf);
    write_samples(out_buf, hop_size);
}

// 6. 清理
mmse_lsa_destroy(denoiser);
free(in_buf);
free(out_buf);
```

## 配置參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `frame_size` | 512 | 幀長 (samples, 512 @ 16kHz = 32ms) |
| `hop_size` | 256 | 幀移/hop size (samples, 256 @ 16kHz = 16ms) |
| `fft_size` | 自動計算 | FFT 點數（8kHz→256, 16kHz→512, 48kHz→1024）|
| `alpha_xi` | 0.88 | 先驗 SNR 平滑因子 |
| `q` | 0.5 | 語音先驗機率 |
| `xi_min_db` | -20 | 先驗 SNR 下限 (dB) |
| `alpha_s` | 0.95 | MCRA 時間平滑 |
| `alpha_d` | 0.7 | MCRA 噪聲更新率 |
| `L` | 32 | MCRA 最小值窗口（320ms 場景追蹤）|
| `num_init_frames` | 20 | 噪聲初始化幀數 |
| `scene_change_threshold_db` | 10.0 | 場景轉換高頻 gamma 閾值 (dB) |
| `scene_change_min_frames` | 5 | 場景轉換需連續幀數 |
| `scene_change_blend` | 0.5 | 場景轉換噪聲重置混合比 |
| `g_min_db` | -15.0 | 最小增益 (dB) |
| `alpha_g` | 0.88 | 增益平滑因子 |
| `alpha_attack` | 0.3 | 非對稱平滑 Attack |
| `alpha_decay` | 0.88 | 非對稱平滑 Decay (= alpha_g) |

## 延遲

算法延遲 = frame_size（取決於採樣率）

| 採樣率 | frame_size | hop_size | 延遲 |
|--------|-----------|----------|------|
| 8 kHz | 256 samples | 128 samples | 32 ms |
| 16 kHz | 512 samples | 256 samples | 32 ms |
| 48 kHz | 1024 samples | 512 samples | ~21 ms |

> **注意**: 初始化期間（前 20 幀）音頻直接 pass-through（不做降噪），
> 之後開始正常降噪處理。

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

- 基本使用: ~50KB (取決於 FFT size 和 n_freqs)
- 精確 percentile (無 USE_FAST_PERCENTILE): +20KB
- MCRA 最小值緩衝: L × n_freqs × 4 = 32 × 513 × 4 ≈ **64KB** (48kHz)

## 參考文獻

1. Ephraim, Y., & Malah, D. (1985). Speech enhancement using a minimum mean-square error log-spectral amplitude estimator. IEEE TASSP.
2. Cohen, I., & Berdugo, B. (2002). Noise estimation by minima controlled recursive averaging. IEEE SAP.
