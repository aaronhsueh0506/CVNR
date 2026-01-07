#!/usr/bin/env python3
"""
批量參數調優測試

自動執行所有測試配置並收集結果

用法：
    python3 tools/batch_tune.py --versions V3-2          # 單版本測試
    python3 tools/batch_tune.py --versions V3 V3-2 V4    # 多版本測試
    python3 tools/batch_tune.py --all                    # 所有版本測試
    python3 tools/batch_tune.py --resume                 # 從斷點繼續
"""

import os
import sys
import re
import csv
import json
import yaml
import argparse
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


# 版本名稱映射
VERSION_FILENAME_MAP = {
    'V3': 'v3',
    'V3-2': 'v3-2',
    'V3-3': 'v3-3',
    'V3-4': 'v3-4',
    'V4': 'v4',
}

FILENAME_VERSION_MAP = {v: k for k, v in VERSION_FILENAME_MAP.items()}


def parse_config_filename(filename: str) -> Optional[Dict]:
    """解析配置文件名，提取版本和測試編號"""
    # 匹配格式: v3_t001.yaml, v3-2_t001.yaml
    match = re.match(r'^(v3(?:-[234])?|v4)_t(\d+)\.yaml$', filename)
    if match:
        version_filename = match.group(1)
        test_num = int(match.group(2))
        version = FILENAME_VERSION_MAP.get(version_filename)
        if version:
            return {
                'version': version,
                'test_num': test_num,
                'tag': f"{version_filename}_t{test_num:03d}",
                'filename': filename
            }
    return None


def get_configs_for_versions(config_dir: Path, versions: List[str]) -> List[Dict]:
    """獲取指定版本的所有配置"""
    configs = []

    for filename in sorted(os.listdir(config_dir)):
        if not filename.endswith('.yaml'):
            continue

        info = parse_config_filename(filename)
        if info and info['version'] in versions:
            info['path'] = str(config_dir / filename)
            configs.append(info)

    return configs


def load_completed_tests(progress_file: Path) -> set:
    """加載已完成的測試"""
    if not progress_file.exists():
        return set()

    completed = set()
    with open(progress_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                completed.add(line)
    return completed


def save_completed_test(progress_file: Path, tag: str):
    """保存已完成的測試"""
    with open(progress_file, 'a') as f:
        f.write(tag + '\n')


def extract_params_from_config(config_path: str) -> Dict:
    """從配置文件提取參數"""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    params = {}

    if 'spp' in config:
        spp = config['spp']
        params['alpha_xi'] = spp.get('alpha_xi')
        params['q'] = spp.get('q')

    if 'gain_calculation' in config:
        gc = config['gain_calculation']
        params['g_min_db'] = gc.get('g_min_db')
        params['alpha_g'] = gc.get('alpha_g')

    return params


def parse_report(report_path: str) -> Dict:
    """解析報告提取指標"""
    if not os.path.exists(report_path):
        return {}

    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # 通用表格行匹配模式
    # | V3-2 | 1.520 | 1.841 | +0.322 | 13 |
    row_pattern = r'\| (V\d(?:-\d)?) \| [\d.]+ \| ([\d.]+) \| ([+-][\d.]+) \| \d+ \|'

    # 解析 PESQ 表格（限定在 PESQ 部分）
    pesq_section = re.search(r'## 2\. 質量指標對比（PESQ）.*?(?=## 3\.|\Z)', content, re.DOTALL)
    if pesq_section:
        pesq_matches = re.findall(row_pattern, pesq_section.group())
        for version, enhanced, delta in pesq_matches:
            result[f'{version}_PESQ'] = float(enhanced)
            result[f'{version}_PESQ_delta'] = float(delta)

    # 解析 STOI 表格（限定在 STOI 部分）
    stoi_section = re.search(r'## 3\. 質量指標對比（STOI）.*?(?=## 4\.|\Z)', content, re.DOTALL)
    if stoi_section:
        stoi_matches = re.findall(row_pattern, stoi_section.group())
        for version, enhanced, delta in stoi_matches:
            result[f'{version}_STOI'] = float(enhanced)
            result[f'{version}_STOI_delta'] = float(delta)

    # 解析改善量（segSNR）
    improvement_pattern = r'\| (V\d(?:-\d)?) \| ([+-][\d.]+) \| ([+-][\d.]+) \|'
    improvement_section = re.search(r'## 1\. 改善量指標.*?(?=## 2\.|\Z)', content, re.DOTALL)
    if improvement_section:
        imp_matches = re.findall(improvement_pattern, improvement_section.group())
        for version, seg_snr, fw_seg_snr in imp_matches:
            result[f'{version}_segSNR'] = float(seg_snr)
            result[f'{version}_fwSegSNR'] = float(fw_seg_snr)

    return result


def run_test(config_info: Dict, results_dir: Path, verbose: bool = True) -> Optional[Dict]:
    """執行單個測試"""
    version = config_info['version']
    config_path = config_info['path']
    tag = config_info['tag']

    start_time = time.time()

    try:
        # 1. 運行 regenerate_all.py
        if verbose:
            print(f"    運行降噪處理...")

        cmd_regen = [
            'python3', 'regenerate_all.py',
            '--version', version,
            '--config', config_path
        ]
        result = subprocess.run(cmd_regen, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            print(f"    ❌ regenerate_all.py 失敗: {result.stderr[:200]}")
            return None

        # 2. 運行 compute_improvement.py
        if verbose:
            print(f"    計算評估指標...")

        cmd_compute = [
            'python3', 'compute_improvement.py',
            '--tag', tag
        ]
        result = subprocess.run(cmd_compute, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            print(f"    ❌ compute_improvement.py 失敗: {result.stderr[:200]}")
            return None

        # 3. 解析報告
        report_path = f"results/improvement_report_{tag}.md"
        metrics = parse_report(report_path)

        elapsed = time.time() - start_time

        # 提取當前版本的指標
        params = extract_params_from_config(config_path)

        result_data = {
            'tag': tag,
            'version': version,
            'config': config_path,
            'elapsed_sec': round(elapsed, 1),
            **params,
            'PESQ': metrics.get(f'{version}_PESQ'),
            'PESQ_delta': metrics.get(f'{version}_PESQ_delta'),
            'STOI': metrics.get(f'{version}_STOI'),
            'STOI_delta': metrics.get(f'{version}_STOI_delta'),
            'segSNR': metrics.get(f'{version}_segSNR'),
            'fwSegSNR': metrics.get(f'{version}_fwSegSNR'),
        }

        return result_data

    except subprocess.TimeoutExpired:
        print(f"    ❌ 超時")
        return None
    except Exception as e:
        print(f"    ❌ 錯誤: {e}")
        return None


def load_existing_results(csv_path: Path) -> List[Dict]:
    """加載已有的 CSV 結果"""
    if not csv_path.exists():
        return []

    results = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 轉換數值類型
            for key in ['alpha_xi', 'q', 'g_min_db', 'alpha_g', 'PESQ', 'PESQ_delta',
                        'STOI', 'STOI_delta', 'segSNR', 'fwSegSNR', 'elapsed_sec']:
                if key in row and row[key]:
                    try:
                        row[key] = float(row[key])
                    except ValueError:
                        pass
            results.append(row)
    return results


def save_results_csv(new_results: List[Dict], output_path: Path):
    """保存結果到 CSV（合併已有結果，避免重複）"""
    if not new_results:
        return

    fieldnames = [
        'tag', 'version', 'alpha_xi', 'q', 'g_min_db', 'alpha_g',
        'PESQ', 'PESQ_delta', 'STOI', 'STOI_delta', 'segSNR', 'fwSegSNR',
        'elapsed_sec'
    ]

    # 加載已有結果
    existing_results = load_existing_results(output_path)
    existing_tags = {r['tag'] for r in existing_results}

    # 合併結果（新結果覆蓋舊結果）
    merged_results = {r['tag']: r for r in existing_results}
    for r in new_results:
        merged_results[r['tag']] = r

    # 按 tag 排序
    all_results = sorted(merged_results.values(), key=lambda x: x['tag'])

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_results)

    return len(all_results)


def main():
    parser = argparse.ArgumentParser(description='批量參數調優測試')
    parser.add_argument('--versions', type=str, nargs='+',
                        help='指定版本 (例: V3 V3-2 V4)')
    parser.add_argument('--all', action='store_true',
                        help='測試所有版本')
    parser.add_argument('--config-dir', type=str, default='config/tune',
                        help='配置目錄 (默認: config/tune)')
    parser.add_argument('--resume', action='store_true',
                        help='從斷點繼續（跳過已完成的測試）')
    parser.add_argument('--limit', type=int,
                        help='限制測試數量（用於快速驗證）')
    parser.add_argument('--quiet', action='store_true',
                        help='減少輸出')
    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    results_dir = Path('results')
    results_dir.mkdir(exist_ok=True)

    # 確定版本
    if args.all:
        versions = list(VERSION_FILENAME_MAP.keys())
    elif args.versions:
        versions = args.versions
    else:
        print("請指定 --versions 或使用 --all")
        print(f"可用版本: {list(VERSION_FILENAME_MAP.keys())}")
        return

    # 檢查配置目錄
    if not config_dir.exists():
        print(f"❌ 配置目錄不存在: {config_dir}")
        print("請先運行: python3 tools/generate_tune_configs.py")
        return

    # 獲取配置列表
    configs = get_configs_for_versions(config_dir, versions)

    if not configs:
        print(f"❌ 未找到配置文件")
        print(f"目錄: {config_dir}")
        print(f"版本: {versions}")
        return

    # 應用限制
    if args.limit:
        configs = configs[:args.limit]

    # 加載已完成的測試
    progress_file = results_dir / '.tune_progress'
    completed = load_completed_tests(progress_file) if args.resume else set()

    # 過濾已完成的測試
    if args.resume and completed:
        original_count = len(configs)
        configs = [c for c in configs if c['tag'] not in completed]
        print(f"跳過 {original_count - len(configs)} 個已完成的測試")

    print("=" * 80)
    print("批量參數調優測試")
    print("=" * 80)
    print(f"配置目錄: {config_dir}")
    print(f"版本: {versions}")
    print(f"待測試: {len(configs)} 個配置")
    print(f"結果目錄: {results_dir}")
    print("=" * 80)

    if not configs:
        print("沒有待測試的配置")
        return

    # 執行測試
    results = []
    start_time = time.time()

    for i, config_info in enumerate(configs, 1):
        tag = config_info['tag']
        version = config_info['version']

        print(f"\n[{i}/{len(configs)}] 測試 {tag} ({version})")

        result = run_test(config_info, results_dir, verbose=not args.quiet)

        if result:
            results.append(result)
            save_completed_test(progress_file, tag)

            pesq_delta = result.get('PESQ_delta')
            if pesq_delta is not None:
                print(f"    ✓ PESQ Δ: {pesq_delta:+.3f} ({result['elapsed_sec']}s)")
            else:
                print(f"    ✓ 完成 ({result['elapsed_sec']}s)")

            # 即時保存結果（合併已有）
            csv_path = results_dir / 'tune_summary.csv'
            total_count = save_results_csv(results, csv_path)

        else:
            print(f"    ✗ 失敗")

    # 最終統計
    elapsed_total = time.time() - start_time
    csv_path = results_dir / 'tune_summary.csv'

    print("\n" + "=" * 80)
    print("測試完成!")
    print("=" * 80)
    print(f"本次成功: {len(results)}/{len(configs)}")
    print(f"耗時: {elapsed_total/60:.1f} 分鐘")

    # 加載全部結果顯示統計
    all_results = load_existing_results(csv_path)
    if all_results:
        print(f"\nCSV 累計記錄: {len(all_results)} 條")
        print(f"結果文件: {csv_path}")

        # 顯示全部結果中的最佳 PESQ
        print("\n全部記錄中最佳 PESQ 改善 (Top 5):")
        sorted_results = sorted(all_results,
                                key=lambda x: float(x.get('PESQ_delta') or -999),
                                reverse=True)
        for r in sorted_results[:5]:
            pesq_delta = r.get('PESQ_delta')
            if pesq_delta is not None:
                print(f"  {r['tag']}: PESQ Δ={float(pesq_delta):+.3f} "
                      f"(α_ξ={r['alpha_xi']}, q={r['q']}, g_min={r['g_min_db']}, α_g={r['alpha_g']})")

    print("=" * 80)


if __name__ == "__main__":
    main()
