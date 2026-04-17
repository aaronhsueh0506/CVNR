"""Unit tests for WindDetector."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from core.wind_detector import WindDetector


@pytest.fixture
def detector():
    return WindDetector(sample_rate=16000, fft_size=512)


def _make_mag(n_freqs, low_val, high_val, low_bins=15):
    m = np.full(n_freqs, high_val, dtype=np.float64)
    m[:low_bins] = low_val
    return m


def test_pure_silence_gives_low_prob(detector):
    # 接近零能量 → 應為低機率（或 NaN 避免）
    mag = np.full(257, 1e-6)
    r = detector.detect(mag)
    assert 0.0 <= r['wind_probability'] <= 1.0
    assert r['wind_severity'] == 'none'


def test_wind_like_signal_eventually_raises_prob(detector):
    # 低頻遠強於高頻，連續若干幀
    mag = _make_mag(257, low_val=4.0, high_val=0.05)
    probs = []
    for _ in range(30):
        r = detector.detect(mag)
        probs.append(r['wind_probability'])
    # 時間平滑後應收斂到很高
    assert probs[-1] > 0.5


def test_speech_like_signal_stays_low(detector):
    # 模擬語音：能量集中在 200-2000Hz，低頻不特別強
    mag = np.zeros(257)
    mag[6:60] = 1.0   # ~200-2kHz
    mag[60:200] = 0.3
    probs = []
    for _ in range(30):
        r = detector.detect(mag)
        probs.append(r['wind_probability'])
    assert probs[-1] < 0.5


def test_hangover_keeps_mild_for_configured_frames():
    det = WindDetector(sample_rate=16000, fft_size=512, hangover_frames=10)
    # 先觸發 severe
    wind_mag = _make_mag(257, low_val=8.0, high_val=0.02)
    for _ in range(30):
        det.detect(wind_mag)
    # 切換到語音 like
    speech_mag = np.zeros(257)
    speech_mag[6:60] = 1.0
    speech_mag[60:200] = 0.3
    sevs = []
    for _ in range(5):  # hangover 期間
        r = det.detect(speech_mag)
        sevs.append(r['wind_severity'])
    # hangover 內至少前幾幀還保持 mild
    assert 'mild' in sevs or 'severe' in sevs


def test_reset_clears_state(detector):
    wind_mag = _make_mag(257, low_val=8.0, high_val=0.02)
    for _ in range(20):
        detector.detect(wind_mag)
    assert detector.wind_prob_prev > 0.1
    detector.reset()
    assert detector.wind_prob_prev == 0.0
    assert detector.hangover_counter == 0
    assert detector.frame_count == 0


def test_zcr_feature_used_when_time_domain_provided(detector):
    mag = _make_mag(257, low_val=4.0, high_val=0.05)
    t = np.random.randn(512)
    r = detector.detect(mag, time_domain_frame=t)
    assert r['features']['zcr'] is not None
    r2 = detector.detect(mag)
    assert r2['features']['zcr'] is None
