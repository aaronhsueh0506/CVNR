[索引](c_user_manual_zh_TW.md) | [上一部分](c_user_manual_zh_TW_01_quick_start.md) <!-- split-nav -->
## 4. Config 欄位參考

`AnrConfig`（`c_impl/include/anr_types.h`）目前有 41 個欄位。以下完整說明
產品整合會直接調整的 grid、SPP、MCRA、與 gain 欄位；低頻語音 guard
及預設關閉的研究欄位則在 4.2 的預設摘要與 header 中列出，避免把實驗開關誤當成
一般調參介面。
「預設值」欄若標示為**依 grid 而定**，代表 constructor 會依實際 hop 換算，實測值見 4.2 節。

**通則**：instance 建立後，改動你手上那份 `AnrConfig` 不會有任何效果（內部已經複製並
衍生出尺寸與狀態）。要換 sample rate、grid、`L` 或 `num_init_frames`，必須 destroy 後重建；
其餘調參欄位可在執行期用 `anr_set_mode()`／`anr_reconfigure()` 換（見 [1.8](c_user_manual_zh_TW_01_quick_start.md#18-執行期換強度anr_set_mode-與-anr_reconfigure)）。

### 4.1 Grid 欄位（4 個）

| 欄位 | 意義 | 合法範圍 | 預設 |
|---|---|---|---|
| `sample_rate` | 取樣率 | 只接受 `8000` / `16000` / `48000` | 由 constructor 參數指定 |
| `fft_size` | 轉換長度 | 2 的次方、`<= 8192`，且必須與 `sample_rate` 組成下表的合法 grid | 見下表 |
| `frame_size` | analysis frame 長度 | **必須等於 `fft_size`**（不做 zero padding） | 等於 `fft_size` |
| `hop_size` | 每次前進的樣本數 | **必須等於 `frame_size / 2`**（固定 50% overlap） | `fft_size / 2` |

合法 grid（實測 `anr_validate_config()`，其餘組合一律被拒）：

| sample_rate | fft_size = frame_size | hop_size | hop 長度 | n_freqs | 狀態 |
|---:|---:|---:|---:|---:|---|
| 8000 | 128 | 64 | 8.000 ms | 65 | 預設 |
| 8000 | 256 | 128 | 16.000 ms | 129 | 支援的替代 grid |
| 16000 | 256 | 128 | 8.000 ms | 129 | 預設 |
| 16000 | 512 | 256 | 16.000 ms | 257 | 支援的替代 grid |
| 48000 | 1024 | 512 | 10.667 ms | 513 | 唯一 grid |

要用替代 grid，改用 `anr_config_for_mode_grid(sample_rate, fft_size, mode)`。
**何時改**：hop 越短延遲越低、每秒運算次數越多；hop 越長頻率解析度越好、延遲越高。
除此之外沒有理由動它。

### 4.2 依 grid 換算的預設值（實測）

以下為 `balanced` preset 在各 grid 上的實際值（由建置後執行程式印出，非手算）：

| 欄位 | 8k/128 | 8k/256 | 16k/256 | 16k/512 | 48k/1024 |
|---|---:|---:|---:|---:|---:|
| `alpha_xi` | 0.959166 | 0.920000 | 0.959166 | 0.920000 | 0.945929 |
| `alpha_s` | 0.959796 | 0.921208 | 0.959796 | 0.921208 | 0.946757 |
| `alpha_d` | 0.921954 | 0.850000 | 0.921954 | 0.850000 | 0.897317 |
| `alpha_p` | 0.275946 | 0.076146 | 0.275946 | 0.076146 | 0.179652 |
| `alpha_g` | 0.902789 | 0.815028 | 0.902789 | 0.815028 | 0.872532 |
| `alpha_attack` | 0.387298 | 0.150000 | 0.387298 | 0.150000 | 0.282311 |
| `alpha_d_speech` | 0.974679 | 0.950000 | 0.974679 | 0.950000 | 0.966383 |
| `alpha_decay` | 0.902789 | 0.815028 | 0.902789 | 0.815028 | 0.872532 |
| `L` | 64 | 32 | 64 | 32 | 48 |
| `num_init_frames` | 25 | 13 | 25 | 13 | 19 |
| `scene_change_min_frames` | 7 | 4 | 7 | 4 | 5 |

換算成時間後，各 grid 的 `L` 都是 512 ms、`num_init_frames` 為 200–208 ms、
`scene_change_min_frames` 為 53–64 ms。**不要把上表任何一個數字寫死在你的程式裡**，
需要時從 config 讀。

與 grid 無關的預設值（`balanced`）：`q = 0.52`、`xi_min_db = -10.0`、`g_min_db = -25.0`、
`noise_over_subtraction = 1.4`、`delta_db = 10.0`、`scene_change_threshold_db = 10.0`、
`scene_change_blend = 0.5`、`scene_change_flatness_threshold = 0.4`、`broadband_threshold = 1.0`、
`speech_protect_floor = true`（`speech_protect_floor_db = -15.0`、`speech_protect_threshold = 0.0`、
`speech_protect_frame_threshold = 0.55`）、`speech_aware_noise_tracking = true`（`noise_gate_xi_db = 3.0`、
`noise_gate_lf_hz = 300.0`、`noise_gate_frame_frac = 0.5`）。四級 strength preset 只改 `g_min_db / q / xi_min_db /
noise_over_subtraction`（mild −20/0.58/−10/1.2、moderate −23/0.54/−10/1.3、balanced −25/0.52/−10/1.4、
aggressive −28/0.45/−12/1.3）；上表的時間常數與低頻語音 guard 的**設定值**四級共用，
但 `speech_protect_frame_threshold` 的**生效值**為 `value + (q − 0.52)`，隨 preset 的 `q`
逐級位移（mild 0.61、moderate 0.57、balanced 0.55、aggressive 0.48）。

記憶體需求（NE10，預設建置參數，實測 byte 數）：

| grid | `anr_get_mem_size()` | 加上 `-DUSE_FAST_PERCENTILE` | `fft_get_mem_size()` |
|---|---:|---:|---:|
| 8k/128 | 23 328 | 23 184 | 3 952 |
| 8k/256 | 28 784 | 28 688 | 7 152 |
| 16k/256 | 45 344 | 45 200 | 7 152 |
| 16k/512 | 56 432 | 56 336 | 13 552 |
| 48k/1024 | 144 576 | 144 464 | 26 352 |

整合 denoiser 內的噪聲追蹤器把「啟動階段的 power 列」與「最小值 ring」放在同一塊記憶體（取兩者
較大者）：啟動列在 `noise_estimator_init_noise()` 取完 30th percentile 後就不再被讀，ring 要等
那之後才第一次被寫。所以預設建置與 `-DUSE_FAST_PERCENTILE` 只差 percentile scratch
（`num_init_frames` 個 float）。獨立使用 `noise_estimator_*` 的呼叫端不受影響：該元件仍各自配置兩塊，
可隨時重新累積、重新初始化。

需求量同時受 `fft_size`、`L`、`num_init_frames` 與建置參數影響，上表僅供規劃 pool 大小時
估算；**正式程式一律以執行時的 `_get_mem_size()` 回傳值為準**。

### 4.3 SPP 參數（3 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `alpha_xi` | 訊噪比估計的時間平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：輸出更平滑，musical noise 更少，但語音起音較鈍。**調小**：反應更快，容易出現孤立的增益跳動。聽到零星「水聲／音樂噪聲」時先往上調 |
| `q` | 語音先驗機率 | 有限值，**開區間 `(0, 1)`**（`0` 與 `1` 都會被拒） | 0.52 | **調大**（趨近 mild 0.58）：更保守、更保語音。**調小**（趨近 aggressive 0.45）：抑噪更深、較容易傷語音 |
| `xi_min_db` | 訊噪比下限（dB） | 有限值，`[-80, 80]` | -10.0（aggressive -12.0） | **調低**：殘留底噪更低（更安靜、更容易聽出處理痕跡）。**調高**：保留較多自然底噪。這是控制殘留噪聲深度的主要旋鈕 |

`q=0.52` 是 balanced preset 的作者設定，不是把輸出的 SPP 固定成 0.52。當頻譜沒有提供
偏向語音或非語音的證據時，Bayesian posterior 會自然回到約 `q`，所以 debug 的
`mean_spp≈0.5` 是預期的中性狀態。
MCRA broadband gate 內部用來計數的 `spp > 0.5` 則是另一個分類門檻，與 `q` 不同。

### 4.4 MCRA 噪聲估計參數（6 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `alpha_s` | 功率譜的時間平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：噪聲追蹤更穩、對瞬態不敏感。**調小**：反應快但估計抖動。一般不動 |
| `alpha_d` | 噪聲估計的更新慣性 | 有限值，`[0, 1]` | 依 grid | **調大**：噪聲估計更新更慢、更不容易吸收語音。**調小**：噪聲底變化時追得更快，但較易把語音當成噪聲吃掉 |
| `alpha_p` | 語音存在指示的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：判定更穩定但反應慢。**調小**：反應快但抖。一般不動 |
| `L` | 最小值追蹤視窗長度（frame 數） | `1 ~ 320` | 依 grid（約 512 ms） | **調大**：不容易把持續語音誤當噪聲，但噪聲底上升時追得慢。**調小**：追得快但長句語音可能被當成噪聲。改這個欄位會改變記憶體需求 |
| `delta_db` | 語音判定門檻（dB） | 有限值，`[-80, 80]` | 10.0 | **調高**：更難判定為語音 → 噪聲估計更容易吸收訊號（抑噪深、傷語音風險高）。**調低**：更容易判定為語音 → 噪聲估計更保守 |
| `num_init_frames` | 初始化 pass-through 的 frame 數 | `1 ~ 200` | 依 grid（200–208 ms） | **調大**：初始噪聲估計更可靠，但開頭未處理的時間更長。**調小**：更快進入處理狀態，但初始估計較差。與契約 A 直接相關；改這個欄位會改變記憶體需求 |

### 4.5 場景變化偵測參數（5 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `scene_change_threshold_db` | 觸發場景變化判定的門檻（dB） | 有限值，`[-80, 80]` | 10.0 | **調低**：更容易判定為場景變化（噪聲底變化時追得快，但誤判也多）。**調高**：更保守 |
| `scene_change_min_frames` | 需連續成立幾個 frame 才確認 | `>= 0`（只檢查非負，無上限） | 依 grid（53–64 ms） | **調大**：只有持續的變化才算數，抗誤觸。**調小**：反應快但容易被瞬態誤觸 |
| `scene_change_blend` | 確認場景變化後，**保留**多少舊噪聲底（新噪聲底 = `blend ×` 舊值 + `(1 - blend) ×` 當前觀測值） | 有限值，`[0, 1]` | 0.5 | **調小**（趨近 0）：幾乎整個換成新場景的觀測值，切換快但誤判時風險高。**調大**（趨近 1）：噪聲底幾乎不動；`1.0` 時噪聲底 `noise_psd` 維持原值，但最小值追蹤 `S_min` 與最小值環仍會用當前功率重新播種（不是停用） |
| `scene_change_flatness_threshold` | 高頻頻譜平坦度門檻 | 有限值，`[0, 1]` | 0.4 | **調高**：只有很「像噪聲」的頻譜才會被當成場景變化，音樂／語音較不會誤觸。**調低**：較寬鬆 |
| `broadband_threshold` | 寬頻場景重置的啟用門檻 | 有限值，`[0, 1]`；**`1.0` 代表關閉** | 1.0（關閉） | 需要在寬頻噪聲突然出現後快速追上時，設成 `< 1.0`（越小越早介入）。不需要就維持 `1.0` |

### 4.6 增益參數（4 個）

| 欄位 | 意義 | 合法範圍 | 預設 | 何時調、往哪個方向 |
|---|---|---|---|---|
| `g_min_db` | 增益下限（**振幅** dB，`/20` 換算） | 有限值，`[-80, 80]` | -25.0 | **調低**：殘留噪聲更少、聽感更「乾淨」，但處理痕跡與語音損傷風險增加。**調高**：留更多底噪、語音更自然。這是控制抑噪深度最直接的旋鈕，也是四個 strength preset 的主要差異 |
| `alpha_g` | 增益平滑係數 | 有限值，`[0, 1]` | 依 grid | **在目前的 C 實作中這個欄位不影響輸出**（詳見下方註記）。要改變增益平滑請改 `alpha_attack` / `alpha_decay` |
| `alpha_attack` | 增益「上升」方向的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調小**：增益回升快，語音起音更清楚，但較容易讓噪聲短暫漏出。**調大**：起音較鈍但更平順 |
| `alpha_decay` | 增益「下降」方向的平滑係數 | 有限值，`[0, 1]` | 依 grid | **調大**：增益下降慢，musical noise 明顯減少，語音尾音拖長。**調小**：噪聲收得快但容易產生抖動 |

> **註記（實測）**：`alpha_g` 會被複製進 instance，但目前沒有任何運算使用它；實際的增益平滑
> 完全由 `alpha_attack` 與 `alpha_decay` 決定。各 preset 剛好把 `alpha_g` 與 `alpha_decay`
> 設成相同的值，所以只調 `alpha_g` 看起來「沒有作用」是正常的。想調平滑度請改
> `alpha_decay`（必要時連同 `alpha_attack`）。

### 4.7 hop 換算輔助函式

如果你在某個 grid 上手調出一組係數，想在另一個 grid 上得到相同的實際時間常數，用
`anr_retime_alpha_ref(alpha, sample_rate, hop_size, ref_hop_seconds)`（平滑係數）與
`anr_retime_frames_ms(frames, sample_rate, hop_size, ref_hop_ms)`（frame 計數，參考 hop 以整數毫秒給定、
全程整數運算；預設 config 的 `L` 用這一版）；
`anr_retime_alpha()` / `anr_retime_frames()` 是 10 ms 參考 hop 的簡寫。
兩者在參數無效時**不會報錯**（見[第 3 節](c_user_manual_zh_TW.md#3-錯誤語意表)），呼叫前請自行確認輸入。

### 4.8 外部（可開放給第三方）與內部（存在但不建議開放）

`AnrConfig` 的 41 欄 = 外部 A 4 欄（3 個概念）＋ 外部 B 4 欄 ＋ 內部 33 欄。完整表（預設、範圍、耦合、
為什麼不開放）在 `docs/html/nr_c_api_params.html`；這裡只列歸屬：

| 類別 | 欄位 | 說明 |
|---|---|---|
| 外部 A | `sample_rate`、`fft_size`（`frame_size`／`hop_size` 是衍生值）、`AnrMode` | 部署環境與強度 preset；建立時決定 |
| 外部 B | `g_min_db`、`xi_min_db`、`q`、`noise_over_subtraction` | 四個 preset 在動的欄位；`speech_protect_floor` 開啟（預設）時 `g_min_db` 實際上限是 `speech_protect_floor_db`（−15）；`q` 連動幀級語音閘 |
| 內部：噪聲追蹤器 | `alpha_s`、`alpha_d`、`alpha_p`、`L`、`delta_db`、`num_init_frames` | `L`／`num_init_frames` 決定 pool，執行期不可改 |
| 內部：平滑 | `alpha_xi`、`alpha_attack`、`alpha_decay`、`alpha_g`（C 不讀） | 手冊 [5.2](c_user_manual_zh_TW.md#52-建議調參順序) 的 musical noise 處方會調 `alpha_decay`，但不建議開放給第三方 |
| 內部：場景切換 | `scene_change_*`（4 欄）、`broadband_threshold` | 門檻與遲滯 |
| 內部：低頻語音保護（預設開） | `speech_protect_floor`、`speech_protect_floor_db`、`speech_protect_threshold`、`speech_protect_frame_threshold` | 閘門值隨 `q` 位移 |
| 內部：speech-aware 追蹤（預設開） | `speech_aware_noise_tracking`、`alpha_d_speech`、`noise_gate_xi_db`、`noise_gate_lf_hz`、`noise_gate_frame_frac` | |
| 內部：預設關閉的研究欄位 | `cross_band_speech_prior`、`cross_band_speech_prior_max_q`、`cross_band_speech_prior_alpha`、`dd_from_gmmse`、`makeup_gain`、`makeup_prior_xi_db`（保留欄位）、`makeup_blim`、`makeup_up_slope`、`makeup_down_slope` | 另有 `anr_apply_speech_protection_experiment()`、`anr_apply_cross_band_speech_experiment()` 兩個研究用疊加函式，不對外 |

---

[索引](c_user_manual_zh_TW.md) | [上一部分](c_user_manual_zh_TW_01_quick_start.md) <!-- split-nav -->
