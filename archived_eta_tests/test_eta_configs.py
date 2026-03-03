#!/usr/bin/env python3
"""
測試不同 eta 配置對 PESQ/STOI 的影響

測試配置:
1. baseline: enable_eta=False
2. hard_th10: threshold=10, slope=0
3. sigmoid_th10_s20: threshold=10, slope=20
4. sigmoid_th15_s10: threshold=15, slope=10 (conservative)
"""

import numpy as np
import librosa
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser

try:
    from pesq import pesq
    from pystoi import stoi
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    print("Warning: pesq/pystoi not available, will only compare SPP")


def create_denoiser(enable_eta, threshold, slope):
    """創建指定配置的 denoiser"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        noise_method='mcra',
        alpha_s=0.8,
        alpha_noise=0.95,
        alpha_p=0.2,
        L=120,
        delta_db=5.0,
        num_init_frames=20,
        enable_eta=enable_eta,
        eta_beta_threshold=threshold,
        eta_slope=slope
    )


def test_config(noisy_path, clean_path, config_name, enable_eta, threshold, slope):
    """測試單一配置"""
    noisy, sr = librosa.load(noisy_path, sr=16000)
    clean, _ = librosa.load(clean_path, sr=16000)

    # 對齊長度
    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    denoiser = create_denoiser(enable_eta, threshold, slope)
    enhanced, spp = denoiser.denoise(noisy, return_spp=True)
    enhanced = enhanced[:min_len]

    result = {
        'config': config_name,
        'spp_mean': np.mean(spp),
        'spp_std': np.std(spp)
    }

    if METRICS_AVAILABLE:
        result['pesq'] = pesq(sr, clean, enhanced, 'wb')
        result['stoi'] = stoi(clean, enhanced, sr, extended=False)

    return result


def main():
    # 測試檔案 (有場景變化的 prepend 檔案)
    test_files = [
        ('test_wav/wav/append_silence/babble_0dB_prepend.wav', 'test_wav/wav/append_silence/clean_prepend.wav'),
        ('test_wav/wav/append_silence/babble_5dB_prepend.wav', 'test_wav/wav/append_silence/clean_prepend.wav'),
        ('test_wav/wav/append_silence/car_0dB_prepend.wav', 'test_wav/wav/append_silence/clean_prepend.wav'),
        ('test_wav/wav/append_silence/street_0dB_prepend.wav', 'test_wav/wav/append_silence/clean_prepend.wav'),
    ]

    # 測試配置
    configs = [
        ('baseline', False, 10.0, 0),
        ('hard_th10', True, 10.0, 0),
        ('sigmoid_th10_s20', True, 10.0, 20.0),
        ('sigmoid_th15_s10', True, 15.0, 10.0),
        ('sigmoid_th5_s20', True, 5.0, 20.0),
    ]

    print("="*80)
    print("Eta 配置測試")
    print("="*80)

    all_results = {cfg[0]: [] for cfg in configs}

    for noisy_path, clean_path in test_files:
        if not os.path.exists(noisy_path):
            print(f"跳過: {noisy_path} (不存在)")
            continue

        print(f"\n--- {os.path.basename(noisy_path)} ---")

        for config_name, enable_eta, threshold, slope in configs:
            result = test_config(noisy_path, clean_path, config_name, enable_eta, threshold, slope)
            all_results[config_name].append(result)

            if METRICS_AVAILABLE:
                print(f"  {config_name:20}: PESQ={result['pesq']:.3f}, STOI={result['stoi']:.3f}")
            else:
                print(f"  {config_name:20}: SPP mean={result['spp_mean']:.4f}")

    # 匯總
    print("\n" + "="*80)
    print("平均分數")
    print("="*80)

    if METRICS_AVAILABLE:
        print(f"{'Config':20} | {'PESQ':>8} | {'STOI':>8}")
        print("-"*45)
        for config_name, results in all_results.items():
            if results:
                avg_pesq = np.mean([r['pesq'] for r in results])
                avg_stoi = np.mean([r['stoi'] for r in results])
                print(f"{config_name:20} | {avg_pesq:>8.3f} | {avg_stoi:>8.3f}")
    else:
        print(f"{'Config':20} | {'SPP Mean':>10}")
        print("-"*35)
        for config_name, results in all_results.items():
            if results:
                avg_spp = np.mean([r['spp_mean'] for r in results])
                print(f"{config_name:20} | {avg_spp:>10.4f}")


if __name__ == "__main__":
    main()
