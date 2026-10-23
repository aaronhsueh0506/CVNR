"""SPP-weighted MMSE gain calculator (V3)."""

import numpy as np
from typing import Optional

from .mmse_lsa import _exp1_approx

try:
    from scipy.special import exp1, i0, i1
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


class SppMmseGainCalculator:
    """SPP-weighted MMSE gain: G = p * G_H1 + (1 - p) * G_min.

    g_min_db: gain floor in amplitude dB (/20). alpha_g: gain smoothing. use_full_formula: MMSE-STSA
    with Bessel functions (Ephraim and Malah, 1984); False uses the E1 (MMSE-LSA) form.
    """

    def __init__(
        self,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        use_full_formula: bool = True
    ):
        self.g_min = 10 ** (g_min_db / 20)  # amplitude dB (/20)
        self.alpha_g = alpha_g
        self.use_full_formula = use_full_formula
        self.gain_prev = None

        self.gamma_const = np.sqrt(np.pi) / 2  # Gamma(1.5)

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """Gain (n_freqs,) from spp, xi and gamma (each (n_freqs,)); g_min, if given, replaces the floor."""
        g_min_effective = g_min if g_min is not None else self.g_min

        if self.use_full_formula:
            gain_mmse = self._mmse_stsa_gain_bessel(xi, gamma)
        else:
            gain_mmse = self._mmse_stsa_gain_e1(xi, gamma)

        gain = spp * gain_mmse + (1 - spp) * g_min_effective

        if self.gain_prev is not None:
            gain = self.alpha_g * self.gain_prev + (1 - self.alpha_g) * gain

        # Stored clipped to [0, 1] so the DD input stays valid.
        self.gain_prev = np.clip(gain, 0.0, 1.0).copy()

        gain = np.clip(gain, g_min_effective, 1.0)

        return gain

    def _mmse_stsa_gain_e1(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """E1 form G = xi / (1 + xi) * exp(0.5 * E1(v)), v = xi / (1 + xi) * gamma (MMSE-LSA)."""
        v = (xi / (1 + xi)) * gamma

        v = np.clip(v, 1e-10, 700)  # avoid overflow

        if SCIPY_AVAILABLE:
            exp1_v = exp1(v)
        else:
            exp1_v = _exp1_approx(v)

        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

        return gain

    def _mmse_stsa_gain_bessel(self, xi: np.ndarray, gamma: np.ndarray) -> np.ndarray:
        """MMSE-STSA gain with Modified Bessel functions (Ephraim and Malah, 1984).

        G = (Gamma(1.5) / gamma) * sqrt(v) * exp(-v/2) * [(1 + v) I0(v/2) + v I1(v/2)]; for v > 100
        the E1 form is used to avoid overflow.
        """
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)

        v_half = v / 2.0

        if SCIPY_AVAILABLE:
            bessel_i0 = i0(v_half)
            bessel_i1 = i1(v_half)
        else:
            bessel_i0 = self._bessel_i0_approx(v_half)
            bessel_i1 = self._bessel_i1_approx(v_half)

        # v > 100 uses the E1 form.
        mask_large = v > 100
        gain = np.zeros_like(v)

        mask_small = ~mask_large
        if np.any(mask_small):
            v_s = v[mask_small]
            v_half_s = v_s / 2.0
            i0_s = bessel_i0[mask_small] if isinstance(bessel_i0, np.ndarray) else i0(v_half_s)
            i1_s = bessel_i1[mask_small] if isinstance(bessel_i1, np.ndarray) else i1(v_half_s)
            gamma_s = gamma[mask_small]

            term = (1 + v_s) * i0_s + v_s * i1_s
            gain[mask_small] = (self.gamma_const / (gamma_s + 1e-10)) * \
                               np.sqrt(v_s) * np.exp(-v_half_s) * term

        if np.any(mask_large):
            v_l = v[mask_large]
            xi_l = xi[mask_large]
            gamma_l = gamma[mask_large]
            gain[mask_large] = self._mmse_stsa_gain_e1(
                xi_l.reshape(-1),
                gamma_l.reshape(-1)
            )

        return gain

    def _bessel_i0_approx(self, x: np.ndarray) -> np.ndarray:
        """Polynomial / asymptotic approximation of I0 (Abramowitz and Stegun)."""
        result = np.zeros_like(x)

        # x < 3.75: polynomial; otherwise asymptotic expansion.
        mask_small = x < 3.75
        if np.any(mask_small):
            t = (x[mask_small] / 3.75) ** 2
            result[mask_small] = 1.0 + 3.5156229*t + 3.0899424*t**2 + \
                                 1.2067492*t**3 + 0.2659732*t**4 + \
                                 0.0360768*t**5 + 0.0045813*t**6

        mask_large = ~mask_small
        if np.any(mask_large):
            ax = np.abs(x[mask_large])
            t = 3.75 / ax
            result[mask_large] = (np.exp(ax) / np.sqrt(ax)) * \
                                 (0.39894228 + 0.01328592*t + 0.00225319*t**2 -
                                  0.00157565*t**3 + 0.00916281*t**4 -
                                  0.02057706*t**5 + 0.02635537*t**6 -
                                  0.01647633*t**7 + 0.00392377*t**8)

        return result

    def _bessel_i1_approx(self, x: np.ndarray) -> np.ndarray:
        """Polynomial / asymptotic approximation of I1 (Abramowitz and Stegun)."""
        result = np.zeros_like(x)

        # x < 3.75: polynomial; otherwise asymptotic expansion.
        mask_small = x < 3.75
        if np.any(mask_small):
            t = (x[mask_small] / 3.75) ** 2
            result[mask_small] = x[mask_small] * \
                                 (0.5 + 0.87890594*t + 0.51498869*t**2 +
                                  0.15084934*t**3 + 0.02658733*t**4 +
                                  0.00301532*t**5 + 0.00032411*t**6)

        mask_large = ~mask_small
        if np.any(mask_large):
            ax = np.abs(x[mask_large])
            t = 3.75 / ax
            result[mask_large] = (np.exp(ax) / np.sqrt(ax)) * \
                                 (0.39894228 - 0.03988024*t - 0.00362018*t**2 +
                                  0.00163801*t**3 - 0.01031555*t**4 +
                                  0.02282967*t**5 - 0.02895312*t**6 +
                                  0.01787654*t**7 - 0.00420059*t**8)

        return result

    def reset(self):
        """Clears the gain history."""
        self.gain_prev = None

    def __repr__(self):
        formula = "Bessel" if self.use_full_formula else "E1"
        return (f"SppMmseGainCalculator(g_min={20*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, formula={formula})")
