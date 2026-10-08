#!/usr/bin/env python3
"""
完整評估系統 - 使用 Loizou 2008 專業指標

評估所有七種降噪方法並與 Speex/RNNoise 對標

評估指標:
1. segSNR (Loizou)      - 帶 VAD 的分段 SNR
2. fwSegSNR (Loizou)    - 頻率加權 segSNR
3. WSS (Loizou)         - 加權頻譜斜率距離
4. PESQ (metrics.py)    - 感知語音質量
5. STOI (metrics.py)    - 短時客觀可懂度
6. global_SNR (Loizou)  - 全局 SNR（參考）

處理流程:
- 48kHz 音頻輸入（保持原始採樣率）
- Resample 到 16kHz 進行評估
- 我們的方法: trim 前 0.5s (因為添加了噪聲)
- Speex/RNNoise: 不 trim (沒有添加噪聲)
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import librosa
import json
import csv
from pathlib import Path
from typing import Dict, List, Tuple

# 導入 Loizou 評估指標
from utils.metrics_loizou import (
    composite_measure,
    segmental_snr,
    frequency_weighted_segsnr,
    weighted_spectral_slope
)

# 導入 PESQ/STOI
from utils.metrics import calculate_pesq, calculate_stoi

# 評估配置
EVAL_SR = 16000  # 評估採樣率
TRIM_SECONDS = 0.5  # 我們的方法需要 trim 的時間

# 測試用例
TEST_CASES = [
    'babble_0dB', 'babble_5dB', 'babble_10dB', 'babble_15dB',
    'car_0dB', 'car_5dB', 'car_10dB', 'car_15dB',
    'street_0dB', 'street_5dB', 'street_10dB', 'street_15dB'
]

# 我們的降噪方法
OUR_METHODS = ['V1', 'V2', 'V3', 'V3-2', 'V3-3', 'V3-4']

# Benchmark 方法
BENCHMARK_METHODS = {
    'Speex': 'test_wav/wav/benchmark_wav/speex/speexdsp',
    'RNNoise': 'test_wav/wav/benchmark_wav/rnnoise/rnnoise'
}


def load_and_prepare_audio(
    file_path: str,
    original_sr: int,
    needs_trim: bool = False
) -> Tuple[np.ndarray, int]:
    """
    加載並準備音頻用於評估

    Args:
        file_path: 音頻文件路徑
        original_sr: 原始採樣率 (用於計算 trim samples)
        needs_trim: 是否需要 trim 前 0.5s

    Returns:
        (audio_16k, 16000): Resample 到 16kHz 的音頻和採樣率
    """
    # 加載音頻（保持原始採樣率）
    audio, sr = librosa.load(file_path, sr=None)

    # Trim 前 0.5s（如果需要）
    if needs_trim:
        skip_samples = int(TRIM_SECONDS * sr)
        audio = audio[skip_samples:]

    # Resample 到 16kHz 用於評估
    if sr != EVAL_SR:
        audio_16k = librosa.resample(audio, orig_sr=sr, target_sr=EVAL_SR)
    else:
        audio_16k = audio

    return audio_16k, EVAL_SR


def evaluate_single_file(
    clean_16k: np.ndarray,
    enhanced_16k: np.ndarray,
    method_name: str,
    test_case: str
) -> Dict:
    """
    評估單個文件的所有指標

    Returns:
        包含所有指標的字典
    """
    results = {
        'method': method_name,
        'test_case': test_case
    }

    # 對齊長度
    min_len = min(len(clean_16k), len(enhanced_16k))
    clean_seg = clean_16k[:min_len]
    enhanced_seg = enhanced_16k[:min_len]

    try:
        # 1. Loizou 復合指標 (segSNR, fwSegSNR, WSS, global_SNR)
        loizou_metrics = composite_measure(clean_seg, enhanced_seg, EVAL_SR)
        results.update(loizou_metrics)

        # 2. PESQ
        try:
            pesq_score = calculate_pesq(clean_seg, enhanced_seg, EVAL_SR)
            results['PESQ'] = pesq_score
        except Exception as e:
            print(f"    ⚠️  PESQ failed for {method_name} - {test_case}: {e}")
            results['PESQ'] = None

        # 3. STOI
        try:
            stoi_score = calculate_stoi(clean_seg, enhanced_seg, EVAL_SR)
            results['STOI'] = stoi_score
        except Exception as e:
            print(f"    ⚠️  STOI failed for {method_name} - {test_case}: {e}")
            results['STOI'] = None

    except Exception as e:
        print(f"    ✗ ERROR evaluating {method_name} - {test_case}: {e}")
        return None

    return results


def format_metric(value, metric_name: str) -> str:
    """格式化指標值"""
    if value is None:
        return "N/A"

    # WSS 是唯一越低越好的指標
    if metric_name == 'WSS':
        return f"{value:6.1f}"
    elif metric_name in ['PESQ', 'STOI']:
        return f"{value:5.2f}"
    else:  # SNR 類指標
        return f"{value:7.2f}"


def print_results_table(all_results: List[Dict]):
    """打印結果表格"""
    print("\n" + "=" * 130)
    print("完整評估結果 - Loizou 2008 專業指標")
    print("=" * 130)
    print(f"{'方法':<12} {'測試':<15} {'segSNR':>8} {'fwSegSNR':>9} {'globalSNR':>10} {'WSS':>7} {'PESQ':>6} {'STOI':>6}")
    print("-" * 130)

    for result in all_results:
        if result is None:
            continue

        method = result['method']
        test_case = result['test_case']
        seg_snr = format_metric(result.get('segSNR'), 'segSNR')
        fw_seg_snr = format_metric(result.get('fwSegSNR'), 'fwSegSNR')
        global_snr = format_metric(result.get('global_SNR'), 'global_SNR')
        wss = format_metric(result.get('WSS'), 'WSS')
        pesq = format_metric(result.get('PESQ'), 'PESQ')
        stoi = format_metric(result.get('STOI'), 'STOI')

        print(f"{method:<12} {test_case:<15} {seg_snr} {fw_seg_snr} {global_snr} {wss} {pesq} {stoi}")

    print("=" * 130)


def calculate_averages(all_results: List[Dict]) -> Dict:
    """計算每個方法的平均值"""
    method_metrics = {}

    for result in all_results:
        if result is None:
            continue

        method = result['method']
        if method not in method_metrics:
            method_metrics[method] = {
                'segSNR': [],
                'fwSegSNR': [],
                'global_SNR': [],
                'WSS': [],
                'PESQ': [],
                'STOI': []
            }

        for metric in ['segSNR', 'fwSegSNR', 'global_SNR', 'WSS', 'PESQ', 'STOI']:
            value = result.get(metric)
            if value is not None:
                method_metrics[method][metric].append(value)

    # 計算平均值
    averages = {}
    for method, metrics in method_metrics.items():
        averages[method] = {}
        for metric, values in metrics.items():
            if len(values) > 0:
                averages[method][metric] = np.mean(values)
            else:
                averages[method][metric] = None

    return averages


def print_averages_table(averages: Dict):
    """打印平均值表格"""
    print("\n" + "=" * 100)
    print("平均值統計")
    print("=" * 100)
    print(f"{'方法':<12} {'segSNR':>8} {'fwSegSNR':>9} {'globalSNR':>10} {'WSS':>7} {'PESQ':>6} {'STOI':>6}")
    print("-" * 100)

    for method, metrics in averages.items():
        seg_snr = format_metric(metrics.get('segSNR'), 'segSNR')
        fw_seg_snr = format_metric(metrics.get('fwSegSNR'), 'fwSegSNR')
        global_snr = format_metric(metrics.get('global_SNR'), 'global_SNR')
        wss = format_metric(metrics.get('WSS'), 'WSS')
        pesq = format_metric(metrics.get('PESQ'), 'PESQ')
        stoi = format_metric(metrics.get('STOI'), 'STOI')

        print(f"{method:<12} {seg_snr} {fw_seg_snr} {global_snr} {wss} {pesq} {stoi}")

    print("=" * 100)

    # 指標解讀
    print("\n指標解讀:")
    print("  segSNR, fwSegSNR, global_SNR: 越高越好 ⬆️  (目標: segSNR > 8.0 dB)")
    print("  WSS: 越低越好 ⬇️  (目標: < 50)")
    print("  PESQ: 越高越好 ⬆️  (範圍: -0.5 ~ 4.5, 目標: > 2.5)")
    print("  STOI: 越高越好 ⬆️  (範圍: 0 ~ 1, 目標: > 0.85)")


def convert_to_serializable(obj):
    """將 numpy 類型轉換為 Python 原生類型"""
    if isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


def save_results(all_results: List[Dict], averages: Dict, output_dir: str = 'results'):
    """保存結果到文件"""
    os.makedirs(output_dir, exist_ok=True)

    # 轉換為可序列化格式
    serializable_results = convert_to_serializable(all_results)
    serializable_averages = convert_to_serializable(averages)

    # 1. 保存 JSON (詳細數據)
    json_file = os.path.join(output_dir, 'loizou_evaluation.json')
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'detailed_results': serializable_results,
            'averages': serializable_averages
        }, f, indent=2, ensure_ascii=False)
    print(f"\n✅ 詳細結果已保存: {json_file}")

    # 2. 保存 CSV (表格數據)
    csv_file = os.path.join(output_dir, 'loizou_evaluation.csv')
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['method', 'test_case', 'segSNR', 'fwSegSNR', 'global_SNR', 'WSS', 'PESQ', 'STOI']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in all_results:
            if result:
                writer.writerow(result)
    print(f"✅ CSV 結果已保存: {csv_file}")

    # 3. 保存 Markdown 報告
    md_file = os.path.join(output_dir, 'loizou_evaluation.md')
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("# Loizou 2008 完整評估報告\n\n")
        f.write("## 平均值統計\n\n")
        f.write("| 方法 | segSNR | fwSegSNR | globalSNR | WSS | PESQ | STOI |\n")
        f.write("|------|--------|----------|-----------|-----|------|------|\n")

        for method, metrics in averages.items():
            seg_snr = metrics.get('segSNR', 0) or 0
            fw_seg_snr = metrics.get('fwSegSNR', 0) or 0
            global_snr = metrics.get('global_SNR', 0) or 0
            wss = metrics.get('WSS', 0) or 0
            pesq = metrics.get('PESQ', 0) or 0
            stoi = metrics.get('STOI', 0) or 0

            f.write(f"| {method} | "
                   f"{seg_snr:.2f} | "
                   f"{fw_seg_snr:.2f} | "
                   f"{global_snr:.2f} | "
                   f"{wss:.1f} | "
                   f"{pesq:.2f} | "
                   f"{stoi:.2f} |\n")

        f.write("\n## 指標說明\n\n")
        f.write("- **segSNR**: 帶 VAD 的分段 SNR (越高越好, 目標 > 8.0 dB)\n")
        f.write("- **fwSegSNR**: 頻率加權 segSNR (越高越好, 目標 > 9.0 dB)\n")
        f.write("- **WSS**: 加權頻譜斜率距離 (越低越好, 目標 < 50)\n")
        f.write("- **PESQ**: 感知語音質量 (越高越好, 目標 > 2.5)\n")
        f.write("- **STOI**: 短時客觀可懂度 (越高越好, 目標 > 0.85)\n")

    print(f"✅ Markdown 報告已保存: {md_file}")


def main():
    """主評估流程"""
    print("=" * 100)
    print("完整評估系統 - Loizou 2008 專業指標")
    print("=" * 100)
    print(f"評估採樣率: {EVAL_SR} Hz")
    print(f"測試用例: {len(TEST_CASES)} 個")
    print(f"我們的方法: {len(OUR_METHODS)} 個")
    print(f"Benchmark: {len(BENCHMARK_METHODS)} 個")
    print("=" * 100)

    all_results = []

    # 加載 clean 參考音頻（需要 trim）
    print("\n📁 加載 clean 參考音頻...")
    clean_file = 'test_wav/wav/clean.wav'
    clean_audio, clean_sr = librosa.load(clean_file, sr=None)
    skip_samples = int(TRIM_SECONDS * clean_sr)
    clean_trimmed = clean_audio[skip_samples:]

    # Resample clean 到 16kHz
    clean_16k = librosa.resample(clean_trimmed, orig_sr=clean_sr, target_sr=EVAL_SR)
    print(f"✓ Clean 音頻已加載 (原始: {clean_sr} Hz, 評估: {EVAL_SR} Hz)")

    # 評估 Benchmark 方法
    print("\n🎯 評估 Benchmark 方法...")
    for bench_name, bench_path_prefix in BENCHMARK_METHODS.items():
        print(f"\n  方法: {bench_name}")
        for test_case in TEST_CASES:
            bench_file = f"{bench_path_prefix}_{test_case}.wav"

            if not os.path.exists(bench_file):
                print(f"    ⚠️  文件不存在: {bench_file}")
                continue

            try:
                # Benchmark 方法不需要 trim
                bench_16k, _ = load_and_prepare_audio(bench_file, clean_sr, needs_trim=False)

                # 評估
                result = evaluate_single_file(clean_16k, bench_16k, bench_name, test_case)
                if result:
                    all_results.append(result)
                    print(f"    ✓ {test_case}: segSNR={result.get('segSNR', 0):.2f} dB")
            except Exception as e:
                print(f"    ✗ {test_case}: ERROR - {e}")

    # 評估我們的方法
    print("\n🎯 評估我們的七種方法...")
    for method in OUR_METHODS:
        print(f"\n  方法: {method}")
        for test_case in TEST_CASES:
            our_file = f"denoised/{method}_{test_case}.wav"

            if not os.path.exists(our_file):
                print(f"    ⚠️  文件不存在: {our_file}")
                continue

            try:
                # 我們的方法需要 trim 前 0.5s
                our_16k, _ = load_and_prepare_audio(our_file, clean_sr, needs_trim=True)

                # 評估
                result = evaluate_single_file(clean_16k, our_16k, method, test_case)
                if result:
                    all_results.append(result)
                    print(f"    ✓ {test_case}: segSNR={result.get('segSNR', 0):.2f} dB")
            except Exception as e:
                print(f"    ✗ {test_case}: ERROR - {e}")

    # 打印結果
    print_results_table(all_results)

    # 計算並打印平均值
    averages = calculate_averages(all_results)
    print_averages_table(averages)

    # 保存結果
    save_results(all_results, averages)

    print("\n" + "=" * 100)
    print("✅ 評估完成!")
    print("=" * 100)


if __name__ == "__main__":
    main()
