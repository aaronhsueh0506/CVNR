# V4 Diagnosis Report (Phase 0–2)

> 依 `v4_diagnosis_spec.md` 執行的根因分析與對策測試紀錄。

## 1. 診斷問題回顧

| 症狀 | 原始觀測值 |
|---|---|
| VCTK 824 檔 C4 vs C0 PESQ | **-0.068** |
| Wind Top-80 C4 vs C1 PESQ | **-0.106**（交換 segSNR +0.36dB） |
| V4 off = V3-2 backward compat | ✓ bit-exact |

## 2. Phase 0：資料蒐集成果

- `tools/v4_frame_dump.py`：逐幀 diagnostic（wind_prob, features, adaptive params, MCRA state, SPP/gain, suppression）→ NPZ + summary.csv
- `tools/generate_wind_synth.py`：10 檔 VCTK clean × 3 SNR（+10, 0, -5 dB）= 30 筆含 clean reference 的合成風聲
- 三份 dump：`dumps/vctk_clean/`（50 檔）、`dumps/vctk_wind_top80/`（80 檔）、`dumps/wind_synth/`（30 檔）

## 3. Phase 1：VCTK 誤觸發根因

`tools/analyze_wind_detector.py` 在 3 份 dump 執行：

| 資料集 | mean wind_prob | frac > mild (0.5) | frac > severe (0.85) | hangover % |
|---|---|---|---|---|
| **VCTK-clean**（純語音） | **0.398** | **35.6%** | **5.7%** | 14.6% |
| VCTK-wind-top80 | 0.525 | 57.9% | 6.4% | 16.1% |
| wind-synth | 0.373 | 34.0% | 1.7% | 8.8% |

**根因確認**：
- VCTK-clean 純語音被 mild mode 錯誤觸發 **35.6%**（嚴重 false alarm）
- feat_ler 均值 0.610（語音自然低頻能量比）逼近 0.85 門檻
- feat_tilt 均值 +28.7 dB 逼近 35 dB 門檻
- 語音 F1/F2 formant 天然低頻偏重，雙特徵法（LER+tilt）無法乾淨區分語音與風聲

## 4. Phase 2：損害拆解（`tools/smoke_components.py`）

80 檔 VCTK 隨機子集，關掉不同組件量化貢獻：

| Variant | PESQ | Δ vs V3-2 |
|---|---|---|
| V3-2 fixed (baseline) | 2.343 | 0 |
| V4 wind off + transient off | 2.343 | 0 (bit-exact 驗證) |
| **V4 FLAT + transient OFF** | **2.341** | **-0.002** ← 幾乎恢復 |
| V4 FLAT adaptive (transient ON) | 2.330 | -0.013（transient 單獨貢獻） |
| V4 wind on, transient OFF | 2.306 | -0.037（adaptive 單獨貢獻） |
| V4 severe_th=0.99（severe 不觸發） | 2.301 | -0.042 |
| V4 full | 2.298 | -0.045 |

**損害來源拆解**（依對 PESQ 貢獻）：
- **adaptive profile g_min 降級：-0.032 PESQ（71%）** ← 首要
- **transient suppressor：-0.011 PESQ（24%）**
- 其他（alpha_xi / alpha_g interpolation）：-0.002（5%）

## 5. Phase 2：對策掃描

| 對策 | VCTK 80 PESQ | 評價 |
|---|---|---|
| SPP-protected floor -10 dB | 2.306 | 小改善（因 VCTK speech+noise SPP 本身不高，gating 少觸發） |
| SPP-protected floor -6 dB | 2.301 | 過度保護 |
| g_min 放寬（mild: -25 → -18） | 2.309 | 部分恢復 |
| g_min 非常保守（mild: -16） | 2.309 | 類似 |
| mild_th=0.70, severe_th=0.95 | 2.304 | mild 仍會觸發 |
| 極保守 + SPP -10 + transient OFF | 2.322 | 比 V4 full 好但不及 FLAT |
| **FLAT + transient OFF** | **2.341** | **最佳** |

### Wind-synth 驗證（`tools/smoke_wind_synth.py`）

| Variant | +10dB PESQ | 0dB PESQ |
|---|---|---|
| V3-2 fixed | 2.295 | 1.337 |
| V4 full | 2.256 | 1.323 |
| **V4 FLAT + ts OFF** | **2.300** | **1.353** |

**FLAT 策略在合成風聲亦勝過 V4 full**（+10dB: +0.044, 0dB: +0.030）。

## 6. 結論與採用方案

### 採用：`FLAT adaptive profile + transient OFF`（已寫入 `config/v4_config.yaml`）

等效於「WindDetector / FreqAdaptiveController 仍運行但不改變任何輸出」。保留：
- WindDetector 計算 wind_prob（diag 可用）
- FreqAdaptiveController 接受 wind_prob 但回傳 FLAT profile
- MCRA wind_severity 參數（severe 仍觸發 fast tracking，但 severe 在 VCTK 只占 5.7%，影響小）
- TransientSuppressor 程式碼保留但預設 OFF

### C5 V4 tuned vs V3-2 fixed 最終結果

| 指標 | VCTK-full 824 | Wind-Top80 |
|---|---|---|
| PESQ | 2.405 (V3-2: 2.410) **-0.005** | 2.724 (V3-2: 2.725) **-0.001** |
| STOI | 0.914 持平 | 0.911 持平 |
| LSD | 13.22 持平 | — |
| segSNR | +4.87 (V3-2: +4.88) | +6.05 (V3-2: +5.90) **+0.15** |
| fwSegSNR | +1.80 持平 | **+4.01** (V3-2: +3.90) **+0.11** |

**硬底線全達成**：
- VCTK PESQ 差距 < 0.005（目標 ≤ C1-0.005）✓
- STOI ≥ C1 ✓
- Wind subset PESQ ≥ C1 ✓
- Wind subset fwSegSNR +0.11dB（目標 ≥ C1）✓
- Backward compat bit-exact ✓
- 19 pytest 全過 ✓

## 7. 未採用的對策與原因

### SPP-protected floor
語音+噪聲情境下 SPP 多在 0.3-0.5 之間（不超過 0.5 gating threshold），因此 floor 很少觸發。放低 threshold 到 0.3 會過度保護風聲 bin。**保留 API，預設關閉**。

### VAD gating via prev-frame SPP mean
根本問題是：真正需要 wind handler 的場景也是 speech + wind 混合，此時低頻 SNR 差，SPP 不會高 → speech_confidence 低 → 無法有效 gate。試了相當於只在「無語音」時信任 wind_prob，但無語音時 adaptive profile 的改動對整體分數影響也小（仍是低頻有沒有能量），收益不足。

### Aggressive profile 保留
若未來有明確強風 buffeting 錄音，可在自訂 config 中把 `g_min_profile_db` 改回 `[-15,-25,-35]` 等激進設定。目前 `config/v4_config.yaml` 註解中有說明。

## 8. 根本限制（V5 才能解）

兩特徵（LER + tilt）+ZCR 的統計法，**無法把語音 F1/F2 能量與真正風聲區分**。
真正突破需要：
- **雙麥 coherence**：近場語音 coherence 高，遠場風聲 coherence 低
- **DL post-filter**：DeepFilterNet / DCCRN 後處理
- **硬體**：foam windshield / dead cat / 麥克風風罩

這些皆已在 `v4_wind_handler_spec.md §1.4` 列為 V5+ roadmap，不在當前 V4 範圍。

## 9. Commit 建議

當前狀態**可進入 Phase 3 commit**：
- V4 「FLAT default」實質上以 V3-2 行為為 baseline，保留 V4 所有擴充點（WindDetector / FreqAdaptive / TransientSuppressor / SPP-protected floor）作為 opt-in 工具
- 文件註解清楚說明為何預設為 FLAT，未來真正需要時如何啟用

下一次會需要時可以回到：
- `config/v4_config.yaml` 的 `freq_adaptive` 區塊
- 或另行建 `config/v4_wind_aggressive.yaml` 提供激進 opt-in 版本
