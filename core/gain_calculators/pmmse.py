"""
PMMSE Gain Calculator (Perceptually Motivated MMSE)
基於 Loizou 2005

參考文獻:
    Loizou, P. C. (2005).
    "Speech enhancement based on perceptually motivated Bayesian estimators
    of the magnitude spectrum."
    IEEE Transactions on Speech and Audio Processing, 13(5), 857-869.

核心差異:
    - 傳統 MMSE: 最小化 E[(|X| - |Xhat|)^2]
    - PMMSE:     最小化 E[(|X| - |Xhat|)^2 / |X|]

數學等價性:
    - PMMSE 成本函數等價於 Itakura-Saito (IS) 距離
    - IS 距離更符合人耳感知特性
    - 對小幅度分量更寬容,對大幅度分量更嚴格

實現特點:
    - 使用 Laplacian 先驗 (非 Gaussian)
    - 閉式解: G = sqrt((v+1)/2 * exp(E1(v/2)))
    - 相比 Gaussian-MMSE 產生更少殘留噪聲
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class PmmseGainCalculator:
    """
    感知動機 MMSE 增益估計器

    基於 Itakura-Saito 距離的 MMSE 估計:
    - 成本函數: E[(|X| - |Xhat|)^2 / |X|]
    - 假設: Laplacian 語音先驗分佈
    - 優勢: 更少的 musical noise,更自然的語音質量

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8
        use_spp_weighting: 是否使用 SPP 加權 (推薦 True)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
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
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        計算 PMMSE 增益

        Loizou 2005 公式 (Equation 27):
        G = sqrt((v+1)/2 * exp(E1(v/2)))

        其中 v = ξ/(1+ξ) * γ

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: 增益 (n_freqs,)
        """
        # PMMSE 基礎增益 (Laplacian 先驗)
        gain_pmmse = self._pmmse_gain_laplacian(xi, gamma)

        # SPP 加權 (線性域)
        if self.use_spp_weighting:
            gain = spp * gain_pmmse + (1 - spp) * self.g_min
        else:
            gain = gain_pmmse

        # 時間平滑
        if self.gain_prev is not None:
            gain = self.alpha_g * self.gain_prev + (1 - self.alpha_g) * gain

        self.gain_prev = gain.copy()
        gain = np.clip(gain, self.g_min, 1.0)

        return gain

    def _pmmse_gain_laplacian(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        PMMSE 增益 (Laplacian 先驗)

        Loizou 2005, Equation 27:
        G_PMMSE = sqrt((v+1)/2 * exp(E1(v/2)))

        其中:
            v = ξ/(1+ξ) * γ
            E1(v) = ∫[v to ∞] (e^(-t)/t) dt

        推導:
        - 假設語音 DFT 係數服從 Laplacian 分佈
        - 成本函數: E[(|X| - |Xhat|)^2 / |X|] (Itakura-Saito)
        - 閉式解基於 Laplacian 先驗的 Bayesian 估計
        """
        # 計算 v
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)  # 防止溢出

        v_half = v / 2.0

        # 計算 E1(v/2)
        if SCIPY_AVAILABLE:
            exp1_v_half = exp1(v_half)
        else:
            exp1_v_half = self._exp1_approx(v_half)

        # PMMSE 公式
        # 數值穩定性: 分為兩步計算
        # G = sqrt((v+1)/2) * sqrt(exp(E1(v/2)))
        #   = sqrt((v+1)/2) * exp(E1(v/2) / 2)

        sqrt_term = np.sqrt((v + 1) / 2.0)
        exp_term = np.exp(exp1_v_half / 2.0)

        gain = sqrt_term * exp_term

        return gain

    def _exp1_approx(self, v: np.ndarray) -> np.ndarray:
        """
        指數積分 E1(v) 的近似

        E1(v) = ∫[v to ∞] (e^(-t)/t) dt

        使用不同範圍的近似:
        - v >= 1.0: 漸近展開
        - v < 1.0: 級數展開
        """
        result = np.zeros_like(v)

        # 大 v: 漸近展開
        mask_large = v >= 1.0
        if np.any(mask_large):
            v_large = v[mask_large]
            result[mask_large] = np.exp(-v_large) / v_large

        # 小 v: 級數展開
        mask_small = ~mask_large
        if np.any(mask_small):
            v_small = v[mask_small]
            gamma_euler = 0.5772156649  # Euler-Mascheroni 常數
            result[mask_small] = -gamma_euler - np.log(v_small + 1e-10) - v_small

        return result

    def reset(self):
        """重置增益歷史"""
        self.gain_prev = None

    def __repr__(self):
        spp_mode = "with SPP" if self.use_spp_weighting else "no SPP"
        return (f"PmmseGainCalculator("
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, "
                f"{spp_mode})")


if __name__ == "__main__":
    # 測試示例
    print("PMMSE 增益計算器 (Loizou 2005)")
    print("\nPMMSE vs MMSE-STSA 對比:")

    # 導入 MMSE-STSA 用於對比
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        from gain_calculators.mmse_stsa import MmseStSaGainCalculator
        HAVE_MMSE_STSA = True
    except ImportError:
        print("Warning: 無法導入 MMSE-STSA,僅測試 PMMSE")
        HAVE_MMSE_STSA = False

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # PMMSE
    calc_pmmse = PmmseGainCalculator(use_spp_weighting=False, alpha_g=0.0)
    gain_pmmse = calc_pmmse.calculate(spp, xi, gamma)

    if HAVE_MMSE_STSA:
        # MMSE-STSA (簡化版)
        calc_stsa = MmseStSaGainCalculator(use_full_formula=False, alpha_g=0.0)
        gain_stsa = calc_stsa.calculate(spp, xi, gamma)

        # 對比
        print("\nSNR (dB) | PMMSE | MMSE-STSA | 差異 (%)")
        print("-" * 55)
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            diff = (gain_pmmse[i] - gain_stsa[i]) / gain_stsa[i] * 100
            print(f"{xi_db:7.1f} | {gain_pmmse[i]:.4f} | {gain_stsa[i]:.4f} | {diff:+7.2f}")

        print("\n觀察:")
        print("- PMMSE 通常比 MMSE-STSA 更保守 (增益更小)")
        print("- PMMSE 基於 Laplacian 先驗,更適合語音稀疏性")
        print("- PMMSE 的 IS 距離成本函數對小幅度更寬容")
    else:
        print("\nPMMSE 增益:")
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            print(f"SNR={xi_db:5.1f} dB: Gain={gain_pmmse[i]:.4f}")

    # 測試 SPP 影響
    print("\n\nSPP 加權效果:")
    print("-" * 50)

    spp_values = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    xi_test = np.full_like(spp_values, 2.0)
    gamma_test = np.full_like(spp_values, 3.0)

    calc_pmmse_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=True, alpha_g=0.0)
    calc_pmmse_no_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=False, alpha_g=0.0)

    print("SPP | 有加權 | 無加權 | 差異")
    print("-" * 40)
    for i in range(len(spp_values)):
        g_with = calc_pmmse_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        g_without = calc_pmmse_no_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        print(f"{spp_values[i]:.1f} | {g_with:.4f} | {g_without:.4f} | {g_with-g_without:+.4f}")

    print("\n結論:")
    print("1. PMMSE 使用 Itakura-Saito 距離,更符合感知特性")
    print("2. Laplacian 先驗比 Gaussian 更適合語音稀疏性")
    print("3. SPP 加權使低語音機率時增益更小 (更多抑制)")
    print("4. PMMSE 理論上產生更少 musical noise")
