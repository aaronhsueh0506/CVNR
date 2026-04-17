#!/usr/bin/env python3
"""
Quick smoke: turn off different V4 components one at a time on a VCTK subset
and report PESQ/STOI. Isolates which component causes VCTK regression.

Usage:
  python3 tools/smoke_components.py --dataset-dir /path/VCTK_DEMAND_testset --subset 80
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import copy
import numpy as np
import librosa
import soundfile as sf
import yaml
from pathlib import Path
from glob import glob

from denoisers import OmlsaDenoiser, MmseLsaDenoiser
from regenerate_all import get_denoiser_params_from_config
from utils.metrics import calculate_pesq, calculate_stoi

EVAL_SR = 16000


def build_omlsa(cfg_dict, overrides=None):
    params = get_denoiser_params_from_config(cfg_dict, 16000, cfg_dict['audio']['fft_size'])
    wh = cfg_dict.get('wind_handler', {})
    params['enable_wind_handler'] = wh.get('enable', False)
    if 'detector' in wh:
        params['wind_detector_config'] = dict(wh['detector'])
    if 'freq_adaptive' in wh:
        params['freq_adaptive_config'] = dict(wh['freq_adaptive'])
    if 'transient_suppressor' in wh:
        ts = dict(wh['transient_suppressor'])
        params['enable_transient_suppressor'] = ts.pop('enable', False)
        params['transient_suppressor_config'] = ts
    if overrides:
        for k, v in overrides.items():
            params[k] = v
    return OmlsaDenoiser(**params)


def run_variant(name, denoiser, files, clean_dir, noisy_dir):
    pesq_list = []
    stoi_list = []
    for wav in files:
        name_base = os.path.basename(wav)
        clean_path = os.path.join(clean_dir, name_base)
        if not os.path.exists(clean_path):
            continue
        noisy, sr0 = librosa.load(wav, sr=None)
        if sr0 != 16000:
            noisy = librosa.resample(noisy, orig_sr=sr0, target_sr=16000)
        clean, _ = librosa.load(clean_path, sr=16000)
        enhanced = denoiser.denoise(noisy)
        # Align lengths
        n = min(len(clean), len(enhanced))
        c = clean[:n]
        e = enhanced[:n]
        try:
            p = calculate_pesq(c, e, EVAL_SR)
            s = calculate_stoi(c, e, EVAL_SR)
            if p is not None and s is not None:
                pesq_list.append(p)
                stoi_list.append(s)
        except Exception:
            pass
    if not pesq_list:
        return name, float('nan'), float('nan'), 0
    return name, np.mean(pesq_list), np.mean(stoi_list), len(pesq_list)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset-dir', required=True)
    ap.add_argument('--config', default='config/v4_config.yaml')
    ap.add_argument('--subset', type=int, default=80,
                    help='random subset of files to evaluate')
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    noisy_dir = os.path.join(args.dataset_dir, 'noisy_testset_wav')
    clean_dir = os.path.join(args.dataset_dir, 'clean_testset_wav')

    all_noisy = sorted(glob(os.path.join(noisy_dir, '*.wav')))
    rng = np.random.default_rng(args.seed)
    idx = rng.choice(len(all_noisy), size=min(args.subset, len(all_noisy)), replace=False)
    files = [all_noisy[i] for i in sorted(idx)]

    print(f"Smoke test on {len(files)} random VCTK files")
    print(f"{'variant':40s}  n   PESQ     STOI")
    print('-' * 70)

    # Variants
    variants = []

    # Baseline: V3-2 fixed
    p = get_denoiser_params_from_config(cfg, 16000, cfg['audio']['fft_size'])
    variants.append(('V3-2 fixed (baseline)', MmseLsaDenoiser(**p)))

    # V4 full
    variants.append(('V4 full', build_omlsa(cfg)))

    # V4 wind off (=V3-2)
    cfg_off = copy.deepcopy(cfg)
    cfg_off['wind_handler']['enable'] = False
    cfg_off['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 wind off + transient off', build_omlsa(cfg_off)))

    # V4 with flat freq-adaptive (normal profile only)
    cfg_flat = copy.deepcopy(cfg)
    # set all profile [normal, mild, severe] = normal
    for prof in ['g_min_profile_db', 'alpha_xi_profile', 'alpha_g_profile']:
        for band in cfg_flat['wind_handler']['freq_adaptive'][prof]:
            v = cfg_flat['wind_handler']['freq_adaptive'][prof][band][0]
            cfg_flat['wind_handler']['freq_adaptive'][prof][band] = [v, v, v]
    variants.append(('V4 wind on + FLAT adaptive (no g_min drop)', build_omlsa(cfg_flat)))

    # V4 with no transient suppressor
    cfg_nots = copy.deepcopy(cfg)
    cfg_nots['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 wind on, transient OFF', build_omlsa(cfg_nots)))

    # V4 with severe_threshold pushed to 0.99 (severe mode never fires)
    cfg_nosevere = copy.deepcopy(cfg)
    cfg_nosevere['wind_handler']['detector']['severe_threshold'] = 0.99
    variants.append(('V4 wind on, severe_threshold=0.99', build_omlsa(cfg_nosevere)))

    # V4 + SPP protected floor -10dB
    cfg_spp10 = copy.deepcopy(cfg)
    cfg_spp10['gain_calculation']['spp_protect_floor_db'] = -10.0
    cfg_spp10['gain_calculation']['spp_protect_threshold'] = 0.5
    variants.append(('V4 full + SPP floor=-10dB (spp>0.5)', build_omlsa(cfg_spp10)))

    # V4 + SPP protected floor -6dB (more conservative)
    cfg_spp6 = copy.deepcopy(cfg)
    cfg_spp6['gain_calculation']['spp_protect_floor_db'] = -6.0
    cfg_spp6['gain_calculation']['spp_protect_threshold'] = 0.5
    variants.append(('V4 full + SPP floor=-6dB (spp>0.5)', build_omlsa(cfg_spp6)))

    # V4 relaxed profile (mild closer to normal)
    cfg_relax = copy.deepcopy(cfg)
    cfg_relax['wind_handler']['freq_adaptive']['g_min_profile_db'] = {
        'band_0': [-15, -18, -25],  # mild from -25 -> -18
        'band_1': [-15, -16, -20],
        'band_2': [-15, -15, -16],
        'band_3': [-15, -15, -15],
    }
    variants.append(('V4 relaxed g_min profile', build_omlsa(cfg_relax)))

    # V4 SPP floor -10dB + relaxed profile (combo)
    cfg_combo = copy.deepcopy(cfg_relax)
    cfg_combo['gain_calculation']['spp_protect_floor_db'] = -10.0
    cfg_combo['gain_calculation']['spp_protect_threshold'] = 0.5
    variants.append(('V4 SPP -10dB + relaxed profile', build_omlsa(cfg_combo)))

    # V4 FLAT adaptive + transient OFF (真正的 baseline 檢查)
    cfg_flat_nots = copy.deepcopy(cfg)
    for prof in ['g_min_profile_db', 'alpha_xi_profile', 'alpha_g_profile']:
        for band in cfg_flat_nots['wind_handler']['freq_adaptive'][prof]:
            v = cfg_flat_nots['wind_handler']['freq_adaptive'][prof][band][0]
            cfg_flat_nots['wind_handler']['freq_adaptive'][prof][band] = [v, v, v]
    cfg_flat_nots['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 FLAT + transient OFF', build_omlsa(cfg_flat_nots)))

    # V4 with mild_threshold raised to 0.70 (harder to trigger mild)
    cfg_high_mild = copy.deepcopy(cfg)
    cfg_high_mild['wind_handler']['detector']['mild_threshold'] = 0.70
    cfg_high_mild['wind_handler']['detector']['severe_threshold'] = 0.95
    variants.append(('V4 mild_th=0.70, severe_th=0.95', build_omlsa(cfg_high_mild)))

    # V4 very-conservative mild profile (nearly normal)
    cfg_very_conservative = copy.deepcopy(cfg)
    cfg_very_conservative['wind_handler']['freq_adaptive']['g_min_profile_db'] = {
        'band_0': [-15, -16, -22],
        'band_1': [-15, -15, -18],
        'band_2': [-15, -15, -16],
        'band_3': [-15, -15, -15],
    }
    variants.append(('V4 very conservative mild profile', build_omlsa(cfg_very_conservative)))

    # V4 full fix: very conservative + SPP floor + transient OFF
    cfg_full_fix = copy.deepcopy(cfg_very_conservative)
    cfg_full_fix['gain_calculation']['spp_protect_floor_db'] = -10.0
    cfg_full_fix['wind_handler']['transient_suppressor']['enable'] = False
    variants.append(('V4 conservative + SPP -10 + transient OFF', build_omlsa(cfg_full_fix)))

    for name, den in variants:
        nm, pesq, stoi, n = run_variant(name, den, files, clean_dir, noisy_dir)
        print(f"{nm:40s}  {n:3d}  {pesq:.3f}   {stoi:.3f}")


if __name__ == '__main__':
    main()
