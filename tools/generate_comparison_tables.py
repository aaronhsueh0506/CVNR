"""
Generate Comparison Tables - 生成對比表格

生成 5 個對比表格，比較 V1-V3 傳統算法和 RNNoise 的性能。

Usage:
    python generate_comparison_tables.py --theory-only    # 只生成理論表格
    python generate_comparison_tables.py                  # 生成所有表格（需要測試結果）
"""

import sys
import os
import json
import argparse
from typing import Dict, List, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def calculate_theoretical_flops() -> Dict[str, Dict[str, Any]]:
    """
    計算各算法的理論 FLOPs。

    Returns:
        各算法的計算複雜度數據
    """
    # FFT 參數
    fft_size = 512
    num_freq_bins = fft_size // 2 + 1  # 257

    # FFT/IFFT 的 FLOPs: 5 * N * log2(N)
    fft_flops = 5 * fft_size * (fft_size.bit_length() - 1)  # ~23,040 FLOPs

    results = {
        'V1': {
            'name': 'V1 頻譜減法',
            'fft_count': 2,  # FFT + IFFT
            'matrix_ops': '基礎減法',
            'special_functions': '無',
            'flops_per_frame': 2 * fft_flops + num_freq_bins * 3,  # FFT+IFFT + 減法+乘法+最大值
            'memory': '低',
            'notes': '最簡單'
        },
        'V2': {
            'name': 'V2 Wiener',
            'fft_count': 2,
            'matrix_ops': '除法、平方',
            'special_functions': '無',
            'flops_per_frame': 2 * fft_flops + num_freq_bins * 5,  # FFT+IFFT + 平方+除法+增益計算
            'memory': '低',
            'notes': '理論最優'
        },
        'V3': {
            'name': 'V3 SPP-MMSE',
            'fft_count': 2,
            'matrix_ops': 'SNR計算、指數',
            'special_functions': 'exp1()',
            'flops_per_frame': 2 * fft_flops + num_freq_bins * 15,  # FFT+IFFT + SPP計算+MMSE增益+exp1
            'memory': '中',
            'notes': '軟判決'
        },
        'RNNoise': {
            'name': 'RNNoise',
            'fft_count': 0,  # 不使用 FFT，使用 Bark-scale 特徵
            'matrix_ops': 'GRU 矩陣乘法',
            'special_functions': 'tanh, sigmoid',
            # RNNoise: 42 features -> GRU(24) -> Dense(22)
            # GRU 每幀: 3 gates × (input_size × hidden + hidden × hidden)
            # = 3 × (42 × 24 + 24 × 24) × 2 (乘法+加法)
            # = 3 × (1008 + 576) × 2 = 3 × 1584 × 2 = 9,504
            # 特徵提取: ~5,000, FC層: ~2,000
            # 總計: ~16,500 FLOPs/10ms → ~33,000 FLOPs/20ms
            'flops_per_frame': 33000,  # 對齊到 20ms 幀
            'memory': '高',
            'notes': '深度學習'
        }
    }

    # 格式化 FLOPs 為 K
    for algo in results.values():
        algo['flops_per_frame_k'] = algo['flops_per_frame'] / 1000

    return results


def generate_table1_theoretical(flops_data: Dict[str, Dict[str, Any]]) -> str:
    """
    生成表格 1：計算資源對比（理論分析）
    """
    table = []
    table.append("## 表格 1：計算資源對比（理論分析）\n")
    table.append("| 算法 | FFT 次數 | 矩陣運算 | 特殊函數 | FLOPs/幀 | 內存佔用 | 備註 |")
    table.append("|------|---------|---------|---------|----------|---------|------|")

    for algo_id in ['V1', 'V2', 'V3', 'RNNoise']:
        data = flops_data[algo_id]
        fft_str = str(data['fft_count']) if data['fft_count'] > 0 else '無'
        if data['fft_count'] == 2:
            fft_str = '2 (FFT+IFFT)'

        table.append(
            f"| {data['name']} | {fft_str} | {data['matrix_ops']} | "
            f"{data['special_functions']} | ~{data['flops_per_frame_k']:.0f}K | "
            f"{data['memory']} | {data['notes']} |"
        )

    table.append("\n**FLOPs 估算方法：**")
    table.append("- FFT(512): ~23,040 FLOPs (5 × N × log2(N))")
    table.append("- 向量運算：每個頻率點的運算量")
    table.append("  - V1: 減法 + 縮放 (~3 ops/bin)")
    table.append("  - V2: 平方 + 除法 + 增益 (~5 ops/bin)")
    table.append("  - V3: SNR 計算 + SPP + MMSE + exp1() (~15 ops/bin)")
    table.append("- RNNoise GRU: 3 × (input_size × hidden + hidden × hidden) × 2")
    table.append("  - 特徵提取: ~5K FLOPs")
    table.append("  - GRU(42→24): ~10K FLOPs")
    table.append("  - 全連接(24→22): ~2K FLOPs")
    table.append("  - 總計: ~17K FLOPs/10ms → ~33K FLOPs/20ms（對齊幀長）\n")

    return "\n".join(table)


def generate_table2_template() -> str:
    """
    生成表格 2：實際性能對比（模板，需要實測數據填充）
    """
    table = []
    table.append("## 表格 2：實際性能對比（實測）\n")
    table.append("| 算法 | 處理時間 (ms) | CPU 使用率 (%) | 內存 (MB) | RTF | 實時性 |")
    table.append("|------|--------------|---------------|-----------|-----|--------|")
    table.append("| V1 頻譜減法 | - | - | - | - | ? |")
    table.append("| V2 Wiener | - | - | - | - | ? |")
    table.append("| V3 SPP-MMSE | - | - | - | - | ? |")
    table.append("| RNNoise | - | - | - | - | ? |")
    table.append("\n**測試條件：**")
    table.append("- 音頻時長：2 秒")
    table.append("- 採樣率：16 kHz")
    table.append("- 幀長：20 ms")
    table.append("- 幀移：10 ms")
    table.append("- CPU：Apple Silicon / Intel x64")
    table.append("\n**說明：** 運行 `python benchmark_all.py` 後自動填充\n")

    return "\n".join(table)


def generate_table3_template() -> str:
    """
    生成表格 3：音質對比（模板）
    """
    table = []
    table.append("## 表格 3：音質對比（各噪聲類型平均）\n")
    table.append("| 算法 | 輸入 SNR | 輸出 SNR | SNR 提升 | PESQ | STOI | LSD | 音樂噪聲 |")
    table.append("|------|---------|---------|---------|------|------|-----|---------|")
    table.append("| V1 頻譜減法 | 5.0 | - | - | - | - | - | 嚴重 |")
    table.append("| V2 Wiener | 5.0 | - | - | - | - | - | 中等 |")
    table.append("| V3 SPP-MMSE | 5.0 | - | - | - | - | - | 輕微 |")
    table.append("| RNNoise | 5.0 | - | - | - | - | - | 極少 |")
    table.append("\n**說明：** 運行 `python benchmark_all.py --full` 後自動填充\n")

    return "\n".join(table)


def generate_table4_template() -> str:
    """
    生成表格 4：不同噪聲類型下的表現（模板）
    """
    table = []
    table.append("## 表格 4：不同噪聲類型下的表現\n")
    table.append("| 噪聲類型 | 算法 | SNR 提升 (dB) | PESQ | STOI |")
    table.append("|---------|------|--------------|------|------|")

    for noise_type in ['白噪聲', 'Babble', '車內噪聲']:
        for algo in ['V1', 'V2', 'V3', 'RNNoise']:
            algo_name = algo if algo == 'RNNoise' else ''
            table.append(f"| {noise_type} | {algo_name} | - | - | - |")
        noise_type = ''  # 後續行留空

    table.append("\n**說明：** 運行 `python benchmark_all.py --full` 後自動填充\n")

    return "\n".join(table)


def generate_table5_radar() -> str:
    """
    生成表格 5：綜合對比（雷達圖數據）

    基於理論分析和實踐經驗的估計值
    """
    table = []
    table.append("## 表格 5：綜合對比（雷達圖數據）\n")
    table.append("| 維度 | V1 | V2 | V3 | RNNoise |")
    table.append("|------|----|----|----|---------|")

    # 理論評分（基於算法特性）
    scores = {
        '降噪效果 (0-10)': {'V1': 5, 'V2': 6, 'V3': 8, 'RNNoise': 9.5},
        '計算效率 (0-10)': {'V1': 10, 'V2': 9, 'V3': 7, 'RNNoise': 3},
        '語音質量 (0-10)': {'V1': 6, 'V2': 7, 'V3': 8.5, 'RNNoise': 8.5},
        '實時性 (0-10)': {'V1': 10, 'V2': 10, 'V3': 9, 'RNNoise': 6},
        '易部署性 (0-10)': {'V1': 10, 'V2': 10, 'V3': 9, 'RNNoise': 4}
    }

    for dimension, values in scores.items():
        table.append(
            f"| {dimension} | {values['V1']} | {values['V2']} | "
            f"{values['V3']} | {values['RNNoise']} |"
        )

    table.append("\n**評分說明：**")
    table.append("- **降噪效果**: 基於理論能力和文獻報告")
    table.append("- **計算效率**: 基於 FLOPs 計算（越低分數越高）")
    table.append("- **語音質量**: 基於算法保真度和失真程度")
    table.append("- **實時性**: 基於計算複雜度（RTF < 1.0）")
    table.append("- **易部署性**: 基於依賴複雜度和實現難度\n")

    return "\n".join(table)


def generate_all_tables(theory_only: bool = False) -> str:
    """
    生成所有對比表格

    Args:
        theory_only: 是否只生成理論表格

    Returns:
        完整的 Markdown 格式表格
    """
    output = []
    output.append("# 語音降噪算法性能對比\n")
    output.append("**生成時間：** 自動生成")
    output.append("**對比算法：** V1 頻譜減法、V2 Wiener、V3 SPP-MMSE、RNNoise\n")
    output.append("---\n")

    # 計算理論 FLOPs
    flops_data = calculate_theoretical_flops()

    # 表格 1：理論計算資源（必定生成）
    output.append(generate_table1_theoretical(flops_data))
    output.append("\n---\n")

    if theory_only:
        output.append("**說明：** 使用 `--theory-only` 模式，僅生成理論表格。")
        output.append("運行 `python benchmark_all.py` 獲取實測數據後，重新運行此腳本生成完整表格。\n")
    else:
        # 表格 2-4：實測數據（模板）
        output.append(generate_table2_template())
        output.append("\n---\n")

        output.append(generate_table3_template())
        output.append("\n---\n")

        output.append(generate_table4_template())
        output.append("\n---\n")

    # 表格 5：綜合對比（雷達圖數據）
    output.append(generate_table5_radar())
    output.append("\n---\n")

    # 參考標準
    output.append("## 參考標準\n")
    output.append("### 實時性標準 (RTF)")
    output.append("- RTF < 0.3：優秀（可在低功耗設備運行）")
    output.append("- RTF < 0.5：良好（可在移動設備運行）")
    output.append("- RTF < 1.0：合格（實時處理）")
    output.append("- RTF ≥ 1.0：不合格（無法實時）\n")

    output.append("### PESQ 標準")
    output.append("- > 4.0：優秀")
    output.append("- 3.5-4.0：良好")
    output.append("- 3.0-3.5：可接受")
    output.append("- < 3.0：較差\n")

    output.append("### STOI 標準")
    output.append("- > 0.9：優秀")
    output.append("- 0.8-0.9：良好")
    output.append("- 0.7-0.8：可接受")
    output.append("- < 0.7：較差\n")

    return "\n".join(output)


def save_flops_data(flops_data: Dict[str, Dict[str, Any]], output_file: str):
    """
    保存 FLOPs 數據為 JSON
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(flops_data, f, ensure_ascii=False, indent=2)
    print(f"FLOPs data saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Generate comparison tables')
    parser.add_argument('--theory-only', action='store_true',
                       help='只生成理論表格（不需要測試數據）')
    parser.add_argument('--output', type=str, default='comparison_tables.md',
                       help='輸出文件名（默認: comparison_tables.md）')
    parser.add_argument('--flops-json', type=str, default='theoretical_flops.json',
                       help='FLOPs 數據 JSON 文件名')

    args = parser.parse_args()

    print("="*60)
    print("生成語音降噪算法對比表格")
    print("="*60)

    # 生成表格
    tables_md = generate_all_tables(theory_only=args.theory_only)

    # 保存 Markdown
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        args.output
    )
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(tables_md)

    print(f"\n✓ 表格已生成: {output_path}")

    # 保存 FLOPs JSON
    if args.theory_only:
        flops_data = calculate_theoretical_flops()
        flops_json_path = os.path.join(
            os.path.dirname(output_path),
            args.flops_json
        )
        save_flops_data(flops_data, flops_json_path)

    print("\n生成的表格：")
    if args.theory_only:
        print("  - 表格 1: 計算資源對比（理論分析）✓")
        print("  - 表格 5: 綜合對比（雷達圖數據）✓")
        print("\n運行以下命令獲取實測數據：")
        print("  python examples/benchmark_all.py --quick")
    else:
        print("  - 表格 1: 計算資源對比（理論分析）✓")
        print("  - 表格 2: 實際性能對比（模板）")
        print("  - 表格 3: 音質對比（模板）")
        print("  - 表格 4: 不同噪聲類型表現（模板）")
        print("  - 表格 5: 綜合對比（雷達圖數據）✓")
        print("\n⚠  表格 2-4 需要運行測試後填充數據")

    print("\n查看表格：")
    print(f"  cat {args.output}")
    print("="*60)


if __name__ == "__main__":
    main()
