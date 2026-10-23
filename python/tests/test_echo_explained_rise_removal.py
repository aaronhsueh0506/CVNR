"""Post-hoc removal of the echo-explained fraction of a noise rise
(McraNoiseEstimator `remove_echo_explained_rise` / `extra_noise_psd`).

The AEC+NR pipeline folds the residual-echo PSD into a local copy of the noise floor before
computing SPP/gain. With `accept_external_spp=True` the SPP computed from that copy is fed back
into update(), so the tracker absorbs power faster during echo. The correction leaves that rate
alone: it runs the unmodified recursion, then subtracts, per bin, the part of this frame's rise
that the supplied extra power explains.

The tests check the mechanism directly against the formula.
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.noise_estimators.mcra import McraNoiseEstimator  # noqa: E402


def _make_estimator(**kwargs):
    est = McraNoiseEstimator(num_init_frames=4, **kwargs)
    init = np.full((4, 8), 1.0, dtype=np.float64)
    est.estimate(init)
    return est


def test_default_off_ignores_extra_noise_psd():
    """Flag off: passing extra_noise_psd must not change the result at all
    (belt-and-suspenders -- a caller that forgets to gate the kwarg is safe)."""
    magnitude = np.array([5.0] * 8)
    extra = np.array([100.0] * 8)

    est_a = _make_estimator(remove_echo_explained_rise=False)
    out_a = est_a.update(magnitude, spp=np.full(8, 0.9), extra_noise_psd=extra)

    est_b = _make_estimator(remove_echo_explained_rise=False)
    out_b = est_b.update(magnitude, spp=np.full(8, 0.9))

    np.testing.assert_array_equal(out_a, out_b)


def test_on_but_no_extra_matches_unmodified_update():
    """Flag on, extra_noise_psd=None: must be identical to the unmodified
    recursion (no snapshot branch should fire)."""
    magnitude = np.array([5.0] * 8)

    est_a = _make_estimator(remove_echo_explained_rise=True)
    out_a = est_a.update(magnitude, spp=np.full(8, 0.9))

    est_b = _make_estimator(remove_echo_explained_rise=False)
    out_b = est_b.update(magnitude, spp=np.full(8, 0.9))

    np.testing.assert_array_equal(out_a, out_b)


def test_zero_extra_is_a_no_op():
    """extra_noise_psd all zero must leave the update unmodified (rising
    condition requires extra > 0)."""
    magnitude = np.array([5.0] * 8)
    zero_extra = np.zeros(8)

    est_a = _make_estimator(remove_echo_explained_rise=True)
    out_a = est_a.update(magnitude, spp=np.full(8, 0.9), extra_noise_psd=zero_extra)

    est_b = _make_estimator(remove_echo_explained_rise=False)
    out_b = est_b.update(magnitude, spp=np.full(8, 0.9))

    np.testing.assert_array_equal(out_a, out_b)


def test_falling_bin_is_untouched():
    """A bin whose frame power is BELOW the pre-update estimate (a falling
    bin) must not be corrected even if extra_noise_psd > 0 there."""
    est = _make_estimator(remove_echo_explained_rise=True)
    previous = est.noise_psd.copy()
    assert np.all(previous == 1.0)

    magnitude = np.array([0.1] * 8)  # power = 0.01, far below previous
    extra = np.array([5.0] * 8)
    out_unmodified = _make_estimator(remove_echo_explained_rise=False).update(
        magnitude, spp=np.full(8, 0.9))
    out_arm4 = est.update(magnitude, spp=np.full(8, 0.9), extra_noise_psd=extra)

    np.testing.assert_array_equal(out_arm4, out_unmodified)


def test_rising_bin_matches_hand_computed_correction():
    """A bin that rises this frame gets exactly:
        excess = power - previous
        fraction = min(extra / excess, 1.0)
        tracked = previous + (tracked - previous) * (1 - fraction)
    Verified against an unmodified run of the SAME inputs (no extra), which
    gives `tracked` and `previous` independently of the correction path.
    """
    spp = np.full(8, 0.3)
    magnitude = np.array([50.0] * 8)  # power = 2500, far above previous=1.0
    extra = np.array([200.0] * 8)     # explains part of the 2499 excess

    # Unmodified run gives "previous" (pre-update) and "tracked" (post-update, no correction)
    # independently of the correction path.
    plain = _make_estimator(remove_echo_explained_rise=False)
    previous = plain.noise_psd.copy()
    tracked_unmodified = plain.update(magnitude, spp=spp)

    arm4 = _make_estimator(remove_echo_explained_rise=True)
    assert np.all(arm4.noise_psd == previous)
    tracked_arm4 = arm4.update(magnitude, spp=spp, extra_noise_psd=extra)

    power = magnitude ** 2
    excess = power - previous
    fraction = np.minimum(extra / excess, 1.0)
    expected = previous + (tracked_unmodified - previous) * (1.0 - fraction)

    np.testing.assert_allclose(tracked_arm4, expected, rtol=1e-12)
    # Sanity: the correction actually did something (rose less than unmodified).
    assert np.all(tracked_arm4 < tracked_unmodified)
    assert np.all(tracked_arm4 >= previous)


def test_large_extra_clamps_fraction_to_one():
    """extra_noise_psd >= excess must fully revert the bin to `previous`
    (fraction clamped to 1.0), not overshoot past it."""
    spp = np.full(8, 0.3)
    magnitude = np.array([50.0] * 8)
    extra = np.array([1.0e9] * 8)  # vastly exceeds any possible excess

    est = _make_estimator(remove_echo_explained_rise=True)
    previous = est.noise_psd.copy()
    tracked = est.update(magnitude, spp=spp, extra_noise_psd=extra)

    np.testing.assert_allclose(tracked, previous, rtol=1e-12)


def test_scene_change_write_is_also_corrected():
    """The snapshot is taken before the scene-change reset and the correction is applied after
    it, so a reset-driven jump in noise_psd is corrected by the same proportional rule as an
    ordinary rise."""
    est = _make_estimator(
        remove_echo_explained_rise=True,
        scene_change_threshold_db=0.1,   # trivially easy to trigger
        scene_change_min_frames=1,
        scene_change_flatness_threshold=0.0,  # any flatness value passes
        scene_change_blend=0.5,
    )
    previous = est.noise_psd.copy()

    # A broadband, flat loud frame in the upper half triggers the scene-change write
    # (hi_gamma large, flatness high for a flat spectrum).
    magnitude = np.array([1.0, 1.0, 1.0, 1.0, 50.0, 50.0, 50.0, 50.0])
    extra = np.array([0.0, 0.0, 0.0, 0.0, 300.0, 300.0, 300.0, 300.0])

    plain = _make_estimator(
        remove_echo_explained_rise=False,
        scene_change_threshold_db=0.1,
        scene_change_min_frames=1,
        scene_change_flatness_threshold=0.0,
        scene_change_blend=0.5,
    )
    tracked_unmodified = plain.update(magnitude.copy(), spp=np.full(8, 0.3))
    assert plain.scene_change_count == 0  # fired and reset the counter
    # Confirm the scene-change path actually fired (high bins moved toward
    # `power`, not just the ordinary recursive update).
    assert tracked_unmodified[4] > previous[4] + 1.0

    tracked_arm4 = est.update(magnitude.copy(), spp=np.full(8, 0.3),
                               extra_noise_psd=extra)

    power = magnitude ** 2
    excess = power - previous
    rising = (extra > 0.0) & (tracked_unmodified > previous) & (excess > 0.0)
    fraction = np.where(rising, np.minimum(extra / np.where(excess > 0, excess, 1.0), 1.0), 0.0)
    expected = previous + (tracked_unmodified - previous) * (1.0 - fraction)
    np.testing.assert_allclose(tracked_arm4, expected, rtol=1e-10)
    # The high bins (extra > 0) should be pulled back below the uncorrected
    # scene-change write.
    assert np.all(tracked_arm4[4:] < tracked_unmodified[4:])
    # The low bins (extra == 0) are untouched.
    np.testing.assert_array_equal(tracked_arm4[:4], tracked_unmodified[:4])


# ---------------------------------------------------------------------------
# Scene-change trigger with the correction active: hi_gamma (energy test only, not flatness) uses
# echo-corrected power, and a fire seeds S_min/min_buffer with the same corrected value as the
# noise_psd write, not the raw (echo-polluted) S.
# ---------------------------------------------------------------------------

N_FREQS_HAZARD = 16
HI_START_HAZARD = 8


def _make_hazard_estimator(remove_echo_explained_rise, **kwargs):
    defaults = dict(
        alpha_s=0.9, alpha_d=0.85, alpha_p=0.2, L=32, delta_db=10.0,
        broadband_threshold=1.0, scene_change_threshold_db=10.0,
        scene_change_flatness_threshold=0.4, scene_change_min_frames=5,
        accept_external_spp=True,
        remove_echo_explained_rise=remove_echo_explained_rise,
    )
    defaults.update(kwargs)
    est = McraNoiseEstimator(num_init_frames=8, **defaults)
    est.estimate(np.ones((8, N_FREQS_HAZARD)))
    return est


def _drive_echo_dominated_rise(est, extra_noise_psd, n_frames=200, echo_level=50.0,
                                echo_frac=0.95, seed=0):
    """Feed a sustained hi-band rise that is `echo_frac` explained by extra_noise_psd (when
    supplied). Returns the number of scene-change fires observed (scene_change_count dropping to
    0 after it was > 0, i.e. a committed reset)."""
    rng = np.random.RandomState(seed)
    fires = 0
    for _ in range(n_frames):
        power = 1.0 + 0.05 * rng.randn(N_FREQS_HAZARD)
        power[HI_START_HAZARD:] = echo_level + 0.5 * rng.randn(
            N_FREQS_HAZARD - HI_START_HAZARD)
        mag = np.sqrt(np.clip(power, 1e-6, None))
        extra = (np.zeros(N_FREQS_HAZARD) if not extra_noise_psd else
                 np.concatenate([np.zeros(HI_START_HAZARD),
                                 np.full(N_FREQS_HAZARD - HI_START_HAZARD,
                                         echo_frac * echo_level)]))
        cnt_before = est.scene_change_count
        est.update(mag, spp=np.full(N_FREQS_HAZARD, 0.3),
                   extra_noise_psd=extra if extra_noise_psd else None)
        if cnt_before > 0 and est.scene_change_count == 0:
            fires += 1
    return fires


def test_echo_dominated_rise_no_longer_refires_repeatedly():
    """When extra_noise_psd explains 95% of a sustained hi-band rise, the trigger must not refire
    every scene_change_min_frames for the whole episode. The non-echo control (same stimulus,
    remove_echo_explained_rise off) legitimately fires once as the noise floor converges."""
    est_off = _make_hazard_estimator(remove_echo_explained_rise=False)
    fires_off = _drive_echo_dominated_rise(est_off, extra_noise_psd=False)
    assert fires_off <= 2, (
        "sanity check: a genuine (non-echo) sustained rise should converge "
        "and stop firing within a couple of resets, not this one")

    est_on = _make_hazard_estimator(remove_echo_explained_rise=True)
    fires_on = _drive_echo_dominated_rise(est_on, extra_noise_psd=True)
    assert fires_on <= 2, (
        f"echo-explained-rise correction must not cause repeated re-firing "
        f"(hazard symptom); got {fires_on} fires over 200 frames of a "
        f"95%-echo-explained rise")


def test_hi_gamma_uses_corrected_power_directly():
    """One frame whose raw hi-band power clears scene_change_threshold but whose echo-corrected
    power does not: the trigger must not fire with remove_echo_explained_rise active, while the
    identical raw stimulus fires with the flag off."""
    threshold_db = 10.0
    est_off = _make_hazard_estimator(remove_echo_explained_rise=False,
                                      scene_change_threshold_db=threshold_db,
                                      scene_change_min_frames=1)
    est_on = _make_hazard_estimator(remove_echo_explained_rise=True,
                                     scene_change_threshold_db=threshold_db,
                                     scene_change_min_frames=1)

    hi_n = N_FREQS_HAZARD - HI_START_HAZARD
    noise_floor = 1.0  # est.noise_psd init level
    # Raw hi power is comfortably over 10x noise_floor (clears threshold);
    # extra explains all but a sliver of it, so corrected power is just
    # under 10x noise_floor (must NOT clear).
    raw_hi = 15.0 * noise_floor
    extra_hi = raw_hi - 9.5 * noise_floor
    magnitude = np.ones(N_FREQS_HAZARD)
    magnitude[HI_START_HAZARD:] = np.sqrt(raw_hi)
    extra = np.zeros(N_FREQS_HAZARD)
    extra[HI_START_HAZARD:] = extra_hi
    spp = np.full(N_FREQS_HAZARD, 0.3)

    # A fire seeds S_min/min_buffer with the just-smoothed S (hi band well above noise_floor);
    # without a fire S_min stays at its init level, so S_min's hi band staying at noise_floor
    # probes "did not fire" directly.
    est_off.update(magnitude.copy(), spp=spp)
    assert not np.allclose(est_off.S_min[HI_START_HAZARD:], noise_floor), (
        "control: the raw stimulus alone must clear the ordinary trigger")

    est_on.update(magnitude.copy(), spp=spp, extra_noise_psd=extra)
    assert np.allclose(est_on.S_min[HI_START_HAZARD:], noise_floor), (
        "echo-corrected hi_gamma must NOT clear the trigger when the "
        "corrected power sits just under scene_change_threshold")


def test_s_min_and_min_buffer_corrected_on_arm4_fire():
    """When a fire happens with remove_echo_explained_rise active (the rise is only partly
    echo-explained), S_min/min_buffer are seeded with the same echo-corrected value as the
    noise_psd write, not the raw S. scene_change_min_frames=1 makes the trigger deterministic so
    S_min is checked right after the fire."""
    est = _make_hazard_estimator(remove_echo_explained_rise=True,
                                  scene_change_threshold_db=0.1,
                                  scene_change_min_frames=1,
                                  scene_change_flatness_threshold=0.0,
                                  scene_change_blend=0.5)
    magnitude = np.ones(N_FREQS_HAZARD)
    magnitude[HI_START_HAZARD:] = 10.0  # power = 100 in the hi band
    extra = np.zeros(N_FREQS_HAZARD)
    extra[HI_START_HAZARD:] = 40.0      # explains 40 of the frame's rise
    spp = np.full(N_FREQS_HAZARD, 0.3)

    pre_S = est.S.copy()
    est.update(magnitude.copy(), spp=spp, extra_noise_psd=extra)

    power = magnitude ** 2
    expected_S_for_reset = np.maximum(
        (0.9 * pre_S + 0.1 * power) - extra, 0.0)  # alpha_s default 0.9
    np.testing.assert_allclose(est.S_min, expected_S_for_reset, rtol=1e-10)
    for row in range(est.min_buffer.shape[0]):
        np.testing.assert_allclose(est.min_buffer[row], expected_S_for_reset,
                                    rtol=1e-10)
    # The low (non-echo) bins are untouched by the correction (extra == 0 there).
    np.testing.assert_allclose(est.S_min[:HI_START_HAZARD],
                                (0.9 * pre_S + 0.1 * power)[:HI_START_HAZARD],
                                rtol=1e-10)


def test_arm4_fire_correction_bit_exact_when_disabled():
    """With remove_echo_explained_rise=False the fire seeds S_min/min_buffer from the raw S and
    extra_noise_psd is ignored: the results are identical with and without it."""
    kwargs = dict(scene_change_threshold_db=0.1, scene_change_min_frames=1,
                  scene_change_flatness_threshold=0.0, scene_change_blend=0.5)
    est_a = _make_hazard_estimator(remove_echo_explained_rise=False, **kwargs)
    est_b = _make_hazard_estimator(remove_echo_explained_rise=False, **kwargs)
    magnitude = np.ones(N_FREQS_HAZARD)
    magnitude[HI_START_HAZARD:] = 10.0
    spp = np.full(N_FREQS_HAZARD, 0.3)

    out_a = est_a.update(magnitude.copy(), spp=spp)
    out_b = est_b.update(magnitude.copy(), spp=spp,
                         extra_noise_psd=np.full(N_FREQS_HAZARD, 999.0))
    np.testing.assert_array_equal(out_a, out_b)
    np.testing.assert_array_equal(est_a.S_min, est_b.S_min)
    np.testing.assert_array_equal(est_a.min_buffer, est_b.min_buffer)
