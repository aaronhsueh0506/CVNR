"""V1: spectral-subtraction denoiser."""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import SimpleAverageNoiseEstimator
from core.gain_calculators import SpectralSubtractionGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Optional, Tuple
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
)


class SpectralSubtractionDenoiser(BaseDenoiser):
    """V1 spectral-subtraction denoiser (Boll, 1979): a fixed noise estimate from the
    lowest-energy frames, with per-frame gain smoothing. Simple, but prone to musical noise.

    The grid (frame_size, frame_shift, fft_size) is given together or resolved from sample_rate.
    alpha: over-subtraction factor (1.5-2.5); beta: spectral floor (0.002-0.02); alpha_smooth:
    gain smoothing; num_init_frames: frames used for the noise estimate. EMA and frame-count
    parameters are authored at a 10 ms hop and retimed to the grid.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        alpha: float = 2.0,
        beta: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20
    ):
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        num_init_frames = retime_frame_count(
            num_init_frames, sample_rate, frame_shift
        )
        alpha_smooth = retime_ema_alpha(
            alpha_smooth, sample_rate, frame_shift
        )

        self.processor = FrameProcessor(
            sample_rate=sample_rate,
            frame_size=frame_size,
            frame_shift=frame_shift,
            fft_size=fft_size,
            window_type='hanning'
        )

        self.reconstructor = Reconstructor(
            fft_size=fft_size,
            frame_shift=self.processor.frame_shift,
            window=self.processor.window
        )

        self.noise_estimator = SimpleAverageNoiseEstimator(
            num_init_frames=num_init_frames
        )

        self.gain_calculator = SpectralSubtractionGainCalculator(
            alpha=alpha,
            beta=beta,
            alpha_smooth=alpha_smooth
        )

        self.noise_magnitude = None

    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """Denoises noisy_signal (n_samples,); returns the enhanced signal (n_samples,)."""
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        enhanced_magnitudes, enhanced_phases = self.denoise_spectrum(magnitudes, phases)

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
        """Denoises magnitude and phase spectra (n_frames, n_freqs); the phase is returned unchanged."""
        n_frames = noisy_magnitude.shape[0]

        noise_psd = self.noise_estimator.estimate(noisy_magnitude)
        self.noise_magnitude = np.sqrt(noise_psd)

        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        for i in range(n_frames):
            gain = self.gain_calculator.calculate(
                noisy_magnitude[i],
                self.noise_magnitude
            )

            enhanced_magnitude[i] = gain * noisy_magnitude[i]

        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """Clears the noise estimator and gain state."""
        self.noise_estimator.reset()
        self.gain_calculator.reset()
        self.noise_magnitude = None

    def get_params(self) -> dict:
        """Returns the configuration as a dict."""
        return {
            'version': 'V1',
            'name': 'Spectral Subtraction',
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
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
