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
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        gamma_0: float = 4.6
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.gamma_0 = gamma_0

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

        # 2. 對數域處理
        log_gain_h1 = np.log(gain_h1 + 1e-10)
        log_g_min_effective = np.log(g_min_effective + 1e-10)

        # v1.5.0: 混合策略（低 SPP 使用線性/對數混合）
        hybrid_threshold = 0.3

        # 計算線性域增益（作為參考）
        gain_linear = spp * gain_h1 + (1 - spp) * g_min_effective

        # 計算對數域增益
        log_gain_log = spp * log_gain_h1 + (1 - spp) * log_g_min_effective
        gain_log = np.exp(log_gain_log)

        # 低 SPP：50% 線性 + 50% 對數
        # 高 SPP：100% 對數（保留原有優勢）
        log_gain = np.where(
            spp < hybrid_threshold,
            np.log(0.5 * gain_linear + 0.5 * gain_log + 1e-10),  # 混合
            log_gain_log  # 純對數
        )

        # v1.5.0: 限制幀間變化速率（防止震動）
        if self.log_gain_prev is not None:
            log_gain_diff = log_gain - self.log_gain_prev
            max_change_db = 6.0  # 最大變化 6dB/幀
            log_gain_diff = np.clip(
                log_gain_diff,
                -max_change_db / 10,
                max_change_db / 10
            )
            log_gain = self.log_gain_prev + log_gain_diff

        # 4. 時間平滑（對數域）
        if self.log_gain_prev is not None:
            log_gain = self.alpha_g * self.log_gain_prev + \
                      (1 - self.alpha_g) * log_gain

        # 保存當前對數增益
        self.log_gain_prev = log_gain.copy()

        # 5. 轉回線性域
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
        指數積分 E1(v) 的近似

        參數:
            v: 輸入值

        返回:
            exp1_v: E1(v) 的近似值
        """
        result = np.zeros_like(v)

        # 對於 v >= 1，使用漸近展開
        mask_large = v >= 1.0
        if np.any(mask_large):
            v_large = v[mask_large]
            result[mask_large] = np.exp(-v_large) / v_large

        # 對於 v < 1，使用級數展開
        mask_small = ~mask_large
        if np.any(mask_small):
            v_small = v[mask_small]
            gamma_const = 0.5772156649
            result[mask_small] = -gamma_const - np.log(v_small + 1e-10) - v_small

        return result

    def reset(self):
        """重置狀態"""
        self.gain_prev = None
        self.log_gain_prev = None

    def __repr__(self):
        return (f"OmlsaGainCalculator(g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g})")
