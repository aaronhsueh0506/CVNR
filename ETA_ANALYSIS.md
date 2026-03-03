# Eta 場景轉換偵測 - 完整分析

## 什麼是 Eta？

Eta (η) 是 MCRA 噪聲估計中的**場景轉換加速因子**，用於在環境噪聲突然變化時加速噪聲更新。

### 核心概念

在正常的 MCRA 中，噪聲更新公式為：
```
α̃_d = α_d + (1 - α_d) × SPP
N(k,l) = α̃_d × N(k,l-1) + (1 - α̃_d) × |Y(k,l)|²
```

加入 eta 後：
```
α̃_d = α̃_d × η
當 η < 1: 噪聲更新加速（α̃_d 降低 → 更快追蹤新噪聲）
當 η = 1: 正常運作（不干擾）
```

### 應用場景

**理想情況**：
- 前 3 秒靜音或低噪聲
- 突然切換到高噪聲環境（例如：進入嘈雜餐廳）
- Eta 偵測到場景變化，加速噪聲更新

**實際問題**：
- 難以區分「語音開始」和「場景變化」
- 容易誤觸發，導致語音段噪聲估計錯誤
- 在穩定噪聲環境反而降低 PESQ

---

## Eta 的三個版本

### Version 1: Sigmoid 方法（v2.6 及之前）

**實現**：
```python
η = 0.95 / (1 + exp(slope × (β - threshold)))
其中 β = E_smooth / E_smooth_prev
```

**問題**：
- 上限 0.95 導致語音幀 `tilde_alpha_d` 也下降
- 噪聲更新速度在語音段增加 ~10x
- 造成語音失真

**測試結果** (VCTK/DEMAND 824 files):
| 配置 | PESQ | STOI |
|------|------|------|
| 舊 eta (threshold=2) | +0.085 | -0.068 |
| 不開 eta | **+0.437** | **-0.007** |

**結論**: ❌ **舊版 eta 反而降低 PESQ -0.35**

---

### Version 2: Hard Threshold 方法（v2.7.0）

**實現**：
```python
E_smooth = 0.7 × E_smooth_prev + 0.3 × E_cur
β = E_smooth / E_smooth_prev

if β > threshold:
    η = 0.1  # 場景突變，加速噪聲更新
else:
    η = 1.0  # 正常，完全不干擾
```

**改進**：
- β ≤ threshold 時 η=1.0，完全不干擾正常運作
- 僅在明確場景變化時觸發

**測試結果** (VCTK/DEMAND 824 files):
| 配置 | PESQ | STOI |
|------|------|------|
| 新 eta (threshold=2) | +0.399 | -0.010 |
| 新 eta (threshold=10) | +0.431 | -0.008 |
| 不開 eta | **+0.437** | **-0.007** |

**結論**: ✓ **新版 eta 大幅改進**，但仍然略低於不開 eta（-0.006 PESQ）

---

### Version 3: S/S_min Ratio + SPP 過濾（v4.0 當前版本）

**實現**：
```python
def _compute_eta_from_ratio(self):
    # 計算平均 beta = mean(S / S_min)
    beta = np.mean(self.S / (self.S_min + 1e-10))

    # 冷卻機制：觸發後暫停 50 幀（0.5秒）
    if self._eta_cooldown > 0:
        self._eta_cooldown -= 1
        return 1.0

    # 條件1: β 要夠大
    if beta <= self.eta_beta_threshold:
        return 1.0

    # 條件2: SPP 要低（確認不是語音）
    if self.spp is not None:
        mean_spp = np.mean(self.spp)
        if mean_spp > 0.3:
            return 1.0  # SPP 高 = 有語音，不觸發

    # 同時滿足：β 高 + SPP 低 = 場景變化
    self._eta_cooldown = 50

    if self.eta_slope > 0:
        eta = 1.0 / (1.0 + np.exp(self.eta_slope * (beta - self.eta_beta_threshold)))
        return max(eta, 0.01)
    else:
        return 0.1
```

**改進**：
- 使用 MCRA 內部的 S/S_min 比值（更直接反映噪聲變化）
- **SPP 過濾**：只有當 SPP < 0.3 才觸發（排除語音段）
- **冷卻機制**：觸發後 50 幀內不重複觸發
- 雙重條件判斷：β 高 + SPP 低

**理論優勢**：
- S/S_min 是 MCRA 核心指標，直接反映噪聲底線變化
- SPP 過濾可避免語音開始誤觸發
- 冷卻機制避免反覆觸發

**測試狀態**：
- ⚠️ **尚未在 VCTK/DEMAND 上進行完整測試**
- 需要驗證是否比 v2.7.0 版本更好

---

## 測試結果總結

### test_wav (13 files, 穩定噪聲)

基於 `compare_eta_full.py` 的測試：

| 配置 | PESQ | STOI | ΔPESQ |
|------|------|------|-------|
| **enable_eta=false** | **2.127** | 0.960 | baseline |
| enable_eta=true (threshold=2) | 1.717 | 0.892 | **-0.41** ❌ |
| enable_eta=true (threshold=10) | 2.067 | 0.952 | **-0.06** ⚠️ |

**結論**：
- Threshold=2 太敏感，嚴重誤觸發（-0.41 PESQ）
- Threshold=10 改善但仍有損失（-0.06 PESQ）
- 在穩定噪聲環境，eta **無益處**

### VCTK/DEMAND (824 files, 非穩態噪聲)

基於 CHANGELOG v2.7.0 的測試：

| 版本 | 配置 | PESQ | STOI | ΔPESQ |
|------|------|------|------|-------|
| v2.6 | 舊 eta (sigmoid, threshold=2) | +0.085 | -0.068 | baseline |
| v2.7 | 新 eta (hard threshold, threshold=2) | +0.399 | -0.010 | **+0.314** ✓ |
| v2.7 | 新 eta (threshold=10) | +0.431 | -0.008 | **+0.346** ✓ |
| v2.7 | **不開 eta** | **+0.437** | **-0.007** | **+0.352** ✓ |

**結論**：
- v2.7 新版 eta 大幅改進舊版
- 但仍然略低於不開 eta（-0.006 PESQ）
- 即使在非穩態噪聲，eta 收益**極其有限**

---

## 當前配置 (v4.0)

### V3-2 配置
```yaml
noise_estimation:
  enable_eta: false
  eta_beta_threshold: 10.0
  eta_slope: 20.0
```

### V4 配置
```yaml
noise_estimation:
  enable_eta: false
  eta_beta_threshold: 10.0
  eta_slope: 20.0
```

**決策**：兩個版本都**默認關閉 eta**

---

## Eta Enable vs Disable 差異

### Enable Eta (enable_eta=true)

**優點**：
- 理論上可加速噪聲適應（場景轉換）
- 在極端場景變化可能有幫助

**缺點**：
- 難以準確區分「語音開始」vs「場景變化」
- 在穩定噪聲環境反而降低 PESQ（-0.06 到 -0.41）
- 即使在非穩態噪聲，收益極其有限（0.006 PESQ）
- 增加代碼複雜度和計算開銷

### Disable Eta (enable_eta=false, **推薦**)

**優點**：
- **PESQ 最高**（測試證明）
- 代碼簡單，穩定可靠
- 無誤觸發風險

**缺點**：
- 場景突變時噪聲適應稍慢（但實測影響極小）

---

## 建議

### 一般應用
✅ **推薦 enable_eta=false**

測試證明：
- 穩定噪聲：eta 降低 PESQ
- 非穩態噪聲：eta 收益 < 0.01 PESQ
- 場景轉換：理論有效但實際測試數據不足

### 特殊場景
如果確實需要快速場景適應，可考慮：
1. **threshold=10**（而非 2）：減少誤觸發
2. **使用 v4.0 ratio 方法**：有 SPP 過濾，理論上更準確
3. **先在目標數據集上測試驗證**

---

## 代碼位置

### Python 實現
- 文件：[core/noise_estimators/mcra.py](LSA/core/noise_estimators/mcra.py)
- v2.7 方法：`_compute_eta()` (已移除)
- v4.0 方法：`_compute_eta_from_ratio()` (line 122-164)

### C 實現
- 文件：`c_impl/src/mcra_noise_estimator.c`
- 配置：`c_impl/example/main.c` line 75
  ```c
  config.enable_eta = false;  // v4.0 默認關閉
  ```

### 測試腳本
- `compare_eta_full.py`: test_wav + VCTK 完整測試
- `test_eta_configs.py`: 不同 threshold 配置測試
- `visualize_eta_curve.py`: Eta 曲線可視化
- `compare_spp_eta.py`: SPP vs Eta 關係分析

---

## 總結

| 方面 | Enable Eta | Disable Eta |
|------|-----------|-------------|
| **PESQ** | 較低 (-0.006 到 -0.41) | ✓ **最高** |
| **穩定噪聲** | ❌ 降低效果 | ✓ 最佳 |
| **非穩態噪聲** | ± 收益極小 | ✓ 最佳 |
| **場景轉換** | ± 理論有效 | - 稍慢（影響小）|
| **複雜度** | 高 | ✓ 簡單 |
| **穩定性** | 有誤觸發風險 | ✓ 穩定 |

**最終建議**: ✅ **disable eta (enable_eta=false)**

測試數據明確顯示，在實際應用中，eta 機制的收益**遠小於**其引入的風險和複雜度。即使在理論上最有利的非穩態噪聲場景，收益也僅 0.006 PESQ，可忽略不計。
