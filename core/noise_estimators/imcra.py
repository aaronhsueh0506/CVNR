"""
IMCRA - Improved Minima Controlled Recursive Averaging
用於 V4
"""

import numpy as np
from typing import Optional


class ImcraNoiseEstimator:
    """
    IMCRA 噪聲估計器

    業界最先進的噪聲估計方法之一（Cohen & Berdugo, 2001）

    核心思想:
        1. 時間-頻率雙重平滑
        2. 最小值追蹤（滑動窗口）
        3. SPP 引導的更新
        4. 偏移補償

    參數:
        alpha_s: 頻譜平滑因子（0.85-0.95）
        alpha_d: 噪聲更新速率（0.80-0.90）
        L: 最小值窗口長度（幀數），通常 150 幀 ≈ 1.5 秒
        delta_db: 偏移量（dB），補償最小值的偏差
        num_init_frames: 初始化幀數

    v1.3.0 新增：
        支持快速追蹤模式，用於噪聲場景快速適應
        - 正常模式：alpha_s=0.9, alpha_d=0.85, L=150
        - 快速模式：alpha_s=0.7, alpha_d=0.5, L=50（縮短窗口）
    """

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        L: int = 150,
        delta_db: float = 5.0,
        num_init_frames: int = 20
    ):
        self.alpha_s = alpha_s
        self.alpha_s_normal = alpha_s  # 保存正常模式參數
        self.alpha_d = alpha_d
        self.alpha_d_normal = alpha_d
        self.L = L
        self.L_normal = L
        self.delta = 10 ** (delta_db / 10)
        self.num_init_frames = num_init_frames

        # 狀態變量
        self.noise_psd = None
        self.smoothed_psd = None
        self.min_buffer = None  # 最小值緩衝區
        self.is_initialized = False
        self.frame_count = 0

        # v1.3.0: 快速追蹤狀態
        self.current_alpha_s = alpha_s
        self.current_alpha_d = alpha_d
        self.current_L = L
        self.is_fast_mode = False
        self.fast_mode_frames = 0
        self.fast_mode_duration = 100  # 快速模式持續幀數
        self.alpha_s_fast = 0.7  # 快速模式參數
        self.alpha_d_fast = 0.5
        self.L_fast = 50

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

        n_freqs = magnitude_spectrum.shape[1]

        # 使用前 N 幀初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2
        self.noise_psd = np.mean(power_spectrum, axis=0)
        self.smoothed_psd = self.noise_psd.copy()

        # 初始化最小值緩衝區
        self.min_buffer = np.tile(self.noise_psd, (self.L, 1))

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        spp: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        IMCRA 更新噪聲估計

        v1.3.0: 支持快速追蹤模式（動態參數）

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            spp: 語音存在機率（可選）(n_freqs,)

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
                self.current_alpha_s = self.alpha_s_normal
                self.current_alpha_d = self.alpha_d_normal
                self.current_L = self.L_normal
                self.is_fast_mode = False
                self.fast_mode_frames = 0

        # 1. 計算當前功率譜
        current_psd = magnitude ** 2

        # 2. 時間平滑（使用當前 alpha_s）
        self.smoothed_psd = self.current_alpha_s * self.smoothed_psd + \
                           (1 - self.current_alpha_s) * current_psd

        # 3. 更新最小值緩衝區（FIFO）
        self.min_buffer = np.roll(self.min_buffer, -1, axis=0)
        self.min_buffer[-1] = self.smoothed_psd

        # 4. 計算最小值（使用當前窗口長度）
        min_psd = np.min(self.min_buffer[-self.current_L:], axis=0)

        # 5. 計算 SPP 指示（如果沒有提供）
        if spp is None:
            # 簡單的 SPP 估計：比較當前值和最小值
            spp_indicator = self.smoothed_psd / (min_psd * self.delta + 1e-10)
            spp = 1.0 / (1.0 + np.exp(-10 * (spp_indicator - 1.0)))
        else:
            # 使用平均 SPP 作為指示
            spp = np.clip(spp, 0, 1)

        # 6. SPP 引導的噪聲更新（使用當前 alpha_d）
        # 低 SPP 區域：更新噪聲估計
        # 高 SPP 區域：保持噪聲估計
        update_factor = (1 - spp) * self.current_alpha_d

        self.noise_psd = update_factor * self.noise_psd + \
                        (1 - update_factor) * min_psd * self.delta

        self.frame_count += 1

        return self.noise_psd

    def trigger_fast_tracking(self):
        """
        觸發快速追蹤模式（v1.3.0 新增）

        用於噪聲場景變化檢測後，快速適應新的噪聲特性
        - 切換到快速模式參數（alpha_s=0.7, alpha_d=0.5, L=50）
        - 縮短最小值緩衝區到 L_fast
        - 持續 100 幀（1秒）後自動恢復正常
        """
        self.current_alpha_s = self.alpha_s_fast
        self.current_alpha_d = self.alpha_d_fast
        self.current_L = self.L_fast
        self.is_fast_mode = True
        self.fast_mode_frames = 0

        # 縮短最小值緩衝區（保留最近的幀）
        if self.min_buffer is not None and len(self.min_buffer) > self.L_fast:
            self.min_buffer = self.min_buffer[-self.L_fast:]

    def reset(self):
        """重置估計器"""
        self.noise_psd = None
        self.smoothed_psd = None
        self.min_buffer = None
        self.is_initialized = False
        self.frame_count = 0
        self.current_alpha_s = self.alpha_s_normal
        self.current_alpha_d = self.alpha_d_normal
        self.current_L = self.L_normal
        self.is_fast_mode = False
        self.fast_mode_frames = 0

    def __repr__(self):
        return (f"ImcraNoiseEstimator(alpha_s={self.alpha_s}, "
                f"alpha_d={self.alpha_d}, L={self.L})")
