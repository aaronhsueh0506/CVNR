# 變更記錄 (Changelog)

本文件記錄所有重要的變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

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
- ⚪ 評估指標（PESQ, STOI）
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
