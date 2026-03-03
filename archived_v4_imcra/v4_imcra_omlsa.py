"""
V4: IMCRA-OMLSA Denoiser - 產品級先進降噪器
v2.6: 添加 Human Voice Band Soft VAD 後處理
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators.imcra import ImcraNoiseEstimator
from core.gain_calculators.omlsa import OmlsaGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Tuple


class ImcraOmlsaDenoiser(BaseDenoiser):
    """
    版本 4: IMCRA-OMLSA 降噪器

    業界最先進的傳統降噪方案（Cohen, 2001-2003）

    核心組件:
        - IMCRA: 最先進的噪聲估計
        - OMLSA: 最優化的對數譜幅度估計
        - SPP: 語音存在機率

    優點:
        - 產品級效果
        - 音樂噪聲極少
        - 語音失真極低
        - 對非穩態噪聲魯棒
        - 被 WebRTC、Cisco 等商業產品使用

    缺點:
        - 計算複雜度最高
        - 需要仔細調參
        - 延遲稍高

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        alpha_s: IMCRA 頻譜平滑因子
        alpha_d: IMCRA 噪聲更新速率
        L: IMCRA 最小值窗口長度（幀數）
        delta_db: IMCRA 偏移量（dB）
        alpha_xi: 先驗 SNR 平滑因子
        q: 語音先驗機率
        xi_min_db: 先驗 SNR 下限（dB）
        g_min_db: 最小增益（dB）
        alpha_g: 增益平滑因子
        num_init_frames: 初始化幀數
        enable_noise_tracking: 是否啟用噪聲場景追蹤（v1.5.0）
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        # IMCRA 參數（Cohen 2003）
        freq_smooth_width: int = 1,  # 頻率平滑窗寬度
        alpha_s: float = 0.9,        # 時間平滑因子
        alpha_d: float = 0.85,       # 噪聲更新速率
        L: int = 96,                 # 最小值窗口長度（約 1 秒）
        V: int = 15,                 # 更新週期
        U: int = 8,                  # 子窗口數量
        delta_db: float = 5.0,       # 第一階段閾值
        delta_s_db: float = 3.0,     # 第二階段閾值
        # SPP 參數
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        # OMLSA 增益參數
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        # 初始化參數
        num_init_frames: int = 20,
        # v2.6 Soft VAD
        enable_soft_vad: bool = False
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

        # 創建 IMCRA 噪聲估計器 ⭐ 核心組件 1（Cohen 2003 兩階段實現）
        self.noise_estimator = ImcraNoiseEstimator(
            freq_smooth_width=freq_smooth_width,
            alpha_s=alpha_s,
            alpha_d=alpha_d,
            L=L,
            V=V,
            U=U,
            delta_db=delta_db,
            delta_s_db=delta_s_db,
            num_init_frames=num_init_frames
        )

        # 創建 SPP 估計器 ⭐ 核心組件 2
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # 創建 OMLSA 增益計算器 ⭐ 核心組件 3（標準 OMLSA, 對數域 SPP 加權）
        self.gain_calculator = OmlsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g
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

        這是 V4 的核心處理流程，展示了 IMCRA-OMLSA 的完整算法

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
        """
        n_frames = noisy_magnitude.shape[0]

        # 步驟 1: 初始化 IMCRA 噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # v1.5.0: 保存上一幀增強功率譜（用於正確的 DD 計算）
        enhanced_psd_prev = None

        # 步驟 2: 逐幀處理
        for i in range(n_frames):
            # 2.1 計算當前幀的功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # 2.2 估計 SPP、先驗 SNR 和後驗 SNR ⭐
            # v1.5.0: 傳入 enhanced_psd_prev 用於正確的 DD 計算
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )

            # 2.3 計算 OMLSA 增益 ⭐
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 2.4 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # 2.5 v2.6: 套用 Soft VAD 後處理
            if self.enable_soft_vad:
                enhanced_magnitude[i] = self._apply_soft_vad(enhanced_magnitude[i])

            # 2.6 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # v1.5.0: 保存增強功率譜供下一幀 DD 使用
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # 2.7 更新 IMCRA 噪聲估計 ⭐
            # IMCRA 使用 SPP 引導更新
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
            'version': 'V4',
            'name': 'IMCRA-OMLSA',
            'sample_rate': self.sample_rate,
            'frame_size_ms': self.processor.frame_size_ms,
            'frame_shift_ms': self.processor.frame_shift_ms,
            'fft_size': self.processor.fft_size,
            # IMCRA 參數
            'freq_smooth_width': self.noise_estimator.freq_smooth_width,
            'alpha_s': self.noise_estimator.alpha_s,
            'alpha_d': self.noise_estimator.alpha_d,
            'L': self.noise_estimator.L,
            'V': self.noise_estimator.V,
            'U': self.noise_estimator.U,
            'delta_db': 10 * np.log10(self.noise_estimator.delta),
            'delta_s_db': 10 * np.log10(self.noise_estimator.delta_s),
            # SPP 參數
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            # 增益參數
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'num_init_frames': self.noise_estimator.num_init_frames
        }

    def __repr__(self):
        params = self.get_params()
        return (f"ImcraOmlsaDenoiser("
                f"L={params['L']}, "
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
