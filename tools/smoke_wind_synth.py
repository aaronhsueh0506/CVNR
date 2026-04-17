#!/usr/bin/env python3
"""
Evaluate V4 variants on wind_synth dataset (has clean ground truth).
Measures PESQ, STOI, SI-SDR to see if the wind handler genuinely helps.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
import csv
import glob
import numpy as np
import librosa
import yaml
from pathlib import Path

from denoisers import OmlsaDenoiser, MmseLsaDenoiser
from regenerate_all import get_denoiser_params_from_config
from utils.metrics import calculate_pesq, calculate_stoi

SR = 16000


def si_sdr(reference, estimate):
    ref = reference - np.mean(reference)
    est = estimate - np.mean(estimate)
    alpha = np.dot(est, ref) / (np.dot(ref, ref) + 1e-20)
    e = est - alpha * ref
    return 10 * np.log10(np.sum((alpha * ref) ** 2) / (np.sum(e ** 2) + 1e-20) + 1e-20)


def build_omlsa(cfg):
    params = get_denoiser_params_from_config(cfg, SR, cfg['audio']['fft_size'])
    wh = cfg.get('wind_handler', {})
    params['enable_wind_handler'] = wh.get('enable', False)
    if 'detector' in wh:
        params['wind_detector_config'] = dict(wh['detector'])
    if 'freq_adaptive' in wh:
        params['freq_adaptive_config'] = dict(wh['freq_adaptive'])
    if 'transient_suppressor' in wh:
        ts = dict(wh['transient_suppressor'])
        params['enable_transient_suppressor'] = ts.pop('enable', False)
        params['transient_suppressor_config'] = ts
    return OmlsaDenoiser(**params)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--synth-dir', default='wind_synth')
    ap.add_argument('--config', default='config/v4_config.yaml')
    args = ap.parse_args()

    synth_dir = Path(args.synth_dir)
    manifest = list(csv.DictReader(open(synth_dir / 'manifest.csv')))

    cfg = yaml.safe_load(open(args.config))

    variants = []

    # V3-2 fixed
    p32 = get_denoiser_params_from_config(cfg, SR, cfg['audio']['fft_size'])
    variants.append(('V3-2 fixed', MmseLsaDenoiser(**p32)))

    # V4 full
    variants.append(('V4 full', build_omlsa(cfg)))

    # V4 FLAT + transient OFF
    cfg_flat = copy.deepcopy(cfg)
    for prof in ['g_min_profile_db', 'alpha_xi_profile', 'alpha_g_profile']:
        for band in cfg_flat['wind_handler']['freq_adaptive'][prof]:
            v = cfg_flat['wind_handler']['freq_adaptive'][prof][band][0]
            cfg_flat['wind_handler']['freq_adaptive'][prof][band] = [v, v, v]
    cfg_flat['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 FLAT + transient OFF', build_omlsa(cfg_flat)))

    # V4 relaxed + no transient
    cfg_relax = copy.deepcopy(cfg)
    cfg_relax['wind_handler']['freq_adaptive']['g_min_profile_db'] = {
        'band_0': [-15, -18, -25],
        'band_1': [-15, -16, -20],
        'band_2': [-15, -15, -16],
        'band_3': [-15, -15, -15],
    }
    cfg_relax['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 relaxed + transient OFF', build_omlsa(cfg_relax)))

    # V4 full but transient OFF
    cfg_ts_off = copy.deepcopy(cfg)
    cfg_ts_off['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 full (transient OFF)', build_omlsa(cfg_ts_off)))

    # Group by SNR
    by_snr = {}
    for row in manifest:
        by_snr.setdefault(int(row['snr_db']), []).append(row)

    for snr, rows in sorted(by_snr.items(), reverse=True):
        print(f"\n==== SNR = {snr:+d} dB  ({len(rows)} files) ====")
        print(f"{'variant':40s}  PESQ     STOI    SI-SDR")
        print('-' * 70)
        for name, den in variants:
            pesqs, stois, sdrs = [], [], []
            for r in rows:
                noisy_path = synth_dir / 'noisy' / r['noisy_file']
                clean_path = synth_dir / 'clean' / r['clean_file']
                noisy, _ = librosa.load(str(noisy_path), sr=SR)
                clean, _ = librosa.load(str(clean_path), sr=SR)
                enhanced = den.denoise(noisy)
                n = min(len(clean), len(enhanced))
                c, e = clean[:n], enhanced[:n]
                try:
                    p = calculate_pesq(c, e, SR)
                    s = calculate_stoi(c, e, SR)
                    sdr_val = si_sdr(c, e)
                    if p is not None and s is not None:
                        pesqs.append(p)
                        stois.append(s)
                        sdrs.append(sdr_val)
                except Exception:
                    pass
            if pesqs:
                print(f"{name:40s}  {np.mean(pesqs):.3f}   {np.mean(stois):.3f}   {np.mean(sdrs):+6.2f}")
            else:
                print(f"{name:40s}   N/A")


if __name__ == '__main__':
    main()
