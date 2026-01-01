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

    v1.3.0 新增：
        支持動態 alpha 切換，用於噪聲場景快速適應
        - 正常模式：alpha = 0.95（慢速適應，時間常數 τ≈20幀）
        - 快速模式：alpha = 0.5（快速適應，時間常數 τ≈2幀）
    """

    def __init__(
        self,
        alpha: float = 0.95,
        num_init_frames: int = 20,
        update_during_speech: bool = False
    ):
        self.alpha = alpha
        self.alpha_normal = alpha  # 保存正常模式的 alpha
        self.num_init_frames = num_init_frames
        self.update_during_speech = update_during_speech

        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0

        # v1.3.0: 快速適應狀態
        self.current_alpha = alpha
        self.is_fast_mode = False
        self.fast_mode_frames = 0
        self.fast_mode_duration = 50  # 快速模式持續幀數
        self.alpha_fast = 0.5  # 快速模式的 alpha

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
        is_speech: Optional[bool] = None
    ) -> np.ndarray:
        """
        遞歸更新噪聲估計

        v1.3.0: 支持動態 alpha（快速/正常模式）

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 當前幀是否為語音（可選）

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # v1.3.0: 快速模式計時器
        if self.is_fast_mode:
            self.fast_mode_frames += 1
            # 達到持續時間後恢復正常模式
            if self.fast_mode_frames >= self.fast_mode_duration:
                self.current_alpha = self.alpha_normal
                self.is_fast_mode = False
                self.fast_mode_frames = 0

        # 計算當前幀的功率譜
        current_psd = magnitude ** 2

        # 決定是否更新
        should_update = True
        if is_speech is not None and not self.update_during_speech:
            should_update = not is_speech

        # 遞歸更新（使用當前 alpha）
        if should_update:
            self.noise_psd = self.current_alpha * self.noise_psd + \
                            (1 - self.current_alpha) * current_psd

        self.frame_count += 1

        return self.noise_psd

    def trigger_fast_adaptation(self):
        """
        觸發快速適應模式（v1.3.0 新增）

        用於噪聲場景變化檢測後，快速適應新的噪聲特性
        - 切換到 alpha = 0.5（快速模式）
        - 持續 50 幀（500ms）後自動恢復正常
        """
        self.current_alpha = self.alpha_fast
        self.is_fast_mode = True
        self.fast_mode_frames = 0

    def reset(self):
        """重置估計器"""
        self.noise_psd = None
        self.is_initialized = False
        self.frame_count = 0
        self.current_alpha = self.alpha_normal
        self.is_fast_mode = False
        self.fast_mode_frames = 0

    def __repr__(self):
        return (f"RecursiveAverageNoiseEstimator(alpha={self.alpha}, "
                f"num_init_frames={self.num_init_frames})")
