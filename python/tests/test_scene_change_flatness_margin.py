"""The MCRA scene-change reset must take the same branch as the C port on
frames whose high-band spectral flatness lies within a few 1e-4 of
scene_change_flatness_threshold.

The detector fires after scene_change_min_frames consecutive frames with a
high-band energy ratio above scene_change_threshold_db AND a high-band
flatness above the threshold, and then blends the noise floor toward the
frame power. On DNS 2020 clip fileid_63 the reference computed a flatness of
0.40061 where a cubic exp approximation in the C port gave 0.39991, so the
two trackers reset on different frames and the outputs diverged for ~120
frames (16 dB waveform parity). The two synthetic bursts below sit +6e-4 and
-6e-4 from the threshold, inside that approximation's 1.7e-3 relative
error: the first must fire, the second must not. c_impl/test/
test_scene_change_margin.c drives the C tracker with the same numbers.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.noise_estimators.mcra import McraNoiseEstimator, _spectral_flatness  # noqa: E402

N_FREQS = 257          # 16 kHz / FFT 512
HI_START = 128         # the detector's high band is the upper half
# 64 bins at HI_A, 65 at HI_B_*. Flatness is scale-free; the level puts the
# mean log power at 5.52, whose fractional part (0.52, folded to -0.48) is
# where a cubic Taylor exp over [-0.5, 0.5) is 0.33% low -- five times the
# margins below (it computed 0.39928 for the frame that must fire).
HI_A = 1200.0
HI_B_FIRE = 53.02      # flatness 0.400612: +6.1e-4 above the 0.4 threshold
HI_B_HOLD = 52.68      # flatness 0.399426: -5.7e-4 below it
N_INIT = 8
MIN_FRAMES = 4
FIRE_MIN = 480.0       # a fired reset leaves the HI_A bins near 0.5 * (N + HI_A)
HOLD_MAX = 120.0       # the ordinary SPP-gated update stays far below that
# Tracker constants of the C default config at 16 kHz / 512 so both tests
# see the same numbers (c_impl test_config_parity dump).
TRACKER = dict(alpha_s=0.921208143, alpha_d=0.849999964, alpha_p=0.0761461556,
               L=32, delta_db=10.0, broadband_threshold=1.0,
               scene_change_threshold_db=10.0)


def _burst_power(hi_b):
    power = np.ones(N_FREQS)
    power[HI_START:HI_START + 64] = HI_A
    power[HI_START + 64:] = hi_b
    return power


def _hi_noise_after_burst(hi_b):
    est = McraNoiseEstimator(num_init_frames=N_INIT,
                             scene_change_min_frames=MIN_FRAMES, **TRACKER)
    est.estimate(np.ones((N_INIT, N_FREQS)))
    magnitude = np.sqrt(_burst_power(hi_b))
    for _ in range(MIN_FRAMES):
        est.update(magnitude)
    return est.noise_psd[HI_START:]


def test_flatness_margins_sit_inside_a_cubic_exp_error_band():
    fire = _spectral_flatness(_burst_power(HI_B_FIRE)[HI_START:])
    hold = _spectral_flatness(_burst_power(HI_B_HOLD)[HI_START:])
    assert 2e-4 < fire - 0.4 < 8e-4, fire
    assert -8e-4 < hold - 0.4 < -2e-4, hold


def test_reset_fires_just_above_the_flatness_threshold():
    hi = _hi_noise_after_burst(HI_B_FIRE)
    assert hi.max() > FIRE_MIN, hi.max()


def test_reset_holds_just_below_the_flatness_threshold():
    hi = _hi_noise_after_burst(HI_B_HOLD)
    assert hi.max() < HOLD_MAX, hi.max()
