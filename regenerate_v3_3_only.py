#!/usr/bin/env python3
"""
只重新生成 V3-3 的降噪輸出（啟用 SNR Adaptive）

修復 V3-3 缺少 SNR adaptive 配置的問題
"""

import numpy as np
import librosa
import soundfile as sf
import os
import yaml
from pathlib import Path
from denoisers import PmmseDenoiser

def load_config(config_path):
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# 輸出目錄
output_dir = 'denoised_original'
os.makedirs(output_dir, exist_ok=True)

print("=" * 80)
print("重新生成 V3-3 (PMMSE) 降噪輸出 - 啟用 SNR Adaptive")
print("=" * 80)
print(f"測試用例: {len(test_cases)} 個")
print(f"輸出目錄: {output_dir}/")
print("=" * 80)

# 加載 V3-3 配置
config_path = 'config/v3_3_config.yaml'
print(f"\n加載配置: {config_path}")
config = load_config(config_path)

# 檢查 SNR adaptive 是否啟用
if config.get('snr_adaptive', {}).get('enable', False):
    print("✅ SNR Adaptive 已啟用")
    print(f"   base_g_min_db: {config['snr_adaptive']['base_g_min_db']}")
else:
    print("⚠️  SNR Adaptive 未啟用")

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
use_spp_weighting = config['gain_calculation']['use_spp_weighting']

# SNR adaptive 參數
snr_adaptive_config = config.get('snr_adaptive', {})

# 創建 V3-3 降噪器
denoiser = PmmseDenoiser(
    sample_rate=sample_rate,
    frame_size_ms=frame_size_ms,
    frame_shift_ms=frame_shift_ms,
    fft_size=fft_size,
    alpha_noise=alpha_noise,
    num_init_frames=num_init_frames,
    alpha_xi=alpha_xi,
    q=q,
    xi_min_db=xi_min_db,
    g_min_db=g_min_db,
    alpha_g=alpha_g,
    use_spp_weighting=use_spp_weighting,
    snr_adaptive_config=snr_adaptive_config
)

print(f"\n降噪器參數:")
print(f"  Sample Rate: {sample_rate} Hz")
print(f"  Frame: {frame_size_ms} ms / {frame_shift_ms} ms")
print(f"  FFT Size: {fft_size}")
print(f"  g_min: {g_min_db} dB")
print(f"  alpha_g: {alpha_g}")
print(f"  alpha_xi: {alpha_xi}")
print(f"  q: {q}")

success_count = 0
fail_count = 0

print(f"\n開始處理...")
print("-" * 80)

for i, case in enumerate(test_cases, 1):
    noisy_path = f'test_wav/wav/{case}.wav'
    output_path = f'{output_dir}/{case}_v3_3.wav'

    if not os.path.exists(noisy_path):
        print(f"[{i}/{len(test_cases)}] ⚠️  跳過: {case} (文件不存在)")
        fail_count += 1
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

        print(f"[{i}/{len(test_cases)}] ✅ {case}")
        success_count += 1

    except Exception as e:
        print(f"[{i}/{len(test_cases)}] ❌ {case}: {e}")
        fail_count += 1

print("-" * 80)
print(f"\n完成: ✅ {success_count} 成功, ❌ {fail_count} 失敗")
print("=" * 80)
