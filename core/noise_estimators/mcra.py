"""
MCRA - Minima Controlled Recursive Averaging
Cohen & Berdugo (2002)

用於 V3 系列降噪器

v3.0: 升級為雙視窗最小值追蹤 (Dual-Window Minima Tracking)
- 整合場景轉換偵測功能
- 移除外部 NoiseChangeDetector 依賴
- 自動適應噪聲場景變化

特點：
- 時間平滑：減少功率譜波動
- 雙視窗最小值追蹤：快速適應噪聲變化
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
    MCRA 噪聲估計器 (整合 Dual-Window Minima Tracking)

    演算法步驟：
    1. 時間平滑：S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
    2. 雙視窗最小值追蹤：
       - S_min = min(S_min, S)
       - S_min_sw = min(S_min_sw, S)
       - 每 L 幀更新：S_min = min(stored_min, S_min_sw)
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
    """

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        spp_hard_threshold: float = 0.8  # 保留向後兼容（未使用）
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)  # 線性域的 delta
        self.num_init_frames = num_init_frames

        # 狀態變量
        self.noise_psd = None       # 噪聲功率譜密度
        self.S = None               # 時間平滑後的功率譜
        self.S_min = None           # 全局最小值
        self.S_min_sw = None        # 子視窗最小值 (Dual-Window)
        self.stored_min = None      # 存儲的最小值 (Dual-Window)
        self.spp = None             # Speech Presence Probability
        self.min_buffer = None      # 保留向後兼容（未使用）

        self.counter = 0            # 視窗計數器 (Dual-Window)
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
        self.S = init_psd.copy()
        self.S_min = init_psd.copy()
        self.S_min_sw = init_psd.copy()   # Dual-Window 子視窗最小值
        self.stored_min = init_psd.copy()  # Dual-Window 存儲的最小值
        self.spp = np.zeros(n_freqs)

        self.counter = 0
        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # 保持接口兼容（MCRA 內部判斷，忽略此參數）
        spp: Optional[np.ndarray] = None   # v2.0: 支持外部 SPP（軟判決）
    ) -> np.ndarray:
        """
        MCRA 噪聲估計更新 (Dual-Window Minima Tracking)

        v3.0: 使用雙視窗最小值追蹤
        - 自動適應噪聲場景變化
        - 不再需要外部 NoiseChangeDetector

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

        # 3. 雙視窗最小值追蹤 (Dual-Window Logic)
        self.S_min = np.minimum(self.S_min, self.S)
        self.S_min_sw = np.minimum(self.S_min_sw, self.S)

        self.counter += 1

        # 每 L 幀強制更新（關鍵：自動適應噪聲場景變化）
        if self.counter >= self.L:
            self.S_min = np.minimum(self.stored_min, self.S_min_sw)
            self.stored_min = self.S_min_sw.copy()
            self.S_min_sw = self.S.copy()
            self.counter = 0

        # 4. 語音指示器（基於最小值比）
        # I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
        ratio = self.S / (self.S_min * self.delta + 1e-10)
        indicator = (ratio > 1.0).astype(float)

        # 5. SPP 平滑
        # p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self.spp = self.alpha_p * self.spp + (1 - self.alpha_p) * indicator

        # 6. 噪聲更新
        # 若提供外部 SPP，使用外部 SPP；否則使用內部 SPP
        used_spp = spp if spp is not None else self.spp
        alpha_d_tilde = self.alpha_d + (1 - self.alpha_d) * used_spp

        # N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²
        self.noise_psd = alpha_d_tilde * self.noise_psd + (1 - alpha_d_tilde) * power

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """重置估計器狀態"""
        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.S_min_sw = None
        self.stored_min = None
        self.spp = None
        self.is_initialized = False
        self.frame_count = 0
        self.counter = 0

    def __repr__(self):
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L})")
