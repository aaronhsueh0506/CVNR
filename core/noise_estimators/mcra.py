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
    """

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        broadband_threshold: float = 0.8,
        # 場景轉換偵測參數（實際實作為「高頻段 γ + 高頻段 spectral flatness」聯合判斷；
        # flatness 用於避免語音誤觸發，因語音 flatness 較低）
        scene_change_threshold_db: float = 10.0,   # 高頻段 γ 閾值 (dB)
        scene_change_min_frames: int = 5,           # 連續幀數確認
        scene_change_blend: float = 0.5,            # 噪聲重置混合比例
        scene_change_flatness_threshold: float = 0.4,  # 高頻段 spectral flatness 閾值
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)  # 線性域的 delta
        self.num_init_frames = num_init_frames
        self.broadband_threshold = broadband_threshold

        # 場景轉換偵測（高頻段 γ + flatness 聯合）
        self.scene_change_threshold = 10 ** (scene_change_threshold_db / 10)
        self.scene_change_min_frames = scene_change_min_frames
        self.scene_change_blend = scene_change_blend
        self.scene_change_flatness_threshold = scene_change_flatness_threshold
        self.scene_change_count = 0

        # 狀態變量
        self.noise_psd = None       # 噪聲功率譜密度
        self.S = None               # 時間平滑後的功率譜
        self.S_min = None           # 最小值
        self.min_buffer = None      # 最小值追蹤緩衝區 (L, n_freqs)
        self.spp = None             # Speech Presence Probability

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

        # 使用 30th 百分位數作初始噪聲估計（20th 太低容易過低估計）
        # v4.2.1 C-align: 改用 k-th 最小值（不做線性插值），與 C quickselect 語義一致。
        # 原 np.percentile(..., 30) 會在 sorted[k]/sorted[k+1] 之間做線性插值，C 則直接取 sorted[k]。
        N = power_spectrum.shape[0]
        k = ((N - 1) * 30) // 100
        init_psd = np.partition(power_spectrum, k, axis=0)[k]

        # 初始化狀態：S、S_min、min_buffer 必須從同一個統計量出發
        # 若 S 用均值而 S_min 用 P30，第一次 update 時 ratio = S/(S_min*delta) 會異常（>>1 或 <<1），
        # 導致 indicator 在純噪聲段誤觸發或誤壓
        self.noise_psd = init_psd.copy()
        self.S = init_psd.copy()       # 與 S_min 一致，避免初始 ratio 異常
        self.S_min = init_psd.copy()
        self.spp = np.zeros(n_freqs)

        # 初始化最小值追蹤緩衝區（用 init_psd 填滿）
        self.min_buffer = np.tile(init_psd, (self.L, 1))

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # 保持接口兼容（MCRA 內部判斷，忽略此參數）
        spp: Optional[np.ndarray] = None,  # v2.0: 支持外部 SPP（軟判決）
    ) -> np.ndarray:
        """
        MCRA 噪聲估計更新

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 忽略，MCRA 使用 SPP 判斷
            spp: 外部 SPP 值 (n_freqs,)，可選

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

        # 7. 場景轉換偵測
        # 條件：高頻 γ 高 AND 高頻 spectral flatness 高
        # - 高頻 γ 高：能量突然增加（可能是噪聲或語音）
        # - Spectral flatness 高：能量分布平坦（噪聲特徵，語音 ~0.1-0.2，白噪聲 ~0.5-0.7）
        # 兩者同時滿足才觸發，避免語音誤觸發
        n_freqs = len(power)
        hi_start = n_freqs // 2  # 上半頻段（~4kHz for 16kHz/512FFT）
        hi_power = power[hi_start:]
        hi_gamma = np.mean(hi_power) / (np.mean(self.noise_psd[hi_start:]) + 1e-10)

        # Spectral flatness = geometric_mean / arithmetic_mean（高頻段）
        hi_power_safe = hi_power + 1e-20
        hi_flatness = np.exp(np.mean(np.log(hi_power_safe))) / (np.mean(hi_power_safe))

        if (hi_gamma > self.scene_change_threshold and
                hi_flatness > self.scene_change_flatness_threshold):
            self.scene_change_count += 1
            if self.scene_change_count >= self.scene_change_min_frames:
                # 場景轉換確認：部分重置噪聲估計和最小值追蹤
                blend = self.scene_change_blend
                self.noise_psd = blend * self.noise_psd + (1 - blend) * power
                self.S_min = self.S.copy()
                self.min_buffer[:] = self.S.reshape(1, -1)
                self.scene_change_count = 0
        else:
            self.scene_change_count = 0

        # 8. 噪聲更新（SPP 門控）
        # v2.0: 若提供外部 SPP，使用外部 SPP；否則使用內部 SPP
        spp_for_update = spp if spp is not None else self.spp

        # 寬頻場景轉換偵測（舊方法，broadband_threshold < 1.0 時啟用）
        if self.broadband_threshold < 1.0:
            high_spp_ratio = np.mean(self.spp > 0.5)
            if high_spp_ratio > self.broadband_threshold:
                scale = max(0.0, 1.0 - (high_spp_ratio - self.broadband_threshold)
                            / (1.0 - self.broadband_threshold))
                spp_for_update = spp_for_update * scale

        # α̃_d(k,l) = α_d + (1-α_d)·p(k,l)
        # 當 SPP 高（語音段）時，α̃_d 接近 1，噪聲更新慢
        # 當 SPP 低（噪聲段）時，α̃_d 接近 α_d，噪聲更新快
        tilde_alpha_d = self.alpha_d + (1 - self.alpha_d) * spp_for_update

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
        self.is_initialized = False
        self.frame_count = 0
        self.scene_change_count = 0

    def __repr__(self):
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L})")
