#!/usr/bin/env python3
"""
完整比較 eta=false vs eta=true (threshold=2) 的 PESQ/STOI 分數
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
    print("Error: pesq/pystoi not available")
    sys.exit(1)


def create_denoiser(enable_eta, threshold=2.0, slope=20.0):
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
        alpha_xi=0.92,
        q=0.5,
        xi_min_db=-20.0,
        g_min_db=-12.5,
        alpha_g=0.8,
        enable_eta=enable_eta,
        eta_beta_threshold=threshold,
        eta_slope=slope
    )


def test_file(noisy_path, clean_path, enable_eta, threshold):
    noisy, sr = librosa.load(noisy_path, sr=16000)
    clean, _ = librosa.load(clean_path, sr=16000)

    # 先對齊 noisy 和 clean
    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    denoiser = create_denoiser(enable_eta, threshold)
    enhanced, _ = denoiser.denoise(noisy, return_spp=True)

    # 再次對齊 enhanced 和 clean（denoiser 可能改變長度）
    final_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:final_len]
    clean = clean[:final_len]

    pesq_score = pesq(sr, clean, enhanced, 'wb')
    stoi_score = stoi(clean, enhanced, sr, extended=False)

    return pesq_score, stoi_score


def main():
    threshold = 2.0

    # test_wav 13個檔案（穩定噪聲）
    test_wav_files = [
        ('test_wav/wav/clean.wav', 'test_wav/wav/clean.wav', 'clean'),
        ('test_wav/wav/babble_0dB.wav', 'test_wav/wav/clean.wav', 'babble_0dB'),
        ('test_wav/wav/babble_5dB.wav', 'test_wav/wav/clean.wav', 'babble_5dB'),
        ('test_wav/wav/babble_10dB.wav', 'test_wav/wav/clean.wav', 'babble_10dB'),
        ('test_wav/wav/babble_15dB.wav', 'test_wav/wav/clean.wav', 'babble_15dB'),
        ('test_wav/wav/car_0dB.wav', 'test_wav/wav/clean.wav', 'car_0dB'),
        ('test_wav/wav/car_5dB.wav', 'test_wav/wav/clean.wav', 'car_5dB'),
        ('test_wav/wav/car_10dB.wav', 'test_wav/wav/clean.wav', 'car_10dB'),
        ('test_wav/wav/car_15dB.wav', 'test_wav/wav/clean.wav', 'car_15dB'),
        ('test_wav/wav/street_0dB.wav', 'test_wav/wav/clean.wav', 'street_0dB'),
        ('test_wav/wav/street_5dB.wav', 'test_wav/wav/clean.wav', 'street_5dB'),
        ('test_wav/wav/street_10dB.wav', 'test_wav/wav/clean.wav', 'street_10dB'),
        ('test_wav/wav/street_15dB.wav', 'test_wav/wav/clean.wav', 'street_15dB'),
    ]

    # VCTK 檔案
    vctk_base = '../VCTK_DEMAND_testset'
    vctk_files = []
    if os.path.exists(vctk_base):
        noisy_dir = os.path.join(vctk_base, 'noisy')
        clean_dir = os.path.join(vctk_base, 'clean')
        if os.path.exists(noisy_dir) and os.path.exists(clean_dir):
            for f in sorted(os.listdir(noisy_dir)):  # 測試全部
                if f.endswith('.wav'):
                    vctk_files.append((
                        os.path.join(noisy_dir, f),
                        os.path.join(clean_dir, f),
                        f'VCTK_{f}'
                    ))

    print("="*80)
    print(f"Eta 比較測試 (threshold={threshold})")
    print("="*80)

    # 測試 test_wav
    print("\n### test_wav 數據集 ###")
    print(f"{'File':<20} | {'eta=false':>20} | {'eta=true':>20} | {'Diff':>12}")
    print(f"{'':20} | {'PESQ':>9} {'STOI':>9} | {'PESQ':>9} {'STOI':>9} | {'ΔPESQ':>12}")
    print("-"*80)

    test_wav_results = []
    for noisy_path, clean_path, name in test_wav_files:
        if not os.path.exists(noisy_path):
            continue

        pesq_off, stoi_off = test_file(noisy_path, clean_path, False, threshold)
        pesq_on, stoi_on = test_file(noisy_path, clean_path, True, threshold)
        diff = pesq_on - pesq_off

        test_wav_results.append({
            'name': name,
            'pesq_off': pesq_off, 'stoi_off': stoi_off,
            'pesq_on': pesq_on, 'stoi_on': stoi_on,
            'diff': diff
        })

        print(f"{name:<20} | {pesq_off:>9.3f} {stoi_off:>9.3f} | {pesq_on:>9.3f} {stoi_on:>9.3f} | {diff:>+12.4f}")

    if test_wav_results:
        avg_pesq_off = np.mean([r['pesq_off'] for r in test_wav_results])
        avg_pesq_on = np.mean([r['pesq_on'] for r in test_wav_results])
        avg_stoi_off = np.mean([r['stoi_off'] for r in test_wav_results])
        avg_stoi_on = np.mean([r['stoi_on'] for r in test_wav_results])
        avg_diff = np.mean([r['diff'] for r in test_wav_results])

        print("-"*80)
        print(f"{'平均':<20} | {avg_pesq_off:>9.3f} {avg_stoi_off:>9.3f} | {avg_pesq_on:>9.3f} {avg_stoi_on:>9.3f} | {avg_diff:>+12.4f}")

    # 測試 VCTK
    if vctk_files:
        print("\n### VCTK 數據集 (前 20 個) ###")
        print(f"{'File':<20} | {'eta=false':>20} | {'eta=true':>20} | {'Diff':>12}")
        print("-"*80)

        vctk_results = []
        for noisy_path, clean_path, name in vctk_files:
            if not os.path.exists(noisy_path) or not os.path.exists(clean_path):
                continue

            try:
                pesq_off, stoi_off = test_file(noisy_path, clean_path, False, threshold)
                pesq_on, stoi_on = test_file(noisy_path, clean_path, True, threshold)
                diff = pesq_on - pesq_off

                vctk_results.append({
                    'name': name[:20],
                    'pesq_off': pesq_off, 'stoi_off': stoi_off,
                    'pesq_on': pesq_on, 'stoi_on': stoi_on,
                    'diff': diff
                })

                print(f"{name[:20]:<20} | {pesq_off:>9.3f} {stoi_off:>9.3f} | {pesq_on:>9.3f} {stoi_on:>9.3f} | {diff:>+12.4f}")
            except Exception as e:
                print(f"{name[:20]:<20} | Error: {e}")

        if vctk_results:
            avg_pesq_off = np.mean([r['pesq_off'] for r in vctk_results])
            avg_pesq_on = np.mean([r['pesq_on'] for r in vctk_results])
            avg_diff = np.mean([r['diff'] for r in vctk_results])

            print("-"*80)
            print(f"{'VCTK 平均':<20} | {avg_pesq_off:>9.3f} {'':>9} | {avg_pesq_on:>9.3f} {'':>9} | {avg_diff:>+12.4f}")
    else:
        print("\n(VCTK 數據集未找到)")

    # 總結
    print("\n" + "="*80)
    print("結論")
    print("="*80)
    if test_wav_results:
        better = sum(1 for r in test_wav_results if r['diff'] > 0.001)
        worse = sum(1 for r in test_wav_results if r['diff'] < -0.001)
        same = len(test_wav_results) - better - worse
        print(f"test_wav: 更好 {better}, 更差 {worse}, 相同 {same}")
        print(f"          平均 ΔPESQ: {avg_diff:+.4f}")


if __name__ == "__main__":
    main()
