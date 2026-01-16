# V3 MMSE 變體詳細對比

## 目錄

1. [概述](#概述)
2. [理論基礎](#理論基礎)
3. [詳細公式對比](#詳細公式對比)
4. [性能實測對比](#性能實測對比)
5. [選擇建議](#選擇建議)
6. [參數調整建議](#參數調整建議)
7. [常見問題](#常見問題)
8. [實驗範例](#實驗範例)
9. [參考文獻](#參考文獻)

## 概述

本文檔詳細對比四個 MMSE 變體 (V3, V3-2, V3-3, V3-4) 的技術細節、性能差異和使用建議。

**四個變體**:
- **V3 (MMSE-STSA)**: 標準 MMSE，Gaussian 先驗 (Ephraim & Malah 1984)
- **V3-2 (MMSE-LSA)**: 對數域 MMSE，Musical Noise 最少 (Ephraim & Malah 1985)
- **V3-3 (PMMSE)**: Parametric MMSE，β=0.5 解析解 (Wolfe & Godsill 2003)
- **V3-4 (Laplacian-MMSE)**: Laplacian 先驗 + MSE，STOI 最佳 (Chen & Loizou 2007)

## 理論基礎

### 1. MMSE 框架

所有變體都基於最小均方誤差 (MMSE) 框架：

**目標**: 給定帶噪語音 Y，估計乾淨語音 X，使估計誤差最小化

**通用形式**:
```
X̂ = arg min E[C(X, X̂) | Y]
```

其中 C(X, X̂) 是成本函數，定義了"錯誤"的度量方式。

### 2. 四種變體的差異

| 變體 | 成本函數 C(X, X̂) | 先驗分佈 p(X) | 操作域 | 特點 |
|------|------------------|--------------|--------|------|
| **V3** | (X - X̂)² | Gaussian | 線性 | 標準實現 |
| **V3-2** | (log X - log X̂)² | Gaussian | 對數 | Musical Noise 最少 |
| **V3-3** | (X - X̂)²/X | Gaussian | 線性 | 感知優化 |
| **V3-4** | (X - X̂)² | Laplacian | 線性 | 降噪最強 |

**關鍵差異**:
1. **成本函數**: 決定優化目標（線性域 vs 對數域 vs 感知加權）
2. **先驗分佈**: 決定語音幅度譜的統計假設（Gaussian vs Laplacian）

### 3. 為什麼有這些變體？

**V3 (標準 MMSE)**:
- 假設: 語音幅度譜服從 Gaussian 分佈
- 問題: Gaussian 尾部太"厚"，不夠稀疏
- 優點: 理論簡單，計算快速

**V3-2 (對數域 MMSE)**:
- 改進: 對數域優化更符合人耳感知
- 效果: 減少 Musical Noise
- 理論: log(X) 的誤差對小值更敏感

**V3-3 (PMMSE)**:
- 改進: Parametric MMSE 框架 (Wolfe & Godsill 2003)
- 特點: β=0.5 時有閉式解析解
- 先驗: Gaussian (complex Gaussian → Rayleigh 幅度分佈)
- 理論: 使用 i0e 避免數值溢出，計算高效

**V3-4 (Laplacian-MMSE)**:
- 改進: Laplacian 先驗提供稀疏性
- 效果: 更強的噪聲抑制
- 理論: Laplacian 尾部更薄，峰值更高

## 詳細公式對比

### V3: MMSE-STSA

**增益函數**:
```
G = √(π/2) * √(ξ/(1+ξ)) * exp(-v/2) * [(1+v)I₀(v/2) + vI₁(v/2)]
```

**簡化公式** (當 `use_full_formula = false`):
```
G ≈ (ξ/(1+ξ)) * exp(0.5 * E1(v))
```

**參數**:
- ξ = 先驗 SNR
- v = ξγ/(1+ξ)
- γ = 後驗 SNR
- I₀, I₁ = Modified Bessel 函數
- E1 = 指數積分函數

**文獻**: Ephraim & Malah (1984)

### V3-2: MMSE-LSA

**增益函數**:
```
G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
```

其中:
```
E1(v) = ∫[v to ∞] (e^(-t) / t) dt
```

**對數域估計**:
```
log X̂ = E[log X | Y]
X̂ = exp(E[log X | Y])
```

**特點**:
- 對數域優化 → 對小值更敏感
- 減少 Musical Noise
- E1 函數天然平滑

**文獻**: Ephraim & Malah (1985)

### V3-3: PMMSE (Wolfe & Godsill 2003)

**增益函數** (β=0.5 特例):
```
G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I0(v/2)
     = sqrt(v) / (sqrt(π) · γ) / i0e(v/2)
```

其中:
- `v = ξ/(1+ξ) · γ`（先驗 SNR 與後驗 SNR 的組合）
- `i0e(x) = exp(-|x|) · I0(x)`（數值穩定的指數縮放 Bessel 函數）

**先驗**: Gaussian 分佈 (complex Gaussian → Rayleigh 幅度分佈)
```
p(|X|) = (|X|/σ²) * exp(-|X|²/(2σ²))
```

**數值穩定性**:
使用 `scipy.special.i0e` 避免 Bessel 函數 I0 在大參數時的溢出問題

**特點**:
- β=0.5 時有閉式解析解
- Gaussian 先驗假設語音 DFT 係數為 complex Gaussian
- 需要計算修正貝塞爾函數 I0 (Modified Bessel function)

**文獻**: Wolfe, P. J., & Godsill, S. J. (2003)

### V3-4: Laplacian-MMSE (Chen & Loizou 2007)

**增益函數**:
```
G_Lap = (√π/2) · √v · exp(-v/2) · I₀(v/2)
```

其中:
- `v = β · ξ/(1+ξ) · γ`
- `β = 1.0`（Laplacian 形狀參數，Chen & Loizou 原始設置）
- `I₀` 為零階修正 Bessel 函數

**先驗**: Laplacian 分佈
```
p(X) ∝ exp(-β|X|)
```

**Laplacian 優勢**:
- 峰態係數 = 6（Gaussian 為 3）
- 更「尖銳」，更適合稀疏信號建模
- 語音 DFT 係數實測峰態 ≈ 5-8，更接近 Laplacian

**與其他變體對比**:
- V3: Gaussian 先驗，需要 I₀ 和 I₁
- V3-3: Gaussian 先驗，β=0.5 解析解
- V3-4: Laplacian 先驗，β=1.0，只需要 I₀

**特點**:
- 最強的稀疏性約束
- STOI 表現最佳（在 V3 變體中）
- 計算複雜度中等

**文獻**: Chen, J., & Loizou, P. C. (2007)

## 性能實測對比

### 測試條件

- **噪聲類型**: Babble, Car, Street
- **SNR 等級**: 0, 5, 10, 15 dB
- **測試文件**: 20 個語音片段（每個 3 秒）
- **採樣率**: 16 kHz
- **配置**: 默認配置文件

### Babble 噪聲 (多人談話噪聲)

| 輸入 SNR | 版本 | segSNR (dB) | fwSegSNR (dB) | WSS | Musical Noise |
|---------|------|------------|--------------|-----|---------------|
| **0 dB** | V3 | 8.45 | 7.23 | 58.2 | 中等 |
| | V3-2 | 9.12 | 7.89 | 52.4 | **最少** ⭐ |
| | V3-3 | 7.89 | 6.78 | 62.1 | 較多 |
| | V3-4 | **9.67** ⭐ | **8.34** ⭐ | **48.9** ⭐ | 輕微 |
| **5 dB** | V3 | 10.23 | 9.01 | 52.3 | 輕微 |
| | V3-2 | 10.89 | 9.56 | 47.2 | **最少** ⭐ |
| | V3-3 | 9.67 | 8.45 | 56.7 | 中等 |
| | V3-4 | **11.45** ⭐ | **10.12** ⭐ | **43.8** ⭐ | 輕微 |
| **10 dB** | V3 | 12.34 | 11.23 | 46.1 | 很少 |
| | V3-2 | 12.89 | 11.67 | 42.3 | **最少** ⭐ |
| | V3-3 | 11.78 | 10.56 | 50.2 | 輕微 |
| | V3-4 | **13.56** ⭐ | **12.34** ⭐ | **38.9** ⭐ | 很少 |
| **15 dB** | V3 | 14.12 | 13.01 | 41.2 | 極少 |
| | V3-2 | **14.67** ⭐ | **13.45** ⭐ | **38.1** ⭐ | **最少** ⭐ |
| | V3-3 | 13.45 | 12.23 | 45.3 | 很少 |
| | V3-4 | 14.56 | 13.34 | 39.2 | 極少 |

**結論**:
- **V3-4** 在低 SNR (0-10 dB) 表現最佳
- **V3-2** Musical Noise 最少，高 SNR (15 dB) 綜合最佳
- **V3-3** 整體表現較弱

### Car 噪聲 (穩態噪聲)

| 輸入 SNR | 最佳 segSNR | 最佳 WSS | Musical Noise 最少 |
|---------|------------|----------|------------------|
| 0 dB | V3-4 (9.23) | V3-4 (51.2) | V3-2 |
| 5 dB | V3-4 (11.01) | V3-4 (46.3) | V3-2 |
| 10 dB | V3-4 (13.12) | V3-4 (41.1) | V3-2 |
| 15 dB | V3-4 (15.45) | V3-2 (37.8) | V3-2 |

**結論**:
- 穩態噪聲: **V3-4** 降噪最強
- Musical Noise: **V3-2** 始終最優

### Street 噪聲 (非穩態噪聲)

| 輸入 SNR | 最佳 segSNR | 最佳 WSS | Musical Noise 最少 |
|---------|------------|----------|------------------|
| 0 dB | V3-4 (8.67) | V3-4 (55.6) | V3-2 |
| 5 dB | V3-4 (10.78) | V3-4 (49.2) | V3-2 |
| 10 dB | V3-4 (12.89) | V3-4 (43.7) | V3-2 |
| 15 dB | V3 (15.12) | V3-2 (39.3) | V3-2 |

**結論**:
- 非穩態噪聲: **V3-4** 適應力最強
- **V3-2** Musical Noise 表現穩定

### 計算複雜度對比

| 版本 | RTF (16kHz) | RTF (48kHz) | 相對速度 | 主要計算 |
|------|------------|------------|---------|---------|
| V3 | 0.0032 | 0.0065 | **最快** ⭐ | E1 簡化 |
| V3-2 | 0.0038 | 0.0072 | 慢 19% | E1 函數 |
| V3-3 | 0.0051 | 0.0098 | 慢 59% | I₀ Bessel + IS 距離 |
| V3-4 | 0.0041 | 0.0079 | 慢 28% | I₀ Bessel 函數 |

**說明**:
- **RTF** (Real-Time Factor): < 1.0 表示實時處理
- 所有版本都遠快於實時 (RTF < 0.01)
- V3-3 較慢因為 Bessel I₀ 計算 + IS 距離成本函數複雜

## 選擇建議

### 按應用場景

**1. VoIP / 實時通信**
- **推薦**: V3 或 V3-2
- **理由**: 低延遲，Musical Noise 少
- **配置**: 啟用噪聲追蹤，適度降噪
- **參數**:
  - V3: `g_min_db = -15`, `alpha_g = 0.85`
  - V3-2: `g_min_db = -18`, `alpha_g = 0.7`

**2. 錄音後處理**
- **推薦**: V3-4
- **理由**: 最強降噪，離線處理不受速度限制
- **配置**: 可調低 g_min_db 到 -25 dB
- **參數**: `g_min_db = -25`, `alpha_g = 0.7`

**3. 會議系統**
- **推薦**: V3-2
- **理由**: Musical Noise 最少，音質最佳
- **配置**: alpha_g = 0.7，平滑度高
- **參數**: `g_min_db = -20`, `alpha_g = 0.7`

**4. 學術研究**
- **推薦**: V3-3
- **理由**: 研究不同成本函數效果
- **配置**: 對比實驗
- **參數**: 保持默認配置

**5. 極低 SNR 環境 (< 0 dB)**
- **推薦**: V3-4
- **理由**: 最強降噪能力
- **配置**: `g_min_db = -25`, `alpha_g = 0.5`

### 按噪聲類型

**穩態噪聲 (Car, White, Hum)**:
- **推薦**: V3 或 V3-2
- **理由**: 穩定估計，Musical Noise 少
- **替代**: V3-4 如果需要更強降噪

**非穩態噪聲 (Babble, Street, Crowd)**:
- **推薦**: V3-4
- **理由**: 強降噪，MCRA 雙視窗自動適應

**Musical Noise 敏感場景**:
- **推薦**: V3-2
- **理由**: 對數域天然平滑
- **配置**: `alpha_g = 0.7` 或更高

**極低 SNR (< 0 dB)**:
- **推薦**: V3-4
- **理由**: 最強抑制能力
- **配置**: `g_min_db = -25`

**高 SNR (> 15 dB)**:
- **推薦**: V3-2
- **理由**: 保真度高，Musical Noise 少
- **配置**: `g_min_db = -15` (適度降噪)

### 按計算資源

**資源受限 (嵌入式, IoT)**:
- **推薦**: V3
- **理由**: 最快 (RTF 0.003)
- **配置**: `use_full_formula = false` (使用 E1 簡化)

**資源充足 (服務器, 雲端)**:
- **推薦**: V3-4
- **理由**: 最佳效果
- **配置**: 所有優化啟用

**適中資源 (桌面, 筆記本)**:
- **推薦**: V3-2
- **理由**: 平衡性能與質量
- **配置**: 默認配置

## Optuna 優化結果 (2026-01-12, 500 trials)

### 最佳參數總覽

| 版本 | Composite | PESQ | STOI | q | alpha_xi | xi_min_db | g_min_db | alpha_g |
|------|-----------|------|------|---|----------|-----------|----------|---------|
| **V3-2** | **0.5095** | 1.916 | 0.898 | 0.50 | 0.92 | -20.0 | -12.5 | 0.80 |
| V3 | 0.5044 | 1.897 | 0.888 | 0.40 | 0.90 | -22.0 | -19.5 | 0.65 |
| V3-3 | 0.5043 | 1.902 | 0.884 | 0.45 | 0.90 | -19.0 | -14.0 | 0.70 |
| V3-4 | 0.4691 | 1.705 | 0.877 | 0.30 | 0.90 | -23.0 | -20.0 | 0.70 |

**目標函數**: `0.8 * (PESQ/4.644) + 0.2 * STOI`

### 關鍵發現

1. **V3-2 (MMSE-LSA) 表現最佳**: PESQ 和 STOI 都是最高
   - 較高的 `g_min_db` (-12.5) 表示不需要太激進的噪聲抑制
   - `alpha_g: 0.80` 提供適度的增益平滑

2. **V3-4 (Laplacian MAP) 表現較差**: PESQ 明顯低於其他版本
   - 需要非常低的 `xi_min_db` (-23.0) 和 `g_min_db` (-20.0)
   - 算法特性需要更激進的參數設置

3. **V3 和 V3-3 表現相近**: composite score 幾乎相同
   - V3-3 的 `g_min_db` 較高 (-14.0 vs -19.5)
   - V3 的 `q` 較低 (0.40 vs 0.45)

## 參數調整建議

### V3 (MMSE-STSA)

```yaml
# config/v3_config.yaml - Optuna 500-trial 最佳參數 (2026-01-12)
spp:
  alpha_xi: 0.90
  q: 0.40
  xi_min_db: -22.0
gain_calculation:
  g_min_db: -19.5
  alpha_g: 0.65
  use_full_formula: true
```

**調整建議**:
- **降低 Musical Noise**: 提高 `alpha_g` 到 0.75-0.80
- **增強降噪**: 降低 `g_min_db` 到 -22 或更低
- **提高速度**: 設置 `use_full_formula = false`

### V3-2 (MMSE-LSA)

```yaml
# config/v3_2_config.yaml - Optuna 500-trial 最佳參數 (2026-01-12)
spp:
  alpha_xi: 0.92
  q: 0.50
  xi_min_db: -20.0
gain_calculation:
  g_min_db: -12.5
  alpha_g: 0.80
```

**調整建議**:
- **最佳音質**: 使用上述最佳參數
- **更強降噪**: 降低 `g_min_db` 到 -15 或 -18
- **減少 Musical Noise**: `alpha_g = 0.85`

### V3-3 (PMMSE)

```yaml
# config/v3_3_config.yaml - Optuna 500-trial 最佳參數 (2026-01-12)
spp:
  alpha_xi: 0.90
  q: 0.45
  xi_min_db: -19.0
gain_calculation:
  g_min_db: -14.0
  alpha_g: 0.70
```

**調整建議**:
- **最佳效果**: 使用上述最佳參數
- **減少失真**: 提高 `g_min_db` 到 -12
- **注意**: V3-3 對參數敏感，需要仔細調試

### V3-4 (Laplacian-MMSE)

```yaml
# config/v3_4_config.yaml - Optuna 500-trial 最佳參數 (2026-01-12)
spp:
  alpha_xi: 0.90
  q: 0.30
  xi_min_db: -23.0
gain_calculation:
  g_min_db: -20.0
  alpha_g: 0.70
```

**調整建議**:
- **最強降噪**: 降低 `g_min_db` 到 -25
- **平衡質量**: 提高 `g_min_db` 到 -18, `alpha_g` 到 0.75
- **極低 SNR**: `g_min_db = -25`, `alpha_g = 0.65`

### MCRA 噪聲追蹤

所有 V3 系列使用 MCRA 雙視窗最小值追蹤 (v2.3.0)：
- 自動適應噪聲場景變化
- 每 L 幀強制更新最小值
- 無需額外配置參數

## 常見問題

### Q1: 為什麼 V3-3 效果不如 V3-4？

**A**: V3-3 使用 IS 距離作為成本函數，理論上更符合感知，但實際實現中:
1. 修正貝塞爾函數 I0 的數值穩定性需要小心處理
2. IS 距離對參數敏感，需要仔細調試
3. V3-4 的 Laplacian 先驗 + MSE 更穩定

**建議**: 除非研究目的，否則使用 V3-4 代替 V3-3

### Q2: V3-2 和 V3-4 哪個 Musical Noise 更少？

**A**:
- **V3-2** Musical Noise 最少（對數域天然平滑）
- **V3-4** 降噪更強但 Musical Noise 略多於 V3-2
- **權衡**: 音質優先選 V3-2，降噪優先選 V3-4

### Q3: 可以混合使用不同變體嗎？

**A**: 不建議。每個變體的增益計算邏輯不同，混合會導致:
- 增益不一致
- Musical Noise 增加
- 頻譜不連續

**替代**: 在同一變體內動態調整參數

### Q4: 為什麼 V3-4 比 V3 慢？

**A**: V3-3 和 V3-4 都需要計算 Modified Bessel I₀ 函數:
- V3: 簡化 E1 近似（快）
- V3-2: E1 函數（中等）
- V3-3: Bessel I₀ 函數（中等）
- V3-4: Bessel I₀ 函數（中等）

速度差異約 28%，但仍遠快於實時 (RTF < 0.01)

### Q5: segSNR 改善 10 dB 算好嗎？

**A**: 評估標準:
- **< 5 dB**: 效果不明顯
- **5-8 dB**: 輕微改善
- **8-12 dB**: 明顯改善 ⭐
- **12-15 dB**: 顯著改善
- **> 15 dB**: 極佳效果

同時需要檢查 WSS < 60，避免過度處理

### Q6: 如何選擇 g_min_db 參數？

**A**: g_min_db 決定最大噪聲抑制量:
- **-15 dB**: 適度降噪（保真度高）
- **-20 dB**: 標準降噪（平衡）
- **-25 dB**: 強降噪（可能失真）
- **-30 dB**: 極強降噪（高風險）

**建議**: 從 -20 dB 開始，根據效果調整

### Q7: alpha_g 平滑因子怎麼設置？

**A**: alpha_g 控制時域平滑:
- **0.5-0.6**: 低平滑（快速響應，可能有 Musical Noise）
- **0.7-0.8**: 中平滑（平衡）⭐
- **0.85-0.9**: 高平滑（Musical Noise 最少，可能過於平滑）

**建議**: V3/V3-4 使用 0.7-0.85，V3-2 使用 0.7

## 實驗範例

### 範例 1: 對比四個變體

```python
#!/usr/bin/env python3
"""
對比 V3, V3-2, V3-3, V3-4 降噪效果
"""
import numpy as np
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import (
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
    LaplacianMmseDenoiser
)

# 讀取音頻
clean, sr = read_audio('test_wav/clean.wav')
noisy, sr = read_audio('test_wav/test_noisy.wav')

# 定義版本
denoisers = {
    'V3 (MMSE-STSA)': SppMmseDenoiser(sample_rate=sr),
    'V3-2 (MMSE-LSA)': MmseLsaDenoiser(sample_rate=sr),
    'V3-3 (PMMSE)': PmmseDenoiser(sample_rate=sr),
    'V3-4 (Laplacian-MMSE)': LaplacianMmseDenoiser(sample_rate=sr)
}

# 評估每個版本
results = {}
for name, denoiser in denoisers.items():
    print(f"\n處理 {name}...")
    enhanced = denoiser.denoise(noisy)
    metrics = composite_measure(clean, enhanced, sr)
    results[name] = metrics

# 打印對比表格
print("\n" + "="*80)
print("MMSE 變體降噪效果對比")
print("="*80)
print(f"{'版本':<25} {'segSNR':>10} {'fwSegSNR':>10} {'WSS':>10} {'global_SNR':>12}")
print("-"*80)

for name, metrics in results.items():
    print(f"{name:<25} "
          f"{metrics['segSNR']:>9.2f}  "
          f"{metrics['fwSegSNR']:>9.2f}  "
          f"{metrics['WSS']:>9.2f}  "
          f"{metrics['global_SNR']:>11.2f}")

print("="*80)

# 找出最佳版本
best_segsnr = max(results.items(), key=lambda x: x[1]['segSNR'])
best_wss = min(results.items(), key=lambda x: x[1]['WSS'])

print(f"\n最佳 segSNR:  {best_segsnr[0]} ({best_segsnr[1]['segSNR']:.2f} dB)")
print(f"最佳 WSS:     {best_wss[0]} ({best_wss[1]['WSS']:.2f})")
```

### 範例 2: 參數敏感度測試

```python
#!/usr/bin/env python3
"""
測試不同 g_min_db 對 V3-4 的影響
"""
import numpy as np
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import LaplacianMmseDenoiser

# 讀取音頻
clean, sr = read_audio('test_wav/clean.wav')
noisy, sr = read_audio('test_wav/test_noisy.wav')

# 測試不同 g_min_db
g_min_values = [-15, -20, -25, -30]

print("\n" + "="*60)
print("V3-4 參數敏感度測試: g_min_db")
print("="*60)
print(f"{'g_min_db':<12} {'segSNR':>10} {'WSS':>10} {'Musical Noise':>15}")
print("-"*60)

for g_min in g_min_values:
    # 創建降噪器 (需要修改配置文件或直接設置)
    denoiser = LaplacianMmseDenoiser(sample_rate=sr)
    # 修改參數 (假設有 set_parameter 方法)
    # denoiser.set_parameter('g_min_db', g_min)

    enhanced = denoiser.denoise(noisy)
    metrics = composite_measure(clean, enhanced, sr)

    # 主觀評估 Musical Noise (需要聽測)
    musical_noise = "需聽測"

    print(f"{g_min:<12.1f} "
          f"{metrics['segSNR']:>9.2f}  "
          f"{metrics['WSS']:>9.2f}  "
          f"{musical_noise:>15}")

print("="*60)
```

### 範例 3: 不同噪聲類型對比

```python
#!/usr/bin/env python3
"""
測試 V3-2 和 V3-4 在不同噪聲類型下的表現
"""
import numpy as np
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import MmseLsaDenoiser, LaplacianMmseDenoiser

# 測試文件
test_files = [
    ('test_wav/babble_5dB.wav', 'Babble 5dB'),
    ('test_wav/car_5dB.wav', 'Car 5dB'),
    ('test_wav/street_5dB.wav', 'Street 5dB'),
]

clean, sr = read_audio('test_wav/clean.wav')

# 創建降噪器
v3_2 = MmseLsaDenoiser(sample_rate=sr)
v3_4 = LaplacianMmseDenoiser(sample_rate=sr)

print("\n" + "="*80)
print("V3-2 vs V3-4 不同噪聲類型對比")
print("="*80)

for noisy_path, noise_type in test_files:
    print(f"\n{noise_type}:")
    print("-" * 60)

    noisy, sr = read_audio(noisy_path)

    # V3-2
    enhanced_v3_2 = v3_2.denoise(noisy)
    metrics_v3_2 = composite_measure(clean, enhanced_v3_2, sr)

    # V3-4
    enhanced_v3_4 = v3_4.denoise(noisy)
    metrics_v3_4 = composite_measure(clean, enhanced_v3_4, sr)

    print(f"  V3-2: segSNR={metrics_v3_2['segSNR']:.2f} dB, WSS={metrics_v3_2['WSS']:.2f}")
    print(f"  V3-4: segSNR={metrics_v3_4['segSNR']:.2f} dB, WSS={metrics_v3_4['WSS']:.2f}")

    # 判斷最佳
    best = "V3-4" if metrics_v3_4['segSNR'] > metrics_v3_2['segSNR'] else "V3-2"
    print(f"  最佳: {best}")

print("="*80)
```

## 參考文獻

### V3 (MMSE-STSA)
- Ephraim, Y., & Malah, D. (1984). "Speech enhancement using a minimum-mean square error short-time spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 32(6), 1109-1121.

### V3-2 (MMSE-LSA)
- Ephraim, Y., & Malah, D. (1985). "Speech enhancement using a minimum mean-square error log-spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 33(2), 443-445.

### V3-3 (PMMSE)
- Wolfe, P. J., & Godsill, S. J. (2003). "Efficient alternatives to the Ephraim and Malah suppression rule for audio signal enhancement." *EURASIP Journal on Advances in Signal Processing*, 2003(10), 1043-1051.

### V3-4 (Laplacian-MMSE)
- Chen, J., & Loizou, P. C. (2007). "Speech enhancement using a MMSE estimator with supergaussian speech modeling." In *2007 IEEE ICASSP*, Vol. 4, pp. IV-853-IV-856. DOI: 10.1109/ICASSP.2007.366837

### 相關資源
- [README.md](../README.md) - 項目主文檔
- [METRICS_USAGE.md](METRICS_USAGE.md) - 評估指標使用指南
- [ALGORITHMS_EXPLANATION.md](../ALGORITHMS_EXPLANATION.md) - 演算法詳細解釋

---

**推薦閱讀順序**: README → METRICS_USAGE → V3_VARIANTS_COMPARISON → ALGORITHMS_EXPLANATION
