# 語音降噪演算法詳解

**版本**：v4.2
**更新日期**：2026-04-17
**適用對象**：技術介紹、演算法說明、項目展示

> **⚠️ v4.2 release 重要聲明**
>
> 本文檔保留了歷史各版本演進脈絡（v1.x–v2.x）供參考。**Release 主推演算法**為 **V3-2 OMLSA**（MMSE-LSA + Bayesian SPP + IMCRA），經 Part A Review 11 項修復，Python 與 C 皆已同步。
>
> **V4 新版本**（`denoisers/v4_omlsa.py` + `core/wind_detector.py` 等）**不是**本文件下方「V4: IMCRA-OMLSA」章節所描述的舊 V4。現行 V4 是「OMLSA + Wind Handler research 框架」，VCTK/DEMAND 驗證**未能改善**風聲場景，**不建議 release 使用**。詳見 [README.md](README.md) 與 `results/v4_diagnosis_report.md`。
>
> 下方舊 V4 章節的歷史內容（IMCRA + 對數域平滑）**仍是 V3-2 + IMCRA 內部設計基礎**，可作為理解 OMLSA 的技術參考，但**命名與參數不再對應現行 V4**。

---

## 目錄

1. [系統概述](#系統概述)
2. [核心技術架構](#核心技術架構)
3. [演算法版本詳解](#演算法版本詳解)
4. [MMSE 變體詳解 (v1.4.0)](#mmse-變體詳解-v140)
5. [評估指標 (v1.4.0)](#評估指標-v140)
6. [關鍵技術創新](#關鍵技術創新)
7. [性能指標與對比](#性能指標與對比)
8. [應用場景](#應用場景)
9. [技術優勢](#技術優勢)

---

## 系統概述

### 項目定位

本系統是一個**基於傳統信號處理的實時語音降噪解決方案**，實現了從基礎到產品級的四個演算法版本，適用於 VoIP、會議系統、錄音降噪等實時語音處理場景。

### 核心特點

- ✅ **七個演算法版本**：V1-V4 基礎版本 + V3-2 到 V3-4 MMSE 變體（V3-1 已合併到 V3）
- ✅ **實時處理能力**：所有版本 RTF < 0.01（遠超實時標準）
- ✅ **Musical Noise 完全解決**：創新的時間平滑機制
- ⚠️ **噪聲場景自適應**：v1.3.0 新增噪聲變化檢測與快速適應（Eta 機制已在 v4.1 移除，L=5 優化已替代）
- ✅ **MMSE 學術標準實現**：v1.4.0 新增四個 MMSE 變體（Ephraim-Malah, Loizou, Chen）
- ✅ **V3 整合升級**：v1.5.0 整合 V3-1，支持 Bessel/E1 公式切換
- ✅ **V4 全面優化**：v1.5.0 修復音量和震動問題，優化配置和混合策略
- ✅ **噪聲追蹤擴展**：v1.5.0 擴展到所有主要版本（V2, V3-2, V3-3, V3-4, V4）
- ✅ **專業評估指標**：v1.4.0 新增 Loizou 2008 推薦指標
- ✅ **模塊化架構**：易於集成和擴展
- ✅ **參數可調**：豐富的配置選項適應不同場景

### 技術指標

| 指標 | 數值 | 說明 |
|------|------|------|
| 處理延遲 | 10ms | 幀移時間 |
| 實時性能 | RTF 0.003-0.008 | 所有版本均遠超實時 |
| 降噪效果 | segSNR 改善 10-15dB | 顯著改善 |
| 適用 SNR | 0-20 dB | 覆蓋常見噪聲環境 |
| 噪聲適應 | 100-600ms | v1.3.0 新增 |

---

## v4.2 重大更新 (2026-04-17) — Part A Review 修復

本次 release 套用 Part A Review 11 項修復，同步至 Python + C：

| Fix | 項目 | 影響模組 |
|-----|------|----------|
| #1 | MCRA 初始化 `S = init_psd`（原 `avg_power`，與 `S_min` 不一致） | `core/noise_estimators/mcra.py`、`c_impl/src/mcra_noise_estimator.c` |
| #2 | 初始化幀 lightweight passthrough（首 200 ms 輸出 = 輸入 + gain 計算） | `denoisers/v3_2_mmse_lsa.py` |
| #3 | SPP Decision-Directed term 改用**前一幀** `noise_psd`（理論一致） | `core/spp_estimator.py`、`c_impl/src/spp_estimator.c` |
| #4 | `alpha_d` 接通 denoiser `__init__` | Python loader |
| #5 | `alpha_attack` / `alpha_decay` 非對稱平滑參數外露 | `denoisers/v3_2_mmse_lsa.py` |
| #6 | Scene change flatness 閾值參數化（config `scene_change_flatness_threshold`） | MCRA（Python + C） |
| #7 | Analysis/synthesis window 改為 periodic (`sym=False`)，COLA 完全準確 | `core/frame_processor.py`（C 端原本就正確） |
| #8 | `denoise_spectrum()` 入口自動 reset，避免跨呼叫狀態污染 | `denoisers/v3_2_mmse_lsa.py` |
| #9 | SPP prior probability `q` clip 到 `(1e-6, 1-1e-6)` | `core/spp_estimator.py`、`c_impl/src/spp_estimator.c` |
| #10/#11 | 清理過時註解與 `__main__` demo | 各檔 |

**V4 誠實定位**（v4.2）：
- `denoisers/v4_omlsa.py` + wind handler 三個模組（`core/wind_detector.py`、`core/freq_adaptive_controller.py`、`core/transient_suppressor.py`）為 **research 框架**
- 在 VCTK/DEMAND 驗證子集上**未能改善風聲**（根因：風聲低頻能量與語音 F1/F2 頻段重疊，單麥克風 + 統計特徵無法可靠區分）
- `config/v4_config.yaml` 預設 **FLAT adaptive profile + transient OFF**，等同 V3-2
- 保留作為後續研究起點，**不建議直接 release 使用**

---

## v1.5.0 重大更新 (2026-01-02)

### 🎯 階段 1：V3 整合 V3-1 - 統一 MMSE-STSA 實現

**背景**：V3 (SPP-MMSE) 和 V3-1 (MMSE-STSA) 實際上是同一演算法的不同實現

**整合方案**：
- V3 現在支持兩種 MMSE-STSA 公式切換：
  - **E1 簡化版**（默認，`use_full_formula: false`）：快速計算，數值穩定，誤差 < 5%
  - **Bessel 完整版**（`use_full_formula: true`）：學術標準實現（Ephraim-Malah 1984）
- V3 統一命名為 "MMSE-STSA"（移除 "SPP-MMSE" 舊稱）
- 刪除獨立的 V3-1 版本，減少冗余

**配置示例**：
```yaml
# config/v3_config.yaml
gain_calculation:
  use_full_formula: true  # true=Bessel, false=E1簡化(推薦)
```

### 🎯 階段 2：V4 性能優化 - 修復音量和震動問題

**問題**：V4 在某些場景下存在音量損失（8-10dB）和震動感

**優化內容**：

#### 1. 配置優化
- **IMCRA 參數調整**：`alpha_d: 0.85 → 0.88`（減緩噪聲更新）、`L: 150 → 120`（縮短窗口）、`delta_db: 5 → 8`（增大偏移）
- **OMLSA 參數調整**：`alpha_g: 0.85 → 0.88`（增強平滑）

#### 2. 混合策略（Hybrid Strategy）
- 低 SPP 區域（< 0.3）：使用線性域/對數域混合增益，減少過度抑制
- 過渡平滑：避免突變

#### 3. 變化限制（Clamping）
- 限制幀間增益變化速率：±6dB max
- 防止震動感

#### 4. 自適應 delta
- 根據 SNR 動態調整 delta：3-12dB
- 高 SNR 使用較小補償，低 SNR 使用較大補償

**效果**：
- 音量損失從 8-10dB 降至 3-5dB
- 震動感明顯減少
- 語音自然度提升

### 🎯 階段 3：噪聲場景追蹤擴展

**新增支持版本**：
- V2 (Wiener Filter)
- V3-2 (MMSE-LSA)
- V3-3 (PMMSE)
- V3-4 (Laplacian-MMSE)
- V4 (IMCRA-OMLSA)

**統一配置**：
```yaml
noise_tracking:
  enable: true  # 所有版本統一開關
```

**適應速度**：
- V2: 100-200ms
- V3-2/V3-3/V3-4: 100-200ms
- V4: 300-600ms（受最小值追蹤影響）

### 🎯 階段 4：文檔和測試完善

- 更新所有配置文件（v2, v3, v3-2, v3-3, v3-4, v4）
- 統一測試框架
- 完善技術文檔

---

## v2.2 重大更新 (2026-01-08)

### 🎯 V2 Wiener Filter 核心改進

#### Bayesian SPP 取代 Sigmoid 近似

**之前（Sigmoid 近似 - 不準確）:**
```python
spp = 1 / (1 + exp(-2*(γ-1)))  # 僅用 γ，忽略 ξ
```

**之後（Bayesian SPP - 正確）:**
```python
Λ = ξ/(1+ξ) · γ
spp = 1 / [1 + (q/(1-q)) · exp(-Λ)]
```

**改進效果**: V2 ΔPESQ 從 +0.035 提升至 +0.244

#### DD 公式修正（Decision-Directed SNR Estimation）

**之前:** 使用 prev_gamma（間接計算）
**之後:** 使用 enhanced_mag_prev（直接計算）

```
ξ(l) = α · [|X̂(l-1)|² / N(l)] + (1-α) · max(γ(l)-1, 0)
其中 |X̂(l-1)| = G(l-1) · |Y(l-1)|  ← 直接使用增強後幅度
```

這是 Ephraim & Malah (1984) 原始論文中的正確實現方式。

#### MCRA 噪聲估計支持

新增 MCRA (Minima Controlled Recursive Averaging) 噪聲估計器選項：
- 更穩健的最小值追蹤
- SPP 加權更新
- 對非穩態噪聲更魯棒

---

## v2.3 重大更新 (2026-01-08)

### 🎯 MCRA 雙視窗最小值追蹤

#### 噪聲場景適應機制

使用 Cohen & Berdugo 2002 的 Dual-Window Minima Tracking 方法，
MCRA 內建自動適應噪聲場景變化的能力，無需外部檢測器。

```python
# 雙視窗最小值追蹤
self.S_min = np.minimum(self.S_min, self.S)
self.S_min_sw = np.minimum(self.S_min_sw, self.S)
self.counter += 1

# 每 L 幀強制更新（自動適應噪聲場景變化）
if self.counter >= self.L:
    self.S_min = np.minimum(self.stored_min, self.S_min_sw)
    self.stored_min = self.S_min_sw.copy()
    self.S_min_sw = self.S.copy()
    self.counter = 0
```

**優點:**
- ✅ 內建場景變化適應
- ✅ 減少程式碼重複
- ✅ 消除邏輯衝突
- ✅ 簡化降噪器介面

#### 架構改善

重構後的簡化架構：
```
Denoiser
└── NoiseEstimator (MCRA with dual-window)
    └── 內建場景變化適應 (每 L 幀自動更新)
```

---

## 核心技術架構

### 信號處理流程

```
輸入音頻
    ↓
[分幀處理] ← 20ms 幀長，50% 重疊
    ↓
[加窗] ← Hanning 窗
    ↓
[FFT] ← 512 點快速傅立葉變換
    ↓
[噪聲估計] ← 各版本不同策略
    ↓
[增益計算] ← 頻率選擇性抑制
    ↓
[增益時間平滑] ← Musical Noise 抑制
    ↓
[IFFT] ← 逆快速傅立葉變換
    ↓
[Overlap-Add] ← 幀重建
    ↓
輸出音頻
```

### 模塊化設計

系統採用清晰的分層架構：

```
denoisers/          ← 完整降噪器（V1-V4 + MMSE 變體）
    ├── v1_spectral_subtraction.py
    ├── v2_wiener.py
    ├── v3_spp_mmse.py          ← v1.5.0 整合 V3-1，支持公式切換
    ├── v3_2_mmse_lsa.py        ← v1.4.0 MMSE-LSA
    ├── v3_3_pmmse.py           ← v1.4.0 PMMSE
    ├── v3_4_laplacian_mmse.py  ← v1.4.0 Laplacian-MMSE
    └── v4_imcra_omlsa.py

core/               ← 核心組件
    ├── frame_processor.py      ← 分幀、FFT
    ├── reconstructor.py        ← 重建、IFFT
    ├── spp_estimator.py        ← 語音存在機率估計
    ├── noise_change_detector.py ← 噪聲場景變化檢測（v1.3.0）
    ├── noise_estimators/       ← 噪聲估計器
    │   ├── simple_average.py
    │   ├── recursive_average.py
    │   └── imcra.py
    └── gain_calculators/       ← 增益計算器
        ├── spectral_subtraction.py
        ├── wiener.py
        ├── spp_mmse.py         ← v1.5.0 整合 MMSE-STSA
        ├── mmse_lsa.py         ← v1.4.0 MMSE-LSA
        ├── pmmse.py            ← v1.4.0 PMMSE
        ├── laplacian_mmse.py   ← v1.4.0 Laplacian-MMSE
        └── omlsa.py

utils/              ← 工具模塊
    ├── audio_io.py
    └── metrics_loizou.py       ← v1.4.0 Loizou 評估指標
```

---

## 演算法版本詳解

### V1: 頻譜減法（Spectral Subtraction）

**技術原理**：直接從噪聲語音頻譜中減去估計的噪聲頻譜

#### 核心公式

```
S_est(ω) = |Y(ω)| - α · |N(ω)|
```

- `Y(ω)`：噪聲語音頻譜
- `N(ω)`：估計的噪聲頻譜
- `α`：過減因子（over-subtraction factor）

#### 噪聲估計方法

- 使用音頻開始的 20 幀（200ms）估計噪聲
- 假設前幾幀只包含噪聲（無語音）
- 計算這些幀的平均功率譜作為噪聲估計

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| alpha | 1.0-2.0 | 過減因子，控制降噪強度 |
| beta | 0.02 | 頻譜下限，防止過度抑制 |
| alpha_smooth | 0.8 | 時間平滑因子（v1.1.0 新增） |

#### 技術特點

- ✅ **最快速**：計算量最小，RTF = 0.003
- ✅ **實現簡單**：概念直觀，易於理解
- ⚠️ **Musical Noise**：已通過時間平滑解決
- ⚠️ **語音失真**：過減因子過大時會削弱語音

#### 適用場景

- 穩態噪聲環境（辦公室、空調）
- 快速原型開發
- 計算資源受限的設備

---

### V2: Wiener 濾波（Wiener Filter）

**技術原理**：基於最小均方誤差（MMSE）準則的最優線性濾波

#### 核心公式

```
H(ω) = SNR(ω) / (1 + SNR(ω))
```

- `H(ω)`：Wiener 增益
- `SNR(ω) = S(ω) / N(ω)`：信噪比

#### 噪聲估計方法

- **遞歸平均**：持續更新噪聲估計
  ```
  N_t(ω) = α · N_{t-1}(ω) + (1-α) · |Y_t(ω)|²
  ```
- 參數 `α = 0.95`：控制適應速度

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| alpha | 0.95 | 噪聲更新速率 |
| min_gain | 0.1 | 最小增益，防止過度抑制 |
| alpha_smooth | 0.8 | 時間平滑因子（v1.1.0 新增） |

#### 技術特點

- ✅ **理論最優**：MMSE 準則下的最優濾波器
- ✅ **適應性強**：遞歸更新可適應緩慢變化的噪聲
- ✅ **語音失真小**：相比頻譜減法更柔和
- ⚠️ **Musical Noise**：已通過時間平滑解決

#### 適用場景

- 一般語音增強應用
- 噪聲緩慢變化的環境
- 需要平衡效果和計算量的場景

---

### V3: MMSE-STSA（Speech Presence Probability + MMSE）⭐

**v1.5.0 更新**：
- V3-1 (MMSE-STSA) 已合併到 V3
- 新增 `use_full_formula` 參數支持 Bessel/E1 公式切換
- 統一命名為 "MMSE-STSA"（原 "SPP-MMSE"）
- 配置文件：[config/v3_config.yaml](config/v3_config.yaml:30)

**技術原理**：基於語音存在機率（SPP）的軟判決 MMSE 估計

#### 核心創新：軟判決

傳統方法使用硬判決（0 或 1），SPP-MMSE 使用軟判決（0 到 1 的概率）：

```
G(ω) = p(ω) · G_MMSE(ω) + (1-p(ω)) · G_min
```

- `p(ω)`：語音存在機率（SPP）
- `G_MMSE(ω)`：MMSE 增益
- `G_min`：最小增益

#### SPP 計算流程

1. **後驗 SNR**（Posterior SNR）
   ```
   γ(ω) = |Y(ω)|² / N(ω)
   ```

2. **先驗 SNR**（Prior SNR）- **Decision Directed 方法**
   ```
   ξ(ω) = α_xi · [G²_{prev}(ω) · γ_{prev}(ω)] + (1-α_xi) · max(γ(ω)-1, 0)
   ```
   - 關鍵創新：結合當前幀和前一幀信息，減少估計誤差

3. **似然比**（Likelihood Ratio）
   ```
   Λ(ω) = ξ(ω)/(1+ξ(ω)) · exp(v(ω)/(1+ξ(ω)))
   ```
   - `v(ω) = ξ(ω)·γ(ω)/(1+ξ(ω))`

4. **SPP**
   ```
   p(ω) = Λ(ω) / (Λ(ω) + (q/(1-q)))
   ```
   - `q`：語音先驗機率

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| alpha_xi | 0.98 | 先驗 SNR 平滑因子（核心參數） |
| q | 0.5 | 語音先驗機率 |
| g_min_db | -20 dB | 最小增益 |
| alpha_g | 0.85 | 增益時間平滑（v1.1.0 強化） |

#### 技術特點

- ✅ **軟判決優勢**：平滑的增益過渡，減少失真
- ✅ **Musical Noise 極少**：Decision Directed + 增益平滑
- ✅ **語音質量高**：保留更多語音細節
- ✅ **適應性好**：適用於多種噪聲環境
- ⚠️ **計算量中等**：RTF = 0.006（仍遠超實時）

#### 適用場景

- **推薦使用**：大多數實際應用
- 會議系統、VoIP
- 需要平衡效果和質量的場景
- 非穩態噪聲環境

---

## MMSE 變體詳解 (v1.4.0)

v1.4.0 新增四個基於 MMSE 理論的學術標準實現,涵蓋不同的成本函數、先驗分佈和操作域。

### V3-1: MMSE-STSA (Ephraim-Malah 1984)

> **⚠️ v1.5.0 更新**：V3-1 已合併到 V3，請使用 V3 並設置 `use_full_formula: true` 來使用 Bessel 完整版公式。
>
> 詳見：[V3: MMSE-STSA](#v3-mmse-stsa-speech-presence-probability--mmse)

**技術原理**：最小均方誤差短時頻譜幅度估計 (線性域)

#### 核心公式

**成本函數**: 最小化 `E[(|X| - |Xhat|)²]`

**完整版 (Bessel)**:
```
G = (Γ(1.5)/γ) * √v * exp(-v/2) * [(1+v)*I₀(v/2) + v*I₁(v/2)]
```
- `I₀, I₁`: Modified Bessel functions of order 0 and 1
- `v = ξ/(1+ξ) * γ`

**簡化版 (E1, 推薦)**:
```
G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
```
- `E1(v)`: 指數積分函數
- 誤差 < 5%, 數值穩定性更好

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| use_full_formula | false | true=Bessel, false=E1簡化(推薦) |
| g_min_db | -20 dB | 最小增益 |
| alpha_g | 0.7 | 增益時間平滑 |
| alpha_xi | 0.98 | 先驗 SNR 平滑 |

#### 技術特點

- ✅ **學術標準**: Ephraim-Malah 1984 原始公式
- ✅ **雙版本**: 完整 Bessel / E1 簡化可切換
- ✅ **數值穩定**: v > 100 自動切換到簡化版
- 📖 **研究基準**: MMSE-STSA 是語音增強領域的經典基準

---

### V3-2: MMSE-LSA (Ephraim-Malah 1985)

**技術原理**：最小均方誤差對數短時頻譜幅度估計 (對數域)

#### 核心創新：對數域操作

**成本函數**: 最小化 `E[(log|X| - log|Xhat|)²]`

**關鍵差異**:
```
STSA (V3-1): G = p*G_mmse + (1-p)*g_min          (線性域加權)
LSA  (V3-2): log(G) = p*log(G_mmse) + (1-p)*log(g_min)  (對數域加權)
```

**基礎公式** (與 STSA 相同):
```
G_base = (ξ/(1+ξ)) * exp(0.5 * E1(v))
```

**優勢**:
- 對數域平滑使小增益被抑制更多
- 大增益變化更平緩
- 更符合人耳對數感知 (Weber-Fechner 定律)

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| use_linear_spp_weighting | false | true=線性域(退化為STSA), false=對數域(推薦) |
| g_min_db | -20 dB | 最小增益 |
| alpha_g | 0.7 | 增益時間平滑 |

#### 技術特點

- ✅ **更少 Musical Noise**: 對數域平滑效果更強
- ✅ **感知優化**: 符合人耳對數感知特性
- ✅ **保守策略**: 對小增益更謹慎,保護弱語音
- 📊 **性能**: 相比 STSA 更平滑,但可能稍微過度抑制

---

### V3-3: PMMSE (Wolfe & Godsill 2003)

**技術原理**：Parametric MMSE，β=0.5 特例的 MMSE 估計

#### 核心創新：β 參數化 MMSE

Wolfe & Godsill (2003) 提出了參數化 MMSE 估計框架，其中 β=0.5 給出解析解。

**增益函數** (β=0.5 特例):
```
G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I0(v/2)
     = sqrt(v) / (sqrt(π) · γ) / i0e(v/2)
```

其中:
- `v = ξ/(1+ξ) · γ`（先驗 SNR 與後驗 SNR 的組合）
- `i0e(x) = exp(-|x|) · I0(x)`（避免數值溢出的指數縮放 Bessel 函數）

**Gaussian 先驗**:
```
p(X) ~ CN(0, σ²)  (complex Gaussian)
|X| ~ Rayleigh(σ)  (幅度譜服從 Rayleigh 分佈)
```

#### 數值穩定性

使用 `scipy.special.i0e` 避免 Bessel 函數 I0 在大參數時的溢出問題：
```python
from scipy.special import i0e
gain = np.sqrt(v) / (np.sqrt(np.pi) * gamma) / i0e(v / 2)
```

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| use_spp_weighting | true | 是否使用 SPP 加權 |
| g_min_db | -20 dB | 最小增益 |
| alpha_g | 0.7 | 增益時間平滑 |

#### 技術特點

- ✅ **解析解**: β=0.5 時有閉式解，計算高效
- ✅ **數值穩定**: 使用 i0e 避免溢出
- ✅ **Gaussian 先驗**: 適合一般語音信號
- 📖 **文獻**: Wolfe, P. J., & Godsill, S. J. (2003)

---

### V3-4: Laplacian-MMSE (Chen & Loizou 2007)

**技術原理**：Laplacian 先驗 + 標準 MSE

#### 核心特點

Chen & Loizou (2007) 提出使用 Laplacian 分佈作為語音幅度譜的先驗，比 Gaussian 先驗更符合語音的稀疏特性。

**與 V3-3 的區別**:
| 項目 | V3-3 (PMMSE) | V3-4 (Lap-MMSE) |
|------|--------------|-----------------|
| 先驗分佈 | Gaussian | Laplacian |
| 增益特性 | β=0.5 解析解 | β=1.0 Laplacian |
| 稀疏性 | 標準 | 更強 |

**增益函數** (Chen & Loizou 2007):
```
G_Lap = (√π/2) · √v · exp(-v/2) · I₀(v/2)
```

其中:
- `v = β · ξ/(1+ξ) · γ`
- `β = 1.0`（Laplacian 形狀參數）
- `I₀` 為零階修正 Bessel 函數

**Laplacian 優勢**:
- 峰態係數 = 6（Gaussian 為 3）
- 更「尖銳」，更適合稀疏信號建模
- 語音 DFT 係數實測峰態 ≈ 5-8，更接近 Laplacian

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| beta_laplacian | 1.0 | Laplacian 形狀參數（Chen & Loizou 原始值）|
| g_min_db | -20 dB | 最小增益 |
| alpha_g | 0.7 | 增益時間平滑 |

**beta_laplacian 調優**:
- 1.0: Chen & Loizou 原始設置（推薦）
- 1.5: 較保守，更多抑制
- 2.0: 最保守

#### 技術特點

- ✅ **稀疏性建模**: Laplacian 更符合語音 DFT 係數分佈
- ✅ **少殘留噪聲**: 比 Gaussian-MMSE 更乾淨
- ✅ **可調形狀**: beta 參數控制保守程度
- ✅ **STOI 最優**: 在所有 V3 變體中 STOI 表現最佳
- 📖 **文獻**: Chen, J., & Loizou, P. C. (2007). "Speech enhancement using a MMSE estimator with supergaussian speech modeling."

---

### MMSE 變體對比總結

**v1.5.0 更新**：V3-1 已合併到 V3，現有 4 個 MMSE 變體（V3 + V3-2/V3-3/V3-4）

| 版本 | 成本函數 | 先驗分佈 | 操作域 | 特點 | 推薦場景 |
|------|---------|---------|--------|------|----------|
| **V3** | E[(X-Xhat)²] | Gaussian | 線性 | 標準實現，支持公式切換 | 基準對比 ⭐ |
| **V3-2** | E[(logX-logXhat)²] | Gaussian | 對數 | 更少MN | 高質量要求 |
| **V3-3** | E[(X-Xhat)²/X] | Gaussian | 線性 | 感知優化 | 研究實驗 |
| **V3-4** | E[(X-Xhat)²] | Laplacian | 線性 | 少殘留 | 最佳降噪 |

**使用建議**:
- 🎯 **研究對比**: 使用 V3 (設置 `use_full_formula: true` 使用學術標準 Bessel 公式)
- 🎵 **音質優先**: 選擇 V3-2 (對數域平滑)
- 🧪 **學術實驗**: 使用 V3-3 (感知動機)
- 🏆 **最佳降噪**: 選擇 V3-4 (殘留噪聲最少)

---

## 評估方法論 (v1.6.0)

### 為什麼使用 Loizou 2008 評估標準？

v1.6.0 全面整合業界認可的 Loizou (2008) 評估方法，提供比傳統指標更準確的質量評估。

#### 傳統評估方法的三大問題

**1. 靜音幀污染問題**
- 傳統 segSNR 包含大量靜音幀
- 靜音幀的 SNR 通常很高（虛假提升分數）
- 導致與主觀質量相關性僅 0.40-0.46 ❌

**2. 極值扭曲問題**
- 未限制 SNR 範圍
- 極端值（如 60 dB 或 -40 dB）嚴重扭曲平均值
- 不符合實際聽感

**3. 頻率權重缺失**
- 傳統指標對所有頻率一視同仁
- 忽略人耳對不同頻率的敏感度差異
- 300-3000 Hz（語音主頻）應有更高權重

### Loizou 2008 改進方案

#### ✅ 改進 1: 使用 VAD 排除靜音幀

**為什麼**:
- 靜音幀對語音質量評估無意義
- 排除後與主觀評分相關性提升到 0.65-0.72 ✅

**實現**:
- 能量閾值法：幀能量 > -40 dB 視為語音
- 只計算語音幀的 SNR

#### ✅ 改進 2: 限制 SNR 範圍

**為什麼**:
- 極值 SNR 不符合實際聽感
- 防止少數幀主導平均值

**實現**:
- SNR 限制在 [-10, 35] dB
- 這個範圍涵蓋 99% 的實際情況

#### ✅ 改進 3: 頻率加權

**為什麼**:
- 人耳對 300-3000 Hz 最敏感（語音主頻段）
- 高頻和低頻對語音質量影響較小

**實現**:
- 300-3000 Hz: 權重 1.0
- < 300 Hz: 權重 0.5
- \> 3000 Hz: 權重遞減（0.3-1.0）

### 對標評估結果 (v1.6.0)

基於 Loizou 2008 專業指標，我們與 Speex/RNNoise 進行了全面對標：

**驚人發現**：我們的所有 7 種方法都顯著優於 Speex/RNNoise ✅

| 方法 | segSNR (dB) | fwSegSNR (dB) | WSS | 對比 Speex |
|------|-------------|---------------|-----|-----------|
| **Speex** | -4.98 | -0.68 | 1.5 | - |
| **RNNoise** | -3.98 | -0.26 | 1.5 | +1.00 dB |
| **我們 V1** | **+2.91** | **+6.59** | **0.8** | **+7.89 dB** ✅✅✅ |
| **我們 V2** | +1.08 | +4.05 | 0.9 | +6.06 dB ✅✅ |
| **我們 V3** | +0.38 | +4.23 | 1.0 | +5.36 dB ✅ |

**關鍵洞察**:
- ✅ **Speex/RNNoise 負值性能**：在我們的測試集上反而降低了音質
- ✅ **V1 最優**：最簡單的頻譜減法反而表現最佳（segSNR +2.91 dB）
- ✅ **全面達標**：即使表現最弱的 V3-3（-0.21），也比 Speex 好 4.77 dB

### 指標解讀參考表

| 指標 | 優秀 | 良好 | 可接受 | 需改進 | 方向 |
|------|------|------|--------|--------|------|
| segSNR | > 10 dB | > 8 dB | > 6 dB | < 6 dB | ⬆️ 越高越好 |
| fwSegSNR | > 11 dB | > 9 dB | > 7 dB | < 7 dB | ⬆️ 越高越好 |
| WSS | < 40 | < 50 | < 60 | > 60 | ⬇️ 越低越好 |
| PESQ | > 3.0 | > 2.5 | > 2.0 | < 2.0 | ⬆️ 越高越好 |
| STOI | > 0.90 | > 0.85 | > 0.80 | < 0.80 | ⬆️ 越高越好 |

**參考文獻**:
```
Loizou, P. C. (2008).
"Evaluation of objective quality measures for speech enhancement."
IEEE Transactions on Audio, Speech, and Language Processing, 16(1), 229-238.
DOI: 10.1109/TASL.2007.911054
```

---

## 評估指標 (v1.4.0)

v1.4.0 新增基於 Loizou 2008 推薦的專業評估指標模塊。

### 傳統 segSNR 的問題

**問題**: 傳統 segSNR 與主觀質量相關性低 (r=0.40-0.46)

**原因**:
1. 包含靜音幀導致分數虛高
2. 未限制 SNR 範圍導致極端值
3. Global SNR 通常比 segSNR 高 7 dB

### Loizou 2008 改進方案

#### 1. segSNR with VAD

**改進**:
- ✅ 使用 VAD 排除靜音幀 (能量閾值 -40 dB)
- ✅ SNR 限制在 [-10, 35] dB 範圍
- ✅ 只計算有語音的幀

**實現**:
```python
from utils.metrics_loizou import segmental_snr

snr = segmental_snr(
    clean, enhanced,
    sample_rate=16000,
    use_vad=True,
    vad_threshold_db=-40.0,
    snr_clip_db=(-10.0, 35.0)
)
```

#### 2. fwSegSNR (Frequency-weighted)

**原理**: 對不同頻率賦予不同權重

**權重策略**:
- 300-3000 Hz: 權重 1.0 (語音主要能量)
- < 300 Hz: 權重 0.5
- \> 3000 Hz: 權重遞減 (0.3-1.0)

**優勢**: 更符合人耳感知特性

#### 3. WSS (Weighted-slope Spectral distance)

**原理**: 測量頻譜失真

**實現**:
- 25 個 Bark 頻帶
- 計算頻譜斜率差異
- 加權平均 (模擬臨界頻帶)

**值越小越好** (與 SNR 相反)

#### 4. Composite Measure

**綜合評估**:
```python
from utils.metrics_loizou import composite_measure

metrics = composite_measure(clean, enhanced, sample_rate=16000)
# 返回: {'segSNR': ..., 'fwSegSNR': ..., 'WSS': ..., 'global_SNR': ...}
```

### 使用示例

```python
from utils.metrics_loizou import (
    segmental_snr,
    frequency_weighted_segsnr,
    weighted_spectral_slope,
    composite_measure,
    print_metrics
)

# 單個指標
seg_snr = segmental_snr(clean, enhanced, sample_rate=16000)
print(f"segSNR: {seg_snr:.2f} dB")

# 綜合評估
metrics = composite_measure(clean, enhanced, sample_rate=16000)
print_metrics(metrics, title="V3-1 評估結果")
```

**輸出範例**:
```
==================================================
V3-1 評估結果
==================================================
segSNR         :  12.345 dB
fwSegSNR       :  13.678 dB
WSS            :   1.234 (越小越好)
global_SNR     :  19.456 dB
==================================================
```

### 參考文獻

Hu, Y., & Loizou, P. C. (2008). "Evaluation of objective quality measures for speech enhancement." IEEE Transactions on Audio, Speech, and Language Processing, 16(1), 229-238.

---

### V4: IMCRA-OMLSA（⚠️ 歷史章節，名稱衝突請先閱讀下方說明）

> **v4.2 注記**：本章標題所稱「V4 IMCRA-OMLSA」指 v1.5.0 時期的 IMCRA + OMLSA 組合。現行 v4.2 release 的 V4 模組（`denoisers/v4_omlsa.py`）為 **OMLSA + Wind Handler research 框架**，與此章描述不是同一個東西。
>
> 本章技術原理（IMCRA 偏移校正、OMLSA 對數域平滑）**仍是 V3-2 release 主線背後的設計基礎**，可讀；但**實作層面**以 [V3-2 MMSE-LSA (Log-Spectral Amplitude MMSE)](#v3-2-mmse-lsa) 章節為準。V3-2 的噪聲估計器 `noise_estimators/mcra.py`（`McraNoiseEstimator`）在 `accept_external_spp=True`（預設）下即為 IMCRA；AEC pipeline 設 `mcra_accept_external_spp=False` 改用 plain MCRA。

**v1.5.0 歷史優化紀錄**（對應當時的 V4 config）：
- 修復音量損失問題（8-10dB → 3-5dB）
- 添加混合策略減少過度抑制
- 添加幀間變化限制（±6dB max）防止震動
- 自適應 delta 調整（3-12dB）
- 歷史配置：[config/v4_config.yaml](config/v4_config.yaml:1)（v4.2 起此檔案改為 **OMLSA + Wind Handler research 框架**，預設 FLAT profile 等同 V3-2）

**技術原理**：結合先進的噪聲估計（IMCRA）和最優增益計算（OMLSA）

#### 兩大核心技術

##### 1. IMCRA（Improved Minima Controlled Recursive Averaging）

**最小值追蹤噪聲估計**：

```
流程：
1. 時間平滑：S_t(ω) = α_s · S_{t-1}(ω) + (1-α_s) · |Y_t(ω)|²
2. 最小值追蹤：維護滑動窗口（L=150幀 ≈ 1.5秒）
3. 計算最小值：S_min(ω) = min(S_{t-L:t}(ω))
4. SPP 引導更新：
   N_t(ω) = α_d · N_{t-1}(ω) + (1-α_d) · S_min(ω) · δ
```

**關鍵優勢**：
- 不依賴純噪聲段假設
- 持續追蹤噪聲變化
- SPP 引導避免誤更新

##### 2. OMLSA（Optimally Modified Log-Spectral Amplitude）

**對數域增益估計**：

```
工作域：對數譜幅度域（更符合人耳感知）

增益計算：
G(ω) = exp(E[log S(ω) | Y(ω)])

優勢：
- 小增益變化更平滑
- 大增益影響較小
- 更符合 Weber-Fechner 定律
```

#### 關鍵參數

| 參數 | 默認值 | 作用 |
|------|--------|------|
| alpha_s | 0.9 | 頻譜平滑因子 |
| alpha_d | 0.85 | 噪聲更新速率 |
| L | 150 幀 | 最小值窗口長度（1.5秒） |
| delta_db | 5 dB | 偏移補償 |
| alpha_g | 0.85 | 對數域增益平滑（v1.1.0 強化） |
| gamma_0 | 4.6 | SPP 閾值參數 |

#### 技術特點

- ✅ **產品級效果**：業界先進水平
- ✅ **噪聲追蹤準確**：最小值追蹤 + SPP 引導
- ✅ **Musical Noise 極少**：對數域平滑 + 時間平滑
- ✅ **語音保真度高**：最優估計 + 對數域處理
- ✅ **適應性強**：適用於各種噪聲環境
- ⚠️ **計算量較高**：RTF = 0.008（仍遠超實時）

#### 適用場景

- **高質量需求**：產品級語音處理
- 電話會議系統
- 專業錄音降噪
- 複雜噪聲環境
- 長時間處理（持續追蹤）

---

## 關鍵技術創新

### 1. Musical Noise 完全解決（v1.1.0）

**問題**：傳統降噪算法的頻譜增益在相鄰幀間劇烈跳變，產生"金屬震動聲"

**解決方案**：時間域增益平滑

```python
# V1/V2: 線性域平滑
G_t(ω) = α · G_{t-1}(ω) + (1-α) · G_t_current(ω)

# V3/V4: 對數域平滑（V4）
log G_t(ω) = α · log G_{t-1}(ω) + (1-α) · log G_t_current(ω)
```

**效果**：
- V1/V2：幀間變化減少 80%+
- V3/V4：幀間變化減少 20-30%（本身已較平滑）

### 2. 噪聲場景自適應機制（v2.7 Eta）⚠️ 已在 v4.1 棄用

> **⚠️ v4.1 重大更新**: 此機制已完全移除。
>
> **移除原因**:
> - L=5 優化已提供 50ms 快速場景適應（比 eta 更快且可靠）
> - 測試證明 eta 導致 PESQ 降低 0.06-0.41（test_wav 穩定噪聲）
> - eta 收益僅 0.006 PESQ（VCTK/DEMAND 非穩態噪聲），可忽略不計
> - 無法區分「語音開始」與「場景變化」，誤觸發率高
>
> **替代方案**: 使用 L=5 的最小值追蹤窗口（詳見 `MCRA_SCENE_CHANGE_ANALYSIS.md`）
>
> 以下內容僅供歷史參考：

**問題**：噪聲類型突變時（如從辦公室切換到街道），噪聲估計需要時間適應

**解決方案**：MCRA 內建 Eta 場景轉換偵測（平滑能量比 + hard threshold）

#### Eta 公式

```
1. 平滑能量:
   E_smooth(l) = 0.7 * E_smooth(l-1) + 0.3 * E_cur(l)
   E_cur(l) = sum(|Y(k,l)|^2)

2. 能量比:
   beta(l) = E_smooth(l) / E_smooth(l-1)

3. Hard threshold:
   eta(l) = 0.1   if beta(l) > theta   (場景突變，加速噪聲更新)
   eta(l) = 1.0   otherwise            (正常，不干擾 alpha_d)

4. 套用:
   alpha_d_tilde(k,l) = [alpha_d + (1-alpha_d) * p(k,l)] * eta(l)
```

**關鍵設計**：
- ✅ 0.7 平滑避免語音瞬態誤觸發
- ✅ Hard threshold（θ=10.0）：正常時 η=1.0 完全不干擾，只有真正場景變化時 η=0.1
- ✅ 純量運算，開銷極低

**v2.7 修正記錄**：
- 舊版 sigmoid `η = 0.95/(1+e^(slope*(β-θ)))` 上限 0.95，導致每幀語音 tilde_alpha_d 從 ~0.995 降至 ~0.945，噪聲更新速度增加 ~10x
- VCTK/DEMAND 824 files 驗證:
  - 舊 eta: PESQ +0.085, STOI -0.068
  - 新 eta: PESQ +0.399, STOI -0.010
  - 不開 eta: PESQ +0.437, STOI -0.007

### 3. Decision Directed 方法

**問題**：直接估計先驗 SNR 誤差大，導致 Musical Noise

**解決方案**（V3/V4）：結合當前幀和前一幀信息

```python
ξ_t = α_xi · [G²_{t-1} · γ_{t-1}] + (1-α_xi) · max(γ_t - 1, 0)
     \_____時間依賴項_____/         \_____即時估計項_____/
```

**優勢**：
- 減少估計方差
- 平滑 SNR 估計
- 有效抑制 Musical Noise

---

## 性能指標與對比

### 實時性能（39秒音頻 @ 16kHz）

| 版本 | 處理時間 | RTF | 狀態 |
|------|---------|-----|------|
| V1 頻譜減法 | 120 ms | 0.003 | ✓ 實時 |
| V2 Wiener | 126 ms | 0.003 | ✓ 實時 |
| V3 SPP-MMSE | 230 ms | 0.006 | ✓ 實時 |
| V4 IMCRA-OMLSA | 295 ms | 0.008 | ✓ 實時 |

**RTF (Real-Time Factor)**：處理時間 / 音頻時長
- RTF < 1.0：實時處理
- 本系統所有版本遠超實時標準

### 降噪效果（segSNR improvement）

| SNR 輸入 | V1 | V2 | V3 | V4 |
|---------|----|----|----|----|
| 0 dB | 8-10 dB | 9-11 dB | 11-13 dB | 12-15 dB |
| 5 dB | 7-9 dB | 8-10 dB | 10-12 dB | 11-14 dB |
| 10 dB | 6-8 dB | 7-9 dB | 9-11 dB | 10-13 dB |

**說明**：segSNR improvement 是主要評估指標，10+ dB 表示顯著改善

### 綜合對比（雷達圖）

| 維度 | V1 | V2 | V3 | V4 |
|------|----|----|----|----|
| 降噪效果 (0-10) | 5 | 6 | 8 | 9 |
| 計算效率 (0-10) | 10 | 9 | 7 | 5 |
| 語音質量 (0-10) | 6.5 | 7.5 | 8.5 | 9 |
| 實時性 (0-10) | 10 | 10 | 9 | 8 |
| Musical Noise 控制 (0-10) | 8 | 8 | 9 | 9.5 |

---

## 應用場景

### VoIP / 電話會議

**推薦版本**：V3 或 V4

**配置建議**：
```yaml
# V3 配置
spp:
  alpha_xi: 0.98  # 穩定估計
  q: 0.5
gain_calculation:
  g_min_db: -20.0
  alpha_g: 0.85
```

**優勢**：
- 實時處理（低延遲）
- 語音質量高
- Musical Noise 極少

### 錄音後處理

**推薦版本**：V4

**配置建議**：
```yaml
# V4 高質量配置
noise_estimation:
  alpha_s: 0.92
  alpha_d: 0.85
  L: 180  # 更長窗口，更準確
gain_calculation:
  g_min_db: -20.0
  alpha_g: 0.9  # 更平滑
```

**優勢**：
- 最佳音質
- 不受實時性限制
- 可配置更長追蹤窗口

### 移動設備 / 低功耗場景

**推薦版本**：V2

**配置建議**：
```yaml
# V2 輕量配置
noise_estimation:
  alpha: 0.95
  update_during_speech: false
gain_calculation:
  min_gain: 0.1
  alpha_smooth: 0.8
```

**優勢**：
- 計算量小
- 功耗低
- 效果可接受

### 動態噪聲環境

**推薦版本**：V3 或 V4

**優勢**：
- MCRA 雙視窗最小值追蹤自動適應噪聲變化
- 每 L 幀自動更新最小值
- 無需手動調整

---

## 技術優勢

### 相比深度學習方法

| 特性 | 傳統方法（本系統） | 深度學習 |
|------|-----------------|---------|
| **計算量** | 極低（RTF 0.003-0.008） | 較高（RTF 0.05-0.2） |
| **內存佔用** | 極小（< 1MB） | 較大（模型 5-50MB） |
| **延遲** | 極低（10-20ms） | 較高（30-100ms） |
| **可解釋性** | ✅ 完全可解釋 | ❌ 黑盒 |
| **可調性** | ✅ 豐富的參數 | ⚠️ 難以調整 |
| **穩定性** | ✅ 穩定可靠 | ⚠️ 可能失效 |
| **部署難度** | ✅ 簡單 | ⚠️ 需專門框架 |
| **降噪效果** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

### 本系統核心優勢

1. **實時性能卓越**
   - 所有版本 RTF < 0.01
   - 可在低功耗設備運行

2. **模塊化設計**
   - 清晰的架構
   - 易於理解和擴展
   - 可靈活替換組件

3. **參數化配置**
   - 豐富的 YAML 配置
   - 適應不同場景
   - 可快速調優

4. **完整的技術方案**
   - Musical Noise 已解決
   - 噪聲場景自適應（v1.3.0，Eta 已在 v4.1 由 L=5 優化替代）
   - 持續追蹤能力（V4）

5. **易於部署**
   - 純 Python 實現
   - 依賴簡單（numpy, scipy）
   - 可移植性強

6. **產品級質量**
   - V3/V4 適用於實際產品
   - 經過充分測試和優化
   - 詳細的文檔和支持

---

## 技術演進路線

```
V1: 頻譜減法（1979）
  ↓ 引入理論最優
V2: Wiener 濾波（1979）
  ↓ 引入軟判決
V3: MMSE-STSA（1984）
  ↓ 引入先進噪聲估計
V4: IMCRA-OMLSA（2001-2002）
  ↓ 持續優化
v1.1.0: Musical Noise 修復（2024）
  ↓ 智能適應
v1.3.0: 噪聲場景自適應（2026，Eta 機制）
  ↓ MMSE 學術實現
v1.4.0: MMSE 變體（V3-2/V3-3/V3-4）（2026）
  ↓ 整合與優化
v1.5.0: V3 整合、V4 優化、噪聲追蹤擴展（2026）
  ↓ 簡化與優化
v4.1.0: 移除 Eta 機制，L=5 優化替代（2026）
```

---

## 總結

本系統提供了一個**完整的、產品級的、實時語音降噪解決方案**：

- 🎯 **七個版本覆蓋不同需求**：V1-V4 基礎版本 + V3-2/V3-3/V3-4 MMSE 變體
- 🚀 **卓越的實時性能**：RTF 0.003-0.008，遠超實時標準
- 🎵 **Musical Noise 完全解決**：創新的時間平滑機制
- 🔄 **智能噪聲適應**（v1.3.0）：自動檢測並適應噪聲變化
- 📊 **優秀的降噪效果**：segSNR 改善 10-15 dB
- 🛠️ **靈活可配置**：豐富的參數適應不同場景
- 📖 **完整的文檔**：詳細的技術說明和使用指南

**推薦配置**：
- 一般應用：V3 SPP-MMSE
- 高質量需求：V4 IMCRA-OMLSA
- 低功耗設備：V2 Wiener
- 快速原型：V1 頻譜減法

---

**如需更多技術細節，請參考**：
- [README.md](README.md) - 完整項目文檔
- [CHANGELOG.md](CHANGELOG.md) - 版本更新記錄
- 代碼註釋 - 詳細的實現說明
