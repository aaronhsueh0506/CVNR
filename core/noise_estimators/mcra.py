"""
MCRA - Minima Controlled Recursive Averaging
Cohen & Berdugo (2002)

用於 V3 系列降噪器

特點：
- 時間平滑：減少功率譜波動
- 最小值追蹤：找到噪聲底線
- SPP 門控：語音段自動減少噪聲更新

參考文獻：
    Cohen, I. & Berdugo, B. (2002). "Noise estimation by minima controlled
    recursive averaging for robust speech enhancement." IEEE Signal Processing
    Letters, 9(1), 12-15.
"""

import numpy as np
from typing import Optional


class McraNoiseEstimator:
    """
    MCRA 噪聲估計器

    演算法步驟：
    1. 時間平滑：S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
    2. 最小值追蹤：S_min(k,l) = min{S(k,τ): l-L+1 ≤ τ ≤ l}
    3. 語音指示器：I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
    4. SPP 平滑：p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
    5. 噪聲更新：α̃_d = α_d + (1-α_d)·p(k,l)
                 N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²

    參數:
        alpha_s: 時間平滑因子 (0.85-0.95)，越大越平滑
        alpha_d: 噪聲更新基礎速率 (0.80-0.90)，越大更新越慢
        alpha_p: SPP 平滑因子 (0.1-0.3)，越大 SPP 變化越平緩
        L: 最小值窗口長度（幀），約 1 秒 @ 10ms 幀移
        delta_db: 偏差補償（dB），語音檢測閾值
        num_init_frames: 初始化使用的幀數
        enable_eta: 場景轉換偵測開關（單幀能量比）
        eta_beta_threshold: 能量比閾值，β > threshold 時觸發（預設 10.0）
        eta_slope: sigmoid 斜率（預設 20.0）
    """

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        enable_eta: bool = False,
        eta_beta_threshold: float = 10.0,
        eta_slope: float = 20.0
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)  # 線性域的 delta
        self.num_init_frames = num_init_frames
        self.enable_eta = enable_eta
        self.eta_beta_threshold = eta_beta_threshold
        self.eta_slope = eta_slope

        # 狀態變量
        self.noise_psd = None       # 噪聲功率譜密度
        self.S = None               # 時間平滑後的功率譜
        self.S_min = None           # 最小值
        self.min_buffer = None      # 最小值追蹤緩衝區 (L, n_freqs)
        self.spp = None             # Speech Presence Probability
        # 場景偵測狀態
        self._prev_frame_power = None
        self._energy_smooth = None

        self.is_initialized = False
        self.frame_count = 0

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        初始化噪聲估計

        v2.1: 改用 20th 百分位數作為噪聲估計，避免語音幀導致過高估計。

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 初始噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_freqs = magnitude_spectrum.shape[1]

        # 使用前 N 幀初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2

        # v2.1: 使用 20th 百分位數而非平均值
        # 這樣即使初始幀包含語音，也能得到較低的噪聲估計
        init_psd = np.percentile(power_spectrum, 20, axis=0)

        # 初始化狀態
        self.noise_psd = init_psd.copy()
        self.S = np.mean(power_spectrum, axis=0)  # S 用平均值以便 SPP 計算
        self.S_min = init_psd.copy()
        self.spp = np.zeros(n_freqs)

        # 初始化最小值追蹤緩衝區（用 init_psd 填滿）
        self.min_buffer = np.tile(init_psd, (self.L, 1))

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def _compute_eta(self, power: np.ndarray) -> float:
        """
        場景轉換偵測：平滑能量比 + hard threshold

        使用平滑後的能量計算 beta，避免語音能量跳變誤觸發。
        Hard threshold: beta < threshold → eta=1.0（不動 alpha_d）,
                       beta > threshold → eta=0.1（加速噪聲更新）

        v2.0: 修正舊版 0.95 上限導致語音幀噪聲更新速度增加 10x 的問題
        """
        E_cur = np.sum(power)

        if self._energy_smooth is None:
            self._energy_smooth = E_cur
            self._prev_frame_power = E_cur
            return 1.0

        # 平滑能量（避免語音瞬態誤觸發）
        self._energy_smooth = 0.7 * self._energy_smooth + 0.3 * E_cur

        beta = self._energy_smooth / (self._prev_frame_power + 1e-10)
        self._prev_frame_power = self._energy_smooth

        if beta > self.eta_beta_threshold:
            return 0.1  # 場景變化：加速噪聲更新
        return 1.0  # 正常：不干擾 alpha_d

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # 保持接口兼容（MCRA 內部判斷，忽略此參數）
        spp: Optional[np.ndarray] = None   # v2.0: 支持外部 SPP（軟判決）
    ) -> np.ndarray:
        """
        MCRA 噪聲估計更新

        v2.0: 支持外部 SPP 軟判決
        - 若傳入 spp 參數，使用外部 SPP 取代內部 SPP 進行噪聲更新
        - 仍會計算內部 SPP（用於最小值追蹤），但更新時使用外部 SPP

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 忽略，MCRA 使用 SPP 判斷
            spp: 外部 SPP 值 (n_freqs,)，可選。若提供則用於噪聲更新門控

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # 1. 計算當前幀的功率譜
        power = magnitude ** 2

        # 2. 時間平滑
        # S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
        self.S = self.alpha_s * self.S + (1 - self.alpha_s) * power

        # 3. 更新最小值緩衝區（FIFO 滾動）
        self.min_buffer = np.roll(self.min_buffer, -1, axis=0)
        self.min_buffer[-1] = self.S

        # 4. 計算最小值
        # S_min(k,l) = min{S(k,τ): l-L+1 ≤ τ ≤ l}
        self.S_min = np.min(self.min_buffer, axis=0)

        # 5. 語音指示器（基於最小值比）
        # I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
        # 注意：比值大於 delta 表示可能有語音
        ratio = self.S / (self.S_min * self.delta + 1e-10)
        indicator = (ratio > 1.0).astype(float)

        # 6. SPP 平滑
        # p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self.spp = self.alpha_p * self.spp + (1 - self.alpha_p) * indicator

        # 7. 噪聲更新（SPP 門控）
        # v2.0: 若提供外部 SPP，使用外部 SPP；否則使用內部 SPP
        spp_for_update = spp if spp is not None else self.spp

        # α̃_d(k,l) = α_d + (1-α_d)·p(k,l)
        # 當 SPP 高（語音段）時，α̃_d 接近 1，噪聲更新慢
        # 當 SPP 低（噪聲段）時，α̃_d 接近 α_d，噪聲更新快
        tilde_alpha_d = self.alpha_d + (1 - self.alpha_d) * spp_for_update

        # 8. 場景轉換偵測
        if self.enable_eta:
            eta = self._compute_eta(power)
            tilde_alpha_d = tilde_alpha_d * eta

        # N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²
        self.noise_psd = tilde_alpha_d * self.noise_psd + (1 - tilde_alpha_d) * power

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """重置估計器狀態"""
        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.min_buffer = None
        self.spp = None
        self._prev_frame_power = None
        self._energy_smooth = None
        self.is_initialized = False
        self.frame_count = 0

    def __repr__(self):
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L})")
