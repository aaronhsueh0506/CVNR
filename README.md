# 語音降噪系統 (Speech Denoising System)

**版本**: v4.2.2 · **Release 主推演算法**: V3-2 OMLSA (MMSE-LSA + Bayesian SPP + IMCRA)

傳統信號處理方法的實時語音降噪系統，採用漸進式學習路徑。

> **v4.2 release 重點**
> - **Part A Review 修復**（11 項 OMLSA 演算法/介面修正；Python + C 已同步 main 與 `feature/static-memory` 雙 branch）
> - **主推 V3-2 OMLSA**（`denoisers/v3_2_mmse_lsa.py` + `c_impl/`），已完整評估並有規格保證
> - **V4 OMLSA + Wind Handler**（`denoisers/v4_omlsa.py`）為 **研究用框架 (research infrastructure)**，在 VCTK/DEMAND 上未能改善風聲；預設 FLAT profile 等同 V3-2，**不建議直接拿去 ship**，詳見下方「演算法限制」章節

## 📋 項目概述

本項目實現了 5 個語音降噪算法，從基礎到先進：

**基礎版本**：
1. **V1: 頻譜減法 (Spectral Subtraction)** - 最經典的方法
2. **V2: Wiener 濾波** - 基於 MMSE 的最優濾波
3. **V3: MMSE-STSA** ⭐ - 概率軟判決方法 (v1.5.0 整合 V3-1，支持公式切換)

**MMSE 變體 (v1.4.0)**：

4. **V3-2: MMSE-LSA (對數域 MMSE)** 🏆 **推薦**
   - 對數域最小均方誤差估計，減少 Musical Noise
   - 適合: 高質量語音增強，對音質要求高的場景
   - 特點: 更少的音樂噪聲，頻譜更平滑
   - **v4.0 優化**: alpha_s=0.7, L=5 (50ms 快速場景適應)
   - **v4.1 優化**: 完全移除 eta 機制（L=5 已替代其功能）

5. **V3-3: PMMSE (感知動機 MMSE)**
   - 基於 Gaussian 先驗 + IS 距離的感知優化
   - 適合: 學術研究，感知質量優化實驗
   - 特點: 感知動機的成本函數，優異的 STOI 表現
   - v2.1.1: alpha_xi=0.96 同步優化

## 🎯 特點

- ✅ **五個演算法版本**：V1-V3 基礎版本 + V3-2/V3-3 MMSE 變體
- ✅ **v2.6**: Human Voice Band Soft VAD 後處理 + MCRA 瞬態偵測 (energy ratio)
- ✅ **v2.5**: MCRA 雙視窗最小值追蹤（內建場景變化適應）
- ✅ **v2.2**: V2 Wiener 使用 Bayesian SPP、DD 使用 enhanced_mag_prev、MCRA 支持
- ✅ **v1.4.0**: MMSE 學術標準實現（4 個 MMSE 變體）
- ✅ 模塊化設計，易於理解和擴展
- ✅ **已修復 Musical Noise 問題**（v1.1.0 更新）
- ✅ 完整的測試數據生成工具
- ✅ 支持多種噪聲類型和 SNR 等級
- ✅ 詳細的中文注釋和參數說明
- ✅ 漸進式學習路徑
- ✅ 實時處理性能（RTF < 0.01）

## 📦 安裝依賴

```bash
# 基礎依賴
pip install numpy scipy

# 音頻 I/O（推薦）
pip install soundfile

# 可視化（可選）
pip install matplotlib

# YAML 配置解析
pip install pyyaml

# 評估指標（可選）
pip install pesq pystoi
```

## 🎯 快速指令參考（常用工具）

### 🧪 完整測試與評估流程（推薦）

如果您想評估所有7個降噪方法的性能，請按以下順序執行：

```bash
# 步驟1: 生成所有測試用例的降噪輸出 (7個方法 × 13個測試用例 = 91個文件)
python3 regenerate_all.py

# 步驟2: 計算改善指標 (segSNR, fwSegSNR, WSS, PESQ, STOI, LSD)
python3 compute_improvement.py

# 查看結果報告
cat results/improvement_report.md
```

**說明**：
- `regenerate_all.py`: 使用當前配置處理所有測試用例，輸出到 `output/` 目錄
- `compute_improvement.py`: 計算每個方法相對於noisy的改善量，生成詳細報告
- 測試用例：clean.wav (高 SNR 保護測試) + 3種噪聲 (babble/car/street) × 4個SNR級別 (0/5/10/15dB) = 13 個測試用例

### 🎵 音頻處理與可視化

#### 1. 處理音頻並生成波形對比圖
```bash
# 使用推薦版本 (V3 和 V4)
python3 process_audio.py your_audio.wav --versions V3 V4

# 輸出:
# - your_audio_v3.wav          # V3 降噪結果
# - your_audio_v4.wav          # V4 降噪結果
# - your_audio_waveforms.png   # 波形對比圖 ⭐

# 測試所有版本
python3 process_audio.py your_audio.wav --versions V1 V2 V3 V3-2 V3-3 V3-4 V4
```

**波形圖說明**：
- 自動生成 `*_waveforms.png` 包含所有版本的時域波形對比
- 可視化內容：原始帶噪音頻 + 各版本降噪結果
- 顯示 RTF（實時率）和處理時間

#### 2. 算法診斷與頻譜可視化
```bash
# 生成頻譜對比圖（Clean / Noisy / Enhanced）
python3 tools/diagnose_algorithm.py

# 輸出:
# - diagnosis_spectrum.png  # 頻譜對比圖（前1秒音頻）
# - 終端顯示詳細診斷訊息

# 診斷內容:
# ✓ 測試數據結構檢查（長度、能量）
# ✓ 0.5s trimming 邏輯驗證
# ✓ 降噪器處理檢查
# ✓ 評估指標計算驗證
# ✓ 問題診斷（輸出音量、頻譜異常）
```

**頻譜圖說明**：
- 使用 `plt.magnitude_spectrum()` 繪製頻譜
- 對比 Clean、Noisy、Enhanced 三者的頻譜差異
- 用於診斷降噪器是否過度抑制高頻或引入失真

### 📊 評估指標計算

#### 3. 計算 Improvement 指標（推薦）
```bash
# 計算所有方法的改善量（segSNR, fwSegSNR, WSS, PESQ, STOI, LSD）
python3 compute_improvement.py

# 輸出:
# - results/improvement_report.md  # 平均改善量統計表
# - 終端顯示每個測試用例的詳細結果

# 顯示指標:
# ✓ segSNR 改善 (dB)      - 分段 SNR 改善
# ✓ fwSegSNR 改善 (dB)    - 頻率加權 SNR 改善
# ✓ WSS 改善              - 頻譜失真減少量
# ✓ PESQ                  - 感知語音質量
# ✓ STOI                  - 短時客觀可懂度
# ✓ LSD                   - 對數頻譜距離
```

**參數說明**：
- `TRIM_SECONDS = 0.5`：移除音頻前 0.5 秒（處理 prepend 文件）
- `EVAL_SR = 16000`：評估時統一重採樣到 16kHz（Loizou 標準）
- 自動處理兩類文件：
  - V1-V4：從 `output/` 讀取（有 prepend）
  - Speex/RNNoise：從 `test_wav/wav/benchmark_wav/` 讀取（無 prepend）

#### 4. 綜合評估（Loizou 2008 專業指標）
```bash
# 完整評估所有方法（V1-V4 + Speex/RNNoise）
python3 tools/comprehensive_evaluation.py

# 輸出:
# - results/loizou_evaluation.json  # JSON 格式詳細數據
# - results/loizou_evaluation.csv   # CSV 表格
# - results/loizou_evaluation.md    # Markdown 報告
```

### 🔧 工具腳本

#### 6. 重新生成所有降噪輸出
```bash
# 使用當前配置重新處理所有測試音檔 (7個方法 × 12個測試用例 = 84個文件)
python3 regenerate_all.py

# 輸出:
# - output/ 目錄中的 84 個 .wav 文件 (統一16kHz)
# - 格式: {VERSION}_{noise_type}_{snr}dB.wav
# - 例如: V3_babble_10dB.wav, V4_car_5dB.wav
```

#### 7. 驗證最佳配置
```bash
# 驗證當前配置參數是否正確
python3 tools/validate_best_config.py

# 檢查:
# ✓ V1 配置參數
# ✓ V2 配置參數
# ✓ V3 配置參數（SPP + 增益參數）
# ✓ V4 配置參數（IMCRA + OMLSA）
```

### 📈 可視化 SPP（語音存在機率）

SPP (Speech Presence Probability) 是 V3/V4 的核心中間量，表示每個時頻點存在語音的機率。

#### 如何可視化 SPP

當前代碼中，SPP 在 `core/spp_estimator.py` 中計算，但沒有內建可視化工具。如需可視化，可以手動添加：

```python
# 示例：在處理音頻時保存 SPP
from denoisers import SppMmseDenoiser
import librosa
import numpy as np
import matplotlib.pyplot as plt

# 讀取音頻
audio, sr = librosa.load('your_audio.wav', sr=None)

# 創建降噪器
denoiser = SppMmseDenoiser(sample_rate=sr)

# 修改 denoise 方法以返回 SPP（需要修改源碼）
# 或直接在 denoisers/v3_spp_mmse.py 中添加 debug 模式

# 可視化 SPP（假設已獲取 SPP 矩陣）
# spp.shape = (n_frames, n_freqs)
plt.figure(figsize=(12, 6))
plt.imshow(spp.T, aspect='auto', origin='lower', cmap='viridis')
plt.colorbar(label='SPP (0-1)')
plt.xlabel('Frame Index')
plt.ylabel('Frequency Bin')
plt.title('Speech Presence Probability (SPP)')
plt.savefig('spp_visualization.png', dpi=150)
```

**SPP 特性**：
- 取值範圍：[0, 1]（0=純噪聲，1=純語音）
- 時間維度：每幀計算一次（通常 10ms 間隔）
- 頻率維度：每個 FFT bin 獨立計算
- 用於軟判決：比 VAD 硬判決更平滑

**關鍵參數**（在 `config/v3_config.yaml` 中調整）：
- `alpha_xi`：先驗 SNR 平滑因子（0.92-0.98），越大越平滑
- `q`：語音先驗機率（通常 0.5），語音多可調高到 0.6-0.7
- `xi_min_db`：先驗 SNR 下限（-25 dB），防止數值問題

### 🎨 可視化最佳實踐

#### 判讀波形圖（`*_waveforms.png`）

**好的降噪結果**：
- ✅ 靜音段接近 0（噪聲被充分抑制）
- ✅ 語音段清晰可見（沒有過度抑制）
- ✅ 波形平滑（無 musical noise 閃爍）

**需要調整的情況**：
- ❌ 靜音段仍有明顯噪聲 → 增加降噪強度（降低 `g_min_db`）
- ❌ 語音段模糊不清 → 減少降噪強度（提高 `g_min_db`）
- ❌ 波形有閃爍偽影 → 增加平滑因子（提高 `alpha_g`）

#### 判讀頻譜圖（`diagnosis_spectrum.png`）

**好的降噪結果**：
- ✅ Enhanced 頻譜接近 Clean
- ✅ 高頻保留良好（無過度抑制）
- ✅ 低頻噪聲被有效抑制

**需要調整的情況**：
- ❌ 高頻完全消失 → 降低降噪強度
- ❌ 低頻噪聲殘留明顯 → 增加降噪強度
- ❌ 頻譜有鋸齒狀波動 → 增加平滑（檢查 musical noise）

---

## 📊 評估指標說明

### 專業評估標準：Loizou 2008

本專案使用業界標準 **Loizou (2008)** 評估方法，提供比傳統指標更準確的質量評估。

#### 核心評估指標

| 指標 | 描述 | 方向 | 目標 |
|------|------|------|------|
| **segSNR** | 帶 VAD 的分段 SNR | ⬆️ 越高越好 | > 8.0 dB |
| **fwSegSNR** | 頻率加權分段 SNR | ⬆️ 越高越好 | > 9.0 dB |
| **WSS** | 加權頻譜斜率距離 | ⬇️ 越低越好 | < 50 |
| **PESQ** | 感知語音質量 | ⬆️ 越高越好 | > 2.5 |
| **STOI** | 短時客觀可懂度 | ⬆️ 越高越好 | > 0.85 |

#### 為什麼使用 Loizou 標準？

**傳統 segSNR 的問題**：
- 包含靜音幀導致評估不準確
- 與主觀評分相關性僅 0.40-0.46
- 極值 SNR 會扭曲平均值

**Loizou 改進**：
- ✅ 使用 VAD 排除靜音幀（相關性提升到 0.65-0.72）
- ✅ 限制 SNR 範圍在 [-10, 35] dB
- ✅ 頻率加權更符合人耳感知
- ✅ Bark 頻帶權重模擬聽覺特性

#### 快速評估

```bash
# 完整評估所有方法
python3 comprehensive_evaluation.py
```

輸出：
- `results/loizou_evaluation.json` - 詳細數據
- `results/loizou_evaluation.csv` - 表格
- `results/loizou_evaluation.md` - 報告

詳細說明請參考：[EVALUATION_GUIDE.md](EVALUATION_GUIDE.md)

### 對標結果（v4.2.2 — 2026-06-11）

與業界標準 Speex/RNNoise 對比。測試集：13 cases（clean + babble/car/street × 0/5/10/15 dB SNR）。

> **v4.2.2 演算法修正影響**：D2 fix（IMCRA 恢復正確 internal SPP gate）令 V3-2 ΔPESQ
> 大幅提升（+0.452 vs 舊 +0.387）；D3 fix（V3 MMSE-STSA 改用正確 Bessel 公式）調整
> V3 gain — 舊分數由錯用 MMSE-LSA 公式產生（過高），新分數為正確基準。

#### 改善量指標（Improvement）- 主要指標

| 排名 | 方法 | segSNR改善↑ | fwSegSNR改善↑ | ΔPESQ | Enhanced STOI |
|------|------|-------------|---------------|-------|---------------|
| 🥇 1 | **V3-2 (MMSE-LSA)** | **+4.79 dB** | **+4.29 dB** | **+0.452** | 0.872 |
| 🥈 2 | **RNNoise** | +2.85 dB | +2.08 dB | +0.390 | **0.905** |
| 🥉 3 | **Speex** | +1.37 dB | +0.68 dB | +0.120 | 0.888 |
| 4 | V3-3 (PMMSE) | +1.52 dB | +0.91 dB | +0.114 | 0.843 |
| 5 | V3 (MMSE-STSA) | +2.13 dB | +1.36 dB | +0.061 | 0.838 |

#### PESQ/STOI 排名（感知語音質量）- 參考指標

| 排名 | 方法 | Enhanced PESQ | ΔPESQ | Enhanced STOI | 特點 |
|------|------|---------------|-------|---------------|------|
| 🥇 1 | **V3-2 (MMSE-LSA)** | **1.971** | **+0.452** | 0.872 | **PESQ 絕對值 + 改善量雙冠** |
| 🥈 2 | **RNNoise** | 1.909 | +0.390 | **0.905** | **STOI 最佳（深度學習）** |
| 🥉 3 | **Speex** | 1.640 | +0.120 | 0.888 | 傳統基準 |
| 4 | V3-3 (PMMSE) | 1.634 | +0.114 | 0.843 | 感知優化 |
| 5 | V3 (MMSE-STSA) | 1.581 | +0.061 | 0.838 | 基礎版本 |

**✅ v4.2.2 關鍵改進**：
- ✅ **V3-2 PESQ 新冠軍**：ΔPESQ +0.452（D2 IMCRA fix 恢復正確 noise gate → 改善 +0.065）
- ✅ **D2 IMCRA fix**：external SPP posterior floor ~0.5 不再阻塞 fast-update leg
- ✅ **D3 MMSE-STSA fix**：V3 gain 改用正確 Bessel 公式（原 MMSE-LSA 公式不正確）
- ✅ **D1 OLA tail fix**：reconstructor 輸出長度 = 輸入長度（tail frames 不再丟失）
- ✅ **V3-2 優於 RNNoise PESQ**：1.971 vs 1.909（傳統 DSP 超越深度學習 PESQ）
- 📊 詳細報告：[results/improvement_report.md](results/improvement_report.md)

輸出範例：
```
======================================================================
Metrics for: V3 SPP-MMSE
======================================================================

[PRIMARY METRICS - Segmental SNR]
  Input segSNR:         5.23 dB
  Output segSNR:        15.67 dB
  segSNR Improvement:   10.44 dB  ★

[Global SNR Metrics]
  Input SNR:            10.00 dB
  Output SNR:           18.34 dB
  SNR Improvement:      8.34 dB

[Reference Metrics - For comparison only]
  PESQ:                 1.45 (1.0-4.5)
  STOI:                 0.756 (0-1)

[Quality Metrics]
  LSD:                  2.34 dB
  Musical Noise:        1.23e-05

======================================================================
Note: For traditional denoising, focus on segSNR improvement (★)
======================================================================
```

### 指標使用建議

| 指標類型 | 用途 | 適用場景 |
|---------|------|---------|
| **segSNR** ⭐ | **主要評估** | **傳統降噪算法 (V1-V4)** |
| Global SNR | 次要參考 | 全局能量評估 |
| PESQ | 參考 | 語音編碼器、深度學習模型 |
| STOI | 參考 | 可懂度評估、深度學習模型 |
| LSD | 輔助 | 頻譜失真程度 |
| Musical Noise | 診斷 | 檢測音樂噪聲偽影 |

### segSNR 典型數值範圍

| segSNR 改善 | 降噪效果 |
|------------|---------|
| < 3 dB | 效果不明顯 |
| 3-6 dB | 輕微改善 |
| 6-10 dB | 明顯改善 |
| 10-15 dB | 顯著改善 ⭐ |
| > 15 dB | 極佳效果 |

## 🚀 快速開始

### 方法 1: 處理單個音頻文件

```bash
# 使用推薦的 V3 和 V4 處理音頻
python3 process_audio.py your_audio.wav --versions V3 V4

# 輸出:
# - your_audio_v3.wav
# - your_audio_v4.wav
# - your_audio_waveforms.png（波形對比圖）
```

### 方法 2: 完整評估工作流程（v2.0）

如果您想複現 v2.0 的評估結果：

```bash
# 1. 準備測試音檔
# 將您的測試檔案放在 test_wav/wav/append_silence/ 目錄
# 格式: {noise_type}_{snr}dB_prepend.wav
# 例如: babble_10dB_prepend.wav

# 2. 重新生成所有降噪輸出（使用優化配置）
python3 regenerate_all_outputs.py
# 輸出: denoised_original/ 目錄中的 84 個 .wav 文件

# 3. 計算 Improvement 指標並生成報告
python3 compute_improvement.py
# 輸出: results/improvement_report.md
```

### 方法 3: Python API（推薦用於集成）

```python
from denoisers import SppMmseDenoiser  # 使用 V3（推薦）
from utils.audio_io import read_audio, write_audio

# 讀取帶噪音頻
audio, sr = read_audio('noisy.wav')

# 創建降噪器
denoiser = SppMmseDenoiser(sample_rate=sr)

# 降噪處理
enhanced = denoiser.denoise(audio)

# 保存結果
write_audio('enhanced.wav', enhanced, sr)
```

## 📂 測試音檔放置說明

### 目錄結構
```
test_wav/
└── wav/
    ├── clean.wav                    # 乾淨參考音檔（必須）
    ├── append_silence/              # ⭐ 測試檔案放這裡
    │   ├── babble_0dB_prepend.wav   # 前面添加了 0.5s 靜音
    │   ├── babble_5dB_prepend.wav
    │   └── ...
    └── benchmark_wav/               # 基準方法輸出（對標用）
        ├── speex/
        └── rnnoise/
```

### 為什麼需要 0.5s prepend？
我們的降噪算法需要初始化幀來估計噪聲特徵。測試檔案前添加 0.5s 靜音：
- 確保算法有足夠的噪聲樣本進行初始化
- 評估時會自動 trim 掉這 0.5s，確保與 clean.wav 對齊

### 如何準備測試檔案？
如果您有自己的音頻文件，需要：
1. 準備 clean.wav（乾淨音檔）
2. 添加噪聲並在前面 prepend 0.5s
3. 放在 `test_wav/wav/append_silence/` 目錄

**或者** 使用工具生成（如果您有 clean speech 和 noise）：
```python
from utils.test_data_generator import TestDataGenerator
import soundfile as sf
import librosa

# 加載音頻
clean, sr = librosa.load('your_clean.wav', sr=None)
noise, _ = librosa.load('your_noise.wav', sr=None)

# 生成測試集
generator = TestDataGenerator(sample_rate=sr)
test_set = generator.generate_test_set(
    clean,
    noise_types=['babble', 'car'],
    snr_levels=[0, 5, 10, 15],
    output_dir='test_wav/wav/append_silence'
)
```

## 📖 詳細文檔

- **[評估指標使用指南](docs/METRICS_USAGE.md)** - 評估指標詳細說明和使用範例
- **[V3 變體詳細對比](docs/V3_VARIANTS_COMPARISON.md)** - MMSE 變體技術對比和選擇建議
- **[演算法詳解](ALGORITHMS_EXPLANATION.md)** - 技術原理和公式推導
- **[更新日誌](CHANGELOG.md)** - 版本歷史和變更記錄

## 📊 V3 變體選擇指南

本系統提供 4 個基於 MMSE 理論的降噪算法變體，適用於不同場景：

### 快速決策表

| 需求 | 推薦版本 | 原因 |
|------|---------|------|
| **最佳綜合效果** | V3 或 V4 | 平衡性能與質量 |
| **非穩態噪聲** | V3-4 (OMLSA-MCRA) | 瞬態偵測快速適應 |
| **最佳音質** | V3-2 (MMSE-LSA) | Musical Noise 最少 |
| **學術研究** | V3-3 (PMMSE) | 感知動機方法 |
| **實時性能** | V3 (MMSE-STSA) | 計算最快 |

### 詳細對比

#### V3: MMSE-STSA (Speech Presence Probability + MMSE)
- **成本函數**: E[(X-X̂)²] (線性域 MSE)
- **先驗分佈**: Gaussian
- **計算複雜度**: 中等
- **音質特點**: 平衡，標準實現
- **適用場景**:
  - 需要標準 MMSE 實現作為基準
  - 實時處理要求較高
  - 一般語音增強應用
- **配置**: `config/v3_config.yaml`

#### V3-2: MMSE-LSA (Log-Spectral Amplitude MMSE)
- **成本函數**: E[(log X - log X̂)²] (對數域 MSE)
- **先驗分佈**: Gaussian
- **計算複雜度**: 中等
- **音質特點**: Musical Noise 更少，頻譜更平滑
- **適用場景**:
  - 對音質要求高
  - 需要減少 Musical Noise
  - 語音通信、會議系統
- **配置**: `config/v3_2_config.yaml`

#### V3-3: PMMSE (Perceptually Motivated MMSE)
- **成本函數**: E[(X-X̂)²/X] (IS 距離)
- **先驗分佈**: Gaussian (complex Gaussian → Rayleigh 幅度分佈)
- **計算複雜度**: 較高
- **音質特點**: 感知優化，實驗性質
- **適用場景**:
  - 學術研究和實驗
  - 感知質量優化研究
  - 對比不同成本函數效果
- **配置**: `config/v3_3_config.yaml`
- **注意**: 需要 scipy >= 1.7.0

#### V3-4: OMLSA-MCRA
- **增益函數**: OMLSA (Optimally-Modified Log-Spectral Amplitude)
- **噪聲估計**: MCRA (含瞬態偵測)
- **計算複雜度**: 中等
- **音質特點**: 快速適應非穩態噪聲
- **適用場景**:
  - 非穩態噪聲環境（街道、咖啡廳）
  - 需要快速噪聲適應
  - 語音存在機率軟判決
- **配置**: `config/v3_4_config.yaml`
- **v2.7 新增**: MCRA 場景轉換偵測 (平滑能量比 + hard threshold, β > θ → η=0.1, 否則 η=1.0)
  > **⚠️ v4.1 已棄用**: Eta 機制已完全移除，L=5 優化提供更快且可靠的場景適應（詳見 `MCRA_SCENE_CHANGE_ANALYSIS.md`）

### 性能對比 (典型值)

| 指標 | V3 | V3-2 | V3-3 | V3-4 |
|------|-------|-------|-------|-------|
| **segSNR 改善** | 10-12 dB | 11-13 dB | 9-11 dB | 12-14 dB |
| **WSS (越小越好)** | 45-55 | 40-50 | 50-60 | 35-45 |
| **Musical Noise** | 輕微 | 最少 | 中等 | 輕微 |
| **計算速度 (RTF)** | 0.003 | 0.004 | 0.005 | 0.004 |

**註**: 實際性能取決於噪聲類型、SNR 和參數配置

### 使用範例

```bash
# V3-2: 高音質降噪
python3 process_audio.py input.wav --versions V3-2 --config-dir config

# V3-4: 最強降噪
python3 process_audio.py input.wav --versions V3-4 --config-dir config

# 對比所有 MMSE 變體
python3 process_audio.py input.wav --versions V3 V3-2 V3-3 V3-4
```

### 參數調整建議

不同變體的關鍵參數：

**V3-2 (MMSE-LSA)**:
- `g_min_db`: -20 dB (可適度降低到 -25 dB)
- `alpha_g`: 0.7 (平滑度，減少 Musical Noise)

**V3-3 (PMMSE)**:
- `g_min_db`: -20 dB (建議範圍: -15 到 -25)
- `alpha_g`: 0.7 (增益時間平滑因子)
- `use_full_formula`: false (推薦數值穩定簡化版)

**V3-4 (OMLSA-MCRA)**:
- `g_min_db`: -20.0 dB (最小增益)
- `alpha_g`: 0.70 (增益時間平滑)
- `use_linear_spp_weighting`: false (使用對數域加權)

詳見：[V3 變體詳細對比](docs/V3_VARIANTS_COMPARISON.md)

## 🆕 重要更新（2024-12）

### Musical Noise 修復

我們已經修復了所有版本的 musical noise（金屬震動聲）問題：

| 版本 | 修復內容 | 改善程度 |
|------|---------|---------|
| V1 | 添加時間平滑 `alpha_smooth=0.8` | 83% 改善 |
| V2 | 添加時間平滑 `alpha_smooth=0.8` | 80%+ 改善 |
| V3 | 提高平滑因子 `alpha_g=0.85` (原0.7) | 30% 改善 |
| V4 | 提高平滑因子 `alpha_g=0.85` (原0.7) | 20% 改善 |

**平滑機制原理**：
```
增益_t = α × 增益_{t-1} + (1-α) × 增益_當前
```
- α = 0.8/0.85：平滑因子，越大越平滑
- 減少幀間增益跳變，避免產生金屬音

**測試檔案**：
使用前 2 秒為純噪聲的測試音頻驗證（`*_2s_silence.wav`），修復後純噪聲段平穩無震動。

## 📁 項目結構（v2.0）

```
speech_denoise/
├── denoisers/                     # 降噪算法實現（7個算法）
│   ├── base_denoiser.py
│   ├── v1_spectral_subtraction.py
│   ├── v2_wiener.py
│   ├── v3_spp_mmse.py
│   ├── v3_2_mmse_lsa.py
│   ├── v3_3_pmmse.py
│   ├── v3_4_omlsa.py
│   └── v4_imcra_omlsa.py
│
├── core/                          # 核心模塊
│   ├── frame_processor.py
│   ├── reconstructor.py
│   ├── spp_estimator.py
│   ├── noise_estimators/
│   │   ├── simple_average.py
│   │   ├── recursive_average.py
│   │   ├── mcra.py                # 雙視窗最小值追蹤 (v2.5 重構)
│   │   └── imcra.py
│   └── gain_calculators/
│       ├── spectral_subtraction.py
│       ├── wiener.py
│       ├── spp_mmse.py
│       ├── mmse_lsa.py
│       ├── pmmse.py
│       └── omlsa.py
│
├── utils/                         # 工具模塊
│   ├── audio_io.py
│   ├── metrics.py                 # PESQ, STOI
│   ├── metrics_loizou.py          # Loizou 2008 專業指標
│   ├── test_data_generator.py
│   └── visualization.py
│
├── config/                        # ⭐ 配置文件（v2.0 優化後）
│   ├── v1_config.yaml             # V1 優化配置
│   ├── v2_config.yaml
│   ├── v3_config.yaml             # V3 優化配置（35% 提升）
│   ├── v3_2_config.yaml
│   ├── v3_3_config.yaml
│   ├── v3_4_config.yaml
│   └── v4_config.yaml
│
├── test_wav/                      # ⭐ 測試音檔目錄
│   └── wav/
│       ├── clean.wav
│       ├── append_silence/        # 測試檔案（含 0.5s prepend）
│       └── benchmark_wav/         # Speex/RNNoise 輸出
│
├── denoised_original/             # ⭐ v2.0 生成的降噪輸出（84個文件）
│   ├── V1_*.wav
│   ├── V2_*.wav
│   ├── V3_*.wav
│   ├── V3-2_*.wav
│   ├── V3-3_*.wav
│   ├── V3-4_*.wav
│   └── V4_*.wav
│
├── results/                       # ⭐ 評估結果
│   ├── improvement_report.md
│   └── improvement_report_final.md
│
├── tools/                         # ⭐ 工具腳本（v2.0 整理後）
│   ├── benchmark_all.py           # 性能基準測試
│   ├── benchmark_comparison.py    # 對標評估
│   ├── comprehensive_evaluation.py
│   ├── diagnose_algorithm.py
│   ├── validate_best_config.py
│   └── generate_comparison_tables.py
│
├── process_audio.py               # ⭐ 單文件處理工具
├── regenerate_all_outputs.py      # ⭐ 重新生成所有測試輸出
├── compute_improvement.py         # ⭐ 計算 Improvement 指標
├── benchmark.py                   # ⭐ 統一 benchmark 入口
│
├── CHANGELOG.md
├── README.md
├── PROJECT_STATUS.md
└── ALGORITHMS_EXPLANATION.md
```

**⭐ v2.0 整理後的根目錄（清爽簡潔）**:
- 只保留 4 個核心 .py 文件（處理音檔 + 評估）
- 工具腳本統一放在 `tools/` 目錄
- 文檔文件保持在根目錄

## 🔬 算法版本對比

| 版本 | 噪聲估計 | 增益計算 | Musical Noise | 語音失真 | 複雜度 | 推薦度 |
|------|---------|---------|---------------|---------|--------|--------|
| V1 頻譜減法 | 前幾幀平均 | 直接相減 | ✅ 已修復 | ⚠️ 中等 | ✅ 低 | ⭐⭐ |
| V2 Wiener | 遞歸平均 | Wiener增益 | ✅ 已修復 | ✅ 低 | ✅ 中 | ⭐⭐⭐ |
| V3 SPP-MMSE | 遞歸平均 | SPP加權MMSE | ✅ 極少 | ✅✅ 很低 | ⚠️ 中高 | ⭐⭐⭐⭐⭐ |
| V4 IMCRA-OMLSA | IMCRA | OMLSA | ✅ 極少 | ✅✅✅ 極低 | ⚠️⚠️ 高 | ⭐⭐⭐⭐⭐ |

### 性能指標（39秒音頻 @ 16kHz）

| 版本 | 處理時間 | RTF | 狀態 |
|------|---------|-----|------|
| V1 | 120 ms | 0.003 | ✓ 實時 |
| V2 | 126 ms | 0.003 | ✓ 實時 |
| V3 | 230 ms | 0.006 | ✓ 實時 |
| V4 | 295 ms | 0.008 | ✓ 實時 |

所有版本都遠超實時處理標準（RTF << 1.0）！

## 📚 核心概念與參數調整

### 通用音頻參數

```yaml
audio:
  sample_rate: 16000      # 採樣率（VoIP標準）
  frame_size: 512         # 幀長 (samples, 32ms @ 16kHz = FFT size，無需 zero-padding)
  hop_size: 256           # 幀移 (samples, 16ms @ 16kHz)，50% overlap
  fft_size: 512           # FFT點數
  window_type: "hanning"  # 窗函數類型
```

**調整建議**：
- 更低延遲：減小 `frame_size` 和 `hop_size`
- 更好頻率分辨率：增加 `fft_size`（512/1024/2048）

### V1: 頻譜減法參數

```yaml
# config/v1_config.yaml
gain_calculation:
  alpha: 1.0              # 過減因子（1.5-2.5）
  beta: 0.02              # 頻譜下限（0.002-0.02）
  alpha_smooth: 0.8       # 時間平滑因子 ⭐
```

**關鍵參數說明**：
- `alpha`：過減因子
  - 越大降噪越多，但可能過度抑制語音
  - 建議：1.0-2.0（10dB SNR 用 1.0）
- `beta`：頻譜下限
  - 防止增益過小導致失真
  - 建議：0.02（保留至少 2% 信號）
- `alpha_smooth`：**時間平滑因子**（新增，修復 musical noise）
  - 越大越平滑，但語音起始可能稍模糊
  - 建議：0.75-0.85

### V2: Wiener 濾波參數

```yaml
# config/v2_config.yaml
noise_estimation:
  alpha: 0.95             # 噪聲平滑因子（0.9-0.95）
  update_during_speech: false  # 是否在語音段更新

gain_calculation:
  min_gain: 0.1           # 最小增益
  alpha_smooth: 0.8       # 時間平滑因子 ⭐
```

**關鍵參數說明**：
- 噪聲估計 `alpha`：
  - 越大越平滑，但適應速度越慢
  - 建議：0.95（穩態噪聲）、0.90（非穩態噪聲）
- `min_gain`：最小增益
  - 防止過度抑制
  - 建議：0.1（保留 10% 信號）
- `alpha_smooth`：**時間平滑因子**（新增，修復 musical noise）
  - 建議：0.8

### V3: SPP-MMSE 參數 ⭐ 重點

```yaml
# config/v3_config.yaml
spp:
  alpha_xi: 0.98          # 先驗SNR平滑因子（0.92-0.98）
  q: 0.5                  # 語音先驗機率
  xi_min_db: -25.0        # 最小先驗SNR (dB)

gain_calculation:
  g_min_db: -20.0         # 最小增益 (dB)
  alpha_g: 0.85           # 增益平滑因子 ⭐
```

**關鍵參數說明**：
- `alpha_xi`：**先驗 SNR 平滑因子**
  - Decision Directed 方法的核心參數
  - 越接近 1 越平滑，但反應越慢
  - 建議：0.95-0.98（語音變化慢）、0.92-0.95（語音變化快）

- `q`：語音先驗機率
  - 影響 SPP 的計算偏向
  - 建議：0.5（平衡）、0.6-0.7（語音多）、0.3-0.4（噪聲多）

- `g_min_db`：**最小增益**
  - 控制降噪強度
  - 越小降噪越多，但語音失真越大
  - 建議：-15dB（輕微降噪）、-20dB（平衡）、-25dB（強力降噪）

- `alpha_g`：**增益時間平滑因子**（已強化）
  - 減少 musical noise 的關鍵參數
  - 建議：0.7-0.9（0.85 為最新優化值）

**SPP 核心公式理解**：
```python
# 1. 後驗 SNR
γ(k,l) = |Y(k,l)|² / λ_d(k,l)

# 2. 先驗 SNR (Decision Directed)
ξ(k,l) = α_xi · [G²(k,l-1) · γ(k,l-1)] + (1-α_xi) · max(γ(k,l)-1, 0)

# 3. 似然比
Λ(k,l) = ξ/(1+ξ) · γ

# 4. SPP（軟判決）
p(k,l) = 1 / [1 + (q/(1-q)) · exp(-Λ)]

# 5. SPP 加權增益
G(k,l) = p · G_MMSE + (1-p) · G_min
```

### V4: IMCRA-OMLSA 參數（產品級）

```yaml
# config/v4_config.yaml
noise_estimation:
  alpha_s: 0.9            # 頻譜平滑因子（0.85-0.95）
  alpha_d: 0.85           # 噪聲更新速率（0.80-0.90）
  L: 150                  # 最小值窗口長度（幀數）
  delta_db: 5.0           # 偏移補償 (dB)

gain_calculation:
  g_min_db: -20.0
  alpha_g: 0.85           # 增益平滑因子 ⭐
  gamma_0: 4.6            # SPP閾值參數
```

**關鍵參數說明**：
- `alpha_s`：頻譜平滑因子
  - 控制頻譜的時間平滑
  - 建議：0.85-0.95（越大越平滑）

- `alpha_d`：**噪聲更新速率**
  - 控制噪聲估計的更新速度
  - 越小更新越快，越大越保守
  - 建議：0.85（平衡）、0.90（穩態噪聲）、0.80（非穩態噪聲）

- `L`：**最小值追蹤窗口長度**
  - 單位：幀數（L=150 約 1.5 秒 @ 10ms 幀移）
  - 太小：追蹤不準確
  - 太大：適應慢，佔用內存多
  - 建議：100-200 幀

- `alpha_g`：**增益時間平滑因子**（已強化）
  - V4 使用對數域平滑，更符合人耳感知
  - 建議：0.7-0.9（0.85 為最新優化值）

**IMCRA 性能調優**：
- 穩態噪聲：增大 alpha_d (0.90)，減小 L (100)
- 非穩態噪聲：減小 alpha_d (0.80)，增大 L (200)
- 實時性要求高：減小 L
- 質量要求高：增大 L，增大 alpha_g

## 🔧 參數調整實戰指南

### 場景1：辦公室噪聲（穩態噪聲）

推薦配置：V3 或 V4
```yaml
# V3 配置
spp:
  alpha_xi: 0.98      # 高平滑（噪聲穩定）
gain_calculation:
  g_min_db: -20.0     # 平衡降噪

# V4 配置
noise_estimation:
  alpha_d: 0.90       # 保守更新（穩態）
  L: 100              # 較短窗口（加快適應）
```

### 場景2：街道噪聲（非穩態噪聲）

推薦配置：V4
```yaml
noise_estimation:
  alpha_d: 0.80       # 快速更新（非穩態）
  L: 200              # 較長窗口（更準確）
gain_calculation:
  alpha_g: 0.85       # 強平滑（減少波動）
```

### 場景3：高 SNR (> 10dB) 輕微降噪

推薦配置：V2 或 V3
```yaml
# V3 配置
spp:
  q: 0.6              # 語音先驗提高
gain_calculation:
  g_min_db: -15.0     # 輕微降噪
  alpha_g: 0.7        # 較低平滑（保留細節）
```

### 場景4：低 SNR (< 5dB) 強力降噪

推薦配置：V4
```yaml
noise_estimation:
  alpha_d: 0.85       # 平衡
  L: 200              # 長窗口（更準確）
gain_calculation:
  g_min_db: -25.0     # 強力降噪
  alpha_g: 0.9        # 強平滑（減少失真）
```

## 🐛 故障排除

### Musical Noise（金屬震動聲）仍然存在

**可能原因**：
1. 配置文件未更新
2. 使用舊版本代碼

**解決方案**：
```bash
# 確認配置文件包含 alpha_smooth/alpha_g 參數
grep -r "alpha_smooth\|alpha_g" config/

# 重新處理
python3 process_audio.py your_audio.wav --versions V2 V3 V4
```

### 語音起始模糊

**原因**：平滑因子過大

**解決方案**：
```yaml
# 降低平滑因子
alpha_smooth: 0.75  # V1/V2（原 0.8）
alpha_g: 0.7        # V3/V4（原 0.85）
```

### 降噪效果不足

**解決方案**：
```yaml
# V1: 提高過減因子
alpha: 2.0  # 原 1.0

# V3/V4: 降低最小增益
g_min_db: -25.0  # 原 -20.0
```

### 語音失真嚴重

**解決方案**：
```yaml
# V1: 降低過減因子
alpha: 1.0  # 原 2.0

# V3/V4: 提高最小增益
g_min_db: -15.0  # 原 -20.0
```

## 🎓 學習路徑

### 建議順序

1. **第1週：基礎框架**
   - 理解分幀、加窗、FFT
   - 實現 Overlap-Add 重建
   - 使用 `process_audio.py` 處理音頻

2. **第2週：V1 頻譜減法**
   - 最簡單的降噪方法
   - 理解 musical noise 問題和時間平滑解決方案
   - 調整 `alpha` 和 `beta` 參數觀察效果

3. **第3週：V2 Wiener 濾波**
   - 最優濾波理論
   - 遞歸噪聲估計
   - 對比 V1 的改進

4. **第4週：V3 SPP-MMSE** ⭐ 重點
   - 深入理解 SPP（語音存在機率）
   - Decision Directed 方法
   - 軟判決的優勢
   - 調整 `alpha_xi`、`q`、`g_min_db` 參數

5. **第5-6週：V4 IMCRA-OMLSA**
   - 最先進的噪聲估計（最小值追蹤）
   - 產品級效果
   - 理解 IMCRA 和 OMLSA 的協同

### 實驗建議

1. **生成測試數據**：
   ```python
   from utils.test_data_generator import TestDataGenerator, generate_sample_speech
   from utils.audio_io import write_audio

   generator = TestDataGenerator(sample_rate=16000)
   speech = generate_sample_speech(duration=2.0)

   # 生成不同 SNR 的測試集
   for snr in [-5, 0, 5, 10, 15]:
       noisy, noise = generator.create_noisy_speech(
           speech, noise_type='white', target_snr_db=snr
       )
       write_audio(f'test_snr{snr}dB.wav', noisy, 16000)
   ```

2. **對比不同參數**：
   ```bash
   # 修改配置文件後重新處理
   python3 process_audio.py test_snr5dB.wav --versions V3
   ```

3. **可視化效果**：
   生成的波形對比圖（`*_waveforms.png`）可直觀對比 Input 和 V1-V4 效果

## 📊 測試數據

### 方案 1: 使用 NOIZEUS Corpus（推薦）

```bash
# 訪問並下載
http://www.utdallas.edu/~loizou/speech/noizeus/

# 包含：
# - 30 個句子
# - 8 種噪聲類型
# - 4 個 SNR 等級 (0, 5, 10, 15 dB)
```

### 方案 2: 自己生成

```python
from utils.test_data_generator import TestDataGenerator

generator = TestDataGenerator(sample_rate=16000)

# 生成測試集
test_set = generator.generate_test_set(
    clean_speech,
    noise_types=['white', 'pink', 'babble'],
    snr_levels=[-5, 0, 5, 10, 15],
    output_dir='./test_data'
)
```

---

## 📖 參考文獻

### 基礎算法

**頻譜減法 (Spectral Subtraction)**:
- Boll, S. F. (1979). "Suppression of acoustic noise in speech using spectral subtraction." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 27(2), 113-120.
- DOI: 10.1109/TASSP.1979.1163209

**Wiener 濾波**:
- Lim, J. S., & Oppenheim, A. V. (1979). "Enhancement and bandwidth compression of noisy speech." *Proceedings of the IEEE*, 67(12), 1586-1604.
- DOI: 10.1109/PROC.1979.11540

**MMSE-STSA (V3, V3-1)**:
- Ephraim, Y., & Malah, D. (1984). "Speech enhancement using a minimum-mean square error short-time spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 32(6), 1109-1121.
- DOI: 10.1109/TASSP.1984.1164453

### MMSE 變體

**MMSE-LSA (V3-2)**:
- Ephraim, Y., & Malah, D. (1985). "Speech enhancement using a minimum mean-square error log-spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 33(2), 443-445.
- DOI: 10.1109/TASSP.1985.1164550
- 說明: 對數域 MMSE 估計，減少 Musical Noise

**PMMSE (V3-3)**:
- Loizou, P. C. (2005). "Speech enhancement based on perceptually motivated Bayesian estimators of the magnitude spectrum." *IEEE Transactions on Speech and Audio Processing*, 13(5), 857-869.
- DOI: 10.1109/TSA.2005.851929
- 說明: Gaussian 先驗 (Rayleigh 幅度分佈) + IS 距離，感知動機方法

**MCRA (V3-4 噪聲估計)**:
- Cohen, I., & Berdugo, B. (2002). "Noise estimation by minima controlled recursive averaging for robust speech enhancement." *IEEE Signal Processing Letters*, 9(1), 12-15.
- DOI: 10.1109/97.988717
- 說明: V3-4 使用 MCRA 噪聲估計 + OMLSA 增益，含瞬態偵測

### 先進算法

**SPP (Speech Presence Probability)**:
- Cohen, I., & Berdugo, B. (2001). "Speech enhancement for non-stationary noise environments." *Signal Processing*, 81(11), 2403-2418.
- DOI: 10.1016/S0165-1684(01)00128-1

**IMCRA (Improved Minima Controlled Recursive Averaging)**:
- Cohen, I., & Berdugo, B. (2002). "Noise estimation by minima controlled recursive averaging for robust speech enhancement." *IEEE Signal Processing Letters*, 9(1), 12-15.
- DOI: 10.1109/97.988717

**OMLSA (Optimally-Modified Log-Spectral Amplitude)**:
- Cohen, I. (2002). "Optimal speech enhancement under signal presence uncertainty using log-spectral amplitude estimator." *IEEE Signal Processing Letters*, 9(4), 113-116.
- DOI: 10.1109/97.1001645

### Musical Noise 抑制

**時間平滑技術**:
- Cappé, O. (1994). "Elimination of the musical noise phenomenon with the Ephraim and Malah noise suppressor." *IEEE Transactions on Speech and Audio Processing*, 2(2), 345-349.
- DOI: 10.1109/89.279283
- 本項目實現: 時間域增益平滑 + 對數域平滑（V4）

### 評估指標

**客觀評估指標**:
- Hu, Y., & Loizou, P. C. (2008). "Evaluation of objective quality measures for speech enhancement." *IEEE Transactions on Audio, Speech, and Language Processing*, 16(1), 229-238.
- DOI: 10.1109/TASL.2007.911054
- 說明: segSNR, fwSegSNR, WSS 等指標的推薦標準

**PESQ (Perceptual Evaluation of Speech Quality)**:
- ITU-T Recommendation P.862 (2001). "Perceptual evaluation of speech quality (PESQ): An objective method for end-to-end speech quality assessment of narrow-band telephone networks and speech codecs."
- URL: https://www.itu.int/rec/T-REC-P.862

**STOI (Short-Time Objective Intelligibility)**:
- Taal, C. H., Hendriks, R. C., Heusdens, R., & Jensen, J. (2011). "An algorithm for intelligibility prediction of time–frequency weighted noisy speech." *IEEE Transactions on Audio, Speech, and Language Processing*, 19(7), 2125-2136.
- DOI: 10.1109/TASL.2011.2114881

### 在線資源

- **IEEE Xplore**: https://ieeexplore.ieee.org/ (論文訪問)
- **Google Scholar**: https://scholar.google.com/ (論文搜索)
- **arXiv**: https://arxiv.org/ (預印本)
- **Loizou's Speech Enhancement Book**: http://www.utdallas.edu/~loizou/speech/software.htm (MATLAB 代碼和數據集)

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

### 開發建議

- 遵循現有代碼風格
- 添加中文注釋
- 更新相關文檔
- 提供測試用例

## 📄 授權

MIT License

## 🔮 未來工作 (Future Work)

### 潛在改進

#### 參數自動調優
- 基於噪聲類型和 SNR 級別的自適應參數選擇
- 在線學習優化 alpha_xi, g_min_db 等關鍵參數

#### 深度學習集成
- 使用神經網絡改進 SPP 估計
- 混合傳統+深度學習的 hybrid 方案

---

## 📜 版本歷史

### v4.2.0 (2026-04-17) ✨ 最新 · Release
- 🔧 **Part A Review 修復（11 項）**：
  - **#1** MCRA 初始化 `S = init_psd`（原為 `avg_power`，與 `S_min` 不一致會造成首幀異常 ratio）
  - **#3** SPP Decision-Directed term 改用**前一幀** `noise_psd`（原為當前幀，理論不一致）
  - **#6** Scene change flatness 閾值從硬編 0.4 改為 config 可調
  - **#7** 分析/合成 window 改為 periodic (`sym=False`)，COLA 完全準確
  - **#9** SPP prior probability `q` 在 create 時 clip 至 `(1e-6, 1-1e-6)`
  - **#2 / #8** init passthrough + auto-reset（Python 端）
  - **#4 / #5** `alpha_d` 接通、asymmetric smoothing（`alpha_attack` / `alpha_decay`）參數外露
  - **#10 / #11** 清理過時註解與 `__main__`
- 🧪 **V4 OMLSA 誠實定位**：
  - Wind Handler (`core/wind_detector.py`, `core/freq_adaptive_controller.py`, `core/transient_suppressor.py`) 在 VCTK/DEMAND 子集**未能改善風聲**，主要原因：風聲低頻能量與語音 F1/F2 頻段重疊，單麥克風 + 統計特徵無法可靠區分
  - v4_config.yaml 預設 **FLAT** adaptive profile（等同 V3-2）+ **transient OFF**
  - 保留 V4 作為 research 框架（詳見 `results/v4_diagnosis_report.md`）
- 🖇️ **C 實作同步**：Part A 核心 4 項 (#1, #3, #6, #9) 已 port 到 C，同步至 `main`（malloc）與 `feature/static-memory`（靜態記憶體）兩條 branch
- 📋 **文檔重構**：更新 README / c_impl/README / ALGORITHMS_EXPLANATION / parameter_adjust_guide 加入 release 用限制條件、風聲/impulse 不適用 case、調參方法

### v4.1.0 (2026-03-04)
- 🚨 **Eta 機制完全移除**: 測試證明 L=5 優化已替代 eta 功能
  - test_wav: enable_eta 降低 PESQ 0.06-0.41
  - VCTK: enable_eta 收益僅 0.006 PESQ（可忽略不計）
  - Python + C 實現完全同步
- ✅ **C 實現同步 Python V3-2 (v4.0)**:
  - alpha_s: 0.8 → 0.7 (更快時間響應)
  - L: 120 → 5 (場景適應速度提升 24 倍)
  - init_percentile: 20th → 30th (更準確初始化)
- 📚 **文檔更新**: 所有 eta 相關內容標記為已棄用

### v2.7.0 (2026-02-03)
- 🐛 **MCRA Eta 場景轉換偵測修正**: sigmoid (η≤0.95) → 平滑能量比 + hard threshold (η=1.0 或 0.1)
  > **⚠️ v4.1 注記**: 此機制已在 v4.1 完全移除，L=5 優化已提供更好的場景適應
  - 修正舊版語音幀噪聲更新速度增加 ~10x 的問題
  - VCTK 驗證: PESQ +0.085→+0.399, STOI -0.068→-0.010

### v2.6.0 (2026-01-22)
- ✨ **V3-4 架構重構**: 從 Laplacian-MMSE 改為 OMLSA-MCRA
  - 使用 MCRA 噪聲估計 + OMLSA 增益函數
  - 新增瞬態偵測 (energy ratio based η)
- ✨ **Human Voice Band Soft VAD**: 全版本新增後處理
  - 頻率範圍: 300Hz - 3400Hz
  - 映射函數: y = 0.1 + 0.9 * (1 - e^(-3*mean_power))
  - 時間平滑: α_vad = 0.95
- ✨ **MCRA 場景轉換偵測 (v2.7 更新)** ⚠️ **已在 v4.1 棄用**:
  - 平滑能量: E_smooth = 0.7 * E_smooth_prev + 0.3 * E_cur
  - 能量比 β = E_smooth / E_smooth_prev
  - Hard threshold: β > θ → η=0.1（加速噪聲更新），否則 η=1.0（不干擾）
  - v2.7 修正: 舊版 sigmoid (η=0.95 上限) 導致語音幀噪聲更新速度增加 10x
  - **v4.1 移除原因**: L=5 優化已提供 50ms 快速場景適應，無需 eta 機制
- 🔄 **OmlsaMcraDenoiser**: 替換 LaplacianMmseDenoiser

### v2.5.0 (2026-01-16)
- ✨ **MCRA 單/雙視窗模式切換**: `use_dual_window` 參數支持效果比較
- 🧹 **清理冗餘程式碼**: 移除死代碼 (spp fast startup, imcra fast tracking, reconstructor 未使用方法)
- ✅ **IMCRA 遺忘機制驗證**: 確認 Cohen 2003 最小值重置邏輯正確

### v2.4.0 (2026-01-11)
- ✨ **Optuna 貝葉斯優化**: 全版本 1000-trial 參數優化

  | 版本 | PESQ | STOI | segSNR | xi_min_db | g_min_db | alpha_g |
  |------|------|------|--------|-----------|----------|---------|
  | V4 (IMCRA-OMLSA) | **1.747** | **0.859** | +5.22 dB | -19.0 | -17.0 | 0.87 |
  | V3-2 (MMSE-LSA) | 1.738 | **0.859** | +5.12 dB | -22.0 | -13.0 | 0.84 |
  | V3-3 (PMMSE) | 1.688 | 0.839 | **+6.06 dB** | -19.0 | -18.0 | 0.80 |
  | V3 (MMSE-STSA) | 1.676 | 0.837 | +6.00 dB | -25.0 | -17.0 | 0.80 |
  | V3-4 (Laplacian) | 1.539 | 0.840 | +5.10 dB | -15.0 | -18.0 | 0.70 |

- ✨ **V3-4 Rescue 優化**: xi_min 原 -10.0 過高導致微弱語音被截斷，g_min 原 -25.0 過低導致死寂

### v2.3.0 (2026-01-08)
- ✨ **重構噪聲追蹤機制**: 移除外部 NoiseChangeDetector
  - MCRA 雙視窗最小值追蹤內建處理場景變化
  - 每 L 幀自動更新最小值（Cohen & Berdugo 2002）
- ⬆️ 簡化降噪器架構，移除 enable_noise_tracking 參數

### v2.2.0 (2026-01-08)
- ✨ **V2 Wiener Filter 核心改進**:
  - 使用 SppEstimator（Bayesian SPP）取代 Sigmoid 近似
  - DD 公式正確使用 enhanced_mag_prev
  - ΔPESQ 從 +0.035 提升至 +0.244
- ✨ **MCRA 噪聲估計支持**: 所有版本可選 MCRA 噪聲估計
- ✨ **V3-3 PMMSE**: 實作 Wolfe & Godsill β=0.5 公式
- ✨ **V3-4 Laplacian**: 實作 Chen & Loizou 2007 公式

### v2.1.2 (2026-01-06)
- 🐛 **修復 segSNR 計算 bug**: benchmark_comparison.py 錯誤地將 sample_rate 傳遞給 frame_size 參數
- ✅ **更新基準測試結果**: 使用正確的 frame_size=256, hop_size=128 計算 segSNR

### v2.1.1 (2026-01-06)
- ✅ **V3 系列參數同步優化**: alpha_xi=0.96 同步到所有 V3 變體

### v2.1.0 (2026-01-05)
- ✅ **V3-3 參數優化**: 採用 V3-2 對齊參數，PESQ 從 1.458 提升至 1.733 (+18.9%)
  - 核心發現：SNR Adaptive (enable: true, base_g_min_db: -12.0) 是高性能的關鍵
  - 對齊參數：alpha_xi=0.92, q=0.5, g_min_db=-20.0, alpha_g=0.7
- ✅ **V3-4 參數優化**: 採用 V3-2 對齊參數，STOI 達到 0.874（傳統算法最佳）
- ✅ **Clean 保護測試**: 新增 clean.wav 高 SNR 測試用例（13 個測試用例）
  - 所有方法通過 clean protection 測試（PESQ 降幅 < 0.01）
- ✅ 更新 README 和文檔，版本升級至 v2.1.0

### v2.0.0 (2026-01)
- ✅ **V3 整合 V3-1**：統一 MMSE-STSA 實現
  - 支持 Bessel/E1 公式切換（`use_full_formula` 參數）
  - 統一命名為 "MMSE-STSA"
  - 刪除獨立的 V3-1 版本
- ✅ **V4 全面優化**：修復音量和震動問題
  - 音量損失從 8-10dB 降至 3-5dB
  - 添加混合策略和變化限制
  - 自適應 delta 調整（3-12dB）
- ✅ **MCRA 雙視窗最小值追蹤**：內建於噪聲估計器
  - 自動適應噪聲場景變化
  - 每 L 幀強制更新最小值
- ✅ 更新所有配置文件和文檔

### v1.4.0 (2026-01)
- ✅ **新增 MMSE 變體**：4 個學術標準實現
  - V3-1: MMSE-STSA (Ephraim-Malah 1984) - 已合併到 V3
  - V3-2: MMSE-LSA (對數域 MMSE)
  - V3-3: PMMSE (Gaussian 先驗 + IS 距離)
  - V3-4: Laplacian-MMSE (Laplacian 先驗 + MSE)
- ✅ **新增 Loizou 評估指標**：專業語音質量評估
  - segSNR with VAD
  - fwSegSNR (頻率加權)
  - WSS (加權頻譜斜率距離)

### v1.3.0 (2026-01)
- ✅ 創建 ALGORITHMS_EXPLANATION.md（演算法詳解文檔）
- ✅ 整理和清理項目文檔

### v1.2.0 (2026-01)
- ✅ **添加 segSNR 評估指標**（主要指標）
- ✅ 更新評估指標體系，PESQ/STOI 改為參考指標
- ✅ 完善評估指標使用說明和文檔

### v1.1.0 (2024-12)
- ✅ **修復所有版本的 Musical Noise 問題**
- ✅ V1/V2 添加時間平滑機制
- ✅ V3/V4 強化增益平滑因子（0.7 → 0.85）
- ✅ 添加完整的參數調整指南
- ✅ 添加 process_audio.py 主處理工具
- ✅ 添加波形對比圖生成功能

### v1.0.0 (2024-11)
- ✅ 實現 V1-V4 四個版本
- ✅ 完整的測試數據生成工具
- ✅ 詳細的中文文檔

詳見：[CHANGELOG.md](CHANGELOG.md)

## 🎓 致謝

本項目基於經典信號處理理論實現，感謝所有論文作者的貢獻。

---

**推薦版本**：
- 🏆 **V4 (IMCRA-OMLSA)**: PESQ 改善最佳 (+0.410)，產品級效果
- 🥈 **V3-4 (OMLSA-MCRA)**: 非穩態噪聲適應，瞬態偵測
- 🥉 **V3 (MMSE-STSA)**: 平衡性能，適合一般應用

**v2.6 新特性**：Human Voice Band Soft VAD + MCRA 瞬態偵測！

---

## 📐 演算法規格 (Specification)

### 音訊格式要求

| 參數 | 規格 | 說明 |
|------|------|------|
| 取樣率 | 8000 / 16000 / 48000 Hz | 自動配置 FFT size 與 frame size |
| 聲道數 | 單聲道 (Mono) | C 實現自動取第一聲道 |
| 位元深度 | 16-bit PCM / 32-bit float | |
| 幀長度 | 20 ms（320 samples @ 16kHz） | 自動依取樣率計算 |
| Hop size | 10 ms（160 samples @ 16kHz） | 50% overlap |
| FFT size | 256 / 512 / 1024 | 自動取 ≥ frame_size 的最小 2 的冪次 |

### 處理性能

| 指標 | 數值 |
|------|------|
| 演算法延遲 | 32 ms（20ms frame + 10ms hop + 2ms 處理） |
| 即時率 (RTF) | < 0.01（遠低於即時要求） |
| 初始化靜默期 | 200 ms（前 20 幀用於噪聲底噪估計） |
| 每幀處理時間 | < 0.1 ms |

### 記憶體使用 (C 實現, 16kHz)

| 配置 | 記憶體用量 |
|------|-----------|
| 標準（`make`） | ~50 KB |
| 含精確 percentile（+Quickselect） | ~70 KB |
| 48kHz（MCRA min buffer 較大） | ~64 KB 額外（L × 513 × 4） |

### 降噪強度模式

| 模式 | g_min | 特性 |
|------|-------|------|
| MILD | -10 dB | 保留語音細節，適合低噪環境 |
| BALANCED（預設） | -15 dB | 平衡降噪與語音品質 |
| AGGRESSIVE | -20 dB | 強力抑噪，適合高噪環境 |

### 品質指標（V3-2 OMLSA, Balanced 模式）

**test_wav 混合噪聲平均**（歷史 Optuna 調參結果）：

| 指標 | 數值 |
|------|------|
| PESQ | 1.738 |
| STOI | 0.859 |
| segSNR 改善 | +5.12 dB |

**v4.2.1 VCTK/DEMAND 824 檔平均**（C-aligned 版本）：

| 指標 | Noisy | Enhanced | Delta |
|------|-------|----------|-------|
| PESQ | 1.973 | **2.391** | +0.418 |
| STOI | 0.921 | 0.906 | −0.015 |
| segSNR 改善 | - | - | +4.21 dB |
| fwSegSNR 改善 | - | - | +1.22 |
| LSD | 16.86 | 14.68 | −2.18 |

> v4.2.1 vs v4.2.0（pre-align）差異：PESQ −0.019、STOI −0.008、LSD +1.46。退步來自 3-segment E1 近似（與 C `exp1_approx` bit-exact 對齊的代價）。需要高精度時設 `core.gain_calculators.mmse_lsa.USE_SCIPY_EXP1 = True`。

---

## 🎧 可處理的噪聲類型 (Supported Noise Types)

### 適用場景 ✅

| 噪聲類型 | 說明 | 效果 |
|----------|------|------|
| **穩態噪聲 (Stationary)** | 風扇、冷氣、引擎怠速、白噪聲、粉紅噪聲 | 優秀 — MCRA 可精準追蹤穩定噪聲底噪 |
| **準穩態噪聲 (Quasi-stationary)** | 車內行駛噪聲、辦公室背景嗡嗡聲 | 優秀 — L=32 視窗（320ms）可平滑追蹤緩慢變化 |
| **人群嘈雜 (Babble)** | 多人交談的餐廳、會議室背景 | 良好 — SPP 可區分目標語音與背景人聲 |
| **街道環境噪聲 (Street)** | 車流、城市環境混合噪聲 | 良好 — 場景轉換偵測可適應突變 |
| **非穩態噪聲 (Non-stationary)** | 噪聲能量緩慢起伏、場景切換 | 良好 — 場景變化偵測（高頻 γ + spectral flatness）自動觸發噪聲重估 |

### 受限場景 ⚠️

| 噪聲類型 | 說明 | 限制原因 |
|----------|------|----------|
| **脈衝噪聲 (Impulse)** | 敲擊、關門、鍵盤敲擊、碗盤碰撞 | 瞬態持續時間 < 10ms hop，MCRA 來不及追蹤；可能殘留 1-2 幀後消失，或產生 musical noise artifact |
| **噪音能量突然變大 (Noise Burst)** | 路過的車輛、突然的引擎加速、開冷氣瞬間 | MCRA 用 minimum tracking 追噪聲底噪，TC 約 320-640ms；噪音突升 → noise PSD estimator 跟不上 → 前 0.3-0.6s 噪音漏抑制（gain 不夠低）|
| **噪音能量突然變小 (Noise Drop)** | 關閉風扇/冷氣、車輛遠離、噪音停止 | minimum tracking 反應快但 OMLSA 的 ξ (a priori SNR) 平滑慢；前 0.2-0.3s 仍會用舊噪音模型，導致過度抑制 |
| **非穩態爆裂噪音 (Crackle/Glitch)** | 麥克風碰觸、衣物摩擦、線材拉扯 | 短時寬頻能量爆發，SPP 可能誤判為語音 → 保留噪音；或誤判為噪音 → 後續過度抑制 |
| **有調性干擾 (Tonal)** | 單頻嗡嗡聲、電源 hum (50/60Hz)、警報聲 | 窄頻能量集中且持續，MCRA 可能誤判為語音；建議搭配 notch filter 前處理 |
| **音樂背景** | 音樂、節奏、樂器聲 | SPP 假設「語音 vs 穩態噪音」二元分類，音樂的 harmonic 結構會被當語音保留 |
| **與語音頻譜高度重疊的噪聲** | 其他人的語音（單一干擾說話者）、電視播放語音 | SPP 無法區分目標語音與干擾語音，兩者會同時被保留或同時被抑制 |
| **極低 SNR (< 0 dB)** | 噪聲能量遠大於語音 | 先驗 SNR 估計困難，增益可能過度抑制語音或抑噪不足 |
| **強迴響環境** | 大空間迴響、教堂、空曠走廊 | reverb tail 與穩態噪音特性相近，部分迴響會被當噪音抑制，導致語音變「乾」失真 |
| **風聲 / 湍流氣流 (Wind Buffeting)** | 戶外強風、汽車車窗縫隙漏風、麥克風無風罩直吹 | 風聲低頻 (<300 Hz) 能量與語音基頻/F1 高度重疊，單麥克風 + 統計特徵無法可靠區分。V4 wind handler 雖已實作但 VCTK/DEMAND 驗證未能改善，**建議硬體加裝風罩或使用雙麥克風 + 空間過濾** |

### 不適用場景 ❌

| 噪聲類型 | 說明 | 建議替代方案 |
|----------|------|-------------|
| **迴響 / 殘響 (Reverberation)** | 房間反射造成的語音模糊 | 需專用 dereverberation 演算法（如 WPE） |
| **回聲 (Echo)** | 喇叭到麥克風的聲學耦合 | 需 AEC（Acoustic Echo Cancellation，參考 `SE/AEC/`） |
| **多說話人分離** | 區分多個同時說話的人 | 需 speech separation（如 TasNet、DPRNN） |
| **音樂中的人聲分離** | 從音樂中提取或去除人聲 | 需 source separation（如 Demucs） |
| **強風直吹 / 麥克風湍流** | Buffeting noise，能量衝擊式非穩態 | 統計型單麥 NR 本質無法處理；需硬體風罩、雙麥 + 空間濾波或 NN-based 專用模型 |

---

## ⚠️ 演算法限制 (Limitations)

### 基本假設

1. **加性噪聲模型**：假設觀測訊號 y(t) = x(t) + n(t)，語音與噪聲統計獨立。不適用於卷積性噪聲（如殘響）。
2. **單聲道輸入**：僅處理單通道音訊，無法利用空間資訊進行波束成形。
3. **噪聲先於語音假設**：前 200ms（20 幀）必須為純噪聲或低語音活動，用於初始化噪聲底噪估計。若前段即為語音，噪聲估計會偏高，導致初期語音被過度抑制。
4. **Gaussian 語音先驗假設**：V1–V3-2 假設語音 DFT 係數服從 Gaussian 分佈（V3-3 使用 Laplacian），對爆破音等瞬態語音成分估計略有偏差。
5. **準穩態噪聲假設**：MCRA / IMCRA 用 minimum tracking 追噪聲底噪，假設噪聲在 320ms-1.6s 視窗內統計性質穩定。突發或快速變化的噪聲會超出追蹤能力。

### SPP + OMLSA 演算法限制

| 限制 | 機制 | 影響 |
|------|------|------|
| **MCRA noise PSD 收斂時間** | minimum tracking 視窗 L=32 (320ms@10ms hop) | 噪音突升後 0.3-0.6s 才能更新底噪估計；噪音降低後 0.5-1s 才完全收斂 |
| **SPP 二元假設** | $H_0$ (純噪聲) vs $H_1$ (語音+噪聲) | 對音樂、樂音、其他人語音等「類語音」訊號分類錯誤 |
| **OMLSA 對數域限制** | gain 在對數域平滑（保護 weak speech） | 強瞬態（爆音、敲擊）的 attack 邊緣可能被柔化 |
| **a priori SNR 估計（Decision-Directed）** | $\xi(k,n) = \alpha \cdot G^2 \xi_{prev} + (1-\alpha) \cdot \max(\gamma-1, 0)$ | 語音/噪音瞬間切換時有 1-2 幀延遲；產生 musical noise 風險 |
| **g_min 下限** | Balanced -15dB / Aggressive -20dB | 噪音無法完全消除，殘留底噪可聽到 |
| **頻譜缺口** | 過度抑制低能量 bin → 頻譜出現「洞」 | 低 SNR 下產生 musical noise 殘留 |
| **無 transient detector** | 沒有獨立的脈衝偵測 | 短脈衝（< 10ms）依靠 MCRA 慢追蹤，效果有限 |

### 處理限制

| 限制項目 | 說明 |
|----------|------|
| **固定取樣率** | 僅支持 8000 / 16000 / 48000 Hz，不支持 22050 / 44100 Hz 等非標準率 |
| **固定幀長** | 20ms frame / 10ms hop 不可動態調整（編譯時決定） |
| **最大抑制量** | 由 g_min 決定：Balanced 模式最多抑制 15 dB，Aggressive 最多 20 dB |
| **Musical Noise** | 已大幅改善（增益時間平滑 + LSA 對數域），但極低 SNR 下仍可能出現微弱殘留 |
| **語音失真** | 高抑噪強度下（Aggressive 模式, SNR < 5dB），語音會有可察覺的失真 |
| **場景切換延遲** | 噪聲環境突變時，需約 50ms（5 幀 × 10ms）偵測 + 320ms 完全收斂 |
| **頻率解析度** | 受限於 FFT size：16kHz 下為 31.25 Hz/bin (512-pt FFT)，無法精細處理窄頻干擾 |
| **不支援多通道** | 無 beamforming、spatial filtering 能力 |

---

## ✅ 使用條件 (Usage Requirements)

### 輸入訊號
- **單聲道**（若多聲道輸入則取第一聲道）
- **取樣率 8 / 16 / 48 kHz**；其他取樣率需先重採樣
- **PCM 16-bit 或 32-bit float**
- **前 200 ms 應為純噪聲**（無語音）— 用於初始化底噪估計。若錄音一開始即為語音，會造成初期過度抑制

### 呼叫模式
- **Streaming（C 實現, `c_impl/`）**：每次餵 1 hop (10 ms)，適合即時處理。首 200 ms 仍會輸出，但為 passthrough / 初始化階段
- **Batch（Python `MmseLsaDenoiser.denoise_spectrum()`）**：一次給完整頻譜；自動 reset，適合離線或 regression 測試

### 不適用情境（必看）
本演算法**無法**處理：
- **迴響 / 回聲** → 需 dereverb / AEC（專門模組，另見 `SE/AEC/`）
- **風聲 / buffeting** → 需硬體風罩或雙麥；V4 wind handler 為 research 框架，**不建議直接 release**
- **與目標語音重疊的干擾**（其他人的語音、電視背景人聲、音樂）→ SPP 無法區分類語音訊號
- **強衝擊 / transient**（敲擊、碰撞、關門）→ MCRA tracking window 320 ms 追不上

---

## 🔧 調參指引 (Quick Tuning for Release)

> **第一原則：先試 strength mode（MILD / BALANCED / AGGRESSIVE），大部分情境不需要動其它參數**

### 依 symptom 調參（四個關鍵旋鈕）

| Symptom | 推薦動作 | 效應 |
|---|---|---|
| 殘留底噪太吵 | `g_min_db` ↓（BALANCED −15 → AGGRESSIVE −20） | 更強抑制，可能略增語音失真 |
| 語音被抑制 / 變悶 | `g_min_db` ↑（BALANCED −15 → MILD −10） 或 `alpha_g` ↑ | 保留更多細節，底噪增多 |
| Musical noise / 水聲 | `alpha_g` ↑（0.88 → 0.92）、`xi_min_db` ↓（−20 → −25） | 增益更平滑，最小 SNR 更低 |
| 噪聲場景切換慢（進地鐵/上車） | `scene_change_threshold_db` ↓（10 → 7） | 更容易觸發 noise reset |
| 過度觸發 scene reset（語音被當成噪聲重估） | `scene_change_threshold_db` ↑（10 → 12） 或 `scene_change_min_frames` ↑（5 → 8） | 提高切換門檻 |
| 語音抓不到（被當噪聲） | `q` ↑（0.5 → 0.6）、`xi_min_db` ↑（−20 → −15） | SPP 更傾向判定為語音 |

### 不建議在 release 動的參數
- `alpha_xi`（DD 平滑）、`alpha_s` / `alpha_d` / `L`（MCRA）：改動對穩定性影響大，請先用 strength mode
- `num_init_frames`（固定 20 = 200 ms）：改短會讓底噪估計不穩
- `scene_change_flatness_threshold`（固定 0.4）：搭配 threshold_db 使用，一般不需單獨調整

### 當 symptom 無法用上述 table 解決
- 先確認是否為「不適用情境」（風聲、衝擊、迴響、類語音干擾）— 屬於本演算法**本質限制**，不是調參問題
- 若需更積極的風聲/衝擊抑制，請評估 NN-based 方案或多麥克風方案
- C 實作端的 log / dump：`make debug` 編譯，`bin/denoise_wav` 可觀察每幀 `noise_psd / spp / gain`，協助診斷
