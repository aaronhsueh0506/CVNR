#!/usr/bin/env python3
"""
ablate_nr_music.py — committed replacement for the ad-hoc fix_gain ablation.

Runs the V3-2 (OM-LSA) denoiser on music/noise test wavs across the strength presets
(mild / balanced / aggressive) plus a few candidate deltas, and for each writes:
  - the enhanced WAV (for listening),
  - a log-magnitude spectrogram PNG (musical noise = isolated speckle / vertical stripes),
  - a metrics row: musical_noise (utils.metrics.detect_musical_noise) + suppression_db.

⚠ musical_noise is a COARSE proxy (frame-to-frame spectral variance) — it conflates residual-noise
energy with tonal artifacts, so it can rank a gentle preset WORSE than an aggressive one. Judge by
EAR + spectrogram; use the number only as a sanity check. suppression_db (<0 = deeper) is the
depth gauge.

The candidate list includes `balanced_old_axi088` = the pre-fix balanced (alpha_xi 0.88) so the
2026-07 musical-noise fix (alpha_xi → 0.92) is directly visible/audible against `balanced`.

Usage:
  python tools/ablate_nr_music.py                         # defaults to the two fix_gain_*.wav
  python tools/ablate_nr_music.py --input path/to.wav ... # explicit inputs
  python tools/ablate_nr_music.py --output-dir results/ablate_nr
"""
import argparse
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')  # headless
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.audio_io import read_audio, write_audio        # noqa: E402
from utils.metrics import detect_musical_noise, suppression_db  # noqa: E402
from process_audio import load_config, build_v3_2_base_params   # noqa: E402
from core.nr_strength import apply_strength                # noqa: E402
from core.nr_modes import apply_mode                       # noqa: E402
from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser        # noqa: E402

SR = 16000
FRAME, HOP, FFT = 512, 256, 512

# (label, strength_base, delta_overrides). balanced = ear-locked anchor; balanced_old_axi088 is the
# pre-fix reference; mild_deep / aggressive_smooth are dialing candidates.
CANDIDATES = [
    # genuine pre-fix shipped balanced (alpha_xi 0.88, default asymmetric smoothing) — musical noise
    ('balanced_old', 'balanced', {'alpha_xi': 0.88, 'alpha_attack': 0.3, 'alpha_decay': 0.88}),
    # the shipped 4-preset ladder (values live in core/nr_strength.py; no deltas here)
    ('mild',       'mild',       {}),   # gentlest (unchanged C-mirror)
    ('moderate',   'moderate',   {}),   # NEW, between mild and balanced (g_min −25)
    ('balanced',   'balanced',   {}),   # ear-locked anchor = alpha_xi 0.92 + attack 0.4 / decay 0.92
    ('aggressive', 'aggressive', {}),   # deepest (= aggressive_smooth: alpha_g 0.85 / decay 0.88)
]

# params surfaced in the table (mirrors the user's ablation columns)
REPORT_KEYS = ['g_min_db', 'q', 'xi_min_db', 'alpha_xi', 'alpha_g', 'alpha_attack', 'alpha_decay']


def build_denoiser(base_params, strength, delta):
    """base params → strength overlay → full mode → candidate delta → MmseLsaDenoiser."""
    params = apply_strength(base_params, strength)
    params = apply_mode(params, 'full')
    params['mode'] = 'full'
    params.update(delta)
    return MmseLsaDenoiser(**params), params


def save_spectrogram(signal, title, path):
    """Log-magnitude STFT spectrogram (musical noise shows as isolated speckle / stripes)."""
    f = np.abs(np.array([
        np.fft.rfft(signal[i:i + FRAME] * np.hanning(FRAME))
        for i in range(0, max(len(signal) - FRAME, 1), HOP)
    ]).T)
    db = 20.0 * np.log10(f + 1e-6)
    plt.figure(figsize=(10, 4))
    plt.imshow(db, origin='lower', aspect='auto', cmap='magma',
               vmax=db.max(), vmin=db.max() - 80,
               extent=[0, len(signal) / SR, 0, SR / 2000.0])
    plt.xlabel('time (s)'); plt.ylabel('kHz'); plt.title(title)
    plt.colorbar(label='dB'); plt.tight_layout()
    plt.savefig(path, dpi=90); plt.close()


def run_one_input(wav_path, out_dir, config):
    audio, sr = read_audio(wav_path, target_sr=SR)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    stem = os.path.splitext(os.path.basename(wav_path))[0]
    base_params = build_v3_2_base_params(config, sr, FRAME, HOP, FFT)

    save_spectrogram(audio, f"{stem} — INPUT", os.path.join(out_dir, f"{stem}_00_input.png"))

    rows = []
    for i, (label, strength, delta) in enumerate(CANDIDATES, start=1):
        denoiser, params = build_denoiser(base_params, strength, delta)
        enhanced = denoiser.denoise(audio)

        mn = detect_musical_noise(enhanced, FRAME, HOP)
        sup = suppression_db(audio, enhanced)

        write_audio(os.path.join(out_dir, f"{stem}_{i:02d}_{label}.wav"), enhanced, sr)
        save_spectrogram(enhanced, f"{stem} — {label}  (MN={mn:.4f}, sup={sup:.2f}dB)",
                         os.path.join(out_dir, f"{stem}_{i:02d}_{label}.png"))

        row = {'input': stem, 'label': label, 'musical_noise': round(mn, 6),
               'suppression_db': round(sup, 2)}
        row.update({k: params.get(k) for k in REPORT_KEYS})
        rows.append(row)
    return rows


def print_table(rows):
    hdr = ['input', 'label', 'musical_noise', 'suppression_db'] + REPORT_KEYS
    widths = {h: max(len(h), *(len(str(r.get(h, ''))) for r in rows)) for h in hdr}
    print('  '.join(h.ljust(widths[h]) for h in hdr))
    print('  '.join('-' * widths[h] for h in hdr))
    for r in rows:
        print('  '.join(str(r.get(h, '')).ljust(widths[h]) for h in hdr))


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', nargs='+',
                    default=[os.path.join(here, 'test_wav', 'music', 'fix_gain_music.wav'),
                             os.path.join(here, 'test_wav', 'music', 'fix_gain_noise.wav')],
                    help='input wav(s) (default: test_wav/music/fix_gain_{music,noise}.wav)')
    ap.add_argument('--output-dir', default=os.path.join(here, 'results', 'ablate_nr'))
    ap.add_argument('--config-dir', default=os.path.join(here, 'config'))
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    config = load_config(os.path.join(args.config_dir, 'v3_2_config.yaml'))

    all_rows = []
    for wav in args.input:
        if not os.path.exists(wav):
            print(f"  ⚠ skip (not found): {wav}")
            continue
        print(f"\nInput: {wav}")
        rows = run_one_input(wav, args.output_dir, config)
        print_table(rows)
        all_rows.extend(rows)

    out_json = os.path.join(args.output_dir, 'ablate_nr_results.json')
    with open(out_json, 'w') as fh:
        json.dump(all_rows, fh, indent=2)
    print(f"\nSaved: {out_json}")
    print(f"Wavs + spectrograms in: {args.output_dir}")


if __name__ == '__main__':
    main()
