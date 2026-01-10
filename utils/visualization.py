"""
SPP Visualization - 語音存在機率時頻圖

用於可視化降噪器的 SPP (Speech Presence Probability) 輸出
"""

import numpy as np
import matplotlib.pyplot as plt
import os


def plot_spp_spectrogram(
    spp_matrix: np.ndarray,
    output_path: str,
    sample_rate: int = 16000,
    hop_length: int = 160,
    title: str = None
):
    """
    繪製 SPP 時頻圖 (Time-Frequency SPP Map)

    Args:
        spp_matrix: SPP 矩陣 (n_frames, n_freqs)，數值範圍 [0, 1]
        output_path: 輸出圖片路徑
        sample_rate: 採樣率 (Hz)
        hop_length: 幀移 (samples)
        title: 圖表標題
    """
    plt.figure(figsize=(12, 6))

    # 計算時間和頻率軸
    n_frames, n_freqs = spp_matrix.shape
    duration = n_frames * hop_length / sample_rate
    max_freq = sample_rate / 2

    # 繪製 SPP 熱力圖
    # 轉置矩陣：頻率在 Y 軸，時間在 X 軸
    # origin='lower' 讓低頻在下方
    plt.imshow(
        spp_matrix.T,
        aspect='auto',
        origin='lower',
        cmap='jet',
        vmin=0.0,
        vmax=1.0,
        extent=[0, duration, 0, max_freq]
    )

    plt.colorbar(label='Speech Presence Probability (SPP)')

    if title:
        plt.title(title)
    else:
        plt.title('SPP Time-Frequency Map')

    plt.xlabel('Time (s)')
    plt.ylabel('Frequency (Hz)')
    plt.tight_layout()

    # 確保輸出目錄存在
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"  SPP visualization saved: {output_path}")


def plot_spp_comparison(
    spp_matrix: np.ndarray,
    noisy_magnitude: np.ndarray,
    enhanced_magnitude: np.ndarray,
    output_path: str,
    sample_rate: int = 16000,
    hop_length: int = 160,
    title: str = None
):
    """
    繪製 SPP 與頻譜對比圖

    Args:
        spp_matrix: SPP 矩陣 (n_frames, n_freqs)
        noisy_magnitude: 帶噪頻譜 (n_frames, n_freqs)
        enhanced_magnitude: 降噪後頻譜 (n_frames, n_freqs)
        output_path: 輸出路徑
        sample_rate: 採樣率
        hop_length: 幀移
        title: 標題
    """
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))

    n_frames = spp_matrix.shape[0]
    duration = n_frames * hop_length / sample_rate
    max_freq = sample_rate / 2

    # 1. Noisy Spectrogram
    noisy_db = 20 * np.log10(noisy_magnitude.T + 1e-10)
    im0 = axes[0].imshow(
        noisy_db, aspect='auto', origin='lower',
        cmap='magma', vmin=-80, vmax=0,
        extent=[0, duration, 0, max_freq]
    )
    axes[0].set_title('Noisy Spectrogram')
    axes[0].set_ylabel('Frequency (Hz)')
    plt.colorbar(im0, ax=axes[0], label='dB')

    # 2. SPP Map
    im1 = axes[1].imshow(
        spp_matrix.T, aspect='auto', origin='lower',
        cmap='jet', vmin=0, vmax=1,
        extent=[0, duration, 0, max_freq]
    )
    axes[1].set_title('SPP (Speech Presence Probability)')
    axes[1].set_ylabel('Frequency (Hz)')
    plt.colorbar(im1, ax=axes[1], label='SPP')

    # 3. Enhanced Spectrogram
    enhanced_db = 20 * np.log10(enhanced_magnitude.T + 1e-10)
    im2 = axes[2].imshow(
        enhanced_db, aspect='auto', origin='lower',
        cmap='magma', vmin=-80, vmax=0,
        extent=[0, duration, 0, max_freq]
    )
    axes[2].set_title('Enhanced Spectrogram')
    axes[2].set_ylabel('Frequency (Hz)')
    axes[2].set_xlabel('Time (s)')
    plt.colorbar(im2, ax=axes[2], label='dB')

    if title:
        fig.suptitle(title, fontsize=14)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"  SPP comparison saved: {output_path}")
