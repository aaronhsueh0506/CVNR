"""`scene_change_confirm_frames` (the fricative guard): a fricative's own
energy is bounded in duration (50-150 ms), so the elevated hi_gamma +
flatness condition that triggers the scene-change reset breaks on its own
shortly after the ordinary trigger point. A genuine broadband scene change
(fan turning on, mic moved) keeps that condition elevated against the
still-stale noise estimate indefinitely -- until the reset itself updates
it. Requiring the condition to additionally hold for
`scene_change_confirm_frames` MORE consecutive frames before committing
therefore separates the two by shape, without a cooldown after the fact
and without a second, independent frequency band.

Measured on DNS2020 (no_reverb test set, 150 files): a real false-fire's
condition, probed past the ordinary 5-frame trigger point against a frozen
pre-fire noise floor, never ran longer than 15 extra frames at the 16 kHz/
256 grid (8 ms hop), 9 at 16 kHz/512 (16 ms hop). A synthetic genuine step
(with a high external SPP, like the real posterior would report for new
energy against a stale noise estimate -- see NOTE below) never breaks
inside a multi-second probe window.

NOTE on the burst stimuli below: every `update()` call here passes
`spp=SPP_HIGH`. Without an external posterior the estimator falls back to
its OWN internal min-stat indicator (self.spp), which starts near 0 and
lets the ORDINARY SPP-gated recursive update (outside this guard's scope)
absorb a sustained synthetic step within a handful of frames on its own --
an artifact of this minimal stimulus, not of production (where the OM-LSA
posterior is always supplied, and is exactly what being initially
inflated keeps slow -- the reason the reset exists at all). Forcing a high
posterior here isolates the fricative guard's own behavior from that
unrelated, sibling-owned mechanism.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.noise_estimators.mcra import McraNoiseEstimator  # noqa: E402

N_FREQS = 129  # 16 kHz / FFT 256
HI_START = 64
N_INIT = 8
MIN_FRAMES = 5
HI_LEVEL = 50.0       # well above threshold*noise so the gate is energy-decided
SPP_HIGH = np.ones(N_FREQS)
TRACKER = dict(alpha_s=0.9, alpha_d=0.85, alpha_p=0.2, L=32, delta_db=10.0,
               broadband_threshold=1.0, scene_change_threshold_db=10.0,
               scene_change_flatness_threshold=0.4, scene_change_min_frames=MIN_FRAMES)


def _make_estimator(confirm_frames):
    est = McraNoiseEstimator(num_init_frames=N_INIT,
                              scene_change_confirm_frames=confirm_frames, **TRACKER)
    est.estimate(np.ones((N_INIT, N_FREQS)))
    return est


def _burst_magnitude():
    power = np.ones(N_FREQS)
    power[HI_START:] = HI_LEVEL
    return np.sqrt(power)


def _quiet_magnitude():
    return np.ones(N_FREQS)


def test_default_is_off_and_bit_exact():
    """scene_change_confirm_frames=0 must reproduce the shipped trigger
    exactly: a burst held for MIN_FRAMES frames fires immediately."""
    est = _make_estimator(confirm_frames=0)
    mag = _burst_magnitude()
    for _ in range(MIN_FRAMES):
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is True, \
        "confirm_frames=0 must still fire at the ordinary threshold"


def test_default_off_matches_estimator_without_the_parameter():
    """Constructing with and without the new kwarg (0 is the default) must
    give identical trajectories -- the mutation test for "did this
    parameter actually default to a no-op"."""
    est_a = McraNoiseEstimator(num_init_frames=N_INIT, **TRACKER)
    est_a.estimate(np.ones((N_INIT, N_FREQS)))
    est_b = _make_estimator(confirm_frames=0)
    mag = _burst_magnitude()
    for _ in range(MIN_FRAMES + 3):
        a = est_a.update(mag, spp=SPP_HIGH)
        b = est_b.update(mag, spp=SPP_HIGH)
        np.testing.assert_array_equal(a, b)


def test_fricative_length_burst_does_not_fire():
    """A burst lasting MIN_FRAMES + 10 frames (bounded, fricative-shaped)
    must NOT commit the scene-change reset when confirm_frames=16 (the
    16 kHz/256 operating value; measured max observed extra streak on
    DNS2020 was 15 frames)."""
    est = _make_estimator(confirm_frames=16)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for _ in range(MIN_FRAMES + 10):  # total streak 15 frames, below the 21-frame bar
        est.update(mag, spp=SPP_HIGH)
    for _ in range(5):  # let the (bounded) burst end, like a real fricative
        est.update(quiet, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False, \
        "a bounded, fricative-length burst must not commit the reset"


def test_sustained_step_still_fires_within_confirm_window():
    """A step that persists past scene_change_min_frames + confirm_frames
    must still fire (the existence guard: a genuine scene change is not
    permanently blocked, only delayed)."""
    est = _make_estimator(confirm_frames=16)
    mag = _burst_magnitude()
    fired = False
    for _ in range(MIN_FRAMES + 16 + 2):
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired = True
            break
    assert fired, "a sustained step must still fire once the confirm window elapses"


def test_isolated_miss_does_not_restart_the_streak():
    """A single stray miss frame inside an otherwise-sustained step must not
    force a full restart (the near-threshold existence-guard robustness
    fix): the streak should resume where it left off, not from 0."""
    est = _make_estimator(confirm_frames=16)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for _ in range(MIN_FRAMES + 5):
        est.update(mag, spp=SPP_HIGH)
    count_before_miss = est.scene_change_count
    est.update(quiet, spp=SPP_HIGH)  # one isolated miss
    for _ in range(3):
        est.update(mag, spp=SPP_HIGH)
    assert est.scene_change_count >= count_before_miss, (
        "an isolated miss must not reset the streak to 0 when the "
        "fricative guard is engaged")


def test_two_separate_short_bursts_do_not_bridge_into_one_episode():
    """Two short fricative-length bursts separated by a real gap (longer
    than SCENE_CHANGE_MISS_TOLERANCE) must each be judged independently --
    the miss-tolerance added for existence-guard robustness must not let
    unrelated short events accumulate into a false confirm."""
    est = _make_estimator(confirm_frames=16)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for _ in range(MIN_FRAMES + 3):
        est.update(mag, spp=SPP_HIGH)
    for _ in range(est.SCENE_CHANGE_MISS_TOLERANCE + 2):
        est.update(quiet, spp=SPP_HIGH)
    assert est.scene_change_count == 0, "the gap must fully end the first episode"
    for _ in range(MIN_FRAMES + 3):
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False, (
        "two separate short bursts must not bridge into a committed reset")
