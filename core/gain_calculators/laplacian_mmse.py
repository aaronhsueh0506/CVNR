"""
Laplacian MAP Gain Calculator
基於 Lotter & Vary (2005)

參考文獻:
    Lotter, T., & Vary, P. (2005).
    "Speech enhancement by MAP spectral amplitude estimation using a
    super-Gaussian speech model."
    EURASIP Journal on Advances in Signal Processing.

核心公式 (Laplacian MAP):
    u = ξ + 1/(2γ) - 1
    G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))

優勢:
    - Laplacian 先驗更適合語音頻譜的稀疏性
    - 峰態係數 = 6 (Gaussian 為 3)
    - 無需 Bessel 函數，數值穩定
    - 高 SNR 時增益自然趨近 1.0
"""

import numpy as np
from typing import Optional


class LaplacianMmseGainCalculator:
    """
    Laplacian 先驗 MAP 增益估計器 (Lotter & Vary 2005)

    公式:
        u = ξ + 1/(2γ) - 1
        G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))

    特點:
        - 無需 Bessel 函數，數值穩定
        - 高 SNR 時增益自然趨近 1.0
        - Laplacian 先驗適合語音頻譜稀疏性

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.5-0.7
        use_spp_weighting: 是否使用 SPP 加權
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.5,
        beta_laplacian: float = 1.0,  # 保留向後兼容，Lotter & Vary 公式不使用
        use_spp_weighting: bool = True
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.beta_laplacian = beta_laplacian  # 保留屬性但不使用
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
        計算 Laplacian MAP 增益 (Lotter & Vary 2005)

        公式:
            u = ξ + 1/(2γ) - 1
            G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))

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

        # Laplacian MAP 基礎增益 (Lotter & Vary 2005)
        gain_laplacian = self._laplacian_map_gain(xi, gamma)

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

    def _laplacian_map_gain(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        Laplacian 先驗 MAP 增益 (Lotter & Vary 2005)

        公式:
            u = ξ + 1/(2γ) - 1
            G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))

        特點:
            - 無需 Bessel 函數，數值穩定
            - 高 SNR 時增益自然趨近 1.0

        參數:
            xi: 先驗 SNR (a priori SNR)
            gamma: 後驗 SNR (a posteriori SNR)

        返回:
            gain: Laplacian MAP 增益
        """
        # 防止除零
        gamma_safe = np.maximum(gamma, 1e-10)
        xi_safe = np.maximum(xi, 1e-10)

        # Lotter & Vary (2005) MAP 公式
        # u = ξ + 1/(2γ) - 1
        u = xi_safe + 1.0 / (2.0 * gamma_safe) - 1.0

        # G = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))
        term_1_plus_xi = 1.0 + xi_safe
        discriminant = u ** 2 + 2.0 * term_1_plus_xi / gamma_safe

        # 數值穩定性：確保判別式非負
        discriminant = np.maximum(discriminant, 0.0)

        gain = (u + np.sqrt(discriminant)) / (2.0 * term_1_plus_xi)

        # 限制增益範圍 (0, 1]
        gain = np.clip(gain, 1e-10, 1.0)

        return gain

    def reset(self):
        """重置增益歷史"""
        self.gain_prev = None

    def __repr__(self):
        spp_mode = "with SPP" if self.use_spp_weighting else "no SPP"
        return (f"LaplacianMmseGainCalculator(Lotter&Vary, "
                f"g_min={10*np.log10(self.g_min):.1f} dB, {spp_mode})")


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
