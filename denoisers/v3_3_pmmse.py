"""
V3-3: PMMSE Denoiser - 感知動機 MMSE 降噪器
基於 Wolfe & Godsill 2003 (β=0.5)
v2.6: 添加 Human Voice Band Soft VAD 後處理
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import PmmseGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Optional
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
)


class PmmseDenoiser(BaseDenoiser):
    """
    版本 3-3: PMMSE 降噪器 (Wolfe & Godsill β=0.5)

    公式:
        G_PM = sqrt(v) / (sqrt(π) · γ) · exp(v/2) / I_0(v/2)
             = sqrt(v) / (sqrt(π) · γ) · 1 / i0e(v/2)

    其中:
        v = ξ/(1+ξ) · γ
        i0e: 指數縮放的 Modified Bessel function (避免數值溢出)

    核心特點:
        - 感知動機的成本函數
        - β=0.5 特例解析解
        - 使用 scipy.special.i0e 避免數值溢出

    與 V3/V3-2 的區別:
        - V3 (MMSE-STSA): 最小化 E[(|X| - |Xhat|)^2] (線性域)
        - V3-2 (MMSE-LSA): 最小化 E[(log|X| - log|Xhat|)^2] (對數域)
        - V3-3 (PMMSE): Wolfe & Godsill β=0.5 感知動機估計

    參數:
        sample_rate: 採樣率
        frame_size: 幀長（samples）
        frame_shift: 幀移（samples）
        fft_size: FFT 點數
        alpha_noise: 噪聲平滑因子
        alpha_xi: 先驗 SNR 平滑因子（0.92-0.98）
        q: 語音先驗機率（通常 0.5）
        xi_min_db: 先驗 SNR 下限（dB）
        g_min_db: 最小增益（dB）
        alpha_g: 增益時間平滑因子
        use_spp_weighting: 是否使用 SPP 加權（推薦 True）
        num_init_frames: 初始噪聲估計幀數
        enable_noise_tracking: 是否啟用噪聲場景追蹤
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        alpha_noise: float = 0.95,
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -40.0,
        alpha_g: float = 0.7,
        use_spp_weighting: bool = True,
        num_init_frames: int = 20,
        # v2.0 MCRA 噪聲估計參數
        noise_method: str = 'recursive_average',  # 'recursive_average' 或 'mcra'
        alpha_s: float = 0.9,       # MCRA 時間平滑因子
        alpha_p: float = 0.2,       # MCRA SPP 平滑因子
        L: int = 96,                # MCRA 最小值窗口長度
        delta_db: float = 5.0,      # MCRA 偏差補償 (dB)
        broadband_threshold: float = 0.8,  # 寬頻場景轉換偵測閾值
        scene_change_threshold_db: float = 10.0,  # 場景轉換偵測閾值 (dB)
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        # IMCRA/MCRA mode: True = IMCRA (use OM-LSA posterior for noise gate,
        # default for standalone NR); False = plain MCRA (use in AEC pipeline
        # to prevent residual-echo from freezing noise tracking).
        mcra_accept_external_spp: bool = True,
    ):
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        alpha_noise = retime_ema_alpha(alpha_noise, sample_rate, frame_shift)
        alpha_xi = retime_ema_alpha(alpha_xi, sample_rate, frame_shift)
        alpha_g = retime_ema_alpha(alpha_g, sample_rate, frame_shift)
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        L = retime_frame_count(L, sample_rate, frame_shift)
        num_init_frames = retime_frame_count(
            num_init_frames, sample_rate, frame_shift
        )
        scene_change_min_frames = retime_frame_count(
            scene_change_min_frames, sample_rate, frame_shift
        )

        # 創建處理器
        self.processor = FrameProcessor(
            sample_rate=sample_rate,
            frame_size=frame_size,
            frame_shift=frame_shift,
            fft_size=fft_size,
            window_type='hanning'
        )

        self.reconstructor = Reconstructor(
            fft_size=fft_size,
            frame_shift=self.processor.frame_shift,
            window=self.processor.window
        )

        # 創建噪聲估計器（根據配置選擇）
        if noise_method == 'mcra':
            self.noise_estimator = McraNoiseEstimator(
                alpha_s=alpha_s,
                alpha_d=alpha_noise,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames,
                broadband_threshold=broadband_threshold,
                scene_change_threshold_db=scene_change_threshold_db,
                scene_change_min_frames=scene_change_min_frames,
                scene_change_blend=scene_change_blend,
                accept_external_spp=mcra_accept_external_spp,
            )
        else:
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha_noise,
                num_init_frames=num_init_frames,
                update_during_speech=False
            )

        # 創建 SPP 估計器
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # 創建 PMMSE 增益計算器 (Wolfe & Godsill β=0.5)
        self.gain_calculator = PmmseGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_spp_weighting=use_spp_weighting
        )

        # 存儲上一幀的增益（Decision Directed）
        self.gain_prev = None

    def denoise(self, noisy_signal: np.ndarray, return_spp: bool = False):
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)
            return_spp: 是否返回 SPP 歷史數據 (用於可視化)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
            spp_history: SPP 歷史數據 (n_frames, n_freqs) - 僅當 return_spp=True
        """
        # 1. 分幀和 FFT
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        # 2. 降噪
        result = self.denoise_spectrum(magnitudes, phases, return_spp=return_spp)
        if return_spp:
            enhanced_magnitudes, enhanced_phases, spp_history = result
        else:
            enhanced_magnitudes, enhanced_phases = result

        # 3. 重建信號
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        if return_spp:
            return enhanced_signal, spp_history
        else:
            return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False
    ):
        """
        在頻域進行降噪

        PMMSE 核心流程:
        1. 估計噪聲功率譜
        2. 計算 SPP, 先驗/後驗 SNR
        3. 使用 Itakura-Saito 距離最小化計算增益
        4. 應用增益到帶噪幅度譜

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)
            return_spp: 是否返回 SPP 歷史數據

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
            spp_history: SPP 歷史數據 (n_frames, n_freqs) - 僅當 return_spp=True
        """
        n_frames = noisy_magnitude.shape[0]
        # Reset state so consecutive calls on different audio files start clean.
        self.reset()

        # 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # 初始化 SPP 歷史記錄
        spp_history = [] if return_spp else None

        # v1.5.0: 保存上一幀增強功率譜（用於正確的 DD 計算）
        enhanced_psd_prev = None

        # 逐幀處理
        for i in range(n_frames):
            # 計算功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # 估計 SPP、先驗 SNR 和後驗 SNR
            # v1.5.0: 傳入 enhanced_psd_prev 用於正確的 DD 計算
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )

            # 保存 SPP 數據 (用於可視化)
            if return_spp:
                spp_history.append(spp.copy())

            # 計算 PMMSE 增益 (Gaussian 先驗 + IS 距離)
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 增益變化率限制（防止 Musical Noise）
            # v1.5.0: 放寬上限以支持爆破音 (-6dB ~ +12dB)
            if self.gain_prev is not None:
                gain_ratio = gain / (self.gain_prev + 1e-10)
                gain_ratio = np.clip(gain_ratio, 0.5, 4.0)  # -6dB ~ +12dB
                gain = self.gain_prev * gain_ratio

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # v2.6: 套用 Soft VAD 後處理（使用 SPP 作為 VAD 指標）
            # 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # v1.5.0: 保存增強功率譜供下一幀 DD 使用
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # 更新噪聲估計（v2.0: 使用 SPP 軟判決）
            # SPP 高（語音）→ 更新慢，SPP 低（噪聲）→ 正常更新
            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        if return_spp:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history)
        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None

    def get_params(self) -> dict:
        """獲取參數"""
        params = {
            'version': 'V3-3',
            'name': 'PMMSE',
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 20 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_spp_weighting': self.gain_calculator.use_spp_weighting,
            'num_init_frames': self.noise_estimator.num_init_frames
        }
        if self.noise_method == 'mcra':
            params['alpha_s'] = self.noise_estimator.alpha_s
            params['alpha_d'] = self.noise_estimator.alpha_d
            params['alpha_p'] = self.noise_estimator.alpha_p
            params['L'] = self.noise_estimator.L
        else:
            params['alpha_noise'] = self.noise_estimator.alpha
        return params

    def __repr__(self):
        params = self.get_params()
        spp_mode = "with SPP" if params['use_spp_weighting'] else "no SPP"
        return (f"PmmseDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB, "
                f"{spp_mode})")
