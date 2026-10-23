"""Recursive-average noise estimator (V2 Wiener filter)."""

import numpy as np
from typing import Optional


class RecursiveAverageNoiseEstimator:
    """Recursive noise PSD: noise = alpha * noise + (1 - alpha) * |Y|^2.

    alpha: smoothing in [0, 1]; num_init_frames: frames used for initialization;
    update_during_speech: also update on speech frames; spp_hard_threshold: SPP above which the
    update stops.
    """

    def __init__(
        self,
        alpha: float = 0.95,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
        spp_hard_threshold: float = 0.8
    ):
        self.alpha = alpha
        self.num_init_frames = num_init_frames
        self.update_during_speech = update_during_speech
        self.spp_hard_threshold = spp_hard_threshold

        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """Initializes the noise PSD (n_freqs,) from the first num_init_frames of the magnitude spectrogram."""
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2
        self.noise_psd = np.mean(power_spectrum, axis=0)

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,
        spp: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """Updates the noise PSD (n_freqs,) from a magnitude frame (n_freqs,).

        spp (soft decision) takes precedence over is_speech (hard decision).
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        current_psd = magnitude ** 2

        if spp is not None:
            # SPP above the threshold stops the update; below it, alpha_tilde = alpha + (1 - alpha) * spp.
            hard_mask = spp > self.spp_hard_threshold
            soft_alpha = self.alpha + (1 - self.alpha) * spp
            tilde_alpha = np.where(hard_mask, 1.0, soft_alpha)

            self.noise_psd = tilde_alpha * self.noise_psd + (1 - tilde_alpha) * current_psd
        elif is_speech is not None and not self.update_during_speech:
            if not is_speech:
                self.noise_psd = self.alpha * self.noise_psd + \
                                (1 - self.alpha) * current_psd
        else:
            # No speech information: always update.
            self.noise_psd = self.alpha * self.noise_psd + \
                            (1 - self.alpha) * current_psd

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """Clears all state."""
        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0

    def __repr__(self):
        return (f"RecursiveAverageNoiseEstimator(alpha={self.alpha}, "
                f"num_init_frames={self.num_init_frames})")
