#!/usr/bin/env python3
"""
比較 V4 (知乎參數) vs V3-2 (baseline) 的 PESQ/STOI 分數

V4 參數:
- alpha_s: 0.7 (0.8 → 0.7)
- alpha_d: 0.0 (0.95 → 0.0) ⚠️
- L: 5 (120 → 5) ⚠️
- init: 30th percentile (20th → 30th)

V3-2 參數 (baseline):
- alpha_s: 0.8
- alpha_d: 0.95
- L: 120
- init: 20th percentile (舊版)
"""

import numpy as np
import librosa
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser

try:
    from pesq import pesq
    from pystoi import stoi
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    print("錯誤: 需要安裝 pesq 和 pystoi")
    print("pip install pesq pystoi")
    sys.exit(1)


def create_v32_baseline():
    """V3-2 baseline (舊參數)"""
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
        enable_eta=False
    )


def create_v4_zhihu():
    """V4 知乎參數 (激進)"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        noise_method='mcra',
        alpha_s=0.7,          # 0.8 → 0.7
        alpha_noise=0.0,      # 0.95 → 0.0 ⚠️
        alpha_p=0.2,
        L=5,                  # 120 → 5 ⚠️
        delta_db=5.0,
        num_init_frames=20,
        alpha_xi=0.92,
        q=0.5,
        xi_min_db=-20.0,
        g_min_db=-12.5,
        alpha_g=0.8,
        enable_eta=False
    )


def test_file(noisy_path, clean_path, denoiser_name, denoiser):
    """測試單個文件"""
    noisy, sr = librosa.load(noisy_path, sr=16000)
    clean, _ = librosa.load(clean_path, sr=16000)

    # 對齊長度
    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    # 降噪
    enhanced = denoiser.denoise(noisy)

    # 再次對齊（denoiser 可能改變長度）
    final_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:final_len]
    clean = clean[:final_len]

    # 計算指標
    pesq_score = pesq(sr, clean, enhanced, 'wb')
    stoi_score = stoi(clean, enhanced, sr, extended=False)

    return pesq_score, stoi_score


def main():
    # 測試文件列表
    test_files = [
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

    print("=" * 80)
    print("V4 (知乎參數) vs V3-2 (Baseline) 比較測試")
    print("=" * 80)
    print()
    print("V4 關鍵參數:")
    print("  - alpha_s: 0.8 → 0.7 (更快響應)")
    print("  - alpha_d: 0.95 → 0.0 ⚠️ (純 SPP 控制)")
    print("  - L: 120 → 5 ⚠️ (50ms 極短窗口)")
    print("  - init: 20th → 30th percentile")
    print()

    # 表頭
    print(f"{'File':<20} | {'V3-2 Baseline':>20} | {'V4 Zhihu':>20} | {'Diff':>12}")
    print(f"{'':20} | {'PESQ':>9} {'STOI':>9} | {'PESQ':>9} {'STOI':>9} | {'ΔPESQ':>12}")
    print("-" * 80)

    v32_results = []
    v4_results = []

    for noisy_path, clean_path, name in test_files:
        if not os.path.exists(noisy_path):
            continue

        # 測試 V3-2 baseline
        denoiser_v32 = create_v32_baseline()
        pesq_v32, stoi_v32 = test_file(noisy_path, clean_path, "V3-2", denoiser_v32)

        # 測試 V4 zhihu
        denoiser_v4 = create_v4_zhihu()
        pesq_v4, stoi_v4 = test_file(noisy_path, clean_path, "V4", denoiser_v4)

        diff = pesq_v4 - pesq_v32

        v32_results.append({'name': name, 'pesq': pesq_v32, 'stoi': stoi_v32})
        v4_results.append({'name': name, 'pesq': pesq_v4, 'stoi': stoi_v4, 'diff': diff})

        # 顏色標記差異
        diff_sign = "+" if diff > 0 else ""
        print(f"{name:<20} | {pesq_v32:>9.3f} {stoi_v32:>9.3f} | {pesq_v4:>9.3f} {stoi_v4:>9.3f} | {diff_sign}{diff:>11.4f}")

    # 統計
    if v32_results and v4_results:
        avg_pesq_v32 = np.mean([r['pesq'] for r in v32_results])
        avg_stoi_v32 = np.mean([r['stoi'] for r in v32_results])
        avg_pesq_v4 = np.mean([r['pesq'] for r in v4_results])
        avg_stoi_v4 = np.mean([r['stoi'] for r in v4_results])
        avg_diff = np.mean([r['diff'] for r in v4_results])

        print("-" * 80)
        print(f"{'平均':<20} | {avg_pesq_v32:>9.3f} {avg_stoi_v32:>9.3f} | {avg_pesq_v4:>9.3f} {avg_stoi_v4:>9.3f} | {avg_diff:>+12.4f}")

        # 結論
        print()
        print("=" * 80)
        print("結論")
        print("=" * 80)

        better = sum(1 for r in v4_results if r['diff'] > 0.01)
        worse = sum(1 for r in v4_results if r['diff'] < -0.01)
        same = len(v4_results) - better - worse

        print(f"V4 vs V3-2: 更好 {better}, 更差 {worse}, 相同 {same}")
        print(f"平均 ΔPESQ: {avg_diff:+.4f}")
        print()

        if avg_diff < -0.1:
            print("⚠️ V4 分數顯著下降 (ΔPESQ < -0.1)")
            print("建議調整參數:")
            print("  - 保守: alpha_d=0.7, L=50")
            print("  - 折中: alpha_d=0.5, L=20")
            print("  - 僅改平滑: alpha_d=0.95, L=120 (只改 alpha_s=0.7)")
        elif avg_diff > 0.1:
            print("✓ V4 分數顯著提升 (ΔPESQ > +0.1)")
            print("知乎參數有效！")
        else:
            print("→ V4 分數變化不大 (-0.1 < ΔPESQ < +0.1)")
            print("知乎參數對此數據集影響有限")


if __name__ == "__main__":
    main()
