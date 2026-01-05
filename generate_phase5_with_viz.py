"""
Phase 5 Generation Script with Visualization
自動生成降噪輸出 + 可視化圖表

功能:
1. 讀取 4 組配置 (V3-3-Natural/Balanced, V3-4-Natural/Balanced)
2. 為每個測試用例生成降噪輸出
3. 自動生成可視化圖表 (Time Domain + Spectrogram + SPP)
4. 保存到 denoised_phase5/ 和 visualizations/

輸出:
- 48 個降噪音頻文件 (4 variants × 12 test cases)
- 48 個可視化圖表 (4 variants × 12 test cases)
"""

import os
import sys
import yaml
import numpy as np
import soundfile as sf
import matplotlib.pyplot as plt
import librosa
import librosa.display
from pathlib import Path
from typing import Dict, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from denoisers.v3_3_pmmse import PmmseDenoiser
from denoisers.v3_4_laplacian_mmse import LaplacianMmseDenoiser


def load_config(config_path: str) -> dict:
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_denoiser_from_config(config: dict):
    """根據配置創建降噪器"""
    method = config['gain_calculation']['method']

    # 準備 SNR adaptive 配置
    snr_adaptive_config = None
    if config.get('snr_adaptive', {}).get('enable', False):
        snr_adaptive_config = {
            'enable': True,
            'base_g_min_db': config['snr_adaptive'].get('base_g_min_db', -15.0),
            'snr_smoothing': config['snr_adaptive'].get('snr_smoothing', 0.9),
            'clean_detection': config['snr_adaptive'].get('clean_detection', False),
            'clean_bypass': config['snr_adaptive'].get('clean_bypass', False)
        }

    common_params = {
        'sample_rate': config['audio']['sample_rate'],
        'frame_size_ms': config['audio']['frame_size_ms'],
        'frame_shift_ms': config['audio']['frame_shift_ms'],
        'fft_size': config['audio']['fft_size'],
        'alpha_noise': config['noise_estimation']['alpha'],
        'alpha_xi': config['spp']['alpha_xi'],
        'q': config['spp']['q'],
        'xi_min_db': config['spp']['xi_min_db'],
        'g_min_db': config['gain_calculation']['g_min_db'],
        'alpha_g': config['gain_calculation']['alpha_g'],
        'num_init_frames': config['noise_estimation']['num_init_frames'],
        'enable_noise_tracking': config['noise_tracking']['enable'],
        'snr_adaptive_config': snr_adaptive_config
    }

    if method == 'pmmse':
        common_params['use_spp_weighting'] = config['gain_calculation'].get('use_spp_weighting', True)
        return PmmseDenoiser(**common_params)
    elif method == 'laplacian_mmse':
        common_params['beta_laplacian'] = config['gain_calculation'].get('beta_laplacian', 1.5)
        return LaplacianMmseDenoiser(**common_params)
    else:
        raise ValueError(f"Unknown method: {method}")


def create_visualization(
    noisy_signal: np.ndarray,
    enhanced_signal: np.ndarray,
    spp_history: np.ndarray,
    sample_rate: int,
    output_path: str,
    test_case: str
):
    """
    創建 6-panel 可視化圖表

    布局:
    Row 1: Time Domain (Noisy, Enhanced)
    Row 2: Spectrogram (Noisy, Enhanced)
    Row 3: SPP Curve (Time Series), SPP Heatmap
    """
    fig, axes = plt.subplots(3, 2, figsize=(16, 12))
    fig.suptitle(f'{test_case}', fontsize=16, fontweight='bold')

    # 時間軸
    time_noisy = np.arange(len(noisy_signal)) / sample_rate
    time_enhanced = np.arange(len(enhanced_signal)) / sample_rate

    # ========== Row 1: Time Domain ==========
    # Noisy
    axes[0, 0].plot(time_noisy, noisy_signal, linewidth=0.5, color='red', alpha=0.7)
    axes[0, 0].set_title('Time Domain - Noisy', fontsize=12)
    axes[0, 0].set_xlabel('Time (s)')
    axes[0, 0].set_ylabel('Amplitude')
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].set_ylim(-1.0, 1.0)

    # Enhanced
    axes[0, 1].plot(time_enhanced, enhanced_signal, linewidth=0.5, color='blue', alpha=0.7)
    axes[0, 1].set_title('Time Domain - Enhanced', fontsize=12)
    axes[0, 1].set_xlabel('Time (s)')
    axes[0, 1].set_ylabel('Amplitude')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].set_ylim(-1.0, 1.0)

    # ========== Row 2: Spectrogram ==========
    # Compute spectrograms
    D_noisy = librosa.stft(noisy_signal, n_fft=512, hop_length=160, win_length=320)
    D_enhanced = librosa.stft(enhanced_signal, n_fft=512, hop_length=160, win_length=320)

    DB_noisy = librosa.amplitude_to_db(np.abs(D_noisy), ref=np.max)
    DB_enhanced = librosa.amplitude_to_db(np.abs(D_enhanced), ref=np.max)

    # Noisy Spectrogram
    img1 = librosa.display.specshow(
        DB_noisy, sr=sample_rate, hop_length=160,
        x_axis='time', y_axis='hz', ax=axes[1, 0], cmap='viridis'
    )
    axes[1, 0].set_title('Spectrogram - Noisy', fontsize=12)
    axes[1, 0].set_ylim(0, 8000)
    fig.colorbar(img1, ax=axes[1, 0], format='%+2.0f dB')

    # Enhanced Spectrogram
    img2 = librosa.display.specshow(
        DB_enhanced, sr=sample_rate, hop_length=160,
        x_axis='time', y_axis='hz', ax=axes[1, 1], cmap='viridis'
    )
    axes[1, 1].set_title('Spectrogram - Enhanced', fontsize=12)
    axes[1, 1].set_ylim(0, 8000)
    fig.colorbar(img2, ax=axes[1, 1], format='%+2.0f dB')

    # ========== Row 3: SPP ==========
    # SPP Curve (average over frequency)
    spp_mean = np.mean(spp_history, axis=1)  # (n_frames,)
    frame_shift_ms = 10
    time_frames = np.arange(len(spp_mean)) * (frame_shift_ms / 1000.0)

    axes[2, 0].plot(time_frames, spp_mean, linewidth=1.5, color='green')
    axes[2, 0].set_title('SPP Curve (Average over Frequency)', fontsize=12)
    axes[2, 0].set_xlabel('Time (s)')
    axes[2, 0].set_ylabel('SPP')
    axes[2, 0].set_ylim(0, 1.0)
    axes[2, 0].grid(True, alpha=0.3)
    axes[2, 0].axhline(y=0.5, color='red', linestyle='--', linewidth=1, alpha=0.5, label='SPP = 0.5')
    axes[2, 0].legend()

    # SPP Heatmap (time × frequency)
    # spp_history shape: (n_frames, n_freqs)
    # 需要轉置以便 imshow 正確顯示 (頻率 × 時間)
    img3 = axes[2, 1].imshow(
        spp_history.T,  # 轉置: (n_freqs, n_frames)
        aspect='auto',
        origin='lower',
        extent=[0, time_frames[-1], 0, sample_rate / 2],
        cmap='hot',
        vmin=0,
        vmax=1
    )
    axes[2, 1].set_title('SPP Heatmap (Time × Frequency)', fontsize=12)
    axes[2, 1].set_xlabel('Time (s)')
    axes[2, 1].set_ylabel('Frequency (Hz)')
    axes[2, 1].set_ylim(0, 8000)
    fig.colorbar(img3, ax=axes[2, 1], label='SPP')

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✅ Visualization saved: {output_path}")


def process_variant(
    variant_name: str,
    config_path: str,
    test_cases: list,
    noisy_dir: str,
    output_audio_dir: str,
    output_viz_dir: str
):
    """處理一個配置變體"""
    print(f"\n{'='*60}")
    print(f"Processing: {variant_name}")
    print(f"Config: {config_path}")
    print(f"{'='*60}")

    # 1. 加載配置
    config = load_config(config_path)

    # 2. 創建降噪器
    denoiser = create_denoiser_from_config(config)
    sample_rate = config['audio']['sample_rate']

    print(f"\nDenoiser: {denoiser}")
    print(f"Parameters: {denoiser.get_params()}")

    # 3. 創建輸出目錄
    variant_audio_dir = os.path.join(output_audio_dir, variant_name)
    variant_viz_dir = os.path.join(output_viz_dir, variant_name)
    os.makedirs(variant_audio_dir, exist_ok=True)
    os.makedirs(variant_viz_dir, exist_ok=True)

    # 4. 處理每個測試用例
    for test_case in test_cases:
        print(f"\n  Processing: {test_case}")

        # 讀取帶噪音頻
        noisy_path = os.path.join(noisy_dir, f"{test_case}.wav")
        if not os.path.exists(noisy_path):
            print(f"  ⚠️ File not found: {noisy_path}")
            continue

        noisy_signal, sr = sf.read(noisy_path)

        # 重採樣（如果需要）
        if sr != sample_rate:
            noisy_signal = librosa.resample(noisy_signal, orig_sr=sr, target_sr=sample_rate)

        # 降噪 + 獲取 SPP 數據
        enhanced_signal, spp_history = denoiser.denoise(noisy_signal, return_spp=True)

        # 保存降噪音頻
        output_audio_path = os.path.join(variant_audio_dir, f"{test_case}.wav")
        sf.write(output_audio_path, enhanced_signal, sample_rate)
        print(f"  ✅ Audio saved: {output_audio_path}")

        # 生成可視化
        output_viz_path = os.path.join(variant_viz_dir, f"{test_case}.png")
        create_visualization(
            noisy_signal,
            enhanced_signal,
            spp_history,
            sample_rate,
            output_viz_path,
            f"{variant_name} - {test_case}"
        )

        # 重置降噪器狀態
        denoiser.reset()

    print(f"\n✅ {variant_name} completed!")


def main():
    """主函數"""
    print("\n" + "="*60)
    print("Phase 5 Generation with Visualization")
    print("="*60)

    # 定義路徑
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, 'config')
    noisy_dir = os.path.join(base_dir, 'test_wav', 'wav')  # ✅ 修正路徑
    output_audio_dir = os.path.join(base_dir, 'denoised_phase5')
    output_viz_dir = os.path.join(base_dir, 'visualizations')

    # 定義 4 組配置
    variants = [
        ('V3-3-Natural', os.path.join(config_dir, 'v3_3_natural.yaml')),
        ('V3-3-Balanced', os.path.join(config_dir, 'v3_3_balanced.yaml')),
        ('V3-4-Natural', os.path.join(config_dir, 'v3_4_natural.yaml')),
        ('V3-4-Balanced', os.path.join(config_dir, 'v3_4_balanced.yaml'))
    ]

    # 定義測試用例 (12 個)
    noise_types = ['babble', 'car', 'street']
    snr_levels = [0, 5, 10, 15]
    test_cases = [f"{noise}_{snr}dB" for noise in noise_types for snr in snr_levels]

    print(f"\nTest Cases ({len(test_cases)}):")
    for tc in test_cases:
        print(f"  - {tc}")

    print(f"\nVariants ({len(variants)}):")
    for vname, _ in variants:
        print(f"  - {vname}")

    print(f"\nTotal Files to Generate:")
    print(f"  - Audio: {len(variants)} × {len(test_cases)} = {len(variants) * len(test_cases)} WAV files")
    print(f"  - Visualizations: {len(variants)} × {len(test_cases)} = {len(variants) * len(test_cases)} PNG files")

    # 處理每個變體
    for variant_name, config_path in variants:
        if not os.path.exists(config_path):
            print(f"\n⚠️ Config file not found: {config_path}")
            continue

        process_variant(
            variant_name,
            config_path,
            test_cases,
            noisy_dir,
            output_audio_dir,
            output_viz_dir
        )

    print("\n" + "="*60)
    print("✅ Phase 5 Generation Complete!")
    print("="*60)
    print(f"\nOutput Locations:")
    print(f"  - Audio: {output_audio_dir}")
    print(f"  - Visualizations: {output_viz_dir}")


if __name__ == '__main__':
    main()
