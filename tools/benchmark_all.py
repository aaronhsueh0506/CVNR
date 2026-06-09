"""
Benchmark All Denoisers - 完整性能評估

對所有降噪算法（V1-V4）進行綜合評估：
- 性能測試：處理時間、CPU、內存、RTF
- 音質測試：SNR、PESQ、STOI、LSD（可選）

Usage:
    python benchmark_all.py --quick              # 快速測試（只測 SNR + 性能）
    python benchmark_all.py --full               # 完整測試（包含 PESQ/STOI）
    python benchmark_all.py --noise-types white  # 只測試特定噪聲類型
"""

import sys
import os
import argparse
import json
from typing import Dict, List, Any
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.test_data_generator import TestDataGenerator, generate_sample_speech
from utils.audio_io import add_noise
from utils.performance_profiler import PerformanceProfiler
from utils.metrics import evaluate_all_metrics
from denoisers import (
    SpectralSubtractionDenoiser,
    WienerDenoiser,
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser
)
# V4 IMCRA-OMLSA archived, V3-4 removed (not better than V3-2)


class BenchmarkRunner:
    """完整的基準測試運行器"""

    def __init__(
        self,
        quick_mode: bool = False,
        output_file: str = "benchmark_results.json"
    ):
        """
        初始化基準測試運行器

        Args:
            quick_mode: 快速模式（跳過 PESQ/STOI）
            output_file: 輸出文件路徑
        """
        self.quick_mode = quick_mode
        self.output_file = output_file
        self.results: Dict[str, Any] = {}

        # 測試參數
        self.sample_rate = 16000
        self.duration = 2.0  # 2 秒測試音頻

        # 創建測試數據生成器
        self.data_generator = TestDataGenerator(
            sample_rate=self.sample_rate
        )

    def create_denoisers(self) -> Dict[str, Any]:
        """創建所有降噪器（v4.0: V4 merged to V3-2, V3-4 removed）"""
        return {
            'V1': SpectralSubtractionDenoiser(sample_rate=self.sample_rate),
            'V2': WienerDenoiser(sample_rate=self.sample_rate, enable_noise_tracking=True),
            'V3': SppMmseDenoiser(sample_rate=self.sample_rate),
            'V3-2': MmseLsaDenoiser(sample_rate=self.sample_rate),
            'V3-3': PmmseDenoiser(sample_rate=self.sample_rate),
            # V3-4 removed (test results not better than V3-2)
            # V4 merged to V3-2 (same implementation with optimized parameters)
        }

    def generate_test_cases(
        self,
        noise_types: List[str],
        snr_levels: List[float]
    ) -> List[Dict[str, Any]]:
        """
        生成測試用例

        Args:
            noise_types: 噪聲類型列表
            snr_levels: SNR 等級列表

        Returns:
            測試用例列表
        """
        test_cases = []

        for noise_type in noise_types:
            for target_snr in snr_levels:
                test_cases.append({
                    'noise_type': noise_type,
                    'target_snr_db': target_snr,
                    'id': f"{noise_type}_snr{int(target_snr)}"
                })

        return test_cases

    def run_single_test(
        self,
        denoiser,
        clean_audio: np.ndarray,
        noisy_audio: np.ndarray,
        test_case: Dict[str, Any],
        denoiser_name: str
    ) -> Dict[str, Any]:
        """
        運行單個測試

        Args:
            denoiser: 降噪器實例
            clean_audio: 乾淨音頻
            noisy_audio: 含噪音頻
            test_case: 測試用例信息
            denoiser_name: 降噪器名稱

        Returns:
            測試結果
        """
        # 性能測試
        profiler = PerformanceProfiler(enable_memory_trace=True)

        with profiler:
            enhanced_audio = denoiser.denoise(noisy_audio)

        # 獲取性能統計
        audio_duration = len(noisy_audio) / self.sample_rate
        perf_stats = profiler.get_stats(audio_duration)

        # 音質測試
        if self.quick_mode:
            # 快速模式：只測 SNR
            from utils.metrics import calculate_snr_improvement

            input_snr, output_snr, snr_improvement = calculate_snr_improvement(
                noisy_audio, clean_audio, enhanced_audio
            )

            quality_stats = {
                'input_snr_db': input_snr,
                'output_snr_db': output_snr,
                'snr_improvement_db': snr_improvement
            }
        else:
            # 完整模式：測試所有指標
            quality_stats = evaluate_all_metrics(
                noisy_audio, clean_audio, enhanced_audio, self.sample_rate
            )

        # 合併結果
        result = {
            'test_case': test_case,
            'denoiser': denoiser_name,
            'performance': perf_stats,
            'quality': quality_stats
        }

        return result

    def run_benchmark(
        self,
        noise_types: List[str] = None,
        snr_levels: List[float] = None
    ) -> Dict[str, Any]:
        """
        運行完整基準測試

        Args:
            noise_types: 噪聲類型列表（默認：white, babble, car）
            snr_levels: SNR 等級列表（默認：5dB）

        Returns:
            完整測試結果
        """
        # 默認測試參數
        if noise_types is None:
            noise_types = ['white', 'babble', 'car']

        if snr_levels is None:
            if self.quick_mode:
                snr_levels = [5.0]  # 快速模式只測一個 SNR
            else:
                snr_levels = [0.0, 5.0, 10.0]  # 完整模式測三個 SNR

        # 生成測試用例
        test_cases = self.generate_test_cases(noise_types, snr_levels)

        print("="*70)
        print("Speech Denoising Benchmark")
        print("="*70)
        print(f"Mode:         {'Quick (SNR only)' if self.quick_mode else 'Full (all metrics)'}")
        print(f"Test cases:   {len(test_cases)} ({len(noise_types)} noise types × {len(snr_levels)} SNR levels)")
        print(f"Duration:     {self.duration} seconds per test")
        print(f"Denoisers:    V1, V2, V3, V4")
        print("="*70)

        # 創建降噪器
        denoisers = self.create_denoisers()

        # 生成乾淨語音信號（所有測試共用）
        clean_audio = generate_sample_speech(
            duration=self.duration,
            sample_rate=self.sample_rate
        )

        # 存儲所有結果
        all_results = {}

        # 遍歷所有測試用例
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[Test {i}/{len(test_cases)}] {test_case['id']}")
            print("-"*70)

            # 生成噪聲
            if test_case['noise_type'] == 'white':
                noise = self.data_generator.generate_white_noise(self.duration)
            elif test_case['noise_type'] == 'pink':
                noise = self.data_generator.generate_pink_noise(self.duration)
            elif test_case['noise_type'] == 'babble':
                noise = self.data_generator.generate_babble_noise(self.duration)
            elif test_case['noise_type'] == 'car':
                # 使用低頻噪聲模擬車內噪聲
                noise = self.data_generator.generate_pink_noise(self.duration) * 0.7
            else:
                noise = self.data_generator.generate_white_noise(self.duration)

            # 添加噪聲到乾淨語音
            noisy_audio = add_noise(
                clean_audio,
                noise,
                target_snr_db=test_case['target_snr_db']
            )

            # 測試每個降噪器
            for denoiser_name, denoiser in denoisers.items():
                print(f"  Testing {denoiser_name}...", end=' ', flush=True)

                try:
                    result = self.run_single_test(
                        denoiser, clean_audio, noisy_audio,
                        test_case, denoiser_name
                    )

                    # 存儲結果
                    key = f"{denoiser_name}_{test_case['id']}"
                    all_results[key] = result

                    # 打印簡要結果
                    rtf = result['performance']['rtf']
                    snr_imp = result['quality']['snr_improvement_db']
                    print(f"RTF: {rtf:.4f}, SNR↑: {snr_imp:+.1f}dB")

                except Exception as e:
                    print(f"FAILED: {e}")
                    all_results[f"{denoiser_name}_{test_case['id']}"] = {
                        'error': str(e)
                    }

        # 保存結果
        self.results = {
            'metadata': {
                'mode': 'quick' if self.quick_mode else 'full',
                'sample_rate': self.sample_rate,
                'duration': self.duration,
                'num_tests': len(test_cases),
                'denoisers': list(denoisers.keys()),
                'noise_types': noise_types,
                'snr_levels': snr_levels
            },
            'results': all_results
        }

        return self.results

    def save_results(self):
        """保存結果到 JSON 文件"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Results saved to: {self.output_file}")

    def generate_summary_table(self) -> str:
        """生成摘要表格（Markdown 格式）"""
        if not self.results:
            return "No results available"

        # 提取數據
        denoisers = self.results['metadata']['denoisers']
        noise_types = self.results['metadata']['noise_types']

        # 計算各算法的平均性能
        summary = {}
        for denoiser in denoisers:
            rtf_list = []
            snr_imp_list = []
            pesq_list = []
            stoi_list = []

            for key, result in self.results['results'].items():
                if 'error' in result or not key.startswith(denoiser):
                    continue

                rtf_list.append(result['performance']['rtf'])
                snr_imp_list.append(result['quality']['snr_improvement_db'])

                if not self.quick_mode:
                    if result['quality']['pesq'] is not None:
                        pesq_list.append(result['quality']['pesq'])
                    if result['quality']['stoi'] is not None:
                        stoi_list.append(result['quality']['stoi'])

            summary[denoiser] = {
                'rtf_mean': np.mean(rtf_list) if rtf_list else None,
                'snr_imp_mean': np.mean(snr_imp_list) if snr_imp_list else None,
                'pesq_mean': np.mean(pesq_list) if pesq_list else None,
                'stoi_mean': np.mean(stoi_list) if stoi_list else None
            }

        # 生成表格
        lines = []
        lines.append("\n## Benchmark Summary\n")

        if self.quick_mode:
            lines.append("| Algorithm | RTF | SNR Improvement (dB) | Real-time |")
            lines.append("|-----------|-----|---------------------|-----------|")

            for denoiser in denoisers:
                data = summary[denoiser]
                rtf = data['rtf_mean']
                snr = data['snr_imp_mean']
                realtime = "✓" if rtf and rtf < 1.0 else "✗"

                rtf_str = f"{rtf:.4f}" if rtf is not None else "N/A"
                snr_str = f"{snr:+6.2f}" if snr is not None else "N/A"

                lines.append(
                    f"| {denoiser:9s} | {rtf_str:6s} | {snr_str:6s} | {realtime:9s} |"
                )
        else:
            lines.append("| Algorithm | RTF | SNR↑ (dB) | PESQ | STOI | Real-time |")
            lines.append("|-----------|-----|-----------|------|------|-----------|")

            for denoiser in denoisers:
                data = summary[denoiser]
                rtf = data['rtf_mean']
                snr = data['snr_imp_mean']
                pesq = data['pesq_mean']
                stoi = data['stoi_mean']
                realtime = "✓" if rtf and rtf < 1.0 else "✗"

                pesq_str = f"{pesq:.2f}" if pesq else "N/A"
                stoi_str = f"{stoi:.2f}" if stoi else "N/A"

                lines.append(
                    f"| {denoiser:9s} | {rtf:.4f} | {snr:+6.2f} | "
                    f"{pesq_str:4s} | {stoi_str:4s} | {realtime:9s} |"
                )

        lines.append("\n**Tested on:**")
        lines.append(f"- Noise types: {', '.join(noise_types)}")
        lines.append(f"- SNR levels: {', '.join(map(str, self.results['metadata']['snr_levels']))} dB")
        lines.append(f"- Audio duration: {self.duration} seconds\n")

        return "\n".join(lines)

    def print_summary(self):
        """打印測試摘要"""
        print("\n" + "="*70)
        print("Benchmark Complete!")
        print("="*70)

        # 打印表格
        print(self.generate_summary_table())

        # 保存表格到文件
        summary_file = self.output_file.replace('.json', '_summary.md')
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(self.generate_summary_table())

        print(f"✓ Summary saved to: {summary_file}")
        print("="*70)


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark all speech denoising algorithms'
    )

    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick mode (SNR + performance only, skip PESQ/STOI)'
    )

    parser.add_argument(
        '--full',
        action='store_true',
        help='Full mode (all metrics including PESQ/STOI)'
    )

    parser.add_argument(
        '--noise-types',
        nargs='+',
        default=['white', 'babble', 'car'],
        help='Noise types to test (default: white babble car)'
    )

    parser.add_argument(
        '--snr-levels',
        nargs='+',
        type=float,
        default=None,
        help='SNR levels to test (default: 5.0 for quick, 0 5 10 for full)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='benchmark_results.json',
        help='Output JSON file (default: benchmark_results.json)'
    )

    args = parser.parse_args()

    # 確定模式
    if args.full:
        quick_mode = False
    else:
        quick_mode = True  # 默認快速模式

    # 創建基準測試運行器
    runner = BenchmarkRunner(
        quick_mode=quick_mode,
        output_file=args.output
    )

    # 運行基準測試
    runner.run_benchmark(
        noise_types=args.noise_types,
        snr_levels=args.snr_levels
    )

    # 保存結果
    runner.save_results()

    # 打印摘要
    runner.print_summary()


if __name__ == "__main__":
    main()
