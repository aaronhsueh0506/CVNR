#!/usr/bin/env python3
"""
算法正確性診斷工具

檢查以下關鍵點：
1. 測試數據結構（clean vs noisy）
2. 0.5s trimming 邏輯
3. FFT size 和窗函數設置
4. 降噪器輸出特性
5. 評估指標計算
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import librosa
import soundfile as sf
from denoisers import SpectralSubtractionDenoiser
from utils.metrics_loizou import segmental_snr, frequency_weighted_segsnr

print("=" * 100)
print("算法正確性診斷")
print("=" * 100)

# ============================================================================
# 1. 檢查測試數據結構
# ============================================================================
print("\n【1】測試數據結構檢查")
print("-" * 100)

# 加載文件
# ✅ 修正：使用 prepend 版本的 noisy，與 benchmark 一致
clean, sr_clean = librosa.load('test_wav/wav/clean.wav', sr=None)
noisy_0db_prepend, sr_noisy = librosa.load('test_wav/wav/append_silence/babble_0dB_prepend.wav', sr=None)
noisy_15db_prepend, _ = librosa.load('test_wav/wav/append_silence/babble_15dB_prepend.wav', sr=None)

print(f"Clean:      sr={sr_clean:5d}Hz, len={len(clean):7d}, duration={len(clean)/sr_clean:.2f}s")
print(f"Noisy 0dB (prepend):  sr={sr_noisy:5d}Hz, len={len(noisy_0db_prepend):7d}, duration={len(noisy_0db_prepend)/sr_noisy:.2f}s")
print(f"Noisy 15dB (prepend): sr={sr_noisy:5d}Hz, len={len(noisy_15db_prepend):7d}, duration={len(noisy_15db_prepend)/sr_noisy:.2f}s")

# 長度差異（prepend 版本應該比 clean 長 0.5s）
len_diff = len(noisy_0db_prepend) - len(clean)
time_diff = len_diff / sr_noisy
print(f"\n長度差異 (noisy_prepend - clean): {len_diff} samples = {time_diff:.3f}s")
print(f"  -> 應該約為 0.5s（prepend 噪聲段）")

# 檢查前段能量
skip_samples = int(0.5 * sr_noisy)
print(f"\n前 0.5s ({skip_samples} samples) 能量分析:")
print(f"  Noisy 0dB prepend 前段 RMS: {np.sqrt(np.mean(noisy_0db_prepend[:skip_samples]**2)):.6f}")
print(f"  Noisy 0dB prepend 後段 RMS: {np.sqrt(np.mean(noisy_0db_prepend[skip_samples:skip_samples+skip_samples]**2)):.6f}")
print(f"  Clean 前段 RMS:             {np.sqrt(np.mean(clean[:skip_samples]**2)):.6f}")

# ============================================================================
# 2. 驗證 0.5s Trimming 的必要性
# ============================================================================
print("\n【2】0.5s Trimming 邏輯驗證")
print("-" * 100)

# ✅ 修正：對 prepend 版本做 trim，使其與 clean 對齊
noisy_trimmed = noisy_0db_prepend[skip_samples:]

# Resample 到相同長度進行對比
min_len = min(len(clean), len(noisy_trimmed))
clean_16k = librosa.resample(clean[:min_len], orig_sr=sr_clean, target_sr=16000)
noisy_16k = librosa.resample(noisy_trimmed[:min_len], orig_sr=sr_noisy, target_sr=16000)

# 計算 SNR
signal_power = np.sum(clean_16k ** 2)
noise_power = np.sum((clean_16k - noisy_16k) ** 2)
input_snr = 10 * np.log10(signal_power / (noise_power + 1e-10))

print(f"Noisy (trim 後) vs Clean 的 SNR: {input_snr:.2f} dB")
print(f"  -> 這應該接近測試用例標註的 SNR (0 dB)")

# ============================================================================
# 3. 檢查降噪器處理
# ============================================================================
print("\n【3】降噪器處理檢查 (V1 - 頻譜減法)")
print("-" * 100)

# 創建 V1 降噪器
fft_size = int(sr_noisy * 0.032)
fft_size = 2 ** int(np.ceil(np.log2(fft_size)))

v1 = SpectralSubtractionDenoiser(
    sample_rate=sr_noisy,
    fft_size=fft_size,
    frame_size_ms=20,
    frame_shift_ms=10
)

print(f"配置: sr={sr_noisy}Hz, fft_size={fft_size}")

# 處理短片段（使用 prepend 版本）
test_segment = noisy_0db_prepend[:sr_noisy * 5]  # 前 5 秒
enhanced_segment = v1.denoise(test_segment)

print(f"\n輸入片段:  len={len(test_segment)}, RMS={np.sqrt(np.mean(test_segment**2)):.6f}")
print(f"輸出片段:  len={len(enhanced_segment)}, RMS={np.sqrt(np.mean(enhanced_segment**2)):.6f}")
print(f"RMS 變化:  {np.sqrt(np.mean(enhanced_segment**2)) / np.sqrt(np.mean(test_segment**2)):.2%}")

# ============================================================================
# 4. 評估指標計算驗證
# ============================================================================
print("\n【4】評估指標計算驗證")
print("-" * 100)

# ✅ 修正：從 output/ 目錄加載 enhanced 文件（與 benchmark 一致）
enhanced_v1, sr_enhanced = librosa.load('output/V1_babble_0dB.wav', sr=None)

print(f"Enhanced V1: len={len(enhanced_v1)}, sr={sr_enhanced}Hz, RMS={np.sqrt(np.mean(enhanced_v1**2)):.6f}")

# ✅ 修正對齊邏輯：
# - clean: 無 prepend，不需要 trim
# - noisy_prepend: 有 prepend，需要 trim 0.5s
# - enhanced: 由 prepend 版本處理得到，也需要 trim 0.5s
skip_samples_16k = int(0.5 * 16000)  # 16kHz 下的 0.5s

# 先 resample 到 16kHz
clean_16k_full = librosa.resample(clean, orig_sr=sr_clean, target_sr=16000)
noisy_16k_prepend = librosa.resample(noisy_0db_prepend, orig_sr=sr_noisy, target_sr=16000)
enhanced_16k_full = librosa.resample(enhanced_v1, orig_sr=sr_enhanced, target_sr=16000)

# 對 prepend 版本做 trim
noisy_16k_full = noisy_16k_prepend[skip_samples_16k:]
enhanced_16k = enhanced_16k_full[skip_samples_16k:]

# 確保長度一致
min_len = min(len(clean_16k_full), len(noisy_16k_full), len(enhanced_16k))
clean_16k_full = clean_16k_full[:min_len]
noisy_16k_full = noisy_16k_full[:min_len]
enhanced_16k = enhanced_16k[:min_len]

print(f"\n16kHz 評估數據長度: {min_len} samples = {min_len/16000:.2f}s")

# 計算指標
print("\n計算 Loizou 指標...")
seg_snr_noisy = segmental_snr(clean_16k_full, noisy_16k_full, 16000, use_vad=True)
seg_snr_enhanced = segmental_snr(clean_16k_full, enhanced_16k, 16000, use_vad=True)
improvement = seg_snr_enhanced - seg_snr_noisy

print(f"\nsegSNR (noisy):    {seg_snr_noisy:.2f} dB")
print(f"segSNR (enhanced): {seg_snr_enhanced:.2f} dB")
print(f"Improvement:       {improvement:+.2f} dB")

fw_snr_noisy = frequency_weighted_segsnr(clean_16k_full, noisy_16k_full, 16000, use_vad=True)
fw_snr_enhanced = frequency_weighted_segsnr(clean_16k_full, enhanced_16k, 16000, use_vad=True)
fw_improvement = fw_snr_enhanced - fw_snr_noisy

print(f"\nfwSegSNR (noisy):    {fw_snr_noisy:.2f} dB")
print(f"fwSegSNR (enhanced): {fw_snr_enhanced:.2f} dB")
print(f"Improvement:         {fw_improvement:+.2f} dB")

# ============================================================================
# 5. 問題診斷
# ============================================================================
print("\n【5】問題診斷")
print("-" * 100)

issues = []

if improvement < 0:
    issues.append(f"⚠️  segSNR improvement 為負 ({improvement:.2f} dB)")
if fw_improvement < -2:
    issues.append(f"⚠️  fwSegSNR improvement 嚴重為負 ({fw_improvement:.2f} dB)")

# 檢查輸出音量
output_volume_ratio = np.sqrt(np.mean(enhanced_16k**2)) / np.sqrt(np.mean(noisy_16k_full**2))
if output_volume_ratio < 0.5:
    issues.append(f"⚠️  輸出音量過低 ({output_volume_ratio:.2%})")
elif output_volume_ratio > 1.5:
    issues.append(f"⚠️  輸出音量過高 ({output_volume_ratio:.2%})")

# 檢查頻譜（使用 librosa 風格的時頻譜圖）
import matplotlib
matplotlib.use('Agg')  # 非交互式後端
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

try:
    # 嘗試使用 librosa（紫色/magma 配色）
    import librosa
    import librosa.display

    # 準備數據（取前 1 秒用於顯示）
    display_samples = 16000  # 1 秒 @ 16kHz
    hop_length = 256
    n_fft = 512

    # 計算 STFT
    D_clean = librosa.stft(clean_16k_full[:display_samples], n_fft=n_fft, hop_length=hop_length)
    D_noisy = librosa.stft(noisy_16k_full[:display_samples], n_fft=n_fft, hop_length=hop_length)
    D_enhanced = librosa.stft(enhanced_16k[:display_samples], n_fft=n_fft, hop_length=hop_length)

    D_clean_db = librosa.amplitude_to_db(np.abs(D_clean), ref=np.max)
    D_noisy_db = librosa.amplitude_to_db(np.abs(D_noisy), ref=np.max)
    D_enhanced_db = librosa.amplitude_to_db(np.abs(D_enhanced), ref=np.max)

    # 計算時間軸（確保波形和頻譜圖對齊）
    duration = display_samples / 16000
    time_axis = np.linspace(0, duration, display_samples)

    # 使用 GridSpec 創建對齊的圖表（含 colorbar 列）
    # 時域波形在上方，頻譜圖在下方
    fig = plt.figure(figsize=(14, 12))
    # 創建 4 行 2 列的 GridSpec，第二列用於 colorbar
    gs = GridSpec(4, 2, width_ratios=[1, 0.03], height_ratios=[1, 1, 1, 1], hspace=0.3, wspace=0.02)

    # ========== 時域波形疊圖 ==========
    ax_waveform = fig.add_subplot(gs[0, 0])
    ax_waveform.plot(time_axis, noisy_16k_full[:display_samples], alpha=0.7, label='Noisy', color='#E74C3C', linewidth=0.5)
    ax_waveform.plot(time_axis, enhanced_16k[:display_samples], alpha=0.8, label='Enhanced', color='#3498DB', linewidth=0.5)
    ax_waveform.plot(time_axis, clean_16k_full[:display_samples], alpha=0.6, label='Clean', color='#2ECC71', linewidth=0.5)
    ax_waveform.set_ylabel('Amplitude')
    ax_waveform.set_title('Waveform Comparison (Noisy / Enhanced / Clean)', fontsize=12, fontweight='bold')
    ax_waveform.legend(loc='upper right', fontsize=9)
    ax_waveform.set_xlim(0, duration)
    ax_waveform.grid(True, alpha=0.3)
    ax_waveform.set_xticklabels([])
    # 波形圖右側留空白區域（與 colorbar 對齊）
    ax_waveform_cbar = fig.add_subplot(gs[0, 1])
    ax_waveform_cbar.axis('off')

    # ========== Clean 頻譜圖 ==========
    ax_clean = fig.add_subplot(gs[1, 0], sharex=ax_waveform)
    img_clean = librosa.display.specshow(D_clean_db, sr=16000, hop_length=hop_length,
                                          x_axis='time', y_axis='hz', cmap='magma', ax=ax_clean)
    ax_clean.set_title('Clean Spectrogram', fontsize=12, fontweight='bold')
    ax_clean.set_ylabel('Frequency (Hz)')
    ax_clean.set_xlabel('')
    ax_clean_cbar = fig.add_subplot(gs[1, 1])
    fig.colorbar(img_clean, cax=ax_clean_cbar, format='%+2.0f dB')

    # ========== Noisy 頻譜圖 ==========
    ax_noisy = fig.add_subplot(gs[2, 0], sharex=ax_waveform)
    img_noisy = librosa.display.specshow(D_noisy_db, sr=16000, hop_length=hop_length,
                                          x_axis='time', y_axis='hz', cmap='magma', ax=ax_noisy)
    ax_noisy.set_title('Noisy Spectrogram', fontsize=12, fontweight='bold')
    ax_noisy.set_ylabel('Frequency (Hz)')
    ax_noisy.set_xlabel('')
    ax_noisy_cbar = fig.add_subplot(gs[2, 1])
    fig.colorbar(img_noisy, cax=ax_noisy_cbar, format='%+2.0f dB')

    # ========== Enhanced 頻譜圖 ==========
    ax_enhanced = fig.add_subplot(gs[3, 0], sharex=ax_waveform)
    img_enhanced = librosa.display.specshow(D_enhanced_db, sr=16000, hop_length=hop_length,
                                             x_axis='time', y_axis='hz', cmap='magma', ax=ax_enhanced)
    ax_enhanced.set_title('Enhanced Spectrogram', fontsize=12, fontweight='bold')
    ax_enhanced.set_ylabel('Frequency (Hz)')
    ax_enhanced.set_xlabel('Time (s)')
    ax_enhanced_cbar = fig.add_subplot(gs[3, 1])
    fig.colorbar(img_enhanced, cax=ax_enhanced_cbar, format='%+2.0f dB')

    plt.savefig('diagnosis_spectrum.png', dpi=150, bbox_inches='tight')
    print("\n✅ 診斷圖（波形 + 頻譜圖）已保存: diagnosis_spectrum.png")
    print("   時域波形和頻譜圖時間軸已對齊")

except ImportError:
    print("\n⚠️  librosa 未安裝，無法生成頻譜圖")

except Exception as e:
    print(f"⚠️  頻譜圖生成失敗: {e}")

if issues:
    print("\n發現的問題:")
    for issue in issues:
        print(f"  {issue}")
else:
    print("\n✅ 未發現明顯問題")

print("\n" + "=" * 100)
print("診斷完成")
print("=" * 100)
