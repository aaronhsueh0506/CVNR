"""
OMLSA - Optimally Modified Log-Spectral Amplitude
用於 V3-4, V4

標準 OMLSA 實現（Cohen, 2002）
使用對數域 SPP 加權: log(G) = p*log(G_h1) + (1-p)*log(G_min)
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

    v1.5.0: 支持非對稱平滑
    - Attack (增益上升): 使用 alpha_attack (快速響應)
    - Decay (增益下降): 使用 alpha_decay (慢速抑制 Musical Noise)

    參數:
        g_min_db: 最小增益（dB）
        alpha_g: 增益平滑因子
        gamma_0: SPP 閾值參數
        use_asymmetric_smoothing: 是否使用非對稱平滑 (v1.5.0)
        alpha_attack: Attack 平滑因子 (增益上升時使用，預設 0.3)
        alpha_decay: Decay 平滑因子 (增益下降時使用，預設 alpha_g)
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        gamma_0: float = 4.6,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.gamma_0 = gamma_0

        # v1.5.0: 非對稱平滑參數
        self.use_asymmetric_smoothing = use_asymmetric_smoothing
        self.alpha_attack = alpha_attack
        self.alpha_decay = alpha_decay if alpha_decay is not None else alpha_g

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
        計算 OMLSA 增益 (Cohen 2002)

        OMLSA = MMSE-LSA + SPP 加權
        公式: G = G_H1^p × G_min^(1-p)

        這和 MMSE-LSA with SPP weighting 是同一個算法。
        Cohen 2002 證明這是 signal presence uncertainty 下的最優估計器。

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
        # G_H1 = (ξ/(1+ξ)) × exp(0.5 × E1(v))
        gain_h1 = self._mmse_lsa_gain(xi, gamma)

        # 2. 對數域 SPP 加權（OMLSA, Cohen 2002）
        # G = G_H1^p × G_min^(1-p)
        # 等價於: log(G) = p×log(G_H1) + (1-p)×log(G_min)
        log_gain_h1 = np.log(gain_h1 + 1e-10)
        log_g_min_effective = np.log(g_min_effective + 1e-10)
        log_gain = spp * log_gain_h1 + (1 - spp) * log_g_min_effective

        # v2.1: 對數域時間平滑
        # v1.5.0: 支持非對稱平滑
        if self.log_gain_prev is not None and self.alpha_g > 0:
            if self.use_asymmetric_smoothing:
                # 非對稱平滑: Attack 快, Decay 慢
                # Attack: log_gain > log_gain_prev (增益上升)
                # Decay: log_gain <= log_gain_prev (增益下降)
                alpha_effective = np.where(
                    log_gain > self.log_gain_prev,
                    self.alpha_attack,  # Attack: 快速響應
                    self.alpha_decay    # Decay: 慢速抑制 Musical Noise
                )
                log_gain = alpha_effective * self.log_gain_prev + (1 - alpha_effective) * log_gain
            else:
                # 對稱平滑 (原始行為)
                log_gain = self.alpha_g * self.log_gain_prev + (1 - self.alpha_g) * log_gain

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
