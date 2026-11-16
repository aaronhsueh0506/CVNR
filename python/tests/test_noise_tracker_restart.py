"""Digital silence and the MCRA noise tracker.

Frames whose bins are all exactly zero carry no noise statistics: they neither
count toward initialization nor advance the tracker. A floor seeded from zeros
(or decayed to the inert level during silence) is hidden by the 1e-10 epsilons
in every consumer, so when a stationary signal returns the posterior saturates
at exactly 1.0, the SPP-gated update coefficient becomes exactly 1.0 and the
estimate never moves. The dead-bin restart in McraNoiseEstimator.update()
re-seeds such bins with the ungated blend.

The tests drive the production V3-2 denoiser on a magnitude spectrogram of
5 s of exact zeros followed by 10 s of a stationary single-bin tone, and
require the tone bin to be suppressed like the same tone without the leading
silence, also when the first tone frame is a reduced-power waveform onset, and
require silence to leave a converged noise floor unchanged.
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


def _tone_gain(silence_s, tone_s, strength='balanced', onset=1.0):
    """Gain of the tone bin over the last second of the tone, given
    `silence_s` seconds of exact-zero frames before it, and the preset's
    linear gain floor. The first tone frame has `onset` times the steady
    amplitude (a frame straddling the waveform onset)."""
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
    mag[n_sil, k] *= onset
    phase = np.zeros_like(mag)
    enhanced, _ = d.denoise_spectrum(mag, phase)
    last = slice(n_sil + n_tone - int(SR / hop), n_sil + n_tone)
    return float(np.mean(enhanced[last, k] / mag[last, k])), 10 ** (p['g_min_db'] / 20)


def test_tone_after_digital_silence_is_suppressed_like_control():
    control, floor = _tone_gain(0.0, 10.0)
    after_silence, _ = _tone_gain(5.0, 10.0)
    # The 1 kHz probe sits above the LF speech guard; a stationary tone settles
    # a few dB above the preset floor because the fixed speech prior and the
    # a-priori-SNR floor keep OM-LSA off g_min. Bound the gain by the preset's
    # own floor rather than a literal so a depth retune cannot silently loosen
    # this check; the dead-bin failure it guards is ~0.93.
    assert control < 4.0 * floor, (control, floor)
    assert after_silence < 4.0 * floor, (after_silence, floor)
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


def test_tone_with_waveform_onset_after_digital_silence_is_suppressed():
    """A frame straddling the onset carries reduced power. Zero frames must not count toward
    initialization, otherwise the floor is seeded from that partial frame and the tracker
    never moves it."""
    control, floor = _tone_gain(0.0, 10.0, onset=0.25)
    after_silence, _ = _tone_gain(5.0, 10.0, onset=0.25)
    assert control < 4.0 * floor, (control, floor)
    assert after_silence < 4.0 * floor, (after_silence, floor)
    assert abs(after_silence - control) < 0.02, (after_silence, control)


def test_digital_silence_does_not_move_converged_noise_floor():
    d = create_denoiser_from_config('V3-2', CONFIG_DIR, SR, mode='full',
                                    strength='balanced')
    p = d.get_params()
    n_freqs = p['fft_size'] // 2 + 1
    hop = p['frame_shift']
    n_noise = 4 * p['num_init_frames']
    n_sil = int(5.0 * SR / hop)
    rng = np.random.default_rng(1)
    mag = np.zeros((n_noise + n_sil, n_freqs))
    mag[:n_noise] = rng.uniform(300.0, 500.0, size=(n_noise, n_freqs))
    phase = np.zeros_like(mag)
    _, _, noise_psd = d.denoise_spectrum(mag, phase, return_noise_psd=True)
    assert np.array_equal(noise_psd[n_noise], noise_psd[-1])


# Bins that were zero for 1 to 10 s keep a small estimate above the inert floor; when the signal
# returns the posterior is 1 and the estimate cannot follow. After frozen_hops frames above
# FROZEN_POWER_RATIO times the estimate it restarts from the smoothed power.
GRIDS = ((16000, 256), (16000, 512), (48000, 1024))
RUN_SECONDS = 2.048
SETTLE_EXTRA_SECONDS = 0.3


def _half_zero_gain(sr, fft, zero_s, back_s=4.0, broadband=1.0):
    """Mean gain of the upper half of the spectrum per frame after `zero_s` seconds in which those
    bins are exactly zero (the lower half stays live); the stream is the one of the C test."""
    d = create_denoiser_from_config('V3-2', CONFIG_DIR, sr, mode='full', strength='balanced',
                                    fft_size=fft)
    d.noise_estimator.broadband_threshold = broadband
    p = d.get_params()
    nf, hop = fft // 2 + 1, p['frame_shift']
    hi = nf // 2
    n_conv = 4 * p['num_init_frames']
    n_zero = int(zero_s * sr / hop)
    n_back = int(back_s * sr / hop)
    k = np.arange(nf)
    mag = np.empty((n_conv + n_zero + n_back, nf))
    for h in range(mag.shape[0]):
        mag[h] = np.where(k % 16 == 0, 12000.0, 400.0) + ((k * 7 + h * 3) % 11)
    mag[n_conv:n_conv + n_zero, hi:] = 0.0
    _, _, gain = d.denoise_spectrum(mag, np.zeros_like(mag), return_gain=True)
    return np.mean(np.asarray(gain)[n_conv + n_zero:, hi:], axis=1), hop / sr, d


def _settle_seconds(mean_gain, hop_s, control):
    off = np.flatnonzero(np.abs(mean_gain - control) >= 0.02)
    return (off[-1] + 1) * hop_s if off.size else 0.0


@pytest.mark.parametrize('sr,fft', GRIDS)
@pytest.mark.parametrize('broadband', (1.0, 0.8))
@pytest.mark.parametrize('gap_s', (1.0, 3.0, 10.0))
def test_bins_zero_for_seconds_return_to_the_control_gain(sr, fft, gap_s, broadband):
    control_series, hop_s, d = _half_zero_gain(sr, fft, 0.0, broadband=broadband)
    control = float(control_series[-1])
    series, _, _ = _half_zero_gain(sr, fft, gap_s, broadband=broadband)
    assert abs(series[-1] - control) < 0.02, (series[-1], control)
    settle = _settle_seconds(series, hop_s, control)
    assert settle <= RUN_SECONDS + SETTLE_EXTRA_SECONDS, (settle, gap_s)
    assert d.noise_estimator.frozen_hops * hop_s >= RUN_SECONDS


def _frozen_estimator(pattern, high):
    """Estimator of the 16 kHz / 512 grid, every 8th bin at `high` times the converged level for 'H'
    frames, posterior 1; returns (noise_psd after the pattern, frozen_hops)."""
    d = create_denoiser_from_config('V3-2', CONFIG_DIR, SR, mode='full', strength='balanced',
                                    fft_size=512)
    est = d.noise_estimator
    nf = 257
    est.estimate(np.full((est.num_init_frames, nf), np.sqrt(1000.0)))
    spp = np.ones(nf)
    spiked = np.arange(nf) % 8 == 0
    for c in pattern:
        mag = np.full(nf, np.sqrt(1000.0))
        if c == 'H':
            mag[spiked] = np.sqrt(1000.0 * high)
        est.update(mag, spp=spp)
    return est.noise_psd.copy(), est.frozen_hops


def test_frozen_run_reseeds_after_an_uninterrupted_run_only():
    ratio = McraNoiseEstimator.FROZEN_POWER_RATIO
    above, below = ratio * 1.1, ratio * 0.9
    _, run = _frozen_estimator('', above)
    assert run == 128
    psd, _ = _frozen_estimator('H' * (run - 1), above)
    assert np.all(psd == 1000.0)
    psd, _ = _frozen_estimator('H' * run, above)
    # The C test pins 70398.1 for this stream (float32).
    assert np.allclose(psd[0], 70398.1, rtol=1e-5), psd[0]
    assert psd[1] == 1000.0
    psd, _ = _frozen_estimator('H' * (6 * run), below)
    assert np.all(psd == 1000.0)
    psd, _ = _frozen_estimator('H' * (run - 1) + 'L' + 'H' * (run - 1), above)
    assert np.all(psd == 1000.0)
    psd, _ = _frozen_estimator('H' * (run - 1) + 'L' + 'H' * run, above)
    assert psd[0] > 10000.0


def test_frozen_reseed_is_off_without_frozen_hops():
    est = McraNoiseEstimator()
    est.estimate(np.full((est.num_init_frames, 129), np.sqrt(1000.0)))
    spp = np.ones(129)
    spiked = np.arange(129) % 8 == 0
    for _ in range(200):
        mag = np.full(129, np.sqrt(1000.0))
        mag[spiked] = np.sqrt(1e5)
        est.update(mag, spp=spp)
    assert np.all(est.noise_psd == 1000.0)
