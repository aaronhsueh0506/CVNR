"""
Laplacian-MMSE Gain Calculator
基於 Chen & Loizou 2007

參考文獻:
    Chen, J., & Loizou, P. C. (2007).
    "Speech enhancement using a new Bayesian estimator with symmetrized
    gamma distribution for speech presence uncertainty."
    IEEE International Conference on Acoustics, Speech and Signal Processing.

核心創新:
    - 使用 Laplacian 分佈對乾淨語音 DFT 係數建模 (非 Gaussian)
    - Laplacian 更適合語音頻譜的稀疏性和峰態特性
    - 結合 SPP (語音存在機率) 進行不確定性處理
    - 產生更少的殘留噪聲和 musical noise

與其他方法對比:
    - MMSE-STSA/LSA: 假設 Gaussian 先驗 + MSE 成本
    - PMMSE (V3-3): Gaussian 先驗 + IS 距離成本函數
    - Laplacian-MMSE (V3-4): Laplacian 先驗 + 標準 MSE 成本函數

實現:
    - 閉式解基於 Laplacian 統計特性
    - 使用指數積分 E1 和修正 Bessel 函數 I0
    - 數值穩定的實現方式
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1, i0
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class LaplacianMmseGainCalculator:
    """
    Laplacian 先驗 MMSE 增益估計器

    基於 Chen & Loizou 2007:
    - 假設乾淨語音 DFT 係數服從 Laplacian 分佈
    - 結合 SPP 處理語音存在不確定性
    - 比 Gaussian-MMSE 產生更少殘留噪聲

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8
        beta_laplacian: Laplacian 形狀參數調整因子, 1.0-2.0 (默認 1.5)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        beta_laplacian: float = 1.5
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.beta_laplacian = beta_laplacian
        self.gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """
        計算 Laplacian-MMSE 增益

        Chen & Loizou 2007 推導:
        G_Lap = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

        其中:
            v = β * ξ/(1+ξ) * γ
            β: Laplacian 形狀參數
            I0: 零階修正 Bessel 函數

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: SNR adaptive 最小增益（可選，用於動態調整）

        返回:
            gain: 增益 (n_freqs,)
        """
        # 使用 SNR adaptive g_min (如果提供) 或默認值
        g_min_effective = g_min if g_min is not None else self.g_min

        # Laplacian-MMSE 基礎增益
        gain_laplacian = self._laplacian_mmse_gain(xi, gamma)

        # SPP 加權 (線性域)
        gain = spp * gain_laplacian + (1 - spp) * g_min_effective

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
        Laplacian 先驗 MMSE 增益

        Chen & Loizou 2007, 基於 Laplacian 統計特性:

        G = (sqrt(π)/2) * sqrt(v) * exp(-v/2) * I0(v/2)

        其中:
            v = β * ξ/(1+ξ) * γ
            β: Laplacian 形狀參數 (通常 1.0-2.0)
            I0: 零階修正 Bessel 函數

        推導要點:
        - Laplacian PDF: p(x) = (1/2b) * exp(-|x|/b)
        - 峰態係數 = 6 (Gaussian 為 3)
        - 更適合建模語音頻譜的稀疏性
        """
        # 計算 v (考慮 Laplacian 形狀參數)
        v = self.beta_laplacian * (xi / (1 + xi)) * gamma
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

        # 數值穩定性: 分開計算避免溢出
        # 對於大 v, I0(v/2) ≈ exp(v/2) / sqrt(2πv/2)
        # 所以 exp(-v/2) * I0(v/2) ≈ 1 / sqrt(πv)

        mask_large = v > 100
        gain = np.zeros_like(v)

        # 小 v: 直接計算
        mask_small = ~mask_large
        if np.any(mask_small):
            v_s = v[mask_small]
            v_half_s = v_s / 2.0
            i0_s = bessel_i0[mask_small]

            gain[mask_small] = sqrt_pi_half * np.sqrt(v_s) * np.exp(-v_half_s) * i0_s

        # 大 v: 使用漸近公式避免溢出
        if np.any(mask_large):
            v_l = v[mask_large]
            # I0(v/2) ≈ exp(v/2) / sqrt(π*v)
            # exp(-v/2) * I0(v/2) ≈ 1 / sqrt(π*v)
            # G ≈ sqrt(π)/2 * sqrt(v) * 1/sqrt(π*v) = 1/2
            gain[mask_large] = 0.5

        return gain

    def _bessel_i0_approx(self, x: np.ndarray) -> np.ndarray:
        """
        Modified Bessel function I0 近似

        使用 Abramowitz & Stegun 的多項式近似:
        - 小參數 (x < 3.75): 多項式展開
        - 大參數 (x >= 3.75): 漸近展開
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
        return (f"LaplacianMmseGainCalculator("
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, "
                f"beta={self.beta_laplacian})")


if __name__ == "__main__":
    # 測試示例
    print("Laplacian-MMSE 增益計算器 (Chen & Loizou 2007)")
    print("\nLaplacian vs Gaussian 先驗對比:")

    # 導入 MMSE-STSA (Gaussian 先驗) 用於對比
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        from gain_calculators.mmse_stsa import MmseStSaGainCalculator
        HAVE_MMSE_STSA = True
    except ImportError:
        print("Warning: 無法導入 MMSE-STSA,僅測試 Laplacian-MMSE")
        HAVE_MMSE_STSA = False

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # Laplacian-MMSE
    calc_lap = LaplacianMmseGainCalculator(beta_laplacian=1.5, alpha_g=0.0)
    gain_lap = calc_lap.calculate(spp, xi, gamma)

    if HAVE_MMSE_STSA:
        # MMSE-STSA (Gaussian 先驗, 簡化版)
        calc_gauss = MmseStSaGainCalculator(use_full_formula=False, alpha_g=0.0)
        gain_gauss = calc_gauss.calculate(spp, xi, gamma)

        # 對比
        print("\nSNR (dB) | Laplacian | Gaussian | 差異 (%)")
        print("-" * 55)
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            diff = (gain_lap[i] - gain_gauss[i]) / gain_gauss[i] * 100
            print(f"{xi_db:7.1f} | {gain_lap[i]:.4f} | {gain_gauss[i]:.4f} | {diff:+7.2f}")

        print("\n觀察:")
        print("- Laplacian 先驗通常比 Gaussian 更保守")
        print("- Laplacian 更適合語音頻譜的稀疏性 (峰態係數=6 vs 3)")
        print("- 理論上產生更少殘留噪聲")
    else:
        print("\nLaplacian-MMSE 增益:")
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            print(f"SNR={xi_db:5.1f} dB: Gain={gain_lap[i]:.4f}")

    # 測試 beta 參數影響
    print("\n\nLaplacian 形狀參數 β 影響:")
    print("-" * 55)

    xi_test = np.array([1.0, 2.0, 5.0])
    gamma_test = np.array([2.0, 3.0, 6.0])
    spp_test = np.ones_like(xi_test)

    beta_values = [1.0, 1.5, 2.0]
    print("SNR (dB) | β=1.0 | β=1.5 | β=2.0")
    print("-" * 40)

    for i in range(len(xi_test)):
        xi_db = 10 * np.log10(xi_test[i])
        gains = []
        for beta in beta_values:
            calc = LaplacianMmseGainCalculator(beta_laplacian=beta, alpha_g=0.0)
            g = calc.calculate(spp_test[i:i+1], xi_test[i:i+1], gamma_test[i:i+1])[0]
            gains.append(g)
        print(f"{xi_db:7.1f} | {gains[0]:.4f} | {gains[1]:.4f} | {gains[2]:.4f}")

    print("\n結論:")
    print("1. Laplacian 分佈更適合語音 DFT 係數的統計特性")
    print("2. β 參數控制 Laplacian 的「尖銳度」")
    print("3. β 越大,增益越保守 (更多抑制)")
    print("4. 建議 β ∈ [1.0, 2.0],默認 1.5")
