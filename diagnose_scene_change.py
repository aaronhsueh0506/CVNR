#!/usr/bin/env python3
"""
場景轉換診斷腳本

用法:
    python diagnose_scene_change.py <audio_file.wav>
    python diagnose_scene_change.py <audio_file.wav> --plot

診斷項目:
1. Beta 值分布 - 確認是否有超過閾值
2. Eta 觸發次數 - 確認 eta 是否有被觸發
3. 噪聲估計變化 - 確認觸發後噪聲是否加速更新
"""

import numpy as np
import librosa
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.frame_processor import FrameProcessor
from core.noise_estimators import McraNoiseEstimator


def diagnose_eta(audio_path, threshold=10.0, plot=False):
    """診斷 eta 場景轉換偵測"""

    print(f"\n{'='*70}")
    print(f"場景轉換診斷: {os.path.basename(audio_path)}")
    print(f"{'='*70}")

    # 載入音頻
    audio, sr = librosa.load(audio_path, sr=16000)
    duration = len(audio) / sr
    print(f"時長: {duration:.2f} 秒, 採樣率: {sr} Hz")

    # 幀處理
    processor = FrameProcessor(
        sample_rate=sr,
        frame_size_ms=20,
        frame_shift_ms=10,
        fft_size=512,
        window_type='hanning'
    )

    magnitudes, _, _ = processor.process_signal(audio)
    n_frames = len(magnitudes)
    print(f"總幀數: {n_frames}")

    # 計算每幀能量和 beta
    frame_energies = np.sum(magnitudes ** 2, axis=1)

    # 模擬 eta 計算
    energy_smooth = frame_energies[0]
    prev_energy = frame_energies[0]

    betas = []
    etas = []
    energy_smooths = []

    for i in range(1, n_frames):
        # 平滑能量
        energy_smooth = 0.7 * energy_smooth + 0.3 * frame_energies[i]
        energy_smooths.append(energy_smooth)

        # 計算 beta
        beta = energy_smooth / (prev_energy + 1e-10)
        betas.append(beta)
        prev_energy = energy_smooth

        # 計算 eta
        if beta > threshold:
            etas.append(0.1)
        else:
            etas.append(1.0)

    betas = np.array(betas)
    etas = np.array(etas)
    energy_smooths = np.array(energy_smooths)

    # 統計
    print(f"\n--- Beta 統計 (閾值={threshold}) ---")
    print(f"  Min:  {np.min(betas):.4f}")
    print(f"  Max:  {np.max(betas):.4f}")
    print(f"  Mean: {np.mean(betas):.4f}")
    print(f"  Std:  {np.std(betas):.4f}")

    # 觸發統計
    trigger_count = np.sum(betas > threshold)
    trigger_frames = np.where(betas > threshold)[0]

    print(f"\n--- Eta 觸發統計 ---")
    print(f"  觸發次數: {trigger_count} / {len(betas)} 幀")
    print(f"  觸發率:   {100*trigger_count/len(betas):.2f}%")

    if trigger_count > 0:
        print(f"\n--- 觸發位置 (前 10 個) ---")
        for i, frame_idx in enumerate(trigger_frames[:10]):
            time_sec = (frame_idx + 1) * 0.01  # 10ms per frame
            print(f"  幀 {frame_idx+1:4d} ({time_sec:5.2f}s): beta={betas[frame_idx]:.2f}")

        if len(trigger_frames) > 10:
            print(f"  ... 還有 {len(trigger_frames)-10} 個觸發點")
    else:
        print(f"\n  ⚠️  Beta 從未超過閾值 {threshold}")
        print(f"  建議: 降低 eta_beta_threshold (目前 max beta = {np.max(betas):.2f})")

    # 能量變化分析
    print(f"\n--- 能量變化分析 ---")
    energy_ratio = np.max(frame_energies) / (np.min(frame_energies) + 1e-10)
    print(f"  能量比 (max/min): {energy_ratio:.2f}")

    # 找出能量突變點
    energy_diff = np.diff(frame_energies)
    sudden_increase = np.where(energy_diff > np.mean(frame_energies))[0]
    print(f"  能量突增點: {len(sudden_increase)} 個")

    if len(sudden_increase) > 0:
        print(f"\n--- 能量突增位置 (前 5 個) ---")
        for i, idx in enumerate(sudden_increase[:5]):
            time_sec = idx * 0.01
            ratio = frame_energies[idx+1] / (frame_energies[idx] + 1e-10)
            print(f"  幀 {idx:4d} ({time_sec:5.2f}s): 能量增加 {ratio:.2f}x")

    # 問題診斷
    print(f"\n{'='*70}")
    print("診斷結論")
    print(f"{'='*70}")

    if trigger_count == 0:
        print("❌ Eta 從未觸發")
        print("\n可能原因:")
        print(f"  1. 場景變化不夠劇烈 (max beta={np.max(betas):.2f} < threshold={threshold})")
        print(f"  2. 能量平滑 (0.7/0.3) 過度平滑了突變")
        print("\n建議:")
        suggested_threshold = np.percentile(betas, 99)
        print(f"  - 降低 eta_beta_threshold 到 {suggested_threshold:.1f} (99th percentile)")
        print(f"  - 或調整平滑係數 (目前 0.7/0.3)")
    elif trigger_count < 5:
        print(f"⚠️  Eta 觸發次數很少 ({trigger_count} 次)")
        print("  這可能是正常的，取決於場景變化的頻率")
    else:
        print(f"✓ Eta 正常觸發 ({trigger_count} 次)")

    # 繪圖
    if plot:
        try:
            import matplotlib.pyplot as plt

            fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)

            time_axis = np.arange(len(frame_energies)) * 0.01

            # 1. 原始能量
            axes[0].plot(time_axis, frame_energies, 'b-', linewidth=0.5)
            axes[0].set_ylabel('Frame Energy')
            axes[0].set_title('Energy & Beta Analysis')
            axes[0].grid(True, alpha=0.3)

            # 2. 平滑能量
            axes[1].plot(time_axis[1:], energy_smooths, 'g-', linewidth=0.5)
            axes[1].set_ylabel('Smoothed Energy')
            axes[1].grid(True, alpha=0.3)

            # 3. Beta 值
            axes[2].plot(time_axis[1:], betas, 'r-', linewidth=0.5)
            axes[2].axhline(y=threshold, color='k', linestyle='--', label=f'threshold={threshold}')
            axes[2].set_ylabel('Beta')
            axes[2].legend()
            axes[2].grid(True, alpha=0.3)

            # 4. Eta 值
            axes[3].plot(time_axis[1:], etas, 'm-', linewidth=1)
            axes[3].set_ylabel('Eta')
            axes[3].set_xlabel('Time (s)')
            axes[3].set_ylim(-0.1, 1.1)
            axes[3].grid(True, alpha=0.3)

            plt.tight_layout()

            output_path = audio_path.replace('.wav', '_eta_diagnosis.png')
            plt.savefig(output_path, dpi=150)
            print(f"\n📊 診斷圖已保存: {output_path}")
            plt.close()

        except ImportError:
            print("\n⚠️  matplotlib 未安裝，跳過繪圖")

    return {
        'betas': betas,
        'etas': etas,
        'trigger_count': trigger_count,
        'trigger_frames': trigger_frames,
        'max_beta': np.max(betas)
    }


def main():
    parser = argparse.ArgumentParser(description='場景轉換診斷')
    parser.add_argument('audio_file', help='音頻文件路徑')
    parser.add_argument('--threshold', type=float, default=10.0, help='Beta 閾值 (default: 10.0)')
    parser.add_argument('--plot', action='store_true', help='生成診斷圖')
    args = parser.parse_args()

    if not os.path.exists(args.audio_file):
        print(f"錯誤: 找不到文件 {args.audio_file}")
        sys.exit(1)

    diagnose_eta(args.audio_file, threshold=args.threshold, plot=args.plot)


if __name__ == "__main__":
    main()
