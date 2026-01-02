"""
SPP-MMSE Gain Calculator - SPP 加權 MMSE 增益計算器
用於 V3

v1.5.0 更新: 支持完整 Bessel 公式和 E1 簡化版切換
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1, i0, i1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class SppMmseGainCalculator:
    """
    基於語音存在機率 (SPP) 的 MMSE 增益計算器

    結合兩種假設下的增益：
    - H1: 語音存在時的 MMSE-STSA 增益
    - H0: 語音不存在時的最小增益

    最終增益：G = p * G_H1 + (1-p) * G_min

    v1.5.0 新增: 支持兩種 MMSE-STSA 公式
    - use_full_formula=False: E1 簡化版（默認，推薦）
    - use_full_formula=True: Bessel I0+I1 完整版（學術標準）

    參數:
        g_min_db: 最小增益 (dB)，通常 -15 到 -25 dB
        alpha_g: 增益時間平滑因子，減少音樂噪聲
        use_full_formula: True=Bessel完整版, False=E1簡化版(推薦)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        use_full_formula: bool = False
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.use_full_formula = use_full_formula
        self.gain_prev = None

        # 常數
        self.gamma_const = np.sqrt(np.pi) / 2  # Γ(1.5)

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        計算 SPP 加權的 MMSE 增益

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: 增益 (n_freqs,)
        """
        # 計算 MMSE-STSA 增益 (在 H1 假設下)
        # v1.5.0: 支持切換完整版/簡化版
        if self.use_full_formula:
            gain_mmse = self._mmse_stsa_gain_bessel(xi, gamma)
        else:
            gain_mmse = self._mmse_stsa_gain_e1(xi, gamma)

        # SPP 加權
        # G = p * G_MMSE + (1-p) * G_min
        gain = spp * gain_mmse + (1 - spp) * self.g_min

        # 時間平滑（減少音樂噪聲）
        if self.gain_prev is not None:
            gain = self.alpha_g * self.gain_prev + (1 - self.alpha_g) * gain

        # 保存當前增益
        self.gain_prev = gain.copy()

        # 限制增益範圍
        gain = np.clip(gain, self.g_min, 1.0)

        return gain

    def _mmse_stsa_gain_e1(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """
        MMSE-STSA 簡化版（使用指數積分 E1）

        公式:
            G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
            其中 v = ξ/(1+ξ) * γ

        這是推薦的默認版本，性能接近完整公式但數值穩定性更好。
        誤差 < 5% vs Bessel 完整版。

        參數:
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: MMSE-STSA 增益 (n_freqs,)
        """
        # 計算 v = ξ/(1+ξ) * γ
        v = (xi / (1 + xi)) * gamma

        # 避免數值問題
        v = np.clip(v, 1e-10, 700)  # exp(700) 接近浮點數上限

        # 計算 E1(v)（指數積分）
        if SCIPY_AVAILABLE:
            # 使用 scipy 的精確實現
            exp1_v = exp1(v)
        else:
            # 使用近似（對於大的 v）
            exp1_v = self._exp1_approx(v)

        # MMSE-STSA 增益
        # G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

        return gain

    def _mmse_stsa_gain_bessel(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """
        MMSE-STSA Bessel 完整版（使用 Modified Bessel 函數）

        公式:
            G = (Γ(1.5)/γ) * √v * exp(-v/2) * [(1+v)*I₀(v/2) + v*I₁(v/2)]

        其中:
            v = ξ/(1+ξ) * γ
            Γ(1.5) = √π/2
            I₀, I₁: Modified Bessel functions of order 0 and 1

        這是學術標準實現（Ephraim-Malah 1984）。
        對於 v > 100，自動切換到 E1 簡化版以避免數值溢出。

        參數:
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: MMSE-STSA 增益 (n_freqs,)
        """
        # 計算 v = ξ/(1+ξ) * γ
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)  # 防止溢出

        v_half = v / 2.0

        # 計算 Bessel functions
        if SCIPY_AVAILABLE:
            bessel_i0 = i0(v_half)
            bessel_i1 = i1(v_half)
        else:
            bessel_i0 = self._bessel_i0_approx(v_half)
            bessel_i1 = self._bessel_i1_approx(v_half)

        # 數值穩定性: 對大 v 使用簡化公式
        mask_large = v > 100
        gain = np.zeros_like(v)

        # 小 v: 直接計算完整公式
        mask_small = ~mask_large
        if np.any(mask_small):
            v_s = v[mask_small]
            v_half_s = v_s / 2.0
            i0_s = bessel_i0[mask_small] if isinstance(bessel_i0, np.ndarray) else i0(v_half_s)
            i1_s = bessel_i1[mask_small] if isinstance(bessel_i1, np.ndarray) else i1(v_half_s)
            gamma_s = gamma[mask_small]

            # G = (Γ(1.5)/γ) * √v * exp(-v/2) * [(1+v)*I₀(v/2) + v*I₁(v/2)]
            term = (1 + v_s) * i0_s + v_s * i1_s
            gain[mask_small] = (self.gamma_const / gamma_s) * \
                               np.sqrt(v_s) * np.exp(-v_half_s) * term

        # 大 v: 使用 E1 簡化公式避免溢出
        if np.any(mask_large):
            v_l = v[mask_large]
            xi_l = xi[mask_large]
            gamma_l = gamma[mask_large]
            gain[mask_large] = self._mmse_stsa_gain_e1(
                xi_l.reshape(-1),
                gamma_l.reshape(-1)
            )

        return gain

    def _bessel_i0_approx(self, x: np.ndarray) -> np.ndarray:
        """
        Modified Bessel function I0 近似

        使用 Abramowitz & Stegun 的多項式近似:
        - 小參數 (x < 3.75): 多項式展開
        - 大參數 (x >= 3.75): 漸近展開

        參數:
            x: 輸入值

        返回:
            I0(x) 的近似值
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

    def _bessel_i1_approx(self, x: np.ndarray) -> np.ndarray:
        """
        Modified Bessel function I1 近似

        使用 Abramowitz & Stegun 的多項式近似:
        - 小參數 (x < 3.75): 多項式展開
        - 大參數 (x >= 3.75): 漸近展開

        參數:
            x: 輸入值

        返回:
            I1(x) 的近似值
        """
        result = np.zeros_like(x)

        # 小參數: 多項式近似
        mask_small = x < 3.75
        if np.any(mask_small):
            t = (x[mask_small] / 3.75) ** 2
            result[mask_small] = x[mask_small] * \
                                 (0.5 + 0.87890594*t + 0.51498869*t**2 +
                                  0.15084934*t**3 + 0.02658733*t**4 +
                                  0.00301532*t**5 + 0.00032411*t**6)

        # 大參數: 漸近展開
        mask_large = ~mask_small
        if np.any(mask_large):
            ax = np.abs(x[mask_large])
            t = 3.75 / ax
            result[mask_large] = (np.exp(ax) / np.sqrt(ax)) * \
                                 (0.39894228 - 0.03988024*t - 0.00362018*t**2 +
                                  0.00163801*t**3 - 0.01031555*t**4 +
                                  0.02282967*t**5 - 0.02895312*t**6 +
                                  0.01787654*t**7 - 0.00420059*t**8)

        return result

    def _exp1_approx(self, v: np.ndarray) -> np.ndarray:
        """
        指數積分 E1(v) 的近似

        對於 v > 1，使用漸近展開：
        E1(v) ≈ exp(-v)/v * (1 - 1/v + 2/v² - ...)

        參數:
            v: 輸入值

        返回:
            exp1_v: E1(v) 的近似值
        """
        # 簡單近似（對於大的 v）
        # E1(v) ≈ exp(-v) / v
        result = np.zeros_like(v)

        # 對於 v >= 1，使用漸近展開
        mask_large = v >= 1.0
        if np.any(mask_large):
            v_large = v[mask_large]
            result[mask_large] = np.exp(-v_large) / v_large

        # 對於 v < 1，使用更精確的近似
        mask_small = ~mask_large
        if np.any(mask_small):
            v_small = v[mask_small]
            # E1(v) ≈ -γ - log(v) - v + v²/4 - v³/18 + ...
            # 其中 γ ≈ 0.5772 (Euler-Mascheroni 常數)
            gamma_const = 0.5772156649
            result[mask_small] = -gamma_const - np.log(v_small + 1e-10) - v_small

        return result

    def reset(self):
        """重置增益歷史"""
        self.gain_prev = None

    def __repr__(self):
        formula = "Bessel" if self.use_full_formula else "E1"
        return (f"SppMmseGainCalculator(g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, formula={formula})")
