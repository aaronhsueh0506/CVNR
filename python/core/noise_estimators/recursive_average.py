"""
Recursive Average Noise Estimator - 遞歸平均噪聲估計器
用於 V2 Wiener 濾波
"""

import numpy as np
from typing import Optional


class RecursiveAverageNoiseEstimator:
    """
    使用遞歸平均更新噪聲功率譜估計

    公式：
        noise_psd(n) = alpha * noise_psd(n-1) + (1-alpha) * |Y(n)|²

    參數:
        alpha: 平滑因子 (0-1)，越大越平滑
        num_init_frames: 初始化用的幀數
        update_during_speech: 是否在語音段也更新噪聲估計
        spp_hard_threshold: SPP 混合門控閾值
    """

    def __init__(
        self,
        alpha: float = 0.95,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
        spp_hard_threshold: float = 0.8
    ):
        self.alpha = alpha
        self.num_init_frames = num_init_frames
        self.update_during_speech = update_during_speech
        self.spp_hard_threshold = spp_hard_threshold

        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        初始化噪聲估計

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        # 使用前 N 幀初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2
        self.noise_psd = np.mean(power_spectrum, axis=0)

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,
        spp: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        遞歸更新噪聲估計

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 當前幀是否為語音（可選，硬判決）
            spp: 語音存在機率 (n_freqs,)（可選，軟判決，優先於 is_speech）

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # 計算當前幀的功率譜
        current_psd = magnitude ** 2

        # SPP 混合門控更新（優先級最高）
        if spp is not None:
            # 混合門控：高 SPP 完全停止，低 SPP 軟判決
            # SPP > threshold → α̃ = 1.0（完全停止更新）
            # SPP ≤ threshold → α̃ = α + (1-α) * SPP（軟判決）
            hard_mask = spp > self.spp_hard_threshold
            soft_alpha = self.alpha + (1 - self.alpha) * spp
            tilde_alpha = np.where(hard_mask, 1.0, soft_alpha)

            self.noise_psd = tilde_alpha * self.noise_psd + (1 - tilde_alpha) * current_psd
        elif is_speech is not None and not self.update_during_speech:
            # 硬判決：原有邏輯
            if not is_speech:
                self.noise_psd = self.alpha * self.noise_psd + \
                                (1 - self.alpha) * current_psd
            # is_speech=True 時不更新
        else:
            # 無語音資訊：總是更新
            self.noise_psd = self.alpha * self.noise_psd + \
                            (1 - self.alpha) * current_psd

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """重置估計器"""
        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0

    def __repr__(self):
        return (f"RecursiveAverageNoiseEstimator(alpha={self.alpha}, "
                f"num_init_frames={self.num_init_frames})")
