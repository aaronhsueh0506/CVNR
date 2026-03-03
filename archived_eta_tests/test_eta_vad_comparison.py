#!/usr/bin/env python3
"""
測試 enable_eta 和 enable_soft_vad 對 V3 和 V3-3 的影響
"""

import numpy as np
import librosa
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers import SppMmseDenoiser, PmmseDenoiser
from utils.metrics import calculate_pesq, calculate_stoi

# 測試配置
TEST_CASES = ['babble_5dB', 'car_5dB', 'street_5dB']
INPUT_DIR = 'test_wav/wav/append_silence'
CLEAN_FILE = 'test_wav/wav/clean.wav'

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_denoiser_params(config, sr=16000, fft_size=512):
    """從配置提取參數"""
    params = {
        'sample_rate': sr,
        'fft_size': fft_size,
        'frame_size_ms': config['audio']['frame_size_ms'],
        'frame_shift_ms': config['audio']['frame_shift_ms']
    }

    # SPP 參數
    if 'spp' in config:
        spp = config['spp']
        params.update({
            'alpha_xi': spp.get('alpha_xi', 0.98),
            'q': spp.get('q', 0.5),
            'xi_min_db': spp.get('xi_min_db', -25.0)
        })

    # 增益參數
    if 'gain_calculation' in config:
        gc = config['gain_calculation']
        params.update({
            'g_min_db': gc.get('g_min_db', -20.0),
            'alpha_g': gc.get('alpha_g', 0.7)
        })
        # V3 特有
        if gc.get('method') == 'spp_mmse':
            params['use_full_formula'] = gc.get('use_full_formula', False)
        # V3-3 特有
        if gc.get('method') == 'pmmse':
            params['use_spp_weighting'] = gc.get('use_spp_weighting', True)

    # 噪聲估計參數
    if 'noise_estimation' in config:
        ne = config['noise_estimation']
        if ne.get('method') == 'mcra':
            params.update({
                'noise_method': 'mcra',
                'alpha_s': ne.get('alpha_s', 0.9),
                'alpha_noise': ne.get('alpha_d', 0.85),
                'alpha_p': ne.get('alpha_p', 0.2),
                'L': ne.get('L', 96),
                'delta_db': ne.get('delta_db', 5.0)
            })

    return params

def evaluate_denoiser(denoiser, noisy, clean, sr=16000):
    """評估降噪器"""
    enhanced = denoiser.denoise(noisy)

    # 移除 prepend 的 0.5 秒靜音
    trim_samples = int(0.5 * sr)
    enhanced = enhanced[trim_samples:]

    # 對齊長度
    min_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:min_len]
    clean_aligned = clean[:min_len]

    pesq = calculate_pesq(clean_aligned, enhanced, sr)
    stoi = calculate_stoi(clean_aligned, enhanced, sr)

    return pesq, stoi

def main():
    print("=" * 100)
    print("V3 / V3-3: enable_eta 和 enable_soft_vad 效果比較")
    print("=" * 100)

    # 加載 clean reference
    clean, sr = librosa.load(CLEAN_FILE, sr=16000)

    # 加載配置
    v3_config = load_config('config/v3_config.yaml')
    v3_3_config = load_config('config/v3_3_config.yaml')

    # 組合測試
    combinations = [
        ('baseline', False, False),
        ('eta_only', True, False),
        ('vad_only', False, True),
        ('eta+vad', True, True),
    ]

    results = {
        'V3': {combo[0]: {'pesq': [], 'stoi': []} for combo in combinations},
        'V3-3': {combo[0]: {'pesq': [], 'stoi': []} for combo in combinations}
    }

    for test_case in TEST_CASES:
        print(f"\n{'='*60}")
        print(f"測試: {test_case}")
        print(f"{'='*60}")

        # 加載 noisy 音頻
        noisy_file = f"{INPUT_DIR}/{test_case}_prepend.wav"
        if not os.path.exists(noisy_file):
            print(f"  ⚠️ 找不到 {noisy_file}")
            continue

        noisy, _ = librosa.load(noisy_file, sr=16000)

        print(f"\n{'V3 (SPP-MMSE)':^50}")
        print("-" * 50)
        print(f"{'組合':<15} | {'PESQ':>8} | {'STOI':>8}")
        print("-" * 50)

        for combo_name, enable_eta, enable_soft_vad in combinations:
            params = get_denoiser_params(v3_config)
            params['enable_eta'] = enable_eta
            params['enable_soft_vad'] = enable_soft_vad

            denoiser = SppMmseDenoiser(**params)
            pesq, stoi = evaluate_denoiser(denoiser, noisy, clean)

            results['V3'][combo_name]['pesq'].append(pesq)
            results['V3'][combo_name]['stoi'].append(stoi)

            print(f"{combo_name:<15} | {pesq:>8.3f} | {stoi:>8.3f}")

        print(f"\n{'V3-3 (PMMSE)':^50}")
        print("-" * 50)
        print(f"{'組合':<15} | {'PESQ':>8} | {'STOI':>8}")
        print("-" * 50)

        for combo_name, enable_eta, enable_soft_vad in combinations:
            params = get_denoiser_params(v3_3_config)
            params['enable_eta'] = enable_eta
            params['enable_soft_vad'] = enable_soft_vad

            denoiser = PmmseDenoiser(**params)
            pesq, stoi = evaluate_denoiser(denoiser, noisy, clean)

            results['V3-3'][combo_name]['pesq'].append(pesq)
            results['V3-3'][combo_name]['stoi'].append(stoi)

            print(f"{combo_name:<15} | {pesq:>8.3f} | {stoi:>8.3f}")

    # 總結
    print("\n" + "=" * 100)
    print("平均分數總結")
    print("=" * 100)

    print(f"\n{'版本':<8} | {'組合':<15} | {'Avg PESQ':>10} | {'Avg STOI':>10}")
    print("-" * 60)

    for version in ['V3', 'V3-3']:
        for combo_name, _, _ in combinations:
            avg_pesq = np.mean(results[version][combo_name]['pesq'])
            avg_stoi = np.mean(results[version][combo_name]['stoi'])
            print(f"{version:<8} | {combo_name:<15} | {avg_pesq:>10.3f} | {avg_stoi:>10.3f}")
        print("-" * 60)

if __name__ == "__main__":
    main()
