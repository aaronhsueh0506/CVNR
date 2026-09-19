# 語音降噪參數調整指南

> **適用版本**: v4.2 · **主推演算法**: V3-2 OMLSA（Python `v3_2_mmse_lsa.py` / C `c_impl/`）
>
> 本指南提供 release 場景下的快速調參，含四個核心旋鈕與場景切換相關參數。遇到本模組「不適用情境」（風聲 / 衝擊 / 迴響 / 重疊干擾），**請勿嘗試調參**，參見 [README.md](../README.md#limitations)。

---

## 🪜 先試 Strength Mode（Python + C 都有）

> **命名好的 4 級 strength mode 兩端都有**（2026-07）：
> - **Python**：`core/nr_strength.py`（`create_denoiser_from_config(..., strength=...)`）或 CLI `process_audio.py --nr-mode {mild,moderate,balanced,aggressive}`。
> - **C**：`mmse_lsa_config_for_mode(sample_rate, MMSE_LSA_NR_MILD|MODERATE|BALANCED|AGGRESSIVE)`（`c_impl/include/mmse_lsa_types.h`）或 `denoise_wav --nr-mode`。
> 兩端 4 級 std-math **bit-exact**。g_min_db 為 **audio 振幅 dB（/20）**。
> 四級共用同一套 DD、MCRA tracker、gain attack/decay 與低頻語音保護；
> preset 只改下表四個「抑噪深度」旋鈕。

| 模式 | g_min_db | q（語音存在先驗） | xi_min_db | noise over-subtraction | 適用 |
|---|---:|---:|---:|---:|---|
| mild | -20 dB | 0.58 | -10 dB | 1.2 | 安靜 / 室內、重視語音自然度（最淺） |
| moderate | -23 dB | 0.54 | -10 dB | 1.3 | mild 與 balanced 之間 |
| balanced（預設） | -25 dB | 0.52 | -10 dB | 1.4 | 一般使用 |
| aggressive | -28 dB | 0.45 | -12 dB | 1.5 | 高噪 / 戶外、可接受更多失真（最深） |

**多數情境切 `--nr-mode` 就夠了**，以下細節調參僅在這一步不符需求時再看。

---

## 📊 參數快速參考表

| 參數 | 作用 | 範圍 | 調高效果 | 調低效果 |
|------|------|------|----------|----------|
| `g_min_db` | 增益地板（振幅 dB /20） | -20 ~ -45 dB | 背景殘留多，語音自然 | 背景乾淨，可能死寂 |
| `xi_min_db` | 最小先驗 SNR | -10 ~ -20 dB | 保留更多弱成分，也可能留噪 | 壓得更深，微弱語音風險增加 |
| `q` | 語音存在先驗機率 | 0.2 ~ 0.7 | 更保守，保留語音 | 更激進降噪 |
| `noise_over_subtraction` | 送入 SPP/gain 的噪聲 PSD 倍率 | 1.0 ~ 2.0 | 壓得更深 | 保留更多內容 |
| `alpha_g` | 增益平滑 | 0.5 ~ 0.95 | 平滑，可能拖泥帶水 | 乾脆，可能粗糙 |

---

## 🎚️ 調參決策表

| 症狀 | 可能原因 | 建議調整 |
|------|----------|----------|
| 聲音太乾、有機械音 | g_min_db 過低 | 調高 (如 -35 → -28) |
| 背景太吵、降噪無感 | g_min_db 過高 | 調低 (如 -26 → -36) |
| 微弱語音被截斷 | xi_min_db 太低 | 調高 (如 -15 → -10) |
| 殘留太多噪聲 | q 過高或 over-subtraction 過低 | 調低 q 或調高 over-subtraction |
| 輔音 (f, s, th) 消失 | q 過低或 over-subtraction 過高 | 調高 q 或調低 over-subtraction |
| 像在水底、有咕嚕聲 | alpha_g 過低 | 調高 (如 0.7 → 0.9) |
| 語音開頭被切 | alpha_g 過高 | 調低 (如 0.9 → 0.8) |

---

## 📖 參數詳細說明

### 1. g_min_db (增益地板 / Gain Floor)

**物理意義**：算法被允許執行的「最大衰減量」。簡單說，就是「最安靜的時候，要把背景壓多低」。

**參數範圍**：通常在 -20 dB 到 -45 dB 之間（振幅 dB /20）。

**直觀理解**：

| 設定 | 效果 |
|------|------|
| 數值越小 (如 -40dB) | 壓得越深，背景越乾淨，但風險是容易把語音的尾音切斷，且容易暴露「音樂噪聲」 |
| 數值越大 (如 -20dB) | 壓得較淺，背景會殘留底噪，但語音聽起來更自然、飽滿，音樂噪聲會被底噪掩蓋住 (Masking Effect) |

**調整建議**：
- 覺得聲音太乾、有機械音、斷斷續續 → 調高 (例如從 -35 改到 -28)
- 覺得背景太吵、降噪無感 → 調低 (例如從 -26 改到 -36)

> 💡 **提示**：g_min_db 設得越高（越接近 0），通常越保守——current V3-2 balanced 預設為 -25 dB（振幅 /20）。

---

### 2. xi_min_db (最小先驗 SNR / Min A Priori SNR)

**物理意義**：這是 V3-4 (Laplacian) 的「致命傷」參數。它告訴算法：「假設最糟糕的情況下，語音信號至少也有這麼強」。

**參數範圍**：通常在 -10 dB 到 -20 dB 之間（現行四級 preset 為 -10 / -12 dB）。

**直觀理解**：它是 DD 先驗 SNR 的數值下限；下限越高，最低允許增益通常越大。

| 設定 | 效果 |
|------|------|
| 設得較高 (如 -10dB) | 提高先驗 SNR 下限，通常保留更多弱成分，也可能增加殘留 |
| 設得較低 (如 -20dB) | 允許更低的先驗 SNR 與更深抑制，弱語音被削的風險上升 |

**調整建議**：
- 語音稍微小聲就被吃掉 → 調高 (如 -15 改 -10)

> ⚠️ **注意**：下面這條只適用於 V3-4 Laplacian MAP，與 MMSE-LSA (V3-2) 的現行 -10 dB 預設無關：
> V3-4 在 xi_min_db = -10.0 時失敗，rescue 後改為 -15.0；該 gain rule 需要更低的下限。

---

### 3. q (語音存在先驗機率 / A Priori Probability of Speech Presence)

**物理意義**：這是算法在看到當前觀測以前，認為該頻率點含語音的機率。

**參數範圍**：0.0 (完全認為是噪聲) ~ 1.0 (完全信任是語音)。通常在 0.2 ~ 0.7。

**直觀理解**：

| 設定 | 效果 |
|------|------|
| 數值越大 (如 0.7) | 更相信語音存在，較保守、較能保留細節，但殘留可能增加 |
| 數值越小 (如 0.3) | 更傾向判為噪聲，抑制更深，但誤傷語音風險增加 |

**調整建議**：
- 殘留太多背景噪聲 → 調低（例如 0.52 改 0.45）
- 語音的輔音或弱諧波不見了 → 調高（例如 0.45 改 0.52）

---

### 4. alpha_g (增益平滑因子 / Gain Smoothing Factor)

**物理意義**：控制降噪過程的「反應速度」。

**參數範圍**：0.5 ~ 0.95。

**直觀理解**：

| 設定 | 效果 |
|------|------|
| 數值越高 (如 0.9) | 變化緩慢、平滑。聽起來比較舒服，像有一層柔焦濾鏡，不容易有突兀的刺耳聲，但可能會有「拖泥帶水」的迴音感 |
| 數值越低 (如 0.6) | 反應極快。能迅速切斷噪聲，但聽起來會很「乾」、「脆」，甚至有點粗糙 |

**調整建議**：
- 聲音聽起來像在水底、有咕嚕聲 (Musical Noise) → 調高 (如 0.8 改 0.9)
- 語音的開頭 (Onset) 被切掉、反應遲鈍 → 調低 (如 0.9 改 0.8)

---

## 🎬 場景切換相關參數（v4.2 起可調）

IMCRA/MCRA 的 scene change detector 用「高頻 gamma + spectral flatness」雙重條件觸發 noise reset。調這組參數是處理「突然切換噪聲環境」（如進地鐵、上車、開冷氣）最有效的方法。

| 參數 | 預設 | 症狀 & 調整 |
|---|---|---|
| `scene_change_threshold_db` | 10.0 | 切換太慢 → 降至 7；誤觸發把語音當噪聲 → 升至 12 |
| `scene_change_min_frames` | 5 | 誤觸發頻率高 → 升至 8；太遲鈍 → 降至 3 |
| `scene_change_blend` | 0.5 | 觸發時噪聲重估強度：1.0 = 完全重置；0 = 不重置 |
| `scene_change_flatness_threshold` | 0.4 | v4.2 新增（Fix #6）。一般搭配 threshold_db 使用，不需單調 |

---

## ⚠️ 不建議在 release 動的參數

下列參數會改變演算法內部穩定性，預設值是 Optuna / Cohen 文獻 / VCTK 驗證的結果：

- `alpha_xi` (0.92)：DD ξ 平滑 = **musical-noise lever**（2026-07 由 0.88 調高至 0.92，全預設共用，語音幾乎零成本）。調更高 → ξ 更平滑 → musical noise 更少，但過高會平滑掉語音瞬態；調低會帶回 musical noise。
- `alpha_s` (0.95) / `alpha_d` (0.903414，即 16 ms grid 上的 0.85；2026-09-03 由 0.7 調慢，0.7 的快速追蹤會傷語音) / `alpha_p` (0.2) / `L` (32)：IMCRA/MCRA 核心常數
- `num_init_frames` (20 = 200 ms)：調短會讓底噪估計 under-fit
- `delta_db` (10)：IMCRA/MCRA 內部 speech indicator 偏移（IMCRA 另有 OM-LSA posterior 作為主要 gate）
- `mcra_accept_external_spp` (True)：**True = 使用 denoiser 的 Bayesian posterior SPP
  （standalone 與目前 Audio_ALG pipeline 都採用）；False = 改用 MCRA 內部 binary
  ratio-test（plain MCRA，僅供另外驗證的組態）**
- `alpha_attack` (0.15，16 ms authored) / `alpha_decay` (= alpha_g)：非對稱平滑，全 preset 共用

如確實需要動，**請務必以 VCTK/DEMAND 800+ 檔做 regression 驗證**，避免改善單一 case 但整體退步。

---

## 🚫 什麼時候不要調參

下列情境屬於 OMLSA **本質限制**，無論怎麼調都無法解決——參見 [README limitations](../README.md#limitations)：

- **風聲 / buffeting**（強風直吹、車窗漏風）— 需硬體風罩或 NN 模型
- **衝擊噪聲**（關門、敲擊、碗盤）— 預設管線無啟用的脈衝偵測（`core/transient_suppressor.py` 存在但 `v4_config.yaml` 預設 `enable: false`）
- **類語音干擾**（其他人語音、電視、音樂）— 需 speech separation
- **迴響 / 回聲**— 需 dereverb / AEC

---

## 📝 調參流程建議

1. 先換 strength mode（`--nr-mode mild|moderate|balanced|aggressive`，Python + C 皆可）（**80% 的情境止於這一步**）
2. 遇到 symptom 對照「調參決策表」調四大核心旋鈕
3. 遇到場景切換問題調 `scene_change_*`
4. 每次只動一個參數，用同一批測試音檔 A/B 比對
5. 拿去 VCTK regression（若有批次測試 pipeline）確認沒變差
6. 記錄到 `config/*.yaml` 或 C 端 custom config

---

## 🏆 歷史 Optuna 1000-trial 最佳參數（v2.4.0，stale）

> 下表為 v2.4.0 歷史資料，僅供參考。**v4.2 release 已改採 config 預設值**，未再用 Optuna 重跑。

| 版本 | PESQ | STOI | segSNR | xi_min_db | g_min_db | alpha_g |
|------|------|------|--------|-----------|----------|---------|
| V3-2 (MMSE-LSA) | 1.738 | 0.859 | +5.12 dB | -22.0 | -13.0 | 0.84 |
| V3-3 (PMMSE) | 1.688 | 0.839 | +6.06 dB | -19.0 | -18.0 | 0.80 |
| V3 (MMSE-STSA) | 1.676 | 0.837 | +6.00 dB | -25.0 | -17.0 | 0.80 |
| V3-4 (Laplacian) | 1.539 | 0.840 | +5.10 dB | -15.0 | -18.0 | 0.70 |

> ⚠️ 原 "V4 (IMCRA-OMLSA)" 欄位已移除：當時的 V4 是指 MCRA 雙視窗版本（v1.5.0），與目前 v4.2 的 V4 OMLSA + Wind Handler 不是同一個東西；現行 V4 wind handler 為 research 框架，不建議 release 使用

---

## 🔗 相關文檔

- [README.md](../README.md) — 項目總覽與現行 release contract
- [歷史演算法說明](archive/algorithm_history.md) — 只供理解早期版本
- [C 使用說明](../c_impl/README.md) — C 實作使用方法與同等調參指引
- [config/](../config/) — 各版本配置文件
