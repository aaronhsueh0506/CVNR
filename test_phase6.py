#!/usr/bin/env python3
"""
Phase 6 測試腳本 - 快速收斂與過渡優化

功能:
1. 讀取 3 組 Phase 6 配置 (Natural/Balanced/Aggressive)
2. 對單個測試用例生成降噪輸出
3. 測試指標:
   - SPP 與語音重疊情況
   - 時域信號與 clean 重疊
   - 是否過度抑制
   - PESQ/STOI 改善

測試用例: car_10dB (包含過渡段)
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

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from denoisers.v3_3_pmmse import PmmseDenoiser
from utils.metrics import calculate_pesq, calculate_stoi
from utils.metrics_loizou import composite_measure


def load_config(config_path: str) -> dict:
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_denoiser_from_config(config: dict) -> PmmseDenoiser:
    """根據配置創建 PMMSE 降噪器"""
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

    # Phase 6: 準備快速啟動和過渡檢測配置
    fast_startup_cfg = config.get('fast_startup', {})
    enable_fast_startup = fast_startup_cfg.get('enable', False)

    transition_cfg = config.get('transition_detection', {})
    enable_transition = transition_cfg.get('enable', False)

    # 創建降噪器
    denoiser = PmmseDenoiser(
        sample_rate=config['audio']['sample_rate'],
        frame_size_ms=config['audio']['frame_size_ms'],
        frame_shift_ms=config['audio']['frame_shift_ms'],
        fft_size=config['audio']['fft_size'],
        alpha_noise=config['noise_estimation']['alpha'],
        alpha_xi=config['spp']['alpha_xi'],
        q=config['spp']['q'],
        xi_min_db=config['spp']['xi_min_db'],
        g_min_db=config['gain_calculation']['g_min_db'],
        alpha_g=config['gain_calculation']['alpha_g'],
        use_spp_weighting=config['gain_calculation'].get('use_spp_weighting', True),
        num_init_frames=config['noise_estimation']['num_init_frames'],
        enable_noise_tracking=config['noise_tracking']['enable'],
        snr_adaptive_config=snr_adaptive_config,
        # Phase 6 參數
        enable_fast_startup=enable_fast_startup,
        startup_frames=fast_startup_cfg.get('startup_frames', 50),
        alpha_noise_startup=fast_startup_cfg.get('alpha_noise_startup', 0.7),
        alpha_xi_startup=fast_startup_cfg.get('alpha_xi_startup', 0.7),
        alpha_g_startup=fast_startup_cfg.get('alpha_g_startup', 0.4),
        num_init_frames_fast=fast_startup_cfg.get('num_init_frames_fast', 10),
        enable_transition_detection=enable_transition,
        transition_config=transition_cfg if enable_transition else None
    )

    return denoiser


def test_variant(
    variant_name: str,
    config_path: str,
    clean_path: str,
    noisy_path: str,
    output_dir: str
):
    """測試一個配置變體"""
    print(f"\n{'='*60}")
    print(f"Testing: {variant_name}")
    print(f"Config: {config_path}")
    print(f"{'='*60}\n")

    # 1. 加載配置
    config = load_config(config_path)

    # 2. 創建降噪器
    denoiser = create_denoiser_from_config(config)
    sample_rate = config['audio']['sample_rate']

    print(f"Denoiser: {denoiser}")
    print(f"Parameters: {denoiser.get_params()}\n")

    # 3. 讀取音頻
    clean_signal, sr_clean = sf.read(clean_path)
    noisy_signal, sr_noisy = sf.read(noisy_path)

    if sr_clean != sample_rate:
        clean_signal = librosa.resample(clean_signal, orig_sr=sr_clean, target_sr=sample_rate)
    if sr_noisy != sample_rate:
        noisy_signal = librosa.resample(noisy_signal, orig_sr=sr_noisy, target_sr=sample_rate)

    # 4. 降噪 + 獲取 SPP
    print("Processing...")
    enhanced_signal, spp_history = denoiser.denoise(noisy_signal, return_spp=True)

    # 5. 保存降噪音頻
    os.makedirs(output_dir, exist_ok=True)
    output_audio_path = os.path.join(output_dir, f"{variant_name}.wav")
    sf.write(output_audio_path, enhanced_signal, sample_rate)
    print(f"✅ Audio saved: {output_audio_path}")

    # 6. 評估指標
    print("\nEvaluating metrics...")

    # 確保長度一致
    min_len = min(len(clean_signal), len(noisy_signal), len(enhanced_signal))
    clean_signal = clean_signal[:min_len]
    noisy_signal = noisy_signal[:min_len]
    enhanced_signal = enhanced_signal[:min_len]

    # Composite measures
    noisy_metrics = composite_measure(clean_signal, noisy_signal, sample_rate)
    enhanced_metrics = composite_measure(clean_signal, enhanced_signal, sample_rate)

    # PESQ/STOI
    noisy_pesq = calculate_pesq(clean_signal, noisy_signal, sample_rate)
    enhanced_pesq = calculate_pesq(clean_signal, enhanced_signal, sample_rate)
    noisy_stoi = calculate_stoi(clean_signal, noisy_signal, sample_rate)
    enhanced_stoi = calculate_stoi(clean_signal, enhanced_signal, sample_rate)

    # Improvement
    pesq_delta = enhanced_pesq - noisy_pesq
    stoi_delta = enhanced_stoi - noisy_stoi
    segsnr_delta = enhanced_metrics['segSNR'] - noisy_metrics['segSNR']

    print(f"\nResults:")
    print(f"  PESQ: {noisy_pesq:.3f} → {enhanced_pesq:.3f} ({pesq_delta:+.3f})")
    print(f"  STOI: {noisy_stoi:.4f} → {enhanced_stoi:.4f} ({stoi_delta:+.4f})")
    print(f"  segSNR: {noisy_metrics['segSNR']:.2f} → {enhanced_metrics['segSNR']:.2f} dB ({segsnr_delta:+.2f} dB)")

    # 7. 生成可視化
    print("\nGenerating visualization...")
    create_analysis_plot(
        clean_signal,
        noisy_signal,
        enhanced_signal,
        spp_history,
        sample_rate,
        variant_name,
        output_dir,
        {
            'PESQ Δ': pesq_delta,
            'STOI Δ': stoi_delta,
            'segSNR Δ': segsnr_delta
        }
    )

    print(f"\n✅ {variant_name} completed!\n")

    # 重置降噪器
    denoiser.reset()

    return {
        'PESQ_Δ': pesq_delta,
        'STOI_Δ': stoi_delta,
        'segSNR_Δ': segsnr_delta
    }


def create_analysis_plot(
    clean_signal,
    noisy_signal,
    enhanced_signal,
    spp_history,
    sample_rate,
    variant_name,
    output_dir,
    metrics
):
    """創建分析圖表"""
    fig, axes = plt.subplots(4, 1, figsize=(16, 14))
    fig.suptitle(f'Phase 6 Analysis - {variant_name}', fontsize=16, fontweight='bold')

    time_clean = np.arange(len(clean_signal)) / sample_rate
    time_noisy = np.arange(len(noisy_signal)) / sample_rate
    time_enhanced = np.arange(len(enhanced_signal)) / sample_rate

    # Row 1: Time Domain Overlay
    axes[0].plot(time_clean, clean_signal, linewidth=0.8, color='green', alpha=0.7, label='Clean')
    axes[0].plot(time_noisy, noisy_signal, linewidth=0.6, color='red', alpha=0.5, label='Noisy')
    axes[0].plot(time_enhanced, enhanced_signal, linewidth=0.8, color='blue', alpha=0.7, label='Enhanced')
    axes[0].set_title('Time Domain - Overlay', fontsize=12)
    axes[0].set_xlabel('Time (s)')
    axes[0].set_ylabel('Amplitude')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(-1.0, 1.0)

    # Row 2: Clean vs Enhanced
    axes[1].plot(time_clean, clean_signal, linewidth=0.8, color='green', alpha=0.7, label='Clean')
    axes[1].plot(time_enhanced, enhanced_signal, linewidth=0.8, color='blue', alpha=0.7, label='Enhanced')
    axes[1].set_title('Clean vs Enhanced - Checking Suppression', fontsize=12)
    axes[1].set_xlabel('Time (s)')
    axes[1].set_ylabel('Amplitude')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim(-1.0, 1.0)

    # Row 3: SPP Curve
    spp_mean = np.mean(spp_history, axis=1)
    frame_shift_ms = 10
    time_frames = np.arange(len(spp_mean)) * (frame_shift_ms / 1000.0)

    axes[2].plot(time_frames, spp_mean, linewidth=1.5, color='purple', label='SPP')
    axes[2].axhline(y=0.5, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Threshold=0.5')
    axes[2].set_title('SPP (Speech Presence Probability)', fontsize=12)
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('SPP')
    axes[2].set_ylim(0, 1.0)
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    # Row 4: Metrics Summary
    axes[3].axis('off')
    metrics_text = (
        f"Metrics Summary:\n\n"
        f"PESQ Δ:   {metrics['PESQ Δ']:+.3f}\n"
        f"STOI Δ:   {metrics['STOI Δ']:+.4f}\n"
        f"segSNR Δ: {metrics['segSNR Δ']:+.2f} dB\n\n"
        f"檢查要點:\n"
        f"1. 時域重疊: Enhanced 應貼近 Clean\n"
        f"2. SPP: 應與語音段重疊\n"
        f"3. 過度抑制: Enhanced 不應明顯小於 Clean\n"
        f"4. PESQ/STOI: 應為正值"
    )
    axes[3].text(0.1, 0.5, metrics_text, fontsize=14, verticalalignment='center',
                 family='monospace', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()

    output_path = os.path.join(output_dir, f"{variant_name}.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ Visualization saved: {output_path}")


def main():
    """主函數"""
    print("\n" + "="*60)
    print("Phase 6 Testing Script")
    print("="*60)

    # 定義路徑
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, 'config')
    test_dir = os.path.join(base_dir, 'test_wav', 'wav')
    output_dir = os.path.join(base_dir, 'phase6_test_results')

    # 測試用例: car_10dB (包含過渡段)
    test_case = 'car_10dB'
    clean_path = os.path.join(test_dir, 'clean.wav')
    noisy_path = os.path.join(test_dir, f'{test_case}.wav')

    print(f"\nTest case: {test_case}")
    print(f"Clean: {clean_path}")
    print(f"Noisy: {noisy_path}")

    # 定義 3 組配置
    variants = [
        ('Natural', os.path.join(config_dir, 'v3_3_phase6_natural.yaml')),
        ('Balanced', os.path.join(config_dir, 'v3_3_phase6_balanced.yaml')),
        ('Aggressive', os.path.join(config_dir, 'v3_3_phase6_aggressive.yaml'))
    ]

    # 測試每個變體
    results = {}
    for variant_name, config_path in variants:
        if not os.path.exists(config_path):
            print(f"\n⚠️ Config file not found: {config_path}")
            continue

        results[variant_name] = test_variant(
            variant_name,
            config_path,
            clean_path,
            noisy_path,
            output_dir
        )

    # 打印摘要
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    print(f"{'Variant':<15} {'PESQ Δ':>10} {'STOI Δ':>10} {'segSNR Δ':>12}")
    print("-"*60)
    for variant_name in ['Natural', 'Balanced', 'Aggressive']:
        if variant_name in results:
            r = results[variant_name]
            print(f"{variant_name:<15} {r['PESQ_Δ']:+.3f}      {r['STOI_Δ']:+.4f}     {r['segSNR_Δ']:+.2f} dB")

    print("\n" + "="*60)
    print("✅ Phase 6 Testing Complete!")
    print("="*60)
    print(f"\nOutput directory: {output_dir}")
    print("\n請檢查:")
    print("1. 時域信號與 clean 重疊情況")
    print("2. SPP 是否與語音出現的地方重疊")
    print("3. 是否有過度抑制")
    print("4. PESQ/STOI 是否有因為這個修改改善")


if __name__ == '__main__':
    main()
