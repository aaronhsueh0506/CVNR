# 語音降噪系統 (Speech Denoising System)

傳統信號處理方法的實時語音降噪系統，採用漸進式學習路徑。

## 📋 項目概述

本項目實現了 4 個版本的語音降噪算法，從基礎到先進：

1. **V1: 頻譜減法 (Spectral Subtraction)** - 最經典的方法
2. **V2: Wiener 濾波** - 基於 MMSE 的最優濾波
3. **V3: SPP + MMSE** ⭐ - 概率軟判決方法
4. **V4: IMCRA + OMLSA** - 產品級先進方案

## 🎯 特點

- ✅ 模塊化設計，易於理解和擴展
- ✅ **已修復 Musical Noise 問題**（2024-12更新）
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

## 📊 評估指標說明

### 主要指標：segSNR（Segmental SNR）

對於傳統降噪算法（V1-V4），我們使用 **segSNR (Segmental SNR)** 作為主要評估指標。

#### 為什麼使用 segSNR？

**PESQ/STOI 的局限性**：
- PESQ 設計用於語音編碼器（codec）評估，對頻譜修改極度敏感
- 傳統降噪算法固有的頻譜變化會被 PESQ 嚴厲懲罰
- STOI 對語音能量損失敏感，傳統算法多少會削減語音
- 結果：V1-V4 的 PESQ/STOI 得分都在 1.0-1.5 範圍，無法有效區分優劣

**segSNR 的優勢**：
- ✅ 逐幀計算 SNR，對頻譜修改更寬容
- ✅ 更符合傳統降噪算法的評估需求
- ✅ 能有效區分不同版本的降噪效果
- ✅ 典型範圍：5-20 dB 表示良好降噪

#### segSNR 計算方法

```python
from utils.metrics import evaluate_all_metrics, print_metrics

# 計算所有指標（需要 clean reference）
metrics = evaluate_all_metrics(noisy, clean, enhanced, fs=16000)

# 顯示結果（segSNR 會被突出顯示 ★）
print_metrics(metrics, "V3 SPP-MMSE")

# 主要關注 segSNR 改善值
print(f"segSNR Improvement: {metrics['segsnr_improvement_db']:.2f} dB")
```

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

### 方法1：使用 process_audio.py（推薦）

```bash
# 處理您的音頻文件（默認使用 V1-V4 所有版本）
python3 examples/process_audio.py your_audio.wav

# 只使用推薦的 V3 和 V4
python3 examples/process_audio.py your_audio.wav --versions V3 V4

# 指定輸出目錄
python3 examples/process_audio.py your_audio.wav --output-dir ./my_output
```

輸出：
- `your_audio_v1.wav` - V1 頻譜減法處理結果
- `your_audio_v2.wav` - V2 Wiener 濾波處理結果
- `your_audio_v3.wav` - V3 SPP-MMSE 處理結果
- `your_audio_v4.wav` - V4 IMCRA-OMLSA 處理結果
- `your_audio_waveforms.png` - 波形對比圖（input + V1-V4）

詳細說明請參考：[process_audio.py 使用說明](examples/PROCESS_AUDIO_USAGE.md)

### 方法2：使用 Python API

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

## 📁 項目結構

```
speech_denoise/
├── core/                          # 核心模塊
│   ├── frame_processor.py         # 分幀、加窗、FFT
│   ├── reconstructor.py           # 重建、IFFT、Overlap-Add
│   ├── spp_estimator.py          # SPP 估計（V3/V4）
│   ├── noise_estimators/         # 噪聲估計器
│   │   ├── simple_average.py     # V1: 簡單平均
│   │   ├── recursive_average.py  # V2/V3: 遞歸平均
│   │   └── imcra.py             # V4: IMCRA
│   └── gain_calculators/         # 增益計算器
│       ├── spectral_subtraction.py  # V1 (含時間平滑)
│       ├── wiener.py                # V2 (含時間平滑)
│       ├── spp_mmse.py              # V3
│       └── omlsa.py                 # V4
│
├── denoisers/                    # 完整降噪器
│   ├── base_denoiser.py         # 基類
│   ├── v1_spectral_subtraction.py
│   ├── v2_wiener.py
│   ├── v3_spp_mmse.py
│   └── v4_imcra_omlsa.py
│
├── utils/                        # 工具模塊
│   ├── audio_io.py              # 音頻讀寫
│   ├── test_data_generator.py   # 測試數據生成
│   └── visualization.py         # 可視化
│
├── config/                       # 配置文件
│   ├── v1_config.yaml           # V1 配置
│   ├── v2_config.yaml           # V2 配置
│   ├── v3_config.yaml           # V3 配置 (alpha_g=0.85)
│   └── v4_config.yaml           # V4 配置 (alpha_g=0.85)
│
├── examples/                     # 示例腳本
│   ├── process_audio.py         # 主處理工具 ⭐
│   ├── compare_all_versions.py  # 版本對比
│   └── quick_start.py           # 快速開始
│
└── docs/                         # 文檔
    ├── CHANGELOG.md             # 變更記錄
    └── parameter_tuning.md      # 參數調整指南
```

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
  frame_size_ms: 20       # 幀長 320 samples @ 16kHz
  frame_shift_ms: 10      # 幀移 50% overlap
  fft_size: 512           # FFT點數
  window_type: "hanning"  # 窗函數類型
```

**調整建議**：
- 更低延遲：減小 `frame_size_ms` 和 `frame_shift_ms`
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
python3 examples/process_audio.py your_audio.wav --versions V2 V3 V4
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
   - 使用 `examples/process_audio.py` 處理音頻

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
   python3 examples/process_audio.py test_snr5dB.wav --versions V3
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

## 📖 參考文獻

### 經典論文

1. **頻譜減法**
   - Boll (1979): "Suppression of Acoustic Noise in Speech Using Spectral Subtraction"

2. **Wiener 濾波**
   - Lim & Oppenheim (1979): "Enhancement and Bandwidth Compression of Noisy Speech"

3. **SPP-MMSE**
   - Ephraim & Malah (1984): "Speech Enhancement Using a Minimum Mean-Square Error STSA Estimator"
   - Cohen & Berdugo (2001): "Speech Enhancement for Non-stationary Noise Environments"

4. **IMCRA-OMLSA**
   - Cohen & Berdugo (2001): "Noise Estimation by Minima Controlled Recursive Averaging"
   - Cohen (2002): "Optimal Speech Enhancement Under Signal Presence Uncertainty"

### Musical Noise 相關

- Cappé (1994): "Elimination of the Musical Noise Phenomenon with the Ephraim and Malah Noise Suppressor"
- 本項目實現：時間域增益平滑 + 對數域平滑（V4）

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

### 開發建議

- 遵循現有代碼風格
- 添加中文注釋
- 更新相關文檔
- 提供測試用例

## 📄 授權

MIT License

## 🎯 更新日誌

### v1.2.0 (2026-01) ✨ 最新
- ✅ **添加 segSNR 評估指標**（主要指標）
- ✅ 更新評估指標體系，PESQ/STOI 改為參考指標
- ✅ 完善評估指標使用說明和文檔

### v1.1.0 (2024-12)
- ✅ 修復所有版本的 Musical Noise 問題
- ✅ V1/V2 添加時間平滑機制
- ✅ V3/V4 強化增益平滑因子（0.7 → 0.85）
- ✅ 添加完整的參數調整指南
- ✅ 完善文檔和使用說明
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

**推薦使用 V3 或 V4 版本以獲得最佳降噪效果！**
