# Changelog

所有重要的改動都會記錄在此文件中。

## [v1.1.0] - 2026-01-27

### 新增優化開關

#### USE_FAST_GAIN_SMOOTHING
- **檔案**: `src/mmse_lsa_gain.c`
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
  - `include/mmse_lsa_gain.h` - 新增 `mmse_lsa_gain_calculate_ex()`
  - `src/mmse_lsa_gain.c` - 實現 `mmse_lsa_gain_calculate_ex()`
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
- **檔案**: `src/mmse_lsa_gain.c`
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

## 注意事項

1. 多個優化開關可以同時使用
2. `USE_STANDARD_MATH` 會覆蓋 fast_math.h 中的優化函數
3. 所有優化都經過相關度測試，確保與原版輸出高度一致
