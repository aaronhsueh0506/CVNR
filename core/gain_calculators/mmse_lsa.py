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

# v4.2.1 C-align: 預設改為走 3 段近似（與 C `exp1_approx` bit-exact 對齊）。
# 若需要 scipy.special.exp1 的精確值（研究/離線分析），將 USE_SCIPY_EXP1 設為 True。
USE_SCIPY_EXP1 = False
try:
    from scipy.special import exp1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


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
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8 (對稱平滑時使用)
        use_asymmetric_smoothing: 是否使用非對稱平滑 (v1.5.0)
        alpha_attack: Attack 平滑因子 (增益上升時使用，預設 0.3)
        alpha_decay: Decay 平滑因子 (增益下降時使用，預設 alpha_g)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None,
        # 語音段保護 floor（NR-review #1，預設關閉）。當 spp > spp_protect_threshold 時
        # 強制 gain >= spp_protect_floor（線性），避免 OMLSA (1−spp)·log(g_min) 過壓高信心語音。
        spp_protect_floor_db: Optional[float] = None,
        spp_protect_threshold: float = 0.5,
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.log_g_min = np.log(self.g_min + 1e-10)
        self.alpha_g = alpha_g

        # v1.5.0: 非對稱平滑參數
        self.use_asymmetric_smoothing = use_asymmetric_smoothing
        self.alpha_attack = alpha_attack
        self.alpha_decay = alpha_decay if alpha_decay is not None else alpha_g

        # SPP-protected floor
        self.spp_protect_floor_db = spp_protect_floor_db
        self.spp_protect_floor = (10 ** (spp_protect_floor_db / 10)
                                  if spp_protect_floor_db is not None else None)
        self.spp_protect_threshold = spp_protect_threshold

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

        # v4.2.1 C-align: 預設用 3 段近似（與 C `exp1_approx` bit-exact 對齊）。
        # 如需 scipy.special.exp1 的精確值，在 caller 端設 USE_SCIPY_EXP1 = True。
        if USE_SCIPY_EXP1 and SCIPY_AVAILABLE:
            exp1_v = exp1(v)
        else:
            exp1_v = self._exp1_approx(v)

        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

        return gain

    def _exp1_approx(self, v: np.ndarray) -> np.ndarray:
        """
        指數積分 E1(v) 的三段近似（v2.1 更新）

        參考: https://bobondemon.github.io/2019/03/20/MMSE-STSA-and-LSA/

        三段近似公式:
        - v < 0.1:   E1(v) ≈ -2.31 * log10(v) - 0.6
        - 0.1 ≤ v ≤ 1.0: E1(v) ≈ -1.544 * log10(v) + 0.166
        - v > 1.0:   E1(v) ≈ 10^(-0.52*v - 0.26)

        參數:
            v: 輸入值

        返回:
            exp1_v: E1(v) 的近似值
        """
        result = np.zeros_like(v)

        # v < 0.1
        mask1 = v < 0.1
        if np.any(mask1):
            v1 = np.maximum(v[mask1], 1e-10)  # 避免 log(0)
            result[mask1] = -2.31 * np.log10(v1) - 0.6

        # 0.1 <= v <= 1.0
        mask2 = (v >= 0.1) & (v <= 1.0)
        if np.any(mask2):
            result[mask2] = -1.544 * np.log10(v[mask2]) + 0.166

        # v > 1.0
        mask3 = v > 1.0
        if np.any(mask3):
            result[mask3] = 10 ** (-0.52 * v[mask3] - 0.26)

        return result

    def reset(self):
        """重置增益歷史"""
        self.log_gain_prev = None

    def __repr__(self):
        return (f"MmseLsaGainCalculator("
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
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
