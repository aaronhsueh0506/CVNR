# 變更記錄 (Changelog)

本文件記錄所有重要的變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)。

## [Unreleased] - 2026-08-06 · Python public default-grid alignment

### 修復 (Fixed)

- Exported `core.FrameProcessor` now resolves omitted dimensions through the
  same project grid table as the denoisers: 8 kHz `128/64`, 16 kHz `256/128`,
  and 48 kHz `1024/512`. Its old constructor defaults silently selected the
  retired 16 kHz `512/256` default and made `FrameProcessor(sample_rate=48000)`
  invalid unless all dimensions were repeated manually. Partial explicit
  grids are now rejected; callers must either omit all three dimensions or
  provide `frame_size`, `frame_shift`, and `fft_size` together.

## [Unreleased] - 2026-08-03 · Audio_ALG C pipeline NR tuning A/B 決策：改用 canonical（B）

### 決策 (Decided)

**Audio_ALG mono C (`audio_pipeline.c`) 與 4ch C (`4aec_nr_res.c`) 原本各自硬編碼覆寫
`alpha_d=0.95`/`alpha_attack=0.3`（10ms 基準換算，pre-fix 公式），蓋過 `mmse_lsa_config_for_mode_grid()`
本身已經正確的 canonical 預設（`alpha_d=0.7` YAML 基礎值、`alpha_attack` 無條件 16ms 換算 —— 上一則
[4.5.0] 追加修復的同一批常數）。**這正是本專案這輪 source audit 抓到的：C 端「覆寫」實際上是在對抗自己
已經修好的 canonical 預設，導致 mono Python（已於本輪改用 canonical）、mono C、4ch C 三者 effective
config 分岔。

比對 A（legacy 硬編碼覆寫）vs B（canonical，即拿掉覆寫後 `mmse_lsa_config_for_mode_grid()` 的原樣輸出）：
逐欄位比對後，四個覆寫欄位裡只有 `alpha_d`／`alpha_attack` 真的有差（`L`：150 用舊 10ms 基準換算後與
canonical 的 pipeline-specific `L=94`-16ms-基準換算在每個 grid 都算出同一個 frame 數，是刻意設計成等價，
非巧合；`alpha_decay=alpha_g` 本來就與 canonical 一致）。

**兩條腿的實測證據**（16kHz/256/128 grid）：

| 腿 | 內容 | 結果 |
|---|---|---|
| VCTK+DEMAND 824-case（純去噪，無回音） | PESQ/STOI/SI-SDR/segSNR | B 只贏 PESQ（+0.14）；STOI/SI-SDR/segSNR 都是 A 較好，B 的 STOI 沒過本專案自己的回歸門檻（−0.026 vs 允許 −0.002，超標約 13 倍） |
| AEC 90-case blind manifest（回音+double-talk，這條 pipeline 實際使用場景） | AECMOS、ERLE-proxy、SDR-proxy、near-end preservation | AECMOS 在此樣本數下接近雜訊；ERLE-proxy／SDR-proxy／near-end 在全部 5 個 bucket 一致偏向 B，尤其在較可靠的大 bucket（movement n=25/26、NE n=30） |

VCTK 那條腿的 STOI 退步是真的，但 VCTK 是純去噪語料，不含回音——不是這條 pipeline 的實際使用場景
（這個 NR 元件在 Audio_ALG 裡永遠接在 AEC 後面處理殘留回音，從未單獨用於乾淨語料去噪）。實際使用場景
（AEC-chained leg）一致、雖幅度不大地偏向 B。

**決策：mono C／4ch C 改用 canonical（B）**——拿掉 `alpha_d`/`alpha_attack` 覆寫，讓
`mmse_lsa_config_for_mode_grid()` 的 canonical 預設直接生效（`L`/`alpha_decay` 保留原樣，因為兩者本來
就與 canonical 等價）。至此 mono Python／mono C／4ch C 三者共用同一份 effective config，不再各自維護
一份會漂移的覆寫。

新增 `c_impl/test/test_config_parity.c` + `test_config_parity.py`：對 3 個 grid（16k/256、16k/512、
48k/1024）× 4 個 strength（mild/moderate/balanced/aggressive）逐欄位比對 Python
`build_v3_2_base_params()+apply_strength()+MmseLsaDenoiser` 與 C `mmse_lsa_config_for_mode_grid()`
的 effective config（不是只測「兩邊都有 finite output」）。13/13 通過；mutation test 確認真的會抓到
偏移（人為在 C dump 注入 +0.05 的 `alpha_d` 偏移，13 項裡對應的 3 項立即 FAIL）。

**⚠ 這解決/取代上一則 [4.5.0] 留下的「未決策項」**：那則只單獨測了 `alpha_attack` 在 VCTK 上的影響；
這次是完整的 A/B（含 `alpha_d`）加上 AEC-chained 這條更貼近實際場景的證據，兩條腿放在一起看，比單獨看
`alpha_attack` 更有把握——採用 canonical 的理由不只是「歷史授權基準正確」，而是在貼近實際使用場景的
測試上也量測到一致（雖然幅度不大）的改善。

## [Unreleased] - 2026-08-03 · retiming 授權基準修復（追加）：`alpha_attack` 修正為無條件 16ms

### 修復 (Fixed)

**[4.5.0] 對 `alpha_attack` 的判斷有誤：`balanced` 並非真正 10ms 授權**

source audit（2026-08-03）指出 `alpha_attack=0.3` 在 `strength=='balanced'` 時仍套用 10ms 基準換算，
但其真正授權基準其實是 16ms——與 [4.5.0] 對 `alpha_g`/`alpha_decay`/`alpha_d` 的判斷（那三者確實是
10ms 授權，`balanced` 换算無誤）不同類。逐一以 git 歷史核實：

- `alpha_g`/`alpha_d`/`alpha_s`/`alpha_p`（YAML 基礎值）：commit `6bde3eb`/`02d7dc7`/`09e74d8`
  （2026-01-02～01-08）—— 全部早於 16ms-hop grid 切換（`04edc42`,2026-03-09）,10ms 授權判斷正確不變。
- `num_init_frames`（YAML=20）：`6bde3eb`（2026-01-02）,同樣早於切換,10ms 授權不變。
- `scene_change_min_frames` base（YAML=5）：`2c779bb`（2026-03-05）,早於切換 4 天,10ms 授權不變。
- **`alpha_attack` base（硬編碼 0.3,從未存在於 YAML——`config/v3_2_config.yaml` 自己註明「fixed in
  code,not configurable here」）：commit `b913beb`（2026-04-17）,晚於切換 5 週 —— 16ms 授權**,原本
  依 `strength` 條件式換算（`balanced`=10ms/其他=16ms）是錯的,應與 `alpha_xi`/`L` 一樣無條件 16ms。

修復：`denoisers/v3_2_mmse_lsa.py` 把 `alpha_attack` 移出共用的 `_preset_hop`/`_strength_is_post_16ms_preset`
機制,改為獨立、無條件 `authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS`；`c_impl/include/mmse_lsa_types.h`
的 `mmse_lsa_default_config_for_grid()` 同步把 `alpha_attack` 從 `mmse_lsa_retime_alpha()`（10ms)
改為 `mmse_lsa_retime_alpha_ref(..., 0.016)`（16ms)。strength 覆寫值（mild/moderate/aggressive 的
0.4/0.4/0.15,commit `6822129`）本來就已經是無條件 16ms,不受影響。

⚠ 非 byte-identical：新預設 16kHz/256/128 grid 上,`alpha_attack` 從錯誤的 0.380 變為（依證據）正確的
0.548。**824-case VCTK+DEMAND 已重跑,結果並非單純變好**——`full` 模式明顯退步（PESQ −0.0050,
STOI −0.0098,SI-SDR −0.821dB,segSNR −0.420dB）；`stationary` 模式反而持平略優（PESQ +0.0103,
SI-SDR +0.105dB,segSNR +0.096dB,STOI −0.0018 在雜訊範圍內）。也就是說：對 `alpha_attack` 授權基準
的判斷（16ms）本身有紮實 git 歷史證據支持,但套用後在最常用的 `full` 模式上量測到有感知意義的退步——
「歷史授權正確」與「感知品質更好」在這個常數上並不一致。

**⚠ 本項為未決策項,尚未視為可上線**：是否要接受這個退步以換取授權基準一致性,或改為保留舊的
（授權基準不精確但實測較好的）`alpha_attack` 處理方式,需要人為決策,不由本次修復單方面認定。程式碼
內的 provenance 註解本身（何時、哪個 commit 授權於哪個 grid）是紮實、值得保留的文件事實,與是否要讓
這個修正後的數值成為新預設輸出是兩件事。

## [4.5.0] - 2026-08-03 · retiming 授權基準修復 + 8ms-hop 預設 grid 擴展

### 修復 (Fixed)

**retiming 機制缺少「非 10ms 授權基準」表達能力，導致多個 16ms-hop 授權常數被錯誤地當成 10ms 授權常數 retime**
- 最直接案例＝ `noise_estimation.L`（MCRA 最小值追蹤視窗）：`config/v3_2_config.yaml` 明載 `L: 32` 是直接對 16ms
  hop 授權（「32 幀 × 16ms/hop = 512ms」），但 `denoisers/v3_2_mmse_lsa.py` 呼叫 retime 時完全沒有
  authored-hop override，一律套用內建 10ms 假設——連在 16ms-hop grid 本身也給出錯的 `L=20`（應為 32）。
- 同一根因也影響其餘已有明確 16ms 授權證據的常數：`alpha_xi`（2026-07-10 musical-noise fix,
  commit 6822129,直接對 16ms-hop grid 調校）；strength preset 覆寫值
  `alpha_g`/`alpha_attack`/`alpha_decay`/`alpha_d`（同一 commit；`balanced` 為空覆寫,其繼承值仍是真正
  10ms 授權,不受影響）；`stationary` mode 的 `alpha_d`/`alpha_xi`/`scene_change_min_frames`
  （2026-07-05 commit,同樣 16ms-hop 授權）。`num_init_frames` 等其餘鄰近常數已逐一確認無對應文件佐證,
  維持原 10ms 基準不變。
- 修復：兩端 retiming helper 新增 `authored_hop_seconds` 參數（預設 10ms＝行為不變）——Python 為
  `retime_ema_alpha`/`retime_frame_count`；C 新增 `mmse_lsa_retime_alpha_ref`/`mmse_lsa_retime_frames_ref`。
  `L`/`alpha_xi` 無條件套用 16ms 基準；`alpha_g`/`alpha_attack`/`alpha_decay`/`alpha_d` 依
  `strength`/`mode` 是否為 post-16ms-grid 覆寫條件式套用（`denoisers/v3_2_mmse_lsa.py` 新增 `strength`
  建構參數；`process_audio.py` 補上 `params['strength']`）；`scene_change_min_frames` 依
  `mode=='stationary'` 條件式套用。C 側鏡像於 `c_impl/include/mmse_lsa_types.h`。
- ⚠ 非 byte-identical：任何常數數值改變的 grid,輸出會隨之改變（例如舊 grid 上 `L` 20→32）。824-case
  VCTK+DEMAND 重跑顯示：standalone NR 這條路徑（`mcra_accept_external_spp: True`）下 `L` 實際是死碼
  （只驅動一個被外部 SPP 短路掉的內部指標),PESQ/STOI/SI-SDR/segSNR 全部無感知差異;真正會被 `L`
  影響的是 `accept_external_spp=False` 的 AEC-整合路徑,尚待該路徑自己的 benchmark 驗證。

**C 端浮點精度 bug：`mmse_lsa_retime_alpha_ref` / `mmse_lsa_retime_frames_ref` 的 `ref_hop_seconds` 誤用 `float`**
- Python 原生以 double 表示 `0.016`；C 若沿用 `float ref_hop_seconds`,`0.016f` 的精度誤差在
  `pow()`-based 的 alpha retiming 上因為是自我抵消的比值而無影響,但在 `ceil()`-based 的 frame-count
  retiming 上是 step function,把一個原本精確落在整數邊界的案例（16kHz/512 anchor grid 的 `L`）推過邊界
  幾個 ULP,令 rounding 結果整整多一幀（32 → 33）。
- 修復：`ref_hop_seconds` 參數改為 `double`；所有呼叫點字面量 `0.016f`/`0.010f` → `0.016`/`0.010`。

### 變更 (Changed)

**16kHz 預設 grid：512/256（16ms hop）→ 256/128（8ms hop）；8kHz 新增 128/64（8ms hop）預設，原
256/128（16ms hop）降為顯式替代選項**
- `core/signal_grid.py`：`_DEFAULT_FFT[16000]` 512→256、`_DEFAULT_FFT[8000]` 256→128；
  `_ALLOWED_FFTS[8000]` 由 `(256,)` 擴為 `(128, 256)`。C 端 `mmse_lsa_types.h` 的
  `mmse_lsa_default_fft_size()` / `mmse_lsa_validate_config()` 同步。16ms-hop grid（8kHz/256、
  16kHz/512）仍受支援,可顯式選用。
- 16ms「授權基準」（上面 retiming 修復的 anchor）與「目前預設 grid 是哪一個」正交獨立——本次 grid
  預設翻轉不影響 L/alpha_xi 等常數的授權基準判斷。

### 測試

`c_impl/test/test_config_validation.c`：舊斷言「L 至少保留 320ms」（沿用修復前 10ms 基準假設）已更正
為「至少保留 512ms」（32 幀 × 16ms,對應修復後正確值）；grid 清單同步加入新的 8000/128。`make
test-config` 全過（在無空白路徑重跑，原路徑空白字元會讓 Makefile 巢狀 -C 解析失敗,是既有已知問題）。

## [4.4.0] - 2026-07-10 · musical-noise fix + V3-2 強度預設（4 級）

### 修復 (Fixed)

**balanced 的 musical noise（root cause = ξ 抖動經 SPP 放大）**
- `config/v3_2_config.yaml`：`alpha_xi 0.88 → 0.92`（DD ξ 平滑 lever，全預設共用）。musical noise 來自
  未平滑的 ξ 經 SPP（`G=G_H1^spp·g_min^(1-spp)` 的指數）放大成孤立增益尖峰；提高 alpha_xi 即壓掉。
- 語音守門（12-file PESQ/STOI 拆解）：alpha_xi 幾乎零成本（PESQ −0.001）；額外 attack/decay 平滑對音樂
  只再 −4% 卻吃掉語音（PESQ −0.021 / segSNR −0.38），已捨棄。stationary 模式（已用 0.92）不受影響。

### 新增 (Added)

**V3-2 強度預設（深度軸，`mild | moderate | balanced | aggressive`）**
- 新 `core/nr_strength.py`：`NR_STRENGTH_PRESETS` + `apply_strength`，鏡像 C `mmse_lsa_config_for_mode`。
  深度 g_min = −20/−25/−30/−40 dB；`moderate` 為本次新增（mild↔balanced 之間）；`aggressive` 加重下游平滑
  （alpha_g 0.75→0.85）壓深度帶回的 speckle。與內容軸（full/stationary）正交，先 strength 再 mode。
- CLI：`process_audio.py --nr-mode {mild,moderate,balanced,aggressive}` + `--mode {full,stationary}`
  （之前 mode 只有函式 kwarg，未上 CLI，本次補上）。
- `tools/ablate_nr_music.py`：committed ablation（4 級 × wav + 頻譜圖 + musical_noise/suppression_db 表）；
  `utils/metrics.py` 新增 `suppression_db`。`process_audio.build_v3_2_base_params` 抽出共用。
- 測試音 `test_wav/music/fix_gain_{music,noise}.wav`。

### C 對齊

`c_impl`：`mmse_lsa_types.h` 加 `MMSE_LSA_NR_MODERATE`、default alpha_xi 0.92、config_for_mode 4 級；
`main.c` / `parity_runner.c` / `tools/parity_nr.py` 加 strength 軸。4 級 std-math **C↔Python bit-exact**
（worst ~1e-5）；stationary 仍 bit-exact。

## [4.3.0] - 2026-07-05 · stationary 內容保留模式 + gain-floor 單位對齊

### 新增 (Added)

**V3-2 `stationary` 內容保留模式**（Python + C，`mode: {full | stationary}`）
- `full`（預設）＝現行全消，空 overlay → 與原 V3-2 **byte-identical**。
- `stationary` ＝只移除穩態底噪、保留語音／音樂／瞬態。機制 = Wiener 增益下界 `gain ≥ (ξ/(β+ξ))^p`
  （p=2，`core/gain_calculators/mmse_lsa.py`）+ MCRA music-aware tonal-veto scene-change。**下界僅 stationary
  生效**（`stationary_floor` 預設 false）。架構 = `core/nr_modes.py` `NR_MODE_PRESETS` + `apply_mode`。
- C 端：`denoise_wav --stationary`、`mmse_lsa_apply_stationary()`（overlay，疊在 `--nr-mode` base 上）；
  parity harness 加 `--mode`，std-math **C↔Python bit-exact**（full worst 6e-5 / stationary 1.3e-5）。

### 變更 (Changed)

**gain-floor dB 對齊 audio 振幅慣例（/10 → /20）**
- `g_min_db`（及 `spp_protect_floor_db`）改用 `10^(db/20)`：gain 直接乘幅度譜（無 sqrt），故 floor 是振幅量。
- **所有 shipped 值加倍以保持行為不變**（v3-2 −15→−30、v3−19.5→−39、v3-3 −14→−28，皆同一線性 floor）。
- 涵蓋 mmse_lsa / spp_mmse / pmmse、denoisers、C（mmse_lsa_denoiser.c / mmse_lsa_types.h）。
- xi_min_db / delta_db / scene_change 為 SNR/功率 dB，維持 /10 不變。AEC 未動（功率域 floor 再 sqrt，本就正確）。

### 移除 (Removed)
- 舊「V4 wind-handler」子系統整個移除（16 檔）；adaptive-q lever 驗證 NO-SHIP 後移除。

## [4.2.2] - 2026-06-11 · IMCRA 正名 + D2 修復

### 修復 (Fixed)

**噪聲估計器正名：IMCRA（非 plain MCRA）**

V3-2 的噪聲估計器在 v2.0 起實際上即為 IMCRA（Cohen 2003），但一直以 `McraNoiseEstimator` 命名，導致 D2 commit 將其錯誤改回 plain MCRA，造成 VCTK/DEMAND 824 檔 ΔPESQ −0.632（獨立 NR 嚴重退步）。

| 項目 | 內容 |
|------|------|
| 根因 | D2 移除外部 OM-LSA posterior SPP 傳入 MCRA noise gate，改用內部 binary ratio-test；IMCRA 設計明確要求兩者耦合（Cohen 2003 Table II） |
| 差異 | IMCRA posterior 帶 DD 歷史（alpha_xi=0.98），語音邊界不誤更新；plain MCRA 的 indicator 無 SNR 記憶 |
| AEC pipeline | 殘餘 echo 導致 OM-LSA posterior 在噪聲段被拉高 → AEC context 改用 plain MCRA 保護 |

**具體修改**：

1. **恢復 IMCRA 耦合**（`core/noise_estimators/mcra.py`）
   - 新增 `accept_external_spp: bool = True` constructor param
   - `spp_for_update = spp if (accept_external_spp and spp is not None) else self.spp`
   - 預設 True = IMCRA mode（standalone NR）；False = plain MCRA（AEC pipeline）

2. **透傳 flag**（`denoisers/v3_2_mmse_lsa.py`）
   - 新增 `mcra_accept_external_spp=True` constructor param，透傳給 `McraNoiseEstimator`

3. **AEC pipeline 使用 plain MCRA**（`Audio_ALG/pipelines/aec_nr_pipeline.py`）
   - `_build_denoiser()` 加 `mcra_accept_external_spp=False`

4. **命名文件化**（`core/noise_estimators/__init__.py`）
   - 加 `ImcraNoiseEstimator = McraNoiseEstimator` alias

### 驗證 (Validation)

VCTK/DEMAND **824 檔**完整比較（standalone NR, `v3_2_config.yaml`，6 workers）：

| 配置 | PESQ noisy | PESQ enhanced | ΔPESQ | STOI noisy | STOI enhanced | ΔSTOI |
|------|-----------|--------------|-------|-----------|--------------|-------|
| IMCRA mode（此修復後） | 1.967 | 2.145 | +0.178 | 0.921 | 0.851 | −0.070 |
| plain MCRA mode（D2 regression） | 1.967 | 1.514 | −0.454 | 0.921 | 0.793 | −0.128 |
| **D2 regression 效應** | — | — | **−0.632** | — | — | **−0.058** |

---

## [4.2.1] - 2026-04-17 · C-Alignment Release

### 變更 (Changed)

Python V3-2 OMLSA 調整為與 C 實作 **bit-exact 對齊**（float32 精度極限內）。以同一配置（16 kHz / MCRA / 同參數）處理 `babble_10dB_16k.wav`：

- 對齊後 correlation: **0.99999994**
- Median sample-level `|diff|`: **1.65e-5**
- 99% samples `|diff|` < **3.3e-5**
- 99.98% samples `|diff|` < 1e-4

三項 Python 語義調整（**會改變 Python V3-2 於 MCRA 模式的數值輸出**）：

1. **MCRA 初始化 percentile 改為 k-th 最小值**
   - 檔案: `core/noise_estimators/mcra.py` `estimate()`
   - 原: `np.percentile(power, 30, axis=0)`（線性插值 sorted[k] 與 sorted[k+1]）
   - 新: `np.partition(power, k, axis=0)[k]`，`k = ((N-1)*30)//100`
   - 原因: C 端 `calculate_percentile()` 使用 quickselect 直接取 k-th 元素，兩者對高變異 bin 可差 ~30%

2. **V3-2 denoise_spectrum init 階段改為嚴格 passthrough**
   - 檔案: `denoisers/v3_2_mmse_lsa.py` `denoise_spectrum()`
   - 原 (Fix #2 輕量版): 前 20 幀仍呼叫 SPP、計算 gain、套用 gain（但跳過 noise update）
   - 新: 前 20 幀 `gain = 1.0`（strict passthrough），不呼叫 SPP estimate，DD state 設為 `(gain_prev=1.0, enhanced_psd_prev=Y_psd)`
   - 原因: C streaming API 於 init 期間只能 passthrough（缺 look-ahead），Python 配合保持兩端同語義
   - 影響: 前 200 ms 輸出變為 raw input（而非經 MMSE-LSA 處理）

3. **MmseLsaGainCalculator 預設改用 3-segment E1 近似**
   - 檔案: `core/gain_calculators/mmse_lsa.py`
   - 原: 預設使用 `scipy.special.exp1`（Taylor + continued fraction，精確）
   - 新: 預設使用 `_exp1_approx`（三段對數/指數近似），與 C `exp1_approx` 公式完全一致
   - 切回 scipy: 在 caller 設 `mmse_lsa_mod.USE_SCIPY_EXP1 = True`（預設 `False`）
   - 原因: C 端不會鏈結 scipy，兩端 E1 必須用相同近似才能 bit-exact
   - 影響: E1(v) 精度損失 ~1e-4 absolute，gain 差 ~1e-3 level；對 PESQ/STOI 實際影響極小（主要在極低 SNR 的少數 bin）

### 驗證 (Validation)

**C/Python 對齊**（同配置 16 kHz/MCRA/debug C build）：
- Aligned correlation **0.99999994**
- Median `|diff|` 1.65e-5，99% 3.33e-5，max 5.9e-3（isolated spike）
- 99.98% post-500 ms 樣點 `|diff|` < 1e-4

**VCTK/DEMAND regression**（824 檔，`v3_2_config.yaml`，C1 baseline vs v4.2.1 C-aligned）：

| 指標 | C1 baseline | v4.2.1 | Delta |
|---|---|---|---|
| PESQ | 2.410 | **2.391** | **−0.019** ✓（目標 < 0.02） |
| STOI | 0.914 | 0.906 | −0.008 |
| segSNR (dB) | +4.88 | +4.21 | −0.67 |
| fwSegSNR (dB) | +1.80 | +1.22 | −0.58 |
| LSD | 13.22 | 14.68 | +1.46（變差） |

**結論**：
- **PESQ 退步 0.019 在 release 可接受範圍內**；使用者聽感差異極小
- segSNR / LSD / fwSegSNR 退步屬 **預期代價**，主要來自 3-segment E1 近似（用來與 C `exp1_approx` bit-exact 對齊）
- 若研究或離線工具需要較高精度，設 `core.gain_calculators.mmse_lsa.USE_SCIPY_EXP1 = True` 即可恢復 scipy.special.exp1 路徑，但 C/Python 將無法 bit-exact

---

## [4.2.0] - 2026-04-17 · Release

### 新增 (Added)

**Part A Review 修復（Python + C 雙 branch 同步）**
- **Fix #1**: MCRA `estimate()` 改 `self.S = init_psd.copy()`（原為 `np.mean(power_spectrum, axis=0)`）——與 `S_min` 一致，避免首幀 `S/(S_min·δ)` 異常
- **Fix #3**: SPP Decision-Directed `xi_dd_term1` 改用**前一幀** `noise_psd`；新增 `self.noise_psd_prev` 狀態，每幀尾端 `copy()` 保存
- **Fix #6**: `scene_change_flatness_threshold` 配置參數化（預設 0.4），同步到 C `MmseLsaConfig`
- **Fix #7**: `frame_processor.py` window 改為 `scipy.signal.windows.*(N, sym=False)`（periodic）
- **Fix #9**: SPP `q` 於 `__init__` / `spp_create()` clip 到 `(1e-6, 1-1e-6)`；移除分母 `+1e-10` 補丁
- **Fix #4/#5**: Denoiser `__init__` 新增 `alpha_d`、`use_asymmetric_smoothing`、`alpha_attack`、`alpha_decay` 參數外露
- **Fix #2**: `denoise_spectrum()` 前 `num_init` 幀 lightweight passthrough（gain=1、spp=0、enhanced_psd=|Y|²）
- **Fix #8**: `denoise_spectrum()` 入口 auto `reset()`，避免跨呼叫狀態污染
- **Fix #10/#11**: 清理過時 Soft VAD 註解與 `__main__` demo

**V4 OMLSA 研究框架（不 release 使用）**
- 新增 `denoisers/v4_omlsa.py`、`core/wind_detector.py`、`core/freq_adaptive_controller.py`、`core/transient_suppressor.py`
- VCTK/DEMAND 驗證顯示 V4 無法改善風聲場景（根因：風聲低頻與語音 F1/F2 頻譜重疊）
- 預設 `config/v4_config.yaml` 採 FLAT adaptive profile + transient OFF（等同 V3-2）
- 產出診斷報告：`results/v4_diagnosis_report.md`、`results/v4_validation_report.md`、`results/next_steps_recommendations.md`

**C 實作同步**
- Part A 4 項核心 fix 已 port 至 `c_impl/` (#1, #3, #6, #9)
- Build & smoke verified：輸出 bit-exact

**文檔重構**
- README / c_impl/README / parameter_adjust_guide / ALGORITHMS_EXPLANATION 全數更新
- 新增「使用條件」、「調參指引」、「風聲/衝擊等不適用情境」章節
- c_impl/README.md 修正 frame_size / hop_size 預設值顯示（原誤為 512/256）
- 各文件加入 v4.2 版本統一標記；V4 舊/新章節命名衝突已註記

### 修復 (Fixed)
- C 與 Python V3-2 演算法端對齊（Part A 之前 C 端就缺這些 fix）
- `tools/validate_best_config.py` 補齊 `enhanced_psd_prev` 參數（Fix #3 連帶修正）

### 驗證 (Validation)
- C pre-fix vs post-fix：輸出差異 −37 dB（相對輸入），init 200 ms passthrough 區完全 bit-exact，符合 fix 範疇
- C post-fix vs Python V3-2：對齊後 correlation 0.58，RMS 差 +0.36 dB（符合 `scipy.special.exp1` vs `exp1_approx` 的既有漂移）

---

## [4.1.0] - 2026-03-04

### 重大變更 (Breaking Changes) 🚨

**Eta 機制完全移除**
- 測試證明 L=5 優化已替代 eta 功能，無需額外的場景轉換偵測
- test_wav (穩定噪聲): enable_eta 降低 PESQ 0.06-0.41
- VCTK/DEMAND (非穩態噪聲): enable_eta 收益僅 0.006 PESQ（可忽略不計）
- 移除所有 eta 相關代碼和配置參數（Python + C）

**C 實現同步 Python V3-2 (v4.0) 優化參數**
- `alpha_s`: 0.8 → 0.7 (更快時間響應，無 PESQ 損失)
- `L`: 120 → 5 (場景適應速度提升 24 倍：1.2s → 50ms)
- `init_percentile`: 20th → 30th (更準確的噪聲初始化)
- 與 Python 實現完全一致，消除參數差異

### 移除 (Removed)

**Python 代碼**:
- `core/noise_estimators/mcra.py`:
  - 移除 `enable_eta`, `eta_beta_threshold`, `eta_slope` 參數
  - 移除 `_compute_eta_from_ratio()` 方法
  - 移除 SPP 歷史追蹤和 eta 計算邏輯
  - 移除 eta 狀態變量（`_prev_frame_power`, `_energy_smooth`, `_spp_history`, `_eta_cooldown`）
- `denoisers/v3_spp_mmse.py`, `v3_2_mmse_lsa.py`, `v3_3_pmmse.py`:
  - 移除所有 eta 參數傳遞
- `config/v3_2_config.yaml`:
  - 移除 eta 配置塊
- `process_audio.py`, `regenerate_all.py`:
  - 移除 eta 參數處理代碼

**C 代碼**:
- `c_impl/include/mmse_lsa_types.h`:
  - 移除 `enable_eta`, `eta_beta_threshold`, `eta_slope` 配置成員
  - 更新默認配置為 v4.0 參數
- `c_impl/src/mcra_noise_estimator.c`:
  - 移除 eta 結構體成員和狀態變量
  - 移除能量累加和 eta 計算邏輯
  - 簡化噪聲更新公式（移除 eta 乘法）
  - 更新初始化百分位數（20 → 30）
- `c_impl/example/main.c`:
  - 移除 `enable_eta` 設置

**測試腳本（已歸檔至 `archived_eta_tests/`）**:
- `compare_eta_full.py`
- `compare_spp_eta.py`
- `test_eta_configs.py`
- `test_eta_params.py`
- `test_eta_vad_comparison.py`
- `diagnose_eta.py`
- `visualize_eta_curve.py`

### 性能提升 (Performance)

- 場景轉換適應時間: 1.2s → 50ms（提升 24 倍）
- MCRA 最小值緩衝記憶體: 240KB → 10KB（48kHz，節省 96%）
- 代碼簡化: 移除約 200 行 eta 相關代碼
- 維護性提升: 消除 Python/C 參數差異

### 文檔更新 (Documentation)

- `README.md`: 添加 v4.1 條目，標記 eta 機制為已棄用
- `c_impl/README.md`: 添加 v4.0/v4.1 同步說明，更新默認參數表
- `ALGORITHMS_EXPLANATION.md`: 標記 eta 章節為已棄用（保留作為歷史參考）
- `parameter_adjust_guide.md`: 更新 v4.0 最終參數表
- `ETA_ANALYSIS.md`: 保留作為測試結果歷史記錄
- `MCRA_SCENE_CHANGE_ANALYSIS.md`: 記錄 L=5 優化原理

### 技術細節 (Technical Details)

**為什麼移除 Eta？**

1. **L=5 追蹤極快**: S_min 僅需 50ms 即可追蹤新噪聲，遠快於噪聲估計收斂時間（195ms）
2. **SPP 自動調整**: 場景變化時 SPP 自動降低，噪聲更新自動加速
3. **Eta 收益極小**: 理論上可節省 ~150ms，但實際 PESQ 收益僅 0.006（可忽略）
4. **Eta 風險更大**: 誤觸發導致 PESQ 下降 0.06-0.41，場景轉換罕見不值得增加風險

**測試驗證**:
- ✅ L 從 120→5: ΔPESQ = 0.0000（完全無負面影響）
- ❌ enable_eta: ΔPESQ = -0.06 到 -0.41（明顯降低性能）

### 修改文件

1. `core/noise_estimators/mcra.py`
2. `denoisers/v3_spp_mmse.py`, `v3_2_mmse_lsa.py`, `v3_3_pmmse.py`
3. `config/v3_2_config.yaml`
4. `process_audio.py`, `regenerate_all.py`
5. `c_impl/include/mmse_lsa_types.h`
6. `c_impl/src/mcra_noise_estimator.c`
7. `c_impl/example/main.c`
8. `README.md`, `c_impl/README.md`, `CHANGELOG.md`, `c_impl/CHANGELOG.md`

---

## [4.0.0] - 2026-03-03

### 新增 (Added)
- ✨ **V4: MCRA-MMSE-LSA with Zhihu Optimized Parameters**:
  - 基於 V3-2，採用知乎文章建議的激進參數組合
  - 配置文件: `config/v4_config.yaml`
  - 使用 `MmseLsaDenoiser` 類（與 V3-2 共用實現）

### 修改 (Changed)
- ⚠️ **MCRA 默認參數調整（高風險修改）**:
  - `alpha_s`: 0.9 → 0.7 (更快時間響應)
  - `alpha_d`: 0.85 → 0.0 (噪聲更新純 SPP 控制，極度激進)
  - `L`: 96 → 5 (最小值窗口從 960ms 縮短到 50ms，極度激進)
  - `init percentile`: 20th → 30th (更準確的初始化)
  - ⚠️ **風險**: alpha_d=0 + L=5 組合極度依賴 SPP 準確性，需測試驗證

- 🔧 **移除 Decision Directed 兼容模式**:
  - `core/spp_estimator.py`: 強制要求傳入 `enhanced_psd_prev`
  - 移除使用舊噪聲的錯誤近似計算
  - 確保所有 SNR 估計使用當前幀噪聲

### 修正 (Fixed)
- 🐛 **Eta 場景轉換偵測默認關閉**:
  - 測試結果證明 eta 導致 PESQ 下降（threshold=2 平均 -0.41, threshold=10 平均 -0.06）
  - 無法區分"語音開始"與"場景變化"，容易誤觸發
  - Python 配置: `enable_eta: false`
  - C 實現: `config.enable_eta = false`

### 歸檔 (Archived)
- 📦 **舊 V4 IMCRA-OMLSA 版本歸檔**:
  - 移動到 `archived_v4_imcra/` 目錄
  - 包含: `v4_imcra_config.yaml`, `v4_imcra_omlsa.py`
  - 理由: 新 V4 採用不同的演算法路線（MCRA vs IMCRA）

### 修改文件
1. `core/noise_estimators/mcra.py` - 默認參數調整、初始化百分位數
2. `core/spp_estimator.py` - 移除 DD 兼容模式
3. `config/v4_config.yaml` - 新建 V4 配置
4. `c_impl/example/main.c` - Eta 默認關閉
5. `README.md` - 版本更新
6. `CHANGELOG.md` - 記錄變更

### 測試結果 (2026-03-03)

**完整測試**: 13 個測試文件 (8 test_wav + 5 VCTK)

#### Alpha_d 優化測試
| alpha_d | 平均 PESQ | ΔPESQ | 說明 |
|---------|----------|-------|------|
| 0.95 | 2.127 | 0.000 | ✓ **最佳**（V3-2 baseline） |
| 0.85 | 2.121 | -0.006 | 非常接近 |
| 0.70 | 2.102 | -0.024 | 輕微下降 |
| 0.50 | 2.087 | -0.040 | 明顯下降 |
| 0.30 | 2.067 | -0.060 | 顯著下降 |
| 0.00 | 2.034 | -0.092 | ⚠️ **知乎原始值，效果最差** |

**明確趨勢**: alpha_d 越高，PESQ 越好

#### 逐步參數測試
| 配置 | ΔPESQ | 結論 |
|------|-------|------|
| 僅改 alpha_s (0.8→0.7) | 0.0000 | ✓ 無負面影響 |
| alpha_s + L (120→5) | 0.0000 | ✓ **L=5 無負面影響** |
| alpha_s + alpha_d (0.95→0) | -0.1524 | ⚠️ **alpha_d=0 是唯一問題** |
| V4 Full (知乎原始參數) | -0.1524 | ⚠️ 效果最差 |

#### 測試腳本
- `compare_v4_v32.py`: V4 vs V3-2 baseline 比較（初步測試）
- `test_v4_gradual.py`: 逐步參數測試，分離每個參數的影響
- `test_v4_vctk_scene.py`: VCTK + 場景轉換測試
- `find_best_alpha_d.py`: 系統性 alpha_d 優化測試

### 最終決策
基於測試結果，V4 最終採用：
- ✓ **alpha_s = 0.7**: 知乎建議，測試證明無負面影響
- ✓ **L = 5**: 知乎建議，測試證明無負面影響且響應更快
- ✗ **alpha_d = 0**: 知乎建議，**測試證明造成 -0.092 PESQ 下降，不採用**
- ✓ **alpha_d = 0.95**: 保持 V3-2 baseline，測試證明最佳

**結論**: 知乎文章的 alpha_s 和 L 參數有效，但 alpha_d=0 不適用於一般語音降噪場景。

## [2.7.0] - 2026-02-03

### 修正 (Fixed)
- 🐛 **MCRA Eta 場景轉換偵測修正 (Strategy K)**:
  - 舊版 sigmoid `η = 0.95 / (1 + e^(slope*(β-θ)))` 上限 0.95 導致語音幀 `tilde_alpha_d` 下降，噪聲更新速度增加 ~10x
  - 新版: 平滑能量比 + hard threshold
    - `E_smooth = 0.7 * E_smooth_prev + 0.3 * E_cur`
    - `β = E_smooth / E_smooth_prev`
    - `β > θ` → `η = 0.1`（場景突變，加速噪聲更新）
    - `β ≤ θ` → `η = 1.0`（正常，完全不干擾 α_d）
  - VCTK/DEMAND 824 files 驗證:
    - 舊 eta: PESQ +0.085, STOI -0.068
    - 新 eta: PESQ +0.399, STOI -0.010
    - 不開 eta: PESQ +0.437, STOI -0.007

### 修改文件
1. `core/noise_estimators/mcra.py` - `_compute_eta()` 方法重寫
2. `c_impl/src/mcra_noise_estimator.c` - 對應 C 實作更新

## [2.5.0] - 2026-01-16

### 重構 (Refactored)
- ✨ **MCRA 單/雙視窗模式切換**: 新增 `use_dual_window` 參數
  - `True` (預設)：雙視窗模式，記憶體效率高 O(3×n_freqs)
  - `False`：單視窗 FIFO 緩衝區模式 O(L×n_freqs)
  - 方便效果比較實驗

- 🧹 **清理冗餘程式碼**:
  - 移除 `spp_estimator.py` 的 fast startup 功能 (死代碼)
  - 移除 `imcra.py` 的 fast tracking 功能 (死代碼)
  - 移除 `reconstructor.py` 的 `apply_gain()` 和 `reconstruct_from_spectra()` 方法 (未使用)
  - 保留 `recursive_average.py` 的 fast 功能 (可能有用)

### 驗證 (Verified)
- ✅ **IMCRA 最小值重置邏輯正確**: 確認 Cohen 2003 FIFO 緩衝區方法的遺忘機制
  - `S_min_sw = S_smoothed.copy()` 在第 213 行存在
  - 每 V 幀重置子視窗最小值
  - 噪聲增加時最多 L = U × V 幀後追上

### 修改文件
1. `core/noise_estimators/mcra.py` - 添加 `use_dual_window` 參數，支持單/雙視窗切換
2. `core/spp_estimator.py` - 移除 fast startup 相關代碼
3. `core/noise_estimators/imcra.py` - 移除 fast tracking 相關代碼
4. `core/reconstructor.py` - 移除未使用的方法

---

## [2.4.0] - 2026-01-12

### 新增 (Added)
- ✨ **V3-2 return_spp 支持**: 添加 SPP 歷史數據返回功能
  - `denoise()` 方法新增 `return_spp` 參數
  - `denoise_spectrum()` 方法新增 SPP 收集邏輯
  - 與 V3, V3-3, V3-4 統一 API

### 改進 (Changed)
- ⬆️ **V3 系列 50-trial Optuna 參數優化**
  - 目標函數: 0.8×PESQ + 0.2×STOI
  - 固定 SPP 參數: alpha_xi=0.95, q=0.3, xi_min_db=-25.0
  - 僅優化 Gain 參數: g_min_db, alpha_g
  - 移除 0dB SNR 測試 case

- ⬆️ **優化結果更新至配置文件**:
  | 版本 | g_min_db | alpha_g | ΔPESQ |
  |------|----------|---------|-------|
  | V3   | -15.0    | 0.85    | +0.403 |
  | V3-2 | -15.0    | 0.90    | +0.399 |
  | V3-3 | -15.0    | 0.85    | +0.354 |
  | V3-4 | -25.0    | 0.85    | +0.197 |

- ⬆️ **SPP 可視化配色方案**: `gray_r` 取代 `jet`
  - 更直觀：黑色=高 SPP（語音），白色=低 SPP（噪聲）
  - 符合 SPP 物理意義

### 修改文件
1. `config/v3_config.yaml` - g_min_db=-15.0, alpha_g=0.85
2. `config/v3_2_config.yaml` - g_min_db=-15.0, alpha_g=0.90
3. `config/v3_3_config.yaml` - g_min_db=-15.0, alpha_g=0.85
4. `config/v3_4_config.yaml` - g_min_db=-25.0, alpha_g=0.85
5. `denoisers/v3_2_mmse_lsa.py` - 添加 return_spp 支持
6. `utils/visualization.py` - SPP colormap 改為 gray_r
7. `tools/parameter_optimizer.py` - 固定 SPP 參數，搜索空間調整

---

## [2.3.0] - 2026-01-08

### 重構 (Refactored)
- ✨ **整合場景轉換偵測至 MCRA**：移除外部 NoiseChangeDetector 和 TransitionDetector
  - 使用 Cohen & Berdugo 的 Dual-Window Minima Tracking 方法
  - MCRA 內建處理噪聲場景變化，每 L 幀自動更新最小值
  - 簡化降噪器架構，移除 `enable_noise_tracking` 參數

### 改進 (Changed)
- ⬆️ **MCRA 雙視窗最小值追蹤**：
  - 新增 `S_min_sw` (子視窗最小值)
  - 新增 `stored_min` (存儲的最小值)
  - 新增 `counter` (視窗計數器)
  - 移除 `min_buffer` (FIFO 緩衝區)

### 技術細節 (Technical Details)

#### Dual-Window Minima Tracking

```python
# 雙視窗最小值追蹤 (Cohen & Berdugo 2002)
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

**優點**:
- 內建場景變化適應
- 減少程式碼重複
- 消除邏輯衝突
- 簡化降噪器介面

### 刪除 (Removed)
- ❌ `core/noise_change_detector.py` - 外部噪聲變化檢測器
- ❌ `core/transition_detector.py` - 外部場景轉換檢測器
- ❌ 所有降噪器的 `enable_noise_tracking` 參數
- ❌ `trigger_fast_adaptation()` 方法

### 修改文件
1. `core/noise_estimators/mcra.py` - 升級為雙視窗最小值追蹤
2. `denoisers/v3_spp_mmse.py` - 移除 NoiseChangeDetector
3. `denoisers/v3_2_mmse_lsa.py` - 移除 NoiseChangeDetector
4. `denoisers/v3_3_pmmse.py` - 移除 NoiseChangeDetector 和 TransitionDetector
5. `denoisers/v3_4_laplacian_mmse.py` - 移除 NoiseChangeDetector
6. `denoisers/v4_imcra_omlsa.py` - 移除 NoiseChangeDetector
7. `regenerate_all.py` - 移除 enable_noise_tracking 參數處理
8. `process_audio.py` - 移除 enable_noise_tracking 參數處理

---

## [2.2.0] - 2026-01-08

### 新增 (Added)
- ✨ **V2.2 版本發布**: Wiener Filter with DD + SPP-gated noise update
  - 啟用 Decision-Directed (DD) 方法估計先驗 SNR
  - 使用 Sigmoid(gamma-1) 近似 SPP 進行軟判決噪聲更新
  - ΔPESQ: +0.035 (相較噪聲輸入)

- ✨ **V2 MCRA 噪聲估計支持** (實驗性)
  - 新增 MCRA 噪聲估計器選項
  - 改進 MCRA 初始化：使用 20th 百分位數避免語音幀污染
  - 注意：MCRA 對 V2 Wiener 效果有限，建議使用 recursive_average

### 改進 (Changed)
- ⬆️ **V3-3 (PMMSE) 重新實作**
  - 使用 Wolfe & Godsill (2003) β=0.5 公式
  - G_PM = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)
  - 使用 `scipy.special.i0e` 避免數值溢出
  - ΔPESQ: +0.339

- ⬆️ **V3-4 (Laplacian-MMSE) 重新實作**
  - 使用 Chen & Loizou (2007) 公式
  - G_Lap = (sqrt(π)/2) · sqrt(v) · exp(-v/2) · I0(v/2)
  - Laplacian 先驗適合語音頻譜稀疏性
  - ΔPESQ: +0.376

### 文檔 (Documentation)
- 📝 **各版本噪聲估計方法說明**

| 版本 | 噪聲估計器 | SPP 來源 | 說明 |
|------|-----------|---------|------|
| V1 | SimpleAverage | 無 | 前 N 幀平均 |
| V2 | RecursiveAverage | Sigmoid 近似 | DD 方法估計先驗 SNR |
| V3~V3-4 | RecursiveAverage | SppEstimator (Bayesian) | 貝葉斯 SPP 軟判決 |
| V4 | IMCRA | 內部兩階段計算 | Cohen 2003 兩階段結構 |

### 修改文件
1. `config/v2_config.yaml` - 更新為 V2.2，添加詳細說明
2. `config/v3_3_config.yaml` - 添加 Wolfe & Godsill 公式說明
3. `config/v3_4_config.yaml` - 添加 Chen & Loizou 公式說明
4. `core/gain_calculators/pmmse.py` - Wolfe & Godsill β=0.5 實作
5. `core/gain_calculators/laplacian_mmse.py` - Chen & Loizou 實作
6. `core/noise_estimators/mcra.py` - 改進初始化策略
7. `denoisers/v2_wiener.py` - 支持 MCRA 噪聲估計
8. `regenerate_all.py` - 支持 V2 MCRA 參數

---

## [2.1.2] - 2026-01-06

### 修復 (Fixed)
- 🐛 **segSNR 計算 bug 修復**
  - **問題**: `tools/benchmark_comparison.py` 錯誤地將 `sample_rate` (16000) 傳遞給 `calculate_segmental_snr()` 的 `frame_size` 參數
  - **影響**: 之前的 segSNR 排名數據不準確
  - **修復**: 使用正確的 `frame_size=256` (16ms @ 16kHz), `hop_size=128` (50% overlap)

### 發現 (Discovered)
- ⚠️ **V4 (IMCRA-OMLSA) 過度抑制問題**
  - **症狀**: 輸出能量僅保留輸入的 ~1%（正常應為 20-70%）
  - **原因**: OMLSA 增益計算中的幀間限制和時間平滑導致增益惡性循環下降
  - **影響**: 雖然 segSNR 數值看起來不錯 (+4.60 dB)，但 PESQ 最低 (1.19)，實際語音被嚴重削弱
  - **建議**: 使用 V3 替代 V4

### 修正後性能結果（benchmark_comparison.py）

| 排名 | 方法 | segSNR 改善 (dB) | PESQ | STOI | 備註 |
|------|------|------------------|------|------|------|
| 🥇 1 | **RNNoise** | **+4.72** | 1.69 | **0.90** | 深度學習，綜合最佳 |
| 🥈 2 | V4 (IMCRA-OMLSA) | +4.60 | 1.19 | 0.20 | ⚠️ 過度抑制 |
| 🥉 3 | **V3 (SPP-MMSE)** | +2.65 | **1.52** | 0.17 | **推薦：傳統算法最佳** |
| 4 | V3-2 (MMSE-LSA) | +2.56 | 1.43 | 0.14 | |
| 5 | V2 (Wiener) | +2.54 | 1.27 | 0.14 | |
| 6 | Speex | +2.40 | 1.44 | 0.88 | |
| 7 | V3-4 (Laplacian) | +2.33 | 1.43 | 0.17 | |
| 8 | V1 (Spectral Sub) | +2.11 | 1.44 | 0.13 | |
| 9 | V3-3 (PMMSE) | +2.08 | 1.43 | 0.15 | |

### 修改文件
1. `tools/benchmark_comparison.py` - 修復 segSNR 計算的 frame_size 參數
2. `README.md` - 更新排名和推薦
3. `CHANGELOG.md` - 新增此版本記錄

---

## [2.1.1] - 2026-01-06

### 改進 (Changed)
- ⬆️ **V3 系列參數同步優化**
  - 將最優參數 `alpha_xi=0.96` 同步到所有 V3 變體（V3, V3-2, V3-3, V3-4）
  - 來源：V3-3 參數調優實驗結果
  - 影響：提升所有 V3 系列的 SNR 平滑效果

### 修改文件
1. `config/v3_config.yaml` - alpha_xi: 0.95 → 0.96
2. `config/v3_2_config.yaml` - alpha_xi: 0.92 → 0.96
3. `config/v3_3_config.yaml` - alpha_xi: 0.90 → 0.96
4. `config/v3_4_config.yaml` - alpha_xi: 0.92 → 0.96

---

## [2.1.0] - 2026-01-05

### 新增 (Added)
- ✨ **V3-3/V3-4 參數優化**: 採用 V3-2 對齊參數
  - V3-3: PESQ 從 1.458 提升至 1.733 (+18.9%)
  - V3-4: STOI 達到 0.874（傳統算法最佳）
  - 核心發現：SNR Adaptive (enable: true, base_g_min_db: -12.0) 是高性能的關鍵

- ✨ **Clean 保護測試**: 新增 clean.wav 高 SNR 測試用例
  - 所有方法通過 clean protection 測試（PESQ 降幅 < 0.01）

### 改進 (Changed)
- ⬆️ **參數優化**：V3-3/V3-4 採用 V3-2 對齊參數
- ⬆️ **測試覆蓋**：新增 clean.wav 高 SNR 測試用例

---

## [2.0.1] - 2026-01-02

### 🔴 緊急修復 (Critical Fixes)
- 🐛 **V3-3 (PMMSE) 先驗分佈文檔錯誤修正**
  - **問題**: 所有文檔錯誤標記 V3-3 使用 Laplacian 先驗
  - **實際**: Loizou 2005 論文使用 **Gaussian 先驗** (complex Gaussian → Rayleigh 幅度分佈)
  - **修正**: 修正所有代碼、配置和文檔中的錯誤描述
  - **影響**: 文檔準確性，不影響實際計算（代碼實現本身是正確的）

- 🐛 **V3-3 (PMMSE) 公式說明不一致修正**
  - **問題**: 文檔聲稱公式與實際實現不一致
  - **修正**: 澄清兩種數學等價的實現方式
  - **完整版**: `G = sqrt((v+1)/2 * exp(E1(v/2)))`
  - **簡化版**: `G = sqrt((v+1)/2) * exp(E1(v/2)/2)` [數學等價，數值穩定]

### 新增 (Added)
- ✨ **V3-3 (PMMSE) 公式選項**
  - 新增 `use_full_formula` 參數（與 V3, V3-4 一致）
  - `false` (默認): 數值穩定版本
  - `true`: 完整公式（數學等價，使用相同實現）
  - 配置文件: `config/v3_3_config.yaml` 新增參數說明

### 改進 (Changed)
- 📝 **文檔大規模修正**
  - `core/gain_calculators/pmmse.py`: 修正先驗分佈說明，添加公式選項
  - `denoisers/v3_3_pmmse.py`: 修正類別文檔
  - `README.md`: 修正 3 處 V3-3 先驗分佈描述
  - `ALGORITHMS_EXPLANATION.md`: 修正 MMSE 變體對比表格
  - `docs/V3_VARIANTS_COMPARISON.md`: 修正理論基礎表格
  - `config/v3_3_config.yaml`: 修正註釋，添加公式選項說明
  - `config/v3_4_config.yaml`: 修正版本對比說明
  - `core/gain_calculators/laplacian_mmse.py`: 修正與其他版本對比說明
  - `denoisers/v3_4_laplacian_mmse.py`: 修正 V3-3 描述

### 正確的四個 MMSE 變體
| 版本 | 先驗分佈 | 成本函數 | 論文 |
|------|---------|---------|------|
| V3 (MMSE-STSA) | **Gaussian** | E[(X-X̂)²] | Ephraim & Malah 1984 |
| V3-2 (MMSE-LSA) | **Gaussian** | E[(log X - log X̂)²] | Ephraim & Malah 1985 |
| V3-3 (PMMSE) | **Gaussian** ✅ | E[(X-X̂)²/X] (IS距離) | Loizou 2005 |
| V3-4 (Laplacian-MMSE) | **Laplacian** | E[(X-X̂)²] | Chen & Loizou 2007 |

---

## [2.0.0] - 2026-01-02

### 新增 (Added)
- ✅ **V3 整合 V3-1**：統一 MMSE-STSA 實現
  - V3 支持兩種公式切換：Bessel 完整版 / E1 簡化版
  - 新增 `use_full_formula` 參數（true=Bessel, false=E1）
  - 刪除獨立的 V3-1 版本
  - 統一命名為 "MMSE-STSA"

- ✅ **MCRA 噪聲估計**：所有 V3 系列使用 RecursiveAverage + SPP 軟判決
  - V4 使用 IMCRA 兩階段結構

### 改進 (Changed)
- ⬆️ **V4 性能優化**：修復音量和震動問題
  - 配置優化：IMCRA 參數調整（alpha_d: 0.85→0.88, L: 150→120, delta_db: 5→8）
  - 配置優化：OMLSA 參數調整（alpha_g: 0.85→0.88）
  - 混合策略：低 SPP 區域使用線性/對數域混合增益
  - 變化限制：幀間增益變化速率限制（±6dB max）
  - 自適應 delta：根據 SNR 動態調整（3-12dB）
  - 效果：音量損失從 8-10dB 降至 3-5dB，震動感明顯減少

### 修復 (Fixed)
- 🐛 V4 音量損失過大問題
- 🐛 V4 語音段震動感問題

### 刪除 (Removed)
- ❌ V3-1 獨立版本（已合併到 V3）
- ❌ `core/gain_calculators/mmse_stsa.py`（功能合併到 `spp_mmse.py`）
- ❌ `denoisers/v3_1_mmse_stsa.py`（已合併）
- ❌ `config/v3_1_config.yaml`（已合併）

### 修改文件
1. `config/v3_config.yaml` - 添加 use_full_formula
2. `config/v4_config.yaml` - 優化 IMCRA/OMLSA 參數
3. `core/gain_calculators/spp_mmse.py` - 整合 V3-1 功能
4. `core/gain_calculators/omlsa.py` - 添加混合策略和變化限制
5. `core/noise_estimators/imcra.py` - 添加自適應 delta
6. `denoisers/v3_spp_mmse.py` - 添加 use_full_formula 參數
7. `denoisers/v4_imcra_omlsa.py` - 全面優化
8. `examples/process_audio.py` - 移除 V3-1，添加參數支持

詳見歷史文件 `PROJECT_STATUS.md`（已自目前原始碼樹移除）。

---

## [1.4.0] - 2026-01-01

### 新增 (Added)
- ✅ **新增 MMSE 變體**：4 個學術標準實現
  - V3-1: MMSE-STSA (Ephraim-Malah 1984)
    - 支持 Bessel 完整版 / E1 簡化版切換
    - `use_full_formula` 參數
  - V3-2: MMSE-LSA (Ephraim-Malah 1985)
    - 對數域 MMSE 估計
    - `use_linear_spp_weighting` 參數
  - V3-3: PMMSE (Loizou 2005)
    - Laplacian 先驗 + Itakura-Saito 距離
    - 感知動機設計
  - V3-4: Laplacian-MMSE (Chen & Loizou 2007)
    - Laplacian 先驗 + 標準 MSE
    - `beta_laplacian` 形狀參數

- ✅ **新增 Loizou 評估指標**：專業語音質量評估
  - segSNR with VAD（排除靜音幀）
  - fwSegSNR（頻率加權）
  - WSS（加權頻譜斜率距離）
  - Composite Measure（綜合評估）

### 新增文件
1. `core/gain_calculators/mmse_stsa.py` - MMSE-STSA 增益計算器
2. `core/gain_calculators/mmse_lsa.py` - MMSE-LSA 增益計算器
3. `core/gain_calculators/pmmse.py` - PMMSE 增益計算器
4. `core/gain_calculators/laplacian_mmse.py` - Laplacian-MMSE 增益計算器
5. `denoisers/v3_1_mmse_stsa.py` - V3-1 降噪器
6. `denoisers/v3_2_mmse_lsa.py` - V3-2 降噪器
7. `denoisers/v3_3_pmmse.py` - V3-3 降噪器
8. `denoisers/v3_4_laplacian_mmse.py` - V3-4 降噪器
9. `config/v3_1_config.yaml` - V3-1 配置
10. `config/v3_2_config.yaml` - V3-2 配置
11. `config/v3_3_config.yaml` - V3-3 配置
12. `config/v3_4_config.yaml` - V3-4 配置
13. `utils/metrics_loizou.py` - Loizou 評估指標

詳見：v1.4.0 相關文檔

---

## [1.3.0] - 2026-01-01

### 新增 (Added)
- ✅ 創建 ALGORITHMS_EXPLANATION.md（演算法詳解文檔）
- ✅ 整理和清理項目文檔

---

## [1.2.0] - 2026-01-01

### 新增 (Added)
- ✅ **添加 segSNR (Segmental SNR) 評估指標**
  - 新增 `calculate_segmental_snr()` 函數
  - 新增 `calculate_segmental_snr_improvement()` 函數
  - segSNR 現在是**主要評估指標**（適用於傳統降噪算法）
  - PESQ/STOI 改為**參考指標**

### 改進 (Changed)
- ⬆️ **評估指標體系調整**
  - `evaluate_all_metrics()` 現在優先計算 segSNR
  - `print_metrics()` 重新設計，突出顯示 segSNR 改善值（標註★）
  - 更新模組文檔說明，明確指出 segSNR 是主要指標

- 📝 **文檔更新**
  - 更新 utils/metrics.py 模組說明
  - 添加 segSNR 計算細節和適用場景說明
  - 說明 PESQ/STOI 不適合傳統算法的原因

### 技術細節 (Technical Details)

#### 為什麼使用 segSNR 而非 PESQ/STOI？

**PESQ/STOI 的問題**：
- PESQ 設計用於語音編碼器（codec）評估
- 對頻譜修改極度敏感，會嚴厲懲罰傳統算法固有的頻譜變化
- STOI 對語音能量損失敏感，傳統算法多少會削減語音
- 結果：所有版本 (V1-V4) 得分都在 1.0-1.5 範圍，無法區分優劣

**segSNR 的優勢**：
- 逐幀計算 SNR，對頻譜修改更寬容
- 更符合傳統降噪算法的評估需求
- 能有效區分不同版本的降噪效果
- 典型範圍：5-20 dB 表示良好降噪

#### segSNR 實現細節

**算法**：
```python
# 1. 將信號分成短幀 (16ms, 50% overlap)
frame_size = 256 samples (16ms @ 16kHz)
hop_size = 128 samples (50% overlap)

# 2. 對每一幀計算 SNR
for each frame:
    signal_power = mean(clean_frame^2)
    noise_power = mean((enhanced_frame - clean_frame)^2)
    frame_snr = 10 * log10(signal_power / noise_power)

# 3. 裁剪異常值並平均
clip frame_snr to [-10, 35] dB
segSNR = mean(all valid frame_snrs)
```

**特點**：
- 跳過靜音幀（signal_power < 1e-10）
- 裁剪到 [-10, 35] dB 避免極值影響
- 計算整段音頻（語音 + 噪聲），不分段

**修改文件**：
1. `utils/metrics.py`
   - 行 5: 添加 segSNR 到模組說明（標註為主要指標）
   - 行 177-258: 添加 `calculate_segmental_snr()` 函數
   - 行 261-293: 添加 `calculate_segmental_snr_improvement()` 函數
   - 行 446-452: 在 `evaluate_all_metrics()` 中優先計算 segSNR
   - 行 494-498: 在 `print_metrics()` 中突出顯示 segSNR（標註★）

#### 指標使用建議

| 指標類型 | 用途 | 適用場景 |
|---------|------|---------|
| **segSNR** | **主要評估** | **傳統降噪算法 (V1-V4)** |
| Global SNR | 次要參考 | 全局能量評估 |
| PESQ | 參考 | 語音編碼器、深度學習模型 |
| STOI | 參考 | 可懂度評估、深度學習模型 |
| LSD | 輔助 | 頻譜失真程度 |
| Musical Noise | 診斷 | 檢測音樂噪聲偽影 |

**使用範例**：
```python
from utils.metrics import evaluate_all_metrics, print_metrics

# 計算所有指標
metrics = evaluate_all_metrics(noisy, clean, enhanced, fs=16000)

# 顯示結果（segSNR 會被突出顯示）
print_metrics(metrics, "V3 SPP-MMSE")

# 主要關注
print(f"segSNR Improvement: {metrics['segsnr_improvement_db']:.2f} dB")
```

---

## [1.1.0] - 2024-12-30

### 新增 (Added)
- ✅ 添加 `process_audio.py` 主處理工具，支持批量處理和波形對比圖生成
- ✅ 添加完整的參數調整指南和實戰場景配置
- ✅ 添加 Musical Noise 修復詳細文檔
- ✅ 添加各版本的 reset() 方法，支持狀態重置

### 修復 (Fixed)
- 🐛 **修復 Musical Noise 問題**（所有版本）
  - V1: 添加時間平滑機制 `alpha_smooth=0.8`，改善 83%
  - V2: 添加時間平滑機制 `alpha_smooth=0.8`，改善 80%+
  - V3: 提高增益平滑因子 `alpha_g: 0.7 → 0.85`，改善 30%
  - V4: 提高增益平滑因子 `alpha_g: 0.7 → 0.85`，改善 20%

- 🐛 修復 core/reconstructor.py 的雙重加窗問題（COLA 一致性）
- 🐛 修復噪聲估計器選擇最小能量幀而非前N幀
- 🐛 修復繪圖顯示問題（確保顯示 input + V1-V4 共5個子圖）

### 改進 (Changed)
- ⬆️ 強化 V3/V4 的增益平滑（0.7 → 0.85）
- ⬆️ 優化配置文件參數和註釋說明
- 📝 完善所有版本的中文文檔和使用說明
- 📝 更新 README.md，添加詳細的參數調整指南

### 技術細節 (Technical Details)

#### Musical Noise 修復機制

**問題原因**：
- 增益在相鄰幀之間劇烈跳動（幀間變化 > 0.5）
- 頻譜隨機變化被感知為「震動」或「金屬音」

**解決方案**：時間域增益平滑
```python
# 線性域平滑（V1/V2/V3）
G_t = α * G_{t-1} + (1 - α) * G_current

# 對數域平滑（V4，更符合人耳感知）
log(G_t) = α * log(G_{t-1}) + (1 - α) * log(G_current)
```

**實現文件**：
1. `core/gain_calculators/spectral_subtraction.py` - V1 增益計算器
   - 添加 `alpha_smooth` 參數和 `prev_gain` 狀態
   - 添加 `reset()` 方法

2. `core/gain_calculators/wiener.py` - V2 增益計算器
   - 添加 `alpha_smooth` 參數和 `prev_gain` 狀態
   - 添加 `reset()` 方法

3. `denoisers/v1_spectral_subtraction.py` - V1 降噪器
   - 更新 `reset()` 調用 `self.gain_calculator.reset()`

4. `denoisers/v2_wiener.py` - V2 降噪器
   - 更新 `__init__` 添加 `alpha_smooth` 參數
   - 更新 `reset()` 調用 `self.gain_calculator.reset()`

5. `config/v1_config.yaml` - V1 配置
   - 添加 `alpha_smooth: 0.8`

6. `config/v2_config.yaml` - V2 配置
   - 添加 `alpha_smooth: 0.8`

7. `config/v3_config.yaml` - V3 配置
   - 更新 `alpha_g: 0.7 → 0.85`

8. `config/v4_config.yaml` - V4 配置
   - 更新 `alpha_g: 0.7 → 0.85`

9. `examples/process_audio.py` - 主處理工具
   - 添加 V2 創建時讀取 `alpha_smooth` 參數
   - 支持波形對比圖生成

**測試驗證**：
- 使用前 2 秒為純噪聲的測試音頻（`*_2s_silence.wav`）
- 純噪聲段平穩無震動聲
- 語音段清晰無失真

#### Reconstructor 修復

**問題**：
- 雙重加窗導致能量損失（-36 dB衰減）
- 分析時加窗 + 綜合時再加窗

**修復**：
```python
# 修改前（錯誤）
output[start:end] += windowed_frame * window

# 修改後（正確）
output[start:end] += frame  # 不重複加窗
# Hanning 窗 50% overlap 滿足 COLA，無需歸一化
```

**文件**：`core/reconstructor.py`

---

## [1.0.0] - 2024-11

### 初始版本

#### 新增 (Added)
- ✅ 實現 V1: 頻譜減法 (Spectral Subtraction)
  - SimpleAverageNoiseEstimator（簡單平均噪聲估計）
  - SpectralSubtractionGainCalculator（頻譜減法增益計算）

- ✅ 實現 V2: Wiener 濾波 (Wiener Filter)
  - RecursiveAverageNoiseEstimator（遞歸平均噪聲估計）
  - WienerGainCalculator（Wiener 增益計算）

- ✅ 實現 V3: SPP-MMSE
  - SPPEstimator（語音存在機率估計）
  - SppMmseGainCalculator（SPP 加權 MMSE 增益）
  - Decision Directed 先驗 SNR 估計

- ✅ 實現 V4: IMCRA-OMLSA
  - ImcraNoiseEstimator（最小值追蹤噪聲估計）
  - OmlsaGainCalculator（對數域 MMSE 增益）
  - SPP 引導的自適應更新

- ✅ 核心組件
  - FrameProcessor（分幀、加窗、FFT）
  - Reconstructor（IFFT、Overlap-Add）
  - 音頻 I/O 工具
  - 測試數據生成器

- ✅ 文檔和示例
  - 完整的中文 README
  - 配置文件（v1-v4）
  - 示例腳本

---

## 未來計劃

### 計劃功能
- ✅ 評估指標（PESQ, STOI, segSNR）- 已完成
- ✅ MCRA 雙視窗最小值追蹤 - 已完成於 v2.3.0
- ⚪ 可視化工具（頻譜圖、SPP 熱圖）
- ⚪ 實時音頻流處理
- ⚪ C++ 移植
- ⚪ WebRTC 集成
- ⚪ GUI 界面

---

## 版本號規則

- 主版本號：重大架構變更
- 次版本號：新功能、重要修復
- 修訂號：小修復、文檔更新

---

## 貢獻者

完整貢獻記錄以 repository commit history 為準。
