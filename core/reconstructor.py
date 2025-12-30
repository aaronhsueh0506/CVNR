"""
Reconstructor - 頻譜重建、IFFT、Overlap-Add
"""

import numpy as np
from typing import Optional


class Reconstructor:
    """
    從頻譜重建時域信號。

    參數:
        fft_size: FFT 點數
        frame_shift: 幀移（樣本數）
        window: 窗函數（可選，用於 OLA）
    """

    def __init__(
        self,
        fft_size: int = 512,
        frame_shift: int = 160,
        window: Optional[np.ndarray] = None
    ):
        self.fft_size = fft_size
        self.frame_shift = frame_shift
        self.window = window

    def apply_gain(
        self,
        spectrum: np.ndarray,
        gain: np.ndarray
    ) -> np.ndarray:
        """
        對頻譜應用增益

        參數:
            spectrum: 複數頻譜 (n_freqs,) 或 (n_frames, n_freqs)
            gain: 增益 (n_freqs,) 或 (n_frames, n_freqs)

        返回:
            enhanced_spectrum: 增強後的複數頻譜
        """
        return spectrum * gain

    def reconstruct_frame(
        self,
        magnitude: np.ndarray,
        phase: np.ndarray
    ) -> np.ndarray:
        """
        從幅度和相位重建時域幀

        參數:
            magnitude: 幅度譜 (fft_size//2 + 1,)
            phase: 相位譜 (fft_size//2 + 1,)

        返回:
            frame: 時域信號 (fft_size,)
        """
        # 重建複數頻譜
        spectrum = magnitude * np.exp(1j * phase)

        # IFFT
        frame = np.fft.irfft(spectrum, n=self.fft_size)

        return frame

    def reconstruct_from_spectrum(
        self,
        spectrum: np.ndarray
    ) -> np.ndarray:
        """
        從複數頻譜重建時域幀

        參數:
            spectrum: 複數頻譜 (fft_size//2 + 1,)

        返回:
            frame: 時域信號 (fft_size,)
        """
        # IFFT
        frame = np.fft.irfft(spectrum, n=self.fft_size)

        return frame

    def overlap_add(
        self,
        frames: np.ndarray,
        original_length: Optional[int] = None
    ) -> np.ndarray:
        """
        使用 Overlap-Add 方法重建完整信號

        參數:
            frames: 時域幀 (n_frames, frame_size)
            original_length: 原始信號長度（可選，用於裁剪）

        返回:
            signal: 重建的時域信號
        """
        n_frames, frame_size = frames.shape

        # 計算輸出長度
        output_length = (n_frames - 1) * self.frame_shift + frame_size

        # 初始化輸出
        output = np.zeros(output_length)

        # Overlap-Add
        # 注意：這裡不應該再次加窗，因為分析階段已經加過窗了
        # 直接疊加 IFFT 結果，然後用窗函數平方和歸一化
        for i, frame in enumerate(frames):
            start = i * self.frame_shift
            end = start + frame_size
            output[start:end] += frame

        # 窗函數能量補償（Overlap-Add 方法需要）
        # 注意：對於 COLA（Constant Overlap-Add）兼容的窗函數（如 50% overlap 的 Hanning），
        # 窗函數和已經約等於 1，不需要額外歸一化
        # 只有在窗函數和不為常數時才需要歸一化
        #
        # 這裡我們假設使用的是 COLA 兼容的參數，所以註釋掉歸一化
        # if self.window is not None:
        #     window_sum = np.zeros(output_length)
        #     window_len = min(len(self.window), frame_size)
        #     for i in range(n_frames):
        #         start = i * self.frame_shift
        #         end = min(start + window_len, output_length)
        #         actual_len = end - start
        #         window_sum[start:end] += self.window[:actual_len]
        #     window_sum = np.maximum(window_sum, 1e-10)
        #     output = output / window_sum

        # 裁剪到原始長度
        if original_length is not None:
            output = output[:original_length]

        return output

    def reconstruct_signal(
        self,
        magnitudes: np.ndarray,
        phases: np.ndarray,
        original_length: Optional[int] = None
    ) -> np.ndarray:
        """
        從幅度譜和相位譜重建完整信號

        參數:
            magnitudes: 幅度譜 (n_frames, n_freqs)
            phases: 相位譜 (n_frames, n_freqs)
            original_length: 原始信號長度

        返回:
            signal: 重建的時域信號
        """
        n_frames = magnitudes.shape[0]

        # 重建每一幀
        frames = np.zeros((n_frames, self.fft_size))
        for i in range(n_frames):
            frames[i] = self.reconstruct_frame(magnitudes[i], phases[i])

        # Overlap-Add
        signal = self.overlap_add(frames, original_length)

        return signal

    def reconstruct_from_spectra(
        self,
        spectra: np.ndarray,
        original_length: Optional[int] = None
    ) -> np.ndarray:
        """
        從複數頻譜重建完整信號

        參數:
            spectra: 複數頻譜 (n_frames, n_freqs)
            original_length: 原始信號長度

        返回:
            signal: 重建的時域信號
        """
        n_frames = spectra.shape[0]

        # 重建每一幀
        frames = np.zeros((n_frames, self.fft_size))
        for i in range(n_frames):
            frames[i] = self.reconstruct_from_spectrum(spectra[i])

        # Overlap-Add
        signal = self.overlap_add(frames, original_length)

        return signal

    def __repr__(self):
        return (f"Reconstructor(fft_size={self.fft_size}, "
                f"frame_shift={self.frame_shift})")
