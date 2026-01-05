#!/usr/bin/env python3
"""
生成 CSV 格式的評估結果

從 compute_improvement.py 的輸出生成方便繪圖的 CSV 文件：
- Methods × SNR 樞紐表格式
- 每個指標獨立的 CSV 文件
- 適合直接用 pandas/matplotlib/seaborn 繪圖
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List
import sys
import os

# 添加父目錄到 path（為了導入 compute_improvement）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_test_case_name(test_case: str) -> tuple:
    """
    解析測試用例名稱，提取噪音類型和 SNR 級別

    例如: "babble_0dB" -> ("babble", "0dB")
    """
    parts = test_case.rsplit('_', 1)
    if len(parts) == 2:
        noise_type = parts[0]
        snr_level = parts[1]
        return noise_type, snr_level
    return None, None


def aggregate_by_snr(
    all_results: Dict[str, List[Dict]],
    metric_key: str,
    source: str = 'improvement'
) -> pd.DataFrame:
    """
    按 SNR 級別聚合指標

    參數:
        all_results: compute_improvement.py 的輸出結果
        metric_key: 指標名稱（如 'segSNR', 'PESQ'）
        source: 'improvement', 'enhanced_metrics', 'noisy_metrics'

    返回:
        DataFrame，行=方法，列=SNR級別
    """
    methods = list(all_results.keys())
    snr_levels = ['0dB', '5dB', '10dB', '15dB']

    # 創建空 DataFrame
    df = pd.DataFrame(index=methods, columns=snr_levels)

    for method in methods:
        results = all_results[method]
        if len(results) == 0:
            continue

        # 按 SNR 分組
        snr_grouped = {snr: [] for snr in snr_levels}

        for result in results:
            # 從測試用例名稱提取 SNR
            # 注意: compute_improvement.py 沒有保存測試用例名稱，需要推斷
            # 我們假設結果順序與 test_cases 一致，或者從文件路徑提取
            # 這裡簡化處理：按順序分配到不同 SNR（3種噪音 × 4個SNR = 12個測試）
            pass

        # 計算每個 SNR 的平均值
        for snr in snr_levels:
            if len(snr_grouped[snr]) > 0:
                df.loc[method, snr] = np.mean(snr_grouped[snr])

    return df


def generate_csv_from_results(results_dir: str = 'results'):
    """
    從評估結果生成 CSV 文件

    注意: 由於 compute_improvement.py 沒有保存 SNR 級別信息，
    這裡使用簡化方案：直接運行 compute_improvement.py 並收集結果
    """
    print("=" * 80)
    print("CSV 報告生成工具")
    print("=" * 80)

    # 創建輸出目錄
    output_dir = Path(results_dir) / 'metrics_by_snr'
    output_dir.mkdir(parents=True, exist_ok=True)

    # 導入並運行 compute_improvement
    print("\n正在運行評估...")
    from compute_improvement import (
        our_methods, benchmark_methods, test_cases,
        evaluate_single_case
    )
    import os

    # 收集結果（按 SNR 分組）
    all_results_by_snr = {}

    # 噪音類型和 SNR 級別
    noise_types = ['babble', 'car', 'street']
    snr_levels = ['0dB', '5dB', '10dB', '15dB']

    # 為每個方法創建數據結構
    for method in our_methods + benchmark_methods:
        all_results_by_snr[method] = {snr: [] for snr in snr_levels}

    # 評估每個測試用例
    for test_id in test_cases:
        # 解析 SNR 級別
        noise_type, snr = parse_test_case_name(test_id)
        if snr not in snr_levels:
            continue

        print(f"  處理: {test_id}")

        # Clean 參考
        clean_path = "test_wav/wav/clean.wav"
        noisy_path_v1_v4 = f"test_wav/wav/append_silence/{test_id}_prepend.wav"
        noisy_path_benchmark = f"test_wav/wav/{test_id}.wav"

        if not os.path.exists(clean_path):
            continue

        # 評估我們的方法
        for method in our_methods:
            enhanced_path = f"denoised_original/{method}_{test_id}.wav"
            if not os.path.exists(enhanced_path):
                continue

            try:
                result = evaluate_single_case(
                    clean_path,
                    noisy_path_v1_v4,
                    enhanced_path,
                    enhanced_needs_trim=True,
                    original_sr=48000,
                    noisy_needs_trim=True
                )
                all_results_by_snr[method][snr].append(result)
            except Exception as e:
                print(f"    ✗ {method}: {e}")

        # 評估基準方法
        for method in benchmark_methods:
            if method == 'Speex':
                enhanced_path = f"test_wav/wav/benchmark_wav/speex/speexdsp_{test_id}.wav"
            elif method == 'RNNoise':
                enhanced_path = f"test_wav/wav/benchmark_wav/rnnoise/rnnoise_{test_id}.wav"
            else:
                continue

            if not os.path.exists(enhanced_path):
                continue

            try:
                result = evaluate_single_case(
                    clean_path,
                    noisy_path_benchmark,
                    enhanced_path,
                    enhanced_needs_trim=False,
                    original_sr=48000,
                    noisy_needs_trim=False
                )
                all_results_by_snr[method][snr].append(result)
            except Exception as e:
                print(f"    ✗ {method}: {e}")

    # 生成 CSV 文件
    print("\n" + "=" * 80)
    print("生成 CSV 文件...")
    print("=" * 80)

    metrics_to_export = [
        ('segSNR_improvement', 'improvement', 'segSNR', '分段SNR改善'),
        ('fwSegSNR_improvement', 'improvement', 'fwSegSNR', '頻率加權segSNR改善'),
        ('WSS_improvement', 'improvement', 'WSS', 'WSS改善'),
        ('PESQ_enhanced', 'enhanced_metrics', 'PESQ', 'PESQ值'),
        ('STOI_enhanced', 'enhanced_metrics', 'STOI', 'STOI值'),
        ('LSD_enhanced', 'enhanced_metrics', 'LSD', 'LSD值'),
        ('PESQ_noisy', 'noisy_metrics', 'PESQ', 'Noisy PESQ'),
        ('STOI_noisy', 'noisy_metrics', 'STOI', 'Noisy STOI'),
        ('LSD_noisy', 'noisy_metrics', 'LSD', 'Noisy LSD'),
    ]

    for csv_name, source_key, metric_key, description in metrics_to_export:
        # 創建 DataFrame
        data = []

        for method in our_methods + benchmark_methods:
            row = {'Method': method}

            for snr in snr_levels:
                results = all_results_by_snr[method][snr]
                if len(results) == 0:
                    row[snr] = None
                    continue

                # 提取指標值
                values = []
                for r in results:
                    try:
                        val = r[source_key][metric_key]
                        if val is not None:
                            values.append(val)
                    except (KeyError, TypeError):
                        pass

                # 計算平均值
                if len(values) > 0:
                    row[snr] = np.mean(values)
                else:
                    row[snr] = None

            # 計算整體平均
            valid_values = [row[snr] for snr in snr_levels if row[snr] is not None]
            if len(valid_values) > 0:
                row['Average'] = np.mean(valid_values)
            else:
                row['Average'] = None

            data.append(row)

        # 轉為 DataFrame
        df = pd.DataFrame(data)

        # 設置列順序
        columns = ['Method'] + snr_levels + ['Average']
        df = df[columns]

        # 保存 CSV
        csv_path = output_dir / f"{csv_name}.csv"
        df.to_csv(csv_path, index=False, float_format='%.4f')
        print(f"  ✅ {description}: {csv_path}")

    # 額外生成改善量 Δ 的 CSV（Enhanced - Noisy）
    print("\n生成改善量 Δ CSV...")

    delta_metrics = [
        ('PESQ_delta', 'PESQ', 'PESQ改善量'),
        ('STOI_delta', 'STOI', 'STOI改善量'),
        ('LSD_delta', 'LSD', 'LSD改善量'),
    ]

    for csv_name, metric_key, description in delta_metrics:
        data = []

        for method in our_methods + benchmark_methods:
            row = {'Method': method}

            for snr in snr_levels:
                results = all_results_by_snr[method][snr]
                if len(results) == 0:
                    row[snr] = None
                    continue

                # 計算 delta
                deltas = []
                for r in results:
                    try:
                        noisy_val = r['noisy_metrics'][metric_key]
                        enh_val = r['enhanced_metrics'][metric_key]
                        if noisy_val is not None and enh_val is not None:
                            # LSD: 越小越好，所以 delta = noisy - enhanced（正值=改善）
                            if metric_key == 'LSD':
                                deltas.append(noisy_val - enh_val)
                            else:
                                deltas.append(enh_val - noisy_val)
                    except (KeyError, TypeError):
                        pass

                if len(deltas) > 0:
                    row[snr] = np.mean(deltas)
                else:
                    row[snr] = None

            # 計算整體平均
            valid_values = [row[snr] for snr in snr_levels if row[snr] is not None]
            if len(valid_values) > 0:
                row['Average'] = np.mean(valid_values)
            else:
                row['Average'] = None

            data.append(row)

        df = pd.DataFrame(data)
        columns = ['Method'] + snr_levels + ['Average']
        df = df[columns]

        csv_path = output_dir / f"{csv_name}.csv"
        df.to_csv(csv_path, index=False, float_format='%.4f')
        print(f"  ✅ {description}: {csv_path}")

    print("\n" + "=" * 80)
    print(f"✅ 所有 CSV 文件已保存到: {output_dir}")
    print("=" * 80)

    # 生成繪圖示例腳本
    generate_plot_example(output_dir)


def generate_plot_example(output_dir: Path):
    """生成繪圖示例腳本"""

    plot_script = output_dir.parent / 'plot_results.py'

    script_content = '''#!/usr/bin/env python3
"""
從 CSV 生成評估結果圖表

使用方法:
    python3 results/plot_results.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# 設置中文字體（Mac）
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# CSV 目錄
csv_dir = Path(__file__).parent / 'metrics_by_snr'

# 繪製熱圖
def plot_heatmap(csv_file: str, title: str, cmap: str = 'RdYlGn',
                 vmin: float = None, vmax: float = None):
    """繪製熱圖"""
    df = pd.read_csv(csv_dir / csv_file)
    df = df.set_index('Method')

    # 排除 Average 列
    data = df.iloc[:, :-1]

    plt.figure(figsize=(10, 6))
    sns.heatmap(data, annot=True, fmt='.3f', cmap=cmap,
                vmin=vmin, vmax=vmax, cbar_kws={'label': 'Value'})
    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel('SNR Level', fontsize=12)
    plt.ylabel('Method', fontsize=12)
    plt.tight_layout()

    output_file = csv_dir.parent / f"{csv_file.replace('.csv', '.png')}"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ 已生成: {output_file}")
    plt.close()


# 繪製折線圖
def plot_line_chart(csv_file: str, title: str, ylabel: str):
    """繪製折線圖"""
    df = pd.read_csv(csv_dir / csv_file)
    df = df.set_index('Method')

    # 排除 Average 列
    data = df.iloc[:, :-1]

    plt.figure(figsize=(12, 6))

    for method in data.index:
        values = data.loc[method].values
        if not pd.isna(values).all():
            plt.plot(data.columns, values, marker='o', label=method, linewidth=2)

    plt.title(title, fontsize=14, fontweight='bold')
    plt.xlabel('SNR Level', fontsize=12)
    plt.ylabel(ylabel, fontsize=12)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    output_file = csv_dir.parent / f"{csv_file.replace('.csv', '_line.png')}"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ 已生成: {output_file}")
    plt.close()


if __name__ == '__main__':
    print("=" * 80)
    print("繪製評估結果圖表")
    print("=" * 80)

    # STOI 熱圖
    plot_heatmap('STOI_enhanced.csv', 'STOI Performance by Method and SNR',
                 vmin=0.0, vmax=1.0)

    # PESQ 熱圖
    plot_heatmap('PESQ_enhanced.csv', 'PESQ Performance by Method and SNR',
                 vmin=1.0, vmax=4.5)

    # segSNR 改善量熱圖
    plot_heatmap('segSNR_improvement.csv', 'segSNR Improvement by Method and SNR',
                 cmap='RdYlGn', vmin=-2, vmax=8)

    # STOI Delta 熱圖
    plot_heatmap('STOI_delta.csv', 'STOI Improvement (Δ) by Method and SNR',
                 cmap='RdYlGn', vmin=-0.2, vmax=0.2)

    # STOI 折線圖
    plot_line_chart('STOI_enhanced.csv', 'STOI vs SNR Level', 'STOI')

    # PESQ 折線圖
    plot_line_chart('PESQ_enhanced.csv', 'PESQ vs SNR Level', 'PESQ')

    # segSNR 改善量折線圖
    plot_line_chart('segSNR_improvement.csv', 'segSNR Improvement vs SNR Level',
                    'segSNR Improvement (dB)')

    print("\\n" + "=" * 80)
    print("✅ 所有圖表已生成")
    print("=" * 80)
'''

    with open(plot_script, 'w', encoding='utf-8') as f:
        f.write(script_content)

    # 添加執行權限
    import stat
    st = os.stat(plot_script)
    os.chmod(plot_script, st.st_mode | stat.S_IEXEC)

    print(f"\n✅ 繪圖示例腳本已生成: {plot_script}")
    print(f"   使用方法: python3 {plot_script}")


if __name__ == '__main__':
    generate_csv_from_results()
