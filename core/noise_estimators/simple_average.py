"""
Simple Average Noise Estimator - 簡單平均噪聲估計器
用於 V1 頻譜減法
"""

import numpy as np
from typing import Optional


class SimpleAverageNoiseEstimator:
    """
    使用初始幀的平均值估計噪聲功率譜

    假設：音頻開始的幾幀只包含噪聲（無語音）

    參數:
        num_init_frames: 用於估計噪聲的初始幀數（默認 20 幀 = 0.2 秒）
    """

    def __init__(self, num_init_frames: int = 20):
        self.num_init_frames = num_init_frames
        self.noise_psd = None
        self.is_initialized = False

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        估計噪聲功率譜密度

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            # 單幀
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_frames = magnitude_spectrum.shape[0]

        # 改進：從整個音頻中選擇能量最小的幀來估計噪聲
        # 而不是假設開頭一定是噪聲
        if n_frames > self.num_init_frames * 2:
            # 計算每幀的能量
            frame_energy = np.sum(magnitude_spectrum ** 2, axis=1)

            # 選擇能量最小的 num_init_frames 幀
            min_energy_indices = np.argsort(frame_energy)[:self.num_init_frames]
            init_frames = magnitude_spectrum[min_energy_indices]
        else:
            # 如果幀數不夠多，還是用前 N 幀
            init_frames = magnitude_spectrum[:self.num_init_frames]

        # 計算功率譜（幅度平方）
        power_spectrum = init_frames ** 2

        # 平均
        self.noise_psd = np.mean(power_spectrum, axis=0)
        self.is_initialized = True

        return self.noise_psd

    def update(self, magnitude: np.ndarray) -> np.ndarray:
        """
        更新噪聲估計（對於簡單平均，不更新）

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)

        返回:
            noise_psd: 噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # 簡單平均方法：噪聲估計固定不變
        return self.noise_psd

    def reset(self):
        """重置估計器"""
        self.noise_psd = None
        self.is_initialized = False

    def __repr__(self):
        return f"SimpleAverageNoiseEstimator(num_init_frames={self.num_init_frames})"
