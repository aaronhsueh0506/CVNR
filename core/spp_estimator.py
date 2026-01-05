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

    v1.4.0 新增 (Phase 6):
        enable_fast_startup: 啟用快速啟動模式
        startup_frames: 快速啟動持續幀數
        alpha_startup: 快速啟動時的 alpha 值

    參考文獻:
        Cohen & Berdugo (2001): "Speech Enhancement for Non-stationary Noise Environments"
    """

    def __init__(
        self,
        alpha: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        enable_fast_startup: bool = False,
        startup_frames: int = 50,
        alpha_startup: float = 0.7
    ):
        self.alpha = alpha
        self.alpha_normal = alpha  # 保存正常模式的 alpha
        self.q = q
        self.xi_min = 10 ** (xi_min_db / 10)

        # 狀態變量（用於 Decision Directed 方法）
        self.xi_prev = None  # 上一幀的先驗 SNR
        self.gamma_prev = None  # 上一幀的後驗 SNR

        # v1.4.0: 快速啟動狀態
        self.enable_fast_startup = enable_fast_startup
        self.startup_frames = startup_frames
        self.alpha_startup = alpha_startup
        self.frame_count = 0
        self.in_startup_mode = enable_fast_startup

        # 當前使用的 alpha
        self.current_alpha = alpha_startup if enable_fast_startup else alpha

    def estimate(
        self,
        Y_psd: np.ndarray,
        noise_psd: np.ndarray,
        gain_prev: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        估計 SPP

        v1.4.0: 支持快速啟動模式，使用動態 alpha

        參數:
            Y_psd: 帶噪語音功率譜密度 (n_freqs,)
            noise_psd: 噪聲功率譜密度 (n_freqs,)
            gain_prev: 上一幀的增益（可選，用於 Decision Directed）

        返回:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
        """
        # v1.4.0: 快速啟動模式計時器
        if self.in_startup_mode:
            if self.frame_count >= self.startup_frames:
                self.in_startup_mode = False
                self.current_alpha = self.alpha_normal

        # 1. 計算後驗 SNR (a posteriori SNR)
        gamma = Y_psd / (noise_psd + 1e-10)

        # 2. 估計先驗 SNR (a priori SNR) - Decision Directed 方法
        if self.xi_prev is None or gain_prev is None:
            # 初始化：使用直接估計
            xi = np.maximum(gamma - 1, 0)
        else:
            # Decision Directed 方法（使用當前 alpha）
            # ξ(k,l) = α·[G²(k,l-1)·γ(k,l-1)] + (1-α)·max(γ(k,l)-1, 0)
            xi_dd = self.current_alpha * (gain_prev ** 2 * self.gamma_prev) + \
                    (1 - self.current_alpha) * np.maximum(gamma - 1, 0)
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

        # v1.4.0: 更新幀計數
        self.frame_count += 1

        return spp, xi, gamma

    def trigger_fast_transition(self, boost_alpha: float = 0.4):
        """
        觸發快速過渡模式（v1.4.0 新增 - Phase 6）

        用於檢測到 SPP 跳變時，快速適應新的語音段
        - 臨時降低 current_alpha
        - 部分重置 xi_prev 以加速響應

        參數:
            boost_alpha: 過渡時使用的 alpha 值（預設 0.4）
        """
        # 臨時設置低 alpha（會被 denoiser 的 boost 計時器管理）
        self.current_alpha = boost_alpha

        # 部分重置 xi_prev 以減少歷史影響
        if self.xi_prev is not None:
            # 保留 50% 的歷史信息，避免完全重置
            self.xi_prev = self.xi_prev * 0.5

    def reset(self):
        """重置狀態（v1.4.0: 包含快速啟動狀態）"""
        self.xi_prev = None
        self.gamma_prev = None

        # v1.4.0: 重置快速啟動狀態
        self.frame_count = 0
        self.in_startup_mode = self.enable_fast_startup
        self.current_alpha = self.alpha_startup if self.enable_fast_startup else self.alpha_normal

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
