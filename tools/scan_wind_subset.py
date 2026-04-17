#!/usr/bin/env python3
"""
Scan VCTK/DEMAND noisy files to find wind-heavy ones (data-driven wind subset).

Uses WindDetector to score each file; outputs a list sorted by average wind_probability.
Top N files constitute the wind subset for V4 targeted validation.

Usage:
    python3 tools/scan_wind_subset.py \
        --noisy-dir /path/to/noisy \
        --top-n 80 \
        --output results/wind_subset.txt
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import numpy as np
import librosa
from pathlib import Path
from glob import glob

from core import FrameProcessor
from core.wind_detector import WindDetector


def scan_file(path, processor, detector):
    signal, sr = librosa.load(path, sr=16000)
    magnitudes, _, _ = processor.process_signal(signal)
    detector.reset()
    probs = []
    for i in range(magnitudes.shape[0]):
        info = detector.detect(magnitudes[i])
        probs.append(info['wind_probability'])
    if not probs:
        return 0.0
    arr = np.asarray(probs)
    # 取 80 百分位數：避免整段靜音/穩定噪聲壓低平均
    return float(np.percentile(arr, 80))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--noisy-dir', required=True)
    ap.add_argument('--top-n', type=int, default=80)
    ap.add_argument('--output', default='results/wind_subset.txt')
    ap.add_argument('--summary', default='results/wind_scores.csv')
    args = ap.parse_args()

    files = sorted(glob(str(Path(args.noisy_dir) / '*.wav')))
    print(f"掃描 {len(files)} 個檔案...")

    processor = FrameProcessor(sample_rate=16000, frame_size=512, frame_shift=256, fft_size=512)
    detector = WindDetector(sample_rate=16000, fft_size=512)

    scores = []
    for i, f in enumerate(files):
        s = scan_file(f, processor, detector)
        scores.append((os.path.basename(f), s))
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(files)}]")

    scores.sort(key=lambda x: x[1], reverse=True)

    os.makedirs(os.path.dirname(args.summary), exist_ok=True)
    with open(args.summary, 'w') as f:
        f.write("filename,wind_score_p80\n")
        for name, s in scores:
            f.write(f"{name},{s:.4f}\n")
    print(f"完整分數: {args.summary}")

    top = scores[:args.top_n]
    with open(args.output, 'w') as f:
        for name, _ in top:
            f.write(name + '\n')
    print(f"Top-{args.top_n} 風聲子集: {args.output}")
    print(f"  最高分 {top[0][0]}: {top[0][1]:.3f}")
    print(f"  最低分 {top[-1][0]}: {top[-1][1]:.3f}")


if __name__ == "__main__":
    main()
