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
clean, sr_clean = librosa.load('test_wav/wav/clean.wav', sr=None)
noisy_0db, sr_noisy = librosa.load('test_wav/wav/babble_0dB.wav', sr=None)
noisy_15db, _ = librosa.load('test_wav/wav/babble_15dB.wav', sr=None)

print(f"Clean:      sr={sr_clean:5d}Hz, len={len(clean):7d}, duration={len(clean)/sr_clean:.2f}s")
print(f"Noisy 0dB:  sr={sr_noisy:5d}Hz, len={len(noisy_0db):7d}, duration={len(noisy_0db)/sr_noisy:.2f}s")
print(f"Noisy 15dB: sr={sr_noisy:5d}Hz, len={len(noisy_15db):7d}, duration={len(noisy_15db)/sr_noisy:.2f}s")

# 長度差異
len_diff = len(noisy_0db) - len(clean)
time_diff = len_diff / sr_noisy
print(f"\n長度差異: {len_diff} samples = {time_diff:.3f}s")

# 檢查前段能量
skip_samples = int(0.5 * sr_noisy)
print(f"\n前 0.5s ({skip_samples} samples) 能量分析:")
print(f"  Noisy 0dB  前段 RMS: {np.sqrt(np.mean(noisy_0db[:skip_samples]**2)):.6f}")
print(f"  Noisy 0dB  後段 RMS: {np.sqrt(np.mean(noisy_0db[skip_samples:skip_samples+skip_samples]**2)):.6f}")
print(f"  Clean      前段 RMS: {np.sqrt(np.mean(clean[:skip_samples]**2)):.6f}")

# ============================================================================
# 2. 驗證 0.5s Trimming 的必要性
# ============================================================================
print("\n【2】0.5s Trimming 邏輯驗證")
print("-" * 100)

# 對比 trim 前後的 noisy 與 clean 的相關性
noisy_trimmed = noisy_0db[skip_samples:]

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

# 處理短片段
test_segment = noisy_0db[:sr_noisy * 5]  # 前 5 秒
enhanced_segment = v1.denoise(test_segment)

print(f"\n輸入片段:  len={len(test_segment)}, RMS={np.sqrt(np.mean(test_segment**2)):.6f}")
print(f"輸出片段:  len={len(enhanced_segment)}, RMS={np.sqrt(np.mean(enhanced_segment**2)):.6f}")
print(f"RMS 變化:  {np.sqrt(np.mean(enhanced_segment**2)) / np.sqrt(np.mean(test_segment**2)):.2%}")

# ============================================================================
# 4. 評估指標計算驗證
# ============================================================================
print("\n【4】評估指標計算驗證")
print("-" * 100)

# 加載完整的 enhanced 文件
enhanced_v1, _ = librosa.load('denoised_original/V1_babble_0dB.wav', sr=None)

print(f"Enhanced V1: len={len(enhanced_v1)}, RMS={np.sqrt(np.mean(enhanced_v1**2)):.6f}")

# Trim 並 resample 到 16kHz
enhanced_trimmed = enhanced_v1[skip_samples:]
clean_16k_full = librosa.resample(clean, orig_sr=sr_clean, target_sr=16000)
noisy_16k_full = librosa.resample(noisy_trimmed, orig_sr=sr_noisy, target_sr=16000)
enhanced_16k = librosa.resample(enhanced_trimmed, orig_sr=sr_noisy, target_sr=16000)

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

# 檢查頻譜
import matplotlib
matplotlib.use('Agg')  # 非交互式後端
import matplotlib.pyplot as plt

plt.figure(figsize=(12, 4))
plt.subplot(131)
plt.magnitude_spectrum(clean_16k_full[:16000], Fs=16000)
plt.title('Clean')
plt.subplot(132)
plt.magnitude_spectrum(noisy_16k_full[:16000], Fs=16000)
plt.title('Noisy')
plt.subplot(133)
plt.magnitude_spectrum(enhanced_16k[:16000], Fs=16000)
plt.title('Enhanced')
plt.tight_layout()
plt.savefig('diagnosis_spectrum.png', dpi=100)
print("\n✅ 頻譜圖已保存: diagnosis_spectrum.png")

if issues:
    print("\n發現的問題:")
    for issue in issues:
        print(f"  {issue}")
else:
    print("\n✅ 未發現明顯問題")

print("\n" + "=" * 100)
print("診斷完成")
print("=" * 100)
