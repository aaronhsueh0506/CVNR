"""
Frame Processor - 分幀、加窗、FFT
"""

import math
import numpy as np
from typing import Tuple, Optional

from .signal_grid import validate_signal_grid


class FrameProcessor:
    """
    處理音頻信號的分幀、加窗和 FFT。

    參數:
        sample_rate: 採樣率 (Hz)
        frame_size: 幀長 (samples, 512 @ 16kHz)
        frame_shift: 幀移 (samples, 256 @ 16kHz)
        fft_size: FFT 點數
        window_type: 窗函數類型 ('hanning', 'hamming', 'blackman')
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: int = 512,
        frame_shift: int = 256,
        fft_size: int = 512,
        window_type: str = 'hanning'
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size

        # 幀長和幀移（已是樣本數）
        self.frame_size = frame_size
        self.frame_shift = frame_shift

        validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)

        # 創建窗函數
        self.window = self._create_window(window_type, self.frame_size)

        # 緩衝區（用於實時處理）
        self.buffer = np.zeros(self.frame_size)

    def _create_window(self, window_type: str, size: int) -> np.ndarray:
        """
        創建 sqrt(periodic window) 以滿足精確 COLA。

        numpy 的 hanning/hamming/blackman 為 symmetric（對稱），
        對 50% overlap 不滿足精確 COLA，需用 periodic 版本
        （scipy.signal.windows.*(N, sym=False)）。
        """
        try:
            from scipy.signal.windows import hann, hamming, blackman
            if window_type == 'hanning':
                return np.sqrt(hann(size, sym=False))
            elif window_type == 'hamming':
                return np.sqrt(hamming(size, sym=False))
            elif window_type == 'blackman':
                return np.sqrt(blackman(size, sym=False))
            else:
                raise ValueError(f"Unknown window type: {window_type}")
        except ImportError:
            import warnings
            warnings.warn(
                "scipy not available, falling back to symmetric window. "
                "OLA reconstruction may not be exact COLA.",
                RuntimeWarning
            )
            if window_type == 'hanning':
                return np.sqrt(np.hanning(size))
            elif window_type == 'hamming':
                return np.sqrt(np.hamming(size))
            elif window_type == 'blackman':
                return np.sqrt(np.blackman(size))
            else:
                raise ValueError(f"Unknown window type: {window_type}")

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        處理單個幀：加窗 + FFT

        參數:
            frame: 時域音頻幀 (frame_size,)

        返回:
            magnitude: 幅度譜 (fft_size//2 + 1,)
            phase: 相位譜 (fft_size//2 + 1,)
            spectrum: 複數頻譜 (fft_size//2 + 1,)
        """
        # 加窗
        windowed = frame * self.window

        # FFT
        spectrum = np.fft.rfft(windowed, n=self.fft_size)

        # 分離幅度和相位
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        return magnitude, phase, spectrum

    def process_signal(self, signal: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        處理整個信號

        參數:
            signal: 輸入音頻信號 (n_samples,)

        返回:
            magnitudes: 幅度譜 (n_frames, fft_size//2 + 1)
            phases: 相位譜 (n_frames, fft_size//2 + 1)
            spectra: 複數頻譜 (n_frames, fft_size//2 + 1)
        """
        # 分幀
        frames = self._split_frames(signal)
        n_frames = frames.shape[0]
        n_freqs = self.fft_size // 2 + 1

        # 初始化輸出
        magnitudes = np.zeros((n_frames, n_freqs))
        phases = np.zeros((n_frames, n_freqs))
        spectra = np.zeros((n_frames, n_freqs), dtype=complex)

        # 處理每一幀
        for i, frame in enumerate(frames):
            mag, phase, spec = self.process_frame(frame)
            magnitudes[i] = mag
            phases[i] = phase
            spectra[i] = spec

        return magnitudes, phases, spectra

    def _split_frames(self, signal: np.ndarray) -> np.ndarray:
        """
        將信號分成重疊的幀

        參數:
            signal: 輸入信號 (n_samples,)

        返回:
            frames: 幀數組 (n_frames, frame_size)
        """
        n_samples = len(signal)

        # ceil ensures the last partial frame (tail) is included, not dropped.
        # e.g. 16000 samples, frame_size=512, frame_shift=256 → ceil((16000-512)/256)+1 = 62
        # vs floor → 61 (drops last 128 samples).
        n_frames = max(1, math.ceil(max(n_samples - self.frame_size, 0) / self.frame_shift) + 1)

        # 創建幀數組
        frames = np.zeros((n_frames, self.frame_size))

        for i in range(n_frames):
            start = i * self.frame_shift
            end = start + self.frame_size

            if end <= n_samples:
                frames[i] = signal[start:end]
            else:
                # 最後一幀可能不足，進行零填充
                available = n_samples - start
                frames[i, :available] = signal[start:]

        return frames

    def get_frame_times(self, n_samples: int) -> np.ndarray:
        """
        獲取每一幀的時間戳（秒）

        參數:
            n_samples: 信號總樣本數

        返回:
            times: 時間戳數組 (n_frames,)
        """
        n_frames = max(1, math.ceil(max(n_samples - self.frame_size, 0) / self.frame_shift) + 1)
        times = np.arange(n_frames) * self.frame_shift / self.sample_rate
        return times

    def __repr__(self):
        return (f"FrameProcessor(sample_rate={self.sample_rate}, "
                f"frame_size={self.frame_size}, "
                f"frame_shift={self.frame_shift}, "
                f"fft_size={self.fft_size})")
