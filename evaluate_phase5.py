#!/usr/bin/env python3
"""
Phase 5 評估腳本

評估 4 組 Phase 5 配置:
- V3-3-Natural
- V3-3-Balanced
- V3-4-Natural
- V3-4-Balanced

對比指標: PESQ, STOI, segSNR
"""

import numpy as np
import librosa
import os
import csv
from pathlib import Path
from typing import Dict, List, Tuple
from utils.metrics_loizou import composite_measure
from utils.metrics import calculate_pesq, calculate_stoi

# 配置
EVAL_SR = 16000

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# Phase 5 方法（不需要 trim，直接從 test_wav/wav 生成）
phase5_methods = ['V3-3-Natural', 'V3-3-Balanced', 'V3-4-Natural', 'V3-4-Balanced']


def load_and_prepare_audio(file_path: str) -> Tuple[np.ndarray, int]:
    """
    加載並準備音頻用於評估

    參數:
        file_path: 音頻文件路徑

    返回:
        audio_16k: 16kHz 音頻數據
        EVAL_SR: 評估採樣率 (16000)
    """
    # 加載音頻
    audio, sr = librosa.load(file_path, sr=None)

    # Resample 到 16kHz 用於評估
    if sr != EVAL_SR:
        audio_16k = librosa.resample(audio, orig_sr=sr, target_sr=EVAL_SR)
    else:
        audio_16k = audio

    return audio_16k, EVAL_SR


def evaluate_single_case(
    clean_path: str,
    noisy_path: str,
    enhanced_path: str
) -> Dict:
    """
    評估單個測試用例，計算 improvement

    參數:
        clean_path: clean 音頻路徑
        noisy_path: noisy 音頻路徑
        enhanced_path: enhanced 音頻路徑

    返回:
        {
            'noisy_metrics': {...},
            'enhanced_metrics': {...},
            'improvement': {...}
        }
    """
    # 加載音頻
    clean, _ = load_and_prepare_audio(clean_path)
    noisy, _ = load_and_prepare_audio(noisy_path)
    enhanced, _ = load_and_prepare_audio(enhanced_path)

    # 確保長度一致
    min_len = min(len(clean), len(noisy), len(enhanced))
    clean = clean[:min_len]
    noisy = noisy[:min_len]
    enhanced = enhanced[:min_len]

    # 評估 Noisy vs Clean（基準）
    noisy_metrics = composite_measure(clean, noisy, EVAL_SR)

    # 評估 Enhanced vs Clean（降噪後）
    enhanced_metrics = composite_measure(clean, enhanced, EVAL_SR)

    # 計算 PESQ
    try:
        noisy_metrics['PESQ'] = calculate_pesq(clean, noisy, EVAL_SR)
        enhanced_metrics['PESQ'] = calculate_pesq(clean, enhanced, EVAL_SR)
    except Exception as e:
        print(f"      ⚠️  PESQ calculation failed: {e}")
        noisy_metrics['PESQ'] = None
        enhanced_metrics['PESQ'] = None

    # 計算 STOI
    try:
        noisy_metrics['STOI'] = calculate_stoi(clean, noisy, EVAL_SR)
        enhanced_metrics['STOI'] = calculate_stoi(clean, enhanced, EVAL_SR)
    except Exception as e:
        print(f"      ⚠️  STOI calculation failed: {e}")
        noisy_metrics['STOI'] = None
        enhanced_metrics['STOI'] = None

    # 計算 Improvement (Δ)
    improvement = {}
    for metric in ['segSNR', 'PESQ', 'STOI']:
        if noisy_metrics.get(metric) is not None and enhanced_metrics.get(metric) is not None:
            improvement[metric] = enhanced_metrics[metric] - noisy_metrics[metric]
        else:
            improvement[metric] = None

    return {
        'noisy_metrics': noisy_metrics,
        'enhanced_metrics': enhanced_metrics,
        'improvement': improvement
    }


def evaluate_method(method: str, base_dir: str) -> Dict[str, Dict]:
    """
    評估一個方法的所有測試用例

    參數:
        method: 方法名稱 (e.g., 'V3-3-Natural')
        base_dir: 項目根目錄

    返回:
        {
            'babble_0dB': {...},
            'babble_5dB': {...},
            ...
        }
    """
    print(f"\n{'='*60}")
    print(f"Evaluating: {method}")
    print(f"{'='*60}")

    results = {}

    # 路徑
    clean_path = os.path.join(base_dir, 'test_wav', 'wav', 'clean.wav')
    noisy_dir = os.path.join(base_dir, 'test_wav', 'wav')
    enhanced_dir = os.path.join(base_dir, 'denoised_phase5', method)

    for test_case in test_cases:
        print(f"  {test_case}...", end=' ')

        noisy_path = os.path.join(noisy_dir, f"{test_case}.wav")
        enhanced_path = os.path.join(enhanced_dir, f"{test_case}.wav")

        # 檢查文件是否存在
        if not os.path.exists(clean_path):
            print(f"⚠️  Clean not found: {clean_path}")
            continue
        if not os.path.exists(noisy_path):
            print(f"⚠️  Noisy not found: {noisy_path}")
            continue
        if not os.path.exists(enhanced_path):
            print(f"⚠️  Enhanced not found: {enhanced_path}")
            continue

        # 評估
        try:
            result = evaluate_single_case(clean_path, noisy_path, enhanced_path)
            results[test_case] = result

            # 打印結果
            imp = result['improvement']
            print(f"✅ PESQ Δ: {imp['PESQ']:+.3f}, STOI Δ: {imp['STOI']:+.4f}, segSNR Δ: {imp['segSNR']:+.2f} dB")
        except Exception as e:
            print(f"❌ Error: {e}")
            continue

    return results


def save_results_to_csv(all_results: Dict[str, Dict], output_path: str):
    """
    保存結果到 CSV

    參數:
        all_results: {method: {test_case: {...}}}
        output_path: 輸出 CSV 路徑
    """
    # 準備數據
    rows = []

    for method in phase5_methods:
        if method not in all_results:
            continue

        for test_case in test_cases:
            if test_case not in all_results[method]:
                continue

            result = all_results[method][test_case]
            imp = result['improvement']

            # 提取 noise type 和 SNR
            parts = test_case.split('_')
            noise_type = parts[0]
            snr = parts[1].replace('dB', '')

            rows.append({
                'Method': method,
                'Noise': noise_type,
                'SNR': snr,
                'Test Case': test_case,
                'PESQ_Δ': imp.get('PESQ'),
                'STOI_Δ': imp.get('STOI'),
                'segSNR_Δ': imp.get('segSNR')
            })

    # 寫入 CSV
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['Method', 'Noise', 'SNR', 'Test Case', 'PESQ_Δ', 'STOI_Δ', 'segSNR_Δ']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Results saved to: {output_path}")


def compute_summary(all_results: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    計算每個方法的平均指標

    參數:
        all_results: {method: {test_case: {...}}}

    返回:
        {method: {'PESQ_Δ': ..., 'STOI_Δ': ..., 'segSNR_Δ': ...}}
    """
    summary = {}

    for method in phase5_methods:
        if method not in all_results:
            continue

        pesq_list = []
        stoi_list = []
        segsnr_list = []

        for test_case, result in all_results[method].items():
            imp = result['improvement']
            if imp['PESQ'] is not None:
                pesq_list.append(imp['PESQ'])
            if imp['STOI'] is not None:
                stoi_list.append(imp['STOI'])
            if imp['segSNR'] is not None:
                segsnr_list.append(imp['segSNR'])

        summary[method] = {
            'PESQ_Δ': np.mean(pesq_list) if pesq_list else None,
            'STOI_Δ': np.mean(stoi_list) if stoi_list else None,
            'segSNR_Δ': np.mean(segsnr_list) if segsnr_list else None
        }

    return summary


def print_summary(summary: Dict[str, Dict]):
    """
    打印摘要表格

    參數:
        summary: {method: {'PESQ_Δ': ..., 'STOI_Δ': ..., 'segSNR_Δ': ...}}
    """
    print("\n" + "="*60)
    print("Phase 5 Summary - Average Improvements")
    print("="*60)
    print(f"{'Method':<20} {'PESQ Δ':>10} {'STOI Δ':>10} {'segSNR Δ':>12}")
    print("-"*60)

    for method in phase5_methods:
        if method not in summary:
            continue

        s = summary[method]
        pesq_str = f"{s['PESQ_Δ']:+.3f}" if s['PESQ_Δ'] is not None else "N/A"
        stoi_str = f"{s['STOI_Δ']:+.4f}" if s['STOI_Δ'] is not None else "N/A"
        segsnr_str = f"{s['segSNR_Δ']:+.2f} dB" if s['segSNR_Δ'] is not None else "N/A"

        print(f"{method:<20} {pesq_str:>10} {stoi_str:>10} {segsnr_str:>12}")

    print("="*60)


def main():
    """主函數"""
    print("\n" + "="*60)
    print("Phase 5 Evaluation")
    print("="*60)

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 評估所有方法
    all_results = {}
    for method in phase5_methods:
        all_results[method] = evaluate_method(method, base_dir)

    # 計算摘要
    summary = compute_summary(all_results)

    # 打印摘要
    print_summary(summary)

    # 保存結果
    output_csv = os.path.join(base_dir, 'results', 'phase5_results.csv')
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    save_results_to_csv(all_results, output_csv)

    # 保存摘要
    summary_csv = os.path.join(base_dir, 'results', 'phase5_summary.csv')
    with open(summary_csv, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['Method', 'PESQ_Δ', 'STOI_Δ', 'segSNR_Δ']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for method in phase5_methods:
            if method in summary:
                s = summary[method]
                writer.writerow({
                    'Method': method,
                    'PESQ_Δ': s['PESQ_Δ'],
                    'STOI_Δ': s['STOI_Δ'],
                    'segSNR_Δ': s['segSNR_Δ']
                })

    print(f"\n✅ Summary saved to: {summary_csv}")

    print("\n" + "="*60)
    print("✅ Phase 5 Evaluation Complete!")
    print("="*60)


if __name__ == '__main__':
    main()
