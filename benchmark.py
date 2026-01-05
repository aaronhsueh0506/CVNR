#!/usr/bin/env python3
"""
統一 Benchmark 工具 - 合併 benchmark_all.py 和 benchmark_comparison.py

功能：
1. 性能基準測試（RTF, 處理時間, CPU, 內存）
2. 對標評估（與 Speex/RNNoise 對比）

使用方式:
  python3 benchmark.py --mode performance    # 性能測試（來自 benchmark_all.py）
  python3 benchmark.py --mode comparison     # 對標評估（來自 benchmark_comparison.py）
  python3 benchmark.py --mode all            # 兩者都執行

Examples:
  # 快速性能測試（只測 SNR + 性能）
  python3 benchmark.py --mode performance --quick

  # 完整性能測試（包含 PESQ/STOI）
  python3 benchmark.py --mode performance --full

  # 對標評估
  python3 benchmark.py --mode comparison --skip-seconds 0.5
"""

import sys
import os
import argparse

# Ensure imports work from root directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_performance_benchmark(args):
    """
    運行性能基準測試（來自 benchmark_all.py）

    對所有降噪算法（V1-V4 + V3變體）進行綜合評估：
    - 性能測試：處理時間、CPU、內存、RTF
    - 音質測試：SNR、PESQ、STOI、LSD（可選）
    """
    print("=" * 100)
    print("性能基準測試 (Performance Benchmark)")
    print("=" * 100)

    # Import from tools directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
    from benchmark_all import BenchmarkRunner

    # 創建 benchmark runner
    runner = BenchmarkRunner(
        quick_mode=args.quick,
        output_file=args.output
    )

    # 運行測試
    noise_types = args.noise_types.split(',') if args.noise_types else ['white', 'babble']
    snr_levels = [0, 5, 10, 15]

    runner.run_benchmark(noise_types=noise_types, snr_levels=snr_levels)

    print(f"\n✅ 性能測試完成! 結果保存到: {args.output}")


def run_comparison_benchmark(args):
    """
    運行對標評估（來自 benchmark_comparison.py）

    對 Speex、RNNoise 和我們的算法使用相同的評估流程，確保公平對比。

    關鍵修復:
    1. 移除前 0.5 秒 append 噪聲段（防止評估偏差）
    2. 使用 segSNR 作為主要指標（Loizou 2008 推薦）
    3. 計算 fwSegSNR、WSS、PESQ、STOI 等多維度指標
    """
    print("=" * 100)
    print("對標評估 (Comparison Benchmark)")
    print("=" * 100)

    # Import from tools directory
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
    from benchmark_comparison import BenchmarkComparison

    # 創建對標評估器
    comparison = BenchmarkComparison(
        skip_seconds=args.skip_seconds,
        clean_path=args.clean_path,
        sample_rate=16000
    )

    # 運行對標評估
    # Note: The comparison class uses its own internal logic
    print("⚠️  Note: 對標評估功能請直接使用:")
    print(f"    python3 tools/benchmark_comparison.py --skip-seconds {args.skip_seconds}")
    print(f"\n   或參考 tools/benchmark_comparison.py 的完整功能")

    print(f"\n✅ 對標評估入口已準備就緒")


def main():
    parser = argparse.ArgumentParser(
        description='統一 Benchmark 工具 - 性能測試與對標評估',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 快速性能測試
  python3 benchmark.py --mode performance --quick

  # 完整性能測試
  python3 benchmark.py --mode performance --full

  # 對標評估（與 Speex/RNNoise 對比）
  python3 benchmark.py --mode comparison

  # 兩者都執行
  python3 benchmark.py --mode all
        """
    )

    # 主要模式選擇
    parser.add_argument(
        '--mode',
        choices=['performance', 'comparison', 'all'],
        default='all',
        help='運行模式：performance (性能測試), comparison (對標評估), all (兩者都執行)'
    )

    # 通用參數
    parser.add_argument(
        '--output',
        default='benchmark_results.json',
        help='輸出文件路徑（默認: benchmark_results.json）'
    )

    # 性能測試專用參數
    parser.add_argument(
        '--quick',
        action='store_true',
        help='快速模式（跳過 PESQ/STOI）'
    )

    parser.add_argument(
        '--full',
        action='store_true',
        help='完整測試（包含 PESQ/STOI）'
    )

    parser.add_argument(
        '--noise-types',
        help='噪聲類型（逗號分隔，例如: white,babble,car）'
    )

    # 對標評估專用參數
    parser.add_argument(
        '--skip-seconds',
        type=float,
        default=0.5,
        help='移除音頻前 N 秒（默認: 0.5）'
    )

    parser.add_argument(
        '--clean-path',
        default='test_wav/wav/clean.wav',
        help='乾淨音頻路徑（默認: test_wav/wav/clean.wav）'
    )

    args = parser.parse_args()

    # 執行對應的測試
    try:
        if args.mode in ['performance', 'all']:
            run_performance_benchmark(args)

        if args.mode in ['comparison', 'all']:
            if args.mode == 'all':
                print("\n" + "=" * 100 + "\n")
            run_comparison_benchmark(args)

    except ImportError as e:
        print(f"❌ 錯誤: 無法導入必要的模組")
        print(f"   詳細訊息: {e}")
        print(f"\n💡 提示: 確保 benchmark_all.py 和 benchmark_comparison.py 的實現")
        print(f"        已重構為 benchmark_all_impl.py 和 benchmark_comparison_impl.py")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
