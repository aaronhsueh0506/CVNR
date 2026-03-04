"""
V4: IMCRA + OMLSA Denoiser
Cohen (2003) Improved Minima Controlled Recursive Averaging +
Cohen (2002) Optimally Modified Log-Spectral Amplitude

核心改進（相對於 V3-2 MCRA + MMSE-LSA）：
    - IMCRA 兩階段噪聲估計：頻率平滑 + 條件平滑，噪聲估計更精確
    - 語音 onset 保護更好（條件平滑排除語音 bin）
    - OMLSA 對數域 SPP 加權（與 MMSE-LSA + SPP weighting 數學等價）
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import ImcraNoiseEstimator
from core.gain_calculators import OmlsaGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Tuple


class ImcraOmlsaDenoiser(BaseDenoiser):
    """
    版本 4: IMCRA + OMLSA 降噪器

    基於 Cohen (2003) IMCRA 噪聲估計 + Cohen (2002) OMLSA 增益計算

    架構:
        - IMCRA: 兩階段最小值追蹤（頻率平滑 + 條件平滑）
        - SppEstimator: Bayesian Decision-Directed SPP（用於增益計算）
        - OMLSA: 對數域 SPP 加權增益

    SPP 流程:
        - Bayesian SPP → OMLSA 增益計算
        - IMCRA 內部 SPP → 噪聲 PSD 更新（獨立於外部 SPP）

    參數:
        sample_rate: 採樣率
        frame_size_ms: 幀長（毫秒）
        frame_shift_ms: 幀移（毫秒）
        fft_size: FFT 點數
        freq_smooth_width: IMCRA 頻率平滑窗寬度（單側）
        alpha_s: 時間平滑因子
        alpha_d: 噪聲更新基礎速率
        L: 最小值追蹤窗口長度（幀）
        V: 子窗口更新週期（幀）
        U: 子窗口數量
        delta_db: 第一階段偏差補償（dB）
        delta_s_db: 第二階段閾值（dB）
        num_init_frames: 初始噪聲估計幀數
        alpha_xi: 先驗 SNR 平滑因子
        q: 語音先驗機率
        xi_min_db: 先驗 SNR 下限（dB）
        g_min_db: 最小增益（dB）
        alpha_g: 增益時間平滑因子
        use_asymmetric_smoothing: 是否使用非對稱平滑
        alpha_attack: Attack 平滑因子
        enable_soft_vad: 是否啟用 Soft VAD 後處理
        vad_method: VAD 方法
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size_ms: int = 20,
        frame_shift_ms: int = 10,
        fft_size: int = 512,
        # IMCRA 噪聲估計參數
        freq_smooth_width: int = 1,
        alpha_s: float = 0.9,
        alpha_d: float = 0.7,
        L: int = 48,
        V: int = 8,
        U: int = 6,
        delta_db: float = 10.0,
        delta_s_db: float = 3.0,
        num_init_frames: int = 20,
        # SPP 參數（Bayesian，用於增益計算）
        alpha_xi: float = 0.88,
        q: float = 0.50,
        xi_min_db: float = -20.0,
        # OMLSA 增益參數
        g_min_db: float = -12.5,
        alpha_g: float = 0.92,
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        # Soft VAD
        enable_soft_vad: bool = False,
        vad_method: str = 'spp'
    ):
        super().__init__(sample_rate, n_fft=fft_size)
        self.enable_soft_vad = enable_soft_vad
        self.vad_method = vad_method

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

        # IMCRA 噪聲估計器
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

        # Bayesian SPP 估計器（用於增益計算）
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # OMLSA 增益計算器
        self.gain_calculator = OmlsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_asymmetric_smoothing=use_asymmetric_smoothing,
            alpha_attack=alpha_attack,
            alpha_decay=alpha_g
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
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        在頻域進行降噪

        IMCRA + OMLSA 核心流程:
        1. IMCRA 兩階段噪聲估計
        2. Bayesian SPP 計算先驗/後驗 SNR
        3. OMLSA 對數域 SPP 加權增益
        4. 時間平滑後轉回線性域

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)
            return_spp: 是否返回 SPP 歷史數據

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
            spp_history: SPP 歷史數據 - 僅當 return_spp=True
        """
        n_frames = noisy_magnitude.shape[0]

        # 初始化噪聲估計
        self.noise_estimator.estimate(noisy_magnitude)

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # SPP 歷史記錄（用於可視化）
        spp_history = [] if return_spp else None

        # 保存上一幀增強功率譜（用於 DD 計算）
        enhanced_psd_prev = None

        # 逐幀處理
        for i in range(n_frames):
            # 計算功率譜密度
            Y_psd = noisy_magnitude[i] ** 2
            noise_psd = self.noise_estimator.noise_psd

            # Bayesian SPP 估計（用於 OMLSA 增益計算）
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )

            # 收集 SPP 歷史
            if return_spp:
                spp_history.append(spp.copy())

            # OMLSA 增益計算（對數域 SPP 加權 + 時間平滑）
            gain = self.gain_calculator.calculate(spp, xi, gamma)

            # 應用增益
            enhanced_magnitude[i] = gain * noisy_magnitude[i]

            # Soft VAD 後處理
            if self.enable_soft_vad:
                enhanced_magnitude[i] = self._apply_soft_vad(enhanced_magnitude[i], spp=spp)

            # 保存增益供下一幀使用
            self.gain_prev = gain.copy()

            # 保存增強功率譜供下一幀 DD 使用
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # 更新噪聲估計
            # IMCRA 內部用自己的兩階段 SPP 更新噪聲，外部 spp 傳入但不使用
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
            # IMCRA params
            'freq_smooth_width': self.noise_estimator.freq_smooth_width,
            'alpha_s': self.noise_estimator.alpha_s,
            'alpha_d': self.noise_estimator.alpha_d,
            'L': self.noise_estimator.L,
            'V': self.noise_estimator.V,
            'U': self.noise_estimator.U,
            'delta_db': 10 * np.log10(self.noise_estimator.delta),
            'delta_s_db': 10 * np.log10(self.noise_estimator.delta_s),
            'num_init_frames': self.noise_estimator.num_init_frames,
            # SPP params
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            # OMLSA params
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
        }

    def __repr__(self):
        params = self.get_params()
        return (f"ImcraOmlsaDenoiser("
                f"alpha_s={params['alpha_s']}, "
                f"alpha_d={params['alpha_d']}, "
                f"L={params['L']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
