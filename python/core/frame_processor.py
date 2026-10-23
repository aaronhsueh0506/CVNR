"""Framing, windowing and FFT."""

import math
import numpy as np
from typing import Tuple, Optional

from .signal_grid import resolve_signal_grid, validate_signal_grid


class FrameProcessor:
    """Frames a signal and computes windowed rFFT spectra.

    frame_size/frame_shift/fft_size must be given together; if all are omitted the project
    default grid for sample_rate is used. window_type: 'hanning', 'hamming' or 'blackman'.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        window_type: str = 'hanning'
    ):
        if frame_size is None and frame_shift is None and fft_size is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError(
                "frame_size, frame_shift, and fft_size must be set together"
            )

        self.sample_rate = sample_rate
        self.fft_size = fft_size

        self.frame_size = frame_size
        self.frame_shift = frame_shift

        validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)

        self.window = self._create_window(window_type, self.frame_size)

        self.buffer = np.zeros(self.frame_size)

    def _create_window(self, window_type: str, size: int) -> np.ndarray:
        """sqrt of the periodic window (exact COLA at 50% overlap; numpy windows are symmetric)."""
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
        """Windows and transforms one frame (frame_size,).

        Returns (magnitude, phase, spectrum), each (fft_size//2 + 1,).
        """
        windowed = frame * self.window

        spectrum = np.fft.rfft(windowed, n=self.fft_size)

        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        return magnitude, phase, spectrum

    def process_signal(self, signal: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Processes a whole signal (n_samples,).

        Returns (magnitudes, phases, spectra), each (n_frames, fft_size//2 + 1).
        """
        frames = self._split_frames(signal)
        n_frames = frames.shape[0]
        n_freqs = self.fft_size // 2 + 1

        magnitudes = np.zeros((n_frames, n_freqs))
        phases = np.zeros((n_frames, n_freqs))
        spectra = np.zeros((n_frames, n_freqs), dtype=complex)

        for i, frame in enumerate(frames):
            mag, phase, spec = self.process_frame(frame)
            magnitudes[i] = mag
            phases[i] = phase
            spectra[i] = spec

        return magnitudes, phases, spectra

    def _split_frames(self, signal: np.ndarray) -> np.ndarray:
        """Splits signal into overlapping frames (n_frames, frame_size); the last is zero-padded."""
        n_samples = len(signal)

        # ceil keeps the trailing partial frame: ceil((N - frame_size) / frame_shift) + 1.
        n_frames = max(1, math.ceil(max(n_samples - self.frame_size, 0) / self.frame_shift) + 1)

        frames = np.zeros((n_frames, self.frame_size))

        for i in range(n_frames):
            start = i * self.frame_shift
            end = start + self.frame_size

            if end <= n_samples:
                frames[i] = signal[start:end]
            else:
                available = n_samples - start
                frames[i, :available] = signal[start:]

        return frames

    def get_frame_times(self, n_samples: int) -> np.ndarray:
        """Frame start times in seconds (n_frames,)."""
        n_frames = max(1, math.ceil(max(n_samples - self.frame_size, 0) / self.frame_shift) + 1)
        times = np.arange(n_frames) * self.frame_shift / self.sample_rate
        return times

    def __repr__(self):
        return (f"FrameProcessor(sample_rate={self.sample_rate}, "
                f"frame_size={self.frame_size}, "
                f"frame_shift={self.frame_shift}, "
                f"fft_size={self.fft_size})")
