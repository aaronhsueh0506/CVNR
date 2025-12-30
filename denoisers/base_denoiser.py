"""
Base Denoiser - 降噪器基類
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class BaseDenoiser(ABC):
    """
    降噪器抽象基類

    定義所有降噪器的通用接口
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.is_initialized = False

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

    def __repr__(self):
        return f"{self.__class__.__name__}(sample_rate={self.sample_rate})"
