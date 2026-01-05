#!/usr/bin/env python3
"""
評估 6 組實驗的降噪效果

對比:
1. V3-3 保守檔 vs 中庸檔 vs 激進檔
2. V3-4 保守檔 vs 中庸檔 vs 激進檔
3. V3-3 最佳 vs V3-4 最佳

指標:
- segSNR improvement (dB)
- PESQ improvement
- STOI improvement
- SI-SNR improvement (dB)
"""

import numpy as np
import librosa
import soundfile as sf
import os
from pathlib import Path
from pesq import pesq
from pystoi import stoi

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# 6 組實驗
variants = [
    {'name': 'V3-3_conservative', 'label': 'V3-3 保守'},
    {'name': 'V3-3_moderate', 'label': 'V3-3 中庸'},
    {'name': 'V3-3_aggressive', 'label': 'V3-3 激進'},
    {'name': 'V3-4_conservative', 'label': 'V3-4 保守'},
    {'name': 'V3-4_moderate', 'label': 'V3-4 中庸'},
    {'name': 'V3-4_aggressive', 'label': 'V3-4 激進'},
]

def seg_snr(clean, enhanced, frame_length=512):
    """計算 segSNR"""
    clean = clean.astype(np.float64)
    enhanced = enhanced.astype(np.float64)

    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    n_frames = min_len // frame_length
    snrs = []

    for i in range(n_frames):
        start = i * frame_length
        end = start + frame_length
        clean_frame = clean[start:end]
        enhanced_frame = enhanced[start:end]

        signal_power = np.sum(clean_frame ** 2)
        noise_power = np.sum((clean_frame - enhanced_frame) ** 2)

        if signal_power < 1e-10 or noise_power < 1e-10:
            continue

        frame_snr = 10 * np.log10(signal_power / noise_power)
        if -10 <= frame_snr <= 35:
            snrs.append(frame_snr)

    return np.mean(snrs) if snrs else 0.0

print("=" * 120)
print("評估 6 組實驗的降噪效果")
print("=" * 120)

# 收集所有結果
all_results = {}

for variant in variants:
    print(f"\n處理: {variant['label']} ({variant['name']})")
    print("-" * 120)

    results = {
        'segSNR': {'noisy': [], 'enhanced': [], 'improvement': []},
        'PESQ': {'noisy': [], 'enhanced': [], 'improvement': []},
        'STOI': {'noisy': [], 'enhanced': [], 'improvement': []},
        'SI-SNR': {'noisy': [], 'enhanced': [], 'improvement': []}
    }

    for test_case in test_cases:
        # 所有測試用例使用同一個 clean.wav
        clean_path = 'test_wav/wav/clean.wav'
        # ✅ 使用 append_silence prepend 文件作為 noisy 參考
        noisy_path = f'test_wav/wav/append_silence/{test_case}_prepend.wav'
        enhanced_path = f'denoised_variants/{test_case}_{variant["name"]}.wav'

        if not all([os.path.exists(p) for p in [clean_path, noisy_path, enhanced_path]]):
            print(f"  ⚠️  跳過 {test_case}: 文件缺失")
            continue

        # 加載音頻 (統一到 16kHz)
        clean, _ = librosa.load(clean_path, sr=16000)
        noisy, _ = librosa.load(noisy_path, sr=16000)
        enhanced, _ = librosa.load(enhanced_path, sr=16000)

        # ✅ 裁剪 prepend 的 0.5s (8000 samples @ 16kHz)
        prepend_samples = int(0.5 * 16000)
        noisy = noisy[prepend_samples:]
        enhanced = enhanced[prepend_samples:]

        # 確保長度一致
        min_len = min(len(clean), len(noisy), len(enhanced))
        clean = clean[:min_len]
        noisy = noisy[:min_len]
        enhanced = enhanced[:min_len]

        # segSNR
        try:
            snr_noisy = seg_snr(clean, noisy)
            snr_enhanced = seg_snr(clean, enhanced)
            snr_improvement = snr_enhanced - snr_noisy
            results['segSNR']['noisy'].append(snr_noisy)
            results['segSNR']['enhanced'].append(snr_enhanced)
            results['segSNR']['improvement'].append(snr_improvement)
        except Exception as e:
            print(f"  ❌ {test_case} segSNR 錯誤: {e}")

        # PESQ
        try:
            pesq_noisy = pesq(16000, clean, noisy, 'wb')
            pesq_enhanced = pesq(16000, clean, enhanced, 'wb')
            pesq_improvement = pesq_enhanced - pesq_noisy
            results['PESQ']['noisy'].append(pesq_noisy)
            results['PESQ']['enhanced'].append(pesq_enhanced)
            results['PESQ']['improvement'].append(pesq_improvement)
        except Exception as e:
            print(f"  ❌ {test_case} PESQ 錯誤: {e}")

        # STOI
        try:
            stoi_noisy = stoi(clean, noisy, 16000, extended=False)
            stoi_enhanced = stoi(clean, enhanced, 16000, extended=False)
            stoi_improvement = stoi_enhanced - stoi_noisy
            results['STOI']['noisy'].append(stoi_noisy)
            results['STOI']['enhanced'].append(stoi_enhanced)
            results['STOI']['improvement'].append(stoi_improvement)
        except Exception as e:
            print(f"  ❌ {test_case} STOI 錯誤: {e}")

    # 計算平均值
    avg_results = {}
    for metric in ['segSNR', 'PESQ', 'STOI']:
        avg_results[metric] = {
            'noisy': np.mean(results[metric]['noisy']) if results[metric]['noisy'] else 0.0,
            'enhanced': np.mean(results[metric]['enhanced']) if results[metric]['enhanced'] else 0.0,
            'improvement': np.mean(results[metric]['improvement']) if results[metric]['improvement'] else 0.0,
        }

    all_results[variant['name']] = avg_results

    print(f"  ✅ 完成: {len(results['STOI']['improvement'])}/12 個測試用例")

# 打印對比表格
print("\n" + "=" * 120)
print("📊 結果對比")
print("=" * 120)

print("\n┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
print("│                                   segSNR (dB) Improvement                                      │")
print("├──────────────────────┬──────────────────┬──────────────────┬──────────────────┬───────────────┤")
print("│ 實驗組               │ Noisy            │ Enhanced         │ Improvement      │ 成功標準      │")
print("├──────────────────────┼──────────────────┼──────────────────┼──────────────────┼───────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['segSNR']
    success = "✅" if r['improvement'] >= 4.0 else "⚠️" if r['improvement'] >= 3.5 else "❌"
    print(f"│ {label:<20} │ {r['noisy']:>16.2f} │ {r['enhanced']:>16.2f} │ {r['improvement']:>+15.2f} │ {success:>12}  │")

print("└──────────────────────┴──────────────────┴──────────────────┴──────────────────┴───────────────┘")

print("\n┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
print("│                                    PESQ Improvement                                             │")
print("├──────────────────────┬──────────────────┬──────────────────┬──────────────────┬───────────────┤")
print("│ 實驗組               │ Noisy            │ Enhanced         │ Improvement      │ 成功標準      │")
print("├──────────────────────┼──────────────────┼──────────────────┼──────────────────┼───────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['PESQ']
    success = "✅" if r['improvement'] >= 0.30 else "⚠️" if r['improvement'] >= 0.20 else "❌"
    print(f"│ {label:<20} │ {r['noisy']:>16.3f} │ {r['enhanced']:>16.3f} │ {r['improvement']:>+15.3f} │ {success:>12}  │")

print("└──────────────────────┴──────────────────┴──────────────────┴──────────────────┴───────────────┘")

print("\n┌─────────────────────────────────────────────────────────────────────────────────────────────────┐")
print("│                                    STOI Improvement ⭐                                           │")
print("├──────────────────────┬──────────────────┬──────────────────┬──────────────────┬───────────────┤")
print("│ 實驗組               │ Noisy            │ Enhanced         │ Improvement      │ 成功標準      │")
print("├──────────────────────┼──────────────────┼──────────────────┼──────────────────┼───────────────┤")

for variant in variants:
    name = variant['name']
    label = variant['label']
    r = all_results[name]['STOI']
    success = "✅" if r['improvement'] >= 0.01 else "⚠️" if r['improvement'] >= 0.00 else "❌"
    print(f"│ {label:<20} │ {r['noisy']:>16.3f} │ {r['enhanced']:>16.3f} │ {r['improvement']:>+15.3f} │ {success:>12}  │")

print("└──────────────────────┴──────────────────┴──────────────────┴──────────────────┴───────────────┘")

# 找出最佳配置
print("\n" + "=" * 120)
print("🏆 最佳配置選擇")
print("=" * 120)

# V3-3 最佳
v3_3_variants = ['V3-3_conservative', 'V3-3_moderate', 'V3-3_aggressive']
v3_3_best = max(v3_3_variants, key=lambda x: all_results[x]['STOI']['improvement'])
print(f"\n🥇 V3-3 最佳: {[v['label'] for v in variants if v['name'] == v3_3_best][0]}")
print(f"   STOI Δ: {all_results[v3_3_best]['STOI']['improvement']:+.3f}")
print(f"   PESQ Δ: {all_results[v3_3_best]['PESQ']['improvement']:+.3f}")
print(f"   segSNR Δ: {all_results[v3_3_best]['segSNR']['improvement']:+.2f} dB")

# V3-4 最佳
v3_4_variants = ['V3-4_conservative', 'V3-4_moderate', 'V3-4_aggressive']
v3_4_best = max(v3_4_variants, key=lambda x: all_results[x]['STOI']['improvement'])
print(f"\n🥇 V3-4 最佳: {[v['label'] for v in variants if v['name'] == v3_4_best][0]}")
print(f"   STOI Δ: {all_results[v3_4_best]['STOI']['improvement']:+.3f}")
print(f"   PESQ Δ: {all_results[v3_4_best]['PESQ']['improvement']:+.3f}")
print(f"   segSNR Δ: {all_results[v3_4_best]['segSNR']['improvement']:+.2f} dB")

# 總冠軍
overall_best = max(all_results.keys(), key=lambda x: all_results[x]['STOI']['improvement'])
print(f"\n🏆 總冠軍: {[v['label'] for v in variants if v['name'] == overall_best][0]}")
print(f"   STOI Δ: {all_results[overall_best]['STOI']['improvement']:+.3f}")
print(f"   PESQ Δ: {all_results[overall_best]['PESQ']['improvement']:+.3f}")
print(f"   segSNR Δ: {all_results[overall_best]['segSNR']['improvement']:+.2f} dB")

print("\n" + "=" * 120)
print("完成評估!")
print("=" * 120)

# 保存結果到 CSV
import csv
with open('variant_results.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['Variant', 'segSNR_Δ', 'PESQ_Δ', 'STOI_Δ'])
    for variant in variants:
        name = variant['name']
        writer.writerow([
            variant['label'],
            f"{all_results[name]['segSNR']['improvement']:.2f}",
            f"{all_results[name]['PESQ']['improvement']:.3f}",
            f"{all_results[name]['STOI']['improvement']:.3f}"
        ])

print("\n結果已保存到 variant_results.csv")
