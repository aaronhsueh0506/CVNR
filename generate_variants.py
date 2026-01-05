#!/usr/bin/env python3
"""
批量生成 6 組實驗的降噪輸出

實驗組:
1. V3-3 保守檔 (base_g_min_db=-12.0, alpha_g=0.7)
2. V3-3 中庸檔 (base_g_min_db=-10.0, alpha_g=0.6)
3. V3-3 激進檔 (base_g_min_db=-8.0, alpha_g=0.5, no SPP)
4. V3-4 保守檔 (base_g_min_db=-12.0, alpha_g=0.7, beta=1.5)
5. V3-4 中庸檔 (base_g_min_db=-10.0, alpha_g=0.6, beta=1.5)
6. V3-4 激進檔 (base_g_min_db=-8.0, alpha_g=0.5, beta=2.0)
"""

import numpy as np
import librosa
import soundfile as sf
import os
import yaml
from pathlib import Path
from denoisers import PmmseDenoiser, LaplacianMmseDenoiser

def load_config(config_path):
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# 輸出目錄
output_dir = 'denoised_variants'
os.makedirs(output_dir, exist_ok=True)

# 6 組實驗配置
experiments = [
    {
        'name': 'V3-3_conservative',
        'config': 'config/v3_3_conservative.yaml',
        'denoiser_class': PmmseDenoiser,
        'label': 'V3-3 保守檔'
    },
    {
        'name': 'V3-3_moderate',
        'config': 'config/v3_3_moderate.yaml',
        'denoiser_class': PmmseDenoiser,
        'label': 'V3-3 中庸檔'
    },
    {
        'name': 'V3-3_aggressive',
        'config': 'config/v3_3_aggressive.yaml',
        'denoiser_class': PmmseDenoiser,
        'label': 'V3-3 激進檔'
    },
    {
        'name': 'V3-4_conservative',
        'config': 'config/v3_4_conservative.yaml',
        'denoiser_class': LaplacianMmseDenoiser,
        'label': 'V3-4 保守檔'
    },
    {
        'name': 'V3-4_moderate',
        'config': 'config/v3_4_moderate.yaml',
        'denoiser_class': LaplacianMmseDenoiser,
        'label': 'V3-4 中庸檔'
    },
    {
        'name': 'V3-4_aggressive',
        'config': 'config/v3_4_aggressive.yaml',
        'denoiser_class': LaplacianMmseDenoiser,
        'label': 'V3-4 激進檔'
    }
]

print("=" * 100)
print("批量生成 6 組實驗的降噪輸出")
print("=" * 100)
print(f"測試用例: {len(test_cases)} 個")
print(f"實驗組: {len(experiments)} 組")
print(f"預期輸出: {len(experiments) * len(test_cases)} 個文件")
print(f"輸出目錄: {output_dir}/")
print("=" * 100)

total_processed = 0
total_files = len(experiments) * len(test_cases)

for exp_idx, experiment in enumerate(experiments, 1):
    print(f"\n[{exp_idx}/{len(experiments)}] 處理實驗組: {experiment['label']}")
    print("-" * 100)

    # 加載配置
    config = load_config(experiment['config'])

    # 打印關鍵參數
    print(f"  配置: {experiment['config']}")
    print(f"  base_g_min_db: {config['snr_adaptive']['base_g_min_db']}")
    print(f"  alpha_g: {config['gain_calculation']['alpha_g']}")
    print(f"  use_spp_weighting: {config['gain_calculation'].get('use_spp_weighting', True)}")
    if 'beta_laplacian' in config['gain_calculation']:
        print(f"  beta_laplacian: {config['gain_calculation']['beta_laplacian']}")

    # 音頻參數
    sample_rate = config['audio']['sample_rate']
    frame_size_ms = config['audio']['frame_size_ms']
    frame_shift_ms = config['audio']['frame_shift_ms']
    fft_size = config['audio']['fft_size']

    # 噪聲估計參數
    alpha_noise = config['noise_estimation']['alpha']
    num_init_frames = config['noise_estimation']['num_init_frames']

    # SPP 參數
    alpha_xi = config['spp']['alpha_xi']
    q = config['spp']['q']
    xi_min_db = config['spp']['xi_min_db']

    # 增益計算參數
    g_min_db = config['gain_calculation']['g_min_db']
    alpha_g = config['gain_calculation']['alpha_g']
    use_spp_weighting = config['gain_calculation'].get('use_spp_weighting', True)

    # SNR adaptive 參數
    snr_adaptive_config = config.get('snr_adaptive', {})

    # 創建降噪器 (根據不同類型構建參數)
    denoiser_params = {
        'sample_rate': sample_rate,
        'frame_size_ms': frame_size_ms,
        'frame_shift_ms': frame_shift_ms,
        'fft_size': fft_size,
        'alpha_noise': alpha_noise,
        'num_init_frames': num_init_frames,
        'alpha_xi': alpha_xi,
        'q': q,
        'xi_min_db': xi_min_db,
        'g_min_db': g_min_db,
        'alpha_g': alpha_g,
        'snr_adaptive_config': snr_adaptive_config
    }

    # V3-3 (PMMSE) 特有參數
    if experiment['denoiser_class'] == PmmseDenoiser:
        denoiser_params['use_spp_weighting'] = use_spp_weighting

    # V3-4 (Laplacian-MMSE) 特有參數
    elif experiment['denoiser_class'] == LaplacianMmseDenoiser:
        denoiser_params['beta_laplacian'] = config['gain_calculation'].get('beta_laplacian', 1.5)

    denoiser = experiment['denoiser_class'](**denoiser_params)

    success_count = 0
    fail_count = 0

    for i, case in enumerate(test_cases, 1):
        # ✅ 使用 append_silence 目錄下的 prepend 文件（與 regenerate_all_outputs.py 一致）
        noisy_path = f'test_wav/wav/append_silence/{case}_prepend.wav'
        output_path = f'{output_dir}/{case}_{experiment["name"]}.wav'

        if not os.path.exists(noisy_path):
            print(f"  [{i}/{len(test_cases)}] ⚠️  跳過: {case} (文件不存在)")
            fail_count += 1
            total_processed += 1
            continue

        try:
            # 加載並統一重採樣到 16kHz
            noisy_signal, original_sr = librosa.load(noisy_path, sr=None)

            # 強制重採樣到 16kHz
            if original_sr != sample_rate:
                noisy_signal = librosa.resample(noisy_signal, orig_sr=original_sr, target_sr=sample_rate)

            # 降噪
            denoiser.reset()
            enhanced_signal = denoiser.denoise(noisy_signal)

            # 保存（使用 16kHz）
            sf.write(output_path, enhanced_signal, sample_rate)

            print(f"  [{i}/{len(test_cases)}] ✅ {case}")
            success_count += 1
            total_processed += 1

        except Exception as e:
            print(f"  [{i}/{len(test_cases)}] ❌ {case}: {e}")
            fail_count += 1
            total_processed += 1

    print(f"  實驗組完成: ✅ {success_count} 成功, ❌ {fail_count} 失敗")
    print(f"  總進度: {total_processed}/{total_files} ({total_processed/total_files*100:.1f}%)")

print("\n" + "=" * 100)
print(f"全部完成! 成功生成 {total_processed}/{total_files} 個文件")
print(f"輸出目錄: {output_dir}/")
print("=" * 100)
print("\n下一步: 運行評估腳本")
print("  python3 compute_improvement.py --variant_mode")
