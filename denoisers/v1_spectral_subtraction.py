"""
V1: Spectral Subtraction Denoiser - 頻譜減法降噪器
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import SimpleAverageNoiseEstimator
from core.gain_calculators import SpectralSubtractionGainCalculator
from core.snr_detector import SnrDetector
from core.clean_detector import CleanDetector
from .base_denoiser import BaseDenoiser
from typing import Tuple, Optional


class SpectralSubtractionDenoiser(BaseDenoiser):
    """
    版本 1: 頻譜減法降噪器

    最經典的降噪算法（Boll, 1979）

    優點:
        - 計算簡單，實時性好
        - 容易理解和實現

    缺點:
        - 嚴重的音樂噪聲
        - 固定的噪聲估計可能不準確

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        alpha: 過減因子（1.5-2.5）
        beta: 頻譜下限（0.002-0.02）
        num_init_frames: 初始噪聲估計幀數
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        alpha: float = 2.0,
        beta: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        snr_adaptive_config: Optional[dict] = None
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
        self.noise_estimator = SimpleAverageNoiseEstimator(
            num_init_frames=num_init_frames
        )

        # 創建增益計算器
        self.gain_calculator = SpectralSubtractionGainCalculator(
            alpha=alpha,
            beta=beta,
            alpha_smooth=alpha_smooth
        )

        # SNR Adaptive Processing (Phase 3)
        self.snr_adaptive_config = snr_adaptive_config or {}
        if self.snr_adaptive_config.get('enable', False):
            self.snr_detector = SnrDetector(
                smoothing_factor=self.snr_adaptive_config.get('snr_smoothing', 0.9)
            )
            self.base_g_min_db = self.snr_adaptive_config.get('base_g_min_db', -12.0)

            if self.snr_adaptive_config.get('clean_detection', False):
                self.clean_detector = CleanDetector(
                    snr_threshold=25.0,
                    confirm_frames=50
                )
            else:
                self.clean_detector = None
        else:
            self.snr_detector = None
            self.clean_detector = None
            self.base_g_min_db = None

        self.noise_magnitude = None

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

        # 估計噪聲（使用前幾幀）
        noise_psd = self.noise_estimator.estimate(noisy_magnitude)
        self.noise_magnitude = np.sqrt(noise_psd)

        # 對每一幀應用頻譜減法
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        for i in range(n_frames):
            # SNR Adaptive Processing (Phase 3)
            g_min = None
            if self.snr_detector is not None:
                # 計算功率譜密度
                Y_psd = noisy_magnitude[i] ** 2
                noise_psd = self.noise_magnitude ** 2

                # 估計 SNR
                snr_db = self.snr_detector.estimate_frame_snr(Y_psd, noise_psd)

                # Clean detection (if enabled)
                if self.clean_detector is not None:
                    is_clean = self.clean_detector.update(snr_db, noise_psd)

                # 獲取 adaptive g_min
                g_min = self.snr_detector.get_adaptive_g_min(snr_db, self.base_g_min_db)

            # 計算增益
            gain = self.gain_calculator.calculate(
                noisy_magnitude[i],
                self.noise_magnitude,
                g_min=g_min
            )

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

        # 相位保持不變
        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.gain_calculator.reset()
        self.noise_magnitude = None

        # Reset SNR adaptive detectors
        if self.snr_detector is not None:
            self.snr_detector.snr_history = []
        if self.clean_detector is not None:
            self.clean_detector.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        return {
            'version': 'V1',
            'name': 'Spectral Subtraction',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'alpha': self.gain_calculator.alpha,
            'beta': self.gain_calculator.beta,
            'num_init_frames': self.noise_estimator.num_init_frames
        }

    def __repr__(self):
        params = self.get_params()
        return (f"SpectralSubtractionDenoiser("
                f"alpha={params['alpha']}, beta={params['beta']}, "
                f"num_init_frames={params['num_init_frames']})")
