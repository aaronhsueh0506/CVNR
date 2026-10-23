# V3 MMSE 變體對比

> Python 範例請在 repository 根目錄設定 `PYTHONPATH=python`；程式碼與 YAML 位於 `python/`。

## 目錄

1. [概述](#概述)
2. [理論基礎](#理論基礎)
3. [公式對比](#公式對比)
4. [選擇與參數](#選擇與參數)
5. [常見問題](#常見問題)
6. [實驗範例](#實驗範例)
7. [參考文獻](#參考文獻)

## 概述

Python 參考實作有三個 MMSE 變體（V3、V3-2、V3-3），共用 MCRA 噪聲估計與 Bayesian SPP。
**release 只用 V3-2**，C 端 (`c_impl/`) 只對應 V3-2；V3 與 V3-3 是研究用程式碼。

- **V3 (MMSE-STSA)**：標準 MMSE，Gaussian 先驗 (Ephraim & Malah 1984)
- **V3-2 (MMSE-LSA)**：對數域 MMSE，Musical Noise 最少 (Ephraim & Malah 1985)
- **V3-3 (PMMSE)**：加權歐氏準則 p = -1 的 MMSE-STSA (Loizou 2005)

| 版本 | 程式 | 設定檔 |
|---|---|---|
| V3 | `python/denoisers/v3_spp_mmse.py` | `python/config/v3_config.yaml` |
| V3-2 | `python/denoisers/v3_2_mmse_lsa.py` | `python/config/v3_2_config.yaml` |
| V3-3 | `python/denoisers/v3_3_pmmse.py` | `python/config/v3_3_config.yaml` |

## 理論基礎

所有變體都基於最小均方誤差 (MMSE) 框架：給定帶噪語音 Y，估計乾淨語音 X，使
`E[C(X, X̂) | Y]` 最小，其中 C 是成本函數。

| 變體 | 成本函數 C(X, X̂) | 先驗分佈 p(X) | 操作域 | 特點 |
|------|------------------|--------------|--------|------|
| **V3** | (X - X̂)² | Gaussian | 線性 | 標準實現 |
| **V3-2** | (log X - log X̂)² | Gaussian | 對數 | Musical Noise 最少 |
| **V3-3** | 加權歐氏 (p = -1) | Gaussian | 線性 | 感知動機 |

**關鍵差異**：成本函數決定優化目標（線性域、對數域或感知加權）；先驗分佈決定語音幅度譜的
統計假設。

- **V3**：假設語音幅度譜服從 Gaussian 分佈；理論簡單，計算快速。
- **V3-2**：對數域優化更符合人耳感知，log(X) 的誤差對小值更敏感，Musical Noise 較少。
- **V3-3**：閉式解析解，使用 `i0e` 避免 Bessel 函數在大參數時溢位。

## 公式對比

### V3: MMSE-STSA

```
G = (Γ(1.5)/γ) * √v * exp(-v/2) * [(1+v)I₀(v/2) + vI₁(v/2)],    Γ(1.5) = √π/2
```

v > 100 時為避免溢位改用 E1 式。`use_full_formula = false` 時全程使用 E1 簡化式：

```
G ≈ (ξ/(1+ξ)) * exp(0.5 * E1(v))
```

- ξ = 先驗 SNR，γ = 後驗 SNR，v = ξγ/(1+ξ)
- I₀, I₁ = Modified Bessel 函數；E1 = 指數積分函數

### V3-2: MMSE-LSA

```
G = (ξ/(1+ξ)) * exp(0.5 * E1(v)),    E1(v) = ∫[v to ∞] (e^(-t) / t) dt
```

對數域估計 `X̂ = exp(E[log X | Y])`；E1 函數天然平滑，Musical Noise 較少。

### V3-3: PMMSE (Loizou 2005, p = -1)

```
G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I0(v/2)
     = sqrt(v) / (sqrt(π) · γ) / i0e(v/2)
```

- `v = ξ/(1+ξ) · γ`
- `i0e(x) = exp(-|x|) · I0(x)`（數值穩定的指數縮放 Bessel 函數，`scipy.special.i0e`）
- Gaussian 先驗：語音 DFT 係數為 complex Gaussian、幅度為 Rayleigh 分佈

## 選擇與參數

- **產品**：V3-2（Musical Noise 最少，C 端同一套演算法）。強度用 strength mode 選，
  見 [parameter_tuning.md](parameter_tuning.md)。
- **研究對比**：V3、V3-3 用於比較不同成本函數。
- 各版本的預設參數在 `python/config/*.yaml`；`g_min_db` 為 audio 振幅 dB（`/20`），
  `alpha_xi`／`xi_min_db` 為 SPP 的 DD 平滑與先驗 SNR 下限。
- 調整時一次只動一個參數，並用同一批音檔做 A/B（`python/tools/run_vctk_benchmark.py`
  與 `compare_vctk_benchmark.py`）。

所有 V3 系列使用同一個 MCRA 最小值追蹤器：自動適應噪聲場景變化，每 L 幀更新最小值，
無需額外配置。

## 常見問題

### Q1: 可以混合使用不同變體嗎？

不建議。每個變體的增益計算邏輯不同，混合會導致增益不一致、Musical Noise 增加與頻譜不連續。
在同一變體內調整參數即可。

### Q2: segSNR 改善 10 dB 算好嗎？

- **< 5 dB**: 效果不明顯
- **5-8 dB**: 輕微改善
- **8-12 dB**: 明顯改善
- **12-15 dB**: 顯著改善
- **> 15 dB**: 極佳效果

同時檢查 WSS < 60，避免過度處理。

### Q3: 如何選擇 g_min_db？

`g_min_db` 決定最大噪聲抑制量（audio 振幅 dB，`/20`）。四級 strength preset 為
-20 / -23 / -25 / -28 dB（見 [parameter_tuning.md](parameter_tuning.md)）；越小壓得越深，
語音失真風險越高。

### Q4: alpha_g 平滑因子怎麼設置？

alpha_g 控制 Python 端的時域增益平滑：

- **0.5-0.6**: 低平滑（快速響應，可能有 Musical Noise）
- **0.7-0.8**: 中平滑（平衡）
- **0.85-0.9**: 高平滑（Musical Noise 最少，可能過於平滑）

C 端 `alpha_g` 不參與增益運算，平滑改調 `alpha_decay`／`alpha_attack`。

## 實驗範例

### 對比三個變體

```python
#!/usr/bin/env python3
"""
對比 V3, V3-2, V3-3 降噪效果
"""
import numpy as np
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import (
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
)

# 讀取音頻
clean, sr = read_audio('test_wav/wav/clean.wav')
noisy, sr = read_audio('test_wav/wav/babble_10dB.wav')

# 定義版本
denoisers = {
    'V3 (MMSE-STSA)': SppMmseDenoiser(sample_rate=sr),
    'V3-2 (MMSE-LSA)': MmseLsaDenoiser(sample_rate=sr),
    'V3-3 (PMMSE)': PmmseDenoiser(sample_rate=sr),
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

## 參考文獻

### V3 (MMSE-STSA)
- Ephraim, Y., & Malah, D. (1984). "Speech enhancement using a minimum-mean square error short-time spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 32(6), 1109-1121.

### V3-2 (MMSE-LSA)
- Ephraim, Y., & Malah, D. (1985). "Speech enhancement using a minimum mean-square error log-spectral amplitude estimator." *IEEE Transactions on Acoustics, Speech, and Signal Processing*, 33(2), 443-445.

### V3-3 (PMMSE)
- Loizou, P. C. (2005). "Speech enhancement based on perceptually motivated Bayesian estimators of the magnitude spectrum." *IEEE Transactions on Speech and Audio Processing*, 13(5), 857-869.

### 相關資源
- [README.md](../README.md) - 項目主文檔
- [METRICS_USAGE.md](METRICS_USAGE.md) - 評估指標使用指南
- [parameter_tuning.md](parameter_tuning.md) - 調參指南
- [歷史演算法說明](archive/algorithm_history.md) - 舊版本公式與研究背景（非現行 release contract）
