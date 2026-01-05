#!/usr/bin/env python3
"""
重新生成所有 7 種方法的原始降噪輸出

保持原始採樣率，不進行 resample
用於後續的 improvement 指標計算

v2.0: 使用配置文件參數進行優化
"""

import numpy as np
import librosa
import soundfile as sf
import os
import yaml
from pathlib import Path
from denoisers import (
    SpectralSubtractionDenoiser,
    WienerDenoiser,
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
    LaplacianMmseDenoiser,
    ImcraOmlsaDenoiser
)

def load_config(config_path):
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# 輸出目錄（原始輸出，未 resample）
output_dir = 'denoised_original'
os.makedirs(output_dir, exist_ok=True)

print("=" * 100)
print("重新生成所有 7 種方法的原始降噪輸出")
print("=" * 100)
print(f"測試用例: {len(test_cases)} 個")
print(f"方法: V1, V2, V3, V3-2, V3-3, V3-4, V4")
print(f"預期輸出: {len(test_cases) * 7} 個文件")
print(f"輸出目錄: {output_dir}/")
print("=" * 100)

# 方法配置（包含配置文件路徑）
methods = {
    'V1': {
        'class': SpectralSubtractionDenoiser,
        'config': 'config/v1_config.yaml'
    },
    'V2': {
        'class': WienerDenoiser,
        'config': 'config/v2_config.yaml'
    },
    'V3': {
        'class': SppMmseDenoiser,
        'config': 'config/v3_config.yaml'
    },
    'V3-2': {
        'class': MmseLsaDenoiser,
        'config': 'config/v3_2_config.yaml'
    },
    'V3-3': {
        'class': PmmseDenoiser,
        'config': 'config/v3_3_config.yaml'
    },
    'V3-4': {
        'class': LaplacianMmseDenoiser,
        'config': 'config/v3_4_config.yaml'
    },
    'V4': {
        'class': ImcraOmlsaDenoiser,
        'config': 'config/v4_config.yaml'
    }
}

def get_denoiser_params_from_config(config, sr, fft_size):
    """從配置文件提取降噪器參數"""
    params = {
        'sample_rate': sr,
        'fft_size': fft_size,
        'frame_size_ms': config['audio']['frame_size_ms'],
        'frame_shift_ms': config['audio']['frame_shift_ms']
    }

    # 添加噪聲追蹤（如果啟用）
    if config.get('noise_tracking', {}).get('enable', False):
        params['enable_noise_tracking'] = True

    # V1 特殊參數
    if 'gain_calculation' in config:
        gc = config['gain_calculation']
        if gc.get('method') == 'spectral_subtraction':
            params.update({
                'alpha': gc.get('alpha', 1.0),
                'beta': gc.get('beta', 0.02),
                'alpha_smooth': gc.get('alpha_smooth', 0.8)
            })
        # V3 (SPP-MMSE) 支持 use_full_formula
        elif gc.get('method') == 'spp_mmse':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7),
                'use_full_formula': gc.get('use_full_formula', False)
            })
        # V3-2, V3-3, V3-4 不支持 use_full_formula
        elif gc.get('method') in ['mmse_lsa', 'pmmse', 'laplacian_mmse']:
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7)
            })
        # V4 (OMLSA)
        elif gc.get('method') == 'omlsa':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7)
            })

    # SPP 參數
    if 'spp' in config:
        spp = config['spp']
        params.update({
            'alpha_xi': spp.get('alpha_xi', 0.98),
            'q': spp.get('q', 0.5),
            'xi_min_db': spp.get('xi_min_db', -25.0)
        })

    # IMCRA 噪聲估計參數（V4）
    if 'noise_estimation' in config and config['noise_estimation'].get('method') == 'imcra':
        ne = config['noise_estimation']
        params.update({
            'alpha_s': ne.get('alpha_s', 0.9),
            'alpha_d': ne.get('alpha_d', 0.85),
            'L': ne.get('L', 150),
            'delta_db': ne.get('delta_db', 5.0)
        })

    return params

# 生成
processed = 0
total = len(methods) * len(test_cases)

for method_name, method_config in methods.items():
    print(f"\n處理方法: {method_name}")
    print("-" * 100)

    # 加載配置文件
    config = load_config(method_config['config'])

    for test_id in test_cases:
        # ✅ 使用正確的輸入文件：append_silence 目錄下的 prepend 文件
        input_file = f"test_wav/wav/append_silence/{test_id}_prepend.wav"
        output_file = f"{output_dir}/{method_name}_{test_id}.wav"

        if not os.path.exists(input_file):
            processed += 1
            print(f"  [{processed}/{total}] ⚠️  {test_id} - 找不到輸入文件")
            continue

        try:
            # 加載並統一重採樣到 16kHz
            noisy, original_sr = librosa.load(input_file, sr=None)

            # 強制重採樣到 16kHz
            target_sr = 16000
            if original_sr != target_sr:
                noisy = librosa.resample(noisy, orig_sr=original_sr, target_sr=target_sr)
            sr = target_sr

            # 使用配置文件的 FFT size（統一為 512）
            fft_size = config['audio']['fft_size']

            # 從配置文件獲取參數
            denoiser_params = get_denoiser_params_from_config(config, sr, fft_size)

            # 創建降噪器
            denoiser = method_config['class'](**denoiser_params)

            # 處理
            enhanced = denoiser.denoise(noisy)

            # 保存（保持原始採樣率）
            sf.write(output_file, enhanced, sr)

            processed += 1
            print(f"  [{processed}/{total}] ✓ {test_id} (sr={sr}Hz)")

        except Exception as e:
            processed += 1
            print(f"  [{processed}/{total}] ✗ {test_id} - ERROR: {e}")

print("\n" + "=" * 100)
print(f"完成! 成功生成 {processed}/{total} 個文件")
print(f"輸出目錄: {output_dir}/")
print("=" * 100)
