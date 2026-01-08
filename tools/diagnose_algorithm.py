#!/usr/bin/env python3
"""
音檔比較工具

用法：
    python3 tools/diagnose_algorithm.py audio1.wav audio2.wav
    python3 tools/diagnose_algorithm.py noisy.wav enhanced.wav --output compare
    python3 tools/diagnose_algorithm.py noisy.wav enhanced.wav --label1 Noisy --label2 Enhanced

產生：
    {output}_comparison.png      - Audition 風格比較圖（波形1, 波形2, 頻譜1, 頻譜2）
    {output}_frequency.png       - 頻率響應比較圖
"""

import argparse
import os
import sys

import numpy as np
import librosa
import librosa.display
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec


def load_audio(path: str, sr: int = 16000) -> tuple:
    """
    加載音檔並重採樣到指定採樣率

    Args:
        path: 音檔路徑
        sr: 目標採樣率 (預設 16kHz)

    Returns:
        (audio, sr): 音訊數據和採樣率
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到音檔: {path}")

    audio, orig_sr = librosa.load(path, sr=sr)
    return audio, sr


def plot_comparison(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                   label1: str, label2: str, output_path: str):
    """
    繪製 Audition 風格的比較圖

    佈局（由上到下）：
        - Waveform 1 (時域波形)
        - Waveform 2 (時域波形)
        - Spectrogram 1 (頻譜圖)
        - Spectrogram 2 (頻譜圖)

    所有子圖共用時間軸
    """
    # 確保長度一致（以較短的為準）
    min_len = min(len(audio1), len(audio2))
    audio1 = audio1[:min_len]
    audio2 = audio2[:min_len]

    duration = min_len / sr
    time_axis = np.linspace(0, duration, min_len)

    # FFT 參數
    n_fft = 512
    hop_length = 256

    # 計算頻譜圖
    D1 = librosa.stft(audio1, n_fft=n_fft, hop_length=hop_length)
    D2 = librosa.stft(audio2, n_fft=n_fft, hop_length=hop_length)
    D1_db = librosa.amplitude_to_db(np.abs(D1), ref=np.max)
    D2_db = librosa.amplitude_to_db(np.abs(D2), ref=np.max)

    # 統一 colorbar 範圍
    vmin = min(D1_db.min(), D2_db.min())
    vmax = max(D1_db.max(), D2_db.max())

    # 創建圖表：4 行 2 列（第二列用於 colorbar）
    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(4, 2, width_ratios=[1, 0.02], height_ratios=[1, 1, 1.2, 1.2],
                  hspace=0, wspace=0.02)

    # ========== Row 1: Waveform 1 ==========
    ax_wave1 = fig.add_subplot(gs[0, 0])
    ax_wave1.plot(time_axis, audio1, color='#3498DB', linewidth=0.5)
    ax_wave1.set_ylabel(f'{label1}')
    ax_wave1.set_xlim(0, duration)
    ax_wave1.set_ylim(-1.0, 1.0)
    ax_wave1.grid(True, alpha=0.3)
    ax_wave1.tick_params(labelbottom=False)
    # 右側留空（對齊 colorbar）
    ax_wave1_cbar = fig.add_subplot(gs[0, 1])
    ax_wave1_cbar.axis('off')

    # ========== Row 2: Waveform 2 ==========
    ax_wave2 = fig.add_subplot(gs[1, 0], sharex=ax_wave1)
    ax_wave2.plot(time_axis, audio2, color='#E74C3C', linewidth=0.5)
    ax_wave2.set_ylabel(f'{label2}')
    ax_wave2.set_ylim(-1.0, 1.0)
    ax_wave2.grid(True, alpha=0.3)
    ax_wave2.tick_params(labelbottom=False)
    ax_wave2_cbar = fig.add_subplot(gs[1, 1])
    ax_wave2_cbar.axis('off')

    # ========== Row 3: Spectrogram 1 ==========
    ax_spec1 = fig.add_subplot(gs[2, 0], sharex=ax_wave1)
    img1 = librosa.display.specshow(D1_db, sr=sr, hop_length=hop_length,
                                     x_axis='time', y_axis='hz', cmap='magma',
                                     ax=ax_spec1, vmin=vmin, vmax=vmax)
    ax_spec1.set_ylabel(f'{label1}')
    ax_spec1.set_xlabel('')
    ax_spec1.set_ylim(0, sr // 2)
    ax_spec1.tick_params(labelbottom=False)
    ax_spec1_cbar = fig.add_subplot(gs[2, 1])
    fig.colorbar(img1, cax=ax_spec1_cbar, format='%+2.0f dB')

    # ========== Row 4: Spectrogram 2 ==========
    ax_spec2 = fig.add_subplot(gs[3, 0], sharex=ax_wave1)
    img2 = librosa.display.specshow(D2_db, sr=sr, hop_length=hop_length,
                                     x_axis='time', y_axis='hz', cmap='magma',
                                     ax=ax_spec2, vmin=vmin, vmax=vmax)
    ax_spec2.set_ylabel(f'{label2}')
    ax_spec2.set_xlabel('Time (s)')
    ax_spec2.set_ylim(0, sr // 2)
    ax_spec2_cbar = fig.add_subplot(gs[3, 1])
    fig.colorbar(img2, cax=ax_spec2_cbar, format='%+2.0f dB')

    # 保存
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"比較圖已保存: {output_path}")


def plot_frequency_response(audio1: np.ndarray, audio2: np.ndarray, sr: int,
                           label1: str, label2: str, output_path: str):
    """
    繪製頻率響應比較圖

    計算整段音訊的平均功率譜密度 (PSD)，並在同一圖表上比較
    """
    # 確保長度一致
    min_len = min(len(audio1), len(audio2))
    audio1 = audio1[:min_len]
    audio2 = audio2[:min_len]

    # FFT 參數
    n_fft = 2048
    hop_length = 512

    # 計算 STFT
    D1 = np.abs(librosa.stft(audio1, n_fft=n_fft, hop_length=hop_length))
    D2 = np.abs(librosa.stft(audio2, n_fft=n_fft, hop_length=hop_length))

    # 計算平均功率譜（跨所有幀）
    psd1 = np.mean(D1 ** 2, axis=1)
    psd2 = np.mean(D2 ** 2, axis=1)

    # 轉換為 dB
    psd1_db = 10 * np.log10(psd1 + 1e-10)
    psd2_db = 10 * np.log10(psd2 + 1e-10)

    # 頻率軸
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    # 繪圖
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(freqs, psd1_db, color='#3498DB', linewidth=1.5, label=label1, alpha=0.8)
    ax.plot(freqs, psd2_db, color='#E74C3C', linewidth=1.5, label=label2, alpha=0.8)

    # 填充差異區域（可選）
    ax.fill_between(freqs, psd1_db, psd2_db, alpha=0.2, color='gray')

    ax.set_xlabel('Frequency (Hz)', fontsize=11)
    ax.set_ylabel('Power (dB)', fontsize=11)
    ax.set_title('Frequency Response Comparison', fontsize=12, fontweight='bold')
    ax.set_xscale('log')
    ax.set_xlim(20, sr // 2)  # 從 20Hz 開始（避免 log(0)）
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.3, which='both')

    # Y 軸間隔設為 5 dB
    from matplotlib.ticker import MultipleLocator
    ax.yaxis.set_major_locator(MultipleLocator(5))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"頻率響應圖已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='音檔比較工具 - Audition 風格顯示',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
範例：
    python3 tools/diagnose_algorithm.py noisy.wav enhanced.wav
    python3 tools/diagnose_algorithm.py audio1.wav audio2.wav --output compare
    python3 tools/diagnose_algorithm.py noisy.wav enhanced.wav --label1 Noisy --label2 Enhanced
        '''
    )
    parser.add_argument('audio1', help='第一個音檔路徑')
    parser.add_argument('audio2', help='第二個音檔路徑')
    parser.add_argument('--label1', default=None, help='第一個音檔的標籤（預設為檔名）')
    parser.add_argument('--label2', default=None, help='第二個音檔的標籤（預設為檔名）')
    parser.add_argument('--output', '-o', default='diagnosis', help='輸出檔名前綴（預設：diagnosis）')
    parser.add_argument('--sr', type=int, default=16000, help='採樣率（預設：16000）')

    args = parser.parse_args()

    # 設置標籤（預設使用檔名）
    label1 = args.label1 or os.path.splitext(os.path.basename(args.audio1))[0]
    label2 = args.label2 or os.path.splitext(os.path.basename(args.audio2))[0]

    print("=" * 60)
    print("音檔比較工具")
    print("=" * 60)

    # 載入音檔
    print(f"\n載入音檔...")
    print(f"  [{label1}] {args.audio1}")
    audio1, sr = load_audio(args.audio1, args.sr)
    print(f"    長度: {len(audio1)/sr:.2f}s, 採樣率: {sr}Hz")

    print(f"  [{label2}] {args.audio2}")
    audio2, _ = load_audio(args.audio2, args.sr)
    print(f"    長度: {len(audio2)/sr:.2f}s, 採樣率: {sr}Hz")

    # 生成比較圖
    print(f"\n生成圖表...")

    comparison_path = f"{args.output}_comparison.png"
    plot_comparison(audio1, audio2, sr, label1, label2, comparison_path)

    frequency_path = f"{args.output}_frequency.png"
    plot_frequency_response(audio1, audio2, sr, label1, label2, frequency_path)

    print("\n" + "=" * 60)
    print("完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
