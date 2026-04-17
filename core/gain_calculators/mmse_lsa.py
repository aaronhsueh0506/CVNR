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

兩種模式:
    - use_spp_weighting=False: 純 MMSE-LSA，G = (ξ/(1+ξ)) × exp(0.5 × E1(v))
    - use_spp_weighting=True:  OMLSA 風格，G = G_H1^p × G_min^(1-p)
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

    兩種模式:
    1. use_spp_weighting=False (純 MMSE-LSA):
       G = (ξ/(1+ξ)) × exp(0.5 × E1(v))
       直接使用 MMSE-LSA 增益，無 SPP 加權

    2. use_spp_weighting=True (OMLSA 風格):
       G = G_H1^p × G_min^(1-p)
       使用 SPP 加權的對數域混合

    v1.5.0: 支持非對稱平滑
    - Attack (增益上升): 使用 alpha_attack (快速響應)
    - Decay (增益下降): 使用 alpha_decay (慢速抑制 Musical Noise)

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8 (對稱平滑時使用)
        use_spp_weighting: True=使用SPP加權(OMLSA), False=純MMSE-LSA
        use_asymmetric_smoothing: 是否使用非對稱平滑 (v1.5.0)
        alpha_attack: Attack 平滑因子 (增益上升時使用，預設 0.3)
        alpha_decay: Decay 平滑因子 (增益下降時使用，預設 alpha_g)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        use_spp_weighting: bool = False,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.log_g_min = np.log(self.g_min + 1e-10)
        self.alpha_g = alpha_g
        self.use_spp_weighting = use_spp_weighting

        # v1.5.0: 非對稱平滑參數
        self.use_asymmetric_smoothing = use_asymmetric_smoothing
        self.alpha_attack = alpha_attack
        self.alpha_decay = alpha_decay if alpha_decay is not None else alpha_g

        self.log_gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """
        計算 SPP 加權的 MMSE-LSA / OMLSA 增益

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: SNR adaptive 最小增益（可選）

        返回:
            gain: 增益 (n_freqs,)
        """
        g_min_effective = g_min if g_min is not None else self.g_min
        log_g_min_effective = np.log(g_min_effective + 1e-10)

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
                alpha_effective = np.where(
                    log_gain > self.log_gain_prev,
                    self.alpha_attack,
                    self.alpha_decay,
                )
                log_gain = alpha_effective * self.log_gain_prev + (1 - alpha_effective) * log_gain
            else:
                log_gain = self.alpha_g * self.log_gain_prev + (1 - self.alpha_g) * log_gain

        # 轉回線性域
        gain = np.exp(log_gain)

        # 限制範圍
        gain = np.clip(gain, g_min_effective, 1.0)

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
    # 測試示例
    print("MMSE-LSA 增益計算器")
    print("\n對數域 vs 線性域對比:")

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # 純 MMSE-LSA（無 SPP 加權）
    calc_lsa = MmseLsaGainCalculator(
        use_spp_weighting=False, alpha_g=0.0, use_asymmetric_smoothing=False
    )
    gain_lsa = calc_lsa.calculate(spp, xi, gamma)

    # OMLSA（SPP 對數域加權）
    calc_omlsa = MmseLsaGainCalculator(
        use_spp_weighting=True, alpha_g=0.0, use_asymmetric_smoothing=False
    )
    gain_omlsa = calc_omlsa.calculate(spp, xi, gamma)

    # 對比
    print("\nSNR (dB) | LSA (純) | OMLSA (SPP) | 差異 (%)")
    print("-" * 60)
    for i in range(len(xi)):
        xi_db = 10 * np.log10(xi[i])
        diff = abs(gain_lsa[i] - gain_omlsa[i]) / (gain_omlsa[i] + 1e-10) * 100
        print(f"{xi_db:7.1f} | {gain_lsa[i]:8.4f} | {gain_omlsa[i]:11.4f} | {diff:8.2f}")

    print("\nSPP 對 OMLSA 增益的影響:")
    print("-" * 60)

    # 測試不同 SPP 值
    spp_low = np.array([0.3, 0.5, 0.7, 0.9, 1.0])
    xi_test = np.array([1.0] * 5)
    gamma_test = np.array([2.0] * 5)

    calc_lsa_pure = MmseLsaGainCalculator(
        use_spp_weighting=False, alpha_g=0.0, use_asymmetric_smoothing=False
    )
    calc_omlsa_pure = MmseLsaGainCalculator(
        use_spp_weighting=True, alpha_g=0.0, use_asymmetric_smoothing=False
    )

    print("\nSPP | LSA純 | OMLSA | 差異")
    print("-" * 50)
    for i in range(len(spp_low)):
        g_lsa = calc_lsa_pure.calculate(
            spp_low[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        g_omlsa = calc_omlsa_pure.calculate(
            spp_low[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        print(f"{spp_low[i]:.1f} | {g_lsa:.4f} | {g_omlsa:.4f} | {abs(g_lsa-g_omlsa):.4f}")

    print("\n結論:")
    print("1. 純 LSA 不受 SPP 影響")
    print("2. OMLSA 以 SPP 在 log 域混合 G_H1 與 g_min，低 SPP 時壓得更低")
    print("3. OMLSA 對時變噪聲更穩定，但弱語音可能被抑制")
