# Phase 6 參數調適完整指南

> **版本**: v2.1.0
> **日期**: 2026-01-05
> **適用**: V3-3 (PMMSE) Phase 6 配置

## 📋 目錄

1. [快速診斷流程圖](#快速診斷流程圖)
2. [參數詳解](#參數詳解)
3. [問題診斷與解決](#問題診斷與解決)
4. [案例研究](#案例研究)
5. [高級調參技巧](#高級調參技巧)
6. [性能優化建議](#性能優化建議)

---

## 快速診斷流程圖

```
開始降噪測試
    |
    ├──> 聽感檢查
    |      ├── 聽起來「悶」或「遠」? ──> 過度抑制 (見問題1)
    |      ├── 有金屬音/鳥叫聲? ──> Musical Noise (見問題2)
    |      ├── 開頭不清晰? ──> 收斂慢 (見問題3)
    |      └── 過渡段有切割? ──> 過渡延遲 (見問題4)
    |
    └──> 指標檢查
           ├── 振幅比 < 0.90? ──> 過度抑制 (見問題1)
           ├── PESQ Δ < 0? ──> 降噪失效 (檢查配置)
           ├── STOI Δ < -0.03? ──> 過度抑制 (見問題1)
           └── segSNR Δ > 1.0 dB? ──> Musical Noise (見問題2)
```

---

## 參數詳解

### 核心 Phase 6 參數分類

#### 1. SNR Adaptive 參數

**功能**: 根據 SNR 動態調整最小增益，防止過度抑制。

| 參數 | 推薦值 | 範圍 | 效果 |
|------|--------|------|------|
| `base_g_min_db` | **-10.0** | -15.0 ~ -8.0 | 最小增益基準 |
| `snr_smoothing` | 0.9 | 0.8 ~ 0.95 | SNR 平滑因子 |
| `clean_detection` | true | - | 檢測乾淨語音 |
| `clean_bypass` | false | - | 跳過乾淨語音處理 |

**調參指南**:
- **過度抑制**: `base_g_min_db` 提高 2dB (-12.0 → -10.0)
- **殘留噪聲**: `base_g_min_db` 降低 2dB (-10.0 → -12.0)
- **振幅比目標**: 0.95-1.05 (理想 1.0)

**實例**:
```yaml
snr_adaptive:
  base_g_min_db: -10.0    # V2 修正值
  # -15.0: 最小增益 3.2% (強烈抑制)
  # -12.0: 最小增益 6.3% (V1 值，過度抑制)
  # -10.0: 最小增益 10.0% (V2 值，平衡)
  # -8.0:  最小增益 15.8% (保守)
```

#### 2. Fast Startup 參數

**功能**: 前 50 幀使用快速參數加速收斂。

| 參數 | Natural | Balanced | Aggressive | 效果 |
|------|---------|----------|------------|------|
| `enable` | true | true | true | 啟用快速啟動 |
| `startup_frames` | 50 | 50 | 50 | 持續幀數 (500ms) |
| `alpha_noise_startup` | 0.7 | 0.7 | 0.6 | 噪聲估計平滑 |
| `alpha_xi_startup` | 0.7 | 0.7 | 0.6 | 先驗 SNR 平滑 |
| **`alpha_g_startup`** | **0.7** | **0.5** | **0.4** | **增益平滑 (關鍵)** |
| `num_init_frames_fast` | 10 | 10 | 5 | 快速初始化幀數 |

**調參指南**:
- **收斂太慢**: 降低 alpha (0.7 → 0.6)，減少 `num_init_frames_fast`
- **Musical Noise**: 提高 alpha (0.6 → 0.7)
- **過度抑制**: 提高 `alpha_g_startup` (0.4 → 0.5 → 0.6)

**alpha 值意義**:
- **Alpha 低** (0.4-0.6): 快速適應，但可能不穩定
- **Alpha 中** (0.7): 平衡速度與穩定性
- **Alpha 高** (0.8-0.95): 穩定但慢

#### 3. Transition Detection 參數

**功能**: 檢測噪音→語音過渡，觸發加速模式。

| 參數 | Natural | Balanced | Aggressive | 效果 |
|------|---------|----------|------------|------|
| `enable` | **false** | true | true | 啟用過渡檢測 |
| `spp_jump_threshold` | - | 0.2 | 0.15 | SPP 跳變閾值 |
| `confirm_frames` | - | 2 | 2 | 確認幀數 |
| `boost_duration` | - | 20 | 25 | 加速持續幀數 |
| `cooldown_frames` | - | 30 | 30 | 冷卻期幀數 |
| `avg_window` | - | 5 | 5 | 平均窗口 |
| `alpha_xi_boost` | - | 0.4 | 0.3 | 加速 xi 平滑 |
| **`alpha_g_boost`** | - | **0.5** | **0.4** | **加速增益平滑** |

**調參指南**:
- **過渡仍慢**: 降低 `spp_jump_threshold` (0.2 → 0.15)
- **誤觸發**: 提高 `spp_jump_threshold` (0.15 → 0.2)，增加 `confirm_frames`
- **過度抑制**: 提高 `alpha_g_boost` (0.4 → 0.5)

**工作流程**:
1. **IDLE**: 持續監測 SPP
2. **CONFIRMING**: SPP 跳變 > threshold，連續 `confirm_frames` 確認
3. **BOOSTING**: 觸發加速模式，持續 `boost_duration` 幀
4. **COOLDOWN**: 冷卻 `cooldown_frames` 幀，防止重複觸發

---

## 問題診斷與解決

### 問題 1: 過度抑制 (Over-suppression)

#### 症狀識別

**主觀**:
- 降噪後語音聽起來「悶」或「遠」
- 語音音量明顯比原始小
- 低頻能量損失

**客觀**:
- **振幅比 < 0.90** (最關鍵指標)
- STOI Δ < -0.02
- 波形振幅明顯縮小

**診斷方法**:
```python
import numpy as np
import soundfile as sf

# 讀取音頻
clean, sr = sf.read('clean.wav')
enhanced, sr = sf.read('enhanced.wav')

# 確保長度一致
min_len = min(len(clean), len(enhanced))
clean = clean[:min_len]
enhanced = enhanced[:min_len]

# 計算振幅比
clean_rms = np.sqrt(np.mean(clean**2))
enhanced_rms = np.sqrt(np.mean(enhanced**2))
amplitude_ratio = enhanced_rms / clean_rms

print(f"振幅比: {amplitude_ratio:.3f}")
print(f"能量損失: {(1 - amplitude_ratio) * 100:.1f}%")

# 判斷
if amplitude_ratio < 0.90:
    print("⚠️ 過度抑制!")
elif amplitude_ratio > 1.10:
    print("⚠️ 抑制不足!")
else:
    print("✅ 振幅比正常")
```

#### 解決方案

**Level 1: 提高最小增益** (最有效)

```yaml
snr_adaptive:
  base_g_min_db: -12.0 → -10.0    # 提高 2dB
```

**效果**:
- 最小增益: 6.3% → 10.0%
- 振幅比改善: 0.89 → 1.02
- 適用: 所有 Phase 6 配置

**Level 2: 增加增益平滑**

```yaml
fast_startup:
  alpha_g_startup: 0.4 → 0.5      # 增加平滑度

transition_detection:
  alpha_g_boost: 0.4 → 0.5        # 減少過渡抑制
```

**效果**:
- 減少瞬時過度抑制
- 更平滑的增益變化
- 適用: Balanced, Aggressive

**Level 3: 調整 SPP 權重** (謹慎)

```yaml
spp:
  q: 0.6 → 0.5                    # 降低 SPP 權重
```

**效果**:
- 減少 SPP 對增益的影響
- 可能增加殘留噪聲
- 僅當 Level 1+2 無效時使用

#### 案例: Balanced V1 → V2

**問題**:
- 振幅比: 0.893 (損失 10.7%)
- 聽感: 語音「悶」，缺乏能量

**修正**:
```yaml
# V1
snr_adaptive:
  base_g_min_db: -12.0
fast_startup:
  alpha_g_startup: 0.4
transition_detection:
  alpha_g_boost: 0.4

# V2
snr_adaptive:
  base_g_min_db: -10.0      # ✅ 提高 2dB
fast_startup:
  alpha_g_startup: 0.5      # ✅ 增加平滑
transition_detection:
  alpha_g_boost: 0.5        # ✅ 減少抑制
```

**結果**:
- 振幅比: 0.893 → 1.017 ✅
- PESQ Δ: +0.079 (保持改善)
- 聽感: 自然，能量充沛

---

### 問題 2: Musical Noise 過多

#### 症狀識別

**主觀**:
- 聽到金屬音、鳥叫聲等偽影
- 快速變化的「嘰嘰」聲
- 頻譜上隨機跳動

**客觀**:
- segSNR Δ > 1.0 dB (異常高)
- 頻譜圖有隨機亮點
- 能量方差大

#### 解決方案

**Level 1: 降低快速啟動激進度**

```yaml
fast_startup:
  alpha_noise_startup: 0.6 → 0.7
  alpha_xi_startup: 0.6 → 0.7
  alpha_g_startup: 0.3 → 0.4
```

**Level 2: 減少過渡檢測敏感度**

```yaml
transition_detection:
  spp_jump_threshold: 0.15 → 0.2   # 提高閾值
  boost_duration: 25 → 20          # 縮短持續
```

**Level 3: 增加穩態增益平滑**

```yaml
gain_calculation:
  alpha_g: 0.5 → 0.6               # 增加平滑
```

---

### 問題 3: 收斂仍然慢

#### 症狀識別

**主觀**:
- 開頭 0.5s 仍不清晰
- 語音「爬升」效應明顯

**客觀**:
- 開頭段 PESQ < 2.5
- SPP 上升緩慢 (>300ms)

#### 解決方案

**Level 1: 確認快速啟動已啟用**

```yaml
fast_startup:
  enable: true                     # 必須啟用
  startup_frames: 50
```

**Level 2: 減少初始化幀數**

```yaml
fast_startup:
  num_init_frames_fast: 20 → 10 → 5
```

**Level 3: 降低啟動 alpha** (謹慎)

```yaml
fast_startup:
  alpha_noise_startup: 0.7 → 0.6
  alpha_xi_startup: 0.7 → 0.6
```

⚠️ **警告**: 過低的 alpha 可能導致 musical noise

---

### 問題 4: 過渡仍有切割感

#### 症狀識別

**主觀**:
- car_10dB 類型噪音後語音恢復慢
- 語音開頭被「切掉」

**客觀**:
- SPP 跳變後 100+ms 才恢復
- 過渡段 PESQ 低

#### 解決方案

**Level 1: 確認過渡檢測已啟用**

```yaml
transition_detection:
  enable: true                     # 必須啟用
```

**Level 2: 降低檢測閾值**

```yaml
transition_detection:
  spp_jump_threshold: 0.2 → 0.15   # 更敏感
```

**Level 3: 延長加速持續**

```yaml
transition_detection:
  boost_duration: 20 → 25          # 延長持續
```

**Level 4: 降低加速 alpha** (謹慎)

```yaml
transition_detection:
  alpha_xi_boost: 0.4 → 0.3
  alpha_g_boost: 0.5 → 0.4
```

⚠️ **警告**: 過低可能導致 musical noise

---

## 案例研究

### 案例 1: Balanced V1 過度抑制修正

**背景**:
- 配置: Balanced V1
- 問題: 振幅比 0.893，語音「悶」

**診斷過程**:
```python
# 1. 計算振幅比
amplitude_ratio = 0.893  # < 0.90，過度抑制!

# 2. 檢查配置
base_g_min_db = -12.0           # 太激進
alpha_g_startup = 0.4           # 平滑不足
alpha_g_boost = 0.4             # 平滑不足
```

**修正策略**:
1. 提高 `base_g_min_db`: -12.0 → -10.0 (最關鍵)
2. 提高 `alpha_g_startup`: 0.4 → 0.5
3. 提高 `alpha_g_boost`: 0.4 → 0.5

**結果對比**:

| 指標 | V1 | V2 | 改善 |
|------|----|----|------|
| 振幅比 | 0.893 | 1.017 | +0.124 |
| PESQ Δ | +0.079 | +0.079 | 0 |
| STOI Δ | -0.0077 | -0.0077 | 0 |
| 聽感 | 悶 | 自然 | ✅ |

**經驗教訓**:
- `base_g_min_db` 是控制過度抑制的最關鍵參數
- -12.0 dB 對大多數場景太激進
- -10.0 dB 是更平衡的選擇
- 振幅比是診斷過度抑制的最佳指標

---

### 案例 2: Aggressive 配置優化

**背景**:
- 配置: Aggressive
- 目標: 最快收斂，可接受輕微 musical noise

**初始配置**:
```yaml
fast_startup:
  alpha_noise_startup: 0.6
  alpha_xi_startup: 0.6
  alpha_g_startup: 0.3          # 過低!

transition_detection:
  spp_jump_threshold: 0.15
  boost_duration: 25
  alpha_g_boost: 0.3            # 過低!
```

**問題**:
- 收斂快 (200ms)
- 但振幅比 0.87 (過度抑制)
- Musical noise 輕微

**修正**:
```yaml
# 保持激進的噪聲和 xi 參數
fast_startup:
  alpha_noise_startup: 0.6      # 保持
  alpha_xi_startup: 0.6         # 保持
  alpha_g_startup: 0.4          # ✅ 提高 (V2 修正)

transition_detection:
  spp_jump_threshold: 0.15      # 保持
  boost_duration: 25            # 保持
  alpha_g_boost: 0.4            # ✅ 提高 (V2 修正)

# 也提高最小增益
snr_adaptive:
  base_g_min_db: -10.0          # ✅ 統一修正
```

**結果**:
- 收斂: 200ms (保持)
- 振幅比: 0.87 → 1.02 ✅
- Musical noise: 輕微 → 可接受
- Trade-off: 最佳平衡

**經驗教訓**:
- Aggressive 不應犧牲振幅比
- alpha_g 是防止過度抑制的最後防線
- 0.4 是 Aggressive 的最低安全值

---

## 高級調參技巧

### 1. 漸進式調參法

**原則**: 每次只調一個參數類別，逐步逼近目標。

**流程**:
```
第1輪: 調整 base_g_min_db
  ↓ 檢查振幅比
第2輪: 調整 alpha_g_startup/boost
  ↓ 檢查振幅比 + PESQ
第3輪: 調整快速啟動 alpha
  ↓ 檢查收斂速度
第4輪: 調整過渡檢測閾值
  ↓ 檢查過渡延遲
第5輪: 微調與平衡
  ↓ 最終驗證
```

### 2. 振幅比優先策略

**理念**: 振幅比是最直觀的質量指標，優先保證 0.95-1.05。

**實踐**:
1. 先確保振幅比 ≥ 0.95
2. 再優化 PESQ/STOI
3. 最後平衡 musical noise

**原因**:
- 振幅比 < 0.95: 用戶立即感知質量差
- PESQ 略低: 用戶可能不察覺
- Musical noise: 場景相關，可容忍

### 3. A/B 測試法

**方法**: 準備多個配置，盲測對比。

**工具**:
```python
# test_ab_comparison.py
configs = [
    ('Original', 'v3_3_phase6_balanced.yaml'),
    ('Modified', 'v3_3_phase6_balanced_v2.yaml')
]

for name, config in configs:
    denoiser = PmmseDenoiser.from_config(config)
    enhanced = denoiser.denoise(noisy)
    save(f'output_{name}.wav', enhanced)

# 盲聽測試，記錄偏好
```

### 4. 場景自適應配置

**理念**: 不同場景使用不同配置。

**示例**:
```python
def select_config(noise_type, snr):
    if noise_type == 'babble' and snr < 10:
        return 'v3_3_phase6_aggressive.yaml'
    elif noise_type == 'white' and snr > 15:
        return 'v3_3_phase6_natural.yaml'
    else:
        return 'v3_3_phase6_balanced_v2.yaml'
```

---

## 性能優化建議

### 計算複雜度分析

**Phase 6 額外開銷**:
- Fast Startup: ~5% (前 50 幀)
- Transition Detection: ~2% (SPP 監測 + 狀態機)
- 總開銷: <10%

**優化建議**:
1. Disable transition detection for 乾淨語音
2. 使用 `clean_bypass` 跳過處理
3. 批處理多個文件共享配置

### 內存優化

**Phase 6 額外內存**:
- Transition Detector: ~1KB (狀態 + 歷史)
- 可忽略不計

### 實時性能

**RTF (Real-Time Factor)**:
- Baseline V3-3: 0.008
- Phase 6: 0.009 (<10% 增加)
- 仍遠優於實時要求 (RTF << 1.0)

---

## 總結與最佳實踐

### 關鍵參數優先級

1. **`base_g_min_db`**: 最關鍵，控制過度抑制
2. **`alpha_g_startup/boost`**: 次關鍵，控制平滑度
3. **`spp_jump_threshold`**: 控制過渡檢測敏感度
4. **其他 alpha**: 微調收斂速度

### 調參檢查清單

- [ ] 振幅比 0.95-1.05 ✅ (最重要)
- [ ] PESQ Δ > 0
- [ ] STOI Δ > -0.02
- [ ] segSNR Δ < 1.0 dB
- [ ] 主觀聽感自然
- [ ] 無明顯 musical noise
- [ ] 收斂時間 < 300ms
- [ ] 過渡延遲 < 100ms

### 推薦配置決策樹

```
開始
  |
  ├─ 通用場景? ──> Phase 6 Balanced V2 ⭐
  ├─ 高噪音環境? ──> Phase 6 Aggressive
  ├─ 穩定性優先? ──> Phase 6 Natural
  └─ 傳統需求? ──> V3-3 Balanced (Non-Phase6)
```

### 故障排除快速參考

| 問題 | 檢查 | 修正 |
|------|------|------|
| 聽起來「悶」 | 振幅比 < 0.90 | `base_g_min_db` +2dB |
| Musical noise | segSNR Δ > 1.0 | alpha 提高 0.1 |
| 開頭慢 | 收斂 > 300ms | `num_init_frames_fast` -5 |
| 過渡切割 | 過渡延遲 > 100ms | `spp_jump_threshold` -0.05 |

---

**Document Version**: 1.0
**Last Updated**: 2026-01-05
**Maintainer**: Claude Sonnet 4.5
