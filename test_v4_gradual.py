#!/usr/bin/env python3
"""
V4 參數逐步測試 - 分離每個參數的影響

測試配置:
1. V3-2 Baseline: alpha_s=0.8, alpha_d=0.95, L=120, init=20th
2. Only alpha_s: alpha_s=0.7, alpha_d=0.95, L=120, init=20th (僅改平滑因子)
3. alpha_s + init: alpha_s=0.7, alpha_d=0.95, L=120, init=30th
4. alpha_s + L: alpha_s=0.7, alpha_d=0.95, L=5, init=20th
5. alpha_s + alpha_d: alpha_s=0.7, alpha_d=0.0, L=120, init=20th
6. V4 Full (知乎): alpha_s=0.7, alpha_d=0.0, L=5, init=30th (全部修改)

目標: 找出導致性能下降的關鍵參數
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
except ImportError:
    print("錯誤: 需要安裝 pesq 和 pystoi")
    sys.exit(1)


def create_denoiser(alpha_s, alpha_d, L):
    """創建 denoiser (init percentile 在代碼中固定為 30th)"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        noise_method='mcra',
        alpha_s=alpha_s,
        alpha_noise=alpha_d,
        alpha_p=0.2,
        L=L,
        delta_db=5.0,
        num_init_frames=20,
        alpha_xi=0.92,
        q=0.5,
        xi_min_db=-20.0,
        g_min_db=-12.5,
        alpha_g=0.8,
        enable_eta=False
    )


def test_file(noisy_path, clean_path, denoiser):
    """測試單個文件"""
    noisy, sr = librosa.load(noisy_path, sr=16000)
    clean, _ = librosa.load(clean_path, sr=16000)

    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    enhanced = denoiser.denoise(noisy)

    final_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:final_len]
    clean = clean[:final_len]

    pesq_score = pesq(sr, clean, enhanced, 'wb')
    stoi_score = stoi(clean, enhanced, sr, extended=False)

    return pesq_score, stoi_score


def main():
    # 測試配置 (name, alpha_s, alpha_d, L, description)
    configs = [
        ('Baseline', 0.8, 0.95, 120, 'V3-2 原始參數'),
        ('Only_alpha_s', 0.7, 0.95, 120, '僅改 alpha_s'),
        ('alpha_s+L', 0.7, 0.95, 5, 'alpha_s + L'),
        ('alpha_s+alpha_d', 0.7, 0.0, 120, 'alpha_s + alpha_d'),
        ('V4_Full', 0.7, 0.0, 5, '知乎全部參數'),
    ]

    # 選擇代表性測試文件（減少測試時間）
    test_files = [
        ('test_wav/wav/babble_0dB.wav', 'test_wav/wav/clean.wav', 'babble_0dB'),
        ('test_wav/wav/babble_10dB.wav', 'test_wav/wav/clean.wav', 'babble_10dB'),
        ('test_wav/wav/car_0dB.wav', 'test_wav/wav/clean.wav', 'car_0dB'),
        ('test_wav/wav/car_10dB.wav', 'test_wav/wav/clean.wav', 'car_10dB'),
        ('test_wav/wav/car_15dB.wav', 'test_wav/wav/clean.wav', 'car_15dB'),
        ('test_wav/wav/street_0dB.wav', 'test_wav/wav/clean.wav', 'street_0dB'),
        ('test_wav/wav/street_10dB.wav', 'test_wav/wav/clean.wav', 'street_10dB'),
    ]

    print("=" * 100)
    print("V4 參數逐步測試 - 分離每個參數的影響")
    print("=" * 100)
    print()

    # 所有配置的結果
    all_results = {cfg[0]: [] for cfg in configs}

    for noisy_path, clean_path, name in test_files:
        if not os.path.exists(noisy_path):
            continue

        print(f"\n--- {name} ---")

        for cfg_name, alpha_s, alpha_d, L, desc in configs:
            denoiser = create_denoiser(alpha_s, alpha_d, L)
            pesq_score, stoi_score = test_file(noisy_path, clean_path, denoiser)

            all_results[cfg_name].append({
                'file': name,
                'pesq': pesq_score,
                'stoi': stoi_score
            })

            print(f"  {cfg_name:20}: PESQ={pesq_score:.3f}, STOI={stoi_score:.3f} | {desc}")

    # 匯總平均分數
    print()
    print("=" * 100)
    print("平均分數匯總")
    print("=" * 100)
    print()

    baseline_pesq = np.mean([r['pesq'] for r in all_results['Baseline']])
    baseline_stoi = np.mean([r['stoi'] for r in all_results['Baseline']])

    print(f"{'配置':20} | {'PESQ':>8} | {'STOI':>8} | {'ΔPESQ':>10} | {'說明':30}")
    print("-" * 100)

    for cfg_name, alpha_s, alpha_d, L, desc in configs:
        if not all_results[cfg_name]:
            continue

        avg_pesq = np.mean([r['pesq'] for r in all_results[cfg_name]])
        avg_stoi = np.mean([r['stoi'] for r in all_results[cfg_name]])
        delta_pesq = avg_pesq - baseline_pesq

        delta_sign = "+" if delta_pesq > 0 else ""
        print(f"{cfg_name:20} | {avg_pesq:>8.3f} | {avg_stoi:>8.3f} | {delta_sign}{delta_pesq:>9.4f} | {desc:30}")

    # 結論
    print()
    print("=" * 100)
    print("結論")
    print("=" * 100)

    only_alpha_s_delta = np.mean([r['pesq'] for r in all_results['Only_alpha_s']]) - baseline_pesq
    alpha_s_L_delta = np.mean([r['pesq'] for r in all_results['alpha_s+L']]) - baseline_pesq
    alpha_s_alpha_d_delta = np.mean([r['pesq'] for r in all_results['alpha_s+alpha_d']]) - baseline_pesq
    v4_full_delta = np.mean([r['pesq'] for r in all_results['V4_Full']]) - baseline_pesq

    print()
    print("參數影響分析:")
    print(f"  1. 僅改 alpha_s (0.8→0.7):     ΔPESQ = {only_alpha_s_delta:+.4f}")
    print(f"  2. alpha_s + L (120→5):        ΔPESQ = {alpha_s_L_delta:+.4f}")
    print(f"  3. alpha_s + alpha_d (0.95→0): ΔPESQ = {alpha_s_alpha_d_delta:+.4f}")
    print(f"  4. V4 全部 (知乎參數):         ΔPESQ = {v4_full_delta:+.4f}")
    print()

    # 判斷主要問題
    if abs(alpha_s_L_delta) > abs(alpha_s_alpha_d_delta):
        print("🔍 主要問題: **L=5 極短窗口**")
        print("   建議: 保持 L=120 或使用 L=50 折中")
    elif abs(alpha_s_alpha_d_delta) > abs(alpha_s_L_delta):
        print("🔍 主要問題: **alpha_d=0 純 SPP 控制**")
        print("   建議: 使用 alpha_d=0.5 或 alpha_d=0.7 折中")
    else:
        print("🔍 兩個參數都有問題，且複合效應放大錯誤")

    print()
    if v4_full_delta < -0.1:
        print("⚠️ 知乎參數不適合此數據集")
        print("建議使用 Only_alpha_s 配置 (僅改平滑因子)")
    elif v4_full_delta > 0.05:
        print("✓ 知乎參數有效")
    else:
        print("→ 知乎參數影響有限")


if __name__ == "__main__":
    main()
