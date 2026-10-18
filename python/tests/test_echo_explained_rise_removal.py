"""arm 4: post-hoc removal of the echo-explained fraction of a noise rise.

Context (see python/core/noise_estimators/mcra.py module docstring and
McraNoiseEstimator.update()'s `remove_echo_explained_rise` / `extra_noise_psd`):
the AEC+NR pipeline folds the AEC residual-echo PSD R²(f) into a LOCAL COPY of
the noise floor before computing SPP/gain (v3_2_mmse_lsa.denoise_spectrum).
That local copy is not supposed to pollute the tracker's own noise_psd, but
with `accept_external_spp=True` (production default) the SPP computed FROM
that polluted copy is fed straight back into update()'s own `spp` parameter,
so the tracker absorbs power faster during echo-active periods. arm 4 does
not touch that update rate -- it runs the unmodified recursion first, then
subtracts back out, per bin, the fraction of THIS frame's rise that the
supplied extra (R²) power can explain.

These tests check the mechanism in isolation, directly against the formula
(not against any acceptance bar/corpus -- see the campaign memory for that).
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

    # Unmodified run to get "previous" (pre-update) and "tracked" (post-update,
    # no correction) independently of arm 4's own bookkeeping.
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
    """The snapshot is taken before step 7 (scene-change reset) and the
    correction is applied after it, so a reset-driven jump in noise_psd is
    corrected by the same proportional rule as an ordinary rise -- arm 4
    wraps the WHOLE update() call, it does not special-case the reset path."""
    est = _make_estimator(
        remove_echo_explained_rise=True,
        scene_change_threshold_db=0.1,   # trivially easy to trigger
        scene_change_min_frames=1,
        scene_change_flatness_threshold=0.0,  # any flatness value passes
        scene_change_blend=0.5,
    )
    previous = est.noise_psd.copy()

    # A broadband, flat loud frame in the upper half triggers the scene-change
    # write at step 7 (hi_gamma large, flatness high for a flat spectrum).
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
    # The low bins (extra == 0) are untouched by arm 4.
    np.testing.assert_array_equal(tracked_arm4[:4], tracked_unmodified[:4])
