#!/usr/bin/env python3
"""
VCTK/DEMAND Dataset 降噪處理

對 noisy/*.wav 目錄中的所有檔案跑 V3-2 (MMSE-LSA) 降噪，
輸出到 output_vctk/ 目錄。

用法:
    python regenerate_all_vctk.py --dataset-dir /path/to/vctk_demand
    python regenerate_all_vctk.py --dataset-dir /path/to/vctk_demand --config config/custom.yaml
"""

import numpy as np
import librosa
import soundfile as sf
import os
import argparse
from pathlib import Path
from glob import glob

from regenerate_all import load_config, get_denoiser_params_from_config
from denoisers import MmseLsaDenoiser, OmlsaDenoiser


def main():
    parser = argparse.ArgumentParser(description='VCTK/DEMAND Dataset 降噪 (V3-2)')
    parser.add_argument('--dataset-dir', type=str, required=True,
                        help='Dataset 路徑 (含 noisy/ 和 clean/ 子目錄)')
    parser.add_argument('--config', type=str, default='config/v3_2_config.yaml',
                        help='V3-2 配置文件 (預設: config/v3_2_config.yaml)')
    parser.add_argument('--output-dir', type=str, default='output_vctk',
                        help='輸出目錄 (預設: output_vctk/)')
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    noisy_dir = dataset_dir / 'noisy'
    output_dir = Path(args.output_dir)

    # 檢查目錄
    if not noisy_dir.exists():
        print(f"找不到 noisy 目錄: {noisy_dir}")
        return

    # 掃描所有 wav 檔案
    noisy_files = sorted(glob(str(noisy_dir / '*.wav')))
    if not noisy_files:
        print(f"noisy 目錄中沒有 wav 檔案: {noisy_dir}")
        return

    os.makedirs(output_dir, exist_ok=True)

    # 加載配置
    config = load_config(args.config)
    target_sr = 16000

    print("=" * 100)
    print("VCTK/DEMAND Dataset 降噪 (V3-2 MMSE-LSA)")
    print("=" * 100)
    print(f"Dataset: {dataset_dir}")
    print(f"檔案數量: {len(noisy_files)}")
    print(f"配置: {args.config}")
    print(f"輸出目錄: {output_dir}/")
    print("=" * 100)

    processed = 0
    errors = 0
    total = len(noisy_files)

    for noisy_path in noisy_files:
        filename = os.path.basename(noisy_path)
        output_path = output_dir / filename

        try:
            # 載入並 resample 到 16kHz
            noisy, original_sr = librosa.load(noisy_path, sr=None)
            if original_sr != target_sr:
                noisy = librosa.resample(noisy, orig_sr=original_sr, target_sr=target_sr)
            sr = target_sr

            # 從配置獲取參數並建立降噪器
            fft_size = config['audio']['fft_size']
            denoiser_params = get_denoiser_params_from_config(config, sr, fft_size)
            # 依 config 版本自動選擇 denoiser class
            if str(config.get('version', '')).startswith('4') or 'wind_handler' in config:
                wh = config.get('wind_handler', {})
                denoiser_params['enable_wind_handler'] = wh.get('enable', False)
                if 'detector' in wh:
                    denoiser_params['wind_detector_config'] = wh['detector']
                if 'freq_adaptive' in wh:
                    denoiser_params['freq_adaptive_config'] = wh['freq_adaptive']
                if 'transient_suppressor' in wh:
                    ts = dict(wh['transient_suppressor'])
                    denoiser_params['enable_transient_suppressor'] = ts.pop('enable', False)
                    denoiser_params['transient_suppressor_config'] = ts
                denoiser = OmlsaDenoiser(**denoiser_params)
            else:
                denoiser = MmseLsaDenoiser(**denoiser_params)

            # 降噪
            enhanced = denoiser.denoise(noisy)

            # 保存
            sf.write(str(output_path), enhanced, sr)

            processed += 1
            print(f"  [{processed}/{total}] {filename} (sr={original_sr}->{sr}Hz)")

        except Exception as e:
            errors += 1
            processed += 1
            print(f"  [{processed}/{total}] {filename} - ERROR: {e}")

    print("\n" + "=" * 100)
    print(f"完成! 成功: {processed - errors}/{total}, 失敗: {errors}")
    print(f"輸出目錄: {output_dir}/")
    print("=" * 100)


if __name__ == "__main__":
    main()
