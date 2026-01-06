#!/usr/bin/env python3
"""
分析遺傳算法優化結果
提取 Pareto 最優解，生成對比報告
"""

import json
import yaml
import numpy as np
from pathlib import Path
from typing import Dict, List
import argparse


def load_evaluation_results(result_dir: Path) -> List[Dict]:
    """加載所有評估結果"""
    results = []
    for eval_file in sorted(result_dir.glob("eval_*.json")):
        with open(eval_file, 'r') as f:
            results.append(json.load(f))
    return results


def calculate_weighted_score(metrics: Dict, weights: List[float] = [0.5, 0.3, 0.2]) -> float:
    """計算加權分數"""
    # 歸一化指標到 [0, 1] 範圍
    pesq_norm = (metrics['pesq'] + 0.3) / 0.6  # 假設範圍 [-0.3, +0.3]
    stoi_norm = (metrics['stoi'] + 0.1) / 0.15  # 假設範圍 [-0.1, +0.05]
    segsnr_norm = (metrics['segsnr'] + 1.0) / 7.0  # 假設範圍 [-1, +6]

    # 限制到 [0, 1]
    pesq_norm = max(0, min(1, pesq_norm))
    stoi_norm = max(0, min(1, stoi_norm))
    segsnr_norm = max(0, min(1, segsnr_norm))

    return weights[0] * pesq_norm + weights[1] * stoi_norm + weights[2] * segsnr_norm


def analyze_version(version: str, result_dir: Path, weights: List[float]) -> Dict:
    """分析單個版本的優化結果"""
    print(f"\n分析 {version}...")

    # 加載結果
    results = load_evaluation_results(result_dir)
    if not results:
        print(f"  ⚠️ 未找到評估結果")
        return None

    print(f"  總評估次數: {len(results)}")

    # 計算加權分數
    for r in results:
        r['weighted_score'] = calculate_weighted_score(r['metrics'], weights)

    # 找出最佳配置（加權分數最高）
    best_result = max(results, key=lambda x: x['weighted_score'])

    # 統計
    pesq_values = [r['metrics']['pesq'] for r in results]
    stoi_values = [r['metrics']['stoi'] for r in results]
    segsnr_values = [r['metrics']['segsnr'] for r in results]

    analysis = {
        'version': version,
        'total_evals': len(results),
        'best_result': best_result,
        'statistics': {
            'pesq': {
                'mean': np.mean(pesq_values),
                'std': np.std(pesq_values),
                'min': np.min(pesq_values),
                'max': np.max(pesq_values)
            },
            'stoi': {
                'mean': np.mean(stoi_values),
                'std': np.std(stoi_values),
                'min': np.min(stoi_values),
                'max': np.max(stoi_values)
            },
            'segsnr': {
                'mean': np.mean(segsnr_values),
                'std': np.std(segsnr_values),
                'min': np.min(segsnr_values),
                'max': np.max(segsnr_values)
            }
        }
    }

    print(f"  最佳加權分數: {best_result['weighted_score']:.4f}")
    print(f"  最佳 PESQ: {best_result['metrics']['pesq']:.3f}")
    print(f"  最佳 STOI: {best_result['metrics']['stoi']:.3f}")
    print(f"  最佳 segSNR: {best_result['metrics']['segsnr']:.2f} dB")

    return analysis


def generate_optimized_config(version: str, best_params: Dict, base_config_path: Path) -> Dict:
    """生成優化後的配置文件"""
    # 加載基礎配置
    with open(base_config_path, 'r') as f:
        config = yaml.safe_load(f)

    # 更新參數
    for param_name, value in best_params.items():
        if param_name in ['alpha_xi', 'q', 'xi_min_db']:
            config['spp'][param_name] = float(value)
        elif param_name in ['g_min_db', 'alpha_g', 'use_spp_weighting']:
            config['gain_calculation'][param_name] = float(value)

    # 添加優化標記
    config['version'] = f"{config.get('version', version)}-optimized"
    config['name'] = f"{config.get('name', version)} (NSGA-II Optimized)"

    return config


def generate_report(analyses: Dict, output_path: Path):
    """生成 Markdown 報告"""
    report = ["# 遺傳算法參數優化結果報告\n"]
    report.append(f"**生成時間**: {Path.ctime(Path(__file__))}\n")
    report.append(f"**優化方法**: NSGA-II 多目標遺傳算法\n")
    report.append(f"**目標權重**: PESQ (0.5) + STOI (0.3) + segSNR (0.2)\n\n")

    report.append("## 1. 最佳配置對比\n\n")
    report.append("| 版本 | 加權分數 | PESQ 改善 | STOI 改善 | segSNR 改善 (dB) | 評估次數 |\n")
    report.append("|------|----------|-----------|-----------|------------------|----------|\n")

    for version, analysis in sorted(analyses.items()):
        if analysis is None:
            continue
        best = analysis['best_result']
        report.append(f"| {version} | {best['weighted_score']:.4f} | "
                     f"{best['metrics']['pesq']:+.3f} | "
                     f"{best['metrics']['stoi']:+.3f} | "
                     f"{best['metrics']['segsnr']:+.2f} | "
                     f"{analysis['total_evals']} |\n")

    report.append("\n## 2. 最佳參數\n\n")
    for version, analysis in sorted(analyses.items()):
        if analysis is None:
            continue
        report.append(f"### {version}\n\n")
        report.append("```yaml\n")
        for param, value in analysis['best_result']['params'].items():
            if isinstance(value, float):
                report.append(f"{param}: {value:.4f}\n")
            else:
                report.append(f"{param}: {value}\n")
        report.append("```\n\n")

    report.append("## 3. 參數分布統計\n\n")
    for version, analysis in sorted(analyses.items()):
        if analysis is None:
            continue
        report.append(f"### {version}\n\n")
        stats = analysis['statistics']
        report.append("| 指標 | 平均值 | 標準差 | 最小值 | 最大值 |\n")
        report.append("|------|--------|--------|--------|--------|\n")
        report.append(f"| PESQ | {stats['pesq']['mean']:+.3f} | {stats['pesq']['std']:.3f} | "
                     f"{stats['pesq']['min']:+.3f} | {stats['pesq']['max']:+.3f} |\n")
        report.append(f"| STOI | {stats['stoi']['mean']:+.3f} | {stats['stoi']['std']:.3f} | "
                     f"{stats['stoi']['min']:+.3f} | {stats['stoi']['max']:+.3f} |\n")
        report.append(f"| segSNR | {stats['segsnr']['mean']:+.2f} | {stats['segsnr']['std']:.2f} | "
                     f"{stats['segsnr']['min']:+.2f} | {stats['segsnr']['max']:+.2f} |\n")
        report.append("\n")

    # 保存報告
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(''.join(report))

    print(f"\n報告已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='分析遺傳算法優化結果')
    parser.add_argument('--timestamp', type=str, default='20260105_230515',
                        help='優化運行的時間戳')
    parser.add_argument('--weights', type=float, nargs=3, default=[0.5, 0.3, 0.2],
                        help='目標權重 [PESQ STOI segSNR]')
    parser.add_argument('--versions', type=str, nargs='+',
                        default=['V3', 'V3-2', 'V3-3', 'V3-4'],
                        help='要分析的版本列表')

    args = parser.parse_args()

    print("=" * 80)
    print("遺傳算法優化結果分析")
    print("=" * 80)

    project_dir = Path(__file__).parent.parent
    optimization_dir = project_dir / 'results' / 'optimization'
    config_dir = project_dir / 'config'

    analyses = {}

    # 分析每個版本
    for version in args.versions:
        result_dir = optimization_dir / f"{version}_{args.timestamp}"
        if not result_dir.exists():
            print(f"\n⚠️ {version}: 結果目錄不存在")
            analyses[version] = None
            continue

        analysis = analyze_version(version, result_dir, args.weights)
        analyses[version] = analysis

        # 生成優化後的配置文件
        if analysis:
            config_name_map = {
                'V3': 'v3_config.yaml',
                'V3-2': 'v3_2_config.yaml',
                'V3-3': 'v3_3_config.yaml',
                'V3-4': 'v3_4_config.yaml'
            }
            base_config = config_dir / config_name_map.get(version, f'{version.lower()}_config.yaml')

            if base_config.exists():
                optimized_config = generate_optimized_config(
                    version,
                    analysis['best_result']['params'],
                    base_config
                )

                # 保存優化配置
                output_config = result_dir / f"{version}_optimized.yaml"
                with open(output_config, 'w', encoding='utf-8') as f:
                    yaml.dump(optimized_config, f, default_flow_style=False, allow_unicode=True)

                print(f"  優化配置已保存: {output_config}")

    # 生成對比報告
    report_path = optimization_dir / f"optimization_report_{args.timestamp}.md"
    generate_report(analyses, report_path)

    print("\n" + "=" * 80)
    print("分析完成!")
    print("=" * 80)


if __name__ == '__main__':
    main()
