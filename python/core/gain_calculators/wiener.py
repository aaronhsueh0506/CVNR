"""Wiener-filter gain calculator (V2) with decision-directed a-priori SNR."""

import numpy as np


class WienerGainCalculator:
    """Wiener gain H = xi / (1 + xi).

    xi is the maximum-likelihood estimate max(gamma - 1, 0), or the decision-directed estimate
    with use_dd (Ephraim and Malah, 1984). min_gain: gain floor; alpha_smooth: temporal gain
    smoothing in [0, 1]; alpha_dd: DD smoothing in [0, 1].
    """

    def __init__(
        self,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        use_dd: bool = True,
        alpha_dd: float = 0.98
    ):
        self.min_gain = min_gain
        self.alpha_smooth = alpha_smooth
        self.use_dd = use_dd
        self.alpha_dd = alpha_dd

        self.prev_gain = None
        self.prev_gamma = None
        self.prev_xi = None

    def calculate(
        self,
        noisy_psd: np.ndarray,
        noise_psd: np.ndarray,
        g_min: float = None,
        enhanced_mag_prev: np.ndarray = None
    ) -> np.ndarray:
        """Wiener gain (n_freqs,) from power spectra (n_freqs,).

        g_min, if given, replaces min_gain. enhanced_mag_prev (previous-frame enhanced magnitude)
        selects the DD estimate with the current noise PSD.
        """
        min_gain_effective = g_min if g_min is not None else self.min_gain

        gamma = noisy_psd / (noise_psd + 1e-10)

        if self.use_dd and enhanced_mag_prev is not None:
            # DD: xi = alpha_dd * |X_prev|^2 / N + (1 - alpha_dd) * max(gamma - 1, 0)
            xi_ml = np.maximum(gamma - 1, 0)
            enhanced_psd_prev = enhanced_mag_prev ** 2
            xi = self.alpha_dd * (enhanced_psd_prev / (noise_psd + 1e-10)) + \
                 (1 - self.alpha_dd) * xi_ml
            xi = np.maximum(xi, 1e-10)
        elif self.use_dd and self.prev_gain is not None and self.prev_gamma is not None:
            # Fallback DD from the previous gain and gamma.
            xi_ml = np.maximum(gamma - 1, 0)
            xi = self.alpha_dd * (self.prev_gain ** 2 * self.prev_gamma) + \
                 (1 - self.alpha_dd) * xi_ml
            xi = np.maximum(xi, 1e-10)
        else:
            # ML estimate (first frame or DD disabled).
            xi = np.maximum(gamma - 1, 0)

        gain = xi / (1 + xi + 1e-10)

        gain = np.maximum(gain, min_gain_effective)

        gain = np.clip(gain, 0.0, 1.0)

        if self.prev_gain is not None and self.alpha_smooth > 0:
            gain = self.alpha_smooth * self.prev_gain + (1 - self.alpha_smooth) * gain

        self.prev_gain = gain.copy()
        self.prev_gamma = gamma.copy()
        self.prev_xi = xi.copy()

        return gain

    def reset(self):
        """Clears all state."""
        self.prev_gain = None
        self.prev_gamma = None
        self.prev_xi = None

    def soft_reset(self, decay_factor: float = 0.5):
        """Decays the stored gain by decay_factor in [0, 1] (0 = hard reset, 1 = no decay)."""
        if self.prev_gain is not None:
            self.prev_gain *= decay_factor

    def __repr__(self):
        dd_str = f", DD(α={self.alpha_dd})" if self.use_dd else ""
        return f"WienerGainCalculator(min_gain={self.min_gain}{dd_str})"
