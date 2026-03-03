#!/usr/bin/env python3
"""
V4 VCTK + 場景轉換測試

測試案例:
1. VCTK 數據集樣本（非穩態噪聲）
2. 場景轉換案例（前 3 秒靜音或小底噪 → 突然噪聲）

配置:
- V3-2 Baseline: alpha_d=0.95, L=120
- V4 alpha_d=0: alpha_d=0.0, L=120 (僅測試 alpha_d 影響)
- V4 Full: alpha_d=0.0, L=5 (知乎全部參數)
"""

import numpy as np
import librosa
import soundfile as sf
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser

try:
    from pesq import pesq
    from pystoi import stoi
except ImportError:
    print("錯誤: 需要安裝 pesq 和 pystoi")
    sys.exit(1)


def create_baseline():
    """V3-2 Baseline"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        noise_method='mcra',
        alpha_s=0.8,
        alpha_noise=0.95,
        L=120,
        enable_eta=False
    )


def create_v4_alpha_d():
    """僅改 alpha_d=0"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        noise_method='mcra',
        alpha_s=0.8,
        alpha_noise=0.0,  # 僅此改變
        L=120,
        enable_eta=False
    )


def create_v4_full():
    """知乎全部參數"""
    return MmseLsaDenoiser(
        sample_rate=16000,
        noise_method='mcra',
        alpha_s=0.7,
        alpha_noise=0.0,
        L=5,
        enable_eta=False
    )


def generate_scene_change_audio(clean_wav, noise_type='white', snr_db=5):
    """
    生成場景轉換測試音頻
    前 3 秒: 靜音或小底噪
    後面: 正常噪聲
    """
    sr = 16000

    # 讀取 clean 音頻
    clean, _ = librosa.load(clean_wav, sr=sr)

    # 生成噪聲
    duration = len(clean) / sr
    if noise_type == 'white':
        noise = np.random.randn(len(clean))
    elif noise_type == 'pink':
        # 簡單的 pink noise 近似
        noise = np.random.randn(len(clean))
        noise = np.cumsum(noise)
        noise = noise / np.std(noise)
    else:
        noise = np.random.randn(len(clean))

    # 前 3 秒使用小底噪（-30 dB）
    samples_3s = int(3 * sr)
    if samples_3s < len(noise):
        quiet_noise = noise[:samples_3s] * 0.001  # 約 -60 dB
        normal_noise = noise[samples_3s:]

        # 調整正常噪聲到目標 SNR
        speech_power = np.mean(clean[samples_3s:] ** 2)
        noise_power = np.mean(normal_noise ** 2)
        target_noise_power = speech_power / (10 ** (snr_db / 10))
        normal_noise = normal_noise * np.sqrt(target_noise_power / noise_power)

        # 組合
        noise = np.concatenate([quiet_noise, normal_noise])

    noisy = clean + noise

    return noisy, clean, sr


def test_file(noisy, clean, sr, denoiser):
    """測試音頻"""
    # 對齊長度
    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    # 降噪
    enhanced = denoiser.denoise(noisy)

    # 再次對齊
    final_len = min(len(enhanced), len(clean))
    enhanced = enhanced[:final_len]
    clean = clean[:final_len]

    # 計算指標
    pesq_score = pesq(sr, clean, enhanced, 'wb')
    stoi_score = stoi(clean, enhanced, sr, extended=False)

    return pesq_score, stoi_score, enhanced


def main():
    # 1. 尋找 VCTK 文件
    vctk_base = Path('../VCTK_DEMAND_testset')
    vctk_files = []

    if vctk_base.exists():
        noisy_dir = vctk_base / 'noisy'
        clean_dir = vctk_base / 'clean'

        if noisy_dir.exists() and clean_dir.exists():
            # 選擇前 5 個文件作為代表
            for f in sorted(os.listdir(noisy_dir))[:5]:
                if f.endswith('.wav'):
                    vctk_files.append({
                        'noisy': str(noisy_dir / f),
                        'clean': str(clean_dir / f),
                        'name': f'VCTK_{f}'
                    })

    # 2. 生成場景轉換測試案例
    scene_change_files = []
    clean_ref = 'test_wav/wav/clean.wav'

    if os.path.exists(clean_ref):
        print("生成場景轉換測試案例...")
        output_dir = Path('test_wav/scene_change')
        output_dir.mkdir(parents=True, exist_ok=True)

        for noise_type in ['white']:
            for snr_db in [0, 10]:
                noisy, clean, sr = generate_scene_change_audio(clean_ref, noise_type, snr_db)

                # 保存測試文件
                noisy_path = output_dir / f'scene_{noise_type}_{snr_db}dB_noisy.wav'
                clean_path = output_dir / f'scene_{noise_type}_{snr_db}dB_clean.wav'

                sf.write(noisy_path, noisy, sr)
                sf.write(clean_path, clean, sr)

                scene_change_files.append({
                    'noisy': str(noisy_path),
                    'clean': str(clean_path),
                    'name': f'Scene_{noise_type}_{snr_db}dB'
                })

        print(f"✓ 生成 {len(scene_change_files)} 個場景轉換測試案例\n")

    # 3. 測試配置 (使用函數引用，不是實例)
    configs = [
        ('Baseline', create_baseline, 'V3-2: alpha_d=0.95, L=120'),
        ('V4_alpha_d', create_v4_alpha_d, 'V4: alpha_d=0.0, L=120'),
        ('V4_Full', create_v4_full, 'V4 Full: alpha_d=0.0, L=5'),
    ]

    # 4. 運行測試
    print("=" * 100)
    print("V4 VCTK + 場景轉換測試")
    print("=" * 100)
    print()

    all_results = {name: [] for name, _, _ in configs}

    # 測試 VCTK
    if vctk_files:
        print("### VCTK 數據集 ###\n")

        for file_info in vctk_files:
            print(f"--- {file_info['name']} ---")

            noisy, sr = librosa.load(file_info['noisy'], sr=16000)
            clean, _ = librosa.load(file_info['clean'], sr=16000)

            for cfg_name, denoiser_factory, desc in configs:
                try:
                    # 每次創建新的 denoiser 實例，避免狀態污染
                    denoiser = denoiser_factory()
                    pesq_score, stoi_score, _ = test_file(noisy, clean, sr, denoiser)

                    all_results[cfg_name].append({
                        'file': file_info['name'],
                        'pesq': pesq_score,
                        'stoi': stoi_score
                    })

                    print(f"  {cfg_name:15}: PESQ={pesq_score:.3f}, STOI={stoi_score:.3f}")
                except Exception as e:
                    print(f"  {cfg_name:15}: Error - {e}")
            print()

    # 測試場景轉換
    if scene_change_files:
        print("\n### 場景轉換測試（前 3 秒靜音 → 噪聲） ###\n")

        for file_info in scene_change_files:
            print(f"--- {file_info['name']} ---")

            noisy, sr = librosa.load(file_info['noisy'], sr=16000)
            clean, _ = librosa.load(file_info['clean'], sr=16000)

            for cfg_name, denoiser_factory, desc in configs:
                try:
                    # 每次創建新的 denoiser 實例
                    denoiser = denoiser_factory()
                    pesq_score, stoi_score, enhanced = test_file(noisy, clean, sr, denoiser)

                    all_results[cfg_name].append({
                        'file': file_info['name'],
                        'pesq': pesq_score,
                        'stoi': stoi_score
                    })

                    print(f"  {cfg_name:15}: PESQ={pesq_score:.3f}, STOI={stoi_score:.3f}")

                    # 保存降噪結果
                    output_path = Path(file_info['noisy']).parent / f"{file_info['name']}_{cfg_name}.wav"
                    sf.write(output_path, enhanced, sr)

                except Exception as e:
                    print(f"  {cfg_name:15}: Error - {e}")
            print()

    # 5. 匯總
    print("=" * 100)
    print("平均分數匯總")
    print("=" * 100)
    print()

    baseline_pesq = np.mean([r['pesq'] for r in all_results['Baseline']]) if all_results['Baseline'] else 0

    print(f"{'配置':15} | {'PESQ':>8} | {'STOI':>8} | {'ΔPESQ':>10} | {'說明':30}")
    print("-" * 100)

    for cfg_name, _, desc in configs:
        if not all_results[cfg_name]:
            continue

        avg_pesq = np.mean([r['pesq'] for r in all_results[cfg_name]])
        avg_stoi = np.mean([r['stoi'] for r in all_results[cfg_name]])
        delta_pesq = avg_pesq - baseline_pesq

        delta_sign = "+" if delta_pesq > 0 else ""
        print(f"{cfg_name:15} | {avg_pesq:>8.3f} | {avg_stoi:>8.3f} | {delta_sign}{delta_pesq:>9.4f} | {desc:30}")

    print()
    print("測試文件已保存到: test_wav/scene_change/")


if __name__ == "__main__":
    main()
