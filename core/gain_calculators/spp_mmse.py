"""
SPP-MMSE Gain Calculator - SPP 加權 MMSE 增益計算器
用於 V3
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1
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

    參數:
        g_min_db: 最小增益 (dB)，通常 -15 到 -25 dB
        alpha_g: 增益時間平滑因子，減少音樂噪聲
    """

    def __init__(self, g_min_db: float = -20.0, alpha_g: float = 0.7):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.gain_prev = None

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
        gain_mmse = self._mmse_stsa_gain(xi, gamma)

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

    def _mmse_stsa_gain(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """
        MMSE 短時頻譜幅度 (STSA) 估計器

        公式:
            G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
            其中 v = ξ/(1+ξ) * γ

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
        return (f"SppMmseGainCalculator(g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g})")
