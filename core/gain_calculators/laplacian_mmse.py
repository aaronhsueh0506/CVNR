"""
Laplacian-MMSE Gain Calculator
基於 Chen & Loizou (2007)

參考文獻:
    Chen, J., & Loizou, P. C. (2007).
    "Speech enhancement using a new Bayesian estimator."
    IEEE International Conference on Acoustics, Speech and Signal Processing.

核心公式:
    G_Lap = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

    其中:
        v = β * ξ/(1+ξ) * γ
        β: Laplacian 形狀參數
        I0: 零階修正 Bessel 函數

優勢:
    - Laplacian 先驗更適合語音頻譜的稀疏性
    - 峰態係數 = 6 (Gaussian 為 3)
    - 產生更少殘留噪聲
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import i0
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class LaplacianMmseGainCalculator:
    """
    Laplacian 先驗 MMSE 增益估計器 (Chen & Loizou 2007)

    公式:
        G_Lap = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

    其中:
        v = β * ξ/(1+ξ) * γ
        β: Laplacian 形狀參數
        I0: 零階修正 Bessel 函數

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.5-0.7
        beta_laplacian: Laplacian 形狀參數, 1.0-2.0
        use_spp_weighting: 是否使用 SPP 加權
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.5,
        beta_laplacian: float = 1.0,
        use_spp_weighting: bool = True
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.beta_laplacian = beta_laplacian
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
        計算 Laplacian-MMSE 增益 (Chen & Loizou 2007)

        公式:
            G_Lap = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

        其中:
            v = β * ξ/(1+ξ) * γ
            β: Laplacian 形狀參數
            I0: 零階修正 Bessel 函數

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

        # Laplacian-MMSE 基礎增益
        gain_laplacian = self._laplacian_mmse_gain(xi, gamma)

        # SPP 加權 (線性域)
        if self.use_spp_weighting:
            gain = spp * gain_laplacian + (1 - spp) * g_min_effective
        else:
            gain = gain_laplacian

        # 時間平滑
        if self.gain_prev is not None:
            gain = self.alpha_g * self.gain_prev + (1 - self.alpha_g) * gain

        self.gain_prev = gain.copy()
        gain = np.clip(gain, g_min_effective, 1.0)

        return gain

    def _laplacian_mmse_gain(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        Laplacian 先驗 MMSE 增益 (Chen & Loizou 2007)

        公式:
            G = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

        其中:
            v = β * ξ/(1+ξ) * γ
            β: Laplacian 形狀參數
            I0: 零階修正 Bessel 函數

        參數:
            xi: 先驗 SNR (a priori SNR)
            gamma: 後驗 SNR (a posteriori SNR)

        返回:
            gain: Laplacian-MMSE 增益
        """
        # 計算 v (考慮 Laplacian 形狀參數)
        v = self.beta_laplacian * (xi / (1 + xi + 1e-10)) * gamma
        v = np.clip(v, 1e-10, 700)  # 防止溢出

        v_half = v / 2.0

        # 計算 I0(v/2)
        if SCIPY_AVAILABLE:
            bessel_i0 = i0(v_half)
        else:
            bessel_i0 = self._bessel_i0_approx(v_half)

        # Laplacian-MMSE 公式
        # G = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)
        sqrt_pi_half = np.sqrt(np.pi) / 2.0

        # 數值穩定性處理
        mask_large = v > 100
        gain = np.zeros_like(v)

        # 小 v: 直接計算
        mask_small = ~mask_large
        if np.any(mask_small):
            v_s = v[mask_small]
            v_half_s = v_s / 2.0
            i0_s = bessel_i0[mask_small]
            gain[mask_small] = sqrt_pi_half * np.sqrt(v_s) * np.exp(-v_half_s) * i0_s

        # 大 v: 使用軟飽和避免硬截斷
        # 高 SNR 時增益趨近 1.0
        if np.any(mask_large):
            v_l = v[mask_large]
            # 軟飽和：v=100 時 gain≈0.5，v→∞ 時 gain→0.95
            gain[mask_large] = 0.95 - 0.45 * np.exp(-0.02 * (v_l - 100))

        return gain

    def _bessel_i0_approx(self, x: np.ndarray) -> np.ndarray:
        """
        Modified Bessel function I0 近似

        使用 Abramowitz & Stegun 的多項式近似
        """
        result = np.zeros_like(x)

        # 小參數: 多項式近似
        mask_small = x < 3.75
        if np.any(mask_small):
            t = (x[mask_small] / 3.75) ** 2
            result[mask_small] = 1.0 + 3.5156229*t + 3.0899424*t**2 + \
                                 1.2067492*t**3 + 0.2659732*t**4 + \
                                 0.0360768*t**5 + 0.0045813*t**6

        # 大參數: 漸近展開
        mask_large = ~mask_small
        if np.any(mask_large):
            ax = np.abs(x[mask_large])
            t = 3.75 / ax
            result[mask_large] = (np.exp(ax) / np.sqrt(ax)) * \
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
        return (f"LaplacianMmseGainCalculator(Chen&Loizou, "
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"beta={self.beta_laplacian}, {spp_mode})")


if __name__ == "__main__":
    # 測試示例
    print("Laplacian MAP 增益計算器 (Lotter & Vary 2005)")
    print("公式: G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))")
    print("      u = ξ + 1/(2γ) - 1")

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # Laplacian MAP
    calc = LaplacianMmseGainCalculator(use_spp_weighting=False, alpha_g=0.0)
    gain = calc.calculate(spp, xi, gamma)

    print("\nLaplacian MAP 增益 (Lotter & Vary 2005):")
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

    calc_spp = LaplacianMmseGainCalculator(g_min_db=-20.0, use_spp_weighting=True, alpha_g=0.0)
    calc_no_spp = LaplacianMmseGainCalculator(g_min_db=-20.0, use_spp_weighting=False, alpha_g=0.0)

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
    print("1. Lotter & Vary MAP: 無需 Bessel 函數，數值穩定")
    print("2. 大 SNR 時增益自然趨近 1.0")
    print("3. SPP 加權使低語音機率時增益更小")
