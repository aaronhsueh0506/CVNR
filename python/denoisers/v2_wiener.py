"""V2: Wiener-filter denoiser with decision-directed a-priori SNR (no SPP, no over-subtraction)."""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import WienerGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Optional, Tuple
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
)


class WienerDenoiser(BaseDenoiser):
    """V2 Wiener denoiser: decision-directed SNR with the noise PSD from a recursive average
    (default) or MCRA.

    The grid is given together or resolved from sample_rate; EMA and frame-count parameters are
    retimed to it. enable_noise_tracking is accepted for interface compatibility and unused.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        noise_method: str = 'recursive_average',
        alpha: float = 0.95,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
        use_dd: bool = True,
        alpha_dd: float = 0.98,
        # MCRA 參數
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        # Accepted for interface compatibility; unused.
        enable_noise_tracking: bool = False,
    ):
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        alpha = retime_ema_alpha(alpha, sample_rate, frame_shift)
        alpha_smooth = retime_ema_alpha(alpha_smooth, sample_rate, frame_shift)
        alpha_dd = retime_ema_alpha(alpha_dd, sample_rate, frame_shift)
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_d = retime_ema_alpha(alpha_d, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        L = retime_frame_count(L, sample_rate, frame_shift)
        num_init_frames = retime_frame_count(
            num_init_frames, sample_rate, frame_shift
        )
        scene_change_min_frames = retime_frame_count(
            5, sample_rate, frame_shift
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

        if noise_method == 'mcra':
            self.noise_estimator = McraNoiseEstimator(
                alpha_s=alpha_s,
                alpha_d=alpha_d,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames,
                scene_change_min_frames=scene_change_min_frames,
                accept_external_spp=False,  # Wiener has no OM-LSA posterior to supply
            )
        else:
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha,
                num_init_frames=num_init_frames,
                update_during_speech=update_during_speech
            )

        self.gain_calculator = WienerGainCalculator(
            min_gain=min_gain,
            alpha_smooth=alpha_smooth,
            use_dd=use_dd,
            alpha_dd=alpha_dd
        )


        self.enhanced_mag_prev = None

    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)
        enhanced_magnitudes, enhanced_phases = self.denoise_spectrum(magnitudes, phases)
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes, enhanced_phases, original_length=len(noisy_signal)
        )
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        
        n_frames = noisy_magnitude.shape[0]

        self.noise_estimator.estimate(noisy_magnitude)
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        for i in range(n_frames):
            noisy_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            
            gain = self.gain_calculator.calculate(
                noisy_psd,
                noise_psd,
                enhanced_mag_prev=self.enhanced_mag_prev
            )

            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            self.enhanced_mag_prev = enhanced_magnitude[i].copy()

            self.noise_estimator.update(noisy_magnitude[i])

        return enhanced_magnitude, noisy_phase

    def reset(self):
        self.noise_estimator.reset()
        self.gain_calculator.reset()
        self.enhanced_mag_prev = None

    def get_params(self) -> dict:
        params = {
            'version': 'V2.3',
            'name': 'Wiener Filter (DD only)',
            'use_dd': self.gain_calculator.use_dd,
            'alpha_dd': self.gain_calculator.alpha_dd,
            'noise_method': self.noise_method
        }
        if self.noise_method == 'mcra':
            params.update({
                'alpha_s': self.noise_estimator.alpha_s,
                'L': self.noise_estimator.L
            })
        else:
            params['alpha'] = self.noise_estimator.alpha
            
        return params
