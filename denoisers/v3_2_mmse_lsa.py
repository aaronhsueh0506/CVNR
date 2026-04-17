"""
V3-2: MMSE-LSA Denoiser - MMSE 對數短時頻譜幅度估計降噪器
基於 Ephraim-Malah 1985
v2.6: 添加 Human Voice Band Soft VAD 後處理
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import MmseLsaGainCalculator
from .base_denoiser import BaseDenoiser
from typing import Tuple


class MmseLsaDenoiser(BaseDenoiser):
    """
    版本 3-2: MMSE-LSA 降噪器

    基於 Ephraim-Malah 1985 的最小均方誤差對數頻譜幅度估計

    核心特點:
        - 在對數域進行 SPP 加權: log(G) = p*log(G_mmse) + (1-p)*log(g_min)
        - 在對數域進行時間平滑: log(G_t) = α*log(G_{t-1}) + (1-α)*log(G_t)
        - 更符合人耳對數感知特性 (Weber-Fechner 定律)
        - 相比 STSA 產生更少 musical noise

    與 V3-1 (MMSE-STSA) 的區別:
        - STSA: 線性域操作,最小化 E[(|X| - |Xhat|)^2]
        - LSA:  對數域操作,最小化 E[(log|X| - log|Xhat|)^2]
        - LSA 對小增益更保守,增益變化更平緩

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
        num_init_frames: 初始噪聲估計幀數
        enable_noise_tracking: 是否啟用噪聲場景追蹤
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: int = 512,
        frame_shift: int = 256,
        fft_size: int = 512,
        alpha_noise: float = 0.95,  # [Deprecated] 保留相容性；等同 alpha_d
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        num_init_frames: int = 20,
        # v2.0 MCRA 噪聲估計參數
        noise_method: str = 'recursive_average',  # 'recursive_average' 或 'mcra'
        alpha_s: float = 0.9,       # MCRA 時間平滑因子
        alpha_d: float = None,      # MCRA 噪聲更新基礎速率（None 則用 alpha_noise）
        alpha_p: float = 0.2,       # MCRA SPP 平滑因子
        L: int = 96,                # MCRA 最小值窗口長度
        delta_db: float = 5.0,      # MCRA 偏差補償 (dB)
        broadband_threshold: float = 0.8,  # 寬頻場景轉換偵測閾值
        scene_change_threshold_db: float = 10.0,  # 場景轉換偵測閾值 (dB)
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        scene_change_flatness_threshold: float = 0.4,  # 高頻段 flatness 閾值
        # 非對稱平滑參數
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: float = None,  # None = 等於 alpha_g
    ):
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method

        # alpha_d 優先於 alpha_noise（兩者同義；alpha_noise 為舊名保留相容）
        alpha_d_effective = alpha_d if alpha_d is not None else alpha_noise

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
                alpha_d=alpha_d_effective,
                alpha_p=alpha_p,
                L=L,
                delta_db=delta_db,
                num_init_frames=num_init_frames,
                broadband_threshold=broadband_threshold,
                scene_change_threshold_db=scene_change_threshold_db,
                scene_change_min_frames=scene_change_min_frames,
                scene_change_blend=scene_change_blend,
                scene_change_flatness_threshold=scene_change_flatness_threshold,
            )
        else:
            self.noise_estimator = RecursiveAverageNoiseEstimator(
                alpha=alpha_d_effective,
                num_init_frames=num_init_frames,
                update_during_speech=False
            )

        # 創建 SPP 估計器
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db
        )

        # 創建 MMSE-LSA / OMLSA 增益計算器
        self.gain_calculator = MmseLsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_asymmetric_smoothing=use_asymmetric_smoothing,
            alpha_attack=alpha_attack,
            alpha_decay=alpha_decay,
        )

        # 存儲上一幀的增益（Decision Directed）
        self.gain_prev = None

    def denoise(self, noisy_signal: np.ndarray, return_spp: bool = False, return_gain: bool = False):
        """
        對帶噪信號進行降噪

        參數:
            noisy_signal: 帶噪音頻信號 (n_samples,)
            return_spp: 是否返回 SPP 歷史數據 (用於可視化)
            return_gain: 是否返回 Gain 歷史數據 (用於可視化)

        返回:
            enhanced_signal: 降噪後的信號 (n_samples,)
            spp_history: SPP 歷史數據 (n_frames, n_freqs) - 僅當 return_spp=True
            gain_history: Gain 歷史數據 (n_frames, n_freqs) - 僅當 return_gain=True
        """
        # 1. 分幀和 FFT
        magnitudes, phases, spectra = self.processor.process_signal(noisy_signal)

        # 2. 降噪
        result = self.denoise_spectrum(magnitudes, phases, return_spp=return_spp, return_gain=return_gain)
        if return_spp and return_gain:
            enhanced_magnitudes, enhanced_phases, spp_history, gain_history = result
        elif return_spp:
            enhanced_magnitudes, enhanced_phases, spp_history = result
        elif return_gain:
            enhanced_magnitudes, enhanced_phases, gain_history = result
        else:
            enhanced_magnitudes, enhanced_phases = result

        # 3. 重建信號
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        if return_spp and return_gain:
            return enhanced_signal, spp_history, gain_history
        if return_spp:
            return enhanced_signal, spp_history
        if return_gain:
            return enhanced_signal, gain_history
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False,
        return_gain: bool = False
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        在頻域進行降噪

        MMSE-LSA 核心流程:
        1. 估計噪聲功率譜
        2. 計算 SPP, 先驗/後驗 SNR
        3. 在對數域進行 SPP 加權和時間平滑
        4. 轉回線性域應用增益

        注意：進入時會自動 reset 內部狀態，確保連續呼叫處理不同音訊段時互不污染。

        參數:
            noisy_magnitude: 帶噪語音幅度譜 (n_frames, n_freqs)
            noisy_phase: 帶噪語音相位譜 (n_frames, n_freqs)
            return_spp: 是否返回 SPP 歷史數據 (用於可視化)
            return_gain: 是否返回 Gain 歷史數據 (用於可視化)

        返回:
            enhanced_magnitude: 降噪後的幅度譜 (n_frames, n_freqs)
            enhanced_phase: 相位譜（不變）(n_frames, n_freqs)
            spp_history: SPP 歷史數據 (n_frames, n_freqs) - 僅當 return_spp=True
            gain_history: Gain 歷史數據 (n_frames, n_freqs) - 僅當 return_gain=True
        """
        # 進入點重置所有幀間狀態，避免不同段落互相污染
        self.reset()

        n_frames = noisy_magnitude.shape[0]

        # 使用前 num_init 幀建立初始噪聲 PSD
        self.noise_estimator.estimate(noisy_magnitude)
        num_init = self.noise_estimator.num_init_frames

        # 初始化輸出
        enhanced_magnitude = np.zeros_like(noisy_magnitude)

        # SPP / Gain 歷史記錄（用於可視化）
        spp_history = [] if return_spp else None
        gain_history = [] if return_gain else None

        # v1.5.0: 保存上一幀增強功率譜（用於正確的 DD 計算）
        enhanced_psd_prev = None

        # 逐幀處理
        # v4.2.1 C-align: 前 num_init 幀改為嚴格 passthrough (gain=1)，與 C streaming 一致。
        # DD state (gain_prev, enhanced_psd_prev) 反映 passthrough 的結果；update() 在 init 完成後才開始。
        n_freqs = noisy_magnitude.shape[1]
        for i in range(n_frames):
            Y_psd = noisy_magnitude[i] ** 2

            if i < num_init:
                # Init 階段：passthrough，不呼叫 SPP / gain 計算（避免狀態污染）
                gain = np.ones(n_freqs)
                if return_spp:
                    spp_history.append(np.zeros(n_freqs))
                if return_gain:
                    gain_history.append(gain.copy())
                enhanced_magnitude[i] = noisy_magnitude[i]
                # DD state：gain_prev = 1.0, enhanced_psd_prev = Y_psd
                self.gain_prev = gain.copy()
                enhanced_psd_prev = Y_psd.copy()
                continue

            # 正常處理
            noise_psd = self.noise_estimator.noise_psd
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )
            if return_spp:
                spp_history.append(spp.copy())

            gain = self.gain_calculator.calculate(spp, xi, gamma)
            if return_gain:
                gain_history.append(gain.copy())

            enhanced_magnitude[i] = gain * noisy_magnitude[i]
            self.gain_prev = gain.copy()
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        if return_spp and return_gain:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history), np.array(gain_history)
        if return_spp:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history)
        if return_gain:
            return enhanced_magnitude, enhanced_phase, np.array(gain_history)
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
            'version': 'V3-2',
            'name': 'OMLSA (MMSE-LSA + SPP weighting)',
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_asymmetric_smoothing': self.gain_calculator.use_asymmetric_smoothing,
            'alpha_attack': self.gain_calculator.alpha_attack,
            'alpha_decay': self.gain_calculator.alpha_decay,
            'num_init_frames': self.noise_estimator.num_init_frames
        }
        if self.noise_method == 'mcra':
            params['alpha_s'] = self.noise_estimator.alpha_s
            params['alpha_d'] = self.noise_estimator.alpha_d
            params['alpha_p'] = self.noise_estimator.alpha_p
            params['L'] = self.noise_estimator.L
            params['scene_change_flatness_threshold'] = (
                self.noise_estimator.scene_change_flatness_threshold
            )
        else:
            params['alpha_noise'] = self.noise_estimator.alpha
        return params

    def __repr__(self):
        params = self.get_params()
        return (f"MmseLsaDenoiser("
                f"alpha_xi={params['alpha_xi']}, "
                f"g_min={params['g_min_db']:.1f}dB)")
