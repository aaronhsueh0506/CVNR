#!/usr/bin/env python3
"""
計算改善（Improvement）指標

對比：
1. Noisy vs Clean（基準，沒有降噪）
2. Enhanced vs Clean（降噪後）
3. Improvement = Enhanced指標 - Noisy指標

使用 Loizou 2008 專業指標評估降噪效果的真實改善量
"""

import numpy as np
import librosa
import os
from pathlib import Path
from typing import Dict, List, Tuple
from utils.metrics_loizou import composite_measure

# 配置
TRIM_SECONDS = 0.5
EVAL_SR = 16000

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

# 我們的方法（需要 trim）
our_methods = ['V1', 'V2', 'V3', 'V3-2', 'V3-3', 'V3-4', 'V4']

# 基準方法（不需要 trim）
benchmark_methods = ['Speex', 'RNNoise']


def load_and_prepare_audio(
    file_path: str,
    original_sr: int,
    needs_trim: bool = False
) -> Tuple[np.ndarray, int]:
    """
    加載並準備音頻用於評估

    參數:
        file_path: 音頻文件路徑
        original_sr: 原始採樣率（48k）
        needs_trim: 是否需要移除前 0.5s（已驗證：測試數據不需要 trim）

    返回:
        audio_16k: 16kHz 音頻數據
        EVAL_SR: 評估採樣率 (16000)
    """
    # 加載音頻（保持原始採樣率）
    audio, sr = librosa.load(file_path, sr=None)

    # ✅ 使用 append_silence 輸入時需要 trim
    # append_silence 文件前添加了 0.5s，需要移除以對齊 clean
    if needs_trim:
        skip_samples = int(TRIM_SECONDS * sr)
        audio = audio[skip_samples:]

    # Resample 到 16kHz 用於評估
    if sr != EVAL_SR:
        audio_16k = librosa.resample(audio, orig_sr=sr, target_sr=EVAL_SR)
    else:
        audio_16k = audio

    return audio_16k, EVAL_SR


def evaluate_single_case(
    clean_path: str,
    noisy_path: str,
    enhanced_path: str,
    needs_trim: bool,
    original_sr: int = 48000
) -> Dict:
    """
    評估單個測試用例，計算 improvement

    返回:
        {
            'noisy_metrics': {...},
            'enhanced_metrics': {...},
            'improvement': {...}
        }
    """
    # 加載音頻
    clean, _ = load_and_prepare_audio(clean_path, original_sr, needs_trim=needs_trim)
    noisy, _ = load_and_prepare_audio(noisy_path, original_sr, needs_trim=needs_trim)
    enhanced, _ = load_and_prepare_audio(enhanced_path, original_sr, needs_trim=needs_trim)

    # 確保長度一致（resample 後可能有微小差異）
    min_len = min(len(clean), len(noisy), len(enhanced))
    clean = clean[:min_len]
    noisy = noisy[:min_len]
    enhanced = enhanced[:min_len]

    # 評估 Noisy vs Clean（基準）
    noisy_metrics = composite_measure(clean, noisy, EVAL_SR)

    # 評估 Enhanced vs Clean（降噪後）
    enhanced_metrics = composite_measure(clean, enhanced, EVAL_SR)

    # 計算 Improvement（正值表示改善）
    improvement = {}
    for key in ['segSNR', 'fwSegSNR', 'global_SNR']:
        # SNR 類指標：enhanced - noisy（正值=改善）
        improvement[key] = enhanced_metrics[key] - noisy_metrics[key]

    # WSS：noisy - enhanced（正值=改善，因為 WSS 越小越好）
    improvement['WSS'] = noisy_metrics['WSS'] - enhanced_metrics['WSS']

    return {
        'noisy_metrics': noisy_metrics,
        'enhanced_metrics': enhanced_metrics,
        'improvement': improvement
    }


def main():
    """
    主評估流程
    """
    print("=" * 100)
    print("降噪改善（Improvement）指標計算")
    print("=" * 100)
    print(f"測試用例: {len(test_cases)} 個")
    print(f"方法數量: {len(our_methods) + len(benchmark_methods)} 個")
    print(f"評估採樣率: {EVAL_SR} Hz")
    print("=" * 100)

    # 存儲所有結果
    all_results = {method: [] for method in our_methods + benchmark_methods}

    # 評估每個測試用例
    for test_id in test_cases:
        print(f"\n處理測試用例: {test_id}")
        print("-" * 100)

        # Clean 參考（無 prepend）
        clean_path = "test_wav/wav/clean.wav"

        # Noisy 輸入（使用 append_silence 目錄的 prepend 文件）
        noisy_path = f"test_wav/wav/append_silence/{test_id}_prepend.wav"

        if not os.path.exists(clean_path):
            print(f"  ⚠️  找不到 clean 文件: {clean_path}")
            continue

        if not os.path.exists(noisy_path):
            print(f"  ⚠️  找不到 noisy 文件: {noisy_path}")
            continue

        # 評估我們的方法（使用新生成的原始輸出）
        for method in our_methods:
            enhanced_path = f"denoised_original/{method}_{test_id}.wav"

            if not os.path.exists(enhanced_path):
                print(f"  ⚠️  {method:8s} - 找不到文件")
                continue

            try:
                result = evaluate_single_case(
                    clean_path,
                    noisy_path,
                    enhanced_path,
                    needs_trim=True,  # ✅ 我們的方法需要 trim（輸入有 prepend）
                    original_sr=48000  # denoised_original/ 目錄是 48kHz 文件
                )
                all_results[method].append(result)

                # 打印改善量
                imp = result['improvement']
                print(f"  ✓ {method:8s} - Improvement: "
                      f"segSNR={imp['segSNR']:+6.2f}, "
                      f"fwSegSNR={imp['fwSegSNR']:+6.2f}, "
                      f"WSS={imp['WSS']:+5.2f}")

            except Exception as e:
                print(f"  ✗ {method:8s} - ERROR: {e}")

        # 評估基準方法
        for method in benchmark_methods:
            if method == 'Speex':
                enhanced_path = f"test_wav/wav/benchmark_wav/speex/speexdsp_{test_id}.wav"
            elif method == 'RNNoise':
                enhanced_path = f"test_wav/wav/benchmark_wav/rnnoise/rnnoise_{test_id}.wav"
            else:
                continue

            if not os.path.exists(enhanced_path):
                print(f"  ⚠️  {method:8s} - 找不到文件")
                continue

            try:
                # ✅ Speex/RNNoise 使用無 prepend 的 noisy 文件作為輸入參考
                benchmark_noisy_path = f"test_wav/wav/{test_id}.wav"

                result = evaluate_single_case(
                    clean_path,
                    benchmark_noisy_path,  # ✅ 使用無 prepend 的 noisy
                    enhanced_path,
                    needs_trim=False,  # ✅ 基準方法不需要 trim
                    original_sr=48000
                )
                all_results[method].append(result)

                # 打印改善量
                imp = result['improvement']
                print(f"  ✓ {method:8s} - Improvement: "
                      f"segSNR={imp['segSNR']:+6.2f}, "
                      f"fwSegSNR={imp['fwSegSNR']:+6.2f}, "
                      f"WSS={imp['WSS']:+5.2f}")

            except Exception as e:
                print(f"  ✗ {method:8s} - ERROR: {e}")

    # 計算平均改善量
    print("\n" + "=" * 100)
    print("平均改善量（Improvement）統計")
    print("=" * 100)
    print(f"{'方法':<12} {'segSNR改善':>12} {'fwSegSNR改善':>13} {'WSS改善':>10} {'評估數量':>10}")
    print("-" * 100)

    method_improvements = {}

    for method in our_methods + benchmark_methods:
        results = all_results[method]

        if len(results) == 0:
            continue

        # 計算平均改善量
        avg_improvement = {
            'segSNR': np.mean([r['improvement']['segSNR'] for r in results]),
            'fwSegSNR': np.mean([r['improvement']['fwSegSNR'] for r in results]),
            'WSS': np.mean([r['improvement']['WSS'] for r in results]),
            'global_SNR': np.mean([r['improvement']['global_SNR'] for r in results])
        }

        method_improvements[method] = avg_improvement

        # 打印
        print(f"{method:<12} "
              f"{avg_improvement['segSNR']:+11.2f} dB "
              f"{avg_improvement['fwSegSNR']:+12.2f} dB "
              f"{avg_improvement['WSS']:+9.2f} "
              f"{len(results):>10}")

    print("=" * 100)

    # 指標解讀
    print("\n指標解讀:")
    print("  segSNR, fwSegSNR, global_SNR 改善: 正值=改善，負值=惡化 ⬆️")
    print("  WSS 改善: 正值=改善（失真減少），負值=惡化（失真增加）⬆️")
    print("\n  改善量 > 0: 降噪有效 ✅")
    print("  改善量 < 0: 降噪反而降低質量 ❌")

    # 保存結果
    output_dir = 'results'
    os.makedirs(output_dir, exist_ok=True)

    # 生成 Markdown 報告
    md_path = f"{output_dir}/improvement_report.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# 降噪改善（Improvement）指標報告\n\n")
        f.write("## 平均改善量統計\n\n")
        f.write("| 方法 | segSNR改善 (dB) | fwSegSNR改善 (dB) | WSS改善 | 評估數量 |\n")
        f.write("|------|-----------------|-------------------|---------|----------|\n")

        for method in our_methods + benchmark_methods:
            if method not in method_improvements:
                continue

            imp = method_improvements[method]
            num_cases = len(all_results[method])

            f.write(f"| {method} | "
                   f"{imp['segSNR']:+.2f} | "
                   f"{imp['fwSegSNR']:+.2f} | "
                   f"{imp['WSS']:+.2f} | "
                   f"{num_cases} |\n")

        f.write("\n## 指標說明\n\n")
        f.write("- **segSNR改善**: 分段 SNR 的改善量（正值=改善）\n")
        f.write("- **fwSegSNR改善**: 頻率加權 segSNR 的改善量（正值=改善）\n")
        f.write("- **WSS改善**: 頻譜失真的減少量（正值=改善，失真減少）\n")
        f.write("\n改善量越大，降噪效果越好。\n")

    print(f"\n✅ Markdown 報告已保存: {md_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()
