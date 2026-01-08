"""
V3-4: Laplacian MAP Denoiser - Super-Gaussian Joint MAP 降噪器
基於 Lotter & Vary 2005
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import LaplacianMmseGainCalculator
from core.noise_change_detector import NoiseChangeDetector
from .base_denoiser import BaseDenoiser
from typing import Tuple


class LaplacianMmseDenoiser(BaseDenoiser):
    """
    版本 3-4: Laplacian MAP 降噪器 (Lotter & Vary 2005)

    公式:
        G_Lap = (u + sqrt(u² + 2(1+ξ)/γ)) / (2(1+ξ))
        u = ξ + 1/(2γ) - 1

    核心特點:
        - Super-Gaussian Joint MAP 估計器
        - 無需 Bessel 函數，數值穩定
        - 大 SNR 時增益自然趨近 1.0
        - 公式簡潔，計算效率高

    與 V3-1/V3-2/V3-3 的區別:
        - V3 (MMSE-STSA):   Gaussian 先驗, 線性域 MSE
        - V3-2 (MMSE-LSA):  Gaussian 先驗, 對數域 MSE
        - V3-3 (PMMSE):     Wolfe & Godsill β=0.5
        - V3-4 (Lap-MAP):   Lotter & Vary Super-Gaussian MAP

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
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
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        alpha_noise: float = 0.95,
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -20.0,
        alpha_g: float = 0.5,
        beta_laplacian: float = 1.0,
        use_spp_weighting: bool = True,
        num_init_frames: int = 20,
        enable_noise_tracking: bool = True,
        # v2.0 MCRA 噪聲估計參數
        noise_method: str = 'recursive_average',  # 'recursive_average' 或 'mcra'
        alpha_s: float = 0.9,       # MCRA 時間平滑因子
        alpha_p: float = 0.2,       # MCRA SPP 平滑因子
        L: int = 96,                # MCRA 最小值窗口長度
        delta_db: float = 5.0       # MCRA 偏差補償 (dB)
    ):
        super().__init__(sample_rate)
        self.noise_method = noise_method

        # 創建處理器
        self.processor = FrameProcessor(
            sample_rate=sample_rate,
            frame_size_ms=frame_size_ms,
            frame_shift_ms=frame_shift_ms,
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
                num_init_frames=num_init_frames
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

        # 創建 Laplacian-MMSE 增益計算器 (Chen & Loizou)
        self.gain_calculator = LaplacianMmseGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            beta_laplacian=beta_laplacian,
            use_spp_weighting=use_spp_weighting
        )

        # 存儲上一幀的增益（Decision Directed）
        self.gain_prev = None

        # 噪聲場景變化檢測器
        self.enable_noise_tracking = enable_noise_tracking
        if enable_noise_tracking:
            self.noise_change_detector = NoiseChangeDetector(
                history_length=20,
                energy_ratio_high=2.0,
                energy_ratio_low=0.5,
                spp_threshold=0.3,
                confirmation_frames=3,
                cooldown_frames=50
            )
        else:
            self.noise_change_detector = None

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

        Laplacian-MMSE 核心流程:
        1. 估計噪聲功率譜
        2. 計算 SPP, 先驗/後驗 SNR
        3. 使用 Laplacian 先驗計算 MMSE 增益
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

        # 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # 初始化 SPP 歷史記錄
        spp_history = [] if return_spp else None

        # 逐幀處理
        for i in range(n_frames):
            # 計算功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # 估計 SPP、先驗 SNR 和後驗 SNR
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev
            )

            # 保存 SPP 數據 (用於可視化)
            if return_spp:
                spp_history.append(spp.copy())

            # 噪聲場景變化檢測
            if self.enable_noise_tracking and self.noise_change_detector is not None:
                if self.noise_change_detector.detect(gamma, spp):
                    # 觸發快速適應
                    self.noise_estimator.trigger_fast_adaptation()
                    # 清除歷史狀態
                    self.gain_calculator.reset()
                    self.spp_estimator.reset()
                    self.gain_prev = None

            # 計算 Laplacian-MMSE 增益
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # 更新噪聲估計（v2.0: 使用 SPP 軟判決）
            # SPP 高（語音）→ 更新慢，SPP 低（噪聲）→ 正常更新
            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        if return_spp:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history)
        else:
            return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None
        if self.enable_noise_tracking and self.noise_change_detector is not None:
            self.noise_change_detector.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        params = {
            'version': 'V3-4',
            'name': 'Laplacian-MMSE',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'beta_laplacian': self.gain_calculator.beta_laplacian,
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
        return (f"LaplacianMmseDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB, "
                f"beta={params['beta_laplacian']})")
