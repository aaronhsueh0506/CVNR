"""
V2: Wiener Filter Denoiser - Wiener 濾波降噪器
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import WienerGainCalculator
from core.noise_change_detector import NoiseChangeDetector  # v1.5.0 新增
from .base_denoiser import BaseDenoiser
from typing import Tuple


class WienerDenoiser(BaseDenoiser):
    """
    版本 2: Wiener 濾波降噪器

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    v2.1 新增:
        - 支持 MCRA 噪聲估計（語音段自動減少噪聲更新）
        - 改善對非平穩噪聲的適應能力

    v2.0 新增:
        - Decision Directed (DD) 方法估計先驗 SNR
        - 顯著減少音樂噪聲

    優點:
        - 理論最優（MMSE 意義下）
        - 比頻譜減法音樂噪聲少
        - MCRA 噪聲估計（語音時不更新噪聲）
        - DD 方法進一步減少音樂噪聲

    缺點:
        - 需要較準確的噪聲估計
        - DD 方法可能略增加語音失真

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        noise_method: 噪聲估計方法 ('recursive_average' 或 'mcra')
        alpha: 噪聲平滑因子（recursive_average 用）
        min_gain: 最小增益
        num_init_frames: 初始噪聲估計幀數
        update_during_speech: 是否在語音段更新噪聲（recursive_average 用）
        enable_noise_tracking: 是否啟用噪聲場景追蹤（v1.5.0）
        use_dd: 是否使用 Decision Directed 方法（v2.0）
        alpha_dd: DD 平滑因子（v2.0）
        # MCRA 參數 (v2.1)
        alpha_s: MCRA 時間平滑因子
        alpha_d: MCRA 噪聲更新速率
        alpha_p: MCRA SPP 平滑因子
        L: MCRA 最小值窗口長度
        delta_db: MCRA 偏差補償 (dB)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        # v2.1: 噪聲估計方法選擇
        noise_method: str = 'recursive_average',  # 'recursive_average' 或 'mcra'
        alpha: float = 0.95,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
        enable_noise_tracking: bool = True,  # v1.5.0 新增
        # v2.0 DD 參數
        use_dd: bool = True,        # 是否使用 Decision Directed 方法
        alpha_dd: float = 0.98,     # DD 平滑因子
        # v2.1 MCRA 參數
        alpha_s: float = 0.9,       # MCRA 時間平滑因子
        alpha_d: float = 0.85,      # MCRA 噪聲更新速率
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

        # v2.1: 根據配置選擇噪聲估計器
        if noise_method == 'mcra':
            self.noise_estimator = McraNoiseEstimator(
                alpha_s=alpha_s,
                alpha_d=alpha_d,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames
            )
        else:
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha,
                num_init_frames=num_init_frames,
                update_during_speech=update_during_speech
            )

        # 創建增益計算器（v2.0: 添加 DD 參數）
        self.gain_calculator = WienerGainCalculator(
            min_gain=min_gain,
            alpha_smooth=alpha_smooth,
            use_dd=use_dd,
            alpha_dd=alpha_dd
        )

        # v1.5.0: 噪聲場景變化檢測器
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

        # 對每一幀應用 Wiener 濾波
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        for i in range(n_frames):
            # 計算當前幀的功率譜
            noisy_psd = noisy_magnitude[i] ** 2

            # 獲取噪聲估計
            noise_psd = self.noise_estimator.noise_psd

            # v2.0: 計算後驗 SNR 和 SPP 近似（用於軟判決噪聲更新）
            gamma = noisy_psd / (noise_psd + 1e-10)
            # 使用 Sigmoid 近似 SPP: spp ≈ 1 / (1 + exp(-2*(gamma-1)))
            spp_approx = 1.0 / (1.0 + np.exp(-2.0 * (gamma - 1.0)))

            # v1.5.0: 噪聲變化檢測
            if self.enable_noise_tracking and self.noise_change_detector is not None:
                # 檢測噪聲變化
                if self.noise_change_detector.detect(gamma, spp_approx):
                    # 觸發快速適應
                    self.noise_estimator.trigger_fast_adaptation()
                    # 清除增益歷史
                    self.gain_calculator.reset()

            # 計算 Wiener 增益
            gain = self.gain_calculator.calculate(noisy_psd, noise_psd)

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # v2.0: 更新噪聲估計（使用 SPP 軟判決）
            self.noise_estimator.update(noisy_magnitude[i], spp=spp_approx)

        # 相位保持不變
        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.gain_calculator.reset()
        # v1.5.0: 重置噪聲變化檢測器
        if self.enable_noise_tracking and self.noise_change_detector is not None:
            self.noise_change_detector.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        params = {
            'version': 'V2',
            'name': 'Wiener Filter',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'min_gain': self.gain_calculator.min_gain,
            'alpha_smooth': self.gain_calculator.alpha_smooth,
            'num_init_frames': self.noise_estimator.num_init_frames,
            'enable_noise_tracking': self.enable_noise_tracking,
            # v2.0 DD 參數
            'use_dd': self.gain_calculator.use_dd,
            'alpha_dd': self.gain_calculator.alpha_dd
        }
        # v2.1: 根據噪聲估計方法添加對應參數
        if self.noise_method == 'mcra':
            params.update({
                'alpha_s': self.noise_estimator.alpha_s,
                'alpha_d': self.noise_estimator.alpha_d,
                'alpha_p': self.noise_estimator.alpha_p,
                'L': self.noise_estimator.L
            })
        else:
            params['alpha'] = self.noise_estimator.alpha
        return params

    def __repr__(self):
        params = self.get_params()
        return (f"WienerDenoiser("
                f"alpha={params['alpha']}, min_gain={params['min_gain']})")
