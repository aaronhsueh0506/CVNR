"""The MCRA noise tracker must recover after digital silence.

A bin whose noise estimate has decayed below McraNoiseEstimator.NOISE_PSD_INERT
(a few seconds of exact-zero input) used to be stuck for good: the 1e-10
epsilons in every consumer hide such a tiny N, so when a signal returns the
posterior saturates at exactly 1.0, the SPP-gated update coefficient becomes
exactly 1.0 and the estimate never moves again -- the bin's gain stays near
unity instead of falling to the noise floor. The dead-bin restart in
McraNoiseEstimator.update() re-seeds such bins with the ungated blend.

The test drives the production V3-2 denoiser on a magnitude spectrogram of
5 s of exact zeros followed by 10 s of a stationary single-bin tone, and
requires the tone bin to be suppressed like the same tone without the leading
silence. Reverting the restart makes the silence-first gain sit at ~0.93
(-0.6 dB) for the whole 10 s while the control reaches ~0.05 (-26 dB).
"""
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from process_audio import create_denoiser_from_config  # noqa: E402
from core.noise_estimators.mcra import McraNoiseEstimator  # noqa: E402

SR = 16000
CONFIG_DIR = os.path.join(ROOT, 'config')


def _tone_gain(silence_s, tone_s, strength='balanced'):
    """Gain of the tone bin over the last second of the tone, given
    `silence_s` seconds of exact-zero frames before it."""
    d = create_denoiser_from_config('V3-2', CONFIG_DIR, SR, mode='full',
                                    strength=strength)
    p = d.get_params()
    n_freqs = p['fft_size'] // 2 + 1
    hop = p['frame_shift']
    n_sil = int(silence_s * SR / hop)
    n_tone = int(tone_s * SR / hop)
    k = int(round(1000.0 * p['fft_size'] / SR))
    mag = np.zeros((n_sil + n_tone, n_freqs))
    mag[n_sil:, k] = 0.03 * 32768.0 * (p['fft_size'] / 2)   # -30 dBFS tone
    phase = np.zeros_like(mag)
    enhanced, _ = d.denoise_spectrum(mag, phase)
    last = slice(n_sil + n_tone - int(SR / hop), n_sil + n_tone)
    return float(np.mean(enhanced[last, k] / mag[last, k]))


def test_tone_after_digital_silence_is_suppressed_like_control():
    control = _tone_gain(0.0, 10.0)
    after_silence = _tone_gain(5.0, 10.0)
    assert control < 0.1, control                     # a stationary tone is noise
    assert after_silence < 0.1, after_silence         # ... also after 5 s of zeros
    assert abs(after_silence - control) < 0.02, (after_silence, control)


def test_restart_only_touches_numerically_dead_bins(monkeypatch):
    """The restart is inert unless N < NOISE_PSD_INERT: on normal-level input
    an estimator with the branch disabled (threshold 0) produces the exact
    same array as one with it enabled."""
    import copy
    rng = np.random.default_rng(0)
    est = McraNoiseEstimator()
    mags = rng.uniform(1e1, 1e3, size=(est.num_init_frames + 1, 129))
    est.estimate(mags)
    twin = copy.deepcopy(est)
    spp = rng.uniform(0.0, 1.0, size=129)
    frame = rng.uniform(1e1, 1e3, size=129)
    with_restart = est.update(frame, spp).copy()
    monkeypatch.setattr(McraNoiseEstimator, 'NOISE_PSD_INERT', 0.0)
    without_restart = twin.update(frame, spp).copy()
    assert np.array_equal(with_restart, without_restart)
    assert np.all(with_restart > 0.0)
