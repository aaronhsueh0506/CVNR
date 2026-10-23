"""Spectral-subtraction gain calculator (V1)."""

import numpy as np


class SpectralSubtractionGainCalculator:
    """Spectral-subtraction gain: S_est = max(|Y| - alpha * |N|, beta * |Y|), gain = S_est / |Y|.

    alpha: over-subtraction factor (typically 1.5-2.5). beta: spectral floor (0.002-0.02).
    alpha_smooth: temporal gain smoothing in [0, 1] (0 disables).
    """

    def __init__(self, alpha: float = 2.0, beta: float = 0.01, alpha_smooth: float = 0.8):
        self.alpha = alpha
        self.beta = beta
        self.alpha_smooth = alpha_smooth
        self.prev_gain = None

    def calculate(
        self,
        noisy_magnitude: np.ndarray,
        noise_magnitude: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """Gain (n_freqs,) from magnitude spectra (n_freqs,); g_min, if given, replaces beta."""
        beta_effective = g_min if g_min is not None else self.beta

        estimated_magnitude = noisy_magnitude - self.alpha * noise_magnitude

        estimated_magnitude = np.maximum(
            estimated_magnitude,
            beta_effective * noisy_magnitude
        )

        gain = estimated_magnitude / (noisy_magnitude + 1e-10)

        gain = np.clip(gain, 0.0, 1.0)

        if self.prev_gain is not None and self.alpha_smooth > 0:
            gain = self.alpha_smooth * self.prev_gain + (1 - self.alpha_smooth) * gain

        self.prev_gain = gain.copy()

        return gain

    def reset(self):
        """Clears the smoothing state."""
        self.prev_gain = None

    def __repr__(self):
        return f"SpectralSubtractionGainCalculator(alpha={self.alpha}, beta={self.beta})"
