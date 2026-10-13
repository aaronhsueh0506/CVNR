"""First frame after noise initialization.

The first estimate after initialization has no a-priori SNR history, so it uses the direct
estimate max(gamma - 1, 0). That estimate must carry the same floor xi_min as the
decision-directed estimate of later frames: with xi = 0 the MMSE-LSA gain is exactly g_min
whatever the speech presence probability, which drops the first tracked frame to the gain floor
while the following frames settle higher.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from process_audio import create_denoiser_from_config  # noqa: E402
from core.spp_estimator import SppEstimator  # noqa: E402

SR = 16000
CONFIG_DIR = os.path.join(ROOT, 'config')


def test_first_estimate_is_floored_at_xi_min():
    est = SppEstimator(alpha=0.92, q=0.5, xi_min_db=-10.0)
    noise = np.full(8, 100.0)
    power = np.array([10.0, 50.0, 99.0, 100.0, 101.0, 150.0, 400.0, 1000.0])
    _, xi, gamma = est.estimate(power, noise)
    assert np.all(xi >= est.xi_min)
    assert np.allclose(xi[:4], est.xi_min)            # gamma <= 1 + xi_min: floor
    assert np.allclose(xi[5:], gamma[5:] - 1.0)       # clearly above the floor: direct estimate


def test_first_tracked_frame_is_not_below_the_following_frames():
    d = create_denoiser_from_config('V3-2', CONFIG_DIR, SR, mode='full', strength='balanced')
    p = d.get_params()
    n_freqs = p['fft_size'] // 2 + 1
    num_init = d.noise_estimator.num_init_frames
    n_frames = num_init + 20
    k = np.arange(n_freqs)[None, :]
    h = np.arange(n_frames)[:, None]
    mag = 400.0 + ((k * 7 + h * 3) % 11)
    extra = np.full((n_frames, n_freqs), 1.0e8)       # residual-echo PSD far above the signal: gamma << 1
    out = d.denoise_spectrum(mag, np.zeros_like(mag), return_gain=True, extra_noise_psd=extra)
    gain = out[2]
    assert np.all(gain[:num_init] == 1.0)
    db = np.mean(20 * np.log10(gain + 1e-6), axis=1)
    first, settled = db[num_init], float(np.mean(db[num_init + 10:]))
    assert first > settled - 1.0, (first, settled)
