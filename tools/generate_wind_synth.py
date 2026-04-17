#!/usr/bin/env python3
"""
Generate synthesized wind noise dataset: clean VCTK + filtered noise at controlled SNR.

Wind model (simplified but perceptually reasonable):
  - Pink noise (1/f power) as base
  - Low-pass filter at ~800 Hz (steep, mimics wind energy concentration)
  - Slow 0.5–4Hz envelope modulation (gust / buffeting)
  - Optional short bursts for "buffeting" severity

Outputs:
  output_dir/clean/<name>.wav          — VCTK clean reference
  output_dir/noisy/<name>_snrXX.wav   — clean + wind at SNR=XX dB
  output_dir/wind_only/<name>_snrXX.wav — wind noise alone
  output_dir/manifest.csv              — mapping file

Usage:
  python3 tools/generate_wind_synth.py \\
      --clean-dir /path/to/VCTK_DEMAND_testset/clean_testset_wav \\
      --output-dir wind_synth \\
      --n-files 10 --snrs 10 0 -5
"""

import argparse
import csv
import glob
import os
import random
import sys

import numpy as np
import librosa
import soundfile as sf
from pathlib import Path

try:
    from scipy.signal import butter, sosfilt
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False


def pink_noise(n, rng):
    """Generate pink noise via simple 1/f shaping in frequency domain."""
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, d=1.0)
    # 1/sqrt(f) amplitude → 1/f power
    scale = 1.0 / np.sqrt(np.maximum(freqs * n, 1.0))
    scale[0] = 0
    return np.fft.irfft(X * scale, n=n)


def wind_noise(duration_s, sr, rng, lowpass_hz=800.0, env_hz=2.0, burstiness=0.0):
    """Synthesize wind-like noise."""
    n = int(duration_s * sr)
    base = pink_noise(n, rng)

    # Low-pass via butter SOS
    if SCIPY_OK:
        sos = butter(4, lowpass_hz, btype='lowpass', fs=sr, output='sos')
        filtered = sosfilt(sos, base)
    else:
        # Fallback：FFT truncation
        X = np.fft.rfft(base)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        mask = np.exp(-(freqs / lowpass_hz) ** 4)  # soft cutoff
        filtered = np.fft.irfft(X * mask, n=n)

    # Slow amplitude envelope (0.5–4Hz modulation)
    t = np.arange(n) / sr
    # 疊多個低頻正弦 + noise modulation
    env = (1.0 + 0.6 * np.sin(2 * np.pi * 0.8 * t + rng.uniform(0, 2 * np.pi))
              + 0.4 * np.sin(2 * np.pi * env_hz * t + rng.uniform(0, 2 * np.pi)))
    env = np.maximum(env, 0.1)
    filtered = filtered * env

    # Optional bursts（buffeting）
    if burstiness > 0:
        n_bursts = int(duration_s * burstiness)
        for _ in range(n_bursts):
            start = rng.integers(0, max(1, n - 800))
            length = rng.integers(int(0.01 * sr), int(0.05 * sr))
            amp = rng.uniform(2.0, 5.0)
            filtered[start:start + length] += amp * pink_noise(length, rng)

    # Normalize to unit RMS
    rms = np.sqrt(np.mean(filtered ** 2) + 1e-20)
    if rms > 0:
        filtered /= rms
    return filtered.astype(np.float32)


def mix_at_snr(clean, noise, snr_db):
    """Mix clean + noise at target SNR (dB)."""
    # Align lengths
    n = min(len(clean), len(noise))
    clean = clean[:n]
    noise = noise[:n]
    p_clean = np.mean(clean ** 2) + 1e-20
    p_noise = np.mean(noise ** 2) + 1e-20
    # 調整 noise 讓 SNR = 10*log10(p_clean / p_noise_new)
    target_p_noise = p_clean / (10 ** (snr_db / 10))
    scale = np.sqrt(target_p_noise / p_noise)
    noise_scaled = noise * scale
    noisy = clean + noise_scaled
    # 避免 clip
    peak = np.max(np.abs(noisy))
    if peak > 0.99:
        clean = clean / peak * 0.99
        noise_scaled = noise_scaled / peak * 0.99
        noisy = clean + noise_scaled
    return noisy.astype(np.float32), noise_scaled.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean-dir', required=True, help='VCTK clean_testset_wav dir')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--n-files', type=int, default=10)
    ap.add_argument('--snrs', type=int, nargs='+', default=[10, 0, -5])
    ap.add_argument('--sr', type=int, default=16000)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    out = Path(args.output_dir)
    (out / 'clean').mkdir(parents=True, exist_ok=True)
    (out / 'noisy').mkdir(parents=True, exist_ok=True)
    (out / 'wind_only').mkdir(parents=True, exist_ok=True)

    clean_files = sorted(glob.glob(str(Path(args.clean_dir) / '*.wav')))
    rng = np.random.default_rng(args.seed)
    idx = rng.choice(len(clean_files), size=args.n_files, replace=False)
    picks = [clean_files[i] for i in sorted(idx)]

    manifest_rows = []

    for i, src in enumerate(picks):
        name = Path(src).stem
        clean, orig_sr = librosa.load(src, sr=None)
        if orig_sr != args.sr:
            clean = librosa.resample(clean, orig_sr=orig_sr, target_sr=args.sr)
        clean = clean.astype(np.float32)

        # Save clean reference
        sf.write(str(out / 'clean' / f'{name}.wav'), clean, args.sr)

        for snr_db in args.snrs:
            # For lower SNR, add more burstiness
            burstiness = max(0.0, (0 - snr_db) * 2.0)  # snr=0 → 0, snr=-5 → 10
            noise = wind_noise(
                duration_s=len(clean) / args.sr,
                sr=args.sr,
                rng=rng,
                lowpass_hz=rng.uniform(600, 900),
                env_hz=rng.uniform(1.0, 3.0),
                burstiness=burstiness,
            )
            noisy, noise_scaled = mix_at_snr(clean, noise, snr_db)
            snr_tag = f'snr{snr_db:+d}'.replace('+', 'p').replace('-', 'n')
            noisy_name = f'{name}_{snr_tag}.wav'
            sf.write(str(out / 'noisy' / noisy_name), noisy, args.sr)
            sf.write(str(out / 'wind_only' / noisy_name), noise_scaled, args.sr)
            manifest_rows.append({
                'noisy_file': noisy_name,
                'clean_file': f'{name}.wav',
                'snr_db': snr_db,
                'burstiness': burstiness,
            })
        print(f"  [{i+1}/{len(picks)}] {name}  snrs={args.snrs}")

    # Manifest
    with open(out / 'manifest.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['noisy_file', 'clean_file', 'snr_db', 'burstiness'])
        w.writeheader()
        w.writerows(manifest_rows)

    print(f"完成: {len(manifest_rows)} 組 noisy 在 {out / 'noisy'}")


if __name__ == '__main__':
    main()
