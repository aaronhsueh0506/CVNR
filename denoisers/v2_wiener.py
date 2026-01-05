"""
V2: Wiener Filter Denoiser - Wiener 濾波降噪器
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor
from core.noise_estimators import RecursiveAverageNoiseEstimator
from core.gain_calculators import WienerGainCalculator
from core.noise_change_detector import NoiseChangeDetector  # v1.5.0 新增
from core.snr_detector import SnrDetector
from core.clean_detector import CleanDetector
from .base_denoiser import BaseDenoiser
from typing import Tuple, Optional


class WienerDenoiser(BaseDenoiser):
    """
    版本 2: Wiener 濾波降噪器

    基於最小均方誤差 (MMSE) 準則的最優濾波器

    優點:
        - 理論最優（MMSE 意義下）
        - 比頻譜減法音樂噪聲少
        - 遞歸更新噪聲估計

    缺點:
        - 仍有一定音樂噪聲
        - 需要較準確的噪聲估計

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        alpha: 噪聲平滑因子（0.9-0.95）
        min_gain: 最小增益
        num_init_frames: 初始噪聲估計幀數
        update_during_speech: 是否在語音段更新噪聲
        enable_noise_tracking: 是否啟用噪聲場景追蹤（v1.5.0）
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        alpha: float = 0.95,
        min_gain: float = 0.01,
        alpha_smooth: float = 0.8,
        num_init_frames: int = 20,
        update_during_speech: bool = False,
        enable_noise_tracking: bool = True,  # v1.5.0 新增
        snr_adaptive_config: Optional[dict] = None
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
            alpha=alpha,
            num_init_frames=num_init_frames,
            update_during_speech=update_during_speech
        )

        # 創建增益計算器
        self.gain_calculator = WienerGainCalculator(
            min_gain=min_gain,
            alpha_smooth=alpha_smooth
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

        # SNR Adaptive Processing (Phase 3)
        self.snr_adaptive_config = snr_adaptive_config or {}
        if self.snr_adaptive_config.get('enable', False):
            self.snr_detector = SnrDetector(
                smoothing_factor=self.snr_adaptive_config.get('snr_smoothing', 0.9)
            )
            self.base_g_min_db = self.snr_adaptive_config.get('base_g_min_db', -15.0)

            if self.snr_adaptive_config.get('clean_detection', False):
                self.clean_detector = CleanDetector(
                    snr_threshold=25.0,
                    confirm_frames=50
                )
            else:
                self.clean_detector = None
        else:
            self.snr_detector = None
            self.clean_detector = None
            self.base_g_min_db = None

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

            # v1.5.0: 噪聲變化檢測（V2 使用後驗 SNR 近似 SPP）
            if self.enable_noise_tracking and self.noise_change_detector is not None:
                # 計算後驗 SNR
                gamma = noisy_psd / (noise_psd + 1e-10)
                # 使用 Sigmoid 近似 SPP: spp ≈ 1 / (1 + exp(-2*(gamma-1)))
                spp_approx = 1.0 / (1.0 + np.exp(-2.0 * (gamma - 1.0)))
                avg_spp = np.mean(spp_approx)

                # 檢測噪聲變化
                if self.noise_change_detector.detect(gamma, spp_approx):
                    # 觸發快速適應
                    self.noise_estimator.trigger_fast_adaptation()
                    # 清除增益歷史
                    self.gain_calculator.reset()

            # SNR Adaptive Processing (Phase 3)
            g_min = None
            if self.snr_detector is not None:
                # 估計 SNR
                snr_db = self.snr_detector.estimate_frame_snr(noisy_psd, noise_psd)

                # Clean detection (if enabled)
                if self.clean_detector is not None:
                    is_clean = self.clean_detector.update(snr_db, noise_psd)

                # 獲取 adaptive g_min
                g_min = self.snr_detector.get_adaptive_g_min(snr_db, self.base_g_min_db)

            # 計算 Wiener 增益
            gain = self.gain_calculator.calculate(noisy_psd, noise_psd, g_min=g_min)

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 更新噪聲估計（遞歸）
            self.noise_estimator.update(noisy_magnitude[i])

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

        # Reset SNR adaptive detectors (Phase 3)
        if self.snr_detector is not None:
            self.snr_detector.snr_history = []
        if self.clean_detector is not None:
            self.clean_detector.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        return {
            'version': 'V2',
            'name': 'Wiener Filter',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            'alpha': self.noise_estimator.alpha,
            'min_gain': self.gain_calculator.min_gain,
            'num_init_frames': self.noise_estimator.num_init_frames,
            'enable_noise_tracking': self.enable_noise_tracking  # v1.5.0 新增
        }

    def __repr__(self):
        params = self.get_params()
        return (f"WienerDenoiser("
                f"alpha={params['alpha']}, min_gain={params['min_gain']})")
