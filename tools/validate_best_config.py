#!/usr/bin/env python3
"""
驗證最佳配置 - 在所有測試用例上評估

最佳配置:
- boost_factor = 1.20
- g_min_db = -1.0
- alpha_xi = 0.92
- alpha_g = 0.60
"""

import numpy as np
import librosa
from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator
from utils.metrics import calculate_segmental_snr

# 最佳配置
BOOST_FACTOR = 1.20
G_MIN_DB = -1.0
ALPHA_XI = 0.92
ALPHA_G = 0.60

g_min = 10 ** (G_MIN_DB / 10)
sr = 16000

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]

print("=" * 100)
print("最佳配置驗證 - 所有測試用例")
print("=" * 100)
print(f"配置: boost={BOOST_FACTOR:.2f}, g_min={G_MIN_DB:.1f}dB, α_ξ={ALPHA_XI:.2f}, α_g={ALPHA_G:.2f}")
print("=" * 100)
print(f"{'Test Case':<20} {'Input SNR':>10} {'RMS%':>7} {'segSNR↑':>9} {'Output SNR':>11}")
print("-" * 100)

# 初始化處理器（共用）
processor = FrameProcessor(sample_rate=sr, frame_size_ms=20, frame_shift_ms=10,
                           fft_size=512, window_type='hanning')
reconstructor = Reconstructor(fft_size=512, frame_shift=processor.frame_shift,
                              window=processor.window)

# 加載 clean
clean, _ = librosa.load("test_wav/wav/clean.wav", sr=sr)
skip = int(0.5 * sr)
clean = clean[skip:]

rms_results = []
segsnr_improvements = []

for noise in noise_types:
    for snr in snr_levels:
        test_id = f"{noise}_{snr}dB"
        input_file = f"test_wav/wav/{test_id}.wav"

        try:
            # 加載音頻
            noisy, _ = librosa.load(input_file, sr=sr)
            noisy_eval = noisy[skip:]

            # 計算輸入 segSNR
            input_segsnr = calculate_segmental_snr(clean, noisy_eval, sr)

            # 重置處理器
            noise_estimator = RecursiveAverageNoiseEstimator(alpha=0.95, num_init_frames=20)
            spp_estimator = SppEstimator(alpha=ALPHA_XI, q=0.5, xi_min_db=-25.0)

            # 分幀
            magnitudes, phases, _ = processor.process_signal(noisy)
            n_frames = magnitudes.shape[0]
            noise_estimator.estimate(magnitudes)

            # 逐幀處理
            gain_prev = None
            enhanced_magnitude = np.zeros_like(magnitudes)

            for i in range(n_frames):
                Y_psd = magnitudes[i] ** 2
                noise_psd = noise_estimator.noise_psd

                # 估計 SPP
                spp, xi, gamma = spp_estimator.estimate(Y_psd, noise_psd, gain_prev)

                # 計算 MMSE gain
                v = (xi / (1 + xi)) * gamma
                v = np.clip(v, 1e-10, 700)

                try:
                    from scipy.special import exp1
                    exp1_v = exp1(v)
                except:
                    exp1_v = np.exp(-v) / v

                gain_mmse = (xi / (1 + xi)) * np.exp(0.5 * exp1_v)

                # 應用提升因子
                gain_boosted = BOOST_FACTOR * gain_mmse

                # SPP 混合
                gain = spp * gain_boosted + (1 - spp) * g_min

                # 時間平滑
                if gain_prev is not None:
                    gain = ALPHA_G * gain_prev + (1 - ALPHA_G) * gain

                # 限制範圍
                gain = np.clip(gain, g_min, 2.0)

                # 應用增益
                enhanced_magnitude[i] = gain * magnitudes[i]
                gain_prev = gain.copy()

                # 更新噪聲估計
                is_speech = np.mean(spp) > 0.5
                noise_estimator.update(magnitudes[i], is_speech=is_speech)

            # 重建信號
            enhanced = reconstructor.reconstruct_signal(enhanced_magnitude, phases,
                                                        original_length=len(noisy))
            enhanced_eval = enhanced[skip:]

            # 對齊
            min_len = min(len(clean), len(enhanced_eval))
            clean_seg = clean[:min_len]
            enhanced_seg = enhanced_eval[:min_len]

            # 計算指標
            clean_rms = np.sqrt(np.mean(clean_seg**2))
            enhanced_rms = np.sqrt(np.mean(enhanced_seg**2))
            rms_ratio = enhanced_rms / clean_rms * 100

            output_segsnr = calculate_segmental_snr(clean_seg, enhanced_seg, sr)
            improvement = output_segsnr - input_segsnr

            rms_results.append(rms_ratio)
            segsnr_improvements.append(improvement)

            print(f"{test_id:<20} {input_segsnr:>9.2f}dB {rms_ratio:>6.1f}% {improvement:>+8.2f}dB {output_segsnr:>10.2f}dB")

        except Exception as e:
            print(f"{test_id:<20} ERROR: {e}")

print("=" * 100)
print("統計摘要:")
print(f"  平均 RMS: {np.mean(rms_results):.1f}%")
print(f"  平均 segSNR improvement: {np.mean(segsnr_improvements):+.2f} dB")
print(f"  RMS 標準差: {np.std(rms_results):.1f}%")
print(f"  segSNR improvement 標準差: {np.std(segsnr_improvements):.2f} dB")
print("=" * 100)
print("\nSpeex 基準: RMS ~105%, segSNR improvement ~+2.2 dB")
print("我們的結果: RMS ~{:.1f}%, segSNR improvement ~{:+.2f} dB".format(
    np.mean(rms_results), np.mean(segsnr_improvements)))
print("=" * 100)
