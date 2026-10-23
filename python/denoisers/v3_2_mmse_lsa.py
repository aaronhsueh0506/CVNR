"""V3-2: MMSE-LSA / OM-LSA denoiser (Ephraim and Malah, 1985; Cohen, 2002)."""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import MmseLsaGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Optional, Tuple
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
    _SIXTEEN_MS_HOP_SECONDS,
    _REFERENCE_HOP_SECONDS,
)


# Frame speech gate anchor; equals the C ANR_SPEECH_PROTECT_ANCHOR_Q.
SPEECH_PROTECT_ANCHOR_Q = 0.52

def _hz_to_bin_ceil(hz, fft_size, sample_rate):
    """First FFT bin at or above hz."""
    return int(np.ceil(hz * fft_size / sample_rate))


def _hz_to_bin_floor_inclusive(hz, fft_size, sample_rate):
    """Number of FFT bins covering [0, hz] inclusive (a slice end)."""
    return int(np.floor(hz * fft_size / sample_rate)) + 1


class MmseLsaDenoiser(BaseDenoiser):
    """V3-2 OM-LSA denoiser: the MMSE-LSA gain is blended with the g_min floor by SPP and smoothed
    over time, both in the log domain.

    The grid is given together or resolved from sample_rate; EMA and frame-count parameters are
    retimed to it. Main parameters: alpha_xi (a-priori SNR smoothing), q (speech prior),
    xi_min_db / g_min_db (SNR and gain floors in dB), alpha_g / alpha_attack / alpha_decay (gain
    smoothing), noise_method ('recursive_average' or 'mcra'), strength (suppression depth, see
    core/nr_strength.py). The remaining options are optional controls that are off by default.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        alpha_noise: float = 0.95,  # deprecated alias of alpha_d
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        num_init_frames: int = 20,
        # MCRA noise estimation
        noise_method: str = 'recursive_average',  # 'recursive_average' or 'mcra'
        alpha_s: float = 0.9,
        alpha_d: float = None,      # None: alpha_noise
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        broadband_threshold: float = 0.8,
        scene_change_threshold_db: float = 10.0,
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        scene_change_flatness_threshold: float = 0.4,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None,  # None: alpha_g
        mcra_accept_external_spp: bool = True,
        # Pass extra_noise_psd to the tracker's post-hoc echo-explained-rise correction (needs
        # noise_method='mcra'; experimental, keep False).
        mcra_remove_echo_explained_rise: bool = False,
        # NR content-preservation mode; only 'full' exists (recorded for provenance).
        mode: str = 'full',
        # NR strength: suppression depth only.
        strength: str = 'balanced',
        # Optional frame/cross-band speech prior; the defaults are a no-op.
        cross_band_prior_strength: float = 0.0,
        cross_band_prior_threshold: float = 0.50,
        cross_band_prior_full_scale: float = 0.70,
        cross_band_prior_max_q: float = 0.54,
        cross_band_prior_alpha: float = 0.90,
        noise_over_subtraction: float = 1.0,
        speech_protect_floor_db: Optional[float] = None,
        speech_protect_threshold: float = 0.5,
        speech_protect_frame_threshold: Optional[float] = None,
        # Direction-aware MCRA update: base rate for the rising direction only (16 ms hop,
        # retimed). None: symmetric.
        alpha_noise_up: Optional[float] = None,
        # Speech-gated MCRA update: base rate in bins gated by noise_speech_gate_p; the estimate
        # may fall at the ordinary rate but rise no faster than this (16 ms hop, retimed). None: off.
        alpha_noise_speech: Optional[float] = None,
        noise_speech_gate_p: float = 0.2,
        # Frame-level condition for the speech-gated update: the mean gating probability over
        # the 80-4000 Hz band must exceed this. None: off.
        noise_frame_gate_p: Optional[float] = None,
        # Per-bin condition for the speech-gated update: the DD a-priori SNR must exceed this
        # (dB). None: use the SPP gate.
        noise_gate_xi_db: Optional[float] = None,
        # Broadband-onset escape for the speech-gated update: above this gated fraction the
        # frame is updated at the ordinary rate. None: off.
        noise_gate_max_frac: Optional[float] = None,
        # Frame-level output energy make-up after the per-bin gain: the amplitude ratio
        # g = sqrt(E_out / E_in) is raised by 1 + up_slope * (g - blim) when g > blim (never past
        # unity) and lowered by 1 - down_slope * (blim - g) when g < blim, blended by the frame
        # speech evidence. The DD state and the noise tracker see the unscaled gain.
        makeup_gain: bool = False,
        makeup_blim: float = 0.5,
        makeup_up_slope: float = 1.3,
        makeup_down_slope: float = 0.3,
        # Feed the DD a-priori SNR from the clamped H1 gain (Cohen 2001, eq. 18) instead of the
        # output gain.
        dd_from_gmmse: bool = False,
        # Frame-context speech prior on the gain-side SPP (see SppEstimator): q rises to
        # frame_prior_q_max as the mean fixed-prior SPP over frame_prior_band_hz goes from spp_lo
        # to spp_hi. The noise tracker always sees the fixed-prior SPP.
        frame_prior_q_max: Optional[float] = None,
        frame_prior_spp_lo: float = 0.5,
        frame_prior_spp_hi: float = 0.8,
        frame_prior_band_hz: Tuple[float, float] = (300.0, 3400.0),
        # Frame-gated gain floor: g_min rises by this many dB times the frame prior (0..1), so
        # speech frames get a shallower floor.
        frame_prior_gmin_lift_db: Optional[float] = None,
        # Floor blend domain in the gain calculator: 'log' | 'sqrt' | 'linear'.
        floor_blend: str = 'log',
        # Restrict the xi-gated slow noise rise to bins below this frequency; it is enabled for
        # the band only when more than noise_gate_frame_frac of the speech-band bins have DD xi
        # above noise_gate_xi_db. None: per-bin xi gate.
        noise_gate_lf_hz: Optional[float] = None,
        noise_gate_frame_frac: float = 0.1,
        # Frame speech evidence that blends the make-up: 'spp' (mean fixed-prior SPP over the
        # speech band) or 'xi' (0.1-EMA of min(1, fraction of bins with DD xi > makeup_prior_xi_db) / 0.15).
        makeup_prior: str = 'spp',
        makeup_prior_xi_db: float = 3.0,
    ):
        if alpha_noise_up is not None and not 0.0 <= alpha_noise_up < 1.0:
            raise ValueError("alpha_noise_up must be None or in [0, 1)")
        if alpha_noise_speech is not None and not 0.0 <= alpha_noise_speech < 1.0:
            raise ValueError("alpha_noise_speech must be None or in [0, 1)")
        if not (0.0 < makeup_blim < 1.0 and makeup_up_slope >= 0.0
                and 0.0 <= makeup_down_slope <= 1.0):
            raise ValueError(
                "makeup_blim must be in (0, 1), makeup_up_slope >= 0, "
                "and makeup_down_slope in [0, 1]"
            )
        self.noise_gate_xi = (10 ** (noise_gate_xi_db / 10)
                              if noise_gate_xi_db is not None else None)
        self.makeup_gain = bool(makeup_gain)
        self.makeup_blim = float(makeup_blim)
        self.makeup_up_slope = float(makeup_up_slope)
        self.makeup_down_slope = float(makeup_down_slope)
        self.dd_from_gmmse = bool(dd_from_gmmse)
        if makeup_prior not in ('spp', 'xi'):
            raise ValueError("makeup_prior must be 'spp' or 'xi'")
        if not 0.0 <= noise_gate_frame_frac <= 1.0:
            raise ValueError("noise_gate_frame_frac must be in [0, 1]")
        if noise_gate_lf_hz is not None and noise_gate_xi_db is None:
            raise ValueError("noise_gate_lf_hz requires noise_gate_xi_db")
        if frame_prior_gmin_lift_db is not None and not 0.0 <= frame_prior_gmin_lift_db <= -g_min_db:
            raise ValueError("frame_prior_gmin_lift_db must be in [0, -g_min_db]")
        self.frame_prior_gmin_lift_db = frame_prior_gmin_lift_db
        self.makeup_prior = makeup_prior
        self.makeup_prior_xi = 10 ** (makeup_prior_xi_db / 10)
        self.noise_gate_frame_frac = float(noise_gate_frame_frac)
        self._makeup_prior_state = 0.5
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        self.mode = mode
        self.strength = strength
        if not np.isfinite(noise_over_subtraction) or noise_over_subtraction < 1.0:
            raise ValueError("noise_over_subtraction must be finite and >= 1")
        self.noise_over_subtraction = float(noise_over_subtraction)
        if (speech_protect_frame_threshold is not None
                and (not np.isfinite(speech_protect_frame_threshold)
                     or not 0.0 <= speech_protect_frame_threshold <= 1.0)):
            raise ValueError(
                "speech_protect_frame_threshold must be None or in [0, 1]"
            )
        self.speech_protect_frame_threshold = speech_protect_frame_threshold
        # Applied gate = authored value + (q - anchor), in float32.
        self.speech_protect_frame_threshold_effective = (
            None if speech_protect_frame_threshold is None else
            float(np.float32(speech_protect_frame_threshold)
                  + (np.float32(q) - np.float32(SPEECH_PROTECT_ANCHOR_Q))))

        # Temporal coefficients are retimed once here: alpha_d, alpha_g and alpha_decay are
        # authored at 10 ms; alpha_xi, alpha_attack and L at 16 ms.
        alpha_d_effective = retime_ema_alpha(
            alpha_d if alpha_d is not None else alpha_noise, sample_rate, frame_shift
        )
        alpha_xi = retime_ema_alpha(
            alpha_xi, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        alpha_g = retime_ema_alpha(
            alpha_g, sample_rate, frame_shift,
            authored_hop_seconds=_REFERENCE_HOP_SECONDS,
        )
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        alpha_attack = retime_ema_alpha(
            alpha_attack, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        if alpha_decay is not None:
            alpha_decay = retime_ema_alpha(
                alpha_decay, sample_rate, frame_shift,
                authored_hop_seconds=_REFERENCE_HOP_SECONDS,
            )
        L = retime_frame_count(
            L, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
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

        n_freqs = fft_size // 2 + 1
        # Frame speech-evidence band (80-4000 Hz): its SPP mean and DD-xi fraction drive the LF
        # gain floor, the tracker guard and the optional priors.
        speech_bin_start = max(1, _hz_to_bin_ceil(80.0, fft_size, sample_rate))
        speech_bin_end = min(
            n_freqs,
            _hz_to_bin_floor_inclusive(min(4000.0, sample_rate / 2.0),
                                       fft_size, sample_rate),
        )
        self.speech_bin_start = speech_bin_start
        self.speech_bin_end = speech_bin_end

        if noise_method == 'mcra':
            alpha_d_up_effective = (
                retime_ema_alpha(alpha_noise_up, sample_rate, frame_shift,
                                 authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS)
                if alpha_noise_up is not None else None)
            alpha_d_speech_effective = (
                retime_ema_alpha(alpha_noise_speech, sample_rate, frame_shift,
                                 authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS)
                if alpha_noise_speech is not None else None)
            self.noise_estimator = McraNoiseEstimator(
                alpha_s=alpha_s,
                alpha_d=alpha_d_effective,
                alpha_d_up=alpha_d_up_effective,
                alpha_d_speech=alpha_d_speech_effective,
                speech_gate_p=noise_speech_gate_p,
                frame_gate_p=noise_frame_gate_p,
                gate_bin_start=speech_bin_start,
                gate_bin_end=speech_bin_end,
                slow_mask_max_frac=noise_gate_max_frac,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames,
                broadband_threshold=broadband_threshold,
                scene_change_threshold_db=scene_change_threshold_db,
                scene_change_min_frames=scene_change_min_frames,
                scene_change_blend=scene_change_blend,
                scene_change_flatness_threshold=scene_change_flatness_threshold,
                accept_external_spp=mcra_accept_external_spp,
                remove_echo_explained_rise=mcra_remove_echo_explained_rise,
            )
        else:
            if mcra_remove_echo_explained_rise:
                raise ValueError(
                    "mcra_remove_echo_explained_rise requires noise_method='mcra'")
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha_d_effective,
                num_init_frames=num_init_frames,
                update_during_speech=False
            )
        # Only McraNoiseEstimator.update() accepts extra_noise_psd.
        self._pass_extra_to_tracker = mcra_remove_echo_explained_rise

        self.noise_gate_lf_bin = (
            None if noise_gate_lf_hz is None
            else max(1, min(n_freqs, _hz_to_bin_ceil(noise_gate_lf_hz, fft_size, sample_rate)))
        )
        self.speech_protect_mask = np.zeros(n_freqs, dtype=bool)
        # The speech guard is low-band only so it does not lift broadband noise; without
        # noise_gate_lf_hz it covers the whole speech band.
        protect_end = (self.noise_gate_lf_bin
                       if self.noise_gate_lf_bin is not None else speech_bin_end)
        self.speech_protect_mask[1:protect_end] = True
        frame_prior_bin_start = max(
            1, _hz_to_bin_ceil(frame_prior_band_hz[0], fft_size, sample_rate))
        frame_prior_bin_end = min(
            n_freqs,
            _hz_to_bin_floor_inclusive(min(frame_prior_band_hz[1], sample_rate / 2.0),
                                       fft_size, sample_rate),
        )
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db,
            cross_band_prior_strength=cross_band_prior_strength,
            cross_band_prior_threshold=cross_band_prior_threshold,
            cross_band_prior_full_scale=cross_band_prior_full_scale,
            cross_band_prior_max_q=cross_band_prior_max_q,
            cross_band_prior_alpha=cross_band_prior_alpha,
            cross_band_prior_bin_start=speech_bin_start,
            cross_band_prior_bin_end=speech_bin_end,
            frame_prior_q_max=frame_prior_q_max,
            frame_prior_spp_lo=frame_prior_spp_lo,
            frame_prior_spp_hi=frame_prior_spp_hi,
            frame_prior_bin_start=frame_prior_bin_start,
            frame_prior_bin_end=frame_prior_bin_end,
            frame_prior_track=frame_prior_gmin_lift_db is not None,
        )
        self.gain_calculator = MmseLsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_asymmetric_smoothing=use_asymmetric_smoothing,
            alpha_attack=alpha_attack,
            alpha_decay=alpha_decay,
            spp_protect_floor_db=speech_protect_floor_db,
            spp_protect_threshold=speech_protect_threshold,
            floor_blend=floor_blend,
        )

        self.gain_prev = None

    def denoise(self, noisy_signal: np.ndarray, return_spp: bool = False,
                return_gain: bool = False, return_noise_psd: bool = False):
        """Denoises noisy_signal (n_samples,). Returns the enhanced signal followed by the requested
        spp / gain / noise_psd histories (n_frames, n_freqs), in that order.
        """
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        # denoise_spectrum returns (mag, phase, [spp], [gain], [noise_psd]) in flag order.
        result = self.denoise_spectrum(
            magnitudes, phases,
            return_spp=return_spp, return_gain=return_gain,
            return_noise_psd=return_noise_psd,
        )
        enhanced_magnitudes, enhanced_phases = result[0], result[1]
        extras = result[2:]

        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        if extras:
            return (enhanced_signal, *extras)
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False,
        return_gain: bool = False,
        return_noise_psd: bool = False,
        extra_noise_psd: np.ndarray = None
    ) -> tuple:  # (mag, phase, [spp], [gain], [noise_psd])
        """Denoises magnitude and phase spectra (n_frames, n_freqs); the phase is returned
        unchanged, followed by the requested spp / gain / noise_psd histories in that order. All
        state is reset on entry. extra_noise_psd (n_frames, n_freqs): residual-echo PSD added to
        the noise floor for the gain computation only.
        """
        self.reset()

        n_frames = noisy_magnitude.shape[0]

        # Digital-silence frames (every bin zero) do not count toward initialization and do
        # not advance the tracker.
        silent = ~np.any(noisy_magnitude, axis=1)
        num_init = self.noise_estimator.num_init_frames
        init_idx = np.flatnonzero(~silent)[:num_init]

        self.noise_estimator.estimate(
            noisy_magnitude[init_idx] if init_idx.size else noisy_magnitude)
        # Frames up to and including the num_init-th non-silent frame are passthrough.
        init_end = int(init_idx[-1]) + 1 if init_idx.size == num_init else n_frames

        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        spp_history = [] if return_spp else None
        gain_history = [] if return_gain else None
        # Noise PSD used for each frame's gain (excludes extra_noise_psd).
        noise_psd_history = [] if return_noise_psd else None

        enhanced_psd_prev = None

        # The first num_init frames pass through (gain = 1) and seed the DD state; update()
        # starts after initialization.
        n_freqs = noisy_magnitude.shape[1]
        for i in range(n_frames):
            Y_psd = noisy_magnitude[i] ** 2

            if i < init_end:
                gain = np.ones(n_freqs)
                if return_spp:
                    spp_history.append(np.zeros(n_freqs))
                if return_gain:
                    gain_history.append(gain.copy())
                if return_noise_psd:
                    noise_psd_history.append(self.noise_estimator.noise_psd.copy())
                enhanced_magnitude[i] = noisy_magnitude[i]
                self.gain_prev = gain.copy()
                enhanced_psd_prev = Y_psd.copy()
                continue

            noise_psd = self.noise_estimator.noise_psd
            # Fold the residual-echo PSD into this frame's noise floor (xi = S^2 / (N^2 + R^2));
            # the tracker's own noise_psd is not modified.
            if extra_noise_psd is not None:
                noise_psd = noise_psd + extra_noise_psd[i]
            if self.noise_over_subtraction != 1.0:
                noise_psd = self.noise_over_subtraction * noise_psd
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )
            # MCRA must see the fixed-prior posterior: feeding the lifted SPP back would freeze the
            # noise estimate (positive feedback).
            fixed_prior_spp = (
                self.spp_estimator.last_fixed_prior_spp
                if self.spp_estimator.last_fixed_prior_spp is not None
                else spp
            )
            if return_spp:
                spp_history.append(spp.copy())

            # Frame speech evidence: the mean SPP over the speech band gates the LF gain floor and
            # blends the make-up; the fraction of bins with DD xi above the gate drives the LF
            # tracker guard.
            frame_spp_mean = self.spp_estimator.last_evidence_mean
            if frame_spp_mean is None:
                frame_spp_mean = self._speech_band_mean(fixed_prior_spp)
            speech_xi_fraction = (
                self._speech_band_mean(xi > self.noise_gate_xi)
                if self.noise_gate_xi is not None else None)
            protect_frame = (
                self.speech_protect_frame_threshold_effective is None
                or frame_spp_mean >= self.speech_protect_frame_threshold_effective
            )
            makeup_weight = frame_spp_mean
            if self.makeup_gain and self.makeup_prior == 'xi':
                indicator = min(
                    1.0, self._speech_band_mean(xi > self.makeup_prior_xi) / 0.15)
                self._makeup_prior_state += 0.1 * (indicator - self._makeup_prior_state)
                self._makeup_prior_state = max(self._makeup_prior_state, 0.01)
                makeup_weight = self._makeup_prior_state
            g_min_frame = None
            if self.frame_prior_gmin_lift_db is not None:
                g_min_frame = self.gain_calculator.g_min * 10 ** (
                    self.frame_prior_gmin_lift_db
                    * self.spp_estimator.last_frame_prior / 20.0)
            gain = self.gain_calculator.calculate(
                spp, xi, gamma,
                g_min=g_min_frame,
                spp_protect_enabled=protect_frame,
                spp_protect_mask=self.speech_protect_mask,
            )
            if return_noise_psd:
                noise_psd_history.append(self.noise_estimator.noise_psd.copy())

            enhanced_magnitude[i] = gain * noisy_magnitude[i]
            self.gain_prev = gain.copy()
            if self.dd_from_gmmse:
                enhanced_psd_prev = (
                    self.gain_calculator.last_gain_mmse * noisy_magnitude[i]) ** 2
            else:
                enhanced_psd_prev = enhanced_magnitude[i] ** 2

            applied_scale = 1.0
            if self.makeup_gain:
                e_in = float(np.sum(Y_psd))
                e_out = float(np.sum(enhanced_magnitude[i] ** 2))
                g_frame = np.sqrt(e_out / (e_in + 1e-20))
                scale_up = 1.0
                if g_frame > self.makeup_blim:
                    scale_up = 1.0 + self.makeup_up_slope * (g_frame - self.makeup_blim)
                    if g_frame * scale_up > 1.0:
                        scale_up = 1.0 / g_frame
                scale_down = 1.0
                if g_frame < self.makeup_blim:
                    g_floored = max(g_frame, self.gain_calculator.g_min)
                    scale_down = 1.0 - self.makeup_down_slope * (self.makeup_blim - g_floored)
                applied_scale = (
                    makeup_weight * scale_up
                    + (1.0 - makeup_weight) * scale_down
                )
                enhanced_magnitude[i] *= applied_scale
            if return_gain:
                # Report the applied gain; the DD state keeps the pre-make-up gain.
                gain_history.append((gain * applied_scale).copy())

            noise_update_spp = (fixed_prior_spp
                                if (self.spp_estimator.cross_band_prior_strength > 0.0
                                    or self.spp_estimator.frame_prior_q_max is not None)
                                else spp)
            # extra_noise_psd reaches update() only when the experimental correction is enabled.
            tracker_update_kwargs = {}
            if self._pass_extra_to_tracker and extra_noise_psd is not None:
                tracker_update_kwargs['extra_noise_psd'] = extra_noise_psd[i]
            if silent[i]:
                pass
            elif self.noise_gate_xi is None:
                self.noise_estimator.update(noisy_magnitude[i], spp=noise_update_spp,
                                            **tracker_update_kwargs)
            else:
                if self.noise_gate_lf_bin is None:
                    slow_mask = xi > self.noise_gate_xi
                else:
                    # One frame-level decision for every bin below the LF boundary.
                    slow_mask = np.zeros(xi.shape, dtype=bool)
                    if speech_xi_fraction > self.noise_gate_frame_frac:
                        slow_mask[:self.noise_gate_lf_bin] = True
                self.noise_estimator.update(noisy_magnitude[i], spp=noise_update_spp,
                                            slow_mask=slow_mask,
                                            **tracker_update_kwargs)

        enhanced_phase = noisy_phase

        # Returns (mag, phase) plus the requested histories in flag order.
        outputs = [enhanced_magnitude, enhanced_phase]
        if return_spp:
            outputs.append(np.array(spp_history))
        if return_gain:
            outputs.append(np.array(gain_history))
        if return_noise_psd:
            outputs.append(np.array(noise_psd_history))
        return tuple(outputs)

    def _speech_band_mean(self, x):
        """Mean of x over the 80-4000 Hz speech-evidence band."""
        return float(np.mean(x[self.speech_bin_start:self.speech_bin_end]))

    def reset(self):
        """Clears the estimator, gain and make-up state."""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None
        self._makeup_prior_state = 0.5

    def get_params(self) -> dict:
        """Returns the configuration as a dict."""
        params = {
            'version': 'V3-2',
            'name': 'OMLSA (MMSE-LSA + SPP weighting)',
            'mode': self.mode,
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'cross_band_prior_strength': self.spp_estimator.cross_band_prior_strength,
            'cross_band_prior_threshold': self.spp_estimator.cross_band_prior_threshold,
            'cross_band_prior_full_scale': self.spp_estimator.cross_band_prior_full_scale,
            'cross_band_prior_max_q': self.spp_estimator.cross_band_prior_max_q,
            'cross_band_prior_alpha': self.spp_estimator.cross_band_prior_alpha,
            'noise_over_subtraction': self.noise_over_subtraction,
            'speech_protect_floor_db': self.gain_calculator.spp_protect_floor_db,
            'speech_protect_threshold': self.gain_calculator.spp_protect_threshold,
            'speech_protect_frame_threshold': self.speech_protect_frame_threshold,
            'speech_protect_frame_threshold_effective':
                self.speech_protect_frame_threshold_effective,
            'frame_prior_q_max': self.spp_estimator.frame_prior_q_max,
            'frame_prior_spp_lo': self.spp_estimator.frame_prior_spp_lo,
            'frame_prior_spp_hi': self.spp_estimator.frame_prior_spp_hi,
            'frame_prior_gmin_lift_db': self.frame_prior_gmin_lift_db,
            'floor_blend': self.gain_calculator.floor_blend,
            'noise_gate_lf_bin': self.noise_gate_lf_bin,
            'noise_gate_frame_frac': self.noise_gate_frame_frac,
            'noise_gate_xi_db': (None if self.noise_gate_xi is None
                                 else 10 * np.log10(self.noise_gate_xi)),
            'alpha_d_speech': (self.noise_estimator.alpha_d_speech
                               if self.noise_method == 'mcra' else None),
            'dd_from_gmmse': self.dd_from_gmmse,
            'makeup_gain': self.makeup_gain,
            'makeup_prior': self.makeup_prior,
            'makeup_prior_xi_db': 10 * np.log10(self.makeup_prior_xi),
            'makeup_blim': self.makeup_blim,
            'makeup_up_slope': self.makeup_up_slope,
            'makeup_down_slope': self.makeup_down_slope,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 20 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_asymmetric_smoothing': self.gain_calculator.use_asymmetric_smoothing,
            'alpha_attack': self.gain_calculator.alpha_attack,
            'alpha_decay': self.gain_calculator.alpha_decay,
            'num_init_frames': self.noise_estimator.num_init_frames
        }
        if self.noise_method == 'mcra':
            params['alpha_s'] = self.noise_estimator.alpha_s
            params['alpha_d'] = self.noise_estimator.alpha_d
            params['alpha_p'] = self.noise_estimator.alpha_p
            params['L'] = self.noise_estimator.L
            params['scene_change_flatness_threshold'] = (
                self.noise_estimator.scene_change_flatness_threshold
            )
        else:
            params['alpha_noise'] = self.noise_estimator.alpha
        return params

    def __repr__(self):
        params = self.get_params()
        return (f"MmseLsaDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
