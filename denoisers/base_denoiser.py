"""
Base Denoiser - 降噪器基類

v2.6: 添加 Human Voice Band Soft VAD 後處理
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class BaseDenoiser(ABC):
    """
    降噪器抽象基類

    定義所有降噪器的通用接口

    v2.6 新增:
        - Human Voice Band Soft VAD: 基於語音頻帶能量的軟 VAD
        - 頻率範圍: 300Hz - 3400Hz
        - 非語音段衰減至 0.1，語音段保持 1.0
    """

    def __init__(self, sample_rate: int = 16000, n_fft: int = 512):
        self.sample_rate = sample_rate
        self.is_initialized = False

        # Soft VAD 參數
        self.n_fft = n_fft
        self.vad_freq_low = 300    # Hz
        self.vad_freq_high = 3400  # Hz
        self.alpha_vad = 0.95      # VAD 平滑因子
        self.vad_state = 1.0       # VAD 狀態

        # 計算頻率 bin 索引
        freq_resolution = sample_rate / n_fft
        self.vad_start_bin = int(self.vad_freq_low / freq_resolution)
        self.vad_end_bin = min(int(self.vad_freq_high / freq_resolution), n_fft // 2 + 1)

    @abstractmethod
    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
        """
        pass

    @abstractmethod
    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        在頻域進行降噪

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（通常不變）(n_frames, n_freqs)
        """
        pass

    @abstractmethod
    def reset(self):
        """重置降噪器狀態"""
        pass

    def _apply_soft_vad(self, enhanced_mag: np.ndarray) -> np.ndarray:
        """
        Human Voice Band Soft VAD

        基於語音頻帶 (300Hz - 3400Hz) 能量進行軟 VAD 處理。
        非語音幀會被衰減，語音幀保持不變。

        映射函數: y = 0.1 + 0.9 * (1 - exp(-3 * sum_power))
        - sum_power ≈ 0 → y ≈ 0.1 (非語音，衰減)
        - sum_power ≈ 2 → y ≈ 1.0 (語音，保持)

        參數:
            enhanced_mag: 增強後的幅度譜 (n_freqs,)

        返回:
            vad_enhanced_mag: 經 VAD 處理的幅度譜 (n_freqs,)
        """
        # 1. 提取語音頻帶功率（使用 sum 而非 mean，自然放大到合適範圍）
        speech_band = enhanced_mag[self.vad_start_bin:self.vad_end_bin]
        sum_power = np.sum(speech_band ** 2) + 1e-10

        # 2. 映射到 [0.1, 1.0]
        vad_inst = 0.1 + 0.9 * (1.0 - np.exp(-3.0 * sum_power))

        # 3. 時間平滑
        self.vad_state = self.alpha_vad * self.vad_state + (1 - self.alpha_vad) * vad_inst

        # 4. 套用增益
        return enhanced_mag * self.vad_state

    def _reset_vad(self):
        """重置 VAD 狀態"""
        self.vad_state = 1.0

    def __repr__(self):
        return f"{self.__class__.__name__}(sample_rate={self.sample_rate})"
