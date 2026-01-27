# MMSE-LSA Speech Denoiser (V3-2 C Implementation)

基於 Ephraim-Malah 1985 的 MMSE-LSA (Minimum Mean Square Error Log-Spectral Amplitude) 語音降噪演算法 C 實現。

## 特性

- **Streaming 處理**：以 hop_size 為單位輸入/輸出，適合即時處理
- **MCRA 噪聲估計**：Cohen & Berdugo (2002) 最小值控制遞迴平均
- **SPP 語音存在機率**：Decision Directed 方法
- **非對稱增益平滑**：Attack/Decay 分離控制
- **可配置優化開關**：透過編譯開關選擇精度/速度權衡

## 編譯

### 基本編譯

```bash
make
```

### 調試版本（與 Python 輸出最接近）

```bash
make EXTRA_CFLAGS="-DUSE_STANDARD_MATH"
```

### 優化版本（全部加速開關）

```bash
make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE -DUSE_FAST_GAIN_SMOOTHING -DUSE_SHARED_XI_RATIO -DUSE_OPTIMIZED_MIN_BUFFER -DUSE_OPTIMIZED_E1 -DUSE_SINGLE_CLAMP"
```

## 編譯開關說明

| 開關 | 說明 | 效果 | 相關度 |
|------|------|------|--------|
| `USE_STANDARD_MATH` | 使用標準數學函數 | 精度最高，適合調試 | 基準 |
| `USE_FAST_PERCENTILE` | 使用 mean×0.17 近似 20th percentile | 省 ~20KB 記憶體 | ~99.5% |
| `USE_FAST_GAIN_SMOOTHING` | 在 log 域直接 clamp，省略 exp→log 轉換 | 每頻點省 ~150 cycles | 100% |
| `USE_SHARED_XI_RATIO` | SPP 和 Gain 共用 v 計算結果 | 每頻點省 1 次除法 | 100% |
| `USE_OPTIMIZED_MIN_BUFFER` | 優化 MCRA 最小值追蹤的記憶體佈局 | 改善 cache 效率 | 100% |
| `USE_OPTIMIZED_E1` | 優化 E1(v) 指數積分分支順序 | 每頻點省 ~50 cycles | 100% |
| `USE_SINGLE_CLAMP` | 移除冗餘的 clamp 操作 | 每頻點省 ~10 cycles | 100% |

### 推薦配置

| 場景 | 配置 |
|------|------|
| 調試/驗證 | `make EXTRA_CFLAGS="-DUSE_STANDARD_MATH"` |
| 標準使用 | `make` |
| 嵌入式/即時 | `make EXTRA_CFLAGS="-DUSE_FAST_PERCENTILE -DUSE_FAST_GAIN_SMOOTHING -DUSE_SHARED_XI_RATIO -DUSE_OPTIMIZED_MIN_BUFFER -DUSE_OPTIMIZED_E1 -DUSE_SINGLE_CLAMP"` |

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
| `frame_size_ms` | 20 | 幀長 (ms) |
| `frame_shift_ms` | 10 | 幀移/hop size (ms) |
| `fft_size` | 自動計算 | FFT 點數（8kHz→256, 16kHz→512, 48kHz→1024）|
| `alpha_xi` | 0.92 | 先驗 SNR 平滑因子 |
| `q` | 0.5 | 語音先驗機率 |
| `xi_min_db` | -20 | 先驗 SNR 下限 (dB) |
| `alpha_s` | 0.8 | MCRA 時間平滑 |
| `alpha_d` | 0.95 | MCRA 噪聲更新率 |
| `L` | 120 | MCRA 最小值窗口 |
| `num_init_frames` | 20 | 噪聲初始化幀數 |
| `g_min_db` | -12.5 | 最小增益 (dB) |
| `alpha_g` | 0.8 | 增益平滑因子 |
| `alpha_attack` | 0.3 | 非對稱平滑 Attack |
| `alpha_decay` | 0.7 | 非對稱平滑 Decay |

## 延遲

總延遲 = frame_size + (num_init_frames × hop_size)

| 採樣率 | frame_size | 初始化延遲 | 總延遲 |
|--------|-----------|-----------|--------|
| 8 kHz | 160 | 1600 | 1760 samples (220 ms) |
| 16 kHz | 320 | 3200 | 3520 samples (220 ms) |
| 48 kHz | 960 | 9600 | 10560 samples (220 ms) |

## 檔案結構

```
c_impl/
├── include/
│   ├── mmse_lsa_denoiser.h    # 主要 API
│   ├── mmse_lsa_types.h       # 配置結構和預設值
│   ├── mcra_noise_estimator.h # MCRA 噪聲估計
│   ├── spp_estimator.h        # SPP 估計
│   ├── mmse_lsa_gain.h        # MMSE-LSA 增益計算
│   ├── fft_wrapper.h          # FFT 接口
│   └── fast_math.h            # 快速數學函數 (LUT+Taylor)
├── src/
│   ├── mmse_lsa_denoiser.c
│   ├── mcra_noise_estimator.c
│   ├── spp_estimator.c
│   ├── mmse_lsa_gain.c
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
- MCRA 最小值緩衝: L × n_freqs × 4 = 96 × 257 × 4 ≈ 98KB

## 參考文獻

1. Ephraim, Y., & Malah, D. (1985). Speech enhancement using a minimum mean-square error log-spectral amplitude estimator. IEEE TASSP.
2. Cohen, I., & Berdugo, B. (2002). Noise estimation by minima controlled recursive averaging. IEEE SAP.
