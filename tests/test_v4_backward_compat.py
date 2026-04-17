"""
Backward-compat: V4 with wind_handler=False and transient_suppressor=False
should produce identical output to V3-2 MmseLsaDenoiser given same params.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from denoisers import MmseLsaDenoiser, OmlsaDenoiser


@pytest.fixture
def signal():
    np.random.seed(42)
    sr = 16000
    sig = np.random.randn(sr * 2) * 0.02
    t = np.linspace(0, 1, sr)
    sig[4000:20000] += 0.3 * np.sin(2 * np.pi * 440 * t)
    return sig


def _common_params():
    return dict(
        sample_rate=16000,
        frame_size=512,
        frame_shift=256,
        fft_size=512,
        noise_method='mcra',
        alpha_s=0.95,
        alpha_d=0.7,
        alpha_p=0.2,
        L=32,
        delta_db=10.0,
        num_init_frames=20,
        broadband_threshold=1.0,
        scene_change_flatness_threshold=0.4,
        alpha_xi=0.88,
        q=0.5,
        xi_min_db=-20.0,
        g_min_db=-15.0,
        alpha_g=0.88,
        use_asymmetric_smoothing=True,
        alpha_attack=0.3,
        alpha_decay=None,
    )


def test_v4_off_matches_v3_2(signal):
    params = _common_params()

    d32 = MmseLsaDenoiser(**params)
    d4 = OmlsaDenoiser(enable_wind_handler=False,
                       enable_transient_suppressor=False, **params)

    out32 = d32.denoise(signal.copy())
    out4 = d4.denoise(signal.copy())

    rms_diff = np.sqrt(np.mean((out32 - out4) ** 2))
    # V4 off 應與 V3-2 幾乎一致（允許極小浮點誤差）
    assert rms_diff < 1e-10, f"V4 off should match V3-2, got RMS diff {rms_diff}"


def test_v4_wind_on_changes_output(signal):
    params = _common_params()

    d_off = OmlsaDenoiser(enable_wind_handler=False,
                          enable_transient_suppressor=False, **params)
    d_on = OmlsaDenoiser(
        enable_wind_handler=True,
        enable_transient_suppressor=False,
        wind_detector_config={
            'low_energy_ratio_threshold': 0.5,  # 降低門檻讓 wind 觸發
            'spectral_tilt_threshold_db': 6.0,
            'mild_threshold': 0.3,
            'severe_threshold': 0.6,
        },
        **params,
    )

    out_off = d_off.denoise(signal.copy())
    out_on = d_on.denoise(signal.copy())

    # 兩者應不同（wind handler 有影響）
    rms_diff = np.sqrt(np.mean((out_off - out_on) ** 2))
    assert rms_diff > 1e-5
