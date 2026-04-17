"""Unit tests for FreqAdaptiveController."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from core.freq_adaptive_controller import FreqAdaptiveController


@pytest.fixture
def ctrl():
    return FreqAdaptiveController(sample_rate=16000, fft_size=512)


def test_prob_zero_returns_normal_profile(ctrl):
    p = ctrl.get_params(0.0, 'none')
    # 全部頻段 g_min = -15 dB (linear 10^-1.5)
    assert np.allclose(10 * np.log10(p['g_min']), -15.0, atol=0.01)
    # alpha_xi = 0.88
    assert np.allclose(p['alpha_xi'], 0.88, atol=0.01)


def test_prob_one_returns_severe_profile(ctrl):
    p = ctrl.get_params(1.0, 'severe')
    # 低頻段 (band_0: 0-200Hz ≈ bin 0-6) g_min = -35 dB
    assert 10 * np.log10(p['g_min'][0]) == pytest.approx(-35.0, abs=0.1)
    # >4kHz (bin ~128+) g_min = -15 dB
    assert 10 * np.log10(p['g_min'][150]) == pytest.approx(-15.0, abs=0.1)


def test_interpolation_is_monotonic(ctrl):
    # 檢查 prob 上升時 low-band g_min 單調降低
    g_mins = []
    for p in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
        r = ctrl.get_params(p)
        g_mins.append(10 * np.log10(r['g_min'][0]))
    for i in range(1, len(g_mins)):
        assert g_mins[i] <= g_mins[i - 1] + 1e-6


def test_mid_prob_between_profiles(ctrl):
    # prob=0.5 介於 mild(0.4) 與 severe(0.75) 之間，低頻 g_min 應在 -25 ~ -35 之間
    p = ctrl.get_params(0.5)
    g_min_low_db = 10 * np.log10(p['g_min'][0])
    assert -35.0 < g_min_low_db < -25.0


def test_high_freq_band_unchanged_even_in_severe(ctrl):
    # >4kHz 頻段不管 prob 多少，g_min 都應為 -15 dB
    for p in [0.0, 0.5, 1.0]:
        r = ctrl.get_params(p)
        g_min_high_db = 10 * np.log10(r['g_min'][200])  # 6kHz 左右
        assert g_min_high_db == pytest.approx(-15.0, abs=0.1)


def test_array_shape_matches_n_freqs(ctrl):
    p = ctrl.get_params(0.3)
    assert p['g_min'].shape == (ctrl.n_freqs,)
    assert p['alpha_xi'].shape == (ctrl.n_freqs,)
    assert p['alpha_g'].shape == (ctrl.n_freqs,)
