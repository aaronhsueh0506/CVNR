# 變更記錄 (Changelog)

本文件記錄所有重要的變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

## [4.0.0] - 2026-03-03

### 新增 (Added)
- ✨ **V4: MCRA-MMSE-LSA with Zhihu Optimized Parameters**:
  - 基於 V3-2，採用知乎文章建議的激進參數組合
  - 配置文件: `config/v4_config.yaml`
  - 使用 `MmseLsaDenoiser` 類（與 V3-2 共用實現）

### 修改 (Changed)
- ⚠️ **MCRA 默認參數調整（高風險修改）**:
  - `alpha_s`: 0.9 → 0.7 (更快時間響應)
  - `alpha_d`: 0.85 → 0.0 (噪聲更新純 SPP 控制，極度激進)
  - `L`: 96 → 5 (最小值窗口從 960ms 縮短到 50ms，極度激進)
  - `init percentile`: 20th → 30th (更準確的初始化)
  - ⚠️ **風險**: alpha_d=0 + L=5 組合極度依賴 SPP 準確性，需測試驗證

- 🔧 **移除 Decision Directed 兼容模式**:
  - `core/spp_estimator.py`: 強制要求傳入 `enhanced_psd_prev`
  - 移除使用舊噪聲的錯誤近似計算
  - 確保所有 SNR 估計使用當前幀噪聲

### 修正 (Fixed)
- 🐛 **Eta 場景轉換偵測默認關閉**:
  - 測試結果證明 eta 導致 PESQ 下降（threshold=2 平均 -0.41, threshold=10 平均 -0.06）
  - 無法區分"語音開始"與"場景變化"，容易誤觸發
  - Python 配置: `enable_eta: false`
  - C 實現: `config.enable_eta = false`

### 歸檔 (Archived)
- 📦 **舊 V4 IMCRA-OMLSA 版本歸檔**:
  - 移動到 `archived_v4_imcra/` 目錄
  - 包含: `v4_imcra_config.yaml`, `v4_imcra_omlsa.py`
  - 理由: 新 V4 採用不同的演算法路線（MCRA vs IMCRA）

### 修改文件
1. `core/noise_estimators/mcra.py` - 默認參數調整、初始化百分位數
2. `core/spp_estimator.py` - 移除 DD 兼容模式
3. `config/v4_config.yaml` - 新建 V4 配置
4. `c_impl/example/main.c` - Eta 默認關閉
5. `README.md` - 版本更新
6. `CHANGELOG.md` - 記錄變更

### 測試結果 (2026-03-03)

**完整測試**: 13 個測試文件 (8 test_wav + 5 VCTK)

#### Alpha_d 優化測試
| alpha_d | 平均 PESQ | ΔPESQ | 說明 |
|---------|----------|-------|------|
| 0.95 | 2.127 | 0.000 | ✓ **最佳**（V3-2 baseline） |
| 0.85 | 2.121 | -0.006 | 非常接近 |
| 0.70 | 2.102 | -0.024 | 輕微下降 |
| 0.50 | 2.087 | -0.040 | 明顯下降 |
| 0.30 | 2.067 | -0.060 | 顯著下降 |
| 0.00 | 2.034 | -0.092 | ⚠️ **知乎原始值，效果最差** |

**明確趨勢**: alpha_d 越高，PESQ 越好

#### 逐步參數測試
| 配置 | ΔPESQ | 結論 |
|------|-------|------|
| 僅改 alpha_s (0.8→0.7) | 0.0000 | ✓ 無負面影響 |
| alpha_s + L (120→5) | 0.0000 | ✓ **L=5 無負面影響** |
| alpha_s + alpha_d (0.95→0) | -0.1524 | ⚠️ **alpha_d=0 是唯一問題** |
| V4 Full (知乎原始參數) | -0.1524 | ⚠️ 效果最差 |

#### 測試腳本
- `compare_v4_v32.py`: V4 vs V3-2 baseline 比較（初步測試）
- `test_v4_gradual.py`: 逐步參數測試，分離每個參數的影響
- `test_v4_vctk_scene.py`: VCTK + 場景轉換測試
- `find_best_alpha_d.py`: 系統性 alpha_d 優化測試

### 最終決策
基於測試結果，V4 最終採用：
- ✓ **alpha_s = 0.7**: 知乎建議，測試證明無負面影響
- ✓ **L = 5**: 知乎建議，測試證明無負面影響且響應更快
- ✗ **alpha_d = 0**: 知乎建議，**測試證明造成 -0.092 PESQ 下降，不採用**
- ✓ **alpha_d = 0.95**: 保持 V3-2 baseline，測試證明最佳

**結論**: 知乎文章的 alpha_s 和 L 參數有效，但 alpha_d=0 不適用於一般語音降噪場景。

## [2.7.0] - 2026-02-03

### 修正 (Fixed)
- 🐛 **MCRA Eta 場景轉換偵測修正 (Strategy K)**:
  - 舊版 sigmoid `η = 0.95 / (1 + e^(slope*(β-θ)))` 上限 0.95 導致語音幀 `tilde_alpha_d` 下降，噪聲更新速度增加 ~10x
  - 新版: 平滑能量比 + hard threshold
    - `E_smooth = 0.7 * E_smooth_prev + 0.3 * E_cur`
    - `β = E_smooth / E_smooth_prev`
    - `β > θ` → `η = 0.1`（場景突變，加速噪聲更新）
    - `β ≤ θ` → `η = 1.0`（正常，完全不干擾 α_d）
  - VCTK/DEMAND 824 files 驗證:
    - 舊 eta: PESQ +0.085, STOI -0.068
    - 新 eta: PESQ +0.399, STOI -0.010
    - 不開 eta: PESQ +0.437, STOI -0.007

### 修改文件
1. `core/noise_estimators/mcra.py` - `_compute_eta()` 方法重寫
2. `c_impl/src/mcra_noise_estimator.c` - 對應 C 實作更新

## [2.5.0] - 2026-01-16

### 重構 (Refactored)
- ✨ **MCRA 單/雙視窗模式切換**: 新增 `use_dual_window` 參數
  - `True` (預設)：雙視窗模式，記憶體效率高 O(3×n_freqs)
  - `False`：單視窗 FIFO 緩衝區模式 O(L×n_freqs)
  - 方便效果比較實驗

- 🧹 **清理冗餘程式碼**:
  - 移除 `spp_estimator.py` 的 fast startup 功能 (死代碼)
  - 移除 `imcra.py` 的 fast tracking 功能 (死代碼)
  - 移除 `reconstructor.py` 的 `apply_gain()` 和 `reconstruct_from_spectra()` 方法 (未使用)
  - 保留 `recursive_average.py` 的 fast 功能 (可能有用)

### 驗證 (Verified)
- ✅ **IMCRA 最小值重置邏輯正確**: 確認 Cohen 2003 FIFO 緩衝區方法的遺忘機制
  - `S_min_sw = S_smoothed.copy()` 在第 213 行存在
  - 每 V 幀重置子視窗最小值
  - 噪聲增加時最多 L = U × V 幀後追上

### 修改文件
1. `core/noise_estimators/mcra.py` - 添加 `use_dual_window` 參數，支持單/雙視窗切換
2. `core/spp_estimator.py` - 移除 fast startup 相關代碼
3. `core/noise_estimators/imcra.py` - 移除 fast tracking 相關代碼
4. `core/reconstructor.py` - 移除未使用的方法

---

## [2.4.0] - 2026-01-12

### 新增 (Added)
- ✨ **V3-2 return_spp 支持**: 添加 SPP 歷史數據返回功能
  - `denoise()` 方法新增 `return_spp` 參數
  - `denoise_spectrum()` 方法新增 SPP 收集邏輯
  - 與 V3, V3-3, V3-4 統一 API

### 改進 (Changed)
- ⬆️ **V3 系列 50-trial Optuna 參數優化**
  - 目標函數: 0.8×PESQ + 0.2×STOI
  - 固定 SPP 參數: alpha_xi=0.95, q=0.3, xi_min_db=-25.0
  - 僅優化 Gain 參數: g_min_db, alpha_g
  - 移除 0dB SNR 測試 case

- ⬆️ **優化結果更新至配置文件**:
  | 版本 | g_min_db | alpha_g | ΔPESQ |
  |------|----------|---------|-------|
  | V3   | -15.0    | 0.85    | +0.403 |
  | V3-2 | -15.0    | 0.90    | +0.399 |
  | V3-3 | -15.0    | 0.85    | +0.354 |
  | V3-4 | -25.0    | 0.85    | +0.197 |

- ⬆️ **SPP 可視化配色方案**: `gray_r` 取代 `jet`
  - 更直觀：黑色=高 SPP（語音），白色=低 SPP（噪聲）
  - 符合 SPP 物理意義

### 修改文件
1. `config/v3_config.yaml` - g_min_db=-15.0, alpha_g=0.85
2. `config/v3_2_config.yaml` - g_min_db=-15.0, alpha_g=0.90
3. `config/v3_3_config.yaml` - g_min_db=-15.0, alpha_g=0.85
4. `config/v3_4_config.yaml` - g_min_db=-25.0, alpha_g=0.85
5. `denoisers/v3_2_mmse_lsa.py` - 添加 return_spp 支持
6. `utils/visualization.py` - SPP colormap 改為 gray_r
7. `tools/parameter_optimizer.py` - 固定 SPP 參數，搜索空間調整

---

## [2.3.0] - 2026-01-08

### 重構 (Refactored)
- ✨ **整合場景轉換偵測至 MCRA**：移除外部 NoiseChangeDetector 和 TransitionDetector
  - 使用 Cohen & Berdugo 的 Dual-Window Minima Tracking 方法
  - MCRA 內建處理噪聲場景變化，每 L 幀自動更新最小值
  - 簡化降噪器架構，移除 `enable_noise_tracking` 參數

### 改進 (Changed)
- ⬆️ **MCRA 雙視窗最小值追蹤**：
  - 新增 `S_min_sw` (子視窗最小值)
  - 新增 `stored_min` (存儲的最小值)
  - 新增 `counter` (視窗計數器)
  - 移除 `min_buffer` (FIFO 緩衝區)

### 技術細節 (Technical Details)

#### Dual-Window Minima Tracking

```python
# 雙視窗最小值追蹤 (Cohen & Berdugo 2002)
self.S_min = np.minimum(self.S_min, self.S)
self.S_min_sw = np.minimum(self.S_min_sw, self.S)
self.counter += 1

# 每 L 幀強制更新（自動適應噪聲場景變化）
if self.counter >= self.L:
    self.S_min = np.minimum(self.stored_min, self.S_min_sw)
    self.stored_min = self.S_min_sw.copy()
    self.S_min_sw = self.S.copy()
    self.counter = 0
```

**優點**:
- 內建場景變化適應
- 減少程式碼重複
- 消除邏輯衝突
- 簡化降噪器介面

### 刪除 (Removed)
- ❌ `core/noise_change_detector.py` - 外部噪聲變化檢測器
- ❌ `core/transition_detector.py` - 外部場景轉換檢測器
- ❌ 所有降噪器的 `enable_noise_tracking` 參數
- ❌ `trigger_fast_adaptation()` 方法

### 修改文件
1. `core/noise_estimators/mcra.py` - 升級為雙視窗最小值追蹤
2. `denoisers/v3_spp_mmse.py` - 移除 NoiseChangeDetector
3. `denoisers/v3_2_mmse_lsa.py` - 移除 NoiseChangeDetector
4. `denoisers/v3_3_pmmse.py` - 移除 NoiseChangeDetector 和 TransitionDetector
5. `denoisers/v3_4_laplacian_mmse.py` - 移除 NoiseChangeDetector
6. `denoisers/v4_imcra_omlsa.py` - 移除 NoiseChangeDetector
7. `regenerate_all.py` - 移除 enable_noise_tracking 參數處理
8. `process_audio.py` - 移除 enable_noise_tracking 參數處理

---

## [2.2.0] - 2026-01-08

### 新增 (Added)
- ✨ **V2.2 版本發布**: Wiener Filter with DD + SPP-gated noise update
  - 啟用 Decision-Directed (DD) 方法估計先驗 SNR
  - 使用 Sigmoid(gamma-1) 近似 SPP 進行軟判決噪聲更新
  - ΔPESQ: +0.035 (相較噪聲輸入)

- ✨ **V2 MCRA 噪聲估計支持** (實驗性)
  - 新增 MCRA 噪聲估計器選項
  - 改進 MCRA 初始化：使用 20th 百分位數避免語音幀污染
  - 注意：MCRA 對 V2 Wiener 效果有限，建議使用 recursive_average

### 改進 (Changed)
- ⬆️ **V3-3 (PMMSE) 重新實作**
  - 使用 Wolfe & Godsill (2003) β=0.5 公式
  - G_PM = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)
  - 使用 `scipy.special.i0e` 避免數值溢出
  - ΔPESQ: +0.339

- ⬆️ **V3-4 (Laplacian-MMSE) 重新實作**
  - 使用 Chen & Loizou (2007) 公式
  - G_Lap = (sqrt(π)/2) · sqrt(v) · exp(-v/2) · I0(v/2)
  - Laplacian 先驗適合語音頻譜稀疏性
  - ΔPESQ: +0.376

### 文檔 (Documentation)
- 📝 **各版本噪聲估計方法說明**

| 版本 | 噪聲估計器 | SPP 來源 | 說明 |
|------|-----------|---------|------|
| V1 | SimpleAverage | 無 | 前 N 幀平均 |
| V2 | RecursiveAverage | Sigmoid 近似 | DD 方法估計先驗 SNR |
| V3~V3-4 | RecursiveAverage | SppEstimator (Bayesian) | 貝葉斯 SPP 軟判決 |
| V4 | IMCRA | 內部兩階段計算 | Cohen 2003 兩階段結構 |

### 修改文件
1. `config/v2_config.yaml` - 更新為 V2.2，添加詳細說明
2. `config/v3_3_config.yaml` - 添加 Wolfe & Godsill 公式說明
3. `config/v3_4_config.yaml` - 添加 Chen & Loizou 公式說明
4. `core/gain_calculators/pmmse.py` - Wolfe & Godsill β=0.5 實作
5. `core/gain_calculators/laplacian_mmse.py` - Chen & Loizou 實作
6. `core/noise_estimators/mcra.py` - 改進初始化策略
7. `denoisers/v2_wiener.py` - 支持 MCRA 噪聲估計
8. `regenerate_all.py` - 支持 V2 MCRA 參數

---

## [2.1.2] - 2026-01-06

### 修復 (Fixed)
- 🐛 **segSNR 計算 bug 修復**
  - **問題**: `tools/benchmark_comparison.py` 錯誤地將 `sample_rate` (16000) 傳遞給 `calculate_segmental_snr()` 的 `frame_size` 參數
  - **影響**: 之前的 segSNR 排名數據不準確
  - **修復**: 使用正確的 `frame_size=256` (16ms @ 16kHz), `hop_size=128` (50% overlap)

### 發現 (Discovered)
- ⚠️ **V4 (IMCRA-OMLSA) 過度抑制問題**
  - **症狀**: 輸出能量僅保留輸入的 ~1%（正常應為 20-70%）
  - **原因**: OMLSA 增益計算中的幀間限制和時間平滑導致增益惡性循環下降
  - **影響**: 雖然 segSNR 數值看起來不錯 (+4.60 dB)，但 PESQ 最低 (1.19)，實際語音被嚴重削弱
  - **建議**: 使用 V3 替代 V4

### 修正後性能結果（benchmark_comparison.py）

| 排名 | 方法 | segSNR 改善 (dB) | PESQ | STOI | 備註 |
|------|------|------------------|------|------|------|
| 🥇 1 | **RNNoise** | **+4.72** | 1.69 | **0.90** | 深度學習，綜合最佳 |
| 🥈 2 | V4 (IMCRA-OMLSA) | +4.60 | 1.19 | 0.20 | ⚠️ 過度抑制 |
| 🥉 3 | **V3 (SPP-MMSE)** | +2.65 | **1.52** | 0.17 | **推薦：傳統算法最佳** |
| 4 | V3-2 (MMSE-LSA) | +2.56 | 1.43 | 0.14 | |
| 5 | V2 (Wiener) | +2.54 | 1.27 | 0.14 | |
| 6 | Speex | +2.40 | 1.44 | 0.88 | |
| 7 | V3-4 (Laplacian) | +2.33 | 1.43 | 0.17 | |
| 8 | V1 (Spectral Sub) | +2.11 | 1.44 | 0.13 | |
| 9 | V3-3 (PMMSE) | +2.08 | 1.43 | 0.15 | |

### 修改文件
1. `tools/benchmark_comparison.py` - 修復 segSNR 計算的 frame_size 參數
2. `README.md` - 更新排名和推薦
3. `CHANGELOG.md` - 新增此版本記錄

---

## [2.1.1] - 2026-01-06

### 改進 (Changed)
- ⬆️ **V3 系列參數同步優化**
  - 將最優參數 `alpha_xi=0.96` 同步到所有 V3 變體（V3, V3-2, V3-3, V3-4）
  - 來源：V3-3 參數調優實驗結果
  - 影響：提升所有 V3 系列的 SNR 平滑效果

### 修改文件
1. `config/v3_config.yaml` - alpha_xi: 0.95 → 0.96
2. `config/v3_2_config.yaml` - alpha_xi: 0.92 → 0.96
3. `config/v3_3_config.yaml` - alpha_xi: 0.90 → 0.96
4. `config/v3_4_config.yaml` - alpha_xi: 0.92 → 0.96

---

## [2.1.0] - 2026-01-05

### 新增 (Added)
- ✨ **V3-3/V3-4 參數優化**: 採用 V3-2 對齊參數
  - V3-3: PESQ 從 1.458 提升至 1.733 (+18.9%)
  - V3-4: STOI 達到 0.874（傳統算法最佳）
  - 核心發現：SNR Adaptive (enable: true, base_g_min_db: -12.0) 是高性能的關鍵

- ✨ **Clean 保護測試**: 新增 clean.wav 高 SNR 測試用例
  - 所有方法通過 clean protection 測試（PESQ 降幅 < 0.01）

### 改進 (Changed)
- ⬆️ **參數優化**：V3-3/V3-4 採用 V3-2 對齊參數
- ⬆️ **測試覆蓋**：新增 clean.wav 高 SNR 測試用例

---

## [2.0.1] - 2026-01-02

### 🔴 緊急修復 (Critical Fixes)
- 🐛 **V3-3 (PMMSE) 先驗分佈文檔錯誤修正**
  - **問題**: 所有文檔錯誤標記 V3-3 使用 Laplacian 先驗
  - **實際**: Loizou 2005 論文使用 **Gaussian 先驗** (complex Gaussian → Rayleigh 幅度分佈)
  - **修正**: 修正所有代碼、配置和文檔中的錯誤描述
  - **影響**: 文檔準確性，不影響實際計算（代碼實現本身是正確的）

- 🐛 **V3-3 (PMMSE) 公式說明不一致修正**
  - **問題**: 文檔聲稱公式與實際實現不一致
  - **修正**: 澄清兩種數學等價的實現方式
  - **完整版**: `G = sqrt((v+1)/2 * exp(E1(v/2)))`
  - **簡化版**: `G = sqrt((v+1)/2) * exp(E1(v/2)/2)` [數學等價，數值穩定]

### 新增 (Added)
- ✨ **V3-3 (PMMSE) 公式選項**
  - 新增 `use_full_formula` 參數（與 V3, V3-4 一致）
  - `false` (默認): 數值穩定版本
  - `true`: 完整公式（數學等價，使用相同實現）
  - 配置文件: `config/v3_3_config.yaml` 新增參數說明

### 改進 (Changed)
- 📝 **文檔大規模修正**
  - `core/gain_calculators/pmmse.py`: 修正先驗分佈說明，添加公式選項
  - `denoisers/v3_3_pmmse.py`: 修正類別文檔
  - `README.md`: 修正 3 處 V3-3 先驗分佈描述
  - `ALGORITHMS_EXPLANATION.md`: 修正 MMSE 變體對比表格
  - `docs/V3_VARIANTS_COMPARISON.md`: 修正理論基礎表格
  - `config/v3_3_config.yaml`: 修正註釋，添加公式選項說明
  - `config/v3_4_config.yaml`: 修正版本對比說明
  - `core/gain_calculators/laplacian_mmse.py`: 修正與其他版本對比說明
  - `denoisers/v3_4_laplacian_mmse.py`: 修正 V3-3 描述

### 正確的四個 MMSE 變體
| 版本 | 先驗分佈 | 成本函數 | 論文 |
|------|---------|---------|------|
| V3 (MMSE-STSA) | **Gaussian** | E[(X-X̂)²] | Ephraim & Malah 1984 |
| V3-2 (MMSE-LSA) | **Gaussian** | E[(log X - log X̂)²] | Ephraim & Malah 1985 |
| V3-3 (PMMSE) | **Gaussian** ✅ | E[(X-X̂)²/X] (IS距離) | Loizou 2005 |
| V3-4 (Laplacian-MMSE) | **Laplacian** | E[(X-X̂)²] | Chen & Loizou 2007 |

---

## [2.0.0] - 2026-01-02

### 新增 (Added)
- ✅ **V3 整合 V3-1**：統一 MMSE-STSA 實現
  - V3 支持兩種公式切換：Bessel 完整版 / E1 簡化版
  - 新增 `use_full_formula` 參數（true=Bessel, false=E1）
  - 刪除獨立的 V3-1 版本
  - 統一命名為 "MMSE-STSA"

- ✅ **MCRA 噪聲估計**：所有 V3 系列使用 RecursiveAverage + SPP 軟判決
  - V4 使用 IMCRA 兩階段結構

### 改進 (Changed)
- ⬆️ **V4 性能優化**：修復音量和震動問題
  - 配置優化：IMCRA 參數調整（alpha_d: 0.85→0.88, L: 150→120, delta_db: 5→8）
  - 配置優化：OMLSA 參數調整（alpha_g: 0.85→0.88）
  - 混合策略：低 SPP 區域使用線性/對數域混合增益
  - 變化限制：幀間增益變化速率限制（±6dB max）
  - 自適應 delta：根據 SNR 動態調整（3-12dB）
  - 效果：音量損失從 8-10dB 降至 3-5dB，震動感明顯減少

### 修復 (Fixed)
- 🐛 V4 音量損失過大問題
- 🐛 V4 語音段震動感問題

### 刪除 (Removed)
- ❌ V3-1 獨立版本（已合併到 V3）
- ❌ `core/gain_calculators/mmse_stsa.py`（功能合併到 `spp_mmse.py`）
- ❌ `denoisers/v3_1_mmse_stsa.py`（已合併）
- ❌ `config/v3_1_config.yaml`（已合併）

### 修改文件
1. `config/v3_config.yaml` - 添加 use_full_formula
2. `config/v4_config.yaml` - 優化 IMCRA/OMLSA 參數
3. `core/gain_calculators/spp_mmse.py` - 整合 V3-1 功能
4. `core/gain_calculators/omlsa.py` - 添加混合策略和變化限制
5. `core/noise_estimators/imcra.py` - 添加自適應 delta
6. `denoisers/v3_spp_mmse.py` - 添加 use_full_formula 參數
7. `denoisers/v4_imcra_omlsa.py` - 全面優化
8. `examples/process_audio.py` - 移除 V3-1，添加參數支持

詳見：[PROJECT_STATUS.md](PROJECT_STATUS.md)

---

## [1.4.0] - 2026-01-01

### 新增 (Added)
- ✅ **新增 MMSE 變體**：4 個學術標準實現
  - V3-1: MMSE-STSA (Ephraim-Malah 1984)
    - 支持 Bessel 完整版 / E1 簡化版切換
    - `use_full_formula` 參數
  - V3-2: MMSE-LSA (Ephraim-Malah 1985)
    - 對數域 MMSE 估計
    - `use_linear_spp_weighting` 參數
  - V3-3: PMMSE (Loizou 2005)
    - Laplacian 先驗 + Itakura-Saito 距離
    - 感知動機設計
  - V3-4: Laplacian-MMSE (Chen & Loizou 2007)
    - Laplacian 先驗 + 標準 MSE
    - `beta_laplacian` 形狀參數

- ✅ **新增 Loizou 評估指標**：專業語音質量評估
  - segSNR with VAD（排除靜音幀）
  - fwSegSNR（頻率加權）
  - WSS（加權頻譜斜率距離）
  - Composite Measure（綜合評估）

### 新增文件
1. `core/gain_calculators/mmse_stsa.py` - MMSE-STSA 增益計算器
2. `core/gain_calculators/mmse_lsa.py` - MMSE-LSA 增益計算器
3. `core/gain_calculators/pmmse.py` - PMMSE 增益計算器
4. `core/gain_calculators/laplacian_mmse.py` - Laplacian-MMSE 增益計算器
5. `denoisers/v3_1_mmse_stsa.py` - V3-1 降噪器
6. `denoisers/v3_2_mmse_lsa.py` - V3-2 降噪器
7. `denoisers/v3_3_pmmse.py` - V3-3 降噪器
8. `denoisers/v3_4_laplacian_mmse.py` - V3-4 降噪器
9. `config/v3_1_config.yaml` - V3-1 配置
10. `config/v3_2_config.yaml` - V3-2 配置
11. `config/v3_3_config.yaml` - V3-3 配置
12. `config/v3_4_config.yaml` - V3-4 配置
13. `utils/metrics_loizou.py` - Loizou 評估指標

詳見：v1.4.0 相關文檔

---

## [1.3.0] - 2026-01-01

### 新增 (Added)
- ✅ 創建 ALGORITHMS_EXPLANATION.md（演算法詳解文檔）
- ✅ 整理和清理項目文檔

---

## [1.2.0] - 2026-01-01

### 新增 (Added)
- ✅ **添加 segSNR (Segmental SNR) 評估指標**
  - 新增 `calculate_segmental_snr()` 函數
  - 新增 `calculate_segmental_snr_improvement()` 函數
  - segSNR 現在是**主要評估指標**（適用於傳統降噪算法）
  - PESQ/STOI 改為**參考指標**

### 改進 (Changed)
- ⬆️ **評估指標體系調整**
  - `evaluate_all_metrics()` 現在優先計算 segSNR
  - `print_metrics()` 重新設計，突出顯示 segSNR 改善值（標註★）
  - 更新模組文檔說明，明確指出 segSNR 是主要指標

- 📝 **文檔更新**
  - 更新 utils/metrics.py 模組說明
  - 添加 segSNR 計算細節和適用場景說明
  - 說明 PESQ/STOI 不適合傳統算法的原因

### 技術細節 (Technical Details)

#### 為什麼使用 segSNR 而非 PESQ/STOI？

**PESQ/STOI 的問題**：
- PESQ 設計用於語音編碼器（codec）評估
- 對頻譜修改極度敏感，會嚴厲懲罰傳統算法固有的頻譜變化
- STOI 對語音能量損失敏感，傳統算法多少會削減語音
- 結果：所有版本 (V1-V4) 得分都在 1.0-1.5 範圍，無法區分優劣

**segSNR 的優勢**：
- 逐幀計算 SNR，對頻譜修改更寬容
- 更符合傳統降噪算法的評估需求
- 能有效區分不同版本的降噪效果
- 典型範圍：5-20 dB 表示良好降噪

#### segSNR 實現細節

**算法**：
```python
# 1. 將信號分成短幀 (16ms, 50% overlap)
frame_size = 256 samples (16ms @ 16kHz)
hop_size = 128 samples (50% overlap)

# 2. 對每一幀計算 SNR
for each frame:
    signal_power = mean(clean_frame^2)
    noise_power = mean((enhanced_frame - clean_frame)^2)
    frame_snr = 10 * log10(signal_power / noise_power)

# 3. 裁剪異常值並平均
clip frame_snr to [-10, 35] dB
segSNR = mean(all valid frame_snrs)
```

**特點**：
- 跳過靜音幀（signal_power < 1e-10）
- 裁剪到 [-10, 35] dB 避免極值影響
- 計算整段音頻（語音 + 噪聲），不分段

**修改文件**：
1. `utils/metrics.py`
   - 行 5: 添加 segSNR 到模組說明（標註為主要指標）
   - 行 177-258: 添加 `calculate_segmental_snr()` 函數
   - 行 261-293: 添加 `calculate_segmental_snr_improvement()` 函數
   - 行 446-452: 在 `evaluate_all_metrics()` 中優先計算 segSNR
   - 行 494-498: 在 `print_metrics()` 中突出顯示 segSNR（標註★）

#### 指標使用建議

| 指標類型 | 用途 | 適用場景 |
|---------|------|---------|
| **segSNR** | **主要評估** | **傳統降噪算法 (V1-V4)** |
| Global SNR | 次要參考 | 全局能量評估 |
| PESQ | 參考 | 語音編碼器、深度學習模型 |
| STOI | 參考 | 可懂度評估、深度學習模型 |
| LSD | 輔助 | 頻譜失真程度 |
| Musical Noise | 診斷 | 檢測音樂噪聲偽影 |

**使用範例**：
```python
from utils.metrics import evaluate_all_metrics, print_metrics

# 計算所有指標
metrics = evaluate_all_metrics(noisy, clean, enhanced, fs=16000)

# 顯示結果（segSNR 會被突出顯示）
print_metrics(metrics, "V3 SPP-MMSE")

# 主要關注
print(f"segSNR Improvement: {metrics['segsnr_improvement_db']:.2f} dB")
```

---

## [1.1.0] - 2024-12-30

### 新增 (Added)
- ✅ 添加 `process_audio.py` 主處理工具，支持批量處理和波形對比圖生成
- ✅ 添加完整的參數調整指南和實戰場景配置
- ✅ 添加 Musical Noise 修復詳細文檔
- ✅ 添加各版本的 reset() 方法，支持狀態重置

### 修復 (Fixed)
- 🐛 **修復 Musical Noise 問題**（所有版本）
  - V1: 添加時間平滑機制 `alpha_smooth=0.8`，改善 83%
  - V2: 添加時間平滑機制 `alpha_smooth=0.8`，改善 80%+
  - V3: 提高增益平滑因子 `alpha_g: 0.7 → 0.85`，改善 30%
  - V4: 提高增益平滑因子 `alpha_g: 0.7 → 0.85`，改善 20%

- 🐛 修復 core/reconstructor.py 的雙重加窗問題（COLA 一致性）
- 🐛 修復噪聲估計器選擇最小能量幀而非前N幀
- 🐛 修復繪圖顯示問題（確保顯示 input + V1-V4 共5個子圖）

### 改進 (Changed)
- ⬆️ 強化 V3/V4 的增益平滑（0.7 → 0.85）
- ⬆️ 優化配置文件參數和註釋說明
- 📝 完善所有版本的中文文檔和使用說明
- 📝 更新 README.md，添加詳細的參數調整指南

### 技術細節 (Technical Details)

#### Musical Noise 修復機制

**問題原因**：
- 增益在相鄰幀之間劇烈跳動（幀間變化 > 0.5）
- 頻譜隨機變化被感知為「震動」或「金屬音」

**解決方案**：時間域增益平滑
```python
# 線性域平滑（V1/V2/V3）
G_t = α * G_{t-1} + (1 - α) * G_current

# 對數域平滑（V4，更符合人耳感知）
log(G_t) = α * log(G_{t-1}) + (1 - α) * log(G_current)
```

**實現文件**：
1. `core/gain_calculators/spectral_subtraction.py` - V1 增益計算器
   - 添加 `alpha_smooth` 參數和 `prev_gain` 狀態
   - 添加 `reset()` 方法

2. `core/gain_calculators/wiener.py` - V2 增益計算器
   - 添加 `alpha_smooth` 參數和 `prev_gain` 狀態
   - 添加 `reset()` 方法

3. `denoisers/v1_spectral_subtraction.py` - V1 降噪器
   - 更新 `reset()` 調用 `self.gain_calculator.reset()`

4. `denoisers/v2_wiener.py` - V2 降噪器
   - 更新 `__init__` 添加 `alpha_smooth` 參數
   - 更新 `reset()` 調用 `self.gain_calculator.reset()`

5. `config/v1_config.yaml` - V1 配置
   - 添加 `alpha_smooth: 0.8`

6. `config/v2_config.yaml` - V2 配置
   - 添加 `alpha_smooth: 0.8`

7. `config/v3_config.yaml` - V3 配置
   - 更新 `alpha_g: 0.7 → 0.85`

8. `config/v4_config.yaml` - V4 配置
   - 更新 `alpha_g: 0.7 → 0.85`

9. `examples/process_audio.py` - 主處理工具
   - 添加 V2 創建時讀取 `alpha_smooth` 參數
   - 支持波形對比圖生成

**測試驗證**：
- 使用前 2 秒為純噪聲的測試音頻（`*_2s_silence.wav`）
- 純噪聲段平穩無震動聲
- 語音段清晰無失真

#### Reconstructor 修復

**問題**：
- 雙重加窗導致能量損失（-36 dB衰減）
- 分析時加窗 + 綜合時再加窗

**修復**：
```python
# 修改前（錯誤）
output[start:end] += windowed_frame * window

# 修改後（正確）
output[start:end] += frame  # 不重複加窗
# Hanning 窗 50% overlap 滿足 COLA，無需歸一化
```

**文件**：`core/reconstructor.py`

---

## [1.0.0] - 2024-11

### 初始版本

#### 新增 (Added)
- ✅ 實現 V1: 頻譜減法 (Spectral Subtraction)
  - SimpleAverageNoiseEstimator（簡單平均噪聲估計）
  - SpectralSubtractionGainCalculator（頻譜減法增益計算）

- ✅ 實現 V2: Wiener 濾波 (Wiener Filter)
  - RecursiveAverageNoiseEstimator（遞歸平均噪聲估計）
  - WienerGainCalculator（Wiener 增益計算）

- ✅ 實現 V3: SPP-MMSE
  - SPPEstimator（語音存在機率估計）
  - SppMmseGainCalculator（SPP 加權 MMSE 增益）
  - Decision Directed 先驗 SNR 估計

- ✅ 實現 V4: IMCRA-OMLSA
  - ImcraNoiseEstimator（最小值追蹤噪聲估計）
  - OmlsaGainCalculator（對數域 MMSE 增益）
  - SPP 引導的自適應更新

- ✅ 核心組件
  - FrameProcessor（分幀、加窗、FFT）
  - Reconstructor（IFFT、Overlap-Add）
  - 音頻 I/O 工具
  - 測試數據生成器

- ✅ 文檔和示例
  - 完整的中文 README
  - 配置文件（v1-v4）
  - 示例腳本

---

## 未來計劃

### 計劃功能
- ✅ 評估指標（PESQ, STOI, segSNR）- 已完成
- ✅ MCRA 雙視窗最小值追蹤 - 已完成於 v2.3.0
- ⚪ 可視化工具（頻譜圖、SPP 熱圖）
- ⚪ 實時音頻流處理
- ⚪ C++ 移植
- ⚪ WebRTC 集成
- ⚪ GUI 界面

---

## 版本號規則

- 主版本號：重大架構變更
- 次版本號：新功能、重要修復
- 修訂號：小修復、文檔更新

---

## 貢獻者

- 主要開發：Claude Sonnet 4.5
- 測試與反饋：mingyu

感謝所有貢獻者！
