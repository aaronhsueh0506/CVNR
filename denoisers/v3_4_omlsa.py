"""
V3-4: OMLSA-MCRA Denoiser

基於 MCRA 噪聲估計的 OMLSA 增益計算器

v2.6 特點:
    - MCRA 噪聲估計（含瞬態偵測 eta）
    - OMLSA 增益計算
    - SPP 語音存在機率
    - Human Voice Band Soft VAD 後處理
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators.mcra import McraNoiseEstimator
from core.gain_calculators.omlsa import OmlsaGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Tuple


class OmlsaMcraDenoiser(BaseDenoiser):
    """
    版本 3-4: OMLSA-MCRA 降噪器

    使用 MCRA 噪聲估計搭配 OMLSA 增益計算

    核心組件:
        - MCRA: 最小值控制遞歸平均噪聲估計（含瞬態偵測）
        - OMLSA: 最優化的對數譜幅度估計
        - SPP: 語音存在機率
        - Soft VAD: 人聲頻帶軟 VAD 後處理

    優點:
        - 比 V3-3 更低的音樂噪聲
        - 語音失真低
        - 瞬態偵測可加速噪聲場景適應

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        alpha_s: MCRA 時間平滑因子
        alpha_d: MCRA 噪聲更新速率
        alpha_p: MCRA SPP 平滑因子
        L: MCRA 最小值窗口長度（幀數）
        delta_db: MCRA 偏移量（dB）
        alpha_xi: 先驗 SNR 平滑因子
        q: 語音先驗機率
        xi_min_db: 先驗 SNR 下限（dB）
        g_min_db: 最小增益（dB）
        alpha_g: 增益平滑因子
        num_init_frames: 初始化幀數
        enable_soft_vad: 是否啟用 Soft VAD 後處理
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        # MCRA 參數
        alpha_s: float = 0.9,        # 時間平滑因子
        alpha_d: float = 0.85,       # 噪聲更新速率
        alpha_p: float = 0.2,        # SPP 平滑因子
        L: int = 96,                 # 最小值窗口長度（約 1 秒）
        delta_db: float = 5.0,       # 語音檢測閾值
        # SPP 參數
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        # OMLSA 增益參數
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        # 初始化參數
        num_init_frames: int = 20,
        use_linear_spp_weighting: bool = False,
        # Soft VAD
        enable_soft_vad: bool = True
    ):
        super().__init__(sample_rate, n_fft=fft_size)

        self.enable_soft_vad = enable_soft_vad

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

        # 創建 MCRA 噪聲估計器（含瞬態偵測 v2.6）
        self.noise_estimator = McraNoiseEstimator(
            alpha_s=alpha_s,
            alpha_d=alpha_d,
            alpha_p=alpha_p,
            L=L,
            delta_db=delta_db,
            num_init_frames=num_init_frames
        )

        # 創建 SPP 估計器
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # 創建 OMLSA 增益計算器
        self.gain_calculator = OmlsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_linear_spp_weighting=use_linear_spp_weighting
        )

        # 存儲上一幀的增益
        self.gain_prev = None

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

        # 步驟 1: 初始化 MCRA 噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # 保存上一幀增強功率譜（用於 DD 計算）
        enhanced_psd_prev = None

        # 步驟 2: 逐幀處理
        for i in range(n_frames):
            # 2.1 計算當前幀的功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # 2.2 估計 SPP、先驗 SNR 和後驗 SNR
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )

            # 2.3 計算 OMLSA 增益
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 2.4 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 2.5 v2.6: 套用 Soft VAD 後處理
            if self.enable_soft_vad:
                enhanced_magnitude[i] = self._apply_soft_vad(enhanced_magnitude[i])

            # 2.6 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # 保存增強功率譜供下一幀 DD 使用
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # 2.7 更新 MCRA 噪聲估計（使用 SPP 引導）
            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        return enhanced_magnitude, enhanced_phase

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None
        self._reset_vad()

    def get_params(self) -> dict:
        """獲取參數"""
        return {
            'version': 'V3-4',
            'name': 'OMLSA-MCRA',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            # MCRA 參數
            'alpha_s': self.noise_estimator.alpha_s,
            'alpha_d': self.noise_estimator.alpha_d,
            'alpha_p': self.noise_estimator.alpha_p,
            'L': self.noise_estimator.L,
            'delta_db': 10 * np.log10(self.noise_estimator.delta),
            # SPP 參數
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            # 增益參數
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'num_init_frames': self.noise_estimator.num_init_frames,
            'enable_soft_vad': self.enable_soft_vad
        }

    def __repr__(self):
        params = self.get_params()
        return (f"OmlsaMcraDenoiser("
                f"L={params['L']}, "
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
