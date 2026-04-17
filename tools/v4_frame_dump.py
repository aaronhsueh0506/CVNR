#!/usr/bin/env python3
"""
V4 per-frame diagnostic dumper.

Runs V4 OmlsaDenoiser on each file in --input-dir with diag_sink, saves:
- dumps/<tag>/<filename>.npz  — full per-frame arrays
- dumps/<tag>/summary.csv     — long-form CSV with file + frame columns

Usage:
    python3 tools/v4_frame_dump.py \\
        --input-dir /path/to/noisy_subset \\
        --config config/v4_config.yaml \\
        --output-dir dumps/vctk_diag \\
        --tag vctk_diag
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import csv
import glob
import numpy as np
import librosa
import yaml
from pathlib import Path

from denoisers import OmlsaDenoiser
from regenerate_all import get_denoiser_params_from_config


DIAG_KEYS = [
    'frame_idx', 'time_sec', 'is_init',
    'wind_prob', 'wind_severity',
    'feat_ler', 'feat_tilt_db', 'feat_zcr',
    'hangover_active',
    'g_min_db_b0', 'g_min_db_b1', 'g_min_db_b2', 'g_min_db_b3',
    'alpha_xi_b0', 'alpha_xi_b3',
    'noise_psd_low_db', 'noise_psd_mid_db', 'noise_psd_high_db',
    'spp_mean', 'spp_low_mean', 'spp_mid_mean',
    'gain_mean', 'gain_low_mean', 'gain_mid_mean', 'gain_high_mean',
    'input_rms_db', 'output_rms_db', 'suppression_db',
]


def build_denoiser(config_path):
    cfg = yaml.safe_load(open(config_path))
    params = get_denoiser_params_from_config(cfg, 16000, cfg['audio']['fft_size'])
    wh = cfg.get('wind_handler', {})
    params['enable_wind_handler'] = wh.get('enable', False)
    if 'detector' in wh:
        params['wind_detector_config'] = wh['detector']
    if 'freq_adaptive' in wh:
        params['freq_adaptive_config'] = wh['freq_adaptive']
    if 'transient_suppressor' in wh:
        ts = dict(wh['transient_suppressor'])
        params['enable_transient_suppressor'] = ts.pop('enable', False)
        params['transient_suppressor_config'] = ts
    return OmlsaDenoiser(**params)


def process_file(denoiser, wav_path, out_npz, sr=16000):
    sig, orig_sr = librosa.load(wav_path, sr=None)
    if orig_sr != sr:
        sig = librosa.resample(sig, orig_sr=orig_sr, target_sr=sr)
    diag = []
    _ = denoiser.denoise(sig, diag_sink=diag)
    # 轉成 np arrays 存
    cols = {}
    for k in DIAG_KEYS:
        vals = [d.get(k) for d in diag]
        if k == 'wind_severity':
            vals = np.array(vals, dtype='U8')
        else:
            vals = np.asarray(vals, dtype=np.float64)
        cols[k] = vals
    np.savez_compressed(out_npz, **cols)
    return diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input-dir', required=True)
    ap.add_argument('--config', default='config/v4_config.yaml')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--tag', default=None, help='CSV tag; 預設 = output-dir basename')
    ap.add_argument('--max-files', type=int, default=None)
    ap.add_argument('--file-list', default=None,
                    help='optional; file containing wav names (one per line) to restrict input')
    args = ap.parse_args()

    tag = args.tag or Path(args.output_dir).name
    os.makedirs(args.output_dir, exist_ok=True)

    # 收集要處理的檔案
    all_files = sorted(glob.glob(str(Path(args.input_dir) / '*.wav')))
    if args.file_list:
        allowed = set(line.strip() for line in open(args.file_list) if line.strip())
        all_files = [f for f in all_files if os.path.basename(f) in allowed]
    if args.max_files:
        all_files = all_files[:args.max_files]

    print(f"[{tag}] 處理 {len(all_files)} 檔 → {args.output_dir}")

    denoiser = build_denoiser(args.config)

    summary_path = Path(args.output_dir) / 'summary.csv'
    with open(summary_path, 'w', newline='') as fcsv:
        writer = csv.writer(fcsv)
        writer.writerow(['file'] + DIAG_KEYS)

        for i, wav in enumerate(all_files):
            name = os.path.basename(wav).replace('.wav', '')
            out_npz = Path(args.output_dir) / f'{name}.npz'
            diag = process_file(denoiser, wav, out_npz)
            for d in diag:
                row = [name] + [d.get(k) for k in DIAG_KEYS]
                writer.writerow(row)
            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(all_files)}] {name}")

    print(f"完成: {args.output_dir}/*.npz + summary.csv")


if __name__ == '__main__':
    main()
