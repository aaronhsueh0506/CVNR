#!/usr/bin/env python3
"""
比較 eta=True vs eta=False 的 SPP 差異

用法:
    python compare_spp_eta.py <audio_file.wav>
"""

import numpy as np
import librosa
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser


def compare_spp(audio_path, threshold=2.0):
    """比較 eta=True vs eta=False 的 SPP"""

    print(f"\n{'='*70}")
    print(f"SPP Eta 對比測試: {os.path.basename(audio_path)}")
    print(f"{'='*70}")
    print(f"Threshold: {threshold}")

    # 載入音頻
    audio, sr = librosa.load(audio_path, sr=16000)
    print(f"時長: {len(audio)/sr:.2f} 秒, 採樣率: {sr} Hz")

    # 創建兩個 denoiser - 一個開 eta，一個關
    common_params = {
        'sample_rate': sr,
        'frame_size_ms': 20,
        'frame_shift_ms': 10,
        'fft_size': 512,
        'noise_method': 'mcra',
        'alpha_s': 0.8,
        'alpha_noise': 0.95,
        'alpha_p': 0.2,
        'L': 120,
        'delta_db': 5.0,
        'num_init_frames': 20,
        'eta_slope': 20.0,
    }

    # eta = False
    print("\n處理 eta=False...")
    denoiser_off = MmseLsaDenoiser(
        **common_params,
        enable_eta=False,
        eta_beta_threshold=threshold
    )
    _, spp_off = denoiser_off.denoise(audio, return_spp=True)

    # eta = True
    print("處理 eta=True...")
    denoiser_on = MmseLsaDenoiser(
        **common_params,
        enable_eta=True,
        eta_beta_threshold=threshold
    )
    _, spp_on = denoiser_on.denoise(audio, return_spp=True)

    # 比較
    diff = spp_on - spp_off

    print(f"\n--- SPP 統計 ---")
    print(f"  {'':15} | {'eta=False':>12} | {'eta=True':>12} | {'差異':>12}")
    print(f"  {'-'*55}")
    print(f"  {'Mean':15} | {np.mean(spp_off):>12.6f} | {np.mean(spp_on):>12.6f} | {np.mean(diff):>+12.6f}")
    print(f"  {'Max':15} | {np.max(spp_off):>12.6f} | {np.max(spp_on):>12.6f} | {np.max(diff):>+12.6f}")
    print(f"  {'Min':15} | {np.min(spp_off):>12.6f} | {np.min(spp_on):>12.6f} | {np.min(diff):>+12.6f}")
    print(f"  {'Std':15} | {np.std(spp_off):>12.6f} | {np.std(spp_on):>12.6f} | {np.std(diff):>+12.6f}")

    # 找出差異最大的位置
    abs_diff = np.abs(diff)
    max_idx = np.unravel_index(np.argmax(abs_diff), diff.shape)
    max_diff_time = max_idx[0] * 0.01  # 10ms per frame
    max_diff_freq = max_idx[1] * (sr/2) / diff.shape[1]  # Hz

    print(f"\n--- 最大差異位置 ---")
    print(f"  幀 {max_idx[0]} ({max_diff_time:.2f}s), 頻率 bin {max_idx[1]} (~{max_diff_freq:.0f}Hz)")
    print(f"  差異: {diff[max_idx]:+.6f}")

    # 統計有顯著差異的像素
    significant = np.sum(np.abs(diff) > 0.01)
    total = diff.size

    print(f"\n--- 結論 ---")
    if significant == 0:
        print(f"  ⚠️  SPP 沒有顯著變化 (|diff| > 0.01 的像素: 0)")
        print(f"  可能原因:")
        print(f"    1. Eta 從未觸發 (beta 沒超過閾值 {threshold})")
        print(f"    2. 觸發後影響太小")
    else:
        print(f"  ✓ SPP 有變化 (|diff| > 0.01 的像素: {significant}/{total} = {100*significant/total:.2f}%)")

    # 繪圖
    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # SPP eta=False
        im1 = axes[0, 0].imshow(spp_off.T, aspect='auto', origin='lower',
                                 cmap='inferno', vmin=0, vmax=1)
        axes[0, 0].set_title('SPP: eta=False')
        axes[0, 0].set_ylabel('Frequency Bin')
        plt.colorbar(im1, ax=axes[0, 0])

        # SPP eta=True
        im2 = axes[0, 1].imshow(spp_on.T, aspect='auto', origin='lower',
                                 cmap='inferno', vmin=0, vmax=1)
        axes[0, 1].set_title('SPP: eta=True')
        axes[0, 1].set_ylabel('Frequency Bin')
        plt.colorbar(im2, ax=axes[0, 1])

        # 差異圖
        im3 = axes[1, 0].imshow(diff.T, aspect='auto', origin='lower',
                                 cmap='RdBu_r', vmin=-0.2, vmax=0.2)
        axes[1, 0].set_title('Difference (eta=True - eta=False)')
        axes[1, 0].set_xlabel('Frame')
        axes[1, 0].set_ylabel('Frequency Bin')
        plt.colorbar(im3, ax=axes[1, 0], label='SPP diff')

        # 差異絕對值
        im4 = axes[1, 1].imshow(np.abs(diff).T, aspect='auto', origin='lower',
                                 cmap='hot', vmin=0, vmax=0.2)
        axes[1, 1].set_title('Absolute Difference |eta=True - eta=False|')
        axes[1, 1].set_xlabel('Frame')
        axes[1, 1].set_ylabel('Frequency Bin')
        plt.colorbar(im4, ax=axes[1, 1], label='|SPP diff|')

        plt.tight_layout()

        output_path = audio_path.replace('.wav', '_spp_eta_comparison.png')
        plt.savefig(output_path, dpi=150)
        print(f"\n📊 對比圖已保存: {output_path}")
        plt.close()

    except ImportError:
        print("\n⚠️  matplotlib 未安裝，跳過繪圖")

    return {
        'spp_off': spp_off,
        'spp_on': spp_on,
        'diff': diff,
        'significant_pixels': significant
    }


def main():
    parser = argparse.ArgumentParser(description='SPP Eta 對比測試')
    parser.add_argument('audio_file', help='音頻文件路徑')
    parser.add_argument('--threshold', type=float, default=2.0, help='Beta 閾值')
    args = parser.parse_args()

    if not os.path.exists(args.audio_file):
        print(f"錯誤: 找不到文件 {args.audio_file}")
        sys.exit(1)

    compare_spp(args.audio_file, threshold=args.threshold)


if __name__ == "__main__":
    main()
