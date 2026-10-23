"""Spectrum reconstruction: IFFT, synthesis window and overlap-add.

With a sqrt-periodic window pair and 50% overlap the squared windows sum to a constant (COLA),
so the output is not normalized.
"""

import numpy as np
from typing import Optional


class Reconstructor:
    """Reconstructs time-domain frames and signals from spectra.

    fft_size: FFT length; frame_shift: hop in samples; window: optional synthesis window.
    """

    def __init__(
        self,
        fft_size: int = 512,
        frame_shift: int = 256,
        window: Optional[np.ndarray] = None
    ):
        self.fft_size = fft_size
        self.frame_shift = frame_shift
        self.window = window

    def reconstruct_frame(
        self,
        magnitude: np.ndarray,
        phase: np.ndarray
    ) -> np.ndarray:
        """Frame from magnitude and phase (fft_size//2 + 1,), truncated to the window length."""
        spectrum = magnitude * np.exp(1j * phase)

        # IFFT, then keep the first len(window) samples.
        frame_full = np.fft.irfft(spectrum, n=self.fft_size)

        if self.window is not None:
            frame = frame_full[:len(self.window)]
        else:
            frame = frame_full

        return frame

    def reconstruct_from_spectrum(
        self,
        spectrum: np.ndarray
    ) -> np.ndarray:
        """Frame from a complex spectrum (fft_size//2 + 1,), truncated to the window length."""
        # IFFT, then keep the first len(window) samples.
        frame_full = np.fft.irfft(spectrum, n=self.fft_size)

        if self.window is not None:
            frame = frame_full[:len(self.window)]
        else:
            frame = frame_full

        return frame

    def overlap_add(
        self,
        frames: np.ndarray,
        original_length: Optional[int] = None
    ) -> np.ndarray:
        """Overlap-adds frames (n_frames, frame_size) after the synthesis window; crops to original_length if given."""
        n_frames, frame_size = frames.shape

        output_length = (n_frames - 1) * self.frame_shift + frame_size

        output = np.zeros(output_length)

        # sqrt(Hann) x sqrt(Hann) at 50% overlap satisfies COLA; other hops would need explicit normalization.
        assert self.frame_shift * 2 == frame_size, (
            f"COLA property requires 50% overlap; got frame_shift={self.frame_shift}, "
            f"frame_size={frame_size}"
        )
        for i, frame in enumerate(frames):
            start = i * self.frame_shift
            end = start + frame_size

            if self.window is not None:
                windowed_frame = frame * self.window
            else:
                windowed_frame = frame

            output[start:end] += windowed_frame

        if original_length is not None:
            output = output[:original_length]

        return output

    def reconstruct_signal(
        self,
        magnitudes: np.ndarray,
        phases: np.ndarray,
        original_length: Optional[int] = None
    ) -> np.ndarray:
        """Signal from magnitude and phase spectra (n_frames, n_freqs); crops to original_length if given."""
        n_frames = magnitudes.shape[0]

        # Frame length: the window length if a window is set, else fft_size.
        frame_length = len(self.window) if self.window is not None else self.fft_size

        frames = np.zeros((n_frames, frame_length))
        for i in range(n_frames):
            frames[i] = self.reconstruct_frame(magnitudes[i], phases[i])

        signal = self.overlap_add(frames, original_length)

        return signal

    def __repr__(self):
        return (f"Reconstructor(fft_size={self.fft_size}, "
                f"frame_shift={self.frame_shift})")
