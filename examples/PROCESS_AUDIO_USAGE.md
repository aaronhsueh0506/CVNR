# process_audio.py 使用說明

## 功能介紹

`process_audio.py` 是一個音頻降噪處理工具，可以將您的真實音頻文件使用 V1-V4 四個降噪算法處理，生成四個不同版本的降噪結果。

## 安裝依賴

```bash
# 必需依賴
pip install numpy pyyaml

# 音頻處理（選擇其一）
pip install soundfile    # 推薦
# 或
pip install scipy
```

## 基本用法

### 1. 最簡單的用法

```bash
python process_audio.py your_noisy_audio.wav
```

這將：
- 讀取 `your_noisy_audio.wav`
- 使用 V1-V4 四個版本處理
- 輸出到 `./denoised/` 目錄：
  - `your_noisy_audio_v1.wav`
  - `your_noisy_audio_v2.wav`
  - `your_noisy_audio_v3.wav`
  - `your_noisy_audio_v4.wav`

### 2. 指定輸出目錄

```bash
python process_audio.py input.wav --output-dir ./my_output
```

### 3. 只使用特定版本

```bash
# 只使用 V3 和 V4（推薦版本）
python process_audio.py input.wav --versions V3 V4

# 只使用 V4（最佳質量）
python process_audio.py input.wav --versions V4
```

### 4. 使用自定義配置文件

```bash
python process_audio.py input.wav --config-dir ./my_configs
```

## 參數說明

### V1-V4 各版本特點

| 版本 | 名稱 | 特點 | 適用場景 |
|------|------|------|---------|
| V1 | 頻譜減法 | 最快，但有音樂噪聲 | 快速測試 |
| V2 | Wiener 濾波 | 平衡效果和速度 | 一般應用 |
| V3 | MMSE-STSA | 效果好，音樂噪聲少 | 推薦使用 |
| V4 | IMCRA-OMLSA | 最佳效果，產品級 | 高質量需求 |

### 配置文件

默認從 `config/` 目錄讀取配置：
- `v1_config.yaml` - V1 參數配置
- `v2_config.yaml` - V2 參數配置
- `v3_config.yaml` - V3 參數配置
- `v4_config.yaml` - V4 參數配置

您可以修改這些文件來調整降噪參數。

## 輸入要求

- **格式**：WAV（16位 PCM）
- **採樣率**：任意（推薦 16kHz）
- **聲道**：單聲道或立體聲（自動轉單聲道）

## 輸出格式

- **格式**：WAV（16位 PCM）
- **採樣率**：與輸入相同
- **聲道**：單聲道
- **命名**：`原文件名_版本號.wav`

## 完整示例

```bash
# 1. 準備您的音頻文件
# 假設有一個含噪音頻：recording.wav

# 2. 運行降噪（使用推薦的 V3 和 V4）
python process_audio.py recording.wav --versions V3 V4 --output-dir ./cleaned

# 3. 查看結果
ls -lh ./cleaned/
# 輸出：
# recording_v3.wav
# recording_v4.wav

# 4. 比較效果，選擇最佳版本
```

## 性能參考

處理 2 秒音頻（16kHz）的典型時間：
- V1: ~10 ms (RTF: 0.005)
- V2: ~8 ms (RTF: 0.004)
- V3: ~12 ms (RTF: 0.006)
- V4: ~16 ms (RTF: 0.008)

所有版本都能實時處理（RTF < 1.0）。

## 常見問題

### Q: 支持哪些音頻格式？
A: 目前只支持 WAV 格式。可以使用 ffmpeg 轉換：
```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 output.wav
```

### Q: 如何調整降噪強度？
A: 修改對應版本的配置文件（`config/v*_config.yaml`）。詳見下方「參數調整指南」。

### Q: 輸出質量不好怎麼辦？
A:
1. 嘗試不同版本（推薦 V3 或 V4）
2. 調整配置文件參數（見下方詳細說明）
3. 確保輸入音頻質量（採樣率、位深度）
4. 檢查噪聲類型（穩態噪聲效果更好）

### Q: 有 Musical Noise（震動聲、金屬音）怎麼辦？
A: v1.1.0 已修復此問題。如果仍有問題：
- V1/V2: 提高 `alpha_smooth`（0.8 → 0.85 或 0.9）
- V3/V4: 提高 `alpha_g`（0.85 → 0.9）

### Q: 可以批量處理多個文件嗎？
A: 目前一次只能處理一個文件，但可以使用 shell 腳本：
```bash
for file in *.wav; do
    python process_audio.py "$file" --versions V3 V4
done
```

## 性能優化建議

1. **如果只需要最佳質量**：只使用 V4
   ```bash
   python process_audio.py input.wav --versions V4
   ```

2. **如果需要快速處理**：只使用 V2
   ```bash
   python process_audio.py input.wav --versions V2
   ```

3. **如果要對比效果**：使用 V3 和 V4
   ```bash
   python process_audio.py input.wav --versions V3 V4
   ```

## 故障排除

### 錯誤：音頻庫不可用

```
RuntimeError: No audio I/O library available
```

**解決方法：**
```bash
pip install soundfile
# 或
pip install scipy
```

### 錯誤：配置文件未找到

```
Warning: Config file not found: config/v1_config.yaml
```

**解決方法：**
確保在項目根目錄運行，或使用 `--config-dir` 指定正確路徑。

### 錯誤：內存不足

處理長時間音頻時可能出現內存問題。

**解決方法：**
1. 將音頻分段處理
2. 降低採樣率到 8kHz 或 16kHz

---

## 參數調整指南

### V1 頻譜減法參數（config/v1_config.yaml）

#### 核心參數

**alpha (過減因子)**
- 範圍：1.5 - 2.5
- 默認：2.0
- 作用：控制降噪強度
- 調整建議：
  - 噪聲太多：增大到 2.2 - 2.5
  - 語音失真：減小到 1.5 - 1.8

**beta (頻譜下限)**
- 範圍：0.002 - 0.02
- 默認：0.01
- 作用：防止過度抑制
- 調整建議：
  - 殘留噪聲太多：減小到 0.005
  - 語音太模糊：增大到 0.015 - 0.02

**alpha_smooth (時間平滑因子)** 🆕
- 範圍：0.0 - 1.0
- 默認：0.8
- 作用：減少 Musical Noise
- 調整建議：
  - 有震動聲：增大到 0.85 - 0.9
  - 語音起始模糊：減小到 0.75

#### 場景配置示例

**街道噪聲（穩態高頻）**
```yaml
alpha: 2.2
beta: 0.008
alpha_smooth: 0.8
```

**辦公室噪聲（低頻穩態）**
```yaml
alpha: 2.0
beta: 0.01
alpha_smooth: 0.8
```

---

### V2 Wiener 濾波參數（config/v2_config.yaml）

#### 核心參數

**min_gain (最小增益)**
- 範圍：0.01 - 0.2
- 默認：0.1
- 作用：噪聲抑制下限
- 調整建議：
  - 降噪不夠：減小到 0.05
  - 語音失真：增大到 0.15

**alpha_smooth (時間平滑因子)** 🆕
- 範圍：0.0 - 1.0
- 默認：0.8
- 作用：減少 Musical Noise
- 調整建議：
  - 有震動聲：增大到 0.85 - 0.9
  - 語音起始模糊：減小到 0.75

**alpha (噪聲更新速率)**
- 範圍：0.85 - 0.98
- 默認：0.95
- 作用：噪聲估計適應速度
- 調整建議：
  - 噪聲變化快：減小到 0.90
  - 噪聲穩定：保持 0.95

#### 場景配置示例

**汽車噪聲（非穩態低頻）**
```yaml
min_gain: 0.08
alpha_smooth: 0.85
alpha: 0.92  # 更快適應
```

**會議室噪聲（穩態）**
```yaml
min_gain: 0.1
alpha_smooth: 0.8
alpha: 0.95
```

---

### V3 SPP-MMSE 參數（config/v3_config.yaml）

#### 核心參數

**g_min_db (最小增益 dB)**
- 範圍：-25 到 -15 dB
- 默認：-20 dB
- 作用：最大抑制強度
- 調整建議：
  - 降噪不夠：降低到 -25 dB
  - 語音失真：提高到 -18 或 -15 dB

**alpha_g (增益平滑因子)** 🆕
- 範圍：0.7 - 0.95
- 默認：0.85（v1.1.0 提高）
- 作用：增益時間平滑
- 調整建議：
  - 有 Musical Noise：增大到 0.9
  - 需要快速響應：減小到 0.8

**alpha_xi (先驗 SNR 平滑因子)**
- 範圍：0.92 - 0.98
- 默認：0.98
- 作用：SNR 估計平滑度
- 建議：不要修改（除非非常了解算法）

#### 場景配置示例

**多人說話噪聲（Babble）**
```yaml
g_min_db: -22.0
alpha_g: 0.85
alpha_xi: 0.98
```

**白噪聲**
```yaml
g_min_db: -20.0
alpha_g: 0.85
alpha_xi: 0.98
```

---

### V4 IMCRA-OMLSA 參數（config/v4_config.yaml）⭐ 產品級

#### 核心參數

**g_min_db (最小增益 dB)**
- 範圍：-25 到 -15 dB
- 默認：-20 dB
- 作用：最大抑制強度
- 調整建議：同 V3

**alpha_g (增益平滑因子)** 🆕
- 範圍：0.7 - 0.95
- 默認：0.85（v1.1.0 提高）
- 作用：對數域增益平滑
- 調整建議：
  - 有 Musical Noise：增大到 0.9
  - 需要快速響應：減小到 0.8

**IMCRA 噪聲估計參數**

**alpha_s (頻譜平滑因子)**
- 範圍：0.85 - 0.95
- 默認：0.9
- 作用：頻譜平滑程度
- 調整建議：
  - 噪聲變化快：減小到 0.85
  - 需要更平滑：增大到 0.95

**alpha_d (噪聲更新速率)**
- 範圍：0.80 - 0.90
- 默認：0.85
- 作用：噪聲追蹤速度
- 調整建議：
  - 噪聲變化快：減小到 0.80
  - 穩態噪聲：增大到 0.90

**L (最小值追蹤窗口長度)**
- 範圍：100 - 200 幀
- 默認：150 幀（約 1.5 秒）
- 作用：追蹤窗口大小
- 調整建議：
  - 實時性要求高：減小到 100
  - 質量要求高：增大到 200

#### 場景配置示例

**穩態噪聲（辦公室、空調）**
```yaml
g_min_db: -20.0
alpha_g: 0.85
alpha_s: 0.92
alpha_d: 0.88  # 更保守
L: 150
```

**非穩態噪聲（街道、汽車）**
```yaml
g_min_db: -22.0
alpha_g: 0.85
alpha_s: 0.88
alpha_d: 0.82  # 更快適應
L: 120
```

**高質量需求**
```yaml
g_min_db: -20.0
alpha_g: 0.9   # 更平滑
alpha_s: 0.92
alpha_d: 0.85
L: 180
```

---

## 調參優先級建議

### 入門級（快速調整）

只調整這 2 個參數：
1. **降噪強度**：
   - V1/V2: `alpha` 或 `min_gain`
   - V3/V4: `g_min_db`
2. **Musical Noise 控制**：
   - V1/V2: `alpha_smooth`
   - V3/V4: `alpha_g`

### 中級（場景優化）

根據噪聲類型調整：
1. 降噪強度參數（同上）
2. 平滑參數（同上）
3. **噪聲適應速度**：
   - V2: `alpha`
   - V4: `alpha_d`

### 高級（完全控制）

可調整所有參數，但需要：
1. 理解每個參數的數學意義
2. 多次測試驗證
3. 注意參數之間的相互影響

---

## 常見問題的調參方案

### 問題 1: 降噪不夠強

**快速方案**：
- V1: `alpha: 2.0 → 2.5`, `beta: 0.01 → 0.005`
- V2: `min_gain: 0.1 → 0.05`
- V3/V4: `g_min_db: -20 → -25`

### 問題 2: 語音失真、模糊

**快速方案**：
- V1: `alpha: 2.0 → 1.5`, `beta: 0.01 → 0.02`
- V2: `min_gain: 0.1 → 0.15`
- V3/V4: `g_min_db: -20 → -15`

### 問題 3: Musical Noise（震動聲）

**快速方案**（v1.1.0 已優化）：
- V1/V2: `alpha_smooth: 0.8 → 0.9`
- V3/V4: `alpha_g: 0.85 → 0.9`

### 問題 4: 語音起始被截斷

**快速方案**：
- V1/V2: `alpha_smooth: 0.8 → 0.75`
- V3/V4: `alpha_g: 0.85 → 0.8`
- V3: `alpha_xi: 0.98 → 0.95`

### 問題 5: 適應慢（噪聲變化時）

**快速方案**：
- V2: `alpha: 0.95 → 0.90`
- V4: `alpha_d: 0.85 → 0.80`, `L: 150 → 100`

---

## 更新日誌

### v1.1.0 (2024-12-30)
- ✅ 修復 Musical Noise 問題
  - V1/V2: 添加 `alpha_smooth=0.8` 時間平滑
  - V3/V4: 提高 `alpha_g` 從 0.7 到 0.85
- ✅ 添加完整的參數調整指南
- ✅ 添加場景配置示例
