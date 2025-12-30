"""
SPP Estimator - Speech Presence Probability 估計器
用於 V3 和 V4 版本
"""

import numpy as np
from typing import Tuple, Optional


class SppEstimator:
    """
    估計語音存在機率 (Speech Presence Probability, SPP)

    SPP 是每個時頻點存在語音的機率，取值範圍 [0, 1]。
    這是一種軟判決方法，比硬判決（VAD）更平滑。

    參數:
        alpha: 先驗 SNR 平滑因子 (0.92-0.98)
        q: 語音先驗機率 (通常為 0.5)
        xi_min_db: 先驗 SNR 下限 (dB)

    參考文獻:
        Cohen & Berdugo (2001): "Speech Enhancement for Non-stationary Noise Environments"
    """

    def __init__(
        self,
        alpha: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0
    ):
        self.alpha = alpha
        self.q = q
        self.xi_min = 10 ** (xi_min_db / 10)

        # 狀態變量（用於 Decision Directed 方法）
        self.xi_prev = None  # 上一幀的先驗 SNR
        self.gamma_prev = None  # 上一幀的後驗 SNR

    def estimate(
        self,
        Y_psd: np.ndarray,
        noise_psd: np.ndarray,
        gain_prev: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        估計 SPP

        參數:
            Y_psd: 帶噪語音功率譜密度 (n_freqs,)
            noise_psd: 噪聲功率譜密度 (n_freqs,)
            gain_prev: 上一幀的增益（可選，用於 Decision Directed）

        返回:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
        """
        # 1. 計算後驗 SNR (a posteriori SNR)
        gamma = Y_psd / (noise_psd + 1e-10)

        # 2. 估計先驗 SNR (a priori SNR) - Decision Directed 方法
        if self.xi_prev is None or gain_prev is None:
            # 初始化：使用直接估計
            xi = np.maximum(gamma - 1, 0)
        else:
            # Decision Directed 方法
            # ξ(k,l) = α·[G²(k,l-1)·γ(k,l-1)] + (1-α)·max(γ(k,l)-1, 0)
            xi_dd = self.alpha * (gain_prev ** 2 * self.gamma_prev) + \
                    (1 - self.alpha) * np.maximum(gamma - 1, 0)
            xi = np.maximum(xi_dd, self.xi_min)

        # 3. 計算對數似然比
        # Λ(k,l) = ξ/(1+ξ) · γ
        log_likelihood = xi / (1 + xi) * gamma

        # 4. 計算 SPP
        # p(k,l) = 1 / [1 + (q/(1-q))·exp(-Λ)]
        spp = 1 / (1 + (self.q / (1 - self.q)) * np.exp(-log_likelihood))

        # 保存當前值供下一幀使用
        self.xi_prev = xi
        self.gamma_prev = gamma

        return spp, xi, gamma

    def reset(self):
        """重置狀態"""
        self.xi_prev = None
        self.gamma_prev = None

    def __repr__(self):
        return (f"SppEstimator(alpha={self.alpha}, q={self.q}, "
                f"xi_min={10 * np.log10(self.xi_min):.1f} dB)")


def compute_spp_batch(
    Y_psd: np.ndarray,
    noise_psd: np.ndarray,
    alpha: float = 0.98,
    q: float = 0.5,
    xi_min_db: float = -25.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    批量計算 SPP（用於離線處理）

    參數:
        Y_psd: 帶噪語音功率譜密度 (n_frames, n_freqs)
        noise_psd: 噪聲功率譜密度 (n_frames, n_freqs) 或 (n_freqs,)
        alpha: 先驗 SNR 平滑因子
        q: 語音先驗機率
        xi_min_db: 先驗 SNR 下限 (dB)

    返回:
        spp: 語音存在機率 (n_frames, n_freqs)
        xi: 先驗 SNR (n_frames, n_freqs)
        gamma: 後驗 SNR (n_frames, n_freqs)
    """
    estimator = SppEstimator(alpha=alpha, q=q, xi_min_db=xi_min_db)

    n_frames = Y_psd.shape[0]
    n_freqs = Y_psd.shape[1]

    # 初始化輸出
    spp = np.zeros_like(Y_psd)
    xi = np.zeros_like(Y_psd)
    gamma = np.zeros_like(Y_psd)

    # 逐幀處理
    gain_prev = None
    for i in range(n_frames):
        if noise_psd.ndim == 1:
            noise_frame = noise_psd
        else:
            noise_frame = noise_psd[i]

        spp[i], xi[i], gamma[i] = estimator.estimate(
            Y_psd[i],
            noise_frame,
            gain_prev
        )

        # 簡單估計增益（用於下一幀）
        # 這裡使用 Wiener 增益作為近似
        gain_prev = xi[i] / (1 + xi[i])

    return spp, xi, gamma
