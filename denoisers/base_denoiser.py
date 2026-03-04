"""
Base Denoiser - 降噪器基類

v2.6: 添加 Human Voice Band Soft VAD 後處理
"""

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple


class BaseDenoiser(ABC):
    """
    降噪器抽象基類

    定義所有降噪器的通用接口

    v2.6 新增:
        - Human Voice Band Soft VAD: 基於語音頻帶能量的軟 VAD
        - 頻率範圍: 300Hz - 3400Hz
        - 非語音段衰減至 0.1，語音段保持 1.0
    """

    def __init__(self, sample_rate: int = 16000, n_fft: int = 512):
        self.sample_rate = sample_rate
        self.is_initialized = False

        # Soft VAD 參數
        self.n_fft = n_fft
        self.vad_freq_low = 300    # Hz
        self.vad_freq_high = 3400  # Hz
        self.alpha_vad = 0.5      # VAD 平滑因子
        self.vad_state = 1.0       # VAD 狀態
        self.vad_method = 'spp'   # 'spp', 'flatness', 'energy_ratio'

        # 計算頻率 bin 索引
        freq_resolution = sample_rate / n_fft
        self.vad_start_bin = int(self.vad_freq_low / freq_resolution)
        self.vad_end_bin = min(int(self.vad_freq_high / freq_resolution), n_fft // 2 + 1)

    @abstractmethod
    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
        """
        pass

    @abstractmethod
    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        在頻域進行降噪

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（通常不變）(n_frames, n_freqs)
        """
        pass

    @abstractmethod
    def reset(self):
        """重置降噪器狀態"""
        pass

    def _apply_soft_vad(self, enhanced_mag: np.ndarray, spp: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Human Voice Band Soft VAD

        支持三種方法（由 self.vad_method 選擇）：
        1. 'spp': 語音頻帶 SPP 平均值（需傳入 spp，零額外計算）
        2. 'flatness': 頻譜平坦度（噪聲平坦≈1，語音有諧波≈0）
        3. 'energy_ratio': 語音頻帶能量比（語音集中在 300-3400Hz）

        參數:
            enhanced_mag: 增強後的幅度譜 (n_freqs,)
            spp: 語音存在機率 (n_freqs,)，可選（method='spp' 時使用）

        返回:
            vad_enhanced_mag: 經 VAD 處理的幅度譜 (n_freqs,)
        """
        speech_band = enhanced_mag[self.vad_start_bin:self.vad_end_bin]

        if self.vad_method == 'spp' and spp is not None:
            # SPP-based: 語音頻帶 SPP 平均值直接作為 VAD 指標
            frame_spp = np.mean(spp[self.vad_start_bin:self.vad_end_bin])
            vad_inst = max(0.1, float(frame_spp))

        elif self.vad_method == 'flatness':
            # Spectral Flatness: geometric_mean / arithmetic_mean
            # 噪聲（平坦）→ flatness ≈ 1 → vad_inst 低
            # 語音（諧波）→ flatness ≈ 0 → vad_inst 高
            psd = speech_band ** 2 + 1e-10
            log_mean = np.exp(np.mean(np.log(psd)))
            arith_mean = np.mean(psd)
            flatness = log_mean / (arith_mean + 1e-10)
            # flatness ∈ [0,1]，反轉: 語音(flatness低)→高增益
            vad_inst = 0.1 + 0.9 * (1.0 - flatness)

        elif self.vad_method == 'energy_ratio':
            # Energy Ratio: 語音頻帶能量 / 全頻帶能量
            # 語音集中在 300-3400Hz → ratio 高
            speech_energy = np.sum(speech_band ** 2)
            total_energy = np.sum(enhanced_mag ** 2) + 1e-10
            ratio = speech_energy / total_energy
            # ratio ∈ [0,1]，語音時 ratio 高
            vad_inst = 0.1 + 0.9 * min(1.0, ratio / 0.5)

        else:
            # Fallback: power-based
            mean_power = np.mean(speech_band ** 2) + 1e-10
            vad_inst = 0.1 + 0.9 * (1.0 - np.exp(-3.0 * mean_power))

        # 時間平滑
        self.vad_state = self.alpha_vad * self.vad_state + (1 - self.alpha_vad) * vad_inst

        # 套用增益
        return enhanced_mag * self.vad_state

    def _reset_vad(self):
        """重置 VAD 狀態"""
        self.vad_state = 1.0

    def __repr__(self):
        return f"{self.__class__.__name__}(sample_rate={self.sample_rate})"
