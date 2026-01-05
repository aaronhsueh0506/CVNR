#!/usr/bin/env python3
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

    print("\n" + "=" * 80)
    print("✅ 所有圖表已生成")
    print("=" * 80)
