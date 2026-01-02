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

實現特點:
    - 使用相同的 E1 公式計算基礎增益
    - 在對數域進行 SPP 加權和時間平滑
    - 更符合人耳對數感知特性 (Weber-Fechner 定律)
    - 相比 STSA 產生更少的 musical noise
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class MmseLsaGainCalculator:
    """
    MMSE 對數短時頻譜幅度估計器

    LSA vs STSA 的關鍵區別:
    1. LSA 在對數域進行 SPP 加權: log(G) = p*log(G_mmse) + (1-p)*log(g_min)
    2. LSA 在對數域進行時間平滑: log(G_t) = α*log(G_{t-1}) + (1-α)*log(G_t)
    3. 這使得小增益被抑制更多,大增益變化更平緩

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8
        use_linear_spp_weighting: True=線性域加權(退化為STSA), False=對數域加權(推薦)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        use_linear_spp_weighting: bool = False
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.log_g_min = np.log(self.g_min + 1e-10)
        self.alpha_g = alpha_g
        self.use_linear_spp_weighting = use_linear_spp_weighting
        self.log_gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        計算 SPP 加權的 MMSE-LSA 增益

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: 增益 (n_freqs,)
        """
        # 基礎 MMSE 增益 (與 MMSE-STSA 簡化版相同公式)
        gain_mmse = self._mmse_gain_base(xi, gamma)

        # 關鍵差異: 對數域 vs 線性域加權
        if self.use_linear_spp_weighting:
            # 線性域加權 (退化為 MMSE-STSA 行為)
            gain = spp * gain_mmse + (1 - spp) * self.g_min
            log_gain = np.log(gain + 1e-10)
        else:
            # 對數域加權 (真正的 MMSE-LSA)
            log_gain_mmse = np.log(gain_mmse + 1e-10)
            log_gain = spp * log_gain_mmse + (1 - spp) * self.log_g_min

        # 對數域時間平滑 (LSA 的核心特徵)
        if self.log_gain_prev is not None:
            log_gain = self.alpha_g * self.log_gain_prev + (1 - self.alpha_g) * log_gain

        # 轉回線性域
        gain = np.exp(log_gain)

        # 限制範圍
        gain = np.clip(gain, self.g_min, 1.0)

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

        # 計算 E1
        if SCIPY_AVAILABLE:
            exp1_v = exp1(v)
        else:
            exp1_v = self._exp1_approx(v)

        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

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
        self.log_gain_prev = None

    def __repr__(self):
        mode = "Linear SPP" if self.use_linear_spp_weighting else "Log-domain SPP (LSA)"
        return (f"MmseLsaGainCalculator("
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, "
                f"mode={mode})")


if __name__ == "__main__":
    # 測試示例
    print("MMSE-LSA 增益計算器")
    print("\n對數域 vs 線性域對比:")

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # 對數域 LSA
    calc_lsa = MmseLsaGainCalculator(use_linear_spp_weighting=False, alpha_g=0.0)
    gain_lsa = calc_lsa.calculate(spp, xi, gamma)

    # 線性域 (退化為 STSA)
    calc_linear = MmseLsaGainCalculator(use_linear_spp_weighting=True, alpha_g=0.0)
    gain_linear = calc_linear.calculate(spp, xi, gamma)

    # 對比
    print("\nSNR (dB) | LSA (對數域) | Linear (線性域) | 差異 (%)")
    print("-" * 60)
    for i in range(len(xi)):
        xi_db = 10 * np.log10(xi[i])
        diff = abs(gain_lsa[i] - gain_linear[i]) / gain_linear[i] * 100
        print(f"{xi_db:7.1f} | {gain_lsa[i]:12.4f} | {gain_linear[i]:14.4f} | {diff:8.2f}")

    print("\n對數域平滑效果:")
    print("-" * 60)

    # 測試對數域平滑對小增益的影響
    spp_low = np.array([0.3, 0.5, 0.7, 0.9, 1.0])  # 不同語音機率
    xi_test = np.array([1.0] * 5)
    gamma_test = np.array([2.0] * 5)

    calc_lsa_smooth = MmseLsaGainCalculator(use_linear_spp_weighting=False, alpha_g=0.0)
    calc_linear_smooth = MmseLsaGainCalculator(use_linear_spp_weighting=True, alpha_g=0.0)

    print("\nSPP | LSA增益 | Linear增益 | LSA更保守")
    print("-" * 50)
    for i in range(len(spp_low)):
        g_lsa = calc_lsa_smooth.calculate(
            spp_low[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        g_lin = calc_linear_smooth.calculate(
            spp_low[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        more_conservative = "是" if g_lsa < g_lin else "否"
        print(f"{spp_low[i]:.1f} | {g_lsa:.4f} | {g_lin:.4f} | {more_conservative}")

    print("\n結論:")
    print("1. LSA 對數域加權使小增益更保守 (更多抑制)")
    print("2. LSA 對數域平滑使增益變化更平緩")
    print("3. LSA 產生更少 musical noise,但可能過度抑制弱語音")
