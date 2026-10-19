"""`scene_change_confirm_window`: scene_change_confirm_
frames requires an unbroken run of hit frames (up to SCENE_CHANGE_MISS_
TOLERANCE consecutive misses) before confirming a reset. That is only safe
at a confirmation-window-vs-modulation-period boundary that happens to sit
just outside the ONE AM rate (3 Hz) it was validated against at 16 kHz/256;
realistic wind/babble/syllabic modulation (3-8 Hz) can dip the trigger
condition below threshold for LONGER than any practical miss-tolerance
covers, structurally (not a tuning problem -- see
test_scene_change_confirm_frames.py and the confirm_frames docstring).

scene_change_confirm_window replaces the run-length test for the FIRST fire
of an episode with a trailing-window true-frame FRACTION: over the last
(scene_change_min_frames + scene_change_confirm_window) frames, at least
scene_change_confirm_frac of them must be hits. A periodic dip at ANY rate
only lowers the window's hit fraction by its duty cycle; it never resets a
run counter to 0, so confirmation is tolerant of dip RATE, not just dip
length relative to one miss-tolerance constant.

These tests check the mechanism directly (toy stimuli, not a corpus-level
acceptance-bar run -- see the campaign memory for that).
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.noise_estimators.mcra import McraNoiseEstimator  # noqa: E402

N_FREQS = 129  # 16 kHz / FFT 256
HI_START = 64
N_INIT = 8
MIN_FRAMES = 5
HI_LEVEL = 50.0
SPP_HIGH = np.ones(N_FREQS)
TRACKER = dict(alpha_s=0.9, alpha_d=0.85, alpha_p=0.2, L=32, delta_db=10.0,
               broadband_threshold=1.0, scene_change_threshold_db=10.0,
               scene_change_flatness_threshold=0.4, scene_change_min_frames=MIN_FRAMES)


def _make_estimator(confirm_window, confirm_frac=0.6, **extra):
    est = McraNoiseEstimator(num_init_frames=N_INIT,
                              scene_change_confirm_window=confirm_window,
                              scene_change_confirm_frac=confirm_frac,
                              **TRACKER, **extra)
    est.estimate(np.ones((N_INIT, N_FREQS)))
    return est


def _burst_magnitude():
    power = np.ones(N_FREQS)
    power[HI_START:] = HI_LEVEL
    return np.sqrt(power)


def _quiet_magnitude():
    return np.ones(N_FREQS)


# Baseline AT the trigger's energy threshold (not HI_LEVEL's comfortable
# margin above it): with a deep modulation depth this gives a near-50%
# duty cycle of hit/miss frames, the adversarial case that actually
# exercises dip-tolerance (a shallow +-3 dB modulation on a level well
# above threshold, measured separately, never dips below it at all --
# duty cycle 1.0 -- and is not a meaningful stress stimulus for either
# confirmation mechanism).
AM_BASE_LEVEL = 10.0   # == scene_change_threshold (linear) x noise_psd(=1)
AM_DEPTH_DB = 30.0


def _am_magnitude(depth_db=AM_DEPTH_DB, rate_hz=6.0, hop_s=0.008, t_frame=0):
    """A hi-band burst whose level is sinusoidally modulated at rate_hz,
    +-depth_db around AM_BASE_LEVEL -- crosses the energy threshold on
    every half-cycle at the depth above, giving a ~50% duty cycle."""
    phase = 2 * np.pi * rate_hz * (t_frame * hop_s)
    level_db = 10 * np.log10(AM_BASE_LEVEL) + depth_db * np.sin(phase)
    level = 10 ** (level_db / 10)
    power = np.ones(N_FREQS)
    power[HI_START:] = level
    return np.sqrt(power)


def test_default_off_is_bit_exact_to_no_kwarg():
    """confirm_window=0 (the default) must reproduce a plain estimator
    (constructed without the new kwargs at all) exactly -- the mutation
    test for 'did this parameter actually default to a no-op'."""
    est_a = McraNoiseEstimator(num_init_frames=N_INIT, **TRACKER)
    est_a.estimate(np.ones((N_INIT, N_FREQS)))
    est_b = _make_estimator(confirm_window=0)
    mag = _burst_magnitude()
    for _ in range(MIN_FRAMES + 20):
        a = est_a.update(mag, spp=SPP_HIGH)
        b = est_b.update(mag, spp=SPP_HIGH)
        np.testing.assert_array_equal(a, b)
    assert est_a._scene_change_confirmed == est_b._scene_change_confirmed


def test_default_off_matches_confirm_frames_mode_too():
    """confirm_window=0 must also be bit-exact to the (already-shipped)
    scene_change_confirm_frames=0 path -- window mode being off must not
    silently change which legacy codepath runs."""
    est_a = McraNoiseEstimator(num_init_frames=N_INIT,
                               scene_change_confirm_frames=0, **TRACKER)
    est_a.estimate(np.ones((N_INIT, N_FREQS)))
    est_b = _make_estimator(confirm_window=0)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for i in range(MIN_FRAMES + 20):
        m = mag if i % 7 != 3 else quiet  # exercise the miss path too
        a = est_a.update(m, spp=SPP_HIGH)
        b = est_b.update(m, spp=SPP_HIGH)
        np.testing.assert_array_equal(a, b)


def test_mutually_exclusive_with_confirm_frames():
    with pytest.raises(ValueError):
        McraNoiseEstimator(scene_change_confirm_window=10,
                           scene_change_confirm_frames=5, **TRACKER)


def test_invalid_frac_rejected():
    with pytest.raises(ValueError):
        McraNoiseEstimator(scene_change_confirm_window=10,
                           scene_change_confirm_frac=0.0, **TRACKER)
    with pytest.raises(ValueError):
        McraNoiseEstimator(scene_change_confirm_window=10,
                           scene_change_confirm_frac=1.5, **TRACKER)


def test_negative_window_rejected():
    with pytest.raises(ValueError):
        McraNoiseEstimator(scene_change_confirm_window=-1, **TRACKER)


def test_bounded_fricative_does_not_fire():
    """A burst strictly shorter than the window's required_hits must NOT
    commit the reset under window mode: even at a 100%-duty burst, the
    hit count can never reach required_hits before the burst itself ends.

    Bug found during /code-review: the original version of this test used
    a MIN_FRAMES+10 = 15-frame burst against confirm_window=16/frac=0.6,
    i.e. window_size=21/required_hits=ceil(0.6*21)=13 -- 15 > 13, so the
    burst DID commit a real reset partway through (confirmed noise_psd
    change at frame 12), and the test's single assertion, checked only
    after 10 TRAILING QUIET frames, passed anyway because an isolated
    later miss had already reset _scene_change_confirmed back to False.
    The test's name and docstring claimed coverage it did not have. Fixed
    by choosing a burst length strictly below required_hits (so a fire is
    structurally impossible, not just absent in this one run) and by
    asserting _scene_change_confirmed is never True at ANY point during
    the burst, not just at the end."""
    est = _make_estimator(confirm_window=16, confirm_frac=0.6)
    window_size = MIN_FRAMES + 16
    required_hits = int(np.ceil(0.6 * window_size))
    burst_len = required_hits - 1  # 100%-duty burst still can't reach the fraction
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for _ in range(burst_len):
        est.update(mag, spp=SPP_HIGH)
        assert est._scene_change_confirmed is False, (
            "a burst shorter than required_hits must never fire, "
            "not even transiently")
    for _ in range(10):
        est.update(quiet, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False, (
        "a bounded, fricative-length burst must not commit the reset "
        "under windowed-fraction confirmation")


def test_sustained_step_still_fires_within_window():
    """A step that persists must still fire (existence guard): the window
    is only (min_frames+window) frames, so a continuous run clears the
    fraction threshold quickly."""
    est = _make_estimator(confirm_window=16, confirm_frac=0.6)
    mag = _burst_magnitude()
    fired = False
    for _ in range(MIN_FRAMES + 16 + 2):
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired = True
            break
    assert fired, "a sustained step must still fire once the window fills"


def test_two_separate_short_bursts_do_not_bridge():
    """Two short fricative-length bursts separated by a real gap must each
    be judged independently: by the time the second starts, the window
    (sized min_frames+confirm_window) has long forgotten the first."""
    est = _make_estimator(confirm_window=16, confirm_frac=0.6)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    for _ in range(MIN_FRAMES + 3):
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False
    for _ in range(30):  # long gap -- window fully flushed to all-miss
        est.update(quiet, spp=SPP_HIGH)
    assert est._window_hit_count == 0
    for _ in range(MIN_FRAMES + 3):
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False, (
        "two separate short bursts must not bridge into a committed reset")


def test_fire_then_isolated_miss_then_hit_does_not_immediately_refire():
    """Bug found during validation: on a committed fire, the window ring
    buffer still held the OLD evidence that earned it. A single ordinary
    miss right after the fire (e.g. the reset's own partial blend dropping
    hi_gamma for one frame) clears _scene_change_confirmed, but if the
    window buffer were untouched, the very next hit frame would see the
    window already satisfied from stale evidence and re-fire immediately
    -- a second confirmed fire backed by zero NEW sustained evidence. A
    fire must clear the window (_window_buf/_window_hit_count), so a
    post-fire re-confirmation requires fresh evidence like any other
    episode."""
    est = _make_estimator(confirm_window=12, confirm_frac=0.6)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    fired_once = False
    for _ in range(40):
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired_once = True
            break
    assert fired_once, "setup: must fire once before the regression check"
    assert est._window_hit_count == 0, (
        "a fire must clear the window's accumulated evidence")

    est.update(quiet, spp=SPP_HIGH)  # one isolated miss
    assert est._scene_change_confirmed is False  # miss clears confirmed

    # Bug found during /code-review's post-merge sweep: the original test
    # re-fed the SAME fixed-level `mag` burst here expecting it to register
    # as a hit, but the fire itself already blended noise_psd[hi:] toward
    # HI_LEVEL (scene_change_blend=0.5 default: ~0.5*old + 0.5*50 = ~25.5),
    # so hi_gamma for that same stimulus drops to ~50/25.5=~1.96, under
    # scene_change_threshold (10) -- that frame was a MISS, not a hit, for
    # reasons unrelated to the window-clear fix being tested, so `not
    # refired` passed trivially (there was no hit at all to re-fire from).
    # Construct a probe that is guaranteed to register as a hit regardless
    # of where the fire already moved noise_psd: scale the same flat hi-band
    # profile (scaling does not change spectral flatness, only level) well
    # above the CURRENT floor x threshold.
    probe_level = 20.0 * est.scene_change_threshold * np.mean(est.noise_psd[HI_START:])
    probe_power = np.ones(N_FREQS)
    probe_power[HI_START:] = probe_level
    probe_hit = np.sqrt(probe_power)
    hi_gamma_probe = (np.mean(probe_power[HI_START:])
                       / (np.mean(est.noise_psd[HI_START:]) + 1e-10))
    assert hi_gamma_probe > est.scene_change_threshold, (
        "test construction error: the probe itself must clear the energy "
        "threshold, or this test proves nothing")

    refired = False
    est.update(probe_hit, spp=SPP_HIGH)  # one GENUINE hit, freshly verified
    if est._scene_change_confirmed:
        refired = True
    assert not refired, (
        "one post-fire hit must NOT immediately re-fire from stale window "
        "evidence -- confirmation must require fresh accumulated hits")


@pytest.mark.parametrize("rate_hz", [3.0, 4.0, 5.0, 6.0, 8.0])
def test_run_length_mode_fails_above_3hz_on_a_50pct_duty_am_step(rate_hz):
    """Reproduces the structural failure measured in this round: on an
    adversarial (baseline-at-threshold, deep-modulation) ~50%-duty AM
    step, the shipped run-length mechanism (scene_change_confirm_frames,
    operating value 12 at 16 kHz/256) confirms at 3 Hz but never confirms
    at 4 Hz or above within a generous budget -- this is the problem the
    windowed-fraction mode below is built to fix, kept here as the
    control half of that comparison."""
    confirm_frames = 12
    est = McraNoiseEstimator(num_init_frames=N_INIT,
                             scene_change_confirm_frames=confirm_frames, **TRACKER)
    est.estimate(np.ones((N_INIT, N_FREQS)))
    budget_frames = 300
    fired_at = None
    for t in range(budget_frames):
        mag = _am_magnitude(rate_hz=rate_hz, t_frame=t)
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired_at = t
            break
    if rate_hz <= 3.0:
        assert fired_at is not None, (
            "sanity: the run-length mechanism is expected to still "
            "confirm at its validated 3 Hz rate")
    else:
        assert fired_at is None, (
            f"expected run-length mode to FAIL to confirm a {rate_hz} Hz "
            f"50%-duty AM step within {budget_frames} frames (this is the "
            f"documented failure, not a new regression); it confirmed at "
            f"frame {fired_at}")


@pytest.mark.parametrize("rate_hz", [3.0, 4.0, 5.0, 6.0, 8.0])
def test_window_mode_is_rate_independent_at_a_duty_matched_frac(rate_hz):
    """Windowed-fraction confirmation's actual advantage over run-length
    mode is RATE independence at a GIVEN duty cycle, not duty-cycle
    independence: confirmation only needs the window's achievable hit
    fraction (~= the stimulus's duty cycle in steady state) to clear
    confirm_frac, regardless of how fast the signal cycles through that
    duty cycle -- unlike run-length mode, which additionally depends on
    the ABSOLUTE dip duration against a fixed miss-tolerance. At
    confirm_frac=0.5 (<= this stimulus's ~50% duty cycle), window mode
    confirms at every rate up to 8 Hz."""
    confirm_window = 16
    confirm_frac = 0.5
    est = _make_estimator(confirm_window=confirm_window, confirm_frac=confirm_frac)
    budget_frames = 300
    fired_at = None
    for t in range(budget_frames):
        mag = _am_magnitude(rate_hz=rate_hz, t_frame=t)
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired_at = t
            break
    assert fired_at is not None, (
        f"a SUSTAINED {rate_hz} Hz 50%-duty AM step must still confirm "
        f"within the window-mode budget ({budget_frames} frames) at a "
        f"duty-matched confirm_frac")


def test_miss_frame_in_window_mode_is_now_tolerated():
    """Bug found by independent review (fixed): the miss-tolerance gate
    checked ONLY `scene_change_confirm_frames > 0`, which construction
    forces to 0 whenever window mode (`scene_change_confirm_window > 0`) is
    active (the two are mutually exclusive) -- so window mode got a HARD
    reset on every single miss frame, with zero miss tolerance, contrary to
    this module's own documented "tolerate transient dips" design. The gate
    must also accept `scene_change_confirm_window > 0`."""
    est = _make_estimator(confirm_window=12, confirm_frac=0.6)
    mag = _burst_magnitude()
    quiet = _quiet_magnitude()
    fired_once = False
    for _ in range(40):
        est.update(mag, spp=SPP_HIGH)
        if est._scene_change_confirmed:
            fired_once = True
            break
    assert fired_once, "setup: must fire once before the tolerance check"

    # A genuine post-fire hit (scaled so the already-blended noise_psd
    # doesn't turn it into a miss -- same construction as the sibling
    # refire test above) advances scene_change_count to 1 without
    # reaching scene_change_min_frames, so `ready` stays False and
    # `_scene_change_confirmed` stays True from the earlier fire.
    probe_level = 20.0 * est.scene_change_threshold * np.mean(est.noise_psd[HI_START:])
    probe_power = np.ones(N_FREQS)
    probe_power[HI_START:] = probe_level
    probe_hit = np.sqrt(probe_power)
    est.update(probe_hit, spp=SPP_HIGH)
    assert est._scene_change_confirmed is True
    assert est.scene_change_count == 1

    # One miss: pre-fix this hard-reset immediately (confirm_frames==0 in
    # window mode). Post-fix it must be tolerated like legacy mode.
    est.update(quiet, spp=SPP_HIGH)
    assert est._scene_change_confirmed is True, (
        "a single isolated miss must be tolerated in window mode, not "
        "hard-reset -- this is the bug being fixed")
    assert est.scene_change_count == 1
    assert est._scene_change_miss_run == 1

    # Two more tolerated misses (SCENE_CHANGE_MISS_TOLERANCE == 3 total).
    est.update(quiet, spp=SPP_HIGH)
    est.update(quiet, spp=SPP_HIGH)
    assert est._scene_change_confirmed is True
    assert est._scene_change_miss_run == 3

    # The 4th consecutive miss exceeds the tolerance -> hard reset, exactly
    # as legacy mode already behaves at the same constant.
    est.update(quiet, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False
    assert est.scene_change_count == 0
    assert est._scene_change_miss_run == 0


def test_unsatisfiable_window_rejected_at_construction():
    """Bug found by independent review (fixed): nothing validated that
    `_window_required_hits` (= ceil(confirm_frac * (scene_change_min_frames
    + scene_change_confirm_window))) actually exceeds scene_change_
    min_frames. A small frac with a large confirm_window can make window
    mode satisfiable on FEWER hits than the unguarded baseline trigger
    itself requires, silently defeating the "gather sustained evidence
    beyond the ordinary trigger" design intent. Construction must now
    reject any confirm_window/frac combination where required_hits <=
    scene_change_min_frames."""
    # window_size = 5 + 20 = 25; ceil(0.1*25) = 3 <= min_frames(5) -> reject.
    with pytest.raises(ValueError):
        _make_estimator(confirm_window=20, confirm_frac=0.1)
    # Exact boundary: ceil(0.2*25) = 5 == min_frames(5) -> still must reject
    # (achievable with EXACTLY as much evidence as the baseline trigger,
    # not more).
    with pytest.raises(ValueError):
        _make_estimator(confirm_window=20, confirm_frac=0.2)
    # One hit above the boundary: ceil(0.24*25) = 6 > min_frames(5) -> fine.
    est = _make_estimator(confirm_window=20, confirm_frac=0.24)
    assert est._window_required_hits == 6


def test_window_mode_cannot_confirm_below_its_own_duty_cycle_floor():
    """The real limit (measured, not a bug): confirm_frac is a hard floor
    on the average hit fraction the window can ever reach -- it does NOT
    get easier to clear by waiting longer or choosing a different rate.
    At confirm_frac=0.773 (the operating point matched to legacy
    confirm_frames=12's false-fire suppression at 16 kHz/256, see the
    constructor docstring's k_held_sweep numbers), a 50%-duty AM step
    NEVER confirms, at any rate, because the window's achievable hit
    count caps at ~50% of its size -- strictly below the 77.3% required.
    This is the real trade-off window mode does not escape: a frac high
    enough to match legacy's fricative rejection cannot also confirm a
    modulation whose duty cycle sits below that frac."""
    est = _make_estimator(confirm_window=17, confirm_frac=0.773)
    for t in range(300):
        mag = _am_magnitude(rate_hz=6.0, t_frame=t)
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False
    assert est._window_hit_count < est._window_required_hits
    # The ceiling is duty-cycle-bound, not budget-bound: a much longer run
    # does not help either.
    for t in range(300, 2000):
        mag = _am_magnitude(rate_hz=6.0, t_frame=t)
        est.update(mag, spp=SPP_HIGH)
    assert est._scene_change_confirmed is False
