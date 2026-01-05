#!/usr/bin/env python3
"""
評估 Ultra/Extreme 配置

目標: STOI Δ ≥ +0.019 (RNNoise), PESQ Δ ≥ +0.40
"""

import numpy as np
import librosa
from pesq import pesq
from pystoi import stoi

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# V3-3 實驗組
variants = [
    {'name': 'V3-3_ultra', 'label': 'V3-3 Ultra (base=-5)'},
    {'name': 'V3-3_extreme', 'label': 'V3-3 Extreme (base=-3)'},
]

def seg_snr(clean, enhanced, frame_length=512):
    """計算 segSNR"""
    clean = clean.astype(np.float64)
    enhanced = enhanced.astype(np.float64)
    min_len = min(len(clean), len(enhanced))
    clean, enhanced = clean[:min_len], enhanced[:min_len]
    n_frames = min_len // frame_length
    snrs = []
    for i in range(n_frames):
        start, end = i * frame_length, (i + 1) * frame_length
        signal_power = np.sum(clean[start:end] ** 2)
        noise_power = np.sum((clean[start:end] - enhanced[start:end]) ** 2)
        if signal_power > 1e-10 and noise_power > 1e-10:
            frame_snr = 10 * np.log10(signal_power / noise_power)
            if -10 <= frame_snr <= 35:
                snrs.append(frame_snr)
    return np.mean(snrs) if snrs else 0.0

print("=" * 120)
print("評估 V3-3 Ultra/Extreme 配置")
print("=" * 120)
print(f"目標: STOI Δ ≥ +0.019 (RNNoise), PESQ Δ ≥ +0.40")
print("=" * 120)

all_results = {}

for variant in variants:
    print(f"\n處理: {variant['label']}")
    print("-" * 120)

    results = {
        'segSNR': {'noisy': [], 'enhanced': [], 'improvement': []},
        'PESQ': {'noisy': [], 'enhanced': [], 'improvement': []},
        'STOI': {'noisy': [], 'enhanced': [], 'improvement': []}
    }

    for test_case in test_cases:
        clean_path = 'test_wav/wav/clean.wav'
        noisy_path = f'test_wav/wav/append_silence/{test_case}_prepend.wav'
        enhanced_path = f'denoised_ultra/{test_case}_{variant["name"]}.wav'

        # 加載並處理
        clean, _ = librosa.load(clean_path, sr=16000)
        noisy, _ = librosa.load(noisy_path, sr=16000)
        enhanced, _ = librosa.load(enhanced_path, sr=16000)

        # 裁剪 prepend 0.5s
        prepend_samples = int(0.5 * 16000)
        noisy, enhanced = noisy[prepend_samples:], enhanced[prepend_samples:]

        # 對齊長度
        min_len = min(len(clean), len(noisy), len(enhanced))
        clean, noisy, enhanced = clean[:min_len], noisy[:min_len], enhanced[:min_len]

        # 計算指標
        try:
            snr_noisy = seg_snr(clean, noisy)
            snr_enhanced = seg_snr(clean, enhanced)
            results['segSNR']['noisy'].append(snr_noisy)
            results['segSNR']['enhanced'].append(snr_enhanced)
            results['segSNR']['improvement'].append(snr_enhanced - snr_noisy)
        except:
            pass

        try:
            pesq_noisy = pesq(16000, clean, noisy, 'wb')
            pesq_enhanced = pesq(16000, clean, enhanced, 'wb')
            results['PESQ']['noisy'].append(pesq_noisy)
            results['PESQ']['enhanced'].append(pesq_enhanced)
            results['PESQ']['improvement'].append(pesq_enhanced - pesq_noisy)
        except:
            pass

        try:
            stoi_noisy = stoi(clean, noisy, 16000, extended=False)
            stoi_enhanced = stoi(clean, enhanced, 16000, extended=False)
            results['STOI']['noisy'].append(stoi_noisy)
            results['STOI']['enhanced'].append(stoi_enhanced)
            results['STOI']['improvement'].append(stoi_enhanced - stoi_noisy)
        except:
            pass

    # 平均值
    avg_results = {}
    for metric in ['segSNR', 'PESQ', 'STOI']:
        avg_results[metric] = {
            'noisy': np.mean(results[metric]['noisy']) if results[metric]['noisy'] else 0.0,
            'enhanced': np.mean(results[metric]['enhanced']) if results[metric]['enhanced'] else 0.0,
            'improvement': np.mean(results[metric]['improvement']) if results[metric]['improvement'] else 0.0,
        }
    all_results[variant['name']] = avg_results
    print(f"  完成: {len(results['STOI']['improvement'])}/12")

# 打印結果
print("\n" + "=" * 120)
print("📊 結果對比")
print("=" * 120)

print("\n┌────────────────────────────────────────────────────────────────────────────────────┐")
print("│                               STOI Improvement ⭐                                  │")
print("├────────────────────┬────────────┬────────────┬────────────┬──────────────────────┤")
print("│ 配置               │ Noisy      │ Enhanced   │ Improvement│ 狀態                 │")
print("├────────────────────┼────────────┼────────────┼────────────┼──────────────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['STOI']

    if r['improvement'] >= 0.019:
        status = "🏆 達標 RNNoise"
    elif r['improvement'] >= 0.001:
        status = "✅ 超越 Speex"
    elif r['improvement'] >= 0.000:
        status = "⚠️  接近目標"
    else:
        status = "❌ 未達標"

    print(f"│ {label:<18} │ {r['noisy']:>10.3f} │ {r['enhanced']:>10.3f} │ {r['improvement']:>+10.3f} │ {status:<20} │")

print("└────────────────────┴────────────┴────────────┴────────────┴──────────────────────┘")

print("\n┌────────────────────────────────────────────────────────────────────────────────────┐")
print("│                               PESQ Improvement                                     │")
print("├────────────────────┬────────────┬────────────┬────────────┬──────────────────────┤")
print("│ 配置               │ Noisy      │ Enhanced   │ Improvement│ 狀態                 │")
print("├────────────────────┼────────────┼────────────┼────────────┼──────────────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['PESQ']

    if r['improvement'] >= 0.40:
        status = "🏆 達標 RNNoise"
    elif r['improvement'] >= 0.30:
        status = "✅ 優秀"
    elif r['improvement'] >= 0.20:
        status = "⚠️  良好"
    else:
        status = "❌ 待改進"

    print(f"│ {label:<18} │ {r['noisy']:>10.3f} │ {r['enhanced']:>10.3f} │ {r['improvement']:>+10.3f} │ {status:<20} │")

print("└────────────────────┴────────────┴────────────┴────────────┴──────────────────────┘")

print("\n┌────────────────────────────────────────────────────────────────────────────────────┐")
print("│                            segSNR (dB) Improvement                                 │")
print("├────────────────────┬────────────┬────────────┬────────────┬──────────────────────┤")
print("│ 配置               │ Noisy      │ Enhanced   │ Improvement│ 狀態                 │")
print("├────────────────────┼────────────┼────────────┼────────────┼──────────────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['segSNR']

    if r['improvement'] >= 4.0:
        status = "✅ 達標"
    elif r['improvement'] >= 3.5:
        status = "⚠️  接近"
    else:
        status = "❌ 未達標"

    print(f"│ {label:<18} │ {r['noisy']:>10.2f} │ {r['enhanced']:>10.2f} │ {r['improvement']:>+10.2f} │ {status:<20} │")

print("└────────────────────┴────────────┴────────────┴────────────┴──────────────────────┘")

# 找出最佳
best_stoi = max(all_results.keys(), key=lambda x: all_results[x]['STOI']['improvement'])
best_pesq = max(all_results.keys(), key=lambda x: all_results[x]['PESQ']['improvement'])

print("\n" + "=" * 120)
print("🏆 最佳配置")
print("=" * 120)

for variant in variants:
    if variant['name'] == best_stoi:
        r = all_results[variant['name']]
        print(f"\n🥇 STOI 最佳: {variant['label']}")
        print(f"   STOI Δ: {r['STOI']['improvement']:+.3f}")
        print(f"   PESQ Δ: {r['PESQ']['improvement']:+.3f}")
        print(f"   segSNR Δ: {r['segSNR']['improvement']:+.2f} dB")

        # 判斷是否達標
        if r['STOI']['improvement'] >= 0.019:
            print(f"   ✅ 已達成 RNNoise 水平！")
        elif r['STOI']['improvement'] >= 0.001:
            print(f"   ⚠️  已超越 Speex，但未達 RNNoise (還差 {0.019 - r['STOI']['improvement']:.3f})")
        else:
            print(f"   ❌ 未達標 (還差 {0.019 - r['STOI']['improvement']:.3f})")

print("\n" + "=" * 120)
print("評估完成！")
print("=" * 120)
