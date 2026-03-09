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
from core.spp_estimator import SppEstimator  # v2.2: 正確的 Bayesian SPP
from .base_denoiser import BaseDenoiser
from typing import Tuple


class WienerDenoiser(BaseDenoiser):
    """
    版本 2: Wiener 濾波降噪器

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    v2.2 新增:
        - 使用正確的 Bayesian SPP 估計器（取代 Sigmoid 近似）
        - 修正 DD 公式：使用上一幀增強後的幅度和當前噪聲估計
        - ξ(l) = α·[|X̂(l-1)|² / N(l)] + (1-α)·max(γ(l)-1, 0)

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
        frame_size_ms: int = 32,
        frame_shift_ms: int = 16,
        fft_size: int = 512,
        # v2.1: 噪聲估計方法選擇
        noise_method: str = 'recursive_average',  # 'recursive_average' 或 'mcra'
        alpha: float = 0.95,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
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

        # v2.2: 正確的 Bayesian SPP 估計器（取代 Sigmoid 近似）
        self.spp_estimator = SppEstimator(
            alpha=alpha_dd,  # 使用 DD 平滑因子
            q=0.5,           # 語音先驗機率
            xi_min_db=-25.0  # 最小先驗 SNR
        )

        # v2.2: 保存上一幀增強後的幅度（用於正確 DD 公式）
        self.enhanced_mag_prev = None

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

            # v2.2: 使用正確的 Bayesian SPP（取代 Sigmoid 近似）
            # SPP 估計器使用 DD 方法計算 xi，返回正確的語音存在機率
            if self.gain_calculator.prev_gain is not None:
                prev_gain = self.gain_calculator.prev_gain
            else:
                prev_gain = np.ones_like(noisy_psd)  # 初始幀使用 1.0

            spp, xi_spp, gamma = self.spp_estimator.estimate(noisy_psd, noise_psd, prev_gain)

            # v2.2: 計算 Wiener 增益，傳遞上一幀增強後的幅度
            gain = self.gain_calculator.calculate(
                noisy_psd,
                noise_psd,
                enhanced_mag_prev=self.enhanced_mag_prev
            )

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # v2.2: 保存當前幀增強後的幅度（供下一幀 DD 使用）
            self.enhanced_mag_prev = enhanced_magnitude[i].copy()

            # v2.0: 更新噪聲估計（使用 SPP 軟判決）
            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.gain_calculator.reset()
        # v2.2: 重置 SPP 估計器和增強幅度歷史
        self.spp_estimator.reset()
        self.enhanced_mag_prev = None

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
