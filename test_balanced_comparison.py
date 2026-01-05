#!/usr/bin/env python3
"""
Phase 6 配置驗證測試
測試 Natural, Balanced, Aggressive 三個配置的 V2 修正效果
"""

import os
import sys
import yaml
import numpy as np
import soundfile as sf
import matplotlib.pyplot as plt
import librosa

sys.path.insert(0, os.path.dirname(__file__))
from denoisers.v3_3_pmmse import PmmseDenoiser
from utils.metrics import calculate_pesq, calculate_stoi
from utils.metrics_loizou import composite_measure


def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_denoiser(config):
    snr_cfg = config.get('snr_adaptive', {})
    snr_adaptive_config = {
        'enable': snr_cfg.get('enable', False),
        'base_g_min_db': snr_cfg.get('base_g_min_db', -15.0),
        'snr_smoothing': snr_cfg.get('snr_smoothing', 0.9),
        'clean_detection': snr_cfg.get('clean_detection', False),
        'clean_bypass': snr_cfg.get('clean_bypass', False)
    } if snr_cfg.get('enable', False) else None

    fast_cfg = config.get('fast_startup', {})
    trans_cfg = config.get('transition_detection', {})

    return PmmseDenoiser(
        sample_rate=16000,
        alpha_noise=0.95,
        alpha_xi=0.95,
        alpha_g=0.5,
        enable_fast_startup=fast_cfg.get('enable', False),
        startup_frames=fast_cfg.get('startup_frames', 50),
        alpha_noise_startup=fast_cfg.get('alpha_noise_startup', 0.7),
        alpha_xi_startup=fast_cfg.get('alpha_xi_startup', 0.7),
        alpha_g_startup=fast_cfg.get('alpha_g_startup', 0.4),
        num_init_frames_fast=fast_cfg.get('num_init_frames_fast', 10),
        enable_transition_detection=trans_cfg.get('enable', False),
        transition_config=trans_cfg if trans_cfg.get('enable', False) else None,
        snr_adaptive_config=snr_adaptive_config
    )


def main():
    print("\n" + "="*60)
    print("Phase 6 V2 Configuration Validation")
    print("="*60)

    base_dir = os.path.dirname(__file__)

    # 測試文件
    clean_path = os.path.join(base_dir, 'test_wav/wav/clean.wav')
    noisy_path = os.path.join(base_dir, 'test_wav/wav/car_10dB.wav')

    clean, _ = sf.read(clean_path)
    noisy, _ = sf.read(noisy_path)

    # 測試三個 Phase 6 配置
    configs = [
        ('Natural', 'config/v3_3_phase6_natural.yaml'),
        ('Balanced', 'config/v3_3_phase6_balanced.yaml'),
        ('Aggressive', 'config/v3_3_phase6_aggressive.yaml')
    ]

    results = {}

    for name, cfg_path in configs:
        print(f"\n{'='*60}")
        print(f"Testing: {name}")
        print(f"{'='*60}")

        config = load_config(os.path.join(base_dir, cfg_path))
        denoiser = create_denoiser(config)

        # 降噪
        enhanced = denoiser.denoise(noisy)

        # 確保長度一致
        min_len = min(len(clean), len(noisy), len(enhanced))
        clean_trim = clean[:min_len]
        noisy_trim = noisy[:min_len]
        enhanced_trim = enhanced[:min_len]

        # 評估
        noisy_metrics = composite_measure(clean_trim, noisy_trim, 16000)
        enhanced_metrics = composite_measure(clean_trim, enhanced_trim, 16000)

        pesq_noisy = calculate_pesq(clean_trim, noisy_trim, 16000)
        pesq_enh = calculate_pesq(clean_trim, enhanced_trim, 16000)
        stoi_noisy = calculate_stoi(clean_trim, noisy_trim, 16000)
        stoi_enh = calculate_stoi(clean_trim, enhanced_trim, 16000)

        # 計算振幅比（檢查過度抑制）
        clean_rms = np.sqrt(np.mean(clean_trim**2))
        enhanced_rms = np.sqrt(np.mean(enhanced_trim**2))
        amplitude_ratio = enhanced_rms / clean_rms

        results[name] = {
            'PESQ_Δ': pesq_enh - pesq_noisy,
            'STOI_Δ': stoi_enh - stoi_noisy,
            'segSNR_Δ': enhanced_metrics['segSNR'] - noisy_metrics['segSNR'],
            'Amplitude_Ratio': amplitude_ratio,
            'enhanced': enhanced_trim
        }

        print(f"\nResults:")
        print(f"  PESQ Δ:   {results[name]['PESQ_Δ']:+.3f}")
        print(f"  STOI Δ:   {results[name]['STOI_Δ']:+.4f}")
        print(f"  segSNR Δ: {results[name]['segSNR_Δ']:+.2f} dB")
        print(f"  振幅比:   {amplitude_ratio:.3f} (1.0 = 與 clean 相同)")

        denoiser.reset()

    # 對比圖
    print("\n" + "="*60)
    print("Comparison Summary")
    print("="*60)
    print(f"{'Metric':<15} {'Natural':>12} {'Balanced':>12} {'Aggressive':>12}")
    print("-"*60)

    for metric in ['PESQ_Δ', 'STOI_Δ', 'segSNR_Δ', 'Amplitude_Ratio']:
        nat = results['Natural'][metric]
        bal = results['Balanced'][metric]
        agg = results['Aggressive'][metric]

        if metric == 'Amplitude_Ratio':
            print(f"{metric:<15} {nat:>12.3f} {bal:>12.3f} {agg:>12.3f}")
        else:
            print(f"{metric:<15} {nat:>+12.4f} {bal:>+12.4f} {agg:>+12.4f}")

    print("\n" + "="*60)
    print("✅ Comparison Complete!")
    print("="*60)
    print("\n驗證標準:")
    print("1. Amplitude_Ratio 應在 0.95-1.05 範圍 (理想值 1.0)")
    print("2. PESQ Δ 應為正值 (>0)")
    print("3. Balanced 應有最佳振幅比 (0.98-1.02)")
    print("4. Aggressive 可能略低，但應 >0.92")


if __name__ == '__main__':
    main()
