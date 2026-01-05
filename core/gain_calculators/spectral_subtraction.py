"""
Spectral Subtraction Gain Calculator - 頻譜減法增益計算器
用於 V1
"""

import numpy as np


class SpectralSubtractionGainCalculator:
    """
    頻譜減法增益計算

    公式:
        S_est(k) = max(|Y(k)| - alpha * |N(k)|, beta * |Y(k)|)
        gain(k) = S_est(k) / |Y(k)|

    參數:
        alpha: 過減因子 (over-subtraction factor)，通常 1.5-2.5
               - 越大降噪越多，但音樂噪聲也越嚴重
        beta: 頻譜下限 (spectral floor)，通常 0.002-0.02
              - 防止增益過小導致的失真
        alpha_smooth: 增益時間平滑因子，0.0-1.0（默認 0.8）
              - 用於減少 musical noise
              - 越大越平滑，但可能降低反應速度
    """

    def __init__(self, alpha: float = 2.0, beta: float = 0.01, alpha_smooth: float = 0.8):
        self.alpha = alpha
        self.beta = beta
        self.alpha_smooth = alpha_smooth
        self.prev_gain = None  # 前一幀的增益

    def calculate(
        self,
        noisy_magnitude: np.ndarray,
        noise_magnitude: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """
        計算頻譜減法增益

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_freqs,)
            noise_magnitude: 噪聲幅度譜 (n_freqs,)
            g_min: SNR adaptive 最小增益（可選，用於動態調整）

        返回:
            gain: 增益 (n_freqs,)
        """
        # 使用 SNR adaptive g_min (如果提供) 或默認 beta
        beta_effective = g_min if g_min is not None else self.beta

        # 頻譜減法
        # S_est = |Y| - alpha * |N|
        estimated_magnitude = noisy_magnitude - self.alpha * noise_magnitude

        # 應用頻譜下限
        # S_est = max(S_est, beta * |Y|)
        estimated_magnitude = np.maximum(
            estimated_magnitude,
            beta_effective * noisy_magnitude
        )

        # 計算增益
        gain = estimated_magnitude / (noisy_magnitude + 1e-10)

        # 限制增益範圍 [0, 1]
        gain = np.clip(gain, 0.0, 1.0)

        # 時間平滑（減少 musical noise）
        if self.prev_gain is not None and self.alpha_smooth > 0:
            gain = self.alpha_smooth * self.prev_gain + (1 - self.alpha_smooth) * gain

        # 保存當前增益供下一幀使用
        self.prev_gain = gain.copy()

        return gain

    def reset(self):
        """重置增益計算器狀態"""
        self.prev_gain = None

    def __repr__(self):
        return f"SpectralSubtractionGainCalculator(alpha={self.alpha}, beta={self.beta})"
