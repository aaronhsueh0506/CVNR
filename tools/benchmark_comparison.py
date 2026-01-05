#!/usr/bin/env python3
"""
Benchmark Comparison - 公平對標評估系統

對 Speex、RNNoise 和我們的算法使用相同的評估流程，確保公平對比。

關鍵修復:
1. 移除前 0.5 秒 append 噪聲段（防止評估偏差）
2. 使用 segSNR 作為主要指標（Loizou 2008 推薦）
3. 計算 fwSegSNR、WSS、PESQ、STOI 等多維度指標
4. 生成對比表格和詳細報告

用法:
    python benchmark_comparison.py --skip-seconds 0.5 --output results/comparison.json
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import librosa
import soundfile as sf
import json
from pathlib import Path
from typing import Dict, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# 導入評估指標
from utils.metrics import (
    calculate_segmental_snr,
    calculate_fw_segsnr,
    calculate_wss,
    calculate_pesq,
    calculate_stoi
)


class BenchmarkComparison:
    """
    公平對標評估系統

    確保所有方法使用相同的評估流程:
    1. 移除前 skip_seconds 秒（默認 0.5s）
    2. 對齊音頻長度
    3. 使用統一的指標計算方法
    4. 生成統計報告
    """

    def __init__(
        self,
        skip_seconds: float = 0.5,
        clean_path: str = 'test_wav/wav/clean.wav',
        sample_rate: int = 16000
    ):
        self.skip_seconds = skip_seconds
        self.clean_path = clean_path
        self.sample_rate = sample_rate

        # 加載 clean 音頻（移除 0.5s）
        self.clean_audio, _ = self.load_and_trim_audio(clean_path)

    def load_and_trim_audio(self, filepath: str) -> Tuple[np.ndarray, int]:
        """
        加載音頻並移除前 skip_seconds 秒

        這是修復評估偏差的關鍵步驟！
        prepare_test_audio.py 在音頻前添加了 0.5 秒純噪聲段，
        如果不移除會導致 segSNR → -∞

        參數:
            filepath: 音頻文件路徑

        返回:
            audio: 裁剪後的音頻
            sr: 採樣率
        """
        audio, sr = librosa.load(filepath, sr=self.sample_rate)

        # 移除前 skip_seconds 秒
        skip_samples = int(self.skip_seconds * sr)
        trimmed_audio = audio[skip_samples:]

        return trimmed_audio, sr

    def evaluate_single_case(
        self,
        enhanced_path: str,
        noisy_path: str
    ) -> Dict[str, float]:
        """
        評估單個測試用例

        參數:
            enhanced_path: 降噪後音頻路徑
            noisy_path: 帶噪音頻路徑

        返回:
            metrics: 各項指標的字典
        """
        # 加載音頻（移除 0.5s）
        enhanced, _ = self.load_and_trim_audio(enhanced_path)
        noisy, _ = self.load_and_trim_audio(noisy_path)

        # 對齊長度（取最短）
        min_len = min(len(enhanced), len(self.clean_audio), len(noisy))
        enhanced = enhanced[:min_len]
        clean = self.clean_audio[:min_len]
        noisy = noisy[:min_len]

        # 計算所有指標
        metrics = {}

        try:
            # 1. segSNR (主要指標 - Loizou 2008)
            # 注意：calculate_segmental_snr(clean, enhanced, ...) 計算 SNR
            input_segsnr = calculate_segmental_snr(clean, noisy, self.sample_rate)
            output_segsnr = calculate_segmental_snr(clean, enhanced, self.sample_rate)
            metrics['input_segSNR'] = input_segsnr
            metrics['output_segSNR'] = output_segsnr
            metrics['segSNR_improvement'] = output_segsnr - input_segsnr

            # 2. fwSegSNR (頻率加權)
            metrics['fwSegSNR'] = calculate_fw_segsnr(enhanced, clean, self.sample_rate)

            # 3. WSS (加權頻譜斜率距離)
            metrics['WSS'] = calculate_wss(enhanced, clean, self.sample_rate)

            # 4. PESQ (參考指標)
            try:
                metrics['PESQ'] = calculate_pesq(clean, enhanced, self.sample_rate)
            except Exception as e:
                print(f"  Warning: PESQ calculation failed: {e}")
                metrics['PESQ'] = None

            # 5. STOI (參考指標)
            try:
                metrics['STOI'] = calculate_stoi(clean, enhanced, self.sample_rate)
            except Exception as e:
                print(f"  Warning: STOI calculation failed: {e}")
                metrics['STOI'] = None

        except Exception as e:
            print(f"  Error evaluating {enhanced_path}: {e}")
            return None

        return metrics

    def run_full_comparison(
        self,
        test_cases: Optional[list] = None,
        methods: Optional[list] = None
    ) -> Dict[str, Dict[str, float]]:
        """
        運行完整對比測試

        參數:
            test_cases: 測試用例列表 (如果為 None，自動生成所有組合)
            methods: 要評估的方法列表 (如果為 None，評估所有可用方法)

        返回:
            results: 完整結果字典 {method_testcase: metrics}
        """
        # 默認測試用例：3 noise × 4 SNR = 12 cases
        if test_cases is None:
            noise_types = ['babble', 'car', 'street']
            snr_levels = [0, 5, 10, 15]
            test_cases = [f"{noise}_{snr}dB" for noise in noise_types for snr in snr_levels]

        # 默認方法列表
        if methods is None:
            methods = ['Speex', 'RNNoise', 'V1', 'V2', 'V3', 'V3-2', 'V3-3', 'V3-4', 'V4']

        results = {}
        total_tests = len(test_cases) * len(methods)
        current_test = 0

        print(f"\n{'='*80}")
        print(f"開始公平對標評估 - 共 {total_tests} 個測試用例")
        print(f"{'='*80}\n")

        for test_id in test_cases:
            noisy_path = f"test_wav/wav/{test_id}.wav"

            if not os.path.exists(noisy_path):
                print(f"⚠️  Noisy file not found: {noisy_path}")
                continue

            print(f"\n測試用例: {test_id}")
            print(f"-" * 60)

            for method in methods:
                current_test += 1

                # 確定降噪音頻路徑
                if method == 'Speex':
                    enhanced_path = f"test_wav/benchmark_wav/speex/speexdsp_{test_id}.wav"
                elif method == 'RNNoise':
                    enhanced_path = f"test_wav/benchmark_wav/rnnoise/rnnoise_{test_id}.wav"
                else:
                    enhanced_path = f"denoised/{method}_{test_id}.wav"

                # 檢查文件是否存在
                if not os.path.exists(enhanced_path):
                    print(f"  [{current_test}/{total_tests}] ⚠️  {method:8s} - 文件不存在")
                    continue

                # 評估
                result_key = f"{method}_{test_id}"
                metrics = self.evaluate_single_case(enhanced_path, noisy_path)

                if metrics is not None:
                    results[result_key] = metrics
                    print(f"  [{current_test}/{total_tests}] ✓ {method:8s} - "
                          f"segSNR↑: {metrics['segSNR_improvement']:+6.2f} dB, "
                          f"WSS: {metrics['WSS']:5.1f}")
                else:
                    print(f"  [{current_test}/{total_tests}] ✗ {method:8s} - 評估失敗")

        print(f"\n{'='*80}")
        print(f"評估完成 - 成功 {len(results)}/{total_tests} 個測試")
        print(f"{'='*80}\n")

        return results

    def generate_summary_table(
        self,
        results: Dict[str, Dict[str, float]]
    ) -> Tuple[str, Dict[str, Dict[str, float]]]:
        """
        生成對比表格（Markdown + 統計數據）

        參數:
            results: 完整結果字典

        返回:
            markdown: Markdown 格式的表格
            summary: 統計摘要字典
        """
        # 按方法聚合
        methods_data = {}
        for key, metrics in results.items():
            method = key.split('_')[0]  # 提取方法名

            if method not in methods_data:
                methods_data[method] = {
                    'segSNR_improvement': [],
                    'fwSegSNR': [],
                    'WSS': [],
                    'PESQ': [],
                    'STOI': []
                }

            for metric_name, value in metrics.items():
                if metric_name in methods_data[method] and value is not None:
                    methods_data[method][metric_name].append(value)

        # 計算平均值和標準差
        summary = {}
        for method, data in methods_data.items():
            summary[method] = {}
            for metric_name, values in data.items():
                if len(values) > 0:
                    summary[method][f'{metric_name}_mean'] = np.mean(values)
                    summary[method][f'{metric_name}_std'] = np.std(values)
                else:
                    summary[method][f'{metric_name}_mean'] = None
                    summary[method][f'{metric_name}_std'] = None

        # 生成 Markdown 表格
        md_lines = []
        md_lines.append("# 算法性能對比（vs Speex & RNNoise）\n")
        md_lines.append(f"**評估條件**: 移除前 {self.skip_seconds}秒 append 噪聲段，所有測試用例平均值\n")
        md_lines.append("| 方法 | segSNR↑ (dB) | fwSegSNR (dB) | WSS | PESQ | STOI |")
        md_lines.append("|------|--------------|---------------|-----|------|------|")

        # 排序：Speex, RNNoise 在前，其他按方法名排序
        ordered = []
        if 'Speex' in summary:
            ordered.append('Speex')
        if 'RNNoise' in summary:
            ordered.append('RNNoise')

        other_methods = sorted([m for m in summary.keys() if m not in ['Speex', 'RNNoise']])
        ordered.extend(other_methods)

        for method in ordered:
            if method not in summary:
                continue

            data = summary[method]

            # 格式化數據
            segsnr_mean = data.get('segSNR_improvement_mean')
            fwsegsnr_mean = data.get('fwSegSNR_mean')
            wss_mean = data.get('WSS_mean')
            pesq_mean = data.get('PESQ_mean')
            stoi_mean = data.get('STOI_mean')

            segsnr_str = f"{segsnr_mean:+7.2f}" if segsnr_mean is not None else "N/A"
            fwsegsnr_str = f"{fwsegsnr_mean:7.2f}" if fwsegsnr_mean is not None else "N/A"
            wss_str = f"{wss_mean:5.1f}" if wss_mean is not None else "N/A"
            pesq_str = f"{pesq_mean:5.2f}" if pesq_mean is not None else "N/A"
            stoi_str = f"{stoi_mean:5.2f}" if stoi_mean is not None else "N/A"

            md_lines.append(
                f"| {method:8s} | "
                f"{segsnr_str:>12s} | "
                f"{fwsegsnr_str:>13s} | "
                f"{wss_str:>3s} | "
                f"{pesq_str:>4s} | "
                f"{stoi_str:>4s} |"
            )

        md_lines.append("\n**評估標準**:")
        md_lines.append("- **segSNR↑**: 5-18 dB 為優秀（主要指標）")
        md_lines.append("- **WSS**: < 60 為優秀，< 40 為卓越")
        md_lines.append("- **PESQ**: 1.0-4.5，> 2.5 為優秀（參考指標）")
        md_lines.append("- **STOI**: 0-1，> 0.85 為優秀（參考指標）")

        return "\n".join(md_lines), summary

    def save_results(
        self,
        results: Dict[str, Dict[str, float]],
        output_dir: str = 'results'
    ):
        """
        保存評估結果

        生成三個文件:
        1. benchmark_comparison.json - 詳細結果（JSON）
        2. benchmark_comparison.md - 對比表格（Markdown）
        3. benchmark_comparison.csv - Excel 可用（CSV）

        參數:
            results: 完整結果字典
            output_dir: 輸出目錄
        """
        os.makedirs(output_dir, exist_ok=True)

        # 1. JSON 詳細結果
        json_path = os.path.join(output_dir, 'benchmark_comparison.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✓ 詳細結果已保存: {json_path}")

        # 2. Markdown 表格
        markdown, summary = self.generate_summary_table(results)
        md_path = os.path.join(output_dir, 'benchmark_comparison.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        print(f"✓ 對比表格已保存: {md_path}")

        # 3. CSV 表格
        csv_path = os.path.join(output_dir, 'benchmark_comparison.csv')
        with open(csv_path, 'w', encoding='utf-8') as f:
            # Header
            f.write("Method,segSNR_improvement,fwSegSNR,WSS,PESQ,STOI\n")

            # Data rows
            for method, data in summary.items():
                segsnr = data.get('segSNR_improvement_mean', '')
                fwsegsnr = data.get('fwSegSNR_mean', '')
                wss = data.get('WSS_mean', '')
                pesq = data.get('PESQ_mean', '')
                stoi = data.get('STOI_mean', '')

                f.write(f"{method},{segsnr},{fwsegsnr},{wss},{pesq},{stoi}\n")

        print(f"✓ CSV 表格已保存: {csv_path}")

        # 顯示摘要表格
        print(f"\n{markdown}")


def main():
    """主函數"""
    import argparse

    parser = argparse.ArgumentParser(description='公平對標評估系統')
    parser.add_argument('--skip-seconds', type=float, default=0.5,
                       help='移除音頻前多少秒（默認 0.5）')
    parser.add_argument('--clean-path', type=str, default='test_wav/wav/clean.wav',
                       help='Clean 音頻路徑')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='結果輸出目錄')
    parser.add_argument('--methods', type=str, nargs='+',
                       default=['Speex', 'RNNoise', 'V1', 'V2', 'V3', 'V3-2', 'V3-3', 'V3-4', 'V4'],
                       help='要評估的方法列表')

    args = parser.parse_args()

    # 創建評估器
    comparator = BenchmarkComparison(
        skip_seconds=args.skip_seconds,
        clean_path=args.clean_path
    )

    # 運行評估
    results = comparator.run_full_comparison(methods=args.methods)

    # 保存結果
    comparator.save_results(results, output_dir=args.output_dir)


if __name__ == '__main__':
    main()
