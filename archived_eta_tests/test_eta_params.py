#!/usr/bin/env python3
"""
Eta 參數測試腳本

測試不同的 eta_beta_threshold 設定對降噪效果的影響
"""

import numpy as np
import librosa
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers import MmseLsaDenoiser
from utils.metrics import calculate_pesq, calculate_stoi

# 測試配置
ETA_CONFIGS = [
    {'name': 'baseline', 'enable_eta': False, 'eta_beta_threshold': 10.0},
    {'name': 'eta_t15', 'enable_eta': True, 'eta_beta_threshold': 15.0},
    {'name': 'eta_t20', 'enable_eta': True, 'eta_beta_threshold': 20.0},
    {'name': 'eta_t25', 'enable_eta': True, 'eta_beta_threshold': 25.0},
]

# V3-2 基礎參數（從 v3_2_config.yaml）
BASE_PARAMS = {
    'sample_rate': 16000,
    'fft_size': 512,
    'frame_size_ms': 20,
    'frame_shift_ms': 10,
    'alpha_xi': 0.92,
    'q': 0.50,
    'xi_min_db': -20.0,
    'g_min_db': -12.5,
    'alpha_g': 0.80,
    'use_linear_spp_weighting': False,
    'noise_method': 'mcra',
    'alpha_s': 0.8,
    'alpha_noise': 0.95,
    'alpha_p': 0.2,
    'L': 120,
    'delta_db': 5.0,
}

# test_wav 測試用例
TEST_WAV_DIR = 'test_wav/wav'
NOISE_TYPES = ['babble', 'car', 'street']
SNR_LEVELS = [0, 5, 10, 15]
TEST_CASES = [f"{n}_{s}dB" for n in NOISE_TYPES for s in SNR_LEVELS]

# VCTK 設定
VCTK_DIR = '/Users/mingyu/Desktop/novatek/SE/VCTK_DEMAND_testset'


def test_single_file(denoiser, noisy_path, clean_path, sr=16000):
    """測試單個文件並返回 PESQ/STOI"""
    noisy, _ = librosa.load(noisy_path, sr=sr)
    clean, _ = librosa.load(clean_path, sr=sr)

    enhanced = denoiser.denoise(noisy)

    # 對齊長度
    min_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:min_len]
    clean = clean[:min_len]

    pesq = calculate_pesq(clean, enhanced, sr)
    stoi = calculate_stoi(clean, enhanced, sr)

    return pesq, stoi


def test_test_wav(eta_config):
    """在 test_wav 數據集上測試"""
    params = BASE_PARAMS.copy()
    params['enable_eta'] = eta_config['enable_eta']
    params['eta_beta_threshold'] = eta_config['eta_beta_threshold']

    results = {'pesq': [], 'stoi': []}

    clean_path = f"{TEST_WAV_DIR}/clean.wav"

    for test_case in TEST_CASES:
        noisy_path = f"{TEST_WAV_DIR}/append_silence/{test_case}_prepend.wav"

        if not os.path.exists(noisy_path):
            continue

        denoiser = MmseLsaDenoiser(**params)

        # 載入帶前導靜音的 noisy
        noisy, _ = librosa.load(noisy_path, sr=16000)
        clean, _ = librosa.load(clean_path, sr=16000)

        enhanced = denoiser.denoise(noisy)

        # 移除前導靜音 (0.5s)
        trim_samples = int(0.5 * 16000)
        enhanced = enhanced[trim_samples:]

        # 對齊長度
        min_len = min(len(enhanced), len(clean))
        enhanced = enhanced[:min_len]
        clean = clean[:min_len]

        pesq = calculate_pesq(clean, enhanced, 16000)
        stoi = calculate_stoi(clean, enhanced, 16000)

        results['pesq'].append(pesq)
        results['stoi'].append(stoi)

    return {
        'avg_pesq': np.mean(results['pesq']) if results['pesq'] else None,
        'avg_stoi': np.mean(results['stoi']) if results['stoi'] else None,
        'count': len(results['pesq'])
    }


def test_vctk(eta_config, max_files=50):
    """在 VCTK 數據集上測試（取樣測試加速）"""
    params = BASE_PARAMS.copy()
    params['enable_eta'] = eta_config['enable_eta']
    params['eta_beta_threshold'] = eta_config['eta_beta_threshold']

    noisy_dir = Path(VCTK_DIR) / 'noisy'
    clean_dir = Path(VCTK_DIR) / 'clean'

    if not noisy_dir.exists():
        print(f"  VCTK 目錄不存在: {noisy_dir}")
        return None

    # 取樣文件進行測試
    noisy_files = sorted(noisy_dir.glob('*.wav'))[:max_files]

    results = {'pesq': [], 'stoi': []}

    for noisy_path in noisy_files:
        clean_path = clean_dir / noisy_path.name

        if not clean_path.exists():
            continue

        denoiser = MmseLsaDenoiser(**params)

        noisy, orig_sr = librosa.load(str(noisy_path), sr=None)
        clean, _ = librosa.load(str(clean_path), sr=None)

        # Resample to 16kHz
        if orig_sr != 16000:
            noisy = librosa.resample(noisy, orig_sr=orig_sr, target_sr=16000)
            clean = librosa.resample(clean, orig_sr=orig_sr, target_sr=16000)

        enhanced = denoiser.denoise(noisy)

        # 對齊長度
        min_len = min(len(enhanced), len(clean))
        enhanced = enhanced[:min_len]
        clean = clean[:min_len]

        pesq = calculate_pesq(clean, enhanced, 16000)
        stoi = calculate_stoi(clean, enhanced, 16000)

        if pesq is not None:
            results['pesq'].append(pesq)
        if stoi is not None:
            results['stoi'].append(stoi)

    return {
        'avg_pesq': np.mean(results['pesq']) if results['pesq'] else None,
        'avg_stoi': np.mean(results['stoi']) if results['stoi'] else None,
        'count': len(results['pesq'])
    }


def main():
    print("=" * 80)
    print("Eta 參數測試 - V3-2 MMSE-LSA")
    print("=" * 80)

    all_results = {}

    # 測試 test_wav
    print("\n[test_wav 數據集]")
    print("-" * 60)
    print(f"{'配置':<15} | {'PESQ':>8} | {'STOI':>8} | {'測試數':>6}")
    print("-" * 60)

    for eta_config in ETA_CONFIGS:
        result = test_test_wav(eta_config)
        all_results[f"test_wav_{eta_config['name']}"] = result

        pesq_str = f"{result['avg_pesq']:.3f}" if result['avg_pesq'] else "N/A"
        stoi_str = f"{result['avg_stoi']:.3f}" if result['avg_stoi'] else "N/A"

        print(f"{eta_config['name']:<15} | {pesq_str:>8} | {stoi_str:>8} | {result['count']:>6}")

    # 測試 VCTK (取樣 50 個文件加速測試)
    print("\n[VCTK 數據集] (取樣 50 個文件)")
    print("-" * 60)
    print(f"{'配置':<15} | {'PESQ':>8} | {'STOI':>8} | {'測試數':>6}")
    print("-" * 60)

    for eta_config in ETA_CONFIGS:
        result = test_vctk(eta_config, max_files=50)

        if result is None:
            print(f"{eta_config['name']:<15} | {'N/A':>8} | {'N/A':>8} | {'0':>6}")
            continue

        all_results[f"vctk_{eta_config['name']}"] = result

        pesq_str = f"{result['avg_pesq']:.3f}" if result['avg_pesq'] else "N/A"
        stoi_str = f"{result['avg_stoi']:.3f}" if result['avg_stoi'] else "N/A"

        print(f"{eta_config['name']:<15} | {pesq_str:>8} | {stoi_str:>8} | {result['count']:>6}")

    # 總結
    print("\n" + "=" * 80)
    print("總結")
    print("=" * 80)

    # 計算 baseline 與各配置的差異
    baseline_tw = all_results.get('test_wav_baseline', {})
    baseline_vctk = all_results.get('vctk_baseline', {})

    print(f"\n{'配置':<15} | {'test_wav ΔPESQ':>14} | {'VCTK ΔPESQ':>12}")
    print("-" * 50)

    for eta_config in ETA_CONFIGS:
        tw_result = all_results.get(f"test_wav_{eta_config['name']}", {})
        vctk_result = all_results.get(f"vctk_{eta_config['name']}", {})

        tw_delta = ""
        if tw_result.get('avg_pesq') and baseline_tw.get('avg_pesq'):
            delta = tw_result['avg_pesq'] - baseline_tw['avg_pesq']
            tw_delta = f"{delta:+.3f}"

        vctk_delta = ""
        if vctk_result.get('avg_pesq') and baseline_vctk.get('avg_pesq'):
            delta = vctk_result['avg_pesq'] - baseline_vctk['avg_pesq']
            vctk_delta = f"{delta:+.3f}"

        print(f"{eta_config['name']:<15} | {tw_delta:>14} | {vctk_delta:>12}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
