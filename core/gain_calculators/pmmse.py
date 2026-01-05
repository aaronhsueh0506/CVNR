"""
PMMSE Gain Calculator (Perceptually Motivated MMSE)
基於 Loizou 2005

參考文獻:
    Loizou, P. C. (2005).
    "Speech enhancement based on perceptually motivated Bayesian estimators
    of the magnitude spectrum."
    IEEE Transactions on Speech and Audio Processing, 13(5), 857-869.

核心差異:
    - 傳統 MMSE: 最小化 E[(|X| - |Xhat|)^2]
    - PMMSE:     最小化 E[(|X| - |Xhat|)^2 / |X|]

數學等價性:
    - PMMSE 成本函數等價於 Itakura-Saito (IS) 距離
    - IS 距離更符合人耳感知特性
    - 對小幅度分量更寬容,對大幅度分量更嚴格

實現特點:
    - 使用 Gaussian 先驗 (complex Gaussian → Rayleigh 幅度分佈)
    - 閉式解 (Equation 12): G = {sqrt(Vk) / [sqrt(pi) * gamma]} * [exp(Vk/2) / I0(Vk/2)]
    - 特殊函數: Modified Bessel function I0
    - IS 距離成本函數，更符合人耳感知特性
"""

import numpy as np
from typing import Optional

try:
    from scipy.special import i0
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy 不可用,將使用近似函數")


class PmmseGainCalculator:
    """
    感知動機 MMSE 增益估計器 (Loizou 2005 Equation 12)

    基於 Itakura-Saito 距離的 MMSE 估計:
    - 成本函數: E[(|X| - |Xhat|)^2 / |X|]
    - 假設: Gaussian 語音先驗分佈 (complex Gaussian → Rayleigh 幅度)
    - 優勢: 感知動機的成本函數，更符合人耳感知特性
    - 特殊函數: Modified Bessel function I0

    參數:
        g_min_db: 最小增益 (dB), -15 到 -25
        alpha_g: 增益時間平滑因子, 0.6-0.8
        use_spp_weighting: 是否使用 SPP 加權 (推薦 True)

    v1.4.0 新增 (Phase 6):
        enable_fast_startup: 啟用快速啟動模式
        startup_frames: 快速啟動持續幀數
        alpha_g_startup: 快速啟動時的 alpha_g 值
        alpha_g_boost: 過渡加速時的 alpha_g 值
    """

    def __init__(
        self,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        use_spp_weighting: bool = True,
        enable_fast_startup: bool = False,
        startup_frames: int = 50,
        alpha_g_startup: float = 0.4,
        alpha_g_boost: float = 0.4
    ):
        self.g_min = 10 ** (g_min_db / 10)
        self.alpha_g = alpha_g
        self.alpha_g_normal = alpha_g  # 保存正常模式的 alpha_g
        self.use_spp_weighting = use_spp_weighting
        self.gain_prev = None

        # v1.4.0: 快速啟動狀態
        self.enable_fast_startup = enable_fast_startup
        self.startup_frames = startup_frames
        self.alpha_g_startup = alpha_g_startup
        self.alpha_g_boost = alpha_g_boost
        self.frame_count = 0
        self.in_startup_mode = enable_fast_startup

        # 當前使用的 alpha_g
        self.current_alpha_g = alpha_g_startup if enable_fast_startup else alpha_g

    def calculate(
        self,
        spp: np.ndarray,
        xi: np.ndarray,
        gamma: np.ndarray,
        g_min: float = None,
        in_boost_mode: bool = False
    ) -> np.ndarray:
        """
        計算 PMMSE 增益

        Loizou 2005 Equation 12:
        G = {sqrt(Vk) / [sqrt(pi) * gamma]} * [exp(Vk/2) / I0(Vk/2)]

        其中 Vk = ξ/(1+ξ) * γ

        v1.4.0: 支持快速啟動和過渡加速模式

        參數:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
            g_min: SNR adaptive 最小增益（可選，用於動態調整）
            in_boost_mode: 是否處於過渡加速模式（Phase 6）

        返回:
            gain: 增益 (n_freqs,)
        """
        # v1.4.0: 選擇當前 alpha_g（三層優先級）
        if in_boost_mode:
            # 最高優先級：過渡加速模式
            alpha_g_current = self.alpha_g_boost
        elif self.in_startup_mode:
            # 第二優先級：快速啟動模式
            if self.frame_count >= self.startup_frames:
                self.in_startup_mode = False
                self.current_alpha_g = self.alpha_g_normal
            alpha_g_current = self.alpha_g_startup
        else:
            # 正常模式
            alpha_g_current = self.alpha_g_normal

        # 使用 SNR adaptive g_min (如果提供) 或默認值
        g_min_effective = g_min if g_min is not None else self.g_min

        # PMMSE 基礎增益 (Gaussian 先驗)
        gain_pmmse = self._pmmse_gain_gaussian(xi, gamma)

        # SPP 加權 (線性域)
        if self.use_spp_weighting:
            gain = spp * gain_pmmse + (1 - spp) * g_min_effective
        else:
            gain = gain_pmmse

        # 時間平滑（使用當前 alpha_g）
        if self.gain_prev is not None:
            gain = alpha_g_current * self.gain_prev + (1 - alpha_g_current) * gain

        self.gain_prev = gain.copy()
        gain = np.clip(gain, g_min_effective, 1.0)

        # v1.4.0: 更新幀計數
        self.frame_count += 1

        return gain

    def _pmmse_gain_gaussian(
        self,
        xi: np.ndarray,
        gamma: np.ndarray
    ) -> np.ndarray:
        """
        PMMSE 增益計算 (Loizou 2005 Equation 12)

        使用 Gaussian 先驗分佈 (complex Gaussian → Rayleigh magnitude)

        公式: G = {sqrt(Vk) / [sqrt(pi) * gamma]} * [exp(Vk/2) / I0(Vk/2)]
        其中 Vk = ξ/(1+ξ) * γ

        參數:
            xi: 先驗 SNR (a priori SNR)
            gamma: 後驗 SNR (posterior SNR)

        返回:
            gain: PMMSE 增益

        推導:
        - 假設語音 DFT 係數服從 complex Gaussian 分佈
        - 幅度譜服從 Rayleigh 分佈
        - 成本函數: E[(|X| - |Xhat|)^2 / |X|] (Itakura-Saito 距離)
        - 閉式解基於 Gaussian 先驗的 Bayesian 估計

        特殊函數:
        - I0(x): Modified Bessel function of the first kind, order 0
        """
        # 計算 Vk
        v = (xi / (1 + xi)) * gamma
        v = np.clip(v, 1e-10, 700)  # 防止 I0 數值溢出（與其他版本一致）

        v_half = v / 2.0

        # 使用修正貝塞爾函數 I0
        if SCIPY_AVAILABLE:
            i0_v_half = i0(v_half)  # Modified Bessel function
        else:
            i0_v_half = self._i0_approx(v_half)

        # Equation 12: G = sqrt(v) / [sqrt(pi) * gamma] * exp(v/2) / I0(v/2)
        sqrt_v = np.sqrt(v)
        sqrt_pi = np.sqrt(np.pi)
        exp_v_half = np.exp(v_half)

        # 防止除以零
        gamma_safe = np.maximum(gamma, 1e-10)
        i0_v_half = np.maximum(i0_v_half, 1e-10)

        gain = (sqrt_v / (sqrt_pi * gamma_safe)) * (exp_v_half / i0_v_half)

        return gain

    def _i0_approx(self, x: np.ndarray) -> np.ndarray:
        """
        修正貝塞爾函數 I0(x) 的近似

        I0(x) = Σ_{k=0}^∞ [(x/2)^(2k) / (k!)^2]

        使用級數展開（前 20 項）
        """
        result = np.ones_like(x)
        term = np.ones_like(x)
        x_half = x / 2.0

        for k in range(1, 20):
            term = term * (x_half / k) ** 2
            result += term

        return result

    def reset(self):
        """重置增益歷史（v1.4.0: 包含快速啟動狀態）"""
        self.gain_prev = None

        # v1.4.0: 重置快速啟動狀態
        self.frame_count = 0
        self.in_startup_mode = self.enable_fast_startup
        self.current_alpha_g = self.alpha_g_startup if self.enable_fast_startup else self.alpha_g_normal

    def __repr__(self):
        spp_mode = "with SPP" if self.use_spp_weighting else "no SPP"
        return (f"PmmseGainCalculator("
                f"g_min={10*np.log10(self.g_min):.1f} dB, "
                f"alpha_g={self.alpha_g}, "
                f"{spp_mode})")


if __name__ == "__main__":
    # 測試示例
    print("PMMSE 增益計算器 (Loizou 2005)")
    print("\nPMMSE vs MMSE-STSA 對比:")

    # 導入 MMSE-STSA 用於對比
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        from gain_calculators.mmse_stsa import MmseStSaGainCalculator
        HAVE_MMSE_STSA = True
    except ImportError:
        print("Warning: 無法導入 MMSE-STSA,僅測試 PMMSE")
        HAVE_MMSE_STSA = False

    # 模擬 SNR 數據
    xi = np.array([0.5, 1.0, 2.0, 5.0, 10.0])  # 先驗 SNR
    gamma = np.array([1.0, 2.0, 3.0, 6.0, 12.0])  # 後驗 SNR
    spp = np.ones_like(xi)  # 假設都是語音

    # PMMSE
    calc_pmmse = PmmseGainCalculator(use_spp_weighting=False, alpha_g=0.0)
    gain_pmmse = calc_pmmse.calculate(spp, xi, gamma)

    if HAVE_MMSE_STSA:
        # MMSE-STSA (簡化版)
        calc_stsa = MmseStSaGainCalculator(use_full_formula=False, alpha_g=0.0)
        gain_stsa = calc_stsa.calculate(spp, xi, gamma)

        # 對比
        print("\nSNR (dB) | PMMSE | MMSE-STSA | 差異 (%)")
        print("-" * 55)
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            diff = (gain_pmmse[i] - gain_stsa[i]) / gain_stsa[i] * 100
            print(f"{xi_db:7.1f} | {gain_pmmse[i]:.4f} | {gain_stsa[i]:.4f} | {diff:+7.2f}")

        print("\n觀察:")
        print("- PMMSE 通常比 MMSE-STSA 更保守 (增益更小)")
        print("- PMMSE 基於 Gaussian 先驗 + IS 距離成本函數")
        print("- PMMSE 的 IS 距離成本函數對小幅度更寬容")
    else:
        print("\nPMMSE 增益:")
        for i in range(len(xi)):
            xi_db = 10 * np.log10(xi[i])
            print(f"SNR={xi_db:5.1f} dB: Gain={gain_pmmse[i]:.4f}")

    # 測試 SPP 影響
    print("\n\nSPP 加權效果:")
    print("-" * 50)

    spp_values = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    xi_test = np.full_like(spp_values, 2.0)
    gamma_test = np.full_like(spp_values, 3.0)

    calc_pmmse_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=True, alpha_g=0.0)
    calc_pmmse_no_spp = PmmseGainCalculator(g_min_db=-20.0, use_spp_weighting=False, alpha_g=0.0)

    print("SPP | 有加權 | 無加權 | 差異")
    print("-" * 40)
    for i in range(len(spp_values)):
        g_with = calc_pmmse_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        g_without = calc_pmmse_no_spp.calculate(
            spp_values[i:i+1], xi_test[i:i+1], gamma_test[i:i+1]
        )[0]
        print(f"{spp_values[i]:.1f} | {g_with:.4f} | {g_without:.4f} | {g_with-g_without:+.4f}")

    print("\n結論:")
    print("1. PMMSE 使用 Itakura-Saito 距離,更符合感知特性")
    print("2. Gaussian 先驗假設語音 DFT 係數為 complex Gaussian")
    print("3. SPP 加權使低語音機率時增益更小 (更多抑制)")
    print("4. PMMSE 的 IS 距離對小幅度分量更寬容")
