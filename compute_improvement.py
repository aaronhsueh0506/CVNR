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
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from utils.metrics_loizou import composite_measure
from utils.metrics import calculate_pesq, calculate_stoi, calculate_lsd

# 配置
TRIM_SECONDS = 0.5
EVAL_SR = 16000

# 測試用例
noise_types = ['babble', 'car', 'street']
snr_levels = [0, 5, 10, 15]
test_cases = ['clean'] + [f"{n}_{s}dB" for n in noise_types for s in snr_levels]  # 加入 clean.wav 高 SNR 測試

# 我們的方法（需要 trim）
our_methods = ['V1', 'V2', 'V3', 'V3-2', 'V3-3']

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
    enhanced_needs_trim: bool,
    original_sr: int = 48000,
    noisy_needs_trim: bool = False
) -> Dict:
    """
    評估單個測試用例，計算 improvement

    參數:
        clean_path: clean 音頻路徑（無 prepend）
        noisy_path: noisy 音頻路徑
        enhanced_path: enhanced 音頻路徑
        enhanced_needs_trim: enhanced 是否需要 trim（V1-V4 需要，Speex/RNNoise 不需要）
        original_sr: 原始採樣率
        noisy_needs_trim: noisy 是否需要 trim（V1-V4 使用 prepend noisy 需要，Speex/RNNoise 不需要）

    返回:
        {
            'noisy_metrics': {...},
            'enhanced_metrics': {...},
            'improvement': {...}
        }
    """
    # 加載音頻
    clean, _ = load_and_prepare_audio(clean_path, original_sr, needs_trim=False)
    noisy, _ = load_and_prepare_audio(noisy_path, original_sr, needs_trim=noisy_needs_trim)
    enhanced, _ = load_and_prepare_audio(enhanced_path, original_sr, needs_trim=enhanced_needs_trim)

    # 確保長度一致（resample 後可能有微小差異）
    min_len = min(len(clean), len(noisy), len(enhanced))
    clean = clean[:min_len]
    noisy = noisy[:min_len]
    enhanced = enhanced[:min_len]

    # 評估 Noisy vs Clean（基準）
    noisy_metrics = composite_measure(clean, noisy, EVAL_SR)

    # 評估 Enhanced vs Clean（降噪後）
    enhanced_metrics = composite_measure(clean, enhanced, EVAL_SR)

    # 額外計算 PESQ/STOI/LSD（為 enhanced 和 noisy 都計算，用於對比）
    # Enhanced 指標
    try:
        enhanced_metrics['PESQ'] = calculate_pesq(clean, enhanced, EVAL_SR)
    except ImportError:
        if not hasattr(calculate_pesq, '_import_warned'):
            print("Warning: PESQ library not installed. Install with: pip install pesq")
            calculate_pesq._import_warned = True
        enhanced_metrics['PESQ'] = None
    except Exception as e:
        print(f"Warning: PESQ calculation failed for enhanced: {e}")
        enhanced_metrics['PESQ'] = None

    try:
        # 調試信息
        print(f"      [DEBUG] STOI計算 (Enhanced): clean_len={len(clean)}, "
              f"enhanced_len={len(enhanced)}, sr={EVAL_SR}")

        enhanced_metrics['STOI'] = calculate_stoi(clean, enhanced, EVAL_SR)

        # 如果 STOI < 0.3，打印警告
        if enhanced_metrics['STOI'] is not None and enhanced_metrics['STOI'] < 0.3:
            print(f"      ⚠️  STOI 異常低: {enhanced_metrics['STOI']:.3f} "
                  f"(預期 > 0.6，可能是音頻對齊問題)")
    except ImportError:
        if not hasattr(calculate_stoi, '_import_warned'):
            print("Warning: STOI library not installed. Install with: pip install pystoi")
            calculate_stoi._import_warned = True
        enhanced_metrics['STOI'] = None
    except Exception as e:
        print(f"Warning: STOI calculation failed for enhanced: {e}")
        enhanced_metrics['STOI'] = None

    try:
        enhanced_metrics['LSD'] = calculate_lsd(clean, enhanced)
    except Exception as e:
        print(f"Warning: LSD calculation failed for enhanced: {e}")
        enhanced_metrics['LSD'] = None

    # Noisy 指標（用於對比）
    try:
        noisy_metrics['PESQ'] = calculate_pesq(clean, noisy, EVAL_SR)
    except Exception:
        noisy_metrics['PESQ'] = None

    try:
        noisy_metrics['STOI'] = calculate_stoi(clean, noisy, EVAL_SR)
    except Exception:
        noisy_metrics['STOI'] = None

    try:
        noisy_metrics['LSD'] = calculate_lsd(clean, noisy)
    except Exception:
        noisy_metrics['LSD'] = None

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
    parser = argparse.ArgumentParser(description='計算改善（Improvement）指標')
    parser.add_argument('--tag', type=str, default='', help='報告標籤，用於區分不同測試')
    args = parser.parse_args()

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

        # Noisy 輸入（V1-V4 使用 prepend 文件，Speex/RNNoise 使用原始文件）
        # Clean 測試特殊處理
        if test_id == 'clean':
            noisy_path_v1_v4 = "test_wav/wav/append_silence/clean_prepend.wav"
            noisy_path_benchmark = "test_wav/wav/clean.wav"
        else:
            noisy_path_v1_v4 = f"test_wav/wav/append_silence/{test_id}_prepend.wav"
            noisy_path_benchmark = f"test_wav/wav/{test_id}.wav"

        if not os.path.exists(clean_path):
            print(f"  ⚠️  找不到 clean 文件: {clean_path}")
            continue

        if not os.path.exists(noisy_path_v1_v4):
            print(f"  ⚠️  找不到 V1-V4 noisy 文件: {noisy_path_v1_v4}")
            continue

        if not os.path.exists(noisy_path_benchmark):
            print(f"  ⚠️  找不到 benchmark noisy 文件: {noisy_path_benchmark}")
            continue

        # 評估我們的方法（使用新生成的輸出）
        for method in our_methods:
            enhanced_path = f"output/{method}_{test_id}.wav"

            if not os.path.exists(enhanced_path):
                print(f"  ⚠️  {method:8s} - 找不到文件")
                continue

            try:
                result = evaluate_single_case(
                    clean_path,
                    noisy_path_v1_v4,  # ✅ V1-V4 使用 prepend 的 noisy（與降噪器輸入一致）
                    enhanced_path,
                    enhanced_needs_trim=True,  # ✅ V1-V4 輸出需要 trim（處理時有 prepend）
                    original_sr=16000,  # output/ 目錄統一為 16kHz 文件
                    noisy_needs_trim=True  # ✅ V1-V4 的 noisy 也需要 trim（與 enhanced 對齊）
                )
                all_results[method].append(result)

                # 打印改善量
                imp = result['improvement']
                noisy = result['noisy_metrics']
                enh = result['enhanced_metrics']

                print(f"  ✓ {method:8s} - Improvement: "
                      f"segSNR={imp['segSNR']:+6.2f}, "
                      f"fwSegSNR={imp['fwSegSNR']:+6.2f}, "
                      f"WSS={imp['WSS']:+5.2f}")

                # 格式化函數
                def fmt(val, digits=3):
                    return f"{val:.{digits}f}" if val is not None else "  N/A"

                # 打印完整對比（Noisy → Enhanced → Δ）
                print(f"             Noisy:    PESQ={fmt(noisy.get('PESQ'))}, "
                      f"STOI={fmt(noisy.get('STOI'))}, LSD={fmt(noisy.get('LSD'), 2)}")
                print(f"             Enhanced: PESQ={fmt(enh.get('PESQ'))}, "
                      f"STOI={fmt(enh.get('STOI'))}, LSD={fmt(enh.get('LSD'), 2)}")

                # 計算 improvement（如果兩者都有值）
                if noisy.get('PESQ') is not None and enh.get('PESQ') is not None:
                    pesq_imp = enh['PESQ'] - noisy['PESQ']
                    stoi_imp = enh['STOI'] - noisy['STOI'] if (noisy.get('STOI') and enh.get('STOI')) else None
                    lsd_imp = enh['LSD'] - noisy['LSD'] if (noisy.get('LSD') and enh.get('LSD')) else None
                    print(f"             Δ:        PESQ={pesq_imp:+.3f}", end="")
                    if stoi_imp is not None:
                        print(f", STOI={stoi_imp:+.3f}", end="")
                    if lsd_imp is not None:
                        print(f", LSD={lsd_imp:+.2f}", end="")
                    print()

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
                result = evaluate_single_case(
                    clean_path,
                    noisy_path_benchmark,  # ✅ Speex/RNNoise 使用無 prepend 的 noisy
                    enhanced_path,
                    enhanced_needs_trim=False,  # ✅ Speex/RNNoise 輸出不需要 trim
                    original_sr=48000,
                    noisy_needs_trim=False  # ✅ Speex/RNNoise 的 noisy 不需要 trim
                )
                all_results[method].append(result)

                # 打印改善量
                imp = result['improvement']
                noisy = result['noisy_metrics']
                enh = result['enhanced_metrics']

                print(f"  ✓ {method:8s} - Improvement: "
                      f"segSNR={imp['segSNR']:+6.2f}, "
                      f"fwSegSNR={imp['fwSegSNR']:+6.2f}, "
                      f"WSS={imp['WSS']:+5.2f}")

                # 格式化函數
                def fmt(val, digits=3):
                    return f"{val:.{digits}f}" if val is not None else "  N/A"

                # 打印完整對比（Noisy → Enhanced → Δ）
                print(f"             Noisy:    PESQ={fmt(noisy.get('PESQ'))}, "
                      f"STOI={fmt(noisy.get('STOI'))}, LSD={fmt(noisy.get('LSD'), 2)}")
                print(f"             Enhanced: PESQ={fmt(enh.get('PESQ'))}, "
                      f"STOI={fmt(enh.get('STOI'))}, LSD={fmt(enh.get('LSD'), 2)}")

                # 計算 improvement（如果兩者都有值）
                if noisy.get('PESQ') is not None and enh.get('PESQ') is not None:
                    pesq_imp = enh['PESQ'] - noisy['PESQ']
                    stoi_imp = enh['STOI'] - noisy['STOI'] if (noisy.get('STOI') and enh.get('STOI')) else None
                    lsd_imp = enh['LSD'] - noisy['LSD'] if (noisy.get('LSD') and enh.get('LSD')) else None
                    print(f"             Δ:        PESQ={pesq_imp:+.3f}", end="")
                    if stoi_imp is not None:
                        print(f", STOI={stoi_imp:+.3f}", end="")
                    if lsd_imp is not None:
                        print(f", LSD={lsd_imp:+.2f}", end="")
                    print()

            except Exception as e:
                print(f"  ✗ {method:8s} - ERROR: {e}")

    # 計算平均改善量和質量指標
    print("\n" + "=" * 140)
    print("平均指標統計（所有測試用例平均）")
    print("=" * 140)

    # 表格標題
    print(f"{'方法':<10} | {'segSNR↑':>8} {'fwSegSNR↑':>9} {'WSS↑':>6} | "
          f"{'N-PESQ':>7} {'E-PESQ':>7} {'Δ':>7} | "
          f"{'N-STOI':>7} {'E-STOI':>7} {'Δ':>7} | "
          f"{'N-LSD':>7} {'E-LSD':>7} {'Δ':>7} | {'評估數':>5}")
    print("-" * 140)

    method_improvements = {}

    # 格式化函數
    def fmt_val(val, digits=3, width=7):
        if val is None:
            return " " * (width - 3) + "N/A"
        return f"{val:>{width}.{digits}f}"

    def fmt_delta(val, digits=3, width=7):
        if val is None:
            return " " * (width - 3) + "N/A"
        return f"{val:>+{width}.{digits}f}"

    for method in our_methods + benchmark_methods:
        results = all_results[method]

        if len(results) == 0:
            continue

        # 計算改善量平均
        avg_imp = {
            'segSNR': np.mean([r['improvement']['segSNR'] for r in results]),
            'fwSegSNR': np.mean([r['improvement']['fwSegSNR'] for r in results]),
            'WSS': np.mean([r['improvement']['WSS'] for r in results]),
        }

        # 計算 noisy 平均
        avg_noisy = {}
        for metric in ['PESQ', 'STOI', 'LSD']:
            vals = [r['noisy_metrics'].get(metric) for r in results
                    if r['noisy_metrics'].get(metric) is not None]
            avg_noisy[metric] = np.mean(vals) if vals else None

        # 計算 enhanced 平均
        avg_enh = {}
        for metric in ['PESQ', 'STOI', 'LSD']:
            vals = [r['enhanced_metrics'].get(metric) for r in results
                    if r['enhanced_metrics'].get(metric) is not None]
            avg_enh[metric] = np.mean(vals) if vals else None

        # 計算指標改善量
        pesq_delta = (avg_enh['PESQ'] - avg_noisy['PESQ']) if (avg_noisy['PESQ'] and avg_enh['PESQ']) else None
        stoi_delta = (avg_enh['STOI'] - avg_noisy['STOI']) if (avg_noisy['STOI'] and avg_enh['STOI']) else None
        lsd_delta = (avg_enh['LSD'] - avg_noisy['LSD']) if (avg_noisy['LSD'] and avg_enh['LSD']) else None

        method_improvements[method] = avg_imp

        # 打印
        print(f"{method:<10} | "
              f"{avg_imp['segSNR']:+8.2f} {avg_imp['fwSegSNR']:+9.2f} {avg_imp['WSS']:+6.2f} | "
              f"{fmt_val(avg_noisy['PESQ'])} {fmt_val(avg_enh['PESQ'])} {fmt_delta(pesq_delta)} | "
              f"{fmt_val(avg_noisy['STOI'])} {fmt_val(avg_enh['STOI'])} {fmt_delta(stoi_delta)} | "
              f"{fmt_val(avg_noisy['LSD'], 2)} {fmt_val(avg_enh['LSD'], 2)} {fmt_delta(lsd_delta, 2)} | "
              f"{len(results):>5}")

    print("=" * 140)

    # 指標解讀
    print("\n指標解讀:")
    print("  改善量指標 (Improvement ↑):")
    print("    segSNR, fwSegSNR 改善: 正值=改善，負值=惡化")
    print("    WSS 改善: 正值=改善（失真減少），負值=惡化（失真增加）")
    print("\n  質量指標 (N-xxx = Noisy, E-xxx = Enhanced, Δ = Improvement):")
    print("    PESQ: 1.0-4.5 (越高越好，> 3.0 為良好)")
    print("    STOI: 0.0-1.0 (越高越好，> 0.8 為良好)")
    print("    LSD: Log Spectral Distance (越低越好，< 1.0 為良好)")
    print("\n  ✅ Δ > 0: 降噪改善質量")
    print("  ❌ Δ < 0: 降噪降低質量")

    # 保存結果
    output_dir = 'results'
    os.makedirs(output_dir, exist_ok=True)

    # 生成 Markdown 報告（4 個獨立表格）
    tag_suffix = f"_{args.tag}" if args.tag else ""
    md_path = f"{output_dir}/improvement_report{tag_suffix}.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# 降噪評估完整報告\n\n")

        # 表格 1: 改善量指標
        f.write("## 1. 改善量指標（Improvement）\n\n")
        f.write("| 方法 | segSNR改善↑ (dB) | fwSegSNR改善↑ (dB) | WSS改善↑ | 評估數 |\n")
        f.write("|------|------------------|---------------------|----------|--------|\n")

        for method in our_methods + benchmark_methods:
            if method not in method_improvements:
                continue
            imp = method_improvements[method]
            results = all_results[method]
            num_cases = len(results)
            f.write(f"| {method} | {imp['segSNR']:+.2f} | {imp['fwSegSNR']:+.2f} | "
                   f"{imp['WSS']:+.2f} | {num_cases} |\n")

        # 表格 2: PESQ 對比
        f.write("\n## 2. 質量指標對比（PESQ）\n\n")
        f.write("| 方法 | Noisy PESQ | Enhanced PESQ | 改善量 Δ | 評估數 |\n")
        f.write("|------|------------|---------------|----------|--------|\n")

        for method in our_methods + benchmark_methods:
            if method not in method_improvements:
                continue
            results = all_results[method]
            num_cases = len(results)

            # 計算 noisy 和 enhanced PESQ 平均
            noisy_pesq_vals = [r['noisy_metrics'].get('PESQ') for r in results
                               if r['noisy_metrics'].get('PESQ') is not None]
            enh_pesq_vals = [r['enhanced_metrics'].get('PESQ') for r in results
                             if r['enhanced_metrics'].get('PESQ') is not None]

            avg_noisy_pesq = np.mean(noisy_pesq_vals) if noisy_pesq_vals else None
            avg_enh_pesq = np.mean(enh_pesq_vals) if enh_pesq_vals else None
            pesq_delta = (avg_enh_pesq - avg_noisy_pesq) if (avg_noisy_pesq and avg_enh_pesq) else None

            noisy_str = f"{avg_noisy_pesq:.3f}" if avg_noisy_pesq is not None else "N/A"
            enh_str = f"{avg_enh_pesq:.3f}" if avg_enh_pesq is not None else "N/A"
            delta_str = f"{pesq_delta:+.3f}" if pesq_delta is not None else "N/A"

            f.write(f"| {method} | {noisy_str} | {enh_str} | {delta_str} | {num_cases} |\n")

        # 表格 3: STOI 對比
        f.write("\n## 3. 質量指標對比（STOI）\n\n")
        f.write("| 方法 | Noisy STOI | Enhanced STOI | 改善量 Δ | 評估數 |\n")
        f.write("|------|------------|---------------|----------|--------|\n")

        for method in our_methods + benchmark_methods:
            if method not in method_improvements:
                continue
            results = all_results[method]
            num_cases = len(results)

            # 計算 noisy 和 enhanced STOI 平均
            noisy_stoi_vals = [r['noisy_metrics'].get('STOI') for r in results
                               if r['noisy_metrics'].get('STOI') is not None]
            enh_stoi_vals = [r['enhanced_metrics'].get('STOI') for r in results
                             if r['enhanced_metrics'].get('STOI') is not None]

            avg_noisy_stoi = np.mean(noisy_stoi_vals) if noisy_stoi_vals else None
            avg_enh_stoi = np.mean(enh_stoi_vals) if enh_stoi_vals else None
            stoi_delta = (avg_enh_stoi - avg_noisy_stoi) if (avg_noisy_stoi and avg_enh_stoi) else None

            noisy_str = f"{avg_noisy_stoi:.3f}" if avg_noisy_stoi is not None else "N/A"
            enh_str = f"{avg_enh_stoi:.3f}" if avg_enh_stoi is not None else "N/A"
            delta_str = f"{stoi_delta:+.3f}" if stoi_delta is not None else "N/A"

            f.write(f"| {method} | {noisy_str} | {enh_str} | {delta_str} | {num_cases} |\n")

        # 表格 4: LSD 對比
        f.write("\n## 4. 質量指標對比（LSD）\n\n")
        f.write("| 方法 | Noisy LSD | Enhanced LSD | 改善量 Δ | 評估數 |\n")
        f.write("|------|-----------|--------------|----------|--------|\n")

        for method in our_methods + benchmark_methods:
            if method not in method_improvements:
                continue
            results = all_results[method]
            num_cases = len(results)

            # 計算 noisy 和 enhanced LSD 平均
            noisy_lsd_vals = [r['noisy_metrics'].get('LSD') for r in results
                              if r['noisy_metrics'].get('LSD') is not None]
            enh_lsd_vals = [r['enhanced_metrics'].get('LSD') for r in results
                            if r['enhanced_metrics'].get('LSD') is not None]

            avg_noisy_lsd = np.mean(noisy_lsd_vals) if noisy_lsd_vals else None
            avg_enh_lsd = np.mean(enh_lsd_vals) if enh_lsd_vals else None
            lsd_delta = (avg_enh_lsd - avg_noisy_lsd) if (avg_noisy_lsd and avg_enh_lsd) else None

            noisy_str = f"{avg_noisy_lsd:.2f}" if avg_noisy_lsd is not None else "N/A"
            enh_str = f"{avg_enh_lsd:.2f}" if avg_enh_lsd is not None else "N/A"
            delta_str = f"{lsd_delta:+.2f}" if lsd_delta is not None else "N/A"

            f.write(f"| {method} | {noisy_str} | {enh_str} | {delta_str} | {num_cases} |\n")

        # 指標說明
        f.write("\n## 指標說明\n\n")
        f.write("### 改善量指標 (Improvement)\n\n")
        f.write("- **segSNR改善↑**: 分段 SNR 的改善量（正值=改善，使用 VAD 排除純噪音片段）\n")
        f.write("- **fwSegSNR改善↑**: 頻率加權 segSNR 的改善量（正值=改善，符合人耳感知）\n")
        f.write("- **WSS改善↑**: 頻譜失真的減少量（正值=改善，失真減少）\n\n")
        f.write("### 質量指標 (Quality)\n\n")
        f.write("- **PESQ**: Perceptual Evaluation of Speech Quality (1.0-4.5，越高越好，> 3.0 為良好)\n")
        f.write("- **STOI**: Short-Time Objective Intelligibility (0.0-1.0，越高越好，> 0.8 為良好)\n")
        f.write("- **LSD**: Log Spectral Distance (越低越好，< 1.0 為良好)\n")
        f.write("- **Δ (Delta)**: Enhanced - Noisy 的差值（正值表示改善，負值表示惡化）\n\n")
        f.write("---\n\n")
        f.write("✅ **Δ > 0**: 降噪改善質量  \n")
        f.write("❌ **Δ < 0**: 降噪降低質量\n")

    print(f"\n✅ Markdown 報告已保存: {md_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()