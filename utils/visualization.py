"""
SPP Visualization - 語音存在機率時頻圖

用於可視化降噪器的 SPP (Speech Presence Probability) 輸出
"""

import numpy as np
import matplotlib.pyplot as plt
import os


def _ensure_parent_dir(output_path):
    """Create the parent directory of output_path if needed (cwd if it has none)."""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)


def _imshow_tf(ax, disp, *, cmap, vmin, vmax, extent, cbar_label):
    """imshow a (freq, time) display matrix as a time-frequency map + attach a colorbar.
    Shared core of the spectrogram plotters (SPP / gain / noise-PSD)."""
    im = ax.imshow(disp, aspect='auto', origin='lower', cmap=cmap,
                   vmin=vmin, vmax=vmax, extent=extent)
    plt.colorbar(im, ax=ax, label=cbar_label)
    return im


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
    # 轉置矩陣：頻率在 Y 軸，時間在 X 軸；origin='lower' 讓低頻在下方
    ax = plt.figure(figsize=(12, 6)).gca()
    n_frames = spp_matrix.shape[0]
    extent = [0, n_frames * hop_length / sample_rate, 0, sample_rate / 2]
    _imshow_tf(ax, spp_matrix.T, cmap='gray_r', vmin=0.0, vmax=1.0,
               extent=extent, cbar_label='Speech Presence Probability (SPP)')
    ax.set_title(title or 'SPP Time-Frequency Map')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Frequency (Hz)')
    plt.tight_layout()
    _ensure_parent_dir(output_path)
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"  SPP visualization saved: {output_path}")


def plot_gain_spectrogram(
    gain_matrix: np.ndarray,
    output_path: str,
    sample_rate: int = 16000,
    hop_length: int = 256,
    title: str = None
):
    """
    繪製增益時頻圖 (Time-Frequency Gain Map)，以 dB 顯示。

    Args:
        gain_matrix: 增益矩陣 (n_frames, n_freqs)，線性 [g_min, 1]
        output_path: 輸出圖片路徑
        sample_rate: 採樣率 (Hz)
        hop_length: 幀移 (samples)
        title: 圖表標題
    """
    ax = plt.figure(figsize=(12, 6)).gca()
    n_frames = gain_matrix.shape[0]
    extent = [0, n_frames * hop_length / sample_rate, 0, sample_rate / 2]
    # 深壓 → 深色；保留 (0 dB) → 亮色
    gain_db = 20 * np.log10(np.maximum(gain_matrix, 1e-10)).T
    _imshow_tf(ax, gain_db, cmap='viridis', vmin=-40.0, vmax=0.0,
               extent=extent, cbar_label='Applied gain (dB)')
    ax.set_title(title or 'Gain Time-Frequency Map')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Frequency (Hz)')
    plt.tight_layout()
    _ensure_parent_dir(output_path)
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Gain visualization saved: {output_path}")


def plot_noise_psd_tracking(
    noise_psd_matrix: np.ndarray,
    output_path: str,
    sample_rate: int = 16000,
    hop_length: int = 256,
    title: str = None,
    input_psd_matrix: np.ndarray = None
):
    """
    繪製噪聲 PSD 追蹤時頻圖，以 dB 顯示。可看出噪聲底是否在音樂下方逐漸爬升
    （音樂被吸進噪聲估計的直接證據）。

    Args:
        noise_psd_matrix: 估計噪聲 PSD (n_frames, n_freqs)，功率域
        output_path: 輸出圖片路徑
        sample_rate: 採樣率 (Hz)
        hop_length: 幀移 (samples)
        title: 圖表標題
        input_psd_matrix: 選填，輸入功率譜 (n_frames, n_freqs)，附加一列對照
    """
    n_panels = 2 if input_psd_matrix is not None else 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 4 * n_panels))
    if n_panels == 1:
        axes = [axes]

    n_frames = noise_psd_matrix.shape[0]
    extent = [0, n_frames * hop_length / sample_rate, 0, sample_rate / 2]

    def _pow_db(m):
        return 10 * np.log10(np.maximum(m, 1e-20)).T

    if input_psd_matrix is not None:
        _imshow_tf(axes[0], _pow_db(input_psd_matrix), cmap='magma', vmin=-80, vmax=0,
                   extent=extent, cbar_label='dB')
        axes[0].set_title('Input power spectrum (dB)')
        axes[0].set_ylabel('Frequency (Hz)')

    _imshow_tf(axes[-1], _pow_db(noise_psd_matrix), cmap='magma', vmin=-80, vmax=0,
               extent=extent, cbar_label='dB')
    axes[-1].set_title('Tracked noise PSD (dB)')
    axes[-1].set_ylabel('Frequency (Hz)')
    axes[-1].set_xlabel('Time (s)')

    if title:
        fig.suptitle(title, fontsize=14)
    plt.tight_layout()

    _ensure_parent_dir(output_path)
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"  Noise-PSD tracking saved: {output_path}")


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
        cmap='gray_r', vmin=0, vmax=1,
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
