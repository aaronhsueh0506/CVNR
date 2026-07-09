"""
MMSE-LSA Gain Calculator (Log-Spectral Amplitude)
基於 Ephraim-Malah 1985

參考文獻:
    Ephraim, Y., & Malah, D. (1985).
    "Speech enhancement using a minimum mean-square error log-spectral
    amplitude estimator."
    IEEE Trans. ASSP, 33(2), 443-445.

關鍵差異 vs MMSE-STSA:
    - STSA: 最小化 E[(|X| - |Xhat|)^2] (線性域)
    - LSA:  最小化 E[(log|X| - log|Xhat|)^2] (對數域)

增益公式 = OM-LSA (Cohen 2002)：在 log 域以 SPP 加權混合
    G = G_H1^spp × g_min^(1-spp)，  G_H1 = (ξ/(1+ξ)) × exp(0.5 × E1(v))
此 calculator 一律走 OM-LSA 混合（與 C 埠 mmse_lsa_denoiser.c bit-exact 對齊）。
"""

import numpy as np
from typing import Optional


def _exp1_approx(v: np.ndarray) -> np.ndarray:
    """E1(v) three-segment approximation (Cohen & Berdugo 2002 / Loizou 2007).

    Segments:
      v < 0.1  : -2.31  * log10(v) - 0.6
      0.1..1.0 : -1.544 * log10(v) + 0.166
      v > 1.0  : 10^(-0.52*v - 0.26)

    Shared with SppMmseGainCalculator (imported there).
    """
    v = np.maximum(v, 1e-10)
    result = np.zeros_like(v)
    mask1 = v < 0.1
    mask2 = (v >= 0.1) & (v <= 1.0)
    mask3 = v > 1.0
    result[mask1] = -2.31 * np.log10(v[mask1]) - 0.6
    result[mask2] = -1.544 * np.log10(v[mask2]) + 0.166
    result[mask3] = 10 ** (-0.52 * v[mask3] - 0.26)
    return result


# v4.2.1 C-align: E1(v) 一律走 3 段近似（與 C `exp1_approx` bit-exact 對齊）。
# scipy.special.exp1 路徑已移除——C 端不會鏈結 scipy，保留 scipy 分支只會是 parity footgun。


class MmseLsaGainCalculator:
    """
    MMSE 對數短時頻譜幅度估計器

    增益 = OM-LSA (Cohen 2002)：log 域以 SPP 加權混合
       G = G_H1^spp × g_min^(1-spp)
       G_H1 = (ξ/(1+ξ)) × exp(0.5 × E1(v))  為 MMSE-LSA 的 H1 增益
       此 calculator 一律走 OM-LSA 混合（與 C 埠 mmse_lsa_denoiser.c 對齊）。

    v1.5.0: 支持非對稱平滑
    - Attack (增益上升): 使用 alpha_attack (快速響應)
    - Decay (增益下降): 使用 alpha_decay (慢速抑制 Musical Noise)

    參數:
        g_min_db: 最小增益 (amplitude dB, /20), -30 到 -50
        alpha_g: 增益時間平滑因子, 0.6-0.8 (對稱平滑時使用)
        use_asymmetric_smoothing: 是否使用非對稱平滑 (v1.5.0)
        alpha_attack: Attack 平滑因子 (增益上升時使用，預設 0.3)
        alpha_decay: Decay 平滑因子 (增益下降時使用，預設 alpha_g)
    """

    def __init__(
        self,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None,
        # 語音段保護 floor（NR-review #1，預設關閉）。當 spp > spp_protect_threshold 時
        # 強制 gain >= spp_protect_floor（線性），避免 OMLSA (1−spp)·log(g_min) 過壓高信心語音。
        spp_protect_floor_db: Optional[float] = None,
        spp_protect_threshold: float = 0.5,
        # === Stationary-mode Wiener lower bound (the `stationary` NR mode mechanism).
        # Default OFF → current (`full`) behaviour, byte-identical. When on, the final gain is
        # floored at the Wiener gain (ξ/(β+ξ))^p; since ξ/(1+ξ)=S/Y this removes exactly the
        # estimated stationary floor and preserves everything with sustained SNR (speech/music/
        # transients). ξ is DD-smoothed → no warble.
        stationary_floor: bool = False,
        stationary_floor_exponent: float = 1.0,   # p: 1.0 = pure Wiener (gentle); 0.5 = deeper
        stationary_floor_beta: float = 1.0,        # β: >1 removes slightly more; 1 = remove exactly N
    ):
        # Amplitude-dB convention (/20): the OM-LSA gain is applied directly to the
        # magnitude spectrum (enhanced = gain * magnitude, no sqrt), so g_min is an
        # AMPLITUDE floor. g_min_db=-15 → 10^(-15/20)=0.178 (a true -15 dB amplitude floor).
        # C mmse_lsa_denoiser.c mirrors this. (SNR/power dB elsewhere — xi_min, delta,
        # scene_change — correctly stay /10 because they ARE power ratios.)
        self.g_min = 10 ** (g_min_db / 20)
        self.log_g_min = np.log(self.g_min + 1e-10)
        self.alpha_g = alpha_g

        # v1.5.0: 非對稱平滑參數
        self.use_asymmetric_smoothing = use_asymmetric_smoothing
        self.alpha_attack = alpha_attack
        self.alpha_decay = alpha_decay if alpha_decay is not None else alpha_g

        # SPP-protected floor
        self.spp_protect_floor_db = spp_protect_floor_db
        self.spp_protect_floor = (10 ** (spp_protect_floor_db / 20)  # amplitude gain floor
                                  if spp_protect_floor_db is not None else None)
        self.spp_protect_threshold = spp_protect_threshold

        # Stationary-mode Wiener lower bound
        self.stationary_floor = stationary_floor
        self.stationary_floor_exponent = stationary_floor_exponent
        self.stationary_floor_beta = stationary_floor_beta

        self.log_gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min=None,
        alpha_g_override: Optional[np.ndarray] = None,
        alpha_attack_override: Optional[np.ndarray] = None,
        alpha_decay_override: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        計算 SPP 加權的 MMSE-LSA / OMLSA 增益

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: 最小增益（可選）。可為 float（scalar）或 ndarray（per-bin）
            alpha_g_override: 對稱平滑 alpha_g 的 per-bin 覆蓋值（可選；預設 None）
            alpha_attack_override: 非對稱 attack 的 per-bin 覆蓋值
            alpha_decay_override: 非對稱 decay 的 per-bin 覆蓋值

        返回:
            gain: 增益 (n_freqs,)
        """
        # g_min 支援 scalar 或 per-bin array（可選 per-bin 覆蓋）
        if g_min is None:
            g_min_effective = self.g_min
            log_g_min_effective = self.log_g_min  # cached at __init__, avoid recompute
        else:
            g_min_effective = g_min
            log_g_min_effective = np.log(np.asarray(g_min_effective) + 1e-10)

        # 基礎 MMSE 增益
        gain_mmse = self._mmse_gain_base(xi, gamma)
        gain_mmse = np.clip(gain_mmse, g_min_effective, 1.0)

        # 對數域加權 (OMLSA 核心)
        log_gain_mmse = np.log(gain_mmse + 1e-10)
        log_gain = spp * log_gain_mmse + (1 - spp) * log_g_min_effective

        # 對數域時間平滑
        if self.log_gain_prev is not None:
            if self.use_asymmetric_smoothing:
                # Attack 快 / Decay 慢
                alpha_attack_eff = (alpha_attack_override
                                    if alpha_attack_override is not None
                                    else self.alpha_attack)
                alpha_decay_eff = (alpha_decay_override
                                   if alpha_decay_override is not None
                                   else self.alpha_decay)
                alpha_effective = np.where(
                    log_gain > self.log_gain_prev,
                    alpha_attack_eff,
                    alpha_decay_eff,
                )
                log_gain = alpha_effective * self.log_gain_prev + (1 - alpha_effective) * log_gain
            else:
                alpha_g_eff = (alpha_g_override if alpha_g_override is not None
                               else self.alpha_g)
                log_gain = alpha_g_eff * self.log_gain_prev + (1 - alpha_g_eff) * log_gain

        # 轉回線性域
        gain = np.exp(log_gain)

        # 限制範圍
        gain = np.clip(gain, g_min_effective, 1.0)

        # SPP-protected floor：語音 bin（spp > threshold）強制 gain >= 保護下限，
        # 避免深 g_min 透過 (1−spp) 誤壓高信心語音（NR-review #1，預設關閉）。
        if self.spp_protect_floor is not None:
            gain = np.where(
                spp > self.spp_protect_threshold,
                np.maximum(gain, self.spp_protect_floor),
                gain,
            )

        # Stationary-mode Wiener lower bound（`stationary` NR mode 的核心機制）。
        # gain 不得低於 Wiener 增益 (ξ/(β+ξ))^p。因 ξ/(1+ξ)=S/Y，此下界剛好只減掉估到的
        # 穩態噪聲底：持續高 SNR 的內容（語音/音樂/瞬態）ξ 大 → 下界≈1 → 保留；穩態噪聲
        # ξ→xi_min → 下界小 → 照壓。ξ 為 DD 平滑 → 無 warble。存入 log_gain_prev 的是「套過
        # 下界後」的 gain，讓時間平滑從被保護的值出發（與 spp_protect 同一 pattern）。
        if self.stationary_floor:
            # g_floor = (ξ/(β+ξ))^p ≤ 1 for β≥1, and gain is already clipped ≤ 1, so a plain
            # lower bound suffices (no outer min-with-1 needed).
            g_floor = (xi / (self.stationary_floor_beta + xi)) ** self.stationary_floor_exponent
            gain = np.maximum(gain, g_floor)

        # 保存對數域增益
        self.log_gain_prev = np.log(gain + 1e-10)

        return gain

    def _mmse_gain_base(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        基礎 MMSE 增益公式 (使用指數積分 E1)

        這是 MMSE-LSA 的精確解 (不是近似)

        G = (ξ/(1+ξ)) * exp(0.5 * E1(v))

        其中:
            v = ξ/(1+ξ) * γ
            E1(v) = ∫[v to ∞] (e^(-t)/t) dt
        """
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)  # 防止溢出

        # v4.2.1 C-align: 一律用 3 段近似（與 C `exp1_approx` bit-exact 對齊）。
        exp1_v = _exp1_approx(v)

        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

        return gain

    def reset(self):
        """重置增益歷史"""
        self.log_gain_prev = None

    def __repr__(self):
        return (f"MmseLsaGainCalculator("
                f"g_min={20*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g})")


if __name__ == "__main__":
    # 測試示例：OM-LSA 增益（log 域以 SPP 混合 G_H1 與 g_min）
    print("MMSE-LSA / OM-LSA 增益計算器")

    print("\nSPP 對 OM-LSA 增益的影響（固定 ξ=1, γ=2）:")
    print("-" * 40)
    print("SPP  | gain")
    print("-" * 40)
    for s in (0.3, 0.5, 0.7, 0.9, 1.0):
        calc = MmseLsaGainCalculator(alpha_g=0.0, use_asymmetric_smoothing=False)
        g = calc.calculate(np.array([s]), np.array([1.0]), np.array([2.0]))[0]
        print(f"{s:.1f}  | {g:.4f}")

    print("\n結論: OM-LSA 以 SPP 在 log 域混合 G_H1 與 g_min，低 SPP 時壓得更低。")
