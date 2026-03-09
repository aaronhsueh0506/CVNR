"""
Reconstructor - 頻譜重建、IFFT、Overlap-Add

Overlap-Add (OLA) 正確實現說明:

1. 分析階段 (FrameProcessor):
   - 加分析窗: x_windowed = x * w_a
   - FFT: X = FFT(x_windowed)

2. 處理階段 (GainCalculator):
   - 應用增益: Y = G * X

3. 合成階段 (Reconstructor):
   - IFFT: y = IFFT(Y)
   - 加合成窗: y_windowed = y * w_s  (必須！)
   - OLA 疊加: output[start:end] += y_windowed
   - COLA 歸一化: output / Σ(w_s^2)  (必須！)

對於 COLA 條件 (Constant Overlap-Add):
- 50% overlap + Hanning 窗
- Σ(w^2) = 常數
- 這是窗函數平方和，不是窗函數和！
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
        """
        從幅度和相位重建時域幀

        參數:
            magnitude: 幅度譜 (fft_size//2 + 1,)
            phase: 相位譜 (fft_size//2 + 1,)

        返回:
            frame: 時域信號 (frame_size,) or (fft_size,)
        """
        # 重建複數頻譜
        spectrum = magnitude * np.exp(1j * phase)

        # IFFT → 取前 frame_size 點（= window length）
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
        """
        從複數頻譜重建時域幀

        參數:
            spectrum: 複數頻譜 (fft_size//2 + 1,)

        返回:
            frame: 時域信號 (frame_size,) or (fft_size,)
        """
        # IFFT → 取前 frame_size 點（= window length）
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
        """
        使用 Overlap-Add 方法重建完整信號

        OLA 正確流程:
        1. IFFT 得到時域幀
        2. 應用合成窗（與分析窗相同）
        3. Overlap-Add 疊加
        4. 窗函數平方和歸一化（COLA）

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

        # Overlap-Add with sqrt(Hann) synthesis window
        # sqrt(Hann) × sqrt(Hann) + 50% overlap = 自動能量守恆
        # 不需要手動歸一化！
        for i, frame in enumerate(frames):
            start = i * self.frame_shift
            end = start + frame_size

            # 應用 sqrt(Hann) 合成窗
            if self.window is not None:
                windowed_frame = frame * self.window
            else:
                windowed_frame = frame

            output[start:end] += windowed_frame

        # ✓ 移除 COLA 歸一化代碼
        # sqrt(w) × sqrt(w) + 50% overlap 已經滿足 COLA 條件
        # 能量自動守恆，不需要手動除以 window_sum

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

        # 確定幀長度（如果有窗函數則使用窗函數長度，否則使用 FFT size）
        frame_length = len(self.window) if self.window is not None else self.fft_size

        # 重建每一幀
        frames = np.zeros((n_frames, frame_length))
        for i in range(n_frames):
            frames[i] = self.reconstruct_frame(magnitudes[i], phases[i])

        # Overlap-Add
        signal = self.overlap_add(frames, original_length)

        return signal

    def __repr__(self):
        return (f"Reconstructor(fft_size={self.fft_size}, "
                f"frame_shift={self.frame_shift})")
