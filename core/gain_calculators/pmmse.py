"""
PMMSE Gain Calculator (MMSE-STSA under weighted-Euclidean criterion)
基於 Loizou (2005) weighted-Euclidean p=-1 特例 (Ephraim & Malah 1984 MMSE-STSA)

參考文獻:
    Loizou, P. C. (2005).
    "Speech enhancement: Theory and practice." (Ch. 7, weighted-Euclidean p=-1)
    Ephraim, Y. & Malah, D. (1984). IEEE Trans. Acoustics, Speech, Signal Processing.

注意: 原本錯誤標記為 Wolfe & Godsill (2003) β=0.5 公式，但 W&G β=0.5
    產生不同增益曲線 (修正 Bessel 函數 K_{-1/2})；本實作的
    i0e 路徑對應 MMSE-STSA / Loizou p=-1。

公式:
    G_PM(k) = sqrt(v_k) / (sqrt(π) · γ_k) · exp(v_k/2) / I_0(v_k/2)

    其中:
        v_k = ξ_k/(1+ξ_k) · γ_k
        I_0: Modified Bessel function of the first kind (order 0)

數值優化:
    使用 scipy.special.i0e 避免 exp/I0 溢出：
    已知: I_0(x) = exp(x) · i0e(x)
    因此: exp(v/2) / I_0(v/2) = 1 / i0e(v/2)
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import i0e  # 指數縮放的 Bessel 函數
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class PmmseGainCalculator:
    """
    MMSE-STSA 增益估計器 (Loizou 2005 weighted-Euclidean p=-1)

    公式:
        G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I_0(v/2)
             = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)

    其中:
        v = ξ/(1+ξ) · γ
        i0e: 指數縮放的 Modified Bessel function (避免數值溢出)

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.5-0.7
        use_spp_weighting: 是否使用 SPP 加權 (推薦 True)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.5,
        use_spp_weighting: bool = True
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.use_spp_weighting = use_spp_weighting
        self.gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None,
        in_boost_mode: bool = False
    ) -> np.ndarray:
        """
        計算 PMMSE 增益 (Loizou 2005 p=-1)

        公式:
            G_PM = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: SNR adaptive 最小增益（可選）
            in_boost_mode: 未使用（保持接口兼容）

        返回:
            gain: 增益 (n_freqs,)
        """
        # 使用 SNR adaptive g_min (如果提供) 或默認值
        g_min_effective = g_min if g_min is not None else self.g_min

        # PMMSE 基礎增益 (Wolfe & Godsill β=0.5)
        gain_pmmse = self._pmmse_gain_wolfe_godsill(xi, gamma)

        # SPP 加權 (線性域)
        if self.use_spp_weighting:
            gain = spp * gain_pmmse + (1 - spp) * g_min_effective
        else:
            gain = gain_pmmse

        # 時間平滑
        if self.gain_prev is not None:
            gain = self.alpha_g * self.gain_prev + (1 - self.alpha_g) * gain

        self.gain_prev = np.clip(gain, 0.0, 1.0).copy()
        gain = np.clip(gain, g_min_effective, 1.0)

        return gain

    def _pmmse_gain_wolfe_godsill(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        Perceptually Motivated Estimator (Loizou 2005 p=-1)

        公式:
            G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I_0(v/2)
                 = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)

        數值優化:
            已知: I_0(x) = exp(x) · i0e(x)
            因此: exp(v/2) / I_0(v/2) = 1 / i0e(v/2)

        參數:
            xi: 先驗 SNR (a priori SNR)
            gamma: 後驗 SNR (posterior SNR)

        返回:
            gain: PMMSE 增益
        """
        # 限制 gamma 範圍，避免極端值導致增益過低
        # 使用與 v 相同的上限確保公式中的比率正確
        gamma_safe = np.clip(gamma, 1e-10, 700)

        # 計算 v_k
        v = (xi / (1 + xi + 1e-10)) * gamma_safe
        v = np.clip(v, 1e-10, 700)

        v_half = v / 2.0

        # 使用 i0e 避免數值溢出
        # exp(v/2) / I_0(v/2) = 1 / i0e(v/2)
        if SCIPY_AVAILABLE:
            i0e_v_half = i0e(v_half)
        else:
            i0e_v_half = self._i0e_approx(v_half)

        # G_PM = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)
        sqrt_pi = np.sqrt(np.pi)

        gain = (np.sqrt(v) / (sqrt_pi * gamma_safe)) / (i0e_v_half + 1e-10)
        gain = np.clip(gain, 0.0, 1.0)

        return gain

    def _i0e_approx(self, x: np.ndarray) -> np.ndarray:
        """
        指數縮放的修正 Bessel 函數 i0e(x) 近似

        i0e(x) = I_0(x) * exp(-x)

        使用多項式近似 (Abramowitz & Stegun)
        """
        result = np.zeros_like(x)

        # 小參數: 多項式近似
        mask_small = x < 3.75
        if np.any(mask_small):
            t = (x[mask_small] / 3.75) ** 2
            i0_val = 1.0 + 3.5156229*t + 3.0899424*t**2 + \
                     1.2067492*t**3 + 0.2659732*t**4 + \
                     0.0360768*t**5 + 0.0045813*t**6
            result[mask_small] = i0_val * np.exp(-x[mask_small])

        # 大參數: 漸近展開
        mask_large = ~mask_small
        if np.any(mask_large):
            ax = np.abs(x[mask_large])
            t = 3.75 / ax
            result[mask_large] = (1.0 / np.sqrt(ax)) * \
                                 (0.39894228 + 0.01328592*t + 0.00225319*t**2 -
                                  0.00157565*t**3 + 0.00916281*t**4 -
                                  0.02057706*t**5 + 0.02635537*t**6 -
                                  0.01647633*t**7 + 0.00392377*t**8)

        return result

    def reset(self):
        """重置增益歷史"""
        self.gain_prev = None

    def __repr__(self):
        spp_mode = "with SPP" if self.use_spp_weighting else "no SPP"
        return (f"PmmseGainCalculator(Loizou p=-1, "
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, {spp_mode})")


if __name__ == "__main__":
    # 測試示例
    print("PMMSE 增益計算器 (Loizou 2005 p=-1)")
    print("公式: G_PM = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)")

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # PMMSE (Wolfe & Godsill)
    calc = PmmseGainCalculator(use_spp_weighting=False, alpha_g=0.0)
    gain = calc.calculate(spp, xi, gamma)

    print("\nPMMSE 增益 (Wolfe & Godsill β=0.5):")
    print("SNR (dB) | Gain")
    print("-" * 25)
    for i in range(len(xi)):
        xi_db = 10 * np.log10(xi[i])
        print(f"{xi_db:7.1f} | {gain[i]:.4f}")

    # 測試 SPP 影響
    print("\n\nSPP 加權效果:")
    print("-" * 50)

    spp_values = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    xi_test = np.full_like(spp_values, 2.0)
    gamma_test = np.full_like(spp_values, 3.0)

    calc_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=True, alpha_g=0.0)
    calc_no_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=False, alpha_g=0.0)

    print("SPP | 有加權 | 無加權 | 差異")
    print("-" * 40)
    for i in range(len(spp_values)):
        g_with = calc_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        g_without = calc_no_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        print(f"{spp_values[i]:.1f} | {g_with:.4f} | {g_without:.4f} | {g_with-g_without:+.4f}")

    print("\n結論:")
    print("1. Wolfe & Godsill β=0.5 公式: 感知動機的 MMSE 估計")
    print("2. 使用 i0e 避免數值溢出")
    print("3. SPP 加權使低語音機率時增益更小")
