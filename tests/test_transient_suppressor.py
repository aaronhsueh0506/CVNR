"""Unit tests for TransientSuppressor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from core.transient_suppressor import TransientSuppressor


def test_single_burst_is_suppressed():
    sr = 16000
    ts = TransientSuppressor(sample_rate=sr, suppression_db=-12.0)
    signal = 0.05 * np.random.RandomState(0).randn(sr)
    burst_start = sr // 2
    burst_len = int(0.03 * sr)  # 30ms burst
    signal[burst_start:burst_start + burst_len] += 1.0 * np.random.RandomState(1).randn(burst_len)

    out = ts.process(signal.copy())
    rms_sig = np.sqrt(np.mean(signal[burst_start:burst_start + burst_len] ** 2))
    rms_out = np.sqrt(np.mean(out[burst_start:burst_start + burst_len] ** 2))
    assert rms_out < rms_sig  # 至少有抑制


def test_pure_speech_is_not_over_suppressed():
    sr = 16000
    ts = TransientSuppressor(sample_rate=sr)
    # 模擬語音：440Hz sine + 中頻噪聲
    t = np.linspace(0, 1, sr)
    speech = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.03 * np.random.RandomState(0).randn(sr)
    out = ts.process(speech.copy())
    ratio = np.sqrt(np.mean(out ** 2)) / np.sqrt(np.mean(speech ** 2))
    # 語音段不應被過度壓制（> 0.7 表示 < 3dB 衰減）
    assert ratio > 0.7


def test_reset_clears_state():
    ts = TransientSuppressor()
    signal = np.random.RandomState(0).randn(100)
    _ = ts.process(signal)
    assert ts.short_rms_prev != 0.0 or ts.long_rms_prev != 0.0
    ts.reset()
    assert ts.short_rms_prev == 0.0
    assert ts.long_rms_prev == 0.0
    assert ts.gain_prev == 1.0


def test_output_finite():
    sr = 16000
    ts = TransientSuppressor(sample_rate=sr)
    signal = np.random.RandomState(0).randn(sr * 2)
    out = ts.process(signal)
    assert np.all(np.isfinite(out))
    assert out.shape == signal.shape


def test_no_suppression_on_quiet_signal():
    """極低能量 signal 不應觸發 transient（因為 short_power / long_power ratio 應接近 1）。"""
    sr = 16000
    ts = TransientSuppressor(sample_rate=sr)
    signal = 1e-5 * np.ones(sr)  # 穩定極低信號
    out = ts.process(signal.copy())
    # gain 應保持接近 1
    assert ts.gain_prev > 0.9
