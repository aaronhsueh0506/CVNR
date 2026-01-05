# Phase 3 優化完成報告

## ✅ 完成狀態

所有 Phase 3 核心功能已完成實現！

### 已完成任務

- [x] **核心檢測器實現**
  - [x] `core/snr_detector.py` - SNR 自適應檢測器
  - [x] `core/clean_detector.py` - Clean 音頻檢測器

- [x] **配置文件更新**（7 個）
  - [x] `config/v1_config.yaml` - base_g_min_db: -12.0
  - [x] `config/v2_config.yaml` - base_g_min_db: -15.0
  - [x] `config/v3_config.yaml` - base_g_min_db: -12.0
  - [x] `config/v3_2_config.yaml` - base_g_min_db: -12.0 + linear weighting
  - [x] `config/v3_3_config.yaml` - base_g_min_db: -15.0
  - [x] `config/v3_4_config.yaml` - base_g_min_db: -15.0
  - [x] `config/v4_config.yaml` - base_g_min_db: -18.0

- [x] **增益計算器更新**（7 個）
  - [x] 所有增益計算器已添加 `g_min: float = None` 參數

- [x] **降噪器集成**（7 個）
  - [x] V1, V2, V3, V3-2, V3-3, V3-4, V4 全部集成 SNR/Clean 檢測器

- [x] **評估工具改進**
  - [x] `compute_improvement.py` 已優化（已存在，包含所有 Phase 3 改進）
  - [x] `tools/generate_csv_results.py` 已創建
  - [x] `tests/test_clean_audio.py` 已創建

---

## 🎯 核心功能

### 1. SNR 自適應機制

**工作原理**:
- 實時估計每幀的 SNR
- 根據 5 級 SNR 分層動態調整 g_min

**SNR 分層**（以 V3-2 為例，base_g_min_db = -12.0）:

| SNR 範圍 (dB) | 場景 | g_min_db | g_min (線性) | 抑制強度 |
|--------------|------|----------|--------------|----------|
| < -5 | 極低 SNR | -15 | 0.0316 | 最強抑制 |
| -5 ~ 5 | 低 SNR | -12 | 0.0631 | 強抑制 |
| 5 ~ 15 | 中 SNR | -9 | 0.1259 | 中等抑制 |
| 15 ~ 25 | 高 SNR | -6 | 0.2512 | 輕抑制 |
| > 25 | 極高/Clean | -3 | 0.5012 | 最輕抑制 |

**預期效果**:
- **低 SNR**: 保持強降噪能力
- **高 SNR**: 減少語音抑制，改善 STOI/PESQ
- **Clean 音頻**: 接近透明處理

### 2. V3-2 Linear Weighting 修復

**問題**: Log-domain SPP 加權放大抑制效應
```python
# 原始（問題）
log(G) = p*log(G_mmse) + (1-p)*log(g_min)
# 當 g_min=0.01, p=0.7: 0.3*log(0.01) = -0.6 嚴重拉低增益
```

**解決方案**:
```python
# Linear-domain 加權（已實現）
G = p*G_mmse + (1-p)*g_min  # use_linear_spp_weighting: true
```

**配置**:
- `config/v3_2_config.yaml`:
  - `use_linear_spp_weighting: true`
  - `alpha_xi: 0.92` (從 0.98，提高 SPP 反應速度)
  - `base_g_min_db: -12.0` (從 -20.0)

### 3. Clean 音頻保護

**檢測標準**:
1. SNR > 25 dB
2. 噪聲 PSD < 1e-4
3. 平均 SPP > 0.8
4. 持續 50 幀確認

**處理策略**:
- 檢測到 clean 時，g_min 提高 9dB（接近 1.0）
- 最小化不必要的頻譜修改

---

## 🚀 運行評估

### Step 1: 重新生成降噪輸出

由於配置文件已更新（SNR adaptive 已啟用），需要重新生成所有降噪輸出：

```bash
cd /Users/mingyu/Desktop/Code/公司/speech_denoise

# 重新生成所有方法的降噪輸出
python3 regenerate_all_outputs.py
```

這將生成使用 SNR adaptive 配置的新輸出到 `denoised_original/` 目錄。

### Step 2: 運行完整評估

```bash
# 運行主評估（計算 improvement, PESQ, STOI, LSD）
python3 compute_improvement.py
```

**輸出**:
- 終端輸出: 每個測試用例的詳細結果
- `results/improvement_report.md`: Markdown 報告（4 個指標表）
- 自動調用 CSV 生成（如果成功）

### Step 3: 生成 CSV 報告

```bash
# 如果 compute_improvement.py 沒有自動生成 CSV，手動運行
python3 tools/generate_csv_results.py
```

**輸出**:
```
results/metrics_by_snr/
├── segSNR_improvement.csv
├── fwSegSNR_improvement.csv
├── WSS_improvement.csv
├── PESQ_enhanced.csv
├── STOI_enhanced.csv
├── LSD_enhanced.csv
├── PESQ_noisy.csv
├── STOI_noisy.csv
├── LSD_noisy.csv
├── PESQ_delta.csv
├── STOI_delta.csv
└── LSD_delta.csv
```

### Step 4: 生成可視化圖表（可選）

```bash
# 生成熱圖和折線圖
python3 results/plot_results.py
```

**輸出**:
- STOI/PESQ 熱圖
- segSNR 改善量熱圖
- STOI/PESQ 隨 SNR 變化的折線圖

### Step 5: Clean 音頻保護測試

```bash
# 使用 pytest 運行
pytest tests/test_clean_audio.py -v

# 或直接運行
python3 tests/test_clean_audio.py
```

**測試標準**:
- ✓ STOI Δ >= -0.05 (允許最多 5% 下降)
- ✓ LSD < 2.0 dB (失真很小)

---

## 📊 預期結果

### STOI 改善（核心目標）

| 方法 | 當前 STOI Δ | 優化後 STOI Δ | 改善幅度 |
|------|-------------|---------------|----------|
| V1 | -0.037 | **+0.005 ~ +0.01** | +4~5% ✅ |
| V2 | -0.041 | **+0.005 ~ +0.01** | +5~6% ✅ |
| V3 | -0.046 | **+0.01 ~ +0.02** | +6~7% ✅ |
| **V3-2** | **-0.111** | **+0.01 ~ +0.02** | **+12~14%** ✅✅ |
| **V3-3** | **-0.083** | **+0.01 ~ +0.015** | **+9~10%** ✅✅ |
| V3-4 | -0.022 | **+0.005 ~ +0.01** | +3~4% ✅ |
| V4 | -0.063 | **+0.005 ~ +0.01** | +7~8% ✅ |

### V3-2/V3-3 高 SNR PESQ 改善

**當前問題**: 15dB SNR 時 PESQ < 2.0（比 V1 還低）

**優化後預期**（15dB SNR）:

| 方法 | 當前 PESQ | 優化後 PESQ | 改善 |
|------|-----------|-------------|------|
| V1 | ~2.3 | ~2.3 | 保持 |
| V3-2 | **< 2.0** | **2.4 ~ 2.6** | +0.4~0.6 ✅ |
| V3-3 | **< 2.0** | **2.3 ~ 2.5** | +0.3~0.5 ✅ |

### Clean 音頻保護

**測試場景**: 用 `clean.wav` 作為輸入

| 指標 | 標準 | 預期結果 |
|------|------|----------|
| STOI Δ | >= -0.05 | **所有方法通過** ✅ |
| LSD | < 2.0 dB | **所有方法通過** ✅ |

### segSNR 性能維持

**關鍵**: SNR adaptive 不應降低降噪能力

| 方法 | 當前 segSNR↑ | 優化後 segSNR↑ | 變化 |
|------|-------------|---------------|------|
| V3-2 | +4.41 dB | +4.0 ~ +5.0 dB | ±0.5 dB ✅ |
| V3-3 | +4.57 dB | +4.0 ~ +5.0 dB | ±0.5 dB ✅ |

---

## 🔍 檢查清單

運行評估後，檢查以下項目：

### 功能驗證

- [ ] `compute_improvement.py` 運行成功，無 ImportError
- [ ] PESQ/STOI 顯示實際數值（非 N/A）
- [ ] 表格包含 Noisy、Enhanced、Δ 三列
- [ ] [DEBUG] 信息顯示音頻長度和採樣率
- [ ] 無 STOI 異常低警告（< 0.3）

### CSV 報告驗證

- [ ] `results/metrics_by_snr/` 目錄存在
- [ ] 包含 12 個 CSV 文件
- [ ] CSV 格式為 Methods × SNR 樞紐表
- [ ] 可以用 Excel/pandas 打開

### 性能驗證

- [ ] **所有方法 STOI Δ >= 0**（至少接近 0）
- [ ] **V3-2 STOI Δ >= +0.01**（從 -0.111 改善）
- [ ] **V3-3 STOI Δ >= +0.01**（從 -0.083 改善）
- [ ] V3-2/V3-3 在高 SNR (15dB) 的 PESQ > 2.3
- [ ] segSNR 改善量下降不超過 1 dB

### Clean 音頻保護驗證

- [ ] 所有 7 種方法 STOI Δ >= -0.05
- [ ] 所有 7 種方法 LSD < 2.0 dB
- [ ] `pytest tests/test_clean_audio.py -v` 全部通過

---

## 📁 修改文件清單

### 核心模塊（已完成）

- `core/snr_detector.py` ✅
- `core/clean_detector.py` ✅

### 配置文件（已完成）

- `config/v1_config.yaml` ✅
- `config/v2_config.yaml` ✅
- `config/v3_config.yaml` ✅
- `config/v3_2_config.yaml` ✅
- `config/v3_3_config.yaml` ✅
- `config/v3_4_config.yaml` ✅
- `config/v4_config.yaml` ✅

### 增益計算器（已完成）

- `core/gain_calculators/spectral_subtraction.py` ✅
- `core/gain_calculators/wiener.py` ✅
- `core/gain_calculators/spp_mmse.py` ✅
- `core/gain_calculators/mmse_lsa.py` ✅
- `core/gain_calculators/pmmse.py` ✅
- `core/gain_calculators/laplacian_mmse.py` ✅
- `core/gain_calculators/omlsa.py` ✅

### 降噪器（已完成）

- `denoisers/v1_spectral_subtraction.py` ✅
- `denoisers/v2_wiener.py` ✅
- `denoisers/v3_spp_mmse.py` ✅
- `denoisers/v3_2_mmse_lsa.py` ✅
- `denoisers/v3_3_pmmse.py` ✅
- `denoisers/v3_4_laplacian_mmse.py` ✅
- `denoisers/v4_imcra_omlsa.py` ✅

### 配置加載器（已完成）

- `process_audio.py` ✅

### 評估工具（已完成）

- `compute_improvement.py` ✅（已存在，包含所有改進）
- `tools/generate_csv_results.py` ✅（新創建）
- `results/plot_results.py` ✅（自動生成）

### 測試工具（已完成）

- `tests/test_clean_audio.py` ✅（新創建）

---

## 🎓 技術細節

### SNR 估算方法

```python
# 1. 計算後驗 SNR (gamma)
gamma = Y_psd / (noise_psd + 1e-10)

# 2. 只使用語音頻段 (300Hz - 4000Hz)
# 假設 512 FFT, 16kHz → bin 10~128
speech_gamma = gamma[10:128]

# 3. SNR = mean(gamma) - 1 (減去噪聲本身)
snr_linear = np.mean(speech_gamma) - 1.0
snr_db = 10 * np.log10(max(snr_linear, 1e-10))

# 4. EMA 平滑（smoothing_factor = 0.9）
snr_db = 0.9 * snr_history[-1] + 0.1 * snr_db
```

### Linear vs Log-domain Weighting 對比

**Log-domain**（原始 MMSE-LSA）:
```python
log_gain = p * log(G_mmse) + (1-p) * log(g_min)
G = exp(log_gain)

# 問題: log(g_min) 是負數，會嚴重拉低增益
# 例如: p=0.7, g_min=0.01
# log_gain = 0.7*log(G_mmse) + 0.3*(-2.0)
```

**Linear-domain**（V3-2 修復）:
```python
G = p * G_mmse + (1-p) * g_min

# 優勢: 線性混合，更溫和
# 例如: p=0.7, g_min=0.01
# G = 0.7*G_mmse + 0.003
```

---

## ⚠️ 注意事項

1. **必須重新生成輸出**: 配置文件已更新，舊的 `denoised_original/` 輸出不包含 SNR adaptive

2. **STOI 異常低警告**: 如果看到 STOI < 0.3 的警告，可能是：
   - 音頻長度對齊問題
   - 採樣率不匹配
   - 降噪過度導致語音失真

3. **Clean 測試可能較慢**: 需要對每個方法運行完整降噪流程

4. **CSV 生成依賴評估結果**: 確保先運行 `compute_improvement.py` 或有測試數據

---

## 📞 問題排查

### 如果 STOI 仍然 < 0.3

1. 檢查 [DEBUG] 輸出:
   ```
   [DEBUG] STOI計算: clean_len=48000, enhanced_len=48000, sr=16000
   ```

2. 確認音頻長度一致

3. 驗證採樣率正確（應該是 16000）

4. 檢查降噪輸出是否嚴重失真（用 `soundfile` 播放）

### 如果 segSNR 下降過多 (> 1 dB)

1. 檢查 SNR adaptive 是否啟用:
   ```yaml
   snr_adaptive:
     enable: true
   ```

2. 確認 base_g_min_db 設置正確

3. 驗證降噪器正確讀取配置（添加 print 調試）

### 如果 Clean 測試失敗

1. 檢查 clean detector 是否正常工作（添加 debug 輸出）

2. 驗證 SNR 估算是否正確（應該 > 25 dB）

3. 確認 g_min 在 clean 場景下提高到接近 1.0

---

## ✅ 下一步

1. **運行評估**: 按照上面的步驟運行完整評估

2. **驗證結果**: 檢查 STOI Δ 是否達到目標（>= +0.01）

3. **分析 CSV**: 使用 CSV 文件繪製性能對比圖

4. **調優（如需要）**: 如果結果未達預期，調整 base_g_min_db 值

5. **文檔化**: 更新 README 和技術文檔

---

**🎉 Phase 3 核心實現已完成！現在可以運行評估來驗證優化效果。**
