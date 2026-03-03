#!/usr/bin/env python3
"""
噪聲估計追蹤診斷

比較 eta=True vs eta=False 時的噪聲估計變化

用法:
    python diagnose_noise_tracking.py <audio_file.wav>
"""

import numpy as np
import librosa
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.frame_processor import FrameProcessor
from core.noise_estimators import McraNoiseEstimator


def track_noise_with_eta(audio_path, enable_eta, threshold=3.0):
    """追蹤噪聲估計變化"""

    audio, sr = librosa.load(audio_path, sr=16000)

    processor = FrameProcessor(
        sample_rate=sr,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        window_type='hanning'
    )

    magnitudes, _, _ = processor.process_signal(audio)
    n_frames = len(magnitudes)
    n_freqs = magnitudes.shape[1]

    # 創建噪聲估計器
    class MockConfig:
        def __init__(self):
            self.alpha_s = 0.8
            self.alpha_d = 0.95
            self.alpha_p = 0.2
            self.L = 120
            self.delta_db = 5.0
            self.num_init_frames = 20
            self.enable_eta = enable_eta
            self.eta_beta_threshold = threshold
            self.eta_slope = 20.0

    config = MockConfig()
    estimator = McraNoiseEstimator(
        alpha_s=config.alpha_s,
        alpha_d=config.alpha_d,
        alpha_p=config.alpha_p,
        L=config.L,
        delta_db=config.delta_db,
        num_init_frames=config.num_init_frames,
        enable_eta=config.enable_eta,
        eta_beta_threshold=config.eta_beta_threshold,
        eta_slope=config.eta_slope
    )

    # 初始化
    estimator.estimate(magnitudes)

    # 追蹤每幀的噪聲估計（取所有頻率的平均）
    noise_history = []

    for i in range(config.num_init_frames, n_frames):
        estimator.update(magnitudes[i])
        noise_psd = estimator.noise_psd.copy()
        noise_history.append(np.mean(noise_psd))

    return np.array(noise_history)


def main():
    parser = argparse.ArgumentParser(description='噪聲估計追蹤診斷')
    parser.add_argument('audio_file', help='音頻文件路徑')
    parser.add_argument('--threshold', type=float, default=3.0, help='Beta 閾值')
    args = parser.parse_args()

    if not os.path.exists(args.audio_file):
        print(f"錯誤: 找不到文件 {args.audio_file}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"噪聲估計追蹤診斷: {os.path.basename(args.audio_file)}")
    print(f"{'='*70}")
    print(f"Threshold: {args.threshold}")

    # 比較 eta=True vs eta=False
    noise_off = track_noise_with_eta(args.audio_file, enable_eta=False, threshold=args.threshold)
    noise_on = track_noise_with_eta(args.audio_file, enable_eta=True, threshold=args.threshold)

    # 計算差異
    diff = noise_on - noise_off

    print(f"\n--- 噪聲估計統計 ---")
    print(f"  {'':15} | {'eta=False':>12} | {'eta=True':>12} | {'差異':>12}")
    print(f"  {'-'*55}")
    print(f"  {'Mean':15} | {np.mean(noise_off):>12.6f} | {np.mean(noise_on):>12.6f} | {np.mean(diff):>+12.6f}")
    print(f"  {'Max':15} | {np.max(noise_off):>12.6f} | {np.max(noise_on):>12.6f} | {np.max(diff):>+12.6f}")
    print(f"  {'Min':15} | {np.min(noise_off):>12.6f} | {np.min(noise_on):>12.6f} | {np.min(diff):>+12.6f}")

    # 找出差異最大的位置
    max_diff_idx = np.argmax(np.abs(diff))
    max_diff_time = (max_diff_idx + 20) * 0.01  # 加上 init frames

    print(f"\n--- 最大差異位置 ---")
    print(f"  幀 {max_diff_idx + 20} ({max_diff_time:.2f}s): 差異 = {diff[max_diff_idx]:+.6f}")

    # 檢查是否有顯著差異
    significant_diff = np.sum(np.abs(diff) > 0.001)

    print(f"\n--- 結論 ---")
    if significant_diff == 0:
        print(f"  ⚠️  噪聲估計沒有顯著變化 (|diff| > 0.001 的幀數: 0)")
        print(f"  可能原因:")
        print(f"    1. Eta 觸發次數太少")
        print(f"    2. Eta 觸發後馬上恢復 (beta 只有一幀超過閾值)")
        print(f"    3. 閾值仍然太高")
    else:
        print(f"  ✓ 噪聲估計有變化 (|diff| > 0.001 的幀數: {significant_diff})")

    # 繪圖
    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

        time_axis = np.arange(len(noise_off)) * 0.01

        axes[0].plot(time_axis, noise_off, 'b-', linewidth=0.5, label='eta=False')
        axes[0].set_ylabel('Noise PSD (mean)')
        axes[0].set_title('Noise Estimation: eta=False')
        axes[0].grid(True, alpha=0.3)

        axes[1].plot(time_axis, noise_on, 'r-', linewidth=0.5, label='eta=True')
        axes[1].set_ylabel('Noise PSD (mean)')
        axes[1].set_title('Noise Estimation: eta=True')
        axes[1].grid(True, alpha=0.3)

        axes[2].plot(time_axis, diff, 'g-', linewidth=0.5)
        axes[2].axhline(y=0, color='k', linestyle='--', alpha=0.5)
        axes[2].set_ylabel('Difference')
        axes[2].set_xlabel('Time (s)')
        axes[2].set_title('Difference (eta=True - eta=False)')
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()

        output_path = args.audio_file.replace('.wav', '_noise_tracking.png')
        plt.savefig(output_path, dpi=150)
        print(f"\n📊 診斷圖已保存: {output_path}")
        plt.close()

    except ImportError:
        print("\n⚠️  matplotlib 未安裝，跳過繪圖")


if __name__ == "__main__":
    main()
