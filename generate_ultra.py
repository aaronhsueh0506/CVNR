#!/usr/bin/env python3
"""
生成 Ultra/Extreme 配置的降噪輸出

目標: 達到 STOI Δ ≥ +0.019 (追平 RNNoise)
"""

import numpy as np
import librosa
import soundfile as sf
import os
import yaml
from denoisers import PmmseDenoiser, LaplacianMmseDenoiser

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# ✅ 先只做 V3-3 (2 組)
experiments = [
    {
        'name': 'V3-3_ultra',
        'config': 'config/v3_3_ultra.yaml',
        'denoiser_class': PmmseDenoiser,
        'label': 'V3-3 Ultra (base=-5.0)'
    },
    {
        'name': 'V3-3_extreme',
        'config': 'config/v3_3_extreme.yaml',
        'denoiser_class': PmmseDenoiser,
        'label': 'V3-3 Extreme (base=-3.0)'
    }
]

output_dir = 'denoised_ultra'
os.makedirs(output_dir, exist_ok=True)

print("=" * 100)
print("生成 Ultra/Extreme 配置的降噪輸出")
print("=" * 100)
print(f"目標: STOI Δ ≥ +0.019, PESQ Δ ≥ +0.40")
print(f"測試用例: {len(test_cases)} 個")
print(f"實驗組: {len(experiments)} 組")
print(f"預期輸出: {len(experiments) * len(test_cases)} 個文件")
print("=" * 100)

total_processed = 0
total_files = len(experiments) * len(test_cases)

for exp_idx, experiment in enumerate(experiments, 1):
    print(f"\n[{exp_idx}/{len(experiments)}] {experiment['label']}")
    print("-" * 100)

    config = load_config(experiment['config'])

    print(f"  base_g_min_db: {config['snr_adaptive']['base_g_min_db']}")
    print(f"  alpha_g: {config['gain_calculation']['alpha_g']}")
    print(f"  use_spp_weighting: {config['gain_calculation'].get('use_spp_weighting', True)}")
    if 'beta_laplacian' in config['gain_calculation']:
        print(f"  beta_laplacian: {config['gain_calculation']['beta_laplacian']}")

    # 創建降噪器
    denoiser_params = {
        'sample_rate': config['audio']['sample_rate'],
        'frame_size_ms': config['audio']['frame_size_ms'],
        'frame_shift_ms': config['audio']['frame_shift_ms'],
        'fft_size': config['audio']['fft_size'],
        'alpha_noise': config['noise_estimation']['alpha'],
        'num_init_frames': config['noise_estimation']['num_init_frames'],
        'alpha_xi': config['spp']['alpha_xi'],
        'q': config['spp']['q'],
        'xi_min_db': config['spp']['xi_min_db'],
        'g_min_db': config['gain_calculation']['g_min_db'],
        'alpha_g': config['gain_calculation']['alpha_g'],
        'snr_adaptive_config': config.get('snr_adaptive', {})
    }

    if experiment['denoiser_class'] == PmmseDenoiser:
        denoiser_params['use_spp_weighting'] = config['gain_calculation'].get('use_spp_weighting', True)
    elif experiment['denoiser_class'] == LaplacianMmseDenoiser:
        denoiser_params['beta_laplacian'] = config['gain_calculation'].get('beta_laplacian', 1.5)

    denoiser = experiment['denoiser_class'](**denoiser_params)

    success_count = 0
    for i, case in enumerate(test_cases, 1):
        noisy_path = f'test_wav/wav/append_silence/{case}_prepend.wav'
        output_path = f'{output_dir}/{case}_{experiment["name"]}.wav'

        if not os.path.exists(noisy_path):
            print(f"  [{i}/{len(test_cases)}] ⚠️  {case} - 文件不存在")
            continue

        try:
            noisy_signal, original_sr = librosa.load(noisy_path, sr=None)
            if original_sr != 16000:
                noisy_signal = librosa.resample(noisy_signal, orig_sr=original_sr, target_sr=16000)

            denoiser.reset()
            enhanced_signal = denoiser.denoise(noisy_signal)
            sf.write(output_path, enhanced_signal, 16000)

            success_count += 1
            total_processed += 1
        except Exception as e:
            print(f"  [{i}/{len(test_cases)}] ❌ {case}: {e}")
            total_processed += 1

    print(f"  完成: {success_count}/12 ✅")
    print(f"  總進度: {total_processed}/{total_files} ({total_processed/total_files*100:.1f}%)")

print("\n" + "=" * 100)
print(f"全部完成! {total_processed}/{total_files} 個文件")
print(f"輸出目錄: {output_dir}/")
print("=" * 100)
print("\n下一步: python3 evaluate_ultra.py")
