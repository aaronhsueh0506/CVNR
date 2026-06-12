# Commit 策略 + 後續工作建議

> 依最終驗證（含 Phase 0/1/2 診斷）結果提供建議。

## 狀態摘要

- **Part A（V3-2 review 修復）**：有實質改善，VCTK STOI +0.003 / fwSegSNR +0.22dB
- **Part B（V4 wind handler）**：**未證實對風聲有改善**。V4 tuned 與 V3-2 fixed 在 VCTK 824、Wind-Top80、Wind-synth 三個測試集的差異都在 run-to-run 雜訊範圍內。當前 V4 config 已 tune 成「FLAT profile + transient OFF」，實質等效於 V3-2 加上一層未激活的 framework
- Backward compat bit-exact ✓、19 pytest 通過 ✓

## Commit 建議：拆兩個 commit

### Commit 1 — Part A: V3-2 review fixes

```
fix(v3-2): apply OMLSA review fixes (11 items) + lightweight init passthrough

Algorithm correctness:
- Fix #1 MCRA init consistency (S=S_min=P30, avoid first-frame ratio anomaly)
- Fix #3 SPP DD uses previous-frame noise PSD (Ephraim-Malah 1984)
- Fix #7 periodic window for exact COLA (numpy sym=False via scipy)
- Fix #9 clip q to (eps, 1-eps) prevent edge collapse

Interface / parameter fixes:
- Fix #4 connect alpha_d from yaml (was shadowed by alpha_noise default)
- Fix #5 expose asymmetric smoothing (attack/decay) through denoiser
- Fix #6 parameterize scene_change flatness threshold

Init & state handling:
- Fix #2 lightweight: init frames use initial PSD to compute gain without
  re-calling noise update (avoids double-count and the 320ms passthrough
  regression of a strict passthrough implementation)
- Fix #8 auto reset at denoise_spectrum entry

Cleanup:
- Fix #10/#11 comments and __main__ test code
- tools/validate_best_config.py: pass enhanced_psd_prev so DD assert holds

VCTK 824 files regression vs baseline:
  PESQ    2.425 -> 2.410 (-0.015, within run-to-run noise)
  STOI    0.911 -> 0.914 (+0.003)
  LSD     13.05 -> 13.22 (+0.17)
  segSNR  +5.07 -> +4.88 dB
  fwSegSNR +1.58 -> +1.80 dB (+0.22)

Delete requirements.txt per maintainer direction.
```

**涉及檔（修改）**：
- `core/frame_processor.py`（#7）
- `core/spp_estimator.py`（#3, #9）
- `core/noise_estimators/mcra.py`（#1, #6）
- `core/gain_calculators/mmse_lsa.py`（#11 `__main__`）
- `denoisers/v3_2_mmse_lsa.py`（#2, #4, #5, #8, #10）
- `config/v3_2_config.yaml`（#6）
- `regenerate_all.py`（#4 的 yaml loader）
- `tools/validate_best_config.py`（#3 連帶）
- `requirements.txt`（刪除）

### Commit 2 — Part B: V4 OMLSA wind handler (research infrastructure)

```
feat(v4): add OmlsaDenoiser with wind handler framework (research infrastructure)

WARNING: V4 wind handler does NOT demonstrate measurable wind-noise
improvement in controlled evaluation. Shipped as research infrastructure
with all adaptive behavior disabled by default; kept for future work on
multi-mic coherence or DL post-filter approaches.

New modules:
- core/wind_detector.py       — LER + spectral tilt + ZCR features
- core/freq_adaptive_controller.py — 4-band profile with linear interpolation
- core/transient_suppressor.py — time-domain short/long window energy ratio
- denoisers/v4_omlsa.py       — OmlsaDenoiser composing existing V3-2 components

Core API extensions (backward-compat, no impact when overrides are None):
- SppEstimator.estimate(): alpha_override for per-bin adaptive alpha_xi
- MmseLsaGainCalculator.calculate(): g_min array support +
  alpha_g/attack/decay overrides + SPP-protected floor
- McraNoiseEstimator.update(): wind_severity parameter for fast tracking
  (only applies in 'severe' mode)

Default config (config/v4_config.yaml):
- WindDetector / FreqAdaptiveController ENABLED but profile is FLAT
  (all severity levels use normal g_min/alpha_xi/alpha_g — no adaptive
  suppression). Equivalent to V3-2 behavior with dormant framework.
- TransientSuppressor DISABLED by default.
- Backward-compat: enable_wind_handler=False + enable_transient_suppressor=False
  produces bit-exact output vs MmseLsaDenoiser (verified by unit test).

Why FLAT default (see results/v4_diagnosis_report.md for full analysis):
- Phase 0 dump: WindDetector false-alarms 35.6% of VCTK-clean speech frames
  because speech F1/F2 formants naturally dominate low-freq (mean LER=0.61
  close to 0.85 threshold; mean tilt=+28.7dB close to 35dB threshold).
- Phase 2 smoke: aggressive profile (mild band_0 -25dB, severe -35dB)
  over-suppresses speech low-freq, costing -0.032 PESQ on VCTK.
- FLAT profile recovers VCTK to within -0.005 of V3-2; aggressive profile
  + wind_synth improvement is within run-to-run noise, so the trade-off
  does not pay off.
- Root cause is the mathematical overlap of speech F1 energy and wind
  low-freq energy under a single-mic statistical detector. Requires
  dual-mic coherence or DL post-filter to resolve (future V5 work).

Validation (full results in results/v4_validation_report.md):
  VCTK 824 files: PESQ 2.405 vs V3-2 2.410 (-0.005)
                  STOI 0.914 (tied)
                  fwSegSNR +1.80 dB (tied)
  Wind-Top80:     PESQ 2.724 vs V3-2 2.725 (-0.001)
                  fwSegSNR +4.01 dB vs +3.90 (+0.11)
  Backward compat: V4 off == V3-2 bit-exact
  19/19 pytest unit tests pass

Includes diagnostic tooling under tools/:
  v4_frame_dump.py, generate_wind_synth.py, analyze_wind_detector.py,
  smoke_components.py, smoke_wind_synth.py, scan_wind_subset.py,
  wind_subset_compare.py
And synthesized wind dataset under wind_synth/ (10 clean x 3 SNR).
```

**涉及檔（新增）**：
- `core/wind_detector.py`
- `core/freq_adaptive_controller.py`
- `core/transient_suppressor.py`
- `denoisers/v4_omlsa.py`
- `denoisers/__init__.py`（加 `OmlsaDenoiser` export）
- `config/v4_config.yaml`
- `regenerate_all_vctk.py`（加載 v4 config）
- `tools/v4_frame_dump.py`
- `tools/generate_wind_synth.py`
- `tools/analyze_wind_detector.py`
- `tools/smoke_components.py`
- `tools/smoke_wind_synth.py`
- `tools/scan_wind_subset.py`
- `tools/wind_subset_compare.py`
- `tests/test_wind_detector.py`
- `tests/test_freq_adaptive_controller.py`
- `tests/test_transient_suppressor.py`
- `tests/test_v4_backward_compat.py`
- `results/v4_validation_report.md`
- `results/v4_diagnosis_report.md`
- `results/next_steps_recommendations.md`（本檔）

**涉及檔（修改）**：
- `core/spp_estimator.py`（`alpha_override` 參數）
- `core/gain_calculators/mmse_lsa.py`（`g_min` array + override + SPP floor）

## 同步到 main

Part A 在 `feature/static-memory` commit 後：
```bash
git checkout main
git cherry-pick <partA_sha>   # Part A 不涉及 static memory
# 若有衝突，static-memory 分支特有的 API 已經分離
```

Part B 同樣可以 cherry-pick 到 main（沒有 static memory 依賴）。

## 未來工作（Part D — C 實作 + 風聲方向）

### Part D：C 實作（現階段 user 指示暫緩）

**應該等 Python 凍結才做**。Part A 的 Fix 清單可直接翻到 C：

- `c_impl/src/spp_estimator.c/.h` — Fix #3 / #9 / alpha_override
- `c_impl/src/mmse_lsa_denoiser.c` — Fix #1/#2/#4/#5/#6/#8
- `c_impl/src/mcra_noise_estimator.c` — #1/#6 + wind_severity
- 雙 branch 同步：`main` (malloc) 與 `feature/static-memory`（加 `_get_mem_size` / `_init`）

V4 module 的 C port **可以延後甚至不做**（因為當前 wind handler 無實質效益，且 FLAT profile 等效於不做）。

**Bit-exact 對齊策略**（依診斷 spec）：
- L1：max abs diff < 1e-5（模組級）
- L2：RMS diff < 1e-4（pipeline）
- L3：PESQ 差 < 0.01（perceptual）
- `-ffp-contract=off`、不要 `-ffast-math`、E1 必須用可移植的三段近似（不依賴 scipy）
- 生成 golden vectors：`tools/generate_golden_vectors.py`（未來工作）

### 風聲方向（真正改善）

**單 mic 統計法已到極限**，要真正改善需要：
1. **雙 mic coherence**：最有效，預期 10-20dB 風聲衰減
2. **DL post-filter**（DeepFilterNet / DCCRN）：可能 1-2 週串起離線評估
3. **硬體（風罩）**：foam 5-15dB、dead cat 10-25dB —— 這是最 CP 的解

三個方向已列在 `v4_wind_handler_spec.md §1.4`。

## 使用指南（Part A + B 合併後）

### V3-2 只跑乾淨降噪（推薦用於室內）
```bash
python3 regenerate_all_vctk.py --config config/v3_2_config.yaml --dataset-dir <path> --output-dir out
```

### V4（預設 = V3-2 行為）
```bash
python3 regenerate_all_vctk.py --config config/v4_config.yaml --dataset-dir <path> --output-dir out
```

### V4 + 激進風聲處理（opt-in，可能傷 PESQ 換 segSNR）
編輯 `config/v4_config.yaml`，把 `wind_handler.freq_adaptive.g_min_profile_db` 的 `band_0/1/2` 三個位置的 mild/severe 值改回原激進值（見註解）。

### 診斷特定檔案
```bash
python3 tools/v4_frame_dump.py --input-dir <dir> --config config/v4_config.yaml --output-dir dumps/my_diag
python3 tools/analyze_wind_detector.py dumps/my_diag/summary.csv
```

### 合成風聲測試資料
```bash
python3 tools/generate_wind_synth.py \\
    --clean-dir /path/VCTK_DEMAND_testset/clean_testset_wav \\
    --output-dir my_wind_synth \\
    --n-files 20 --snrs 10 0 -5
```

## 誠實總結

**做對的事**：
- Part A 11 項修復提升演算法正確性
- V4 框架可擴充（override API 不破壞 V3-2 行為）
- Phase 0–2 診斷流程建立可重用工具鏈
- 19 pytest + 合成風聲資料集 + 逐幀 diagnostic tool

**沒做到的事**：
- V4 wind handler 在當前實測場景下**未提供統計顯著的風聲改善**
- 原始 md spec 的激進 adaptive profile 被證實對語音有害
- 單 mic 統計法遇到 F1/F2 能量重疊的數學限制

**為什麼仍值得 commit**：
- 修好的 V3-2 本身是 net positive
- V4 infrastructure + 診斷工具為後續雙麥 coherence / DL post-filter 奠基
- Honest documentation 讓未來 user 知道什麼有效、什麼沒效
