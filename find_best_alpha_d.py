#!/usr/bin/env python3
"""
尋找最佳 alpha_d 參數

測試範圍: alpha_d = 0.0, 0.3, 0.5, 0.7, 0.85 (baseline), 0.95

目標: 找出在 test_wav + VCTK 數據集上平均 PESQ 最高的 alpha_d
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
except ImportError:
    print("錯誤: 需要安裝 pesq 和 pystoi")
    sys.exit(1)


def create_denoiser(alpha_d):
    """創建指定 alpha_d 的 denoiser"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        noise_method='mcra',
        alpha_s=0.8,
        alpha_noise=alpha_d,
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


def test_file(noisy, clean, sr, denoiser):
    """測試音頻"""
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
    # 測試的 alpha_d 值
    alpha_d_values = [0.0, 0.3, 0.5, 0.7, 0.85, 0.95]

    # 測試文件 - test_wav (代表性樣本)
    test_wav_files = [
        ('test_wav/wav/babble_0dB.wav', 'test_wav/wav/clean.wav', 'babble_0dB'),
        ('test_wav/wav/babble_10dB.wav', 'test_wav/wav/clean.wav', 'babble_10dB'),
        ('test_wav/wav/car_0dB.wav', 'test_wav/wav/clean.wav', 'car_0dB'),
        ('test_wav/wav/car_5dB.wav', 'test_wav/wav/clean.wav', 'car_5dB'),
        ('test_wav/wav/car_10dB.wav', 'test_wav/wav/clean.wav', 'car_10dB'),
        ('test_wav/wav/car_15dB.wav', 'test_wav/wav/clean.wav', 'car_15dB'),
        ('test_wav/wav/street_0dB.wav', 'test_wav/wav/clean.wav', 'street_0dB'),
        ('test_wav/wav/street_10dB.wav', 'test_wav/wav/clean.wav', 'street_10dB'),
    ]

    # VCTK 文件
    vctk_files = []
    vctk_base = Path('../VCTK_DEMAND_testset')
    if vctk_base.exists():
        noisy_dir = vctk_base / 'noisy'
        clean_dir = vctk_base / 'clean'
        if noisy_dir.exists() and clean_dir.exists():
            # 選擇前 5 個
            for f in sorted(os.listdir(noisy_dir))[:5]:
                if f.endswith('.wav'):
                    vctk_files.append({
                        'noisy': str(noisy_dir / f),
                        'clean': str(clean_dir / f),
                        'name': f'VCTK_{f}'
                    })

    print("=" * 100)
    print("尋找最佳 alpha_d 參數")
    print("=" * 100)
    print()
    print(f"測試範圍: alpha_d = {alpha_d_values}")
    print(f"測試文件: {len(test_wav_files)} test_wav + {len(vctk_files)} VCTK = {len(test_wav_files) + len(vctk_files)} 總計")
    print()

    # 收集所有結果
    all_results = {alpha_d: [] for alpha_d in alpha_d_values}

    # 測試 test_wav
    print("### 測試 test_wav 數據集 ###\n")

    for noisy_path, clean_path, name in test_wav_files:
        if not os.path.exists(noisy_path):
            continue

        print(f"測試 {name}...", end=' ')

        noisy, sr = librosa.load(noisy_path, sr=16000)
        clean, _ = librosa.load(clean_path, sr=16000)

        file_results = {}
        for alpha_d in alpha_d_values:
            denoiser = create_denoiser(alpha_d)
            pesq_score, stoi_score = test_file(noisy, clean, sr, denoiser)

            all_results[alpha_d].append({
                'file': name,
                'pesq': pesq_score,
                'stoi': stoi_score
            })
            file_results[alpha_d] = pesq_score

        # 找出此文件最佳 alpha_d
        best_alpha_d = max(file_results.keys(), key=lambda x: file_results[x])
        print(f"最佳 alpha_d={best_alpha_d} (PESQ={file_results[best_alpha_d]:.3f})")

    # 測試 VCTK
    if vctk_files:
        print("\n### 測試 VCTK 數據集 ###\n")

        for file_info in vctk_files:
            print(f"測試 {file_info['name']}...", end=' ')

            noisy, sr = librosa.load(file_info['noisy'], sr=16000)
            clean, _ = librosa.load(file_info['clean'], sr=16000)

            file_results = {}
            for alpha_d in alpha_d_values:
                try:
                    denoiser = create_denoiser(alpha_d)
                    pesq_score, stoi_score = test_file(noisy, clean, sr, denoiser)

                    all_results[alpha_d].append({
                        'file': file_info['name'],
                        'pesq': pesq_score,
                        'stoi': stoi_score
                    })
                    file_results[alpha_d] = pesq_score
                except Exception as e:
                    print(f"Error with alpha_d={alpha_d}: {e}")
                    continue

            if file_results:
                best_alpha_d = max(file_results.keys(), key=lambda x: file_results[x])
                print(f"最佳 alpha_d={best_alpha_d} (PESQ={file_results[best_alpha_d]:.3f})")

    # 匯總結果
    print()
    print("=" * 100)
    print("平均分數匯總")
    print("=" * 100)
    print()

    # 計算每個 alpha_d 的平均分數
    summary = []
    for alpha_d in alpha_d_values:
        if not all_results[alpha_d]:
            continue

        avg_pesq = np.mean([r['pesq'] for r in all_results[alpha_d]])
        avg_stoi = np.mean([r['stoi'] for r in all_results[alpha_d]])

        summary.append({
            'alpha_d': alpha_d,
            'pesq': avg_pesq,
            'stoi': stoi_score,
            'count': len(all_results[alpha_d])
        })

    # 排序（PESQ 由高到低）
    summary.sort(key=lambda x: x['pesq'], reverse=True)

    # 找出 baseline (alpha_d=0.95)
    baseline_pesq = next((s['pesq'] for s in summary if s['alpha_d'] == 0.95), None)
    if baseline_pesq is None:
        baseline_pesq = next((s['pesq'] for s in summary if s['alpha_d'] == 0.85), 0)

    print(f"{'排名':4} | {'alpha_d':8} | {'PESQ':>8} | {'STOI':>8} | {'ΔPESQ':>10} | {'說明':30}")
    print("-" * 100)

    for i, s in enumerate(summary, 1):
        delta_pesq = s['pesq'] - baseline_pesq
        delta_sign = "+" if delta_pesq > 0 else ""

        marker = ""
        if s['alpha_d'] == 0.95 or s['alpha_d'] == 0.85:
            marker = "← Baseline"
        elif i == 1:
            marker = "★ 最佳"

        print(f"{i:4} | {s['alpha_d']:8.2f} | {s['pesq']:>8.3f} | {s['stoi']:>8.3f} | {delta_sign}{delta_pesq:>9.4f} | {marker:30}")

    # 結論
    print()
    print("=" * 100)
    print("結論")
    print("=" * 100)
    print()

    best = summary[0]
    print(f"🏆 最佳 alpha_d: {best['alpha_d']}")
    print(f"   平均 PESQ: {best['pesq']:.4f}")
    print(f"   相對 baseline ΔPESQ: {best['pesq'] - baseline_pesq:+.4f}")
    print()

    # 給出建議
    if best['alpha_d'] == 0.95 or best['alpha_d'] == 0.85:
        print("💡 建議: 保持 baseline 參數 (alpha_d=0.95)")
    elif best['alpha_d'] == 0.0:
        print("⚠️ 建議: alpha_d=0.0 在此數據集表現最佳，但風險較高")
        print("   需要在更多數據集上驗證穩定性")
    else:
        print(f"💡 建議: 使用 alpha_d={best['alpha_d']} 作為新的默認值")
        print("   平衡了性能和穩定性")

    # 分析趨勢
    print()
    print("📊 趨勢分析:")
    print(f"   alpha_d=0.0:  PESQ={next(s['pesq'] for s in summary if s['alpha_d'] == 0.0):.3f}")
    print(f"   alpha_d=0.5:  PESQ={next(s['pesq'] for s in summary if s['alpha_d'] == 0.5):.3f}")
    print(f"   alpha_d=0.95: PESQ={next((s['pesq'] for s in summary if s['alpha_d'] == 0.95), 0):.3f}")


if __name__ == "__main__":
    main()
