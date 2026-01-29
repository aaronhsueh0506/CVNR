# Changelog

所有重要的改動都會記錄在此文件中。

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
  - eta sigmoid 計算放在兩迴圈之間（純量運算）
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
