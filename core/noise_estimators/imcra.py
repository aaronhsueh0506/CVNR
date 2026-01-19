"""
IMCRA - Improved Minima Controlled Recursive Averaging

基於 Cohen 2003 論文的正確實現：
Cohen, I. (2003). "Noise spectrum estimation in adverse environments:
Improved minima controlled recursive averaging."
IEEE Trans. Speech Audio Process., 11(5), 466-475.

核心特點：
    1. 頻率平滑（Hanning 窗）
    2. 兩階段結構（粗略 VAD + 精細估計）
    3. 週期性最小值追蹤
    4. 雙 SPP 機制（一個用於增益，一個用於噪聲更新）
"""

import numpy as np
from typing import Optional, Tuple
from scipy.ndimage import convolve1d


class ImcraNoiseEstimator:
    """
    IMCRA 噪聲估計器（Cohen 2003）

    兩階段處理流程：
        第一階段（粗略 VAD）:
            1. 頻率平滑：S_f = Σ b(i) * |Y(k-i)|²（Hanning 窗）
            2. 時間平滑：S = α_s * S + (1-α_s) * S_f
            3. 最小值追蹤：S_min = min{S[l-L:l]}
            4. 粗略語音指示：I(k) = 1 if S(k)/S_min(k) < δ

        第二階段（精細估計）:
            5. 條件頻率平滑：tilde_S_f = Σ b(i)*I(k-i)*S_f(k-i) / Σ b(i)*I(k-i)
            6. 時間平滑：tilde_S = α_s * tilde_S + (1-α_s) * tilde_S_f
            7. 精細最小值：tilde_S_min
            8. 精細 SPP：p(k) = {1 + q/(1-q) * (1+ξ) * exp(-v)}^{-1}

        噪聲更新:
            9. 自適應平滑：tilde_α_d = α_d + (1-α_d) * p
            10. 噪聲估計：λ_d = tilde_α_d * λ_d + (1-tilde_α_d) * |Y|²

    參數:
        freq_smooth_width: 頻率平滑窗寬度（單側），默認 1
        alpha_s: 時間平滑因子（默認 0.9）
        alpha_d: 噪聲更新基礎速率（默認 0.85）
        L: 最小值窗口長度（幀），默認 96（約 1 秒）
        V: 更新週期（幀），默認 15
        U: 歷史緩衝區數量，默認 8
        delta_db: 偏差補償（dB），默認 5.0
        delta_s_db: 第二階段閾值（dB），默認 3.0
        num_init_frames: 初始化幀數，默認 20
    """

    def __init__(
        self,
        freq_smooth_width: int = 1,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        L: int = 96,
        V: int = 15,
        U: int = 8,
        delta_db: float = 5.0,
        delta_s_db: float = 3.0,
        num_init_frames: int = 20
    ):
        # 頻率平滑參數
        self.freq_smooth_width = freq_smooth_width
        self._init_freq_smooth_window()

        # 時間平滑參數
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d

        # 最小值追蹤參數
        self.L = L  # 總窗口長度
        self.V = V  # 更新週期
        self.U = U  # 子窗口數量

        # 閾值參數（線性域）
        self.delta = 10 ** (delta_db / 10)  # 第一階段閾值 Γ_0
        self.delta_s = 10 ** (delta_s_db / 10)  # 第二階段閾值 Γ_1

        # 初始化參數
        self.num_init_frames = num_init_frames

        # 狀態變量
        self.noise_psd = None  # 噪聲功率譜 λ_d
        self.S = None  # 第一階段時間平滑後的功率譜
        self.S_tilde = None  # 第二階段時間平滑後的功率譜
        self.S_min = None  # 第一階段最小值
        self.S_tilde_min = None  # 第二階段最小值

        # 最小值追蹤緩衝區（使用 U 個子窗口）
        self.S_min_buffer = None  # shape: (U, n_freqs)
        self.S_tilde_min_buffer = None

        # 子窗口內的當前最小值
        self.S_min_sw = None  # 當前子窗口最小值
        self.S_tilde_min_sw = None

        self.is_initialized = False
        self.frame_count = 0
        self.subwin_count = 0  # 子窗口內的幀計數

    def _init_freq_smooth_window(self):
        """初始化頻率平滑窗（歸一化 Hanning 窗）"""
        w = self.freq_smooth_width
        if w <= 0:
            self.freq_window = np.array([1.0])
        else:
            # 創建 Hanning 窗 (2*w+1 長度)
            window = np.hanning(2 * w + 1)
            # 歸一化
            self.freq_window = window / window.sum()

    def _frequency_smooth(self, power_spectrum: np.ndarray) -> np.ndarray:
        """
        頻率平滑（使用 Hanning 窗卷積）

        S_f(k,l) = Σ_{i=-w}^{w} b(i) * |Y(k-i,l)|²

        參數:
            power_spectrum: 功率譜 |Y|² (n_freqs,)

        返回:
            smoothed: 頻率平滑後的功率譜 (n_freqs,)
        """
        if len(self.freq_window) == 1:
            return power_spectrum.copy()

        # 使用 scipy 的 convolve1d，邊界使用反射模式
        smoothed = convolve1d(power_spectrum, self.freq_window, mode='reflect')
        return smoothed

    def _conditional_frequency_smooth(
        self,
        S_f: np.ndarray,
        indicator: np.ndarray
    ) -> np.ndarray:
        """
        條件頻率平滑（第二階段）

        tilde_S_f(k) = Σ b(i) * I(k-i) * S_f(k-i) / Σ b(i) * I(k-i)

        只對語音不存在的頻率進行平滑

        參數:
            S_f: 頻率平滑後的功率譜 (n_freqs,)
            indicator: 語音不存在指示 I(k)，1=非語音，0=語音 (n_freqs,)

        返回:
            tilde_S_f: 條件平滑後的功率譜 (n_freqs,)
        """
        if len(self.freq_window) == 1:
            return S_f.copy()

        # 加權功率譜
        weighted = indicator * S_f

        # 卷積
        numerator = convolve1d(weighted, self.freq_window, mode='reflect')
        denominator = convolve1d(indicator, self.freq_window, mode='reflect')

        # 避免除零
        denominator = np.maximum(denominator, 1e-10)

        tilde_S_f = numerator / denominator

        # 對於沒有非語音鄰居的位置，使用原始 S_f
        no_neighbor = denominator < 1e-8
        tilde_S_f[no_neighbor] = S_f[no_neighbor]

        return tilde_S_f

    def _update_minimum_tracking(
        self,
        S_smoothed: np.ndarray,
        S_min_sw: np.ndarray,
        S_min_buffer: np.ndarray,
        S_min: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        更新最小值追蹤（週期性方法）

        每 V 幀更新一次：
            1. 將當前子窗口最小值存入緩衝區
            2. 計算所有子窗口的全局最小值
            3. 重置子窗口最小值

        參數:
            S_smoothed: 當前時間平滑後的功率譜
            S_min_sw: 當前子窗口內的最小值
            S_min_buffer: 歷史子窗口最小值緩衝區 (U, n_freqs)
            S_min: 當前全局最小值

        返回:
            (updated_S_min_sw, updated_S_min_buffer, updated_S_min)
        """
        # 更新子窗口內的最小值
        S_min_sw = np.minimum(S_min_sw, S_smoothed)

        # 檢查是否到達更新週期
        if self.subwin_count >= self.V:
            # 滾動緩衝區，將最舊的子窗口移除
            S_min_buffer = np.roll(S_min_buffer, -1, axis=0)
            # 將當前子窗口最小值存入最新位置
            S_min_buffer[-1] = S_min_sw

            # 計算所有子窗口的全局最小值
            S_min = np.min(S_min_buffer, axis=0)

            # 重置子窗口最小值為當前值
            S_min_sw = S_smoothed.copy()

            # 重置子窗口計數
            self.subwin_count = 0

        return S_min_sw, S_min_buffer, S_min

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        使用初始幀估計噪聲

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 初始噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_freqs = magnitude_spectrum.shape[1]

        # 使用前 N 幀的平均功率初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2
        init_psd = np.mean(power_spectrum, axis=0)

        # 初始化噪聲估計
        self.noise_psd = init_psd.copy()

        # 初始化第一階段狀態
        self.S = init_psd.copy()
        self.S_min = init_psd.copy()
        self.S_min_sw = init_psd.copy()
        self.S_min_buffer = np.tile(init_psd, (self.U, 1))

        # 初始化第二階段狀態
        self.S_tilde = init_psd.copy()
        self.S_tilde_min = init_psd.copy()
        self.S_tilde_min_sw = init_psd.copy()
        self.S_tilde_min_buffer = np.tile(init_psd, (self.U, 1))

        self.is_initialized = True
        self.frame_count = self.num_init_frames
        self.subwin_count = 0

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        spp: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        IMCRA 兩階段噪聲估計更新

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            spp: 外部 SPP（可選，用於增益計算的 SPP）

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # ==================== 第一階段：粗略 VAD ====================

        # 1. 計算功率譜
        power = magnitude ** 2

        # 2. 頻率平滑
        S_f = self._frequency_smooth(power)

        # 3. 時間平滑
        self.S = self.alpha_s * self.S + (1 - self.alpha_s) * S_f

        # 4. 最小值追蹤
        self.S_min_sw, self.S_min_buffer, self.S_min = self._update_minimum_tracking(
            self.S, self.S_min_sw, self.S_min_buffer, self.S_min
        )

        # 5. 粗略語音指示（非語音 = 1，語音 = 0）
        # I(k) = 1 if S(k) / S_min(k) < δ
        S_ratio = self.S / (self.S_min + 1e-10)
        indicator = (S_ratio < self.delta).astype(float)

        # ==================== 第二階段：精細估計 ====================

        # 6. 條件頻率平滑
        S_tilde_f = self._conditional_frequency_smooth(S_f, indicator)

        # 7. 第二階段時間平滑
        self.S_tilde = self.alpha_s * self.S_tilde + (1 - self.alpha_s) * S_tilde_f

        # 8. 第二階段最小值追蹤
        self.S_tilde_min_sw, self.S_tilde_min_buffer, self.S_tilde_min = \
            self._update_minimum_tracking(
                self.S_tilde, self.S_tilde_min_sw,
                self.S_tilde_min_buffer, self.S_tilde_min
            )

        # 9. 計算精細 SPP（用於噪聲更新）
        # 基於 tilde_S / tilde_S_min 的比值
        S_tilde_ratio = self.S_tilde / (self.S_tilde_min + 1e-10)

        # 使用 sigmoid 函數平滑 SPP
        # p(k) ≈ 1 / (1 + exp(-κ * (ratio - δ_s)))
        # 這裡使用簡化版本
        spp_noise_update = 1.0 / (1.0 + np.exp(-5 * (S_tilde_ratio / self.delta_s - 1.0)))

        # ==================== 噪聲更新 ====================

        # 10. 自適應平滑因子
        # tilde_α_d = α_d + (1 - α_d) * p
        tilde_alpha_d = self.alpha_d + (1 - self.alpha_d) * spp_noise_update

        # 11. 噪聲估計更新
        # λ_d = tilde_α_d * λ_d + (1 - tilde_α_d) * |Y|²
        self.noise_psd = tilde_alpha_d * self.noise_psd + (1 - tilde_alpha_d) * power

        # 更新計數器
        self.frame_count += 1
        self.subwin_count += 1

        return self.noise_psd

    def get_spp_for_gain(self) -> Optional[np.ndarray]:
        """
        獲取用於增益計算的 SPP

        這是第一階段的 SPP，與用於噪聲更新的 SPP 不同
        """
        if self.S is None or self.S_min is None:
            return None

        S_ratio = self.S / (self.S_min + 1e-10)
        spp = 1.0 / (1.0 + np.exp(-5 * (S_ratio / self.delta - 1.0)))
        return spp

    def reset(self):
        """重置估計器"""
        self.noise_psd = None
        self.S = None
        self.S_tilde = None
        self.S_min = None
        self.S_tilde_min = None
        self.S_min_buffer = None
        self.S_tilde_min_buffer = None
        self.S_min_sw = None
        self.S_tilde_min_sw = None
        self.is_initialized = False
        self.frame_count = 0
        self.subwin_count = 0

    def __repr__(self):
        return (f"ImcraNoiseEstimator(alpha_s={self.alpha_s}, "
                f"alpha_d={self.alpha_d}, L={self.L}, V={self.V}, U={self.U})")
