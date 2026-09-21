"""Speech protection: the shipped LF gain floor / frame gate and the
default-off cross-band speech prior."""

import numpy as np
import pytest

from core.gain_calculators import MmseLsaGainCalculator
from core.spp_estimator import SppEstimator
from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser


def _run(estimator, y_psd, noise_psd):
    gain_prev = np.ones_like(y_psd)
    enhanced_prev = y_psd.copy()
    outputs = []
    for _ in range(20):
        spp, _, _ = estimator.estimate(
            y_psd, noise_psd, gain_prev, enhanced_prev
        )
        outputs.append(spp.copy())
        enhanced_prev = y_psd.copy()
    return outputs[-1]


def test_disabled_cross_band_prior_is_exact_legacy_path():
    rng = np.random.default_rng(7)
    y_psd = rng.uniform(0.01, 8.0, 129)
    noise_psd = rng.uniform(0.1, 2.0, 129)
    legacy = SppEstimator(alpha=0.92, q=0.5, xi_min_db=-20.0)
    explicit_off = SppEstimator(
        alpha=0.92,
        q=0.5,
        xi_min_db=-20.0,
        cross_band_prior_strength=0.0,
    )
    assert np.array_equal(
        _run(legacy, y_psd, noise_psd),
        _run(explicit_off, y_psd, noise_psd),
    )


def test_cross_band_evidence_lifts_weak_bins_without_lowering_any_bin():
    # Most of the speech band has decisive evidence; bin 12 is deliberately
    # weak.  The cross-band prior must lift that weak bin while never reducing
    # the shipped fixed-prior SPP anywhere.
    y_psd = np.full(129, 8.0)
    noise_psd = np.ones(129)
    y_psd[12] = 1.05

    fixed = SppEstimator(alpha=0.92, q=0.5, xi_min_db=-20.0)
    adaptive = SppEstimator(
        alpha=0.92,
        q=0.5,
        xi_min_db=-20.0,
        cross_band_prior_strength=1.0,
        cross_band_prior_threshold=0.55,
        cross_band_prior_full_scale=0.75,
        cross_band_prior_max_q=0.62,
        cross_band_prior_alpha=0.0,
        cross_band_prior_bin_start=1,
        cross_band_prior_bin_end=65,
    )
    spp_fixed = _run(fixed, y_psd, noise_psd)
    spp_adaptive = _run(adaptive, y_psd, noise_psd)
    assert adaptive.last_effective_q > adaptive.q
    assert spp_adaptive[12] > spp_fixed[12]
    assert np.all(spp_adaptive >= spp_fixed)


def test_reset_clears_cross_band_history():
    est = SppEstimator(
        cross_band_prior_strength=1.0,
        cross_band_prior_max_q=0.65,
        cross_band_prior_alpha=0.9,
    )
    _run(est, np.full(33, 10.0), np.ones(33))
    assert est.cross_band_prior_state > 0.0
    est.reset()
    assert est.cross_band_prior_state == 0.0
    assert est.last_evidence_mean is None
    assert est.last_effective_q == est.q


def test_denoiser_keeps_cross_band_lift_out_of_mcra_feedback():
    denoiser = MmseLsaDenoiser(
        sample_rate=16000,
        frame_size=256,
        frame_shift=128,
        fft_size=256,
        noise_method="mcra",
        num_init_frames=2,
        L=4,
        cross_band_prior_strength=1.0,
        cross_band_prior_threshold=0.20,
        cross_band_prior_full_scale=0.40,
        cross_band_prior_max_q=0.62,
        cross_band_prior_alpha=0.0,
    )
    captured_spp = []
    update = denoiser.noise_estimator.update

    def capture_update(magnitude, spp=None, **kwargs):
        captured_spp.append(spp.copy())
        return update(magnitude, spp=spp, **kwargs)

    denoiser.noise_estimator.update = capture_update
    magnitudes = np.full((5, 129), 4.0)
    magnitudes[:, 12] = 1.05
    phases = np.zeros_like(magnitudes)
    _, _, gain_side_spp = denoiser.denoise_spectrum(
        magnitudes, phases, return_spp=True
    )

    assert captured_spp
    np.testing.assert_array_equal(
        captured_spp[-1], denoiser.spp_estimator.last_fixed_prior_spp
    )
    assert np.any(gain_side_spp[-1] > captured_spp[-1])


def test_speech_floor_only_protects_bins_above_the_spp_gate():
    common = dict(
        g_min_db=-30.0,
        alpha_g=0.0,
        use_asymmetric_smoothing=False,
    )
    base = MmseLsaGainCalculator(**common)
    protected = MmseLsaGainCalculator(
        **common,
        spp_protect_floor_db=-20.0,
        spp_protect_threshold=0.5,
    )
    # Put the raw OM-LSA gain below the -20 dB protection floor.  The third
    # bin has high SPP too, but is outside the speech-band mask.
    spp = np.array([0.4, 0.6, 0.6])
    xi = np.full(3, 1e-6)
    gamma = np.full(3, 0.1)
    protect_mask = np.array([True, True, False])
    base_gain = base.calculate(spp, xi, gamma)
    protected_gain = protected.calculate(
        spp, xi, gamma, spp_protect_mask=protect_mask
    )
    gated_off_gain = protected.calculate(
        spp, xi, gamma, spp_protect_enabled=False
    )

    assert protected_gain[0] == base_gain[0]
    assert protected_gain[1] >= 10 ** (-20.0 / 20.0)
    assert protected_gain[1] > base_gain[1]
    assert protected_gain[2] == base_gain[2]
    np.testing.assert_allclose(gated_off_gain, base_gain, rtol=0.0, atol=1e-15)


@pytest.mark.parametrize("floor,threshold", [(-31.0, 0.5), (1.0, 0.5), (-20.0, -0.1), (-20.0, 1.1)])
def test_speech_floor_rejects_invalid_controls(floor, threshold):
    with pytest.raises(ValueError):
        MmseLsaGainCalculator(
            g_min_db=-30.0,
            spp_protect_floor_db=floor,
            spp_protect_threshold=threshold,
        )
