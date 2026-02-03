#!/usr/bin/env python3
"""
VCTK/DEMAND Dataset 評估

對比 noisy vs enhanced vs clean，計算 PESQ/STOI/segSNR/fwSegSNR/WSS/LSD。

用法:
    python compute_improvement_vctk.py --dataset-dir /path/to/vctk_demand
    python compute_improvement_vctk.py --dataset-dir /path/to/vctk_demand --enhanced-dir output_vctk
"""

import numpy as np
import librosa
import os
import argparse
from pathlib import Path
from glob import glob
from typing import Dict, List

from compute_improvement import evaluate_single_case, EVAL_SR


def main():
    parser = argparse.ArgumentParser(description='VCTK/DEMAND Dataset 評估')
    parser.add_argument('--dataset-dir', type=str, required=True,
                        help='Dataset 路徑 (含 noisy/ 和 clean/ 子目錄)')
    parser.add_argument('--enhanced-dir', type=str, default='output_vctk',
                        help='Enhanced 檔案目錄 (預設: output_vctk/)')
    parser.add_argument('--tag', type=str, default='', help='報告標籤')
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    noisy_dir = dataset_dir / 'noisy'
    clean_dir = dataset_dir / 'clean'
    enhanced_dir = Path(args.enhanced_dir)

    # 檢查目錄
    for d, name in [(noisy_dir, 'noisy'), (clean_dir, 'clean'), (enhanced_dir, 'enhanced')]:
        if not d.exists():
            print(f"找不到 {name} 目錄: {d}")
            return

    # 掃描 noisy 檔案
    noisy_files = sorted(glob(str(noisy_dir / '*.wav')))
    if not noisy_files:
        print(f"noisy 目錄中沒有 wav 檔案: {noisy_dir}")
        return

    print("=" * 100)
    print("VCTK/DEMAND Dataset 評估 (V3-2 MMSE-LSA)")
    print("=" * 100)
    print(f"Dataset: {dataset_dir}")
    print(f"Enhanced: {enhanced_dir}")
    print(f"檔案數量: {len(noisy_files)}")
    print(f"評估採樣率: {EVAL_SR} Hz")
    print("=" * 100)

    results = []
    skipped = 0

    for noisy_path in noisy_files:
        filename = os.path.basename(noisy_path)
        clean_path = str(clean_dir / filename)
        enhanced_path = str(enhanced_dir / filename)

        if not os.path.exists(clean_path):
            print(f"  {filename} - 找不到 clean 檔案")
            skipped += 1
            continue

        if not os.path.exists(enhanced_path):
            print(f"  {filename} - 找不到 enhanced 檔案")
            skipped += 1
            continue

        try:
            # 檢測 noisy 的原始採樣率
            noisy_audio, noisy_sr = librosa.load(noisy_path, sr=None, duration=0.1)

            result = evaluate_single_case(
                clean_path,
                noisy_path,
                enhanced_path,
                enhanced_needs_trim=False,
                original_sr=noisy_sr,
                noisy_needs_trim=False
            )
            result['filename'] = filename
            results.append(result)

            imp = result['improvement']
            enh = result['enhanced_metrics']
            fmt = lambda v, d=3: f"{v:.{d}f}" if v is not None else "N/A"

            print(f"  {filename}: "
                  f"segSNR={imp['segSNR']:+.2f}, "
                  f"fwSegSNR={imp['fwSegSNR']:+.2f}, "
                  f"PESQ={fmt(enh.get('PESQ'))}, "
                  f"STOI={fmt(enh.get('STOI'))}")

        except Exception as e:
            print(f"  {filename} - ERROR: {e}")
            skipped += 1

    if not results:
        print("\n沒有成功評估的檔案")
        return

    # 計算平均指標
    print("\n" + "=" * 140)
    print(f"平均指標統計 ({len(results)} 個檔案)")
    print("=" * 140)

    avg_imp = {
        'segSNR': np.mean([r['improvement']['segSNR'] for r in results]),
        'fwSegSNR': np.mean([r['improvement']['fwSegSNR'] for r in results]),
        'WSS': np.mean([r['improvement']['WSS'] for r in results]),
    }

    def avg_metric(key, source='enhanced_metrics'):
        vals = [r[source].get(key) for r in results if r[source].get(key) is not None]
        return np.mean(vals) if vals else None

    avg_noisy_pesq = avg_metric('PESQ', 'noisy_metrics')
    avg_enh_pesq = avg_metric('PESQ')
    avg_noisy_stoi = avg_metric('STOI', 'noisy_metrics')
    avg_enh_stoi = avg_metric('STOI')
    avg_noisy_lsd = avg_metric('LSD', 'noisy_metrics')
    avg_enh_lsd = avg_metric('LSD')

    fmt_v = lambda v, d=3: f"{v:.{d}f}" if v is not None else "N/A"
    fmt_d = lambda v, d=3: f"{v:+.{d}f}" if v is not None else "N/A"
    delta = lambda a, b: (a - b) if (a is not None and b is not None) else None

    print(f"\n改善量 (Improvement):")
    print(f"  segSNR:   {avg_imp['segSNR']:+.2f} dB")
    print(f"  fwSegSNR: {avg_imp['fwSegSNR']:+.2f} dB")
    print(f"  WSS:      {avg_imp['WSS']:+.2f}")

    print(f"\n質量指標:")
    print(f"  {'':12s}  {'Noisy':>8s}  {'Enhanced':>8s}  {'Delta':>8s}")
    print(f"  {'PESQ':12s}  {fmt_v(avg_noisy_pesq):>8s}  {fmt_v(avg_enh_pesq):>8s}  {fmt_d(delta(avg_enh_pesq, avg_noisy_pesq)):>8s}")
    print(f"  {'STOI':12s}  {fmt_v(avg_noisy_stoi):>8s}  {fmt_v(avg_enh_stoi):>8s}  {fmt_d(delta(avg_enh_stoi, avg_noisy_stoi)):>8s}")
    print(f"  {'LSD':12s}  {fmt_v(avg_noisy_lsd, 2):>8s}  {fmt_v(avg_enh_lsd, 2):>8s}  {fmt_d(delta(avg_enh_lsd, avg_noisy_lsd), 2):>8s}")

    print(f"\n評估: {len(results)} 成功, {skipped} 跳過")

    # 生成 Markdown 報告
    output_dir = 'results'
    os.makedirs(output_dir, exist_ok=True)

    tag_suffix = f"_{args.tag}" if args.tag else ""
    md_path = f"{output_dir}/improvement_report_vctk{tag_suffix}.md"

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# VCTK/DEMAND Dataset 評估報告 (V3-2 MMSE-LSA)\n\n")
        f.write(f"- Dataset: `{dataset_dir}`\n")
        f.write(f"- Enhanced: `{enhanced_dir}`\n")
        f.write(f"- 檔案數: {len(results)}\n\n")

        # 總覽表格
        f.write("## 平均指標\n\n")
        f.write("| 指標 | Noisy | Enhanced | Delta |\n")
        f.write("|------|-------|----------|-------|\n")
        f.write(f"| segSNR (dB) | - | - | {avg_imp['segSNR']:+.2f} |\n")
        f.write(f"| fwSegSNR (dB) | - | - | {avg_imp['fwSegSNR']:+.2f} |\n")
        f.write(f"| WSS | - | - | {avg_imp['WSS']:+.2f} |\n")
        f.write(f"| PESQ | {fmt_v(avg_noisy_pesq)} | {fmt_v(avg_enh_pesq)} | {fmt_d(delta(avg_enh_pesq, avg_noisy_pesq))} |\n")
        f.write(f"| STOI | {fmt_v(avg_noisy_stoi)} | {fmt_v(avg_enh_stoi)} | {fmt_d(delta(avg_enh_stoi, avg_noisy_stoi))} |\n")
        f.write(f"| LSD | {fmt_v(avg_noisy_lsd, 2)} | {fmt_v(avg_enh_lsd, 2)} | {fmt_d(delta(avg_enh_lsd, avg_noisy_lsd), 2)} |\n")

        # 逐檔案表格
        f.write("\n## 逐檔案結果\n\n")
        f.write("| 檔案 | segSNR Imp | fwSegSNR Imp | PESQ (N/E) | STOI (N/E) |\n")
        f.write("|------|------------|--------------|------------|------------|\n")

        for r in results:
            imp = r['improvement']
            n = r['noisy_metrics']
            e = r['enhanced_metrics']
            f.write(f"| {r['filename']} "
                    f"| {imp['segSNR']:+.2f} "
                    f"| {imp['fwSegSNR']:+.2f} "
                    f"| {fmt_v(n.get('PESQ'))}/{fmt_v(e.get('PESQ'))} "
                    f"| {fmt_v(n.get('STOI'))}/{fmt_v(e.get('STOI'))} |\n")

    print(f"\nMarkdown 報告已保存: {md_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()
