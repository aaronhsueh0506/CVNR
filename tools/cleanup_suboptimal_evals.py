#!/usr/bin/env python3
"""
清理次優評估結果，只保留 Pareto 最優解
節省磁盤空間並加快後續分析
"""

import json
import numpy as np
from pathlib import Path
from typing import List, Dict
import argparse


def is_dominated(solution: Dict, other_solutions: List[Dict], weights: List[float]) -> bool:
    """
    檢查一個解是否被其他解支配（Pareto dominance）

    Args:
        solution: 要檢查的解
        other_solutions: 其他解的列表
        weights: 目標權重 [PESQ, STOI, segSNR]

    Returns:
        True 如果被支配（即有更好的解存在）
    """
    s_metrics = [
        solution['metrics']['pesq'],
        solution['metrics']['stoi'],
        solution['metrics']['segsnr']
    ]

    for other in other_solutions:
        if other['eval_id'] == solution['eval_id']:
            continue

        o_metrics = [
            other['metrics']['pesq'],
            other['metrics']['stoi'],
            other['metrics']['segsnr']
        ]

        # 檢查是否所有目標都不差於當前解，且至少一個目標更好
        all_not_worse = all(o >= s for o, s in zip(o_metrics, s_metrics))
        at_least_one_better = any(o > s for o, s in zip(o_metrics, s_metrics))

        if all_not_worse and at_least_one_better:
            return True  # 被支配

    return False


def calculate_weighted_score(metrics: Dict, weights: List[float]) -> float:
    """計算加權分數"""
    # 歸一化
    pesq_norm = (metrics['pesq'] + 0.3) / 0.6
    stoi_norm = (metrics['stoi'] + 0.1) / 0.15
    segsnr_norm = (metrics['segsnr'] + 1.0) / 7.0

    # 限制範圍
    pesq_norm = max(0, min(1, pesq_norm))
    stoi_norm = max(0, min(1, stoi_norm))
    segsnr_norm = max(0, min(1, segsnr_norm))

    return weights[0] * pesq_norm + weights[1] * stoi_norm + weights[2] * segsnr_norm


def cleanup_version(result_dir: Path, weights: List[float], keep_top_n: int = 50, min_score: float = 0.3) -> Dict:
    """
    清理單個版本的次優評估結果

    策略：
    1. 保留 Pareto 最優解
    2. 保留加權分數 Top N
    3. 刪除分數低於閾值的解

    Args:
        result_dir: 結果目錄
        weights: 目標權重
        keep_top_n: 保留 Top N 個解
        min_score: 最低分數閾值

    Returns:
        清理統計信息
    """
    # 加載所有評估結果
    eval_files = sorted(result_dir.glob("eval_*.json"))
    if not eval_files:
        return {'total': 0, 'kept': 0, 'deleted': 0, 'saved_mb': 0}

    results = []
    for eval_file in eval_files:
        try:
            with open(eval_file, 'r') as f:
                result = json.load(f)
                result['_file'] = eval_file
                result['_score'] = calculate_weighted_score(result['metrics'], weights)
                results.append(result)
        except:
            continue

    if not results:
        return {'total': 0, 'kept': 0, 'deleted': 0, 'saved_mb': 0}

    # 1. 找出 Pareto 最優解
    pareto_optimal = []
    for result in results:
        if not is_dominated(result, results, weights):
            pareto_optimal.append(result['eval_id'])

    # 2. 找出 Top N 解
    results_sorted = sorted(results, key=lambda x: x['_score'], reverse=True)
    top_n_ids = {r['eval_id'] for r in results_sorted[:keep_top_n]}

    # 3. 決定保留哪些解
    keep_ids = set()
    delete_files = []
    total_size = 0

    for result in results:
        eval_id = result['eval_id']
        score = result['_score']
        file_path = result['_file']
        file_size = file_path.stat().st_size
        total_size += file_size

        # 保留條件：Pareto 最優 OR Top N OR 分數高於閾值
        if eval_id in pareto_optimal or eval_id in top_n_ids or score >= min_score:
            keep_ids.add(eval_id)
        else:
            delete_files.append(file_path)

    # 執行刪除
    deleted_size = 0
    for file_path in delete_files:
        deleted_size += file_path.stat().st_size
        file_path.unlink()

    stats = {
        'total': len(results),
        'kept': len(keep_ids),
        'deleted': len(delete_files),
        'pareto_optimal': len(pareto_optimal),
        'saved_mb': deleted_size / (1024 * 1024)
    }

    return stats


def main():
    parser = argparse.ArgumentParser(description='清理次優評估結果')
    parser.add_argument('--timestamp', type=str, default='20260105_230515',
                        help='優化運行的時間戳')
    parser.add_argument('--weights', type=float, nargs=3, default=[0.5, 0.3, 0.2],
                        help='目標權重 [PESQ STOI segSNR]')
    parser.add_argument('--keep-top-n', type=int, default=50,
                        help='保留 Top N 個解（默認 50）')
    parser.add_argument('--min-score', type=float, default=0.3,
                        help='最低分數閾值（默認 0.3）')
    parser.add_argument('--versions', type=str, nargs='+',
                        default=['V3', 'V3-2', 'V3-3', 'V3-4'],
                        help='要清理的版本')
    parser.add_argument('--dry-run', action='store_true',
                        help='模擬運行，不實際刪除文件')

    args = parser.parse_args()

    print("=" * 80)
    print("清理次優評估結果")
    print("=" * 80)
    print(f"時間戳: {args.timestamp}")
    print(f"保留策略:")
    print(f"  - Pareto 最優解")
    print(f"  - Top {args.keep_top_n} 高分解")
    print(f"  - 分數 >= {args.min_score} 的解")
    if args.dry_run:
        print("  [模擬模式 - 不實際刪除]")
    print("=" * 80)
    print()

    project_dir = Path(__file__).parent.parent
    optimization_dir = project_dir / 'results' / 'optimization'

    total_stats = {
        'total': 0,
        'kept': 0,
        'deleted': 0,
        'pareto_optimal': 0,
        'saved_mb': 0
    }

    for version in args.versions:
        result_dir = optimization_dir / f"{version}_{args.timestamp}"
        if not result_dir.exists():
            print(f"⚠️  {version}: 結果目錄不存在")
            continue

        print(f"處理 {version}...")

        if args.dry_run:
            # 模擬模式：只統計，不刪除
            stats = cleanup_version(result_dir, args.weights, args.keep_top_n, args.min_score)
        else:
            stats = cleanup_version(result_dir, args.weights, args.keep_top_n, args.min_score)

        print(f"  總計: {stats['total']} 評估")
        print(f"  保留: {stats['kept']} ({stats['kept']*100/stats['total']:.1f}%)")
        print(f"    - Pareto 最優: {stats['pareto_optimal']}")
        print(f"  刪除: {stats['deleted']} ({stats['deleted']*100/stats['total']:.1f}%)")
        print(f"  節省空間: {stats['saved_mb']:.2f} MB")
        print()

        for key in total_stats:
            total_stats[key] += stats[key]

    print("=" * 80)
    print("清理完成!")
    print("=" * 80)
    print(f"總計:")
    print(f"  評估總數: {total_stats['total']}")
    print(f"  保留: {total_stats['kept']} ({total_stats['kept']*100/total_stats['total']:.1f}%)")
    print(f"  刪除: {total_stats['deleted']} ({total_stats['deleted']*100/total_stats['total']:.1f}%)")
    print(f"  節省空間: {total_stats['saved_mb']:.2f} MB")
    print("=" * 80)


if __name__ == '__main__':
    main()
