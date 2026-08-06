# Part A — C 實作計劃（歷史封存）

> 此計畫對應的修改已完成；內容只保留作為設計決策紀錄，不是目前的
> build、API 或驗證說明。現行使用方式請見根目錄 README 與
> `docs/c_user_manual_zh_TW.md`。

> 對 Python Part A（commit `7bcdef1`）的 C 端 port。先確認範圍，user 核可後才動。

## 現況 audit（c_impl/ 已閱讀）

| Fix | Python 改動 | C 現況 | 要不要動 |
|---|---|---|---|
| **#1** MCRA init `S = init_psd` | ✓ | `mcra_noise_estimator.c` `mcra_init_noise()`：`S = avg_power`，與 `S_min = init_psd` 不一致 | ✅ **要改**（兩條 code path：`USE_FAST_PERCENTILE` 與 exact quickselect） |
| **#3** SPP DD 用上一幀 noise_psd | ✓ | `spp_estimator.c`：`xi_dd_term1 = enhanced_psd_prev[k] / noise_psd[k]` 用的是 **當前幀** noise_psd | ✅ **要改**（需加 `noise_psd_prev` state 欄位 + 每幀尾端 memcpy 保存） |
| **#6** flatness 閾值參數化 | ✓ | `mcra_noise_estimator.c:443` 硬編 `hi_flatness > 0.4f` | ✅ **要改**（加 config 欄位 + struct 欄位 + 讀取） |
| **#9** q clip | ✓ | `spp_create()`：`prior_ratio = (1-q)/(q + 1e-10f)` 只有 `+eps` 保護，沒有 clip q 本身 | ✅ **要改**（clip q 到 `(eps, 1-eps)` 後再算 prior_ratio） |
| **#7** periodic window | `sym=False` | `create_sqrt_hann_window()` 已用 `cosf(2π·i/N)`（periodic 公式） | ✅ **已正確**，不動 |
| **#5** asymmetric smoothing 外露 | `alpha_attack/decay` 透傳 | `MmseLsaConfig` 已有 `alpha_attack`、`alpha_decay`，`calculate_gain()` 也已實作 | ✅ **已有**，不動 |
| **#4** alpha_d 接通 | Python loader 修 shadow bug | C 直接從 config 讀 `alpha_d`，無 shadow 問題 | ❌ **N/A** |
| **#2** init 輕量 passthrough | Python 循環內切分 | C streaming 本就在 init 階段 passthrough（`gain=1`）然後 `mcra_init_noise()` 一次 init。streaming 天然無法「回頭用最終 PSD 重算前 N 幀」 | ⚠ **語義差異**，C 保留 streaming 行為 |
| **#8** auto reset | `denoise_spectrum()` 入口 reset | C 是 streaming API，每次呼叫不能 reset 掉狀態。caller 自己控制 `mmse_lsa_reset()` | ❌ **N/A** |
| **#10/#11** cleanup | Python 註解 / `__main__` | - | ❌ **N/A** |

**結論**：C 端只需動 **4 個 fix**（#1, #3, #6, #9），都是小改動，不觸及架構。

## 要改的檔案（兩個 branch 都要）

| 檔案 | 變更 | 觸及函式 |
|---|---|---|
| `c_impl/include/mmse_lsa_types.h` | 加 `scene_change_flatness_threshold` 欄位 + 預設 0.4f | `MmseLsaConfig`, `mmse_lsa_default_config()`, `mmse_lsa_config_for_mode()` |
| `c_impl/src/mcra_noise_estimator.c` | Fix #1：`mcra_init_noise()` 中 `S=init_psd`（兩條 code path）<br>Fix #6：讀取 config 的 flatness threshold 存入 struct，用於 line 443 | `struct McraNoiseEstimator`, `mcra_create()`, `mcra_init_noise()`, `mcra_update()` |
| `c_impl/src/spp_estimator.c` | Fix #3：加 `noise_psd_prev` state 欄位<br>Fix #9：在 `spp_create()` 中 clip q | `struct SppEstimator`, `spp_create()`, `spp_estimate()`, `spp_estimate_ex()`, `spp_reset()`, `spp_destroy()` |

## 具體改動草稿

### 1. `mmse_lsa_types.h`

```c
// 加到 MmseLsaConfig
float scene_change_flatness_threshold;  // Hi-freq spectral flatness threshold (0.4)

// mmse_lsa_default_config() 內
config.scene_change_flatness_threshold = 0.4f;
```

### 2. `mcra_noise_estimator.c`

```c
// struct McraNoiseEstimator 加
float scene_change_flatness_threshold;

// mcra_create() 加
self->scene_change_flatness_threshold = config->scene_change_flatness_threshold;

// mcra_init_noise() 兩條 code path 改
// USE_FAST_PERCENTILE:
self->S[k] = init_psd;  // was: avg_power
// exact quickselect path:
self->S[k] = init_psd;  // was: avg_power (+remove avg_power variable 若不再用)

// mcra_update() line 443 改
if (hi_gamma > self->scene_change_threshold &&
    hi_flatness > self->scene_change_flatness_threshold) {
```

### 3. `spp_estimator.c`

```c
// struct SppEstimator 加
float* noise_psd_prev;  // Previous frame's noise PSD

// spp_create() 加
float _eps = 1e-6f;
float q_clipped = config->q;
if (q_clipped < _eps) q_clipped = _eps;
if (q_clipped > 1.0f - _eps) q_clipped = 1.0f - _eps;
self->q = q_clipped;
self->prior_ratio = (1.0f - q_clipped) / q_clipped;  // 去掉 +1e-10f

self->noise_psd_prev = (float*)calloc(n_freqs, sizeof(float));

// spp_estimate() / spp_estimate_ex() DD path 改
// 原:
//   xi_dd_term1 = enhanced_psd_prev[k] / (noise_psd[k] + 1e-10f);
// 新:
//   const float* nd = self->has_prev_noise ? self->noise_psd_prev : noise_psd;
//   xi_dd_term1 = enhanced_psd_prev[k] / (nd[k] + 1e-10f);
//
// 函式尾端：
//   memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));
//   self->has_prev_noise = true;

// spp_reset() 加
memset(self->noise_psd_prev, 0, self->n_freqs * sizeof(float));
self->has_prev_noise = false;

// spp_destroy() 加
if (self->noise_psd_prev) free(self->noise_psd_prev);
```

## 驗證策略

### L1 模組級（建議這階段 target）
- c_impl 有 `DEBUG_DUMP` 機制會輸出每幀 `noise_psd / spp / xi / gamma / gain` 到 `/tmp/c_debug_dump.bin`
- 對同一 wav 比對 Python V3-2 與 C v3_2 的逐幀中間值
- 目標：**差異在 scipy E1 三段近似誤差範圍內**（Python 用 `scipy.special.exp1`，C 用 `exp1_approx`；兩者本就不是 bit-exact，差異 ~1e-4）

### 宏觀（最終驗證）
- 用 `c_impl/bin/denoise_wav` 跑 VCTK 子集
- 對同一份 wav，比較 Python v3_2 修復後 vs C 修復後的輸出 RMS 差異
- 目標：差異 <1dB，PESQ 差 <0.05

### 不做 L1 bit-exact（診斷 spec 裡提到的）
原因：Python 用 `scipy.special.exp1`（Taylor+continued-fraction），C 用三段近似；這本來就不可能 bit-exact。要做真正的 L1 需要先把 Python 改成用 `_exp1_approx`（已有實作但預設關閉）再對齊。可以作為未來 V5 工作。

## 執行步驟（得到你 OK 後）

1. 在 `main` 做上述 4 個 fix
2. `make -C c_impl clean && make -C c_impl` 確認能 build
3. 跑一下 `c_impl/bin/denoise_wav test_wav/wav/car_5dB.wav /tmp/out.wav` 或已有的 demo 確認無 crash
4. Commit
5. （可選）寫簡單的 c vs python diff 驗證 script

## 風險與注意事項

- **`spp_estimator.c` 會增加記憶體** — `noise_psd_prev` 加 `n_freqs * sizeof(float)` ≈ 1 KB @ 16kHz/512 FFT。
- **`mcra_update()` 的 line 443 改 `0.4f` 為變數** — 若 struct 沒初始化（某些 edge case 如直接 memcpy），會讀到 0 導致永遠不觸發 scene change。`mcra_create()` 內一定要設好。
- **Fix #3 的 DD 第一幀** — Python 版 `noise_psd_prev is None` 時 fallback 到 current noise_psd。C 版需要 `has_prev_noise` flag 或用 `is_initialized`（但 spp 已有這個 flag 了——可以共用）。

---

**請 review 這份 plan。等你核可後我再動。**
