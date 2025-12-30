"""
V2: Wiener Filter Denoiser - Wiener 濾波降噪器
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import RecursiveAverageNoiseEstimator
from core.gain_calculators import WienerGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Tuple


class WienerDenoiser(BaseDenoiser):
    """
    版本 2: Wiener 濾波降噪器

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    優點:
        - 理論最優（MMSE 意義下）
        - 比頻譜減法音樂噪聲少
        - 遞歸更新噪聲估計

    缺點:
        - 仍有一定音樂噪聲
        - 需要較準確的噪聲估計

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        alpha: 噪聲平滑因子（0.9-0.95）
        min_gain: 最小增益
        num_init_frames: 初始噪聲估計幀數
        update_during_speech: 是否在語音段更新噪聲
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        alpha: float = 0.95,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        update_during_speech: bool = False
    ):
        super().__init__(sample_rate)

        # 創建處理器
        self.processor = FrameProcessor(
            sample_rate=sample_rate,
            frame_size_ms=frame_size_ms,
            frame_shift_ms=frame_shift_ms,
            fft_size=fft_size,
            window_type='hanning'
        )

        self.reconstructor = Reconstructor(
            fft_size=fft_size,
            frame_shift=self.processor.frame_shift,
            window=self.processor.window
        )

        # 創建噪聲估計器
        self.noise_estimator = RecursiveAverageNoiseEstimator(
            alpha=alpha,
            num_init_frames=num_init_frames,
            update_during_speech=update_during_speech
        )

        # 創建增益計算器
        self.gain_calculator = WienerGainCalculator(
            min_gain=min_gain,
            alpha_smooth=alpha_smooth
        )

    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
        """
        # 1. 分幀和 FFT
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        # 2. 降噪
        enhanced_magnitudes, enhanced_phases = self.denoise_spectrum(magnitudes, phases)

        # 3. 重建信號
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        return enhanced_signal

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
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
        """
        n_frames = noisy_magnitude.shape[0]

        # 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 對每一幀應用 Wiener 濾波
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        for i in range(n_frames):
            # 計算當前幀的功率譜
            noisy_psd = noisy_magnitude[i] ** 2

            # 獲取噪聲估計
            noise_psd = self.noise_estimator.noise_psd

            # 計算 Wiener 增益
            gain = self.gain_calculator.calculate(noisy_psd, noise_psd)

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 更新噪聲估計（遞歸）
            self.noise_estimator.update(noisy_magnitude[i])

        # 相位保持不變
        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.gain_calculator.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        return {
            'version': 'V2',
            'name': 'Wiener Filter',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'alpha': self.noise_estimator.alpha,
            'min_gain': self.gain_calculator.min_gain,
            'num_init_frames': self.noise_estimator.num_init_frames
        }

    def __repr__(self):
        params = self.get_params()
        return (f"WienerDenoiser("
                f"alpha={params['alpha']}, min_gain={params['min_gain']})")
