# C ↔ Python 函式對照表（NR）

> 範圍：`c_impl/src/*.c` 與 `c_impl/include/anr_types.h` 內的演算法函式 ↔ `python/core/**`、`python/denoisers/**`。
> Python 路徑相對 `NR/python/`，C 路徑相對 `NR/c_impl/`。
> 守門測試：`python/tests/test_c_python_map.py`（讀本檔，用 `ast` 驗證 Python 符號、掃描 C 函式定義，不匯入任何模組）。

## 1. 用途

函式級的 C ↔ Python 對應，由 pytest 守住：

- 修 Python↔C 落差時，定位要改的 C 函式、對照的 Python 符號與落差編號。
- 讓對拍腳本（`python/tools/pyc_parity_nr.py`）的 EXPECTED_RED 紅燈能回頭找到函式。
- 在 Python 或 C 側增刪改符號時，由 pytest 提醒更新本表。

每一列的最後一欄用標籤標出依據（見 §3）；標 `[讀碼]` 的列是逐行對讀 C 與 Python 後的判斷，沒有文件或註解背書。

## 2. 如何維護

1. 新增、刪除或改名 C 函式（含 `anr_types.h` 的 `static inline`）：在 §6 對應小節增刪一列。測試會比對「掃描到的 C 函式定義」與「表中列出的 C 函式」，缺一個或多一個都會失敗。
2. 新增、刪除或改名 Python 符號：改 Python 欄。測試用 `ast` 檢查每個符號仍存在；`core/**`、`denoisers/**` 的頂層類別與函式必須出現在表中（對應列或 Python-only 列）。
3. 以**符號名**為準；表內不放行號。
4. 某條落差修好：從「已知落差」欄與附錄 A 移除該編號。
5. 改完更新 §5 的涵蓋率行（測試會重算並比對）。
6. 驗證指令（從 `NR/` 根目錄；`Audio_ALG/lib/nr/` 同樣適用）：

   ```
   PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider python/tests/test_c_python_map.py
   ```

7. `Audio_ALG/lib/nr/` 內有本檔與測試的逐字副本，兩處要同步。

## 3. 讀表說明

**關係**：`mirror` = 同一數學（浮點精度、近似數學、輸入單位的差別不影響此標籤，差別寫在說明與落差欄）；`partial` = 只涵蓋對方的一部分、或同一功能拆在不同位置；`C-only` = Python 沒有對應（記憶體管理、SIMD twin、執行期重設定、診斷等）；`Python-only` = C 沒有對應。「未判斷」目前為 0，若日後出現必須明列於 §5。

**符號語法（Python 欄）**：`相對路徑.py:符號[#錨點]`，多個以 `；` 分隔，`—` 表示無。符號是模組層級的 `def`／`class`／被賦值的名稱，或 `Class.method`。`#錨點` 是該符號的語法樹內必須出現的識別字（變數、屬性、參數名或字串常數），用來把「某函式內的一段 inline 程式」釘在外層方法上而不發明不存在的函式名；測試會檢查錨點仍在。

**C 欄**：`相對路徑:函式`，同一列可有多個函式（共用同一關係）；`（twin：…）` 後列出該列主函式的 scalar／NEON／dispatcher 實作變體，它們一律算 C-only，數學見主函式。`include/…` 檔內的列是 header 的 `static inline` 定義，或（標「宣告無實作」者）只有宣告的符號。

**已知落差**：落差編號（見附錄 A）。`anr_process`、`anr_process_gain`、`run_frame_gain_stage` 三列列的是整條路徑上的編號，細項在各子函式列。`—` = 沒有登記落差（不等於證明無落差）。

**對拍／測試**：路徑相對 `NR/`；後綴 `[CP]` = C↔Python 數值對照、`[CC]` = C 對 C（scalar 對 NEON、串流）、`[C]` = 只測 C 行為、`[PY]` = 只測 Python。`parity_nr.py compare` 只印統計、不設門檻；`test_config_parity` 只對拍設定欄位；數值閘門是 `pyc_parity_nr`（見 §4）。

**依據標籤**：`[CHANGELOG]` = `c_impl/CHANGELOG.md` 或 `CHANGELOG.md` 明載；`[README]` = `c_impl/README.md` 或 `docs/` 明載；`[註解]` = C 或 Python 原始碼註解／docstring 明載；`[稽核]` = 兩側位置經 Python↔C 逐項稽核核對；`[測試]` = 現有測試或工具以此為配對對象；`[讀碼]` = 以上皆無，只憑逐行對讀判斷。

## 4. 與對拍工具（pyc_parity_nr）的關係

本表回答「哪個 C 函式對應哪個 Python 符號、已知落差是哪一條」（**符號層追溯**）；`python/tools/pyc_parity_nr.py`（由 `c_impl/test/pyc_parity_nr.sh` 驅動）回答「兩邊輸出差多少」（**數值層量測**）。兩者互不 import，共用的只有落差編號：`c_impl/test/pyc_parity/expected_red.json` 裡的 `S-xx` 與本表「已知落差」欄是同一套編號。腳本某個情境變紅時，用編號在本表找到函式列；修好一個落差後，從預期紅名單與本表該列各拿掉該編號。測試 `test_expected_red_ids_of_the_parity_registry_are_locatable` 在預期紅名單檔存在時檢查其中每個 `S-xx` 都能在本表「已知落差」欄找到（檔不存在則略過）。

腳本的情境分 gain（同一份 float32 頻譜餵 Python `denoise_spectrum` 與 C `anr_process_gain`）與 e2e（整條波形）兩種，層分 L1（std-math C 對 Python，偏差即 sync bug）與 L2（出貨建置對 std-math C，即 fast-math 近似）。預期紅名單目前只有 S-13（L1）。

## 5. 涵蓋率與未能判斷

<!-- STATS -->
**涵蓋率**：C 函式定義 96；mirror 28；partial 43；C-only 25（其中 SIMD twin／dispatcher 3）；未能判斷 0；另有宣告無實作 0；Python-only 18 個符號（9 列）

- 統計來源：測試內的掃描器對 `src/anr.c`、`src/noise_estimator.c`、`src/spp_estimator.c`、`include/anr_types.h` 取頂層函式定義（`extern "C"` 包裝不算函式、條件編譯分支的重複定義只算一次）。分項：`anr.c` 38、`noise_estimator.c` 28、`spp_estimator.c` 14、`anr_types.h` 16，合計 96。`anr.h`、`noise_estimator.h`、`spp_estimator.h`、`anr_internal.h` 沒有函式定義（只有宣告）。
- 「已對應」= mirror + partial = 71；C-only 中 3 個是 twin（scalar／NEON／dispatcher 變體），其餘 22 個是記憶體管理、執行期重設定、診斷、實驗 overlay 等。
- **未能判斷：0**。沒有任何 C 函式在嘗試後仍無法決定「有／無 Python 對應」。判斷力度較低、值得複核的是只有 `[讀碼]` 標籤的 38 列（全表 78 列）；這些列的對應是合理的對讀結果，但沒有文件或註解背書。
- Python 側：`core/**`、`denoisers/**` 的頂層類別與函式全部出現在表中（對應列或 Python-only 列，由測試守住）；Python-only 以類別／函式為粒度，方法與研究旋鈕不單獨成列（旋鈕寫在所屬列的「已知落差」S-35）。

## 6. 對照表

<!-- MAP:BEGIN -->

### 6.1 `src/anr.c`（頻域核心：語音證據、增益、串流 API）

| C 檔:函式 | Python 檔:符號 | 關係 | 已知落差 | 對拍／測試 | 依據與說明 |
| --- | --- | --- | --- | --- | --- |
| `src/anr.c:apply_gain_config_scalars` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__`；`core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.__init__`；`denoisers/v3_2_mmse_lsa.py:SPEECH_PROTECT_ANCHOR_Q` | partial | D-20 | `c_impl/test/test_reconfigure.c`[C] | [註解] C 把兩個 Python ctor 內的衍生純量（`g_min`／`log_g_min`、speech_protect floor、`noise_gate_xi`、frame threshold = 設定值 + (q − 0.52)）集中成一個可重複套用的函式，`anr_reconfigure` 共用。Python 的 `SPEECH_PROTECT_ANCHOR_Q` 註解寫明鏡射 C 的 `ANR_SPEECH_PROTECT_ANCHOR_Q`。`alpha_g` 在 C 只被存下、增益路徑不讀（D-20）。 |
| `src/anr.c:hz_to_bin_ceil`、`src/anr.c:hz_to_bin_floor_inclusive` | `denoisers/v3_2_mmse_lsa.py:_hz_to_bin_ceil`；`denoisers/v3_2_mmse_lsa.py:_hz_to_bin_floor_inclusive` | mirror | — | — | [讀碼] 兩側註解用語相同（first bin at or above hz／bin count covering [0, hz] inclusive）。C 用 float32 `ceilf`／`floorf`，Python 用 float64 `np.ceil`／`np.floor`；作者用 numpy float32／float64 各算一次，5 組支援 grid 的 80 Hz 與 4000 Hz 邊界 bin 相同（非稽核項，無專屬測試）。 |
| `src/anr.c:update_noise_gate_geometry` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__#noise_gate_lf_bin` | partial | S-35 | — | [註解] C 一律把 `noise_gate_lf_hz` 解成 bin 並夾到 [1, n_freqs]（`anr_validate_config` 要求 hz > 0）。Python 的 `noise_gate_lf_hz=None` 是研究設定，此時保護 floor 涵蓋整個語音頻帶；Python `__init__` 註解寫明「the C port always resolves the LF band」。 |
| `src/anr.c:reset_gain_state` | `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.reset` | mirror | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] Python `log_gain_prev = None` ↔ C `gain_initialized = false` 並把 `log_gain_prev` 清零；首幀不做平滑，兩側一致。 |
| `src/anr.c:reset_frame_evidence_state` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.reset`；`core/spp_estimator.py:SppEstimator.reset` | partial | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] C 一次清 cross-band EMA、LF 保護旗標、`slow_lf_rise`、`makeup_prior_state = 0.5`；Python 分散在 `MmseLsaDenoiser.reset`（`_makeup_prior_state`）與 `SppEstimator.reset`（`cross_band_prior_state`）。 |
| `src/anr.c:lift_spp` | `core/spp_estimator.py:SppEstimator.estimate#lift` | partial | S-35 | `c_impl/test/test_bit_exact_stream.c`[CC]；`python/tests/test_speech_protection.py`[PY] | [註解][稽核] 一階 logit 提升 `p + lift·p·(1−p)`。Python 在 `estimate()` 內提升並以提升後的 SPP 當回傳值；C 保留原始 SPP，只在增益端與 LF floor 呼叫 `lift_spp`。C 的 cross-band 是 bool 加固定 0.50／0.70 ramp（等於 Python strength = 1 與預設 threshold／full_scale），Python 另有 strength／threshold／full_scale 旋鈕（S-35）。Python 註解寫「the embedded C implementation mirrors the same scalar path」。 |
| `src/anr.c:store_gain_state` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#enhanced_psd_prev`；`core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.calculate#log_gain_prev` | partial | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] 下一 hop 的 DD 狀態：C 集中寫 `gain_prev`／`log_gain_prev`／`enhanced_psd_prev = dd_gain²·power`（`dd_gain` 為輸出增益，`dd_from_gmmse` 時為 G_H1）。Python 的 `gain_prev`、`enhanced_psd_prev` 在 denoiser，`log_gain_prev` 在 calculator。make-up 縮放不進 DD 狀態，兩側一致。 |
| `src/anr.c:update_frame_speech_evidence` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#frame_spp_mean`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#speech_xi_fraction`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#_makeup_prior_state`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser._speech_band_mean`；`core/spp_estimator.py:SppEstimator.estimate#cross_band_prior_state`；`core/spp_estimator.py:_ramp01` | partial | S-13、D-20、S-35 | `python/tests/test_speech_protection.py`[PY] | [稽核] 一次掃 80–4000 Hz 語音頻帶：SPP 平均 → LF 保護旗標、DD-xi 比例 → `slow_lf_rise`、make-up 先驗 EMA、cross-band EMA。Python 把同樣的量散在 `denoise_spectrum` 與 `SppEstimator.estimate`。**make-up 權重：Python 預設 `makeup_prior='spp'`，C 只有 xi 版（`xi_fraction/0.15`、0.1 EMA、下限 0.01），S-13。**`makeup_prior_xi_db` 在 C 是惰性欄位（D-20）；make-up 路徑由 `pyc_parity_nr` 的 makeup 情境對拍（S-13 為預期紅）。 |
| `src/anr.c:apply_frame_makeup` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#makeup_blim` | partial | S-13、D-20 | — | [稽核] `g_frame = sqrt(E_out/(E_in+1e-20))`、up／down slope 與 blend 兩側公式相同；差在權重來源（見 `update_frame_speech_evidence`）。預設兩邊 `makeup_gain = false`，屬休眠路徑。 |
| `src/anr.c:apply_low_band_speech_floor` | `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.calculate#spp_protect_floor`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__#speech_protect_mask` | mirror | — | `python/tests/test_speech_protection.py`[PY] | [CHANGELOG] LF（bin 1 到 `noise_gate_lf_bin − 1`）且 SPP > threshold、且本幀為語音幀時 gain ≥ floor（CHANGELOG「共用低頻語音保護」兩側同步）。C 在套 floor 的當下回頭修正該 bin 的 DD 狀態；Python 在 `calculate()` 內先套 floor，再以套完的 gain 重算 `log_gain_prev`，`enhanced_psd_prev` 由 denoiser 用最終 gain 計算。 |
| `src/anr.c:update_noise_estimator` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#slow_mask`；`core/noise_estimators/mcra.py:McraNoiseEstimator.update` | partial | S-35 | `c_impl/test/test_noise_restart.c`[C]；`python/tests/test_noise_tracker_restart.py`[PY] | [註解] C 一律把原始（未 lift）SPP、`slow_lf_rise`、LF bin 數、`alpha_d_speech` 傳進 `noise_estimator_update_ex`。Python 在 `noise_gate_xi` 設定時算 `slow_mask`（LF 帶一個 frame 級決策，Python 註解寫「as in the C port」）；cross-band／frame prior 開啟時改傳 `fixed_prior_spp`，預設路徑同值。 |
| `src/anr.c:prepare_noise_for_spp` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#extra_noise_psd`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#noise_over_subtraction` | mirror | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] SPP／SNR 用的噪聲底 = `noise_over_subtraction × (N + R²)`，追蹤器不吃這份，兩側一致。NR 層的 `extra_noise_psd` 路徑沒有 Python↔C 專屬對拍（`parity_runner` 傳 NULL）。 |
| `src/anr.c:gain_prepare`（twin：無；kernel 本體在 audiolib simd_nr.h） | `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator._mmse_gain_base` | partial | D-18 | `c_impl/test/test_anr_kernels.c`[CC]；`python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [稽核] 僅在 `USE_SHARED_XI_RATIO`（出貨預設）編譯。v 夾到 [1e-10, 700] 兩側相同；xi/(1+xi) 在 C 以 `v_in/(gamma+1e-10f)` 反推（`v_in<1e-10f` 時直接算 `xi/(1+xi)`），Python 直接算 `xi/(1+xi)`。`make debug` 不含此旗標。本列是 ANR_VECTOR 分派 wrapper，kernel（`skr_gain_prepare_*`）在 `audiolib/common/utility/simd_nr.h`，函式級對應見 Audio_ALG/docs/c_python_function_map.md 的 AC-SIMD-08。 |
| `src/anr.c:calculate_gain` | `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.calculate`；`core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator._mmse_gain_base`；`core/gain_calculators/mmse_lsa.py:_exp1_approx` | mirror | D-18、D-20、S-35 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP]；`python/tests/test_speech_protection.py`[PY] | [註解][稽核] OM-LSA：G_H1 = xi/(1+xi)·exp(0.5·E1(v)) 夾到 [g_min, 1]，log 域與 SPP 混合、非對稱平滑、LF floor。E1 用 Martin 2004 式 (17) 三段近似，Python `_exp1_approx` 與 audiolib `sk_exp1_approx_f32` 同公式（c_impl/CHANGELOG）；`mmse_lsa.py` docstring 寫明與 `anr.c` 公式對齊。`sk_fast_exp_f32`／`sk_fast_log_f32` 為近似數學（D-18：出貨建置相對 Python 的偏差，來自硬判決翻轉）。 |
| `src/anr.c:run_frame_gain_stage` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum` | mirror | S-13、S-35 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [讀碼] 每幀主體順序兩側相同：SPP／DD → 語音證據 → 增益＋LF floor → make-up → 噪聲追蹤（靜音幀不推進追蹤器）。Python 迴圈內另有 Python-only 研究分支（`frame_prior_*`、`frame_prior_gmin_lift_db` 等，S-35）。 |
| `src/anr.c:_setup` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__#speech_bin_start` | partial | — | — | [讀碼] 語音頻帶 bin 範圍 [max(1, ceil(80 Hz)), min(n_freqs, floor(4 kHz)+1))、`speech_band_inv_count`、LF bin、增益純量。C 另有 `end ≤ start` 時回退成 (0, n_freqs) 的分支，Python 沒有；5 組支援 grid 都不會觸發（作者重算）。 |
| `src/anr.c:anr_get_mem_size`、`src/anr.c:anr_destroy` | — | C-only | D-19 | `c_impl/test/test_config_validation.c`[C] | [稽核] 靜態記憶體池尺寸查詢與釋放；Python 以 numpy 動態配置，沒有對應。 |
| `src/anr.c:anr_create`、`src/anr.c:anr_init` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__` | partial | D-19、S-34 | `c_impl/test/test_config_validation.c`[C]；`c_impl/test/test_reconfigure.c`[C]；`c_impl/test/test_api_cpp.cpp`[C] | [讀碼] 建構：先 `anr_validate_config` 再配置（heap／靜態池兩條路）。Python ctor 另含參數 retime 與研究旋鈕；C 的 retime 在 config builder（`anr_default_config_for_grid`）。 |
| `src/anr.c:frame_is_silent` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#silent` | mirror | — | `c_impl/test/test_noise_restart.c`[C]；`python/tests/test_noise_tracker_restart.py`[PY] | [CHANGELOG][測試] 數位靜音（全 bin 精確為 0）不計入噪聲初始化、不推進追蹤器（c_impl/CHANGELOG「數位靜音幀不計入噪聲初始化與追蹤」，Python 同步）。Python 判斷用幅度譜、C 用功率譜。 |
| `src/anr.c:anr_process` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum` | partial | S-13、D-18 | `c_impl/test/test_noise_restart.c`[C]；`c_impl/test/test_bit_exact_stream.c`[CC] | [README][CHANGELOG] 頻域串流：power → 初始化（前 `num_init_frames` 個非靜音幀，期間 gain = 1）→ 正常處理 → 套 gain。Python 是整段批次，進入時自動 `reset()`（C 的 streaming 由 caller 負責 reset，c_impl/CHANGELOG 已記）。視窗／FFT／OLA 在 C 側屬 caller 與 audiolib，對應 Python `FrameProcessor`／`Reconstructor`（Python-only 區）。`c_impl/README.md` 標示 C 對應 `v3_2_mmse_lsa.py`。 |
| `src/anr.c:anr_process_gain` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#return_gain`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#extra_noise_psd` | partial | S-13、D-18 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [測試] 與 `anr_process` 同一內部流程，另吃 `extra_noise_psd`（R²）並輸出 gain；`parity_nr.py` 的 C 側（`parity_runner`）就是逐幀呼叫它，Python 側取 `denoise(..., return_gain=True)`。數值對拍由 `pyc_parity_nr` 承擔。 |
| `src/anr.c:process_init_or_gain` | — | C-only | — | `c_impl/test/test_noise_restart.c`[C]；`c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] `anr_process` 與 `anr_process_gain` 共用的逐幀階段：噪聲底尚未初始化時累積起始功率並旁路（gain = 1），之後呼叫增益階段；Python 在 `denoise_spectrum` 內聯。 |
| `src/anr.c:anr_reconfigure` | — | C-only | D-19 | `c_impl/test/test_reconfigure.c`[C] | [稽核] 執行期換設定並保留 DSP 狀態（grid／L／num_init_frames 不可變）；Python 沒有。 |
| `src/anr.c:anr_set_mode` | `core/nr_strength.py:apply_strength` | partial | D-19 | `c_impl/test/test_reconfigure.c`[C]；`c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] C：以 `anr_config_for_mode_grid` 產生目標設定後 `anr_reconfigure`（執行期）。Python 只能在建構前以 `apply_strength` 疊 preset，沒有執行期切換。 |
| `src/anr.c:anr_reset` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.reset` | mirror | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] 清所有幀間狀態；Python 在 `denoise_spectrum` 進入時自動呼叫 `reset()`。 |
| `src/anr.c:anr_get_hop_size`、`src/anr.c:anr_get_frame_size`、`src/anr.c:anr_get_n_freqs`、`src/anr.c:anr_get_latency` | — | C-only | — | `c_impl/test/test_reconfigure.c`[C] | [讀碼] 設定值存取器。Python 以 `FrameProcessor` 屬性表達 frame／hop（見 Python-only 區）；`anr_get_latency` 恆為 0（頻域核心無額外延遲）。 |
| `src/anr.c:anr_is_initialized` | `core/noise_estimators/mcra.py:McraNoiseEstimator.estimate#is_initialized` | partial | — | `c_impl/test/test_noise_restart.c`[C]；`c_impl/test/test_reconfigure.c`[C] | [讀碼] C 回報噪聲初始化完成；Python 對應 `McraNoiseEstimator.is_initialized`（由 `estimate()` 設定）。 |
| `src/anr.c:anr_get_spp` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#return_spp` | partial | — | — | [讀碼] 借用最近一幀的 SPP。C 回傳未 lift 的原始 SPP；Python `return_spp` 記錄 `estimate()` 的回傳值（cross-band／frame prior 開啟時已 lift），預設路徑兩者相同。 |
| `src/anr.c:anr_get_noise_psd` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#return_noise_psd` | partial | — | `c_impl/test/test_reconfigure.c`[C] | [讀碼] 時點不同：C 在 `anr_process*` 之後讀到的是本幀追蹤更新後的值；Python `return_noise_psd` 記錄「算該幀增益前」的估計器內部值（不含 R²）。 |
| `src/anr.c:anr_get_speech_protect_frame_threshold` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__#speech_protect_frame_threshold_effective` | mirror | — | `c_impl/test/test_reconfigure.c`[C] | [註解] = 設定值 + (q − 0.52)；Python 註解寫明以 float32 計算「like the C port」。 |
| `src/anr.c:anr_get_gain` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#return_gain` | partial | — | `c_impl/test/test_config_validation.c`[C] | [讀碼] 最近一幀的最終增益；兩側都含 make-up 縮放（Python `return_gain` 記錄 `gain × applied_scale`）。 |
| `src/anr.c:anr_debug_status` | — | C-only | D-19 | `c_impl/example/main.c`[C] | [稽核] 診斷用唯讀彙總（mean／min gain dB 等）；Python 沒有，`example/main.c` 使用。 |

`final_blend`／`final_store` 不在本表範圍：它們的 kernel（`skr_final_blend_*`、`skr_final_store_*`）在 `audiolib/common/utility/simd_nr.h`，`anr.c` 只在 `USE_FAST_GAIN_SMOOTHING` 且 `ANR_VECTOR` 時直接呼叫 `skr_*_neon`，函式級條目在 Audio_ALG/docs/c_python_function_map.md 的 AC-SIMD-08。Python 對應如下。

- `final_blend` ↔ `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.calculate#log_gain_prev`（mirror，已知落差 S-35、D-20、D-18）。[讀碼] 僅在 `USE_FAST_GAIN_SMOOTHING` 編譯：log 域 SPP 混合 `p·log G_H1 + (1−p)·log g_min`、非對稱 attack／decay 平滑、log 域夾限。Python 只有 `floor_blend='log'` 是出貨路徑；`'sqrt'`／`'linear'` 混合、per-bin `g_min`、alpha override、`use_asymmetric_smoothing=False`（用 `alpha_g`）是 Python-only（S-35）；C 恆走非對稱，`alpha_g` 惰性（D-20）。
- `final_store` ↔ `core/gain_calculators/mmse_lsa.py:MmseLsaGainCalculator.calculate#log_gain_prev`＋`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise_spectrum#enhanced_psd_prev`（partial，已知落差 D-18）。[讀碼] 僅在 `USE_FAST_GAIN_SMOOTHING` 編譯：log 增益落在 [log g_min, 0] 之外時直接取 g_min／1，並寫回 DD 狀態；Python 為 `np.exp` 後 `np.clip(g_min, 1)`，再以夾限後的 gain 重算 `log_gain_prev`，C 存的是夾限後的 log 值。

### 6.2 `src/noise_estimator.c`（噪聲 PSD 追蹤器）

| C 檔:函式 | Python 檔:符號 | 關係 | 已知落差 | 對拍／測試 | 依據與說明 |
| --- | --- | --- | --- | --- | --- |
| `src/noise_estimator.c:spectral_flatness` | `core/noise_estimators/mcra.py:_spectral_flatness` | mirror | D-18 | `c_impl/test/test_scene_change_margin.c`[C]；`python/tests/test_scene_change_flatness_margin.py`[PY] | [CHANGELOG][測試] 高頻帶 geometric／arithmetic mean flatness（各 bin 加 1e-20）。C 的 log 用 `sk_fast_log_f32`、exp 用 libm `expf`（不用近似 exp，避免硬門檻判決翻轉）；Python 用 float64。flatness 直接和 0.4 硬門檻比，所以兩個測試用門檻 ±6e-4 的合成頻譜釘住兩端。 |
| `src/noise_estimator.c:noise_estimator_reset_noise_floor` | `core/noise_estimators/mcra.py:McraNoiseEstimator.update#scene_change_blend` | mirror | S-35 | `c_impl/test/test_scene_change_margin.c`[C]；`python/tests/test_scene_change_flatness_margin.py`[PY] | [讀碼] 場景轉換確認後：noise_psd 以 `blend` 往當前 power 靠，`S_min` 與 min_buffer 以 `S` 重播種。Python 在 `remove_echo_explained_rise`（arm 4）開啟時改用回音修正後的 `S`（Python-only，S-35／D-22）。 |
| `src/noise_estimator.c:noise_estimator_apply_config_scalars` | `core/noise_estimators/mcra.py:McraNoiseEstimator.__init__` | partial | — | `c_impl/test/test_reconfigure.c`[C] | [讀碼] `delta = 10^(delta_db/10)`、scene-change 門檻等純量；只更新純量、保留追蹤器狀態（`anr_reconfigure` 共用）。 |
| `src/noise_estimator.c:noise_estimator_min_ordered`（twin：無；kernel 本體在 audiolib simd_nr.h） | `core/noise_estimators/mcra.py:McraNoiseEstimator.update#S_min` | partial | — | `c_impl/test/test_min_ordered_special.c`[C]；`c_impl/test/test_anr_kernels.c`[CC] | [讀碼] 僅在 `USE_OPTIMIZED_MIN_BUFFER` 編譯。取 L 個 `S` 的有序最小值（嚴格 `<` 才取代；NaN 不取代、±0 保位置身分）。Python 為 `np.min(min_buffer, axis=0)`；NaN 語意不同（`np.min` 會傳遞 NaN），輸入是非負 power 時結果相同（作者讀碼）。本列是 ANR_VECTOR 分派 wrapper，kernel（`skr_min_ordered_*`、`skr_vmin_lt`）在 `audiolib/common/utility/simd_nr.h`，見 Audio_ALG/docs/c_python_function_map.md 的 AC-SIMD-08。 |
| `src/noise_estimator.c:noise_estimator_init_scalars` | — | C-only | — | — | [讀碼] 配置後的純量初始化（共用於 heap 與靜態池兩條建構路徑）。 |
| `src/noise_estimator.c:noise_estimator_ring_rows` | — | C-only | — | `c_impl/test/test_shared_startup.c`[C] | [讀碼] 最小值環所在區域的列數（共用起始時取 L 與 `num_init_frames` 較大者），供 heap、靜態池與尺寸查詢共用；Python 動態配置。 |
| `src/noise_estimator.c:noise_estimator_seed_bin`、`src/noise_estimator.c:noise_estimator_seed_from_mean` | — | C-only | D-19 | `c_impl/test/test_noise_restart.c`[C] | [讀碼] 初始噪聲估計寫入 noise_psd／S／S_min／spp 的共用步驟（夾到 ≥ 1e-10）；`seed_from_mean` 是 `USE_FAST_PERCENTILE` 與「scratch 不可用」時的 mean × 0.23 回退（D-19）。 |
| `src/noise_estimator.c:noise_estimator_get_mem_size`、`src/noise_estimator.c:noise_estimator_get_mem_size_shared_startup`、`src/noise_estimator.c:noise_estimator_mem_size_impl`、`src/noise_estimator.c:noise_estimator_destroy` | — | C-only | D-19 | `c_impl/test/test_config_validation.c`[C]；`c_impl/test/test_shared_startup.c`[C] | [稽核] 靜態記憶體池尺寸查詢與釋放。`_shared_startup` 是整合 denoiser 專用的私有變體（`anr_internal.h`）：啟動列與最小值 ring 共用同一塊儲存（取兩者較大者），公開版維持各自配置。 |
| `src/noise_estimator.c:noise_estimator_create`、`src/noise_estimator.c:noise_estimator_create_shared_startup`、`src/noise_estimator.c:noise_estimator_create_impl`、`src/noise_estimator.c:noise_estimator_init`、`src/noise_estimator.c:noise_estimator_init_shared_startup`、`src/noise_estimator.c:noise_estimator_init_impl` | `core/noise_estimators/mcra.py:McraNoiseEstimator.__init__` | partial | D-19 | `c_impl/test/test_config_validation.c`[C]；`c_impl/test/test_reconfigure.c`[C]；`c_impl/test/test_shared_startup.c`[C] | [讀碼] 建構（heap／靜態池兩條路；整合 denoiser 走 `_shared_startup` 私有變體）；Python ctor 另有 arm 4、`alpha_d_up` 等研究參數。 |
| `src/noise_estimator.c:noise_estimator_accumulate_init_power` | `core/noise_estimators/mcra.py:McraNoiseEstimator.estimate#init_frames` | partial | D-19 | `c_impl/test/test_noise_restart.c`[C]；`python/tests/test_noise_tracker_restart.py`[PY] | [讀碼] C 逐幀把 power 存進 `init_power_buffer`（檔內兩份定義，`USE_FAST_PERCENTILE` 開時為空操作）；Python 一次取 `magnitude_spectrum[:num_init_frames]` 平方。 |
| `src/noise_estimator.c:quickselect_partition`、`src/noise_estimator.c:quickselect`、`src/noise_estimator.c:calculate_percentile` | `core/noise_estimators/mcra.py:McraNoiseEstimator.estimate#partition` | mirror | — | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [註解] 第 k 小值，`k = ((N−1)·30)//100`，不做線性插值；Python `estimate()` 註解寫明「與 C quickselect 語義一致」。僅在 `USE_FAST_PERCENTILE` 關閉（預設）時編譯。 |
| `src/noise_estimator.c:noise_estimator_init_noise` | `core/noise_estimators/mcra.py:McraNoiseEstimator.estimate` | partial | D-19 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [稽核] 以 30th percentile 初始化 noise_psd／S／S_min／spp 並填滿 min_buffer。C 在三條路徑都把 init_psd 夾到 ≥ 1e-10，Python `estimate()` 以 `np.maximum(init_psd, 1e-10)` 同樣夾限（數值防護，非演算法參數）。`USE_FAST_PERCENTILE`（mean × 0.23）與「scratch 不可用」回退是 C-only（D-19）。 |
| `src/noise_estimator.c:noise_estimator_ring_min`（twin：無；kernel 本體在 audiolib simd_nr.h） | `core/noise_estimators/mcra.py:McraNoiseEstimator.update#min_buffer` | partial | — | `c_impl/test/test_anr_kernels.c`[CC] | [讀碼] 僅在 `USE_OPTIMIZED_MIN_BUFFER`＋`USE_INCREMENTAL_MIN` 編譯。增量最小值：新 `S` ≤ `S_min` 直接取代，被逐出值 ≤ `S_min·(1+1e-6)` 才整排重掃；作者讀碼推得結果等於 Python 每幀 `np.min` 全掃（無 Python↔C 專屬測試，`test_anr_kernels.c` 只比 scalar／NEON）。本列是 ANR_VECTOR 分派 wrapper，kernel（`skr_ring_min_*`、`skr_lane_list`、`skr_lane_count`、`SKR_RING_MIN_BLOCK`）在 `audiolib/common/utility/simd_nr.h`，見 Audio_ALG/docs/c_python_function_map.md 的 AC-SIMD-08。 |
| `src/noise_estimator.c:noise_estimator_restart_inert`（twin：無；kernel 本體在 audiolib simd_nr.h） | `core/noise_estimators/mcra.py:McraNoiseEstimator.update#NOISE_PSD_INERT` | mirror | — | `c_impl/test/test_noise_restart.c`[C]；`python/tests/test_noise_tracker_restart.py`[PY]；`c_impl/test/test_anr_kernels.c`[CC] | [註解][測試] noise_psd < 1e-20 的 bin 以 p = 0 的未門控混合重啟（數位靜音後訊號回來時避免後驗恆為 1 的不動點）。`1e-20` 門檻的單一來源是 `simd_nr.h` 的 `SKR_NOISE_PSD_INERT`，Python 類別常數 `NOISE_PSD_INERT` 與之相等。本列是 ANR_VECTOR 分派 wrapper，kernel（`skr_restart_inert_*`）在 `audiolib/common/utility/simd_nr.h`，見 Audio_ALG/docs/c_python_function_map.md 的 AC-SIMD-08。 |
| `src/noise_estimator.c:noise_estimator_update_ex` | `core/noise_estimators/mcra.py:McraNoiseEstimator.update` | partial | S-35、D-22 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP]；`c_impl/test/test_scene_change_margin.c`[C]；`python/tests/test_scene_change_flatness_margin.py`[PY] | [稽核] `S` → ring min → 內部 SPP 平滑 → 場景轉換 → 寬頻縮放 → 噪聲更新（LF 慢升速）→ 死 bin 重啟，順序兩側相同。scene-change 的 `hi_gamma` 兩側都先取 mean 再加 epsilon（C `hi_power_mean/(hi_noise_mean+1e-10f)`，Python `mean(power)/(mean(noise)+1e-10)`）。Python 吃 magnitude（內部平方）、C 吃 power。Python-only 選項：`alpha_d_up`、`frame_gate_p`、`slow_mask_max_frac`、`remove_echo_explained_rise`、`accept_external_spp=False`（S-35／D-22）。 |
| `src/noise_estimator.c:noise_estimator_get_noise_psd` | `core/noise_estimators/mcra.py:McraNoiseEstimator.update#noise_psd` | partial | — | — | [讀碼] 借用的狀態存取器 ↔ Python 屬性 `noise_psd`。 |
| `src/noise_estimator.c:noise_estimator_reset` | `core/noise_estimators/mcra.py:McraNoiseEstimator.reset` | mirror | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] 清追蹤狀態；C 把陣列清零、Python 設為 None（`estimate()` 重建）。 |

### 6.3 `src/spp_estimator.c`（decision-directed 語音存在機率）

| C 檔:函式 | Python 檔:符號 | 關係 | 已知落差 | 對拍／測試 | 依據與說明 |
| --- | --- | --- | --- | --- | --- |
| `src/spp_estimator.c:spp_apply_config_scalars` | `core/spp_estimator.py:SppEstimator.__init__` | partial | — | `c_impl/test/test_reconfigure.c`[C]；`python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP] | [讀碼] `alpha`、q 夾到 (1e-6, 1−1e-6)、`prior_ratio = (1−q)/q`、`xi_min = 10^(xi_min_db/10)`。 |
| `src/spp_estimator.c:spp_init_scalars` | — | C-only | — | — | [讀碼] 配置後的純量初始化（heap 與靜態池共用）。 |
| `src/spp_estimator.c:spp_get_mem_size`、`src/spp_estimator.c:spp_destroy` | — | C-only | D-19 | `c_impl/test/test_config_validation.c`[C] | [稽核] 靜態記憶體池尺寸查詢與釋放。 |
| `src/spp_estimator.c:spp_create`、`src/spp_estimator.c:spp_init` | `core/spp_estimator.py:SppEstimator.__init__` | partial | D-19 | `c_impl/test/test_config_validation.c`[C]；`c_impl/test/test_reconfigure.c`[C] | [讀碼] 建構（heap／靜態池兩條路）；Python ctor 另含 frame prior 與 cross-band 參數。 |
| `src/spp_estimator.c:spp_dd_elem`（twin：`spp_dd_scalar`、`spp_dd_neon`、`spp_dd`） | `core/spp_estimator.py:SppEstimator.estimate#xi_dd` | mirror | — | `c_impl/test/test_anr_kernels.c`[CC]；`python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [README] DD：`xi = max(α·enhanced_prev/(N_prev+1e-10) + (1−α)·max(γ−1, 0), xi_min)`，分母用上一 hop 的噪聲底（c_impl/README「Fix #3: DD term 用前一幀 noise_psd」；Python `noise_psd_prev`）。 |
| `src/spp_estimator.c:spp_prepare` | `core/spp_estimator.py:SppEstimator.estimate#gamma` | partial | — | `c_impl/test/test_noise_restart.c`[C]；`python/tests/test_first_frame_gain.py`[PY] | [CHANGELOG][測試] γ、xi、v 與 `1+xi` 暫存。首幀（沒有 DD 歷史）用 `max(γ−1, xi_min)`，兩側同一下限（c_impl/CHANGELOG「初始化後第一幀的 a-priori SNR 下界」：C `spp_prepare`、Python `SppEstimator.estimate`）。C-only 分支：`gain_prev` 有而 `enhanced_psd_prev` 為 NULL 時的 `g²·γ_prev` 回退；Python 以 assert 禁止。 |
| `src/spp_estimator.c:spp_estimate` | `core/spp_estimator.py:SppEstimator.estimate` | partial | S-35、D-18 | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP]；`python/tests/test_first_frame_gain.py`[PY]；`python/tests/test_speech_protection.py`[PY] | [CHANGELOG] SPP = 1/(1 + ((1−q)/q)·(1+xi)·exp(−v))，並存下本幀噪聲底供下一 hop 的 DD。Python `estimate()` 另含 frame prior（`frame_prior_q_max`／`frame_prior_track`，C 無，S-35）與 cross-band 提升（C 在 `anr.c`）。exp(−v) 用 `sk_fast_exp_neg_f32` 近似（D-18）。 |
| `src/spp_estimator.c:spp_estimate_ex` | `core/spp_estimator.py:SppEstimator.estimate` | partial | — | `python/tools/parity_nr.py`[CP]＋`c_impl/example/parity_runner.c`[CP] | [稽核] 僅在 `USE_SHARED_XI_RATIO` 編譯；同 `spp_estimate`，另輸出 `v_out` 供增益階段反推 xi/(1+xi)。 |
| `src/spp_estimator.c:spp_reset` | `core/spp_estimator.py:SppEstimator.reset` | mirror | — | `c_impl/test/test_bit_exact_stream.c`[CC] | [讀碼] 清 `gamma_prev`、`noise_psd_prev` 與 is_initialized；Python 另清 cross-band／frame prior 狀態（C 的 cross-band 狀態在 `anr.c`，見 `reset_frame_evidence_state`）。 |

### 6.4 `include/anr_types.h`（config／retime／preset／驗證的 `static inline`）

| C 檔:函式 | Python 檔:符號 | 關係 | 已知落差 | 對拍／測試 | 依據與說明 |
| --- | --- | --- | --- | --- | --- |
| `include/anr_types.h:anr_nr_mode_is_valid` | `core/nr_strength.py:apply_strength` | partial | — | `c_impl/test/test_reconfigure.c`[C] | [讀碼] C：enum 白名單（bool）；Python：`strength not in NR_STRENGTH_PRESETS` 時 raise ValueError。測試只經 `anr_set_mode` 的無效 enum 案例間接走到，沒有直接呼叫。 |
| `include/anr_types.h:anr_nr_mode_from_name` | `core/nr_strength.py:nr_strength_name` | partial | — | `python/tests/test_nr_strength_index.py`[PY] | [CHANGELOG][測試] C：名稱或 `0`..`3` → enum，未知／NULL 回 −1。Python `nr_strength_name` 只把 `"0"`..`"3"` 換成名稱，其他值原樣通過給 argparse 的 `choices`。`test_nr_strength_index.py` 讀 `anr_types.h` 的 `ANR_MODE_*` 值核對索引（c_impl/CHANGELOG）。 |
| `include/anr_types.h:anr_nr_mode_name` | `core/nr_strength.py:NR_STRENGTH_PRESETS` | partial | — | `python/tests/test_nr_strength_index.py`[PY] | [註解][測試] enum → 名稱。Python `NR_STRENGTH_PRESETS` 的鍵順序即 C `AnrMode` 值順序（`nr_strength.py` 註解）。 |
| `include/anr_types.h:anr_default_fft_size` | `core/signal_grid.py:_DEFAULT_FFT`；`core/signal_grid.py:resolve_signal_grid` | mirror | — | `python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP] | [讀碼] 8 kHz → 128、16 kHz → 256、48 kHz → 1024；`resolve_signal_grid` 另檢查 grid 白名單（對應 C 的 `anr_validate_config`）。 |
| `include/anr_types.h:anr_retime_alpha_ref`、`include/anr_types.h:anr_retime_alpha` | `core/signal_grid.py:retime_ema_alpha` | mirror | — | `python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP] | [稽核][測試] `alpha^((hop/sr)/ref_hop)`：C 為 float32 `powf`（參考時長保持 double），Python float64。`test_config_parity` 對拍用它算出的設定欄位。輸入超出 [0, 1] 時 Python raise、C 原值回傳（作者讀碼）。 |
| `include/anr_types.h:anr_retime_frames` | `core/signal_grid.py:retime_frame_count` | mirror | — | `python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP] | [稽核][測試] 不縮短實際時長的幀數換算 `ceil(frames·ref·sr/hop − 1e-12)`：Python 用 double，C `anr_retime_frames` 用整數運算。`test_config_parity` 對拍用它算出的設定欄位。非正輸入 Python raise、C 回 0（作者讀碼）。 |
| `include/anr_types.h:anr_retime_frames_ms` | `core/signal_grid.py:retime_frame_count` | mirror | — | — | [讀碼] `anr_default_config()` 的 `config.L` 呼叫這個整數版（ceil 用 int64 ceiling division，同檔 `anr_retime_frames` 的手法；有溢位檢查）。在 5 個白名單 grid（8k/128、8k/256、16k/256、16k/512、48k/1024）上結果與 Python `retime_frame_count()` 相同（L=64/32/64/32/48）；差異只可能出現在 `L>320`（`anr_validate_config()` 拒收的範圍）。 |
| `include/anr_types.h:anr_default_config_for_grid`、`include/anr_types.h:anr_default_config` | `process_audio.py:build_v3_2_base_params`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__` | mirror | D-20 | `python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP] | [註解][測試][稽核] 預設（balanced）設定：Python 由 `config/v3_2_config.yaml` 經 `build_v3_2_base_params` 組出參數，再於 `MmseLsaDenoiser.__init__` retime；C 在 builder 內 retime（C 檔註解「sync with Python v3_2_config.yaml」）。`test_config_parity.py` 對拍 16k/256、16k/512、48k/1024 三個 grid × 4 個 strength，8 kHz 不在其中。`process_audio.py` 不在 core／denoisers 範圍，只因它是預設值的實際來源而列入。 |
| `include/anr_types.h:anr_config_for_mode_grid`、`include/anr_types.h:anr_config_for_mode` | `core/nr_strength.py:apply_strength`；`core/nr_strength.py:NR_STRENGTH_PRESETS` | mirror | — | `python/tests/test_config_parity.py`[CP]＋`c_impl/test/test_config_parity.c`[CP]；`python/tests/test_nr_strength_index.py`[PY] | [註解][測試] 四個 strength 只改 `g_min_db`／`q`／`xi_min_db`／`noise_over_subtraction`。`nr_strength.py` docstring 寫明鏡射 C `anr_config_for_mode`。 |
| `include/anr_types.h:anr_apply_speech_protection_experiment`、`include/anr_types.h:anr_apply_cross_band_speech_experiment` | — | C-only | — | `c_impl/test/test_bit_exact_stream.c`[CC]；`c_impl/test/test_config_validation.c`[C] | [讀碼] 整組實驗 overlay；repo 內只有 C 測試引用。Python 沒有同名函式，研究 CLI 以旗標逐欄設定（未逐值比對）。 |
| `include/anr_types.h:anr_finite_in_range`、`include/anr_types.h:anr_validate_config` | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.__init__`；`core/signal_grid.py:validate_signal_grid` | partial | S-34、D-19 | `c_impl/test/test_config_validation.c`[C] | [稽核] C：有限值＋範圍＋grid 白名單 fail-closed；Python：`__init__` 只有少數 raise（約 11 處）與 `validate_signal_grid`。邊界值上的不一致方向都是 Python 接受、C 拒絕（S-34）。 |

### 6.5 只有宣告、沒有實作的符號

目前沒有。新增時在此加列，關係欄標「宣告無實作」。

### 6.6 Python-only（C 沒有對應）

| C 檔:函式 | Python 檔:符號 | 關係 | 已知落差 | 對拍／測試 | 依據與說明 |
| --- | --- | --- | --- | --- | --- |
| — | `core/frame_processor.py:FrameProcessor` | Python-only | — | — | [註解] 分幀＋視窗＋rFFT。C 函式庫只做頻域核心（`anr.c` 檔頭：「Caller owns windowing, FFT/IFFT and overlap-add」），實際由 pipelines 與 `audiolib`（audio_stft）承擔。 |
| — | `core/reconstructor.py:Reconstructor` | Python-only | — | — | [註解] iFFT＋overlap-add，同上。 |
| — | `denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.denoise`；`denoisers/v3_2_mmse_lsa.py:MmseLsaDenoiser.get_params` | Python-only | — | — | [讀碼] `denoise()` = 分幀 → `denoise_spectrum` → 重建的時域包裝；`get_params()` 為診斷輸出。C 沒有時域入口。 |
| — | `core/spp_estimator.py:compute_spp_batch` | Python-only | — | — | [CHANGELOG] 離線批次 SPP（用簡化 Wiener 增益當 DD 的 gain_prev）；c_impl/CHANGELOG「初始化後第一幀的 a-priori SNR 下界」條目寫明該 Python 路徑與 C 無對應（「C 函式庫只對應 V3-2」）。 |
| — | `core/spp_estimator.py:_band_slice` | Python-only | — | — | [讀碼] 把可選的 [start, end) bin 範圍夾進頻譜的 helper；C 對應處理在 `_setup`（見該列）。 |
| — | `core/nr_modes.py:apply_mode` | Python-only | — | — | [讀碼] 只接受 `'full'` 的內容保留模式常數；C 沒有 content mode。 |
| — | `core/gain_calculators/pmmse.py:PmmseGainCalculator`；`core/gain_calculators/spectral_subtraction.py:SpectralSubtractionGainCalculator`；`core/gain_calculators/spp_mmse.py:SppMmseGainCalculator`；`core/gain_calculators/wiener.py:WienerGainCalculator` | Python-only | D-22 | — | [稽核] 其他增益計算器（V1／V2／V3／V3-3 用）；C 只實作 V3-2 的 MMSE-LSA。 |
| — | `core/noise_estimators/recursive_average.py:RecursiveAverageNoiseEstimator`；`core/noise_estimators/simple_average.py:SimpleAverageNoiseEstimator` | Python-only | D-22 | — | [稽核] 其他噪聲估計器。`MmseLsaDenoiser` 的 ctor 預設 `noise_method='recursive_average'`，出貨 YAML（`config/v3_2_config.yaml`）用 `mcra`；C 只有 MCRA 式追蹤器。 |
| — | `denoisers/base_denoiser.py:BaseDenoiser`；`denoisers/v1_spectral_subtraction.py:SpectralSubtractionDenoiser`；`denoisers/v2_wiener.py:WienerDenoiser`；`denoisers/v3_spp_mmse.py:SppMmseDenoiser`；`denoisers/v3_3_pmmse.py:PmmseDenoiser` | Python-only | D-22 | — | [README][稽核] 其餘 denoiser 版本與基底類別；`c_impl/README.md` 標示 C 以 V3-2 為主線、V4 wind handler 不移植。 |

<!-- MAP:END -->

## 附錄 A：落差編號

每個編號是一條 Python↔C 的已知落差（`S-` = 演算法或介面差異，`D-` = 刻意存在的差異，已文件化、非待修）。

<!-- IDS:BEGIN -->

| 編號 | 摘要 |
| --- | --- |
| `S-13` | `makeup_gain` 證據來源：Python 預設 `makeup_prior='spp'`、C 只有 xi 版（預設兩邊 makeup 皆關，休眠） |
| `S-34` | 設定範圍檢查不對稱：C `anr_validate_config` 嚴格 fail-closed，Python 幾乎不驗 |
| `S-35` | Python-only 的預設關閉研究旋鈕（`frame_prior_*`、`floor_blend`、`alpha_noise_up`、cross-band strength 等），C 不實作 |
| `D-18` | 出貨預設（fast-math＋六旗標）相對 Python 的數值偏差；量測見 `pyc_parity_nr` 的 L2 |
| `D-19` | 只存在 C 的機制與較嚴格驗證：`anr_reconfigure`／`anr_set_mode`／`anr_debug_status`／靜態記憶體池／`USE_FAST_PERCENTILE`／`anr_validate_config` |
| `D-20` | `makeup_prior_xi_db` 與 `alpha_g` 在 C 為惰性欄位（make-up 門檻借用 `noise_gate_xi_db`；見 `anr_types.h` 註解） |
| `D-22` | Python-only 研究旋鈕與其他版本（V1／V2／V3／V3-3、`recursive_average`…） |

<!-- IDS:END -->
