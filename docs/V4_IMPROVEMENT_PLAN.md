# V4 (IMCRA-OMLSA) 改善計劃

**狀態**: 未來計劃
**優先級**: 中
**創建日期**: 2026-01-06

## 當前狀態 (v1.6.0)

### 已完成的修復

1. **OMLSA 增益公式修正** ([core/gain_calculators/omlsa.py](../core/gain_calculators/omlsa.py))
   - 移除混合增益公式（線性+對數混合），改用標準 Cohen OMLSA 幾何平均公式
   - 移除雙重增益平滑（幀間限制 + alpha_g 平滑）

2. **配置文件更新** ([config/v4_config.yaml](../config/v4_config.yaml))
   - `g_min_db`: -20.0 → -15.0（避免過度抑制）
   - `alpha_g`: 0.7 → 0.0（完全移除增益平滑）

3. **Benchmark 對齊修復** ([tools/benchmark_comparison.py](../tools/benchmark_comparison.py))
   - 修復 clean.wav 與 prepend 音頻的對齊問題
   - STOI 從 0.20 → 0.79 大幅改善

### 當前性能

| 指標 | V4 | RNNoise | V3-4 (最佳傳統) |
|------|-----|---------|-----------------|
| segSNR 改善 | +4.02 dB | +3.94 dB | +5.30 dB |
| PESQ | 1.24 | 1.70 | 1.40 |
| STOI | 0.79 | 0.90 | 0.86 |
| WSS | 73.9 | 66.4 | 73.5 |

**問題**: V4 的 PESQ (1.24) 和 STOI (0.79) 仍是所有方法中最低的。

---

## 未來改善方向

### 1. 進一步調參

嘗試更保守的參數配置：

```yaml
# config/v4_config.yaml
gain_calculation:
  g_min_db: -12.0     # 更保守（-15 → -12）
  alpha_g: 0.2        # 輕微平滑（0 → 0.2）

noise_estimation:
  alpha_d: 0.88       # 更保守的噪聲更新（0.92 → 0.88）
  delta_db: 6.0       # 減少噪聲估計偏移（8.0 → 6.0）
```

### 2. 噪聲場景轉換功能

**背景**: 當噪聲場景突然變化時（如從安靜環境進入嘈雜街道），IMCRA 的最小值追蹤需要時間適應。

**已實現但未優化的功能**:
- `NoiseChangeDetector` ([core/noise_change_detector.py](../core/noise_change_detector.py))
- `trigger_fast_tracking()` in IMCRA
- `trigger_fast_transition()` in SPP estimator

**改善方向**:

1. **自適應閾值調整**
   ```python
   # 根據當前 SNR 動態調整檢測閾值
   if avg_snr < 5:  # 低 SNR 環境
       energy_ratio_high = 1.5  # 更敏感
   else:
       energy_ratio_high = 2.5  # 更保守
   ```

2. **漸進式參數恢復**
   ```python
   # 不要立即恢復，而是漸進式
   for frame in transition_frames:
       alpha_s = alpha_s_fast + (alpha_s_normal - alpha_s_fast) * (frame / total_frames)
   ```

3. **頻帶獨立的場景檢測**
   ```python
   # 低頻和高頻分別檢測
   low_freq_change = detect_change(spectrum[:n_freqs//4])
   high_freq_change = detect_change(spectrum[n_freqs//4:])
   ```

### 3. 使用 MCRA 替代 IMCRA

**MCRA (Minima Controlled Recursive Averaging)** 是 IMCRA 的前身，計算更簡單但可能更穩定。

對比：
| 特性 | MCRA | IMCRA |
|------|------|-------|
| 複雜度 | 低 | 高 |
| 適應速度 | 較慢 | 較快 |
| 穩定性 | 較高 | 較低 |
| 非穩態噪聲 | 一般 | 較好 |

### 4. 嘗試其他增益函數

除了 OMLSA，還可以嘗試：

1. **MMSE-LSA with IMCRA** - 結合 V3-2 的增益函數和 V4 的噪聲估計
2. **Ephraim-Malah** - 原始 MMSE-STSA
3. **Beta-order MMSE** - 更靈活的增益形狀

---

## 參考資料

- [Cohen's OMLSA Paper (2001)](https://israelcohen.com/wp-content/uploads/2018/05/sp_Nov2001.pdf)
- [GitHub: OMLSA-IMCRA Python](https://github.com/yuzhouhe2000/OMLSA-IMCRA)
- [GitHub: OMLSA MATLAB](https://github.com/zhr1201/OMLSA-speech-enhancement)

### 標準 Cohen OMLSA 公式

- **增益**: G = G_H1^p × G_min^(1-p) (幾何平均)
- **G_H1**: η/(1+η) × exp(0.5×E1(v))，其中 v = η/(1+η)×γ
- **SNR 平滑**: η = α×(G²_prev×γ_prev) + (1-α)×max(γ-1, 0)
- **無額外增益平滑**: 平滑僅通過 SNR 估計實現

---

## 相關文件

- [core/gain_calculators/omlsa.py](../core/gain_calculators/omlsa.py) - OMLSA 增益計算器
- [core/noise_estimators/imcra.py](../core/noise_estimators/imcra.py) - IMCRA 噪聲估計器
- [core/spp_estimator.py](../core/spp_estimator.py) - SPP 估計器
- [core/noise_change_detector.py](../core/noise_change_detector.py) - 噪聲場景變化檢測器
- [denoisers/v4_imcra_omlsa.py](../denoisers/v4_imcra_omlsa.py) - V4 降噪器
- [config/v4_config.yaml](../config/v4_config.yaml) - V4 配置文件
