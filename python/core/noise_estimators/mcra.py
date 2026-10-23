"""MCRA-based noise estimator (minima-controlled recursive averaging, Cohen and Berdugo, 2002).

This is MCRA-lite, not canonical IMCRA (Cohen, 2003): single-pass minimum tracking and a
posterior-gated recursive average, without IMCRA's two-iteration minimum smoothing or bias
compensation. `accept_external_spp` selects the noise-update gate: True (default) uses the
posterior SPP passed in by the denoiser (the internal min-stat SPP if none is given); False always
uses the internal min-stat indicator, for callers whose posterior is unreliable (for example when
residual echo inflates it in noise-only bins).
"""

import numpy as np
from typing import Optional


def _spectral_flatness(power_band: np.ndarray) -> float:
    """Ratio of the geometric to the arithmetic mean of a power band, in (0, 1]."""
    p = power_band + 1e-20
    return np.exp(np.mean(np.log(p))) / np.mean(p)


class McraNoiseEstimator:
    """MCRA-lite noise estimator.

    Per bin: S = alpha_s * S + (1 - alpha_s) * |Y|^2; S_min = minimum of S over the last L frames;
    I = [S / (S_min * delta) > 1]; p = alpha_p * p + (1 - alpha_p) * I;
    alpha_tilde = alpha_d + (1 - alpha_d) * p_gate; N = alpha_tilde * N + (1 - alpha_tilde) * |Y|^2.
    p_gate is the external posterior when accept_external_spp is set and one is passed, else p.

    alpha_s: time smoothing (0.85-0.95); alpha_d: base noise update rate (0.70-0.90);
    alpha_p: SPP smoothing (0.1-0.3); L: minimum window in frames; delta_db: speech detection
    threshold in dB; num_init_frames: initialization frames.
    """

    # Below this the 1e-10 epsilons in every consumer of noise_psd dominate the estimate, which
    # then cannot be updated either (see update()). Equals SKR_NOISE_PSD_INERT in the C library (audiolib utility/simd_nr.h).
    NOISE_PSD_INERT = 1e-20

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        broadband_threshold: float = 0.8,
        scene_change_threshold_db: float = 10.0,
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        scene_change_flatness_threshold: float = 0.4,
        accept_external_spp: bool = True,  # True: external-posterior gate; False: internal gate
        # Direction-aware update: a bin whose power exceeds its estimate blends at this slower
        # rate instead of alpha_d, so partly flagged speech cannot ratchet the floor up.
        alpha_d_up: Optional[float] = None,
        # Speech-gated slow update: where the gating probability exceeds speech_gate_p the base
        # rate is alpha_d_speech and the estimate may only fall at the ordinary rate.
        alpha_d_speech: Optional[float] = None,
        speech_gate_p: float = 0.2,
        # Frame-level condition: the slow update needs the mean gating probability over
        # [gate_bin_start, gate_bin_end) to exceed frame_gate_p.
        frame_gate_p: Optional[float] = None,
        gate_bin_start: int = 0,
        gate_bin_end: Optional[int] = None,
        # Broadband-onset escape: above this gated fraction the ordinary update is kept.
        slow_mask_max_frac: Optional[float] = None,
        # Experimental; keep False. Removes the part of the noise rise explained by extra_noise_psd.
        remove_echo_explained_rise: bool = False,
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        if alpha_d_up is not None and not 0.0 <= alpha_d_up < 1.0:
            raise ValueError("alpha_d_up must be None or in [0, 1)")
        self.alpha_d_up = alpha_d_up
        if alpha_d_speech is not None and not 0.0 <= alpha_d_speech < 1.0:
            raise ValueError("alpha_d_speech must be None or in [0, 1)")
        if not 0.0 <= speech_gate_p <= 1.0:
            raise ValueError("speech_gate_p must be in [0, 1]")
        self.alpha_d_speech = alpha_d_speech
        self.speech_gate_p = speech_gate_p
        if frame_gate_p is not None and not 0.0 <= frame_gate_p <= 1.0:
            raise ValueError("frame_gate_p must be None or in [0, 1]")
        self.frame_gate_p = frame_gate_p
        self.gate_bin_start = int(gate_bin_start)
        self.gate_bin_end = gate_bin_end
        if slow_mask_max_frac is not None and not 0.0 < slow_mask_max_frac <= 1.0:
            raise ValueError("slow_mask_max_frac must be None or in (0, 1]")
        self.slow_mask_max_frac = slow_mask_max_frac
        self.remove_echo_explained_rise = remove_echo_explained_rise
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)
        self.num_init_frames = num_init_frames
        self.broadband_threshold = broadband_threshold

        self.scene_change_threshold = 10 ** (scene_change_threshold_db / 10)
        self.scene_change_min_frames = scene_change_min_frames
        self.scene_change_blend = scene_change_blend
        self.scene_change_flatness_threshold = scene_change_flatness_threshold
        self.scene_change_count = 0
        self.accept_external_spp = accept_external_spp

        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.min_buffer = None      # (L, n_freqs) minimum-tracking ring
        self._buf_ptr = 0           # circular-buffer write pointer
        self.spp = None

        self.is_initialized = False
        self.frame_count = 0

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """Initializes the noise PSD (n_freqs,) from the first num_init_frames of the magnitude
        spectrogram (n_frames, n_freqs) or one frame, using the 30th-percentile power per bin.
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_freqs = magnitude_spectrum.shape[1]

        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2

        # 30th percentile as the k-th smallest power (no interpolation).
        N = power_spectrum.shape[0]
        k = ((N - 1) * 30) // 100
        init_psd = np.partition(power_spectrum, k, axis=0)[k]

        # Floor against subnormal or zero init values at very low input levels.
        init_psd = np.maximum(init_psd, 1e-10)

        self.noise_psd = init_psd.copy()
        self.S = self.noise_psd.copy()
        self.S_min = self.noise_psd.copy()
        self.spp = np.zeros(n_freqs)

        # _buf_ptr starts at the last slot so the first update() writes slot 0.
        self.min_buffer = np.tile(init_psd, (self.L, 1))
        self._buf_ptr = self.L - 1

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # unused
        spp: Optional[np.ndarray] = None,  # external SPP (soft decision)
        slow_mask: Optional[np.ndarray] = None,  # per-bin override of the slow-update gate
        extra_noise_psd: Optional[np.ndarray] = None,  # power added upstream this frame
    ) -> np.ndarray:
        """Updates the noise PSD (n_freqs,) from a magnitude frame (n_freqs,).

        is_speech is ignored. spp: optional external SPP (n_freqs,). slow_mask: optional per-bin
        override of the slow-update gate. extra_noise_psd: power added upstream this frame, used
        only with remove_echo_explained_rise.
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        power = magnitude ** 2

        # Pre-update snapshot for the remove_echo_explained_rise correction at the end.
        apply_arm4 = self.remove_echo_explained_rise and extra_noise_psd is not None
        previous_noise_psd = self.noise_psd.copy() if apply_arm4 else None

        self.S = self.alpha_s * self.S + (1 - self.alpha_s) * power

        self._buf_ptr = (self._buf_ptr + 1) % self.L
        self.min_buffer[self._buf_ptr] = self.S

        self.S_min = np.min(self.min_buffer, axis=0)

        ratio = self.S / (self.S_min * self.delta + 1e-10)
        indicator = (ratio > 1.0).astype(float)

        self.spp = self.alpha_p * self.spp + (1 - self.alpha_p) * indicator

        # Scene change: high-band gamma high AND high-band spectral flatness high (speech is
        # ~0.1-0.2, white noise ~0.5-0.7).
        n_freqs = len(power)
        hi_start = n_freqs // 2  # upper half of the spectrum
        hi_power = power[hi_start:]
        # With remove_echo_explained_rise the energy test (not the flatness test) sees
        # echo-corrected power, so the trigger clears while a bin's rise is echo-explained.
        hi_power_for_gamma = (
            np.maximum(hi_power - extra_noise_psd[hi_start:], 0.0)
            if apply_arm4 else hi_power)
        hi_gamma = np.mean(hi_power_for_gamma) / (np.mean(self.noise_psd[hi_start:]) + 1e-10)

        # Flatness costs one log per high-band bin; compute it only when the energy gate passes.
        hi_energy_candidate = hi_gamma > self.scene_change_threshold
        hi_flatness = (_spectral_flatness(hi_power)
                       if hi_energy_candidate else 0.0)
        hit_now = bool(hi_energy_candidate
                       and hi_flatness > self.scene_change_flatness_threshold)

        if hit_now:
            self.scene_change_count += 1
            if self.scene_change_count >= self.scene_change_min_frames:
                blend = self.scene_change_blend
                self.noise_psd = blend * self.noise_psd + (1 - blend) * power
                # S_min and the ring use the same echo-corrected value as the noise_psd write.
                S_for_reset = (np.maximum(self.S - extra_noise_psd, 0.0)
                                if apply_arm4 else self.S)
                self.S_min = S_for_reset if apply_arm4 else S_for_reset.copy()
                self.min_buffer[:] = S_for_reset.reshape(1, -1)
                self.scene_change_count = 0
        else:
            self.scene_change_count = 0

        # Noise update gated by the external posterior or the internal indicator.
        spp_for_update = (spp if (self.accept_external_spp and spp is not None)
                          else self.spp)

        if self.broadband_threshold < 1.0:
            high_spp_ratio = np.mean(self.spp > 0.5)
            if high_spp_ratio > self.broadband_threshold:
                scale = max(0.0, 1.0 - (high_spp_ratio - self.broadband_threshold)
                            / (1.0 - self.broadband_threshold))
                spp_for_update = spp_for_update * scale

        tilde_alpha_d = self.alpha_d + (1 - self.alpha_d) * spp_for_update

        noise_new = tilde_alpha_d * self.noise_psd + (1 - tilde_alpha_d) * power
        if self.alpha_d_up is not None:
            # Both blends are convex, so the estimate rises exactly when power exceeds it; only
            # that direction takes the slow rate.
            tilde_up = self.alpha_d_up + (1 - self.alpha_d_up) * spp_for_update
            noise_up = tilde_up * self.noise_psd + (1 - tilde_up) * power
            noise_new = np.where(power > self.noise_psd, noise_up, noise_new)
        if self.alpha_d_speech is not None:
            speechy = (spp_for_update > self.speech_gate_p if slow_mask is None
                       else np.asarray(slow_mask, dtype=bool))
            if self.frame_gate_p is not None:
                gate_end = (len(spp_for_update) if self.gate_bin_end is None
                            else self.gate_bin_end)
                frame_mean = float(np.mean(
                    spp_for_update[self.gate_bin_start:gate_end]))
                if frame_mean <= self.frame_gate_p:
                    speechy = np.zeros_like(speechy)
            if (self.slow_mask_max_frac is not None
                    and np.mean(speechy) > self.slow_mask_max_frac):
                speechy = np.zeros_like(speechy)
            # Gated bins take the lower of the slow and ordinary candidates (a rise is held to the
            # slow rate); only those bins are computed.
            if speechy.any():
                tilde_sp = (self.alpha_d_speech
                            + (1 - self.alpha_d_speech) * spp_for_update[speechy])
                noise_slow = (tilde_sp * self.noise_psd[speechy]
                              + (1 - tilde_sp) * power[speechy])
                noise_new[speechy] = np.minimum(noise_slow, noise_new[speechy])
        self.noise_psd = noise_new

        # Dead-bin restart: a bin whose N decayed below NOISE_PSD_INERT is numerically inert and
        # would never track again once signal returns (the posterior saturates at 1.0); restart
        # it with the ungated blend.
        dead = self.noise_psd < self.NOISE_PSD_INERT
        if np.any(dead):
            self.noise_psd[dead] = (self.alpha_d * self.noise_psd[dead]
                                    + (1 - self.alpha_d) * power[dead])

        # remove_echo_explained_rise: for bins that rose this frame, remove the fraction of the
        # rise explainable by extra_noise_psd. This corrects where the extra power landed, not
        # the update rate.
        if apply_arm4:
            excess = power - previous_noise_psd
            rising = ((extra_noise_psd > 0.0)
                      & (self.noise_psd > previous_noise_psd)
                      & (excess > 0.0))
            if np.any(rising):
                fraction = np.minimum(extra_noise_psd[rising] / excess[rising], 1.0)
                self.noise_psd[rising] = (
                    previous_noise_psd[rising]
                    + (self.noise_psd[rising] - previous_noise_psd[rising])
                    * (1.0 - fraction)
                )

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """Clears all state."""
        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.min_buffer = None
        self._buf_ptr = 0
        self.spp = None
        self.is_initialized = False
        self.frame_count = 0
        self.scene_change_count = 0

    def __repr__(self):
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L})")
