"""
V3-3: PMMSE Denoiser - 感知動機 MMSE 降噪器
基於 Loizou 2005
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator
from core.gain_calculators import PmmseGainCalculator
from core.noise_change_detector import NoiseChangeDetector
from .base_denoiser import BaseDenoiser
from typing import Tuple


class PmmseDenoiser(BaseDenoiser):
    """
    版本 3-3: PMMSE 降噪器 (Perceptually Motivated MMSE with Gaussian Prior)

    基於 Loizou 2005 的感知動機 Bayesian 估計器 (Equation 12)

    核心特點:
        - 先驗分佈: Gaussian (complex Gaussian → Rayleigh 幅度分佈)
        - 成本函數: E[(|X| - |Xhat|)^2 / |X|] (Itakura-Saito 距離)
        - 感知動機的 IS 距離，更符合人耳感知特性
        - 特殊函數: Modified Bessel function I0

    與 V3/V3-2 的區別:
        - V3 (MMSE-STSA): 最小化 E[(|X| - |Xhat|)^2] (線性域)
        - V3-2 (MMSE-LSA): 最小化 E[(log|X| - log|Xhat|)^2] (對數域)
        - V3-3 (PMMSE): 最小化 E[(|X| - |Xhat|)^2 / |X|] (感知加權 IS 距離)

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
        alpha_g: float = 0.7,
        use_spp_weighting: bool = True,
        num_init_frames: int = 20,
        enable_noise_tracking: bool = True
    ):
        super().__init__(sample_rate)

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

        # 創建噪聲估計器
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

        # 創建 PMMSE 增益計算器
        self.gain_calculator = PmmseGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
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

    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
        """
        # 1. 分幀和 FFT
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        # 2. 降噪
        enhanced_magnitudes, enhanced_phases = self.denoise_spectrum(magnitudes, phases)

        # 3. 重建信號
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
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

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
        """
        n_frames = noisy_magnitude.shape[0]

        # 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

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

            # 噪聲場景變化檢測
            if self.enable_noise_tracking and self.noise_change_detector is not None:
                if self.noise_change_detector.detect(gamma, spp):
                    # 觸發快速適應
                    self.noise_estimator.trigger_fast_adaptation()
                    # 清除歷史狀態
                    self.gain_calculator.reset()
                    self.spp_estimator.reset()
                    self.gain_prev = None

            # 計算 PMMSE 增益 (Gaussian 先驗 + IS 距離)
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 增益變化率限制（防止 Musical Noise）
            # 限制幀間增益變化 ±6dB (ratio: 0.5~2.0)
            if self.gain_prev is not None:
                gain_ratio = gain / (self.gain_prev + 1e-10)
                gain_ratio = np.clip(gain_ratio, 0.5, 2.0)
                gain = self.gain_prev * gain_ratio

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # 更新噪聲估計
            is_speech = np.mean(spp) > 0.5
            self.noise_estimator.update(noisy_magnitude[i], is_speech=is_speech)

        # 相位保持不變
        enhanced_phase = noisy_phase

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
        return {
            'version': 'V3-3',
            'name': 'PMMSE',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'alpha_noise': self.noise_estimator.alpha,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_spp_weighting': self.gain_calculator.use_spp_weighting,
            'num_init_frames': self.noise_estimator.num_init_frames
        }

    def __repr__(self):
        params = self.get_params()
        spp_mode = "with SPP" if params['use_spp_weighting'] else "no SPP"
        return (f"PmmseDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB, "
                f"{spp_mode})")
