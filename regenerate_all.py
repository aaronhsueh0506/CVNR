#!/usr/bin/env python3
"""
重新生成所有 7 種方法的原始降噪輸出

保持原始採樣率，不進行 resample
用於後續的 improvement 指標計算

v2.0: 使用配置文件參數進行優化
v2.1: 支持 --version 和 --config 參數用於批量調參
"""

import numpy as np
import librosa
import soundfile as sf
import os
import yaml
import argparse
from pathlib import Path
from denoisers import (
    SpectralSubtractionDenoiser,
    WienerDenoiser,
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
    OmlsaMcraDenoiser,
    ImcraOmlsaDenoiser
)

def load_config(config_path):
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = ['clean'] + [f"{n}_{s}dB" for n in noise_types for s in snr_levels]  # 加入 clean.wav 高 SNR 測試

# 輸出目錄（統一到 output/）
output_dir = 'output'
os.makedirs(output_dir, exist_ok=True)

# 方法配置（包含配置文件路徑）
methods = {
    # 'V1': {
    #     'class': SpectralSubtractionDenoiser,
    #     'config': 'config/v1_config.yaml'
    # },
    # 'V2': {
    #     'class': WienerDenoiser,
    #     'config': 'config/v2_config.yaml'
    # },
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
        'class': OmlsaMcraDenoiser,
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

    # V1 特殊參數
    if 'gain_calculation' in config:
        gc = config['gain_calculation']
        if gc.get('method') == 'spectral_subtraction':
            params.update({
                'alpha': gc.get('alpha', 1.0),
                'beta': gc.get('beta', 0.02),
                'alpha_smooth': gc.get('alpha_smooth', 0.8)
            })
        # V2 Wiener 參數（含 DD）
        elif gc.get('method') == 'wiener':
            params.update({
                'min_gain': gc.get('min_gain', 0.01),
                'alpha_smooth': gc.get('alpha_smooth', 0.8),
                'use_dd': gc.get('use_dd', True),           # v2.0 DD 方法
                'alpha_dd': gc.get('alpha_dd', 0.98)        # v2.0 DD 平滑因子
            })
            # v2.1: V2 Wiener 噪聲估計支持
            if 'noise_estimation' in config:
                ne = config['noise_estimation']
                ne_method = ne.get('method', 'recursive_average')
                if ne_method == 'mcra':
                    params.update({
                        'noise_method': 'mcra',
                        'alpha_s': ne.get('alpha_s', 0.9),
                        'alpha_d': ne.get('alpha_d', 0.85),
                        'alpha_p': ne.get('alpha_p', 0.2),
                        'L': ne.get('L', 96),
                        'delta_db': ne.get('delta_db', 5.0)
                    })
                else:
                    # recursive_average 參數
                    params.update({
                        'noise_method': 'recursive_average',
                        'alpha': ne.get('alpha', 0.95),
                        'update_during_speech': ne.get('update_during_speech', False)
                    })
        # V3 (SPP-MMSE) 支持 use_full_formula
        elif gc.get('method') == 'spp_mmse':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7),
                'use_full_formula': gc.get('use_full_formula', False)
            })
        # V3-2 (MMSE-LSA)
        elif gc.get('method') == 'mmse_lsa':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7),
                'use_linear_spp_weighting': gc.get('use_linear_spp_weighting', False)
            })
        # V3-3 (PMMSE - Wolfe & Godsill β=0.5)
        elif gc.get('method') == 'pmmse':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.5),
                'use_spp_weighting': gc.get('use_spp_weighting', True)
            })
        # V3-4 (OMLSA-MCRA) 和 V4 (IMCRA-OMLSA) 都使用 omlsa 增益
        elif gc.get('method') == 'omlsa':
            params.update({
                'g_min_db': gc.get('g_min_db', -20.0),
                'alpha_g': gc.get('alpha_g', 0.7),
                'use_linear_spp_weighting': gc.get('use_linear_spp_weighting', False)
            })

    # SPP 參數
    if 'spp' in config:
        spp = config['spp']
        params.update({
            'alpha_xi': spp.get('alpha_xi', 0.98),
            'q': spp.get('q', 0.5),
            'xi_min_db': spp.get('xi_min_db', -25.0)
        })

    # 噪聲估計參數
    # V3-4 (OMLSA-MCRA) 直接使用 MCRA 參數，不需要 noise_method
    # V3/V3-2/V3-3 需要 noise_method 參數來選擇噪聲估計器
    gc = config.get('gain_calculation', {})
    is_v3_4 = gc.get('method') == 'omlsa' and config.get('noise_estimation', {}).get('method') == 'mcra'
    is_v3_series = 'spp' in config and not is_v3_4

    if 'noise_estimation' in config:
        ne = config['noise_estimation']
        ne_method = ne.get('method', 'recursive_average')

        if is_v3_4:
            # V3-4: 直接傳遞 MCRA 參數（OmlsaMcraDenoiser 不接受 noise_method）
            params.update({
                'alpha_s': ne.get('alpha_s', 0.9),
                'alpha_d': ne.get('alpha_d', 0.85),
                'alpha_p': ne.get('alpha_p', 0.2),
                'L': ne.get('L', 96),
                'delta_db': ne.get('delta_db', 5.0)
            })
        elif is_v3_series:
            if ne_method == 'mcra':
                # V3/V3-2/V3-3 的 MCRA 噪聲估計參數
                params.update({
                    'noise_method': 'mcra',
                    'alpha_s': ne.get('alpha_s', 0.9),
                    'alpha_noise': ne.get('alpha_d', 0.85),
                    'alpha_p': ne.get('alpha_p', 0.2),
                    'L': ne.get('L', 96),
                    'delta_db': ne.get('delta_db', 5.0)
                })
            elif ne_method == 'recursive_average':
                # RecursiveAverage 噪聲估計參數
                params.update({
                    'noise_method': 'recursive_average',
                    'alpha_noise': ne.get('alpha', 0.95)
                })

    # IMCRA 噪聲估計參數（V4, Cohen 2003 兩階段實現）
    if 'noise_estimation' in config and config['noise_estimation'].get('method') == 'imcra':
        ne = config['noise_estimation']
        params.update({
            'freq_smooth_width': ne.get('freq_smooth_width', 1),
            'alpha_s': ne.get('alpha_s', 0.9),
            'alpha_d': ne.get('alpha_d', 0.85),
            'L': ne.get('L', 96),
            'V': ne.get('V', 15),
            'U': ne.get('U', 8),
            'delta_db': ne.get('delta_db', 5.0),
            'delta_s_db': ne.get('delta_s_db', 3.0)
        })

    return params

def main():
    parser = argparse.ArgumentParser(description='重新生成降噪輸出')
    parser.add_argument('--version', type=str, nargs='+',
                        help='指定版本 (例: V3 V3-2 V4)，不指定則處理全部')
    parser.add_argument('--config', type=str,
                        help='使用自定義配置文件 (需配合 --version 使用單一版本)')
    args = parser.parse_args()

    # 確定要處理的方法
    if args.version:
        methods_to_process = {k: v for k, v in methods.items() if k in args.version}
        if not methods_to_process:
            print(f"❌ 未找到指定版本: {args.version}")
            print(f"可用版本: {list(methods.keys())}")
            return
    else:
        methods_to_process = methods

    # 如果提供了自定義配置，檢查是否只處理單一版本
    if args.config:
        if len(methods_to_process) != 1:
            print("❌ 使用 --config 時必須指定單一 --version")
            return
        version_name = list(methods_to_process.keys())[0]
        methods_to_process[version_name]['config'] = args.config
        print(f"使用自定義配置: {args.config}")

    # 生成
    processed = 0
    total = len(methods_to_process) * len(test_cases)

    print("=" * 100)
    print("重新生成降噪方法的原始降噪輸出")
    print("=" * 100)
    print(f"測試用例: {len(test_cases)} 個")
    print(f"處理版本: {list(methods_to_process.keys())}")
    print(f"預期輸出: {total} 個文件")
    print(f"輸出目錄: {output_dir}/")
    print("=" * 100)

    for method_name, method_config in methods_to_process.items():
        print(f"\n處理方法: {method_name}")
        print("-" * 100)

        # 加載配置文件
        config = load_config(method_config['config'])

        for test_id in test_cases:
            # ✅ 使用正確的輸入文件：append_silence 目錄下的 prepend 文件
            # Clean 測試使用特殊路徑
            if test_id == 'clean':
                input_file = "test_wav/wav/append_silence/clean_prepend.wav"
            else:
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


if __name__ == "__main__":
    main()