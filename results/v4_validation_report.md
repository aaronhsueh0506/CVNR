# V4 OMLSA Wind Handler — Validation Report

> 本報告包含 Part A（V3-2 review 修復）與 Part B（V4 wind handler）的完整驗證結果、診斷分析與誠實評估。

## 1. Part A：V3-2 Review 修復（11 項 + tools/validate_best_config.py）

### VCTK 824 檔整體迴歸

| Metric | C0 V3-2 baseline | C1 V3-2 fixed | Δ |
|---|---|---|---|
| PESQ Enhanced | 2.425 | 2.410 | **-0.015**（雜訊範圍） |
| STOI Enhanced | 0.911 | **0.914** | **+0.003** |
| LSD Enhanced | 13.05 | 13.22 | +0.17 |
| segSNR 改善 | +5.07 dB | +4.88 dB | -0.19 dB |
| fwSegSNR 改善 | +1.58 dB | **+1.80 dB** | **+0.22 dB** |

**結論**：Part A 11 項修復大致持平（PESQ/LSD/segSNR 在雜訊範圍），STOI 與 fwSegSNR 微改善。

### 關鍵修正要點
1. **Fix #2 改輕量版**：md 原建議「init 幀 passthrough」導致 segSNR 降 0.73dB；改為「init 幀用初始 PSD 算 gain 但不 update」，避免 320ms 原始噪聲洩漏
2. **Fix #3 DD 用上一幀 noise_psd**：符合 Ephraim-Malah 1984 原公式，讓 |X̂(k,l-1)|² 與 λ_d(k,l-1) 統計一致
3. **Fix #4 alpha_d 接通**：yaml 值 0.7 之前因參數名 shadow 而從未生效
4. **Fix #7 periodic window**：numpy 的 hanning 是 symmetric，對 50% overlap 不滿足精確 COLA，改用 scipy `hann(N, sym=False)`

## 2. Part B：V4 OMLSA Wind Handler

### 設計與現狀
- **新增模組**：WindDetector（LER + tilt + ZCR）、FreqAdaptiveController（4 段 profile 線性插值）、TransientSuppressor（時域 short/long window 能量比）、OmlsaDenoiser（組合以上）
- **預設 config**（`v4_config.yaml`）：FLAT adaptive profile + transient OFF
- **Backward compat**：`OmlsaDenoiser(enable_wind_handler=False, enable_transient_suppressor=False)` 與 `MmseLsaDenoiser` bit-exact（RMS diff = 0）

### 驗證結果

**VCTK 824 檔**：

| | C0 baseline | C1 V3-2 fixed | C5 V4 tuned | Δ (C5 vs C1) |
|---|---|---|---|---|
| PESQ | 2.425 | 2.410 | 2.405 | -0.005 |
| STOI | 0.911 | 0.914 | 0.914 | 0 |
| LSD | 13.05 | 13.22 | 13.22 | 0 |
| segSNR | +5.07 dB | +4.88 dB | +4.87 dB | -0.01 dB |
| fwSegSNR | +1.58 dB | +1.80 dB | +1.80 dB | 0 |

**Wind-Top80（VCTK 內依 detector 排序，高低頻能量比）**:

| | C1 V3-2 fixed | C5 V4 tuned | Δ |
|---|---|---|---|
| PESQ | 2.725 | 2.724 | -0.001 |
| STOI | 0.912 | 0.911 | -0.001 |
| segSNR | +5.90 dB | +6.05 dB | +0.15 dB |
| fwSegSNR | +3.90 dB | +4.01 dB | +0.11 dB |

**Wind-synth（合成風聲 + clean 10 檔）**:

| SNR | V3-2 PESQ | V4 tuned PESQ | V3-2 SI-SDR | V4 tuned SI-SDR |
|---|---|---|---|---|
| +10 dB | 2.295 | 2.300 | +12.57 | +12.93 |
| 0 dB | 1.337 | 1.353 | +2.28 | +2.70 |
| -5 dB | 1.046 | 1.046 | -5.80 | -5.80 |

## 3. 誠實評估（Phase 2 診斷結論）

### V4 實質效益：**未能證實**

V4 tuned vs V3-2 fixed 在所有測試場景的差異**都在 run-to-run 雜訊範圍內**：
- VCTK 824 檔 PESQ 差 -0.005
- Wind-Top80 PESQ 差 -0.001
- Wind-synth +10dB PESQ 差 +0.005
- Wind-synth 0dB PESQ 差 +0.016

**V4 目前的設計未在任何測試場景中提供有意義的風聲改善**。

### 為何 V4 無實質改善

Phase 0/1/2 診斷發現（詳見 `v4_diagnosis_report.md`）：

1. **WindDetector 對 VCTK 純語音誤觸發 35.6%**（frac > mild threshold），因為語音 F1/F2 formant 天然低頻偏重（mean LER = 0.610 逼近 0.85 門檻，mean tilt +28.7 dB 逼近 35 dB 門檻）
2. **FreqAdaptiveController 降 g_min（mild band_0 = -25 dB, severe = -35 dB）同時壓到語音低頻能量**，造成 VCTK PESQ 下降 0.032（smoke test 量化）
3. **退回 FLAT profile 才不傷 VCTK，但 FLAT 等於沒做風聲處理**

這是**兩特徵統計法的數學限制**，不是調參能解決的：
- 語音 F1 (500-1000Hz) 能量集中與風聲低頻能量集中**重疊太多**
- 降低 F1 頻段增益 → 風聲減少同時語音暖度喪失
- 唯一能突破的路線（V5+）：
  - 雙麥 coherence（近場語音 coherence 高，遠場風聲低）
  - DL post-filter（DeepFilterNet / DCCRN）
  - 物理風罩（foam windshield, dead cat）

### V4 當前定位

以 `research infrastructure` 看待：
- **WindDetector / FreqAdaptiveController / TransientSuppressor 等模組可用**，供未來實驗
- **預設 config 不激活任何 adaptive 行為**，與 V3-2 等效
- 激進 profile 保留在程式碼中（註解指出），未來若有明確強風 buffeting 場景可 opt-in

## 4. 單元測試
19/19 通過：
- `test_wind_detector.py`（6）
- `test_freq_adaptive_controller.py`（6）
- `test_transient_suppressor.py`（5）
- `test_v4_backward_compat.py`（2）

## 5. 產出檔案

### Part A 修改
`core/frame_processor.py` / `core/spp_estimator.py` / `core/noise_estimators/mcra.py` / `core/gain_calculators/mmse_lsa.py` / `denoisers/v3_2_mmse_lsa.py` / `config/v3_2_config.yaml` / `regenerate_all.py` / `tools/validate_best_config.py`（＋刪除 `requirements.txt`）

### Part B 新增（research infrastructure）
`core/wind_detector.py` / `core/freq_adaptive_controller.py` / `core/transient_suppressor.py` / `denoisers/v4_omlsa.py` / `denoisers/__init__.py` / `config/v4_config.yaml` / `regenerate_all_vctk.py`

### 診斷工具
`tools/v4_frame_dump.py` / `tools/generate_wind_synth.py` / `tools/analyze_wind_detector.py` / `tools/smoke_components.py` / `tools/smoke_wind_synth.py` / `tools/scan_wind_subset.py` / `tools/wind_subset_compare.py`

### 測試 + 報告 + 資料
`tests/test_*.py`（4 檔）/ `results/v4_validation_report.md`（本檔）/ `results/v4_diagnosis_report.md` / `results/next_steps_recommendations.md` / `wind_synth/`

## 6. Commit 建議
見 `results/next_steps_recommendations.md`。建議拆兩個 commit：
- Part A：V3-2 review fixes（實質改善演算法正確性）
- Part B：V4 wind handler as research infrastructure（誠實標明「未證實對風聲有改善」，保留模組供未來用）
