#!/usr/bin/env python3
"""
診斷 eta 觸發情況

分析 beta 值分布，看看為什麼 eta 沒有被觸發
"""

import numpy as np
import librosa
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.frame_processor import FrameProcessor


def analyze_energy_ratio(audio_path, sr=16000):
    """分析音頻的能量比分布"""
    audio, orig_sr = librosa.load(audio_path, sr=None)
    if orig_sr != sr:
        audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=sr)

    # 使用相同的幀處理器
    processor = FrameProcessor(
        sample_rate=sr,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        window_type='hanning'
    )

    magnitudes, _, _ = processor.process_signal(audio)

    # 計算每幀的能量
    frame_energies = np.sum(magnitudes ** 2, axis=1)

    # 計算平滑能量和 beta
    energy_smooth = frame_energies[0]
    prev_energy = frame_energies[0]
    betas = []

    for i in range(1, len(frame_energies)):
        energy_smooth = 0.7 * energy_smooth + 0.3 * frame_energies[i]
        beta = energy_smooth / (prev_energy + 1e-10)
        betas.append(beta)
        prev_energy = energy_smooth

    return np.array(betas), frame_energies


def main():
    print("=" * 80)
    print("Eta Beta 值診斷")
    print("=" * 80)

    # 測試幾個代表性文件
    test_files = [
        ('test_wav/wav/append_silence/babble_5dB_prepend.wav', 'babble_5dB'),
        ('test_wav/wav/append_silence/car_5dB_prepend.wav', 'car_5dB'),
        ('test_wav/wav/append_silence/street_5dB_prepend.wav', 'street_5dB'),
    ]

    # VCTK 文件
    vctk_noisy = '/Users/mingyu/Desktop/novatek/SE/VCTK_DEMAND_testset/noisy'
    if os.path.exists(vctk_noisy):
        vctk_files = sorted([f for f in os.listdir(vctk_noisy) if f.endswith('.wav')])[:3]
        for f in vctk_files:
            test_files.append((f"{vctk_noisy}/{f}", f"VCTK_{f[:20]}"))

    print(f"\n{'文件':<30} | {'Beta Max':>10} | {'Beta Min':>10} | {'Beta Mean':>10} | {'>10':>6} | {'>15':>6} | {'>20':>6}")
    print("-" * 100)

    for filepath, name in test_files:
        if not os.path.exists(filepath):
            print(f"{name:<30} | 文件不存在")
            continue

        betas, energies = analyze_energy_ratio(filepath)

        if len(betas) == 0:
            continue

        max_beta = np.max(betas)
        min_beta = np.min(betas)
        mean_beta = np.mean(betas)
        count_10 = np.sum(betas > 10)
        count_15 = np.sum(betas > 15)
        count_20 = np.sum(betas > 20)

        print(f"{name:<30} | {max_beta:>10.2f} | {min_beta:>10.4f} | {mean_beta:>10.4f} | {count_10:>6} | {count_15:>6} | {count_20:>6}")

    print("\n" + "=" * 80)
    print("分析結論：")
    print("  - Beta 值代表相鄰幀的平滑能量比")
    print("  - 如果 Max Beta < 10，則 eta 永遠不會被觸發")
    print("  - 正常語音的 beta 值通常在 0.9-1.1 之間")
    print("  - 只有突然的場景變化（如噪聲突增）才會有 beta >> 10")
    print("=" * 80)


if __name__ == "__main__":
    main()
