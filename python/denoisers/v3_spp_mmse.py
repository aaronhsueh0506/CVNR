"""V3: SPP-weighted MMSE denoiser."""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import SppMmseGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Optional, Tuple
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
)


class SppMmseDenoiser(BaseDenoiser):
    """V3 SPP-weighted MMSE denoiser (Ephraim and Malah, 1984): speech presence probability
    replaces a hard VAD, with decision-directed a-priori SNR and gain smoothing.

    The grid is given together or resolved from sample_rate; EMA and frame-count parameters are
    retimed to it. alpha_noise: noise smoothing; alpha_xi: a-priori SNR smoothing (0.92-0.98);
    q: speech prior; xi_min_db / g_min_db: SNR and gain floors in dB; alpha_g: gain smoothing;
    use_full_formula: Bessel MMSE-STSA (True) or the E1 form (False, default); noise_method:
    'recursive_average' or 'mcra'; mcra_accept_external_spp: MCRA noise gate driven by the
    external posterior (True) or the internal indicator (False).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        alpha_noise: float = 0.95,
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        use_full_formula: bool = False,
        num_init_frames: int = 20,
        # MCRA noise estimation
        noise_method: str = 'recursive_average',  # 'recursive_average' or 'mcra'
        alpha_s: float = 0.9,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        broadband_threshold: float = 0.8,
        scene_change_threshold_db: float = 10.0,
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        mcra_accept_external_spp: bool = True,
    ):
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        alpha_noise = retime_ema_alpha(alpha_noise, sample_rate, frame_shift)
        alpha_xi = retime_ema_alpha(alpha_xi, sample_rate, frame_shift)
        alpha_g = retime_ema_alpha(alpha_g, sample_rate, frame_shift)
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        L = retime_frame_count(L, sample_rate, frame_shift)
        num_init_frames = retime_frame_count(
            num_init_frames, sample_rate, frame_shift
        )
        scene_change_min_frames = retime_frame_count(
            scene_change_min_frames, sample_rate, frame_shift
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
                alpha_d=alpha_noise,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames,
                broadband_threshold=broadband_threshold,
                scene_change_threshold_db=scene_change_threshold_db,
                scene_change_min_frames=scene_change_min_frames,
                scene_change_blend=scene_change_blend,
                accept_external_spp=mcra_accept_external_spp,
            )
        else:
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha_noise,
                num_init_frames=num_init_frames,
                update_during_speech=False
            )

        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        self.gain_calculator = SppMmseGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_full_formula=use_full_formula
        )

        self.gain_prev = None

    def denoise(self, noisy_signal: np.ndarray, return_spp: bool = False):
        """Denoises noisy_signal (n_samples,); with return_spp also returns the SPP matrix (n_frames, n_freqs)."""
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        if return_spp:
            enhanced_magnitudes, enhanced_phases, spp_matrix = self.denoise_spectrum(
                magnitudes, phases, return_spp=True
            )
        else:
            enhanced_magnitudes, enhanced_phases = self.denoise_spectrum(magnitudes, phases)

        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        if return_spp:
            return enhanced_signal, spp_matrix
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False
    ):
        """Denoises magnitude and phase spectra (n_frames, n_freqs); the phase is returned
        unchanged. With return_spp the SPP history (n_frames, n_freqs) is returned as well.
        """
        n_frames = noisy_magnitude.shape[0]
        # Reset so consecutive calls on different audio start clean.
        self.reset()

        self.noise_estimator.estimate(noisy_magnitude)
        num_init = self.noise_estimator.num_init_frames

        enhanced_magnitude = np.zeros_like(noisy_magnitude)
        spp_history = [] if return_spp else None
        n_freqs = noisy_magnitude.shape[1]

        enhanced_psd_prev = None

        # The first num_init frames pass through (gain = 1) and seed the DD state.
        for i in range(n_frames):
            Y_psd = noisy_magnitude[i] ** 2

            if i < num_init:
                if return_spp:
                    spp_history.append(np.zeros(n_freqs))
                enhanced_magnitude[i] = noisy_magnitude[i]
                self.gain_prev = np.ones(n_freqs)
                enhanced_psd_prev = Y_psd.copy()
                continue

            noise_psd = self.noise_estimator.noise_psd

            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )

            if return_spp:
                spp_history.append(spp.copy())

            gain = self.gain_calculator.calculate(spp, xi, gamma)

            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            self.gain_prev = gain.copy()

            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # The SPP slows the noise update where speech is likely.
            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        enhanced_phase = noisy_phase

        if return_spp:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history)
        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """Clears the estimator and gain state."""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None

    def get_params(self) -> dict:
        """Returns the configuration as a dict."""
        params = {
            'version': 'V3',
            'name': 'MMSE-STSA',
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 20 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_full_formula': self.gain_calculator.use_full_formula,
            'num_init_frames': self.noise_estimator.num_init_frames
        }
        if self.noise_method == 'mcra':
            params['alpha_s'] = self.noise_estimator.alpha_s
            params['alpha_d'] = self.noise_estimator.alpha_d
            params['alpha_p'] = self.noise_estimator.alpha_p
            params['L'] = self.noise_estimator.L
        else:
            params['alpha_noise'] = self.noise_estimator.alpha
        return params

    def get_spp_statistics(self) -> dict:
        """Returns SPP and SNR statistics for analysis."""
        if self.spp_estimator.xi_prev is None:
            return {'status': 'not_initialized'}

        return {
            'status': 'initialized',
            'avg_xi_db': 10 * np.log10(np.mean(self.spp_estimator.xi_prev) + 1e-10),
            'avg_gamma_db': 10 * np.log10(np.mean(self.spp_estimator.gamma_prev) + 1e-10),
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min)
        }

    def __repr__(self):
        params = self.get_params()
        return (f"SppMmseDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"q={params['q']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
