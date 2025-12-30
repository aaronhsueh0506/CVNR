"""
Wiener Filter Gain Calculator - Wiener 濾波增益計算器
用於 V2
"""

import numpy as np


class WienerGainCalculator:
    """
    Wiener 濾波增益計算

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    公式:
        H(k) = SNR(k) / (1 + SNR(k))
        其中 SNR(k) = S(k) / N(k)

    參數:
        min_gain: 最小增益，防止過度抑制
        alpha_smooth: 增益時間平滑因子，0.0-1.0（默認 0.8）
                     - 用於減少 musical noise
                     - 越大越平滑，但可能降低反應速度
    """

    def __init__(self, min_gain: float = 0.01, alpha_smooth: float = 0.8):
        self.min_gain = min_gain
        self.alpha_smooth = alpha_smooth
        self.prev_gain = None  # 前一幀的增益

    def calculate(
        self,
        noisy_psd: np.ndarray,
        noise_psd: np.ndarray
    ) -> np.ndarray:
        """
        計算 Wiener 濾波增益

        參數:
            noisy_psd: 帶噪語音功率譜密度 (n_freqs,)
            noise_psd: 噪聲功率譜密度 (n_freqs,)

        返回:
            gain: Wiener 增益 (n_freqs,)
        """
        # 估計語音功率譜
        # S_psd = Y_psd - N_psd
        speech_psd = np.maximum(noisy_psd - noise_psd, 0)

        # 計算 SNR
        # SNR = S_psd / N_psd
        snr = speech_psd / (noise_psd + 1e-10)

        # Wiener 增益
        # H = SNR / (1 + SNR) = S / (S + N)
        gain = snr / (1 + snr)

        # 等價形式：
        # gain = speech_psd / (speech_psd + noise_psd)
        # gain = speech_psd / noisy_psd

        # 應用最小增益
        gain = np.maximum(gain, self.min_gain)

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
        return f"WienerGainCalculator(min_gain={self.min_gain})"
