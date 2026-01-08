"""
Wiener Filter Gain Calculator - Wiener 濾波增益計算器
用於 V2

v2.0: 添加 Decision Directed (DD) 方法估計先驗 SNR
"""

import numpy as np


class WienerGainCalculator:
    """
    Wiener 濾波增益計算

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    公式:
        H(k) = ξ(k) / (1 + ξ(k))
        其中 ξ(k) = 先驗 SNR (a priori SNR)

    先驗 SNR 估計方法:
        - ML 估計: ξ = max(γ - 1, 0)，其中 γ = Y²/N (後驗 SNR)
        - DD 估計: ξ(l) = α·G²(l-1)·γ(l-1) + (1-α)·max(γ(l)-1, 0)

    v2.0 新增:
        - use_dd: 是否使用 Decision Directed 方法
        - alpha_dd: DD 平滑因子 (0.92-0.98)

    參數:
        min_gain: 最小增益，防止過度抑制
        alpha_smooth: 增益時間平滑因子，0.0-1.0（默認 0.8）
                     - 用於減少 musical noise
                     - 越大越平滑，但可能降低反應速度
        use_dd: 是否使用 Decision Directed 方法（默認 True）
        alpha_dd: DD 平滑因子，0.0-1.0（默認 0.98）
                 - 越大時間平滑越強，音樂噪聲越少
                 - 但可能略增加語音失真

    參考文獻:
        Ephraim, Y. & Malah, D. (1984). "Speech enhancement using a minimum
        mean-square error short-time spectral amplitude estimator."
        IEEE Trans. ASSP, 32(6), 1109-1121.
    """

    def __init__(
        self,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        use_dd: bool = True,
        alpha_dd: float = 0.98
    ):
        self.min_gain = min_gain
        self.alpha_smooth = alpha_smooth
        self.use_dd = use_dd
        self.alpha_dd = alpha_dd

        # 狀態變量
        self.prev_gain = None   # 前一幀的增益
        self.prev_gamma = None  # 前一幀的後驗 SNR（DD 方法需要）
        self.prev_xi = None     # 前一幀的先驗 SNR（可選，用於診斷）

    def calculate(
        self,
        noisy_psd: np.ndarray,
        noise_psd: np.ndarray,
        g_min: float = None
    ) -> np.ndarray:
        """
        計算 Wiener 濾波增益

        v2.0: 支持 Decision Directed 方法

        參數:
            noisy_psd: 帶噪語音功率譜密度 (n_freqs,)
            noise_psd: 噪聲功率譜密度 (n_freqs,)
            g_min: SNR adaptive 最小增益（可選，用於動態調整）

        返回:
            gain: Wiener 增益 (n_freqs,)
        """
        # 使用 SNR adaptive g_min (如果提供) 或默認 min_gain
        min_gain_effective = g_min if g_min is not None else self.min_gain

        # 1. 計算後驗 SNR (a posteriori SNR)
        # γ = Y² / N
        gamma = noisy_psd / (noise_psd + 1e-10)

        # 2. 估計先驗 SNR (a priori SNR)
        if self.use_dd and self.prev_gain is not None and self.prev_gamma is not None:
            # Decision Directed 方法 (Ephraim & Malah 1984)
            # ξ(l) = α·G²(l-1)·γ(l-1) + (1-α)·max(γ(l)-1, 0)
            xi_ml = np.maximum(gamma - 1, 0)  # ML 估計部分
            xi = self.alpha_dd * (self.prev_gain ** 2 * self.prev_gamma) + \
                 (1 - self.alpha_dd) * xi_ml
            xi = np.maximum(xi, 1e-10)  # 防止除零
        else:
            # ML 估計（初始化或禁用 DD）
            # ξ_ML = max(γ - 1, 0) = max(Y² - N, 0) / N
            xi = np.maximum(gamma - 1, 0)

        # 3. Wiener 增益
        # H = ξ / (1 + ξ)
        gain = xi / (1 + xi + 1e-10)

        # 4. 應用最小增益
        gain = np.maximum(gain, min_gain_effective)

        # 5. 限制增益範圍 [0, 1]
        gain = np.clip(gain, 0.0, 1.0)

        # 6. 時間平滑（可選，與 DD 互補）
        if self.prev_gain is not None and self.alpha_smooth > 0:
            gain = self.alpha_smooth * self.prev_gain + (1 - self.alpha_smooth) * gain

        # 7. 保存狀態供下一幀使用
        self.prev_gain = gain.copy()
        self.prev_gamma = gamma.copy()
        self.prev_xi = xi.copy()

        return gain

    def reset(self):
        """重置增益計算器狀態"""
        self.prev_gain = None
        self.prev_gamma = None
        self.prev_xi = None

    def __repr__(self):
        dd_str = f", DD(α={self.alpha_dd})" if self.use_dd else ""
        return f"WienerGainCalculator(min_gain={self.min_gain}{dd_str})"
