"""
Performance Profiler - 性能分析工具

提供性能測量工具：
- 處理時間測量
- 實時率（RTF）計算
- CPU/內存監控（可選，需要 psutil）
- 內存追蹤（使用 tracemalloc）
"""

import time
import tracemalloc
from typing import Optional, Dict, Any, Callable
import numpy as np

# 可選依賴
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class PerformanceProfiler:
    """
    性能分析器

    用法:
        profiler = PerformanceProfiler()

        with profiler:
            # 處理音頻
            result = denoiser.process(audio)

        stats = profiler.get_stats()
        profiler.print_stats()
    """

    def __init__(self, enable_memory_trace: bool = False):
        """
        初始化性能分析器

        Args:
            enable_memory_trace: 是否啟用詳細內存追蹤（使用 tracemalloc）
        """
        self.enable_memory_trace = enable_memory_trace

        # 時間測量
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed_time: Optional[float] = None

        # CPU/內存（使用 psutil）
        self.process = None
        self.cpu_percent: Optional[float] = None
        self.memory_before: Optional[float] = None
        self.memory_after: Optional[float] = None
        self.memory_used: Optional[float] = None

        # 內存追蹤（使用 tracemalloc）
        self.memory_current: Optional[float] = None
        self.memory_peak: Optional[float] = None

        if PSUTIL_AVAILABLE:
            self.process = psutil.Process()

    def __enter__(self):
        """進入上下文管理器（開始測量）"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器（結束測量）"""
        self.stop()

    def start(self):
        """開始性能測量"""
        # 重置狀態
        self.start_time = None
        self.end_time = None
        self.elapsed_time = None
        self.cpu_percent = None
        self.memory_before = None
        self.memory_after = None
        self.memory_used = None
        self.memory_current = None
        self.memory_peak = None

        # 開始時間測量
        self.start_time = time.perf_counter()

        # CPU/內存測量（psutil）
        if PSUTIL_AVAILABLE and self.process:
            # 初始化 CPU 測量
            self.process.cpu_percent()
            # 記錄起始內存
            self.memory_before = self.process.memory_info().rss / 1024 / 1024  # MB

        # 內存追蹤（tracemalloc）
        if self.enable_memory_trace:
            tracemalloc.start()

    def stop(self):
        """結束性能測量"""
        # 結束時間測量
        self.end_time = time.perf_counter()

        if self.start_time is not None:
            self.elapsed_time = self.end_time - self.start_time

        # CPU/內存測量（psutil）
        if PSUTIL_AVAILABLE and self.process:
            self.cpu_percent = self.process.cpu_percent()
            self.memory_after = self.process.memory_info().rss / 1024 / 1024  # MB

            if self.memory_before is not None:
                self.memory_used = self.memory_after - self.memory_before

        # 內存追蹤（tracemalloc）
        if self.enable_memory_trace:
            current, peak = tracemalloc.get_traced_memory()
            self.memory_current = current / 1024 / 1024  # MB
            self.memory_peak = peak / 1024 / 1024  # MB
            tracemalloc.stop()

    def calculate_rtf(self, audio_duration: float) -> Optional[float]:
        """
        計算實時率（Real-Time Factor）

        Args:
            audio_duration: 音頻時長（秒）

        Returns:
            RTF = 處理時間 / 音頻時長
            < 1.0 表示可以實時處理
        """
        if self.elapsed_time is None or audio_duration <= 0:
            return None

        return self.elapsed_time / audio_duration

    def get_stats(self, audio_duration: Optional[float] = None) -> Dict[str, Any]:
        """
        獲取性能統計數據

        Args:
            audio_duration: 音頻時長（秒），用於計算 RTF

        Returns:
            性能統計字典
        """
        stats = {
            'elapsed_time_ms': self.elapsed_time * 1000 if self.elapsed_time else None,
            'elapsed_time_s': self.elapsed_time,
        }

        # RTF
        if audio_duration is not None:
            stats['audio_duration_s'] = audio_duration
            stats['rtf'] = self.calculate_rtf(audio_duration)

        # CPU
        if self.cpu_percent is not None:
            stats['cpu_percent'] = self.cpu_percent

        # 內存（psutil）
        if self.memory_used is not None:
            stats['memory_used_mb'] = self.memory_used
            stats['memory_before_mb'] = self.memory_before
            stats['memory_after_mb'] = self.memory_after

        # 內存（tracemalloc）
        if self.memory_peak is not None:
            stats['memory_current_mb'] = self.memory_current
            stats['memory_peak_mb'] = self.memory_peak

        return stats

    def print_stats(
        self,
        audio_duration: Optional[float] = None,
        algorithm_name: str = ""
    ):
        """
        打印性能統計

        Args:
            audio_duration: 音頻時長（秒）
            algorithm_name: 算法名稱
        """
        stats = self.get_stats(audio_duration)

        if algorithm_name:
            print(f"\n{'='*60}")
            print(f"Performance: {algorithm_name}")
            print(f"{'='*60}")

        # 時間
        if stats['elapsed_time_ms'] is not None:
            print(f"Processing time:    {stats['elapsed_time_ms']:8.2f} ms")

        # RTF
        if 'rtf' in stats and stats['rtf'] is not None:
            rtf = stats['rtf']
            print(f"Audio duration:     {stats['audio_duration_s']:8.2f} s")
            print(f"Real-time factor:   {rtf:8.4f}")

            # 評估實時性
            if rtf < 0.3:
                status = "優秀（可在低功耗設備運行）"
            elif rtf < 0.5:
                status = "良好（可在移動設備運行）"
            elif rtf < 1.0:
                status = "合格（實時處理）"
            else:
                status = "不合格（無法實時）"
            print(f"Status:             {status}")

        # CPU
        if 'cpu_percent' in stats and stats['cpu_percent'] is not None:
            print(f"CPU usage:          {stats['cpu_percent']:8.1f}%")
        else:
            if not PSUTIL_AVAILABLE:
                print(f"CPU usage:          N/A (install psutil)")

        # 內存
        if 'memory_used_mb' in stats and stats['memory_used_mb'] is not None:
            print(f"Memory used:        {stats['memory_used_mb']:8.2f} MB")

        if 'memory_peak_mb' in stats and stats['memory_peak_mb'] is not None:
            print(f"Memory peak:        {stats['memory_peak_mb']:8.2f} MB (tracemalloc)")

        print(f"{'='*60}\n")


def profile_function(
    func: Callable,
    *args,
    audio_duration: Optional[float] = None,
    name: str = "",
    enable_memory_trace: bool = False,
    **kwargs
) -> tuple:
    """
    測量函數性能

    Args:
        func: 要測量的函數
        *args: 函數參數
        audio_duration: 音頻時長（秒），用於計算 RTF
        name: 函數名稱（用於顯示）
        enable_memory_trace: 是否啟用內存追蹤
        **kwargs: 函數關鍵字參數

    Returns:
        (result, stats) - 函數返回值和性能統計
    """
    profiler = PerformanceProfiler(enable_memory_trace=enable_memory_trace)

    with profiler:
        result = func(*args, **kwargs)

    stats = profiler.get_stats(audio_duration)

    if name:
        profiler.print_stats(audio_duration, name)

    return result, stats


def measure_processing_time(func: Callable, num_runs: int = 1) -> Dict[str, float]:
    """
    測量函數處理時間（多次運行取平均）

    Args:
        func: 要測量的函數（無參數）
        num_runs: 運行次數

    Returns:
        時間統計（平均、最小、最大、標準差）
    """
    times = []

    for _ in range(num_runs):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    times = np.array(times)

    return {
        'mean_ms': float(np.mean(times) * 1000),
        'std_ms': float(np.std(times) * 1000),
        'min_ms': float(np.min(times) * 1000),
        'max_ms': float(np.max(times) * 1000),
        'num_runs': num_runs
    }


def estimate_flops(
    algorithm: str,
    fft_size: int = 512,
    num_freq_bins: Optional[int] = None
) -> int:
    """
    估算算法的理論 FLOPs

    Args:
        algorithm: 算法名稱（'V1', 'V2', 'V3', 'V4', 'RNNoise'）
        fft_size: FFT 大小
        num_freq_bins: 頻率點數（默認 fft_size//2 + 1）

    Returns:
        每幀的 FLOPs 估計值
    """
    if num_freq_bins is None:
        num_freq_bins = fft_size // 2 + 1

    # FFT/IFFT FLOPs: 5 * N * log2(N)
    fft_flops = 5 * fft_size * (fft_size.bit_length() - 1)

    if algorithm == 'V1':
        # FFT + IFFT + 減法 + 縮放
        return 2 * fft_flops + num_freq_bins * 3

    elif algorithm == 'V2':
        # FFT + IFFT + 平方 + 除法 + 增益計算
        return 2 * fft_flops + num_freq_bins * 5

    elif algorithm == 'V3':
        # FFT + IFFT + SNR計算 + SPP + MMSE + exp1()
        return 2 * fft_flops + num_freq_bins * 15

    elif algorithm == 'V4':
        # FFT + IFFT + IMCRA + OMLSA
        return 2 * fft_flops + num_freq_bins * 25

    elif algorithm == 'RNNoise':
        # 特徵提取 + GRU + FC
        # 對齊到 20ms 幀
        return 33000

    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")


def compare_algorithms_theoretical(algorithms: list) -> Dict[str, Dict[str, Any]]:
    """
    對比多個算法的理論性能

    Args:
        algorithms: 算法名稱列表

    Returns:
        各算法的理論性能數據
    """
    results = {}

    for algo in algorithms:
        flops = estimate_flops(algo)
        results[algo] = {
            'flops_per_frame': flops,
            'flops_per_frame_k': flops / 1000,
            'relative_complexity': flops / estimate_flops('V1')
        }

    return results


if __name__ == "__main__":
    print("Performance Profiler Module")
    print(f"psutil available: {PSUTIL_AVAILABLE}")
    print()

    # 測試性能分析器
    print("Testing PerformanceProfiler...")

    def dummy_processing():
        """模擬音頻處理"""
        time.sleep(0.1)  # 模擬 100ms 處理時間
        # 模擬一些內存分配
        data = np.random.randn(1000000)
        return np.mean(data)

    profiler = PerformanceProfiler(enable_memory_trace=True)

    with profiler:
        result = dummy_processing()

    # 假設處理 2 秒音頻
    profiler.print_stats(audio_duration=2.0, algorithm_name="Dummy Test")

    # 測試理論 FLOPs 計算
    print("\nTheoretical FLOPs Comparison:")
    print("="*60)

    algos = ['V1', 'V2', 'V3', 'V4', 'RNNoise']
    flops_comparison = compare_algorithms_theoretical(algos)

    for algo, data in flops_comparison.items():
        print(f"{algo:10s}: {data['flops_per_frame_k']:6.1f}K FLOPs  "
              f"({data['relative_complexity']:.2f}x relative to V1)")

    print("="*60)
