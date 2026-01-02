"""
V3: MMSE-STSA Denoiser - MMSE 短時頻譜幅度估計降噪器
⭐ 重點版本：引入概率軟判決
v1.5.0: 整合 V3-1，支持 Bessel/E1 公式切換
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator
from core.gain_calculators import SppMmseGainCalculator
from core.noise_change_detector import NoiseChangeDetector  # v1.3.0 新增
from .base_denoiser import BaseDenoiser
from typing import Tuple


class SppMmseDenoiser(BaseDenoiser):
    """
    版本 3: MMSE-STSA 降噪器 (Ephraim-Malah 1984)

    基於語音存在機率 (Speech Presence Probability) 的軟判決降噪
    v1.5.0: 整合 V3-1，支持 Bessel 完整版和 E1 簡化版切換

    核心創新:
        - 使用 SPP 取代硬判決 VAD
        - Decision Directed 方法估計先驗 SNR
        - SPP 加權的 MMSE 增益
        - 時間平滑減少音樂噪聲

    優點:
        - 軟判決比硬判決更平滑
        - 音樂噪聲顯著減少
        - 語音失真很低
        - 適應性強

    缺點:
        - 計算複雜度較高
        - 需要調參

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
        use_full_formula: True=Bessel完整版, False=E1簡化版（默認，推薦）
        num_init_frames: 初始噪聲估計幀數
        enable_noise_tracking: 是否啟用噪聲場景追蹤（v1.3.0）
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
        use_full_formula: bool = False,  # v1.5.0 新增：True=Bessel完整版, False=E1簡化版
        num_init_frames: int = 20,
        enable_noise_tracking: bool = True  # v1.3.0 新增：是否啟用噪聲場景追蹤
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
            update_during_speech=False  # 不在語音段更新
        )

        # 創建 SPP 估計器 ⭐ 核心組件
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # 創建增益計算器
        self.gain_calculator = SppMmseGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_full_formula=use_full_formula  # v1.5.0 新增
        )

        # 存儲上一幀的增益（用於 Decision Directed）
        self.gain_prev = None

        # v1.3.0: 噪聲場景變化檢測器
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

        這是 V3 的核心處理流程，展示了 SPP-MMSE 的完整算法

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
        """
        n_frames = noisy_magnitude.shape[0]

        # 步驟 1: 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # 步驟 2: 逐幀處理
        for i in range(n_frames):
            # 2.1 計算當前幀的功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # 2.2 估計 SPP、先驗 SNR 和後驗 SNR ⭐ 核心步驟
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev
            )

            # v1.3.0: 噪聲場景變化檢測
            if self.enable_noise_tracking and self.noise_change_detector is not None:
                # 使用 posterior SNR (gamma) 檢測噪聲變化
                if self.noise_change_detector.detect(gamma, spp):
                    # 觸發快速適應
                    self.noise_estimator.trigger_fast_adaptation()
                    # 清除歷史狀態
                    self.gain_calculator.reset()
                    self.spp_estimator.reset()
                    self.gain_prev = None

            # 2.3 計算 SPP 加權的 MMSE 增益 ⭐ 核心步驟
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 2.4 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 2.5 保存增益供下一幀使用（Decision Directed）
            self.gain_prev = gain.copy()

            # 2.6 更新噪聲估計
            # 使用 SPP 作為語音活動指示（軟判決）
            is_speech = np.mean(spp) > 0.5  # 簡單閾值
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
        # v1.3.0: 重置噪聲變化檢測器
        if self.enable_noise_tracking and self.noise_change_detector is not None:
            self.noise_change_detector.reset()

    def get_params(self) -> dict:
        """獲取參數"""
        return {
            'version': 'V3',
            'name': 'MMSE-STSA',
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
            'use_full_formula': self.gain_calculator.use_full_formula,
            'num_init_frames': self.noise_estimator.num_init_frames,
            'enable_noise_tracking': self.enable_noise_tracking
        }

    def get_spp_statistics(self) -> dict:
        """
        獲取 SPP 統計信息（用於分析）

        返回:
            stats: SPP 統計字典
        """
        if self.spp_estimator.xi_prev is None:
            return {'status': 'not_initialized'}

        return {
            'status': 'initialized',
            'avg_xi_db': 10 * np.log10(np.mean(self.spp_estimator.xi_prev) + 1e-10),
            'avg_gamma_db': 10 * np.log10(np.mean(self.spp_estimator.gamma_prev) + 1e-10),
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min)
        }

    def __repr__(self):
        params = self.get_params()
        return (f"SppMmseDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"q={params['q']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
