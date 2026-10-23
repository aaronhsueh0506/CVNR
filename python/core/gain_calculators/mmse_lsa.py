"""MMSE-LSA / OM-LSA gain calculator.

G = G_H1^spp * g_min^(1 - spp) in the log domain, with G_H1 = xi / (1 + xi) * exp(0.5 * E1(v))
(Ephraim and Malah, 1985; Cohen, 2002).
"""

import numpy as np
from typing import Optional


def _exp1_approx(v: np.ndarray) -> np.ndarray:
    """Three-segment E1 approximation (Martin et al., 2004, Eq. 17); also used by SppMmseGainCalculator."""
    v = np.maximum(v, 1e-10)
    result = np.zeros_like(v)
    mask1 = v < 0.1
    mask2 = (v >= 0.1) & (v <= 1.0)
    mask3 = v > 1.0
    result[mask1] = -2.31 * np.log10(v[mask1]) - 0.6
    result[mask2] = -1.544 * np.log10(v[mask2]) + 0.166
    result[mask3] = 10 ** (-0.52 * v[mask3] - 0.26)
    return result


class MmseLsaGainCalculator:
    """OM-LSA gain: log-domain SPP-weighted blend of the MMSE-LSA H1 gain and the g_min floor.

    g_min_db: gain floor in amplitude dB (/20). alpha_g: symmetric gain smoothing; with
    use_asymmetric_smoothing, alpha_attack applies when the gain rises and alpha_decay (default
    alpha_g) when it falls. spp_protect_floor_db (optional): bins with spp above
    spp_protect_threshold keep at least this gain. floor_blend: 'log', 'sqrt' or 'linear'.
    """

    def __init__(
        self,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None,
        # Optional floor for high-SPP bins: gain >= spp_protect_floor where spp > threshold.
        spp_protect_floor_db: Optional[float] = None,
        spp_protect_threshold: float = 0.5,
        # Domain of the G_H1 / g_min blend: 'log' (OM-LSA), 'sqrt' (amplitude domain, as in the
        # Speex preprocessor) or 'linear'.
        floor_blend: str = 'log',
    ):
        # g_min is an amplitude floor (/20): the gain multiplies the magnitude spectrum directly.
        # SNR and power quantities use /10.
        self.g_min = 10 ** (g_min_db / 20)
        self.log_g_min = np.log(self.g_min + 1e-10)
        self.alpha_g = alpha_g

        self.use_asymmetric_smoothing = use_asymmetric_smoothing
        self.alpha_attack = alpha_attack
        self.alpha_decay = alpha_decay if alpha_decay is not None else alpha_g

        if (spp_protect_floor_db is not None
                and (not np.isfinite(spp_protect_floor_db)
                     or spp_protect_floor_db < g_min_db
                     or spp_protect_floor_db > 0.0)):
            raise ValueError(
                "spp_protect_floor_db must be finite and in [g_min_db, 0]"
            )
        if (not np.isfinite(spp_protect_threshold)
                or not 0.0 <= spp_protect_threshold <= 1.0):
            raise ValueError("spp_protect_threshold must be finite and in [0, 1]")
        self.spp_protect_floor_db = spp_protect_floor_db
        self.spp_protect_floor = (10 ** (spp_protect_floor_db / 20)  # amplitude gain floor
                                  if spp_protect_floor_db is not None else None)
        self.spp_protect_threshold = spp_protect_threshold

        if floor_blend not in ('log', 'sqrt', 'linear'):
            raise ValueError("floor_blend must be 'log', 'sqrt' or 'linear'")
        self.floor_blend = floor_blend

        self.log_gain_prev = None
        self.last_gain_mmse = None

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min=None,
        alpha_g_override: Optional[np.ndarray] = None,
        alpha_attack_override: Optional[np.ndarray] = None,
        alpha_decay_override: Optional[np.ndarray] = None,
        spp_protect_enabled: bool = True,
        spp_protect_mask: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """OM-LSA gain (n_freqs,) from spp, xi and gamma (each (n_freqs,)).

        g_min: optional scalar or per-bin floor. The alpha_*_override arguments replace the
        smoothing coefficients per bin; spp_protect_enabled and spp_protect_mask restrict the
        speech floor.
        """
        # g_min may be a scalar or a per-bin array.
        if g_min is None:
            g_min_effective = self.g_min
            log_g_min_effective = self.log_g_min
        else:
            g_min_effective = g_min
            log_g_min_effective = np.log(np.asarray(g_min_effective) + 1e-10)

        gain_mmse = self._mmse_gain_base(xi, gamma)
        gain_mmse = np.clip(gain_mmse, g_min_effective, 1.0)
        # Exposed so a caller can feed the DD a-priori SNR from the H1 gain (Cohen 2001, eq. 18).
        self.last_gain_mmse = gain_mmse

        if self.floor_blend == 'linear':
            log_gain = np.log(spp * gain_mmse + (1 - spp) * g_min_effective + 1e-10)
        elif self.floor_blend == 'sqrt':
            log_gain = 2.0 * np.log(spp * np.sqrt(gain_mmse)
                                    + (1 - spp) * np.sqrt(g_min_effective) + 1e-10)
        else:
            log_gain_mmse = np.log(gain_mmse + 1e-10)
            log_gain = spp * log_gain_mmse + (1 - spp) * log_g_min_effective

        if self.log_gain_prev is not None:
            if self.use_asymmetric_smoothing:
                alpha_attack_eff = (alpha_attack_override
                                    if alpha_attack_override is not None
                                    else self.alpha_attack)
                alpha_decay_eff = (alpha_decay_override
                                   if alpha_decay_override is not None
                                   else self.alpha_decay)
                alpha_effective = np.where(
                    log_gain > self.log_gain_prev,
                    alpha_attack_eff,
                    alpha_decay_eff,
                )
                log_gain = alpha_effective * self.log_gain_prev + (1 - alpha_effective) * log_gain
            else:
                alpha_g_eff = (alpha_g_override if alpha_g_override is not None
                               else self.alpha_g)
                log_gain = alpha_g_eff * self.log_gain_prev + (1 - alpha_g_eff) * log_gain

        gain = np.exp(log_gain)

        gain = np.clip(gain, g_min_effective, 1.0)

        # Speech floor: bins with spp above the threshold keep at least spp_protect_floor.
        if self.spp_protect_floor is not None and spp_protect_enabled:
            protect_bins = spp > self.spp_protect_threshold
            if spp_protect_mask is not None:
                protect_bins = protect_bins & spp_protect_mask
            # gain is the fresh np.clip result; raise only the protected bins in place.
            np.maximum(gain, self.spp_protect_floor, out=gain, where=protect_bins)

        self.log_gain_prev = np.log(gain + 1e-10)

        return gain

    def _mmse_gain_base(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """H1 gain xi / (1 + xi) * exp(0.5 * E1(v)) with v = xi / (1 + xi) * gamma."""
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)

        exp1_v = _exp1_approx(v)

        gain = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

        return gain

    def reset(self):
        """Clears the gain history."""
        self.log_gain_prev = None
        self.last_gain_mmse = None

    def __repr__(self):
        return (f"MmseLsaGainCalculator("
                f"g_min={20*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g})")


if __name__ == "__main__":
    print("MMSE-LSA / OM-LSA 增益計算器")

    print("\nSPP 對 OM-LSA 增益的影響（固定 ξ=1, γ=2）:")
    print("-" * 40)
    print("SPP  | gain")
    print("-" * 40)
    for s in (0.3, 0.5, 0.7, 0.9, 1.0):
        calc = MmseLsaGainCalculator(alpha_g=0.0, use_asymmetric_smoothing=False)
        g = calc.calculate(np.array([s]), np.array([1.0]), np.array([2.0]))[0]
        print(f"{s:.1f}  | {g:.4f}")

    print("\n結論: OM-LSA 以 SPP 在 log 域混合 G_H1 與 g_min，低 SPP 時壓得更低。")
