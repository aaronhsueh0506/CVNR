"""Speech presence probability (SPP) estimator for the V3 (OM-LSA) denoisers."""

import numpy as np
from typing import Tuple, Optional


def _band_slice(n_freqs, start, end):
    """Clamp an optional [start, end) bin range to the spectrum."""
    start = 0 if start is None else max(0, min(int(start), n_freqs - 1))
    end = n_freqs if end is None else max(start + 1, min(int(end), n_freqs))
    return start, end


def _ramp01(x, lo, hi):
    """(x - lo) / (hi - lo) clipped to [0, 1]."""
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


class SppEstimator:
    """Decision-directed speech presence probability per time-frequency bin, in [0, 1].

    alpha: a-priori SNR smoothing (0.92-0.98); q: speech prior probability; xi_min_db: a-priori
    SNR floor in dB. The optional frame and cross-band priors raise q for weak bins in frames
    with strong speech evidence and are off by default. Reference: Cohen and Berdugo (2001).
    """

    def __init__(
        self,
        alpha: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        cross_band_prior_strength: float = 0.0,
        cross_band_prior_threshold: float = 0.50,
        cross_band_prior_full_scale: float = 0.70,
        cross_band_prior_max_q: float = 0.54,
        cross_band_prior_alpha: float = 0.90,
        cross_band_prior_bin_start: Optional[int] = None,
        cross_band_prior_bin_end: Optional[int] = None,
        # Frame-context speech prior (gain side only): q rises towards frame_prior_q_max as the
        # mean fixed-prior SPP over [frame_prior_bin_start, frame_prior_bin_end) goes from
        # frame_prior_spp_lo to frame_prior_spp_hi. None disables it.
        frame_prior_q_max: Optional[float] = None,
        frame_prior_spp_lo: float = 0.5,
        frame_prior_spp_hi: float = 0.8,
        frame_prior_bin_start: Optional[int] = None,
        frame_prior_bin_end: Optional[int] = None,
        # Track the frame prior (last_frame_prior) without re-prioring the SPP.
        frame_prior_track: bool = False,
    ):
        self.alpha = alpha
        # Clip q to (eps, 1 - eps) so the prior ratio is finite.
        _eps = 1e-6
        self.q = float(np.clip(q, _eps, 1.0 - _eps))
        self.xi_min = 10 ** (xi_min_db / 10)

        # Optional cross-band speech prior; strength 0 bypasses it. It reuses the fixed-prior SPP,
        # so it adds no exp/log.
        if not 0.0 <= cross_band_prior_strength <= 1.0:
            raise ValueError("cross_band_prior_strength must be in [0, 1]")
        if not 0.0 < cross_band_prior_threshold < cross_band_prior_full_scale <= 1.0:
            raise ValueError(
                "cross-band prior thresholds must satisfy "
                "0 < threshold < full_scale <= 1"
            )
        if not 0.0 < cross_band_prior_max_q < 1.0:
            raise ValueError("cross_band_prior_max_q must be in (0, 1)")
        if (cross_band_prior_strength > 0.0
                and cross_band_prior_max_q < self.q):
            raise ValueError("enabled cross_band_prior_max_q must be >= q")
        if not 0.0 <= cross_band_prior_alpha < 1.0:
            raise ValueError("cross_band_prior_alpha must be in [0, 1)")
        self.cross_band_prior_strength = float(cross_band_prior_strength)
        self.cross_band_prior_threshold = float(cross_band_prior_threshold)
        self.cross_band_prior_full_scale = float(cross_band_prior_full_scale)
        self.cross_band_prior_max_q = float(cross_band_prior_max_q)
        self.cross_band_prior_alpha = float(cross_band_prior_alpha)
        self.cross_band_prior_bin_start = cross_band_prior_bin_start
        self.cross_band_prior_bin_end = cross_band_prior_bin_end
        self.cross_band_prior_state = 0.0
        self.last_effective_q = self.q
        self.last_fixed_prior_spp = None
        # Mean SPP over the evidence band (after the frame prior, before the cross-band lift);
        # None while the cross-band prior is off.
        self.last_evidence_mean = None

        if frame_prior_q_max is not None and not self.q < frame_prior_q_max < 1.0:
            raise ValueError("frame_prior_q_max must be None or in (q, 1)")
        if not 0.0 <= frame_prior_spp_lo < frame_prior_spp_hi <= 1.0:
            raise ValueError("frame prior ramp must satisfy 0 <= lo < hi <= 1")
        self.frame_prior_q_max = (float(frame_prior_q_max)
                                  if frame_prior_q_max is not None else None)
        self.frame_prior_spp_lo = float(frame_prior_spp_lo)
        self.frame_prior_spp_hi = float(frame_prior_spp_hi)
        self.frame_prior_bin_start = frame_prior_bin_start
        self.frame_prior_bin_end = frame_prior_bin_end
        self.frame_prior_track = bool(frame_prior_track)
        self.last_frame_prior = 0.0

        self.xi_prev = None
        self.gamma_prev = None
        self.noise_psd_prev = None
        self.frame_count = 0

    def estimate(
        self,
        Y_psd: np.ndarray,
        noise_psd: np.ndarray,
        gain_prev: Optional[np.ndarray] = None,
        enhanced_psd_prev: Optional[np.ndarray] = None,
        alpha_override: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Estimates SPP, a-priori SNR xi and posterior SNR gamma, each (n_freqs,).

        Y_psd, noise_psd: (n_freqs,). gain_prev and enhanced_psd_prev (previous-frame |X|^2) feed
        the decision-directed term; without gain_prev xi is a direct estimate. alpha_override:
        optional per-bin smoothing.
        """
        gamma = Y_psd / (noise_psd + 1e-10)

        if self.xi_prev is None or gain_prev is None:
            # First frame: direct estimate with the same floor as the DD path.
            xi = np.maximum(gamma - 1, self.xi_min)
        else:
            # Ephraim-Malah DD: xi = alpha * |X_prev|^2 / noise_prev + (1 - alpha) * max(gamma - 1, 0).
            # The denominator is the previous frame's noise PSD, matching how |X_prev|^2 was formed.
            assert enhanced_psd_prev is not None, \
                "enhanced_psd_prev must be provided for Decision Directed estimation"

            # Fall back to the current noise PSD if none is stored.
            noise_for_dd = self.noise_psd_prev if self.noise_psd_prev is not None else noise_psd

            alpha_effective = alpha_override if alpha_override is not None else self.alpha
            xi_dd_term1 = enhanced_psd_prev / (noise_for_dd + 1e-10)
            xi_dd = alpha_effective * xi_dd_term1 + \
                    (1 - alpha_effective) * np.maximum(gamma - 1, 0)
            xi = np.maximum(xi_dd, self.xi_min)

        log_likelihood = xi / (1 + xi) * gamma

        term_xi = 1 + xi
        # q is clipped in __init__, so prior_ratio = (1 - q) / q is finite.
        prior_ratio = (1 - self.q) / self.q

        exp_neg_likelihood = np.exp(-log_likelihood)
        spp = 1 / (1 + prior_ratio * term_xi * exp_neg_likelihood)
        # Keep the fixed-prior SPP for the noise tracker: feeding the lifted SPP back would freeze
        # the noise estimate (positive feedback).
        self.last_fixed_prior_spp = spp

        if self.frame_prior_q_max is not None or self.frame_prior_track:
            start, end = _band_slice(spp.shape[0], self.frame_prior_bin_start,
                                     self.frame_prior_bin_end)
            frame_prior = _ramp01(float(np.mean(spp[start:end])),
                                  self.frame_prior_spp_lo, self.frame_prior_spp_hi)
            self.last_frame_prior = frame_prior
            if self.frame_prior_q_max is not None:
                q_frame = self.q + (self.frame_prior_q_max - self.q) * frame_prior
                spp = 1 / (1 + (1 - q_frame) / q_frame * term_xi * exp_neg_likelihood)

        # Cross-band protection: when speech evidence is coherent across the band, lift the prior
        # of weak bins in the same frame; effective_q never falls below q.
        if self.cross_band_prior_strength > 0.0:
            start, end = _band_slice(spp.shape[0], self.cross_band_prior_bin_start,
                                     self.cross_band_prior_bin_end)
            evidence_mean = float(np.mean(spp[start:end]))
            self.last_evidence_mean = evidence_mean
            target = _ramp01(evidence_mean, self.cross_band_prior_threshold,
                             self.cross_band_prior_full_scale)
            a = self.cross_band_prior_alpha
            self.cross_band_prior_state = (
                a * self.cross_band_prior_state + (1.0 - a) * target
            )
            effective_q = self.q + (
                self.cross_band_prior_strength
                * self.cross_band_prior_state
                * (self.cross_band_prior_max_q - self.q)
            )
            effective_q = float(np.clip(effective_q, self.q,
                                        self.cross_band_prior_max_q))
            # First-order logit lift about q = 0.5 (matches exact re-prioring at SPP = 0.5).
            lift = 4.0 * (effective_q - self.q)
            spp = spp + lift * spp * (1.0 - spp)
            self.last_effective_q = effective_q
        else:
            self.last_effective_q = self.q
            self.last_evidence_mean = None

        self.xi_prev = xi
        self.gamma_prev = gamma
        self.noise_psd_prev = noise_psd.copy()  # DD needs the previous noise PSD
        self.frame_count += 1

        return spp, xi, gamma

    def reset(self):
        """Clears all state."""
        self.xi_prev = None
        self.gamma_prev = None
        self.noise_psd_prev = None
        self.frame_count = 0
        self.cross_band_prior_state = 0.0
        self.last_effective_q = self.q
        self.last_fixed_prior_spp = None
        self.last_evidence_mean = None
        self.last_frame_prior = 0.0

    def __repr__(self):
        return (f"SppEstimator(alpha={self.alpha}, q={self.q}, "
                f"xi_min={10 * np.log10(self.xi_min):.1f} dB)")


def compute_spp_batch(
    Y_psd: np.ndarray,
    noise_psd: np.ndarray,
    alpha: float = 0.98,
    q: float = 0.5,
    xi_min_db: float = -25.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Runs SppEstimator over Y_psd (n_frames, n_freqs).

    noise_psd is (n_frames, n_freqs) or (n_freqs,). Returns (spp, xi, gamma), each
    (n_frames, n_freqs).
    """
    estimator = SppEstimator(alpha=alpha, q=q, xi_min_db=xi_min_db)

    n_frames = Y_psd.shape[0]
    n_freqs = Y_psd.shape[1]

    spp = np.zeros_like(Y_psd)
    xi = np.zeros_like(Y_psd)
    gamma = np.zeros_like(Y_psd)

    gain_prev = None
    enhanced_psd_prev = None

    for i in range(n_frames):
        if noise_psd.ndim == 1:
            noise_frame = noise_psd
        else:
            noise_frame = noise_psd[i]

        spp[i], xi[i], gamma[i] = estimator.estimate(
            Y_psd[i],
            noise_frame,
            gain_prev,
            enhanced_psd_prev
        )

        # The Wiener gain xi / (1 + xi) feeds the next frame.
        gain_prev = xi[i] / (1 + xi[i])

        enhanced_psd_prev = (gain_prev ** 2) * Y_psd[i]

    return spp, xi, gamma
