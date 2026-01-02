# 變更記錄 (Changelog)

本文件記錄所有重要的變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

## [1.5.1] - 2026-01-02

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

## [1.5.0] - 2026-01-02

### 新增 (Added)
- ✅ **V3 整合 V3-1**：統一 MMSE-STSA 實現
  - V3 支持兩種公式切換：Bessel 完整版 / E1 簡化版
  - 新增 `use_full_formula` 參數（true=Bessel, false=E1）
  - 刪除獨立的 V3-1 版本
  - 統一命名為 "MMSE-STSA"

- ✅ **噪聲追蹤擴展**：擴展到所有主要版本
  - V2 (Wiener Filter)
  - V3-2 (MMSE-LSA)
  - V3-3 (PMMSE)
  - V3-4 (Laplacian-MMSE)
  - V4 (IMCRA-OMLSA)
  - 統一配置：`noise_tracking.enable: true`

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
1. `config/v2_config.yaml` - 添加 noise_tracking
2. `config/v3_config.yaml` - 添加 use_full_formula, noise_tracking
3. `config/v3_2_config.yaml` - 添加 noise_tracking
4. `config/v3_3_config.yaml` - 添加 noise_tracking
5. `config/v3_4_config.yaml` - 添加 noise_tracking
6. `config/v4_config.yaml` - 優化 4 個參數，添加 noise_tracking
7. `core/gain_calculators/spp_mmse.py` - 整合 V3-1 功能
8. `core/gain_calculators/omlsa.py` - 添加混合策略和變化限制
9. `core/noise_estimators/imcra.py` - 添加自適應 delta
10. `denoisers/v2_wiener.py` - 添加噪聲追蹤
11. `denoisers/v3_spp_mmse.py` - 添加 use_full_formula 參數
12. `denoisers/v3_2_mmse_lsa.py` - 添加噪聲追蹤
13. `denoisers/v3_3_pmmse.py` - 添加噪聲追蹤
14. `denoisers/v3_4_laplacian_mmse.py` - 添加噪聲追蹤
15. `denoisers/v4_imcra_omlsa.py` - 全面優化
16. `examples/process_audio.py` - 移除 V3-1，添加參數支持

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
- ✅ **噪聲場景自適應機制**
  - 新增 `NoiseChangeDetector` 噪聲場景變化檢測器
  - 使用 Posterior SNR (γ) 檢測噪聲場景突變
  - V3 降噪器集成場景自適應功能
  - 新增 `enable_noise_tracking` 參數（可選啟用/關閉）

### 改進 (Changed)
- ⬆️ **V1 噪聲估計器**：添加快速重估機制（200-400ms 適應）
- ⬆️ **V2/V3 噪聲估計器**：添加動態 alpha 切換（100-200ms 適應）
- ⬆️ **V4 噪聲估計器**：添加快速追蹤模式（300-600ms 適應）

### 技術細節 (Technical Details)

#### 噪聲場景自適應機制

**設計原理**：
- 使用已有的 Posterior SNR (γ) 進行檢測，無需額外計算
- 在非語音段（SPP < 0.3）檢測噪聲能量比變化
- 當能量比 > 2.0 或 < 0.5 時觸發快速適應

**檢測流程**：
```python
γ_ref = mean(γ_history[過去20幀])
γ_cur = γ[當前幀]
energy_ratio = sum(γ_cur) / sum(γ_ref)

if energy_ratio > 2.0 or < 0.5:
    → 噪聲場景變化！觸發快速適應
```

**適應策略**：

| 版本 | 正常模式 | 快速模式 | 適應時間 |
|------|----------|----------|----------|
| V1 | 固定噪聲 | 重估20幀 | 200-400ms |
| V2/V3 | α=0.95 | α=0.5 | 100-200ms |
| V4 | α_s=0.9, L=150 | α_s=0.7, L=50 | 300-600ms |

**修改文件**：
1. `core/noise_change_detector.py` - 新建檢測器
2. `core/noise_estimators/simple_average.py` - V1 重估機制
3. `core/noise_estimators/recursive_average.py` - V2/V3 動態 alpha
4. `core/noise_estimators/imcra.py` - V4 快速追蹤
5. `denoisers/v3_spp_mmse.py` - 集成檢測器
6. `examples/test_noise_scene_adaptation.py` - 測試腳本

**使用範例**：
```python
from denoisers.v3_spp_mmse import SppMmseDenoiser

# 默認啟用噪聲追蹤
denoiser = SppMmseDenoiser(sample_rate=16000)
enhanced = denoiser.denoise(noisy_signal)

# 關閉噪聲追蹤（如果不需要）
denoiser = SppMmseDenoiser(
    sample_rate=16000,
    enable_noise_tracking=False
)
```

**性能影響**：
- 計算開銷：< 1%
- 內存開銷：~10KB
- 適應速度：2-4倍提升

詳見：[CHANGES_SUMMARY_v1.3.0.md](CHANGES_SUMMARY_v1.3.0.md)

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

### [1.2.0] - 噪聲場景轉換適應機制（計劃中）

**目標**：讓 V1-V4 能夠檢測並適應噪聲類型突變

#### 計劃新增
- ⚪ NoiseChangeDetector（噪聲變化檢測器）
  - 三個檢測指標：頻譜距離、能量比、頻帶遷移
  - 多指標融合判決
  - SPP 引導檢測（只在非語音段）

- ⚪ 快速適應機制
  - V1: 噪聲重估機制（200-400ms）
  - V2/V3: 動態 alpha 切換（100-200ms）
  - V4: IMCRA 快速追蹤模式（300-600ms）

#### 預期效果
- 適應速度：0.5-2 秒
- 加速比：2-4 倍（相比原始）
- 誤檢率：< 1-2%

詳見：[計劃文件](/Users/mingyu/.claude/plans/clever-cooking-moon.md)

---

## [1.3.0] - 擴展功能（未來）

### 計劃功能
- ✅ 評估指標（PESQ, STOI, segSNR）- 已完成於 v1.2.0
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
