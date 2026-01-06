"""
OMLSA - Optimally Modified Log-Spectral Amplitude
用於 V4
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import exp1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class OmlsaGainCalculator:
    """
    OMLSA 增益計算器

    最優化的對數譜幅度估計器（Cohen, 2002）

    與 SPP-MMSE 的區別:
        - 使用對數譜幅度域（而非線性域）
        - 更複雜的增益平滑策略
        - 進一步減少音樂噪聲

    參數:
        g_min_db: 最小增益（dB）
        alpha_g: 增益平滑因子
        gamma_0: SPP 閾值參數
        use_linear_spp_weighting: True=線性域加權（對齊V3-2）, False=對數域加權（標準OMLSA）
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        gamma_0: float = 4.6,
        use_linear_spp_weighting: bool = False
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.gamma_0 = gamma_0
        self.use_linear_spp_weighting = use_linear_spp_weighting

        # 狀態變量
        self.gain_prev = None
        self.log_gain_prev = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """
        計算 OMLSA 增益

        v1.5.0 改進：
        1. 低 SPP 區域使用混合策略（線性+對數）
        2. 限制幀間變化速率（防止震動）

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: SNR adaptive 最小增益（可選，用於動態調整）

        返回:
            gain: OMLSA 增益 (n_freqs,)
        """
        # 使用 SNR adaptive g_min (如果提供) 或默認值
        g_min_effective = g_min if g_min is not None else self.g_min

        # 1. 計算 MMSE-LSA 增益（在 H1 假設下）
        gain_h1 = self._mmse_lsa_gain(xi, gamma)

        # v2.1: 線性域 vs 對數域 SPP 加權（對齊 V3-2）
        if self.use_linear_spp_weighting:
            # 線性域加權（與 V3-2 相同）
            gain = spp * gain_h1 + (1 - spp) * g_min_effective
            log_gain = np.log(gain + 1e-10)
        else:
            # 對數域加權（標準 OMLSA）
            log_gain_h1 = np.log(gain_h1 + 1e-10)
            log_g_min_effective = np.log(g_min_effective + 1e-10)
            log_gain = spp * log_gain_h1 + (1 - spp) * log_g_min_effective

        # v2.1: 對數域時間平滑
        if self.log_gain_prev is not None and self.alpha_g > 0:
            log_gain = self.alpha_g * self.log_gain_prev + \
                      (1 - self.alpha_g) * log_gain

        # 保存當前對數增益
        self.log_gain_prev = log_gain.copy()

        # 轉回線性域
        gain = np.exp(log_gain)

        # 限制增益範圍
        gain = np.clip(gain, g_min_effective, 1.0)

        # 保存線性增益
        self.gain_prev = gain.copy()

        return gain

    def _mmse_lsa_gain(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """
        MMSE 對數譜幅度估計器

        這與 MMSE-STSA 類似，但在對數域優化

        參數:
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)

        返回:
            gain: MMSE-LSA 增益 (n_freqs,)
        """
        # 計算 v = ξ/(1+ξ) * γ
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)

        # 計算指數積分
        if SCIPY_AVAILABLE:
            exp1_v = exp1(v)
        else:
            exp1_v = self._exp1_approx(v)

        # MMSE-LSA 增益
        # G = exp(0.5 * E1(v))
        # 但為了數值穩定性，使用另一種形式：
        # G = (ξ/(1+ξ)) * exp(0.5 * E1(v))
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
        """重置狀態"""
        self.gain_prev = None
        self.log_gain_prev = None

    def __repr__(self):
        return (f"OmlsaGainCalculator(g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g})")
