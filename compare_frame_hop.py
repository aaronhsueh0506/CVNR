#!/usr/bin/env python3
"""
Compare old frame/hop (20ms/10ms) vs new (32ms/16ms) on NR quality.
Quick A/B test for V3, V3-2, V3-3.
"""

import numpy as np
import librosa
import sys
import os
import yaml

sys.path.insert(0, os.path.dirname(__file__))

from denoisers import SppMmseDenoiser, MmseLsaDenoiser, PmmseDenoiser
from utils.metrics import calculate_pesq, calculate_stoi, calculate_lsd

# Test files
CLEAN_PATH = "test_wav/wav/clean.wav"
TEST_CASES = [
    ("babble_5dB", "test_wav/wav/babble_5dB.wav"),
    ("car_5dB", "test_wav/wav/car_5dB.wav"),
    ("street_5dB", "test_wav/wav/street_5dB.wav"),
]

VERSIONS = {
    'V3': {'class': SppMmseDenoiser, 'config': 'config/v3_config.yaml'},
    'V3-2': {'class': MmseLsaDenoiser, 'config': 'config/v3_2_config.yaml'},
    'V3-3': {'class': PmmseDenoiser, 'config': 'config/v3_3_config.yaml'},
}

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_params(config, sr, fft_size, frame_size, frame_shift):
    """Extract denoiser params from config, overriding frame/hop."""
    params = {
        'sample_rate': sr,
        'fft_size': fft_size,
        'frame_size': frame_size,
        'frame_shift': frame_shift,
    }

    gc = config.get('gain_calculation', {})
    method = gc.get('method', '')

    if method == 'spp_mmse':
        params.update({
            'g_min_db': gc.get('g_min_db', -20.0),
            'alpha_g': gc.get('alpha_g', 0.7),
            'use_full_formula': gc.get('use_full_formula', False),
        })
    elif method == 'mmse_lsa':
        params.update({
            'g_min_db': gc.get('g_min_db', -20.0),
            'alpha_g': gc.get('alpha_g', 0.7),
        })
    elif method == 'pmmse':
        params.update({
            'g_min_db': gc.get('g_min_db', -20.0),
            'alpha_g': gc.get('alpha_g', 0.5),
            'use_spp_weighting': gc.get('use_spp_weighting', True),
        })

    if 'spp' in config:
        spp = config['spp']
        params.update({
            'alpha_xi': spp.get('alpha_xi', 0.98),
            'q': spp.get('q', 0.5),
            'xi_min_db': spp.get('xi_min_db', -25.0),
        })

    if 'noise_estimation' in config:
        ne = config['noise_estimation']
        if ne.get('method') == 'mcra':
            params.update({
                'noise_method': 'mcra',
                'alpha_s': ne.get('alpha_s', 0.9),
                'alpha_noise': ne.get('alpha_d', 0.85),
                'alpha_p': ne.get('alpha_p', 0.2),
                'L': ne.get('L', 96),
                'delta_db': ne.get('delta_db', 5.0),
            })

    return params

def evaluate(clean, enhanced, sr):
    """Compute PESQ, STOI, LSD."""
    min_len = min(len(clean), len(enhanced))
    c, e = clean[:min_len], enhanced[:min_len]
    try:
        pesq = calculate_pesq(c, e, sr)
    except Exception:
        pesq = None
    try:
        stoi = calculate_stoi(c, e, sr)
    except Exception:
        stoi = None
    try:
        lsd = calculate_lsd(c, e)
    except Exception:
        lsd = None
    return pesq, stoi, lsd


def main():
    sr = 16000

    # Load clean reference
    clean, _ = librosa.load(CLEAN_PATH, sr=sr)

    # Settings to compare
    settings = [
        ("OLD (frame=320, hop=160)", 320, 160),
        ("NEW (frame=512, hop=256)", 512, 256),
    ]

    print("=" * 100)
    print("Frame/Hop Size A/B Comparison")
    print("=" * 100)

    for version_name, version_info in VERSIONS.items():
        config = load_config(version_info['config'])
        fft_size = config['audio']['fft_size']

        print(f"\n{'='*80}")
        print(f"  {version_name}")
        print(f"{'='*80}")

        for test_name, test_path in TEST_CASES:
            if not os.path.exists(test_path):
                print(f"  {test_name}: file not found, skipping")
                continue

            noisy, _ = librosa.load(test_path, sr=sr)

            # Compute noisy baseline
            pesq_n, stoi_n, lsd_n = evaluate(clean, noisy, sr)

            print(f"\n  {test_name}:")
            print(f"    {'Noisy baseline':<40s}  PESQ={pesq_n:.3f}  STOI={stoi_n:.3f}  LSD={lsd_n:.2f}")

            for label, frame_sz, hop_sz in settings:
                params = get_params(config, sr, fft_size, frame_sz, hop_sz)
                denoiser = version_info['class'](**params)
                enhanced = denoiser.denoise(noisy)

                pesq_e, stoi_e, lsd_e = evaluate(clean, enhanced, sr)

                # Deltas
                dp = f"{pesq_e - pesq_n:+.3f}" if pesq_e and pesq_n else "N/A"
                ds = f"{stoi_e - stoi_n:+.3f}" if stoi_e and stoi_n else "N/A"
                dl = f"{lsd_e - lsd_n:+.2f}" if lsd_e and lsd_n else "N/A"

                pesq_str = f"{pesq_e:.3f}" if pesq_e else "N/A"
                stoi_str = f"{stoi_e:.3f}" if stoi_e else "N/A"
                lsd_str = f"{lsd_e:.2f}" if lsd_e else "N/A"

                print(f"    {label:<40s}  PESQ={pesq_str} ({dp})  STOI={stoi_str} ({ds})  LSD={lsd_str} ({dl})")

    print(f"\n{'='*100}")
    print("Done.")


if __name__ == "__main__":
    main()
