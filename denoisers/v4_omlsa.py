"""
V4: OMLSA Denoiser with Wind Handler (RESEARCH INFRASTRUCTURE)

!! STATUS !!
當前 V4 wind handler 於 VCTK 824 / Wind-Top80 / 合成風聲三個測試集皆未能
提供統計顯著的風聲改善（差異均在 run-to-run 雜訊範圍）。原因是單 mic 的
LER + tilt + ZCR 統計法難以分離語音 F1/F2 formant 能量與風聲低頻能量
（細節見 results/v4_diagnosis_report.md）。

預設 config（config/v4_config.yaml）將 adaptive profile 設為 FLAT、
transient suppressor 關閉，行為實質等效於修復後 V3-2。保留框架供未來
雙 mic coherence / DL post-filter 延伸使用。

在修復後的 V3-2 (OMLSA) 基礎上，組合：
- WindDetector：偵測風聲機率與嚴重度
- FreqAdaptiveController：依風聲嚴重度頻段自適應 g_min / alpha_xi / alpha_g
- McraNoiseEstimator 的 wind_severity 參數：severe 時啟用 fast tracking
- TransientSuppressor：時域 buffeting 抑制

關閉 wind handler 時（enable_wind_handler=False），行為與修復後的 V3-2 完全一致
（bit-exact，已測）。

參考：V4 規格書 §5，診斷報告 results/v4_diagnosis_report.md
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from typing import Tuple, Optional

from core import FrameProcessor, Reconstructor, SppEstimator
from core.noise_estimators import RecursiveAverageNoiseEstimator, McraNoiseEstimator
from core.gain_calculators import MmseLsaGainCalculator
from core.wind_detector import WindDetector
from core.freq_adaptive_controller import FreqAdaptiveController
from core.transient_suppressor import TransientSuppressor
from .base_denoiser import BaseDenoiser


class OmlsaDenoiser(BaseDenoiser):
    """V4 OMLSA 降噪器

    組合 V3-2 的既有元件（FrameProcessor、MCRA、SPP、LSA gain、Reconstructor），
    加上 WindDetector + FreqAdaptiveController（+ Phase 3 TransientSuppressor）。

    enable_wind_handler=False 時行為與修復後 V3-2 一致，可作為 backward-compat baseline。
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: int = 512,
        frame_shift: int = 256,
        fft_size: int = 512,
        alpha_noise: float = 0.95,
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -20.0,
        alpha_g: float = 0.7,
        num_init_frames: int = 20,
        # MCRA
        noise_method: str = 'mcra',
        alpha_s: float = 0.9,
        alpha_d: Optional[float] = None,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        broadband_threshold: float = 0.8,
        scene_change_threshold_db: float = 10.0,
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        scene_change_flatness_threshold: float = 0.4,
        # 非對稱平滑
        use_asymmetric_smoothing: bool = True,
        alpha_attack: float = 0.3,
        alpha_decay: Optional[float] = None,
        # V4: SPP-protected floor（保護語音 bin 不被 wind handler 過壓）
        spp_protect_floor_db: Optional[float] = None,
        spp_protect_threshold: float = 0.5,
        # V4 Wind Handler
        enable_wind_handler: bool = False,
        wind_detector_config: Optional[dict] = None,
        freq_adaptive_config: Optional[dict] = None,
        enable_transient_suppressor: bool = False,
        transient_suppressor_config: Optional[dict] = None,
    ):
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        self.enable_wind_handler = enable_wind_handler

        alpha_d_effective = alpha_d if alpha_d is not None else alpha_noise

        # 分幀 / 重建
        self.processor = FrameProcessor(
            sample_rate=sample_rate,
            frame_size=frame_size,
            frame_shift=frame_shift,
            fft_size=fft_size,
            window_type='hanning',
        )
        self.reconstructor = Reconstructor(
            fft_size=fft_size,
            frame_shift=self.processor.frame_shift,
            window=self.processor.window,
        )

        # 噪聲估計器
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
                update_during_speech=False,
            )

        # SPP
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db,
        )

        # OMLSA gain
        self.gain_calculator = MmseLsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_asymmetric_smoothing=use_asymmetric_smoothing,
            alpha_attack=alpha_attack,
            alpha_decay=alpha_decay,
            spp_protect_floor_db=spp_protect_floor_db,
            spp_protect_threshold=spp_protect_threshold,
        )

        # V4 Wind Handler
        if enable_wind_handler:
            wd_cfg = wind_detector_config or {}
            self.wind_detector = WindDetector(
                sample_rate=sample_rate,
                fft_size=fft_size,
                **wd_cfg,
            )
            fa_cfg = freq_adaptive_config or {}
            self.freq_adaptive = FreqAdaptiveController(
                sample_rate=sample_rate,
                fft_size=fft_size,
                # 對齊 WindDetector 的 severity 閾值
                mild_threshold=self.wind_detector.mild_threshold,
                severe_threshold=self.wind_detector.severe_threshold,
                **fa_cfg,
            )
        else:
            self.wind_detector = None
            self.freq_adaptive = None

        # V4 Phase 3: Transient suppressor（時域 buffeting 壓制）
        self.enable_transient_suppressor = enable_transient_suppressor
        if enable_transient_suppressor:
            ts_cfg = transient_suppressor_config or {}
            self.transient_suppressor = TransientSuppressor(
                sample_rate=sample_rate,
                **ts_cfg,
            )
        else:
            self.transient_suppressor = None

        self.gain_prev = None

    def denoise(
        self,
        noisy_signal: np.ndarray,
        return_spp: bool = False,
        return_gain: bool = False,
        diag_sink: Optional[list] = None,
    ):
        """
        diag_sink: 若提供（list），每幀會 append 一個 dict 包含所有診斷變數
                   （wind/adaptive/MCRA/SPP/gain 等）供 Phase 0 離線分析。
        """
        original_input = noisy_signal

        # Phase 3: 時域 transient suppression 在分幀前做
        if self.enable_transient_suppressor:
            pre_signal = noisy_signal
            noisy_signal = self.transient_suppressor.process(noisy_signal)
            if diag_sink is not None:
                # 估計整段 transient 施加的平均衰減（dB）
                r0 = np.sqrt(np.mean(pre_signal ** 2) + 1e-20)
                r1 = np.sqrt(np.mean(noisy_signal ** 2) + 1e-20)
                self._transient_total_db = 20 * np.log10(r1 / r0)
            else:
                self._transient_total_db = 0.0
        else:
            self._transient_total_db = 0.0

        magnitudes, phases, _ = self.processor.process_signal(noisy_signal)

        # 取時域幀給 WindDetector 算 ZCR（Phase 2 特徵）
        time_frames = None
        if self.enable_wind_handler or diag_sink is not None:
            time_frames = self.processor._split_frames(noisy_signal)

        result = self.denoise_spectrum(
            magnitudes, phases,
            return_spp=return_spp, return_gain=return_gain,
            time_domain_frames=time_frames,
            diag_sink=diag_sink,
            original_signal_frames=(
                self.processor._split_frames(original_input)
                if diag_sink is not None else None
            ),
        )
        if return_spp and return_gain:
            enh_mag, enh_phase, spp_hist, gain_hist = result
        elif return_spp:
            enh_mag, enh_phase, spp_hist = result
        elif return_gain:
            enh_mag, enh_phase, gain_hist = result
        else:
            enh_mag, enh_phase = result

        enhanced = self.reconstructor.reconstruct_signal(
            enh_mag, enh_phase, original_length=len(noisy_signal)
        )

        if return_spp and return_gain:
            return enhanced, spp_hist, gain_hist
        if return_spp:
            return enhanced, spp_hist
        if return_gain:
            return enhanced, gain_hist
        return enhanced

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False,
        return_gain: bool = False,
        time_domain_frames: Optional[np.ndarray] = None,
        diag_sink: Optional[list] = None,
        original_signal_frames: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """頻域逐幀降噪，進入點自動 reset 狀態。

        time_domain_frames: 可選 (n_frames, frame_size) 時域幀；提供時 WindDetector
        會計算 ZCR 特徵（Phase 2）。
        diag_sink: 若為 list，每幀會 append 診斷字典。
        """
        self.reset()

        n_frames = noisy_magnitude.shape[0]
        self.noise_estimator.estimate(noisy_magnitude)
        num_init = self.noise_estimator.num_init_frames

        enhanced_magnitude = np.zeros_like(noisy_magnitude)
        spp_history = [] if return_spp else None
        gain_history = [] if return_gain else None
        enhanced_psd_prev = None

        # 預計算診斷用 band 切分
        n_freqs = noisy_magnitude.shape[1]
        sr = self.sample_rate
        fft_size = self.processor.fft_size
        bin_200 = max(1, int(200 * fft_size / sr))   # 0-200 Hz
        bin_800 = int(800 * fft_size / sr)
        bin_4k = int(4000 * fft_size / sr)

        for i in range(n_frames):
            mag = noisy_magnitude[i]
            Y_psd = mag ** 2
            noise_psd = self.noise_estimator.noise_psd

            # V4 Wind Handler：偵測 + 取得頻段自適應參數
            if self.enable_wind_handler:
                td_frame = time_domain_frames[i] if time_domain_frames is not None else None
                wind_info = self.wind_detector.detect(mag, time_domain_frame=td_frame)
                adaptive = self.freq_adaptive.get_params(
                    wind_info['wind_probability'], wind_info['wind_severity']
                )
                g_min_frame = adaptive['g_min']
                alpha_xi_frame = adaptive['alpha_xi']
                alpha_g_frame = adaptive['alpha_g']
                wind_severity = wind_info['wind_severity']
            else:
                wind_info = None
                adaptive = None
                g_min_frame = None
                alpha_xi_frame = None
                alpha_g_frame = None
                wind_severity = 'none'

            # SPP 估計
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd, noise_psd, self.gain_prev, enhanced_psd_prev,
                alpha_override=alpha_xi_frame,
            )

            if return_spp:
                spp_history.append(spp.copy())

            # OMLSA gain
            gain = self.gain_calculator.calculate(
                spp, xi, gamma,
                g_min=g_min_frame,
                alpha_g_override=alpha_g_frame,
            )

            if return_gain:
                gain_history.append(gain.copy())

            enhanced_magnitude[i] = gain * mag
            self.gain_prev = gain.copy()
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            # 只在 init 完成後更新噪聲估計
            if i >= num_init:
                if self.noise_method == 'mcra':
                    self.noise_estimator.update(mag, spp=spp, wind_severity=wind_severity)
                else:
                    self.noise_estimator.update(mag, spp=spp)

            # === 診斷資料收集 ===
            if diag_sink is not None:
                # band energy 用於 noise_psd 的 low/mid/high mean
                def _safe_log_mean_db(x):
                    return float(10 * np.log10(np.mean(x) + 1e-20))

                rec = {
                    'frame_idx': i,
                    'time_sec': i * self.processor.frame_shift / sr,
                    'is_init': i < num_init,
                    # Wind detector
                    'wind_prob': wind_info['wind_probability'] if wind_info else 0.0,
                    'wind_severity': wind_severity,
                    'feat_ler': wind_info['features']['low_energy_ratio'] if wind_info else 0.0,
                    'feat_tilt_db': wind_info['features']['spectral_tilt_db'] if wind_info else 0.0,
                    'feat_zcr': (wind_info['features']['zcr']
                                 if wind_info and wind_info['features']['zcr'] is not None
                                 else -1.0),
                    'hangover_active': int(wind_info['hangover_active']) if wind_info else 0,
                    # Adaptive params (代表頻段：取 band 中點)
                    'g_min_db_b0': (float(10 * np.log10(adaptive['g_min'][0]))
                                    if adaptive else 0.0),
                    'g_min_db_b1': (float(10 * np.log10(adaptive['g_min'][bin_200 + 2]))
                                    if adaptive and bin_200 + 2 < n_freqs else 0.0),
                    'g_min_db_b2': (float(10 * np.log10(adaptive['g_min'][bin_800 + 2]))
                                    if adaptive and bin_800 + 2 < n_freqs else 0.0),
                    'g_min_db_b3': (float(10 * np.log10(adaptive['g_min'][min(bin_4k + 2, n_freqs-1)]))
                                    if adaptive else 0.0),
                    'alpha_xi_b0': float(adaptive['alpha_xi'][0]) if adaptive else 0.0,
                    'alpha_xi_b3': (float(adaptive['alpha_xi'][min(bin_4k + 2, n_freqs-1)])
                                    if adaptive else 0.0),
                    # MCRA noise PSD 三段
                    'noise_psd_low_db': _safe_log_mean_db(noise_psd[:bin_200]),
                    'noise_psd_mid_db': _safe_log_mean_db(noise_psd[bin_200:bin_4k]),
                    'noise_psd_high_db': _safe_log_mean_db(noise_psd[bin_4k:]),
                    # SPP / gain
                    'spp_mean': float(np.mean(spp)),
                    'spp_low_mean': float(np.mean(spp[:bin_200])),
                    'spp_mid_mean': float(np.mean(spp[bin_200:bin_4k])),
                    'gain_mean': float(np.mean(gain)),
                    'gain_low_mean': float(np.mean(gain[:bin_200])),
                    'gain_mid_mean': float(np.mean(gain[bin_200:bin_4k])),
                    'gain_high_mean': float(np.mean(gain[bin_4k:])),
                    # 輸入 / 輸出 RMS
                    'input_rms_db': _safe_log_mean_db(mag ** 2),
                    'output_rms_db': _safe_log_mean_db(enhanced_magnitude[i] ** 2),
                }
                rec['suppression_db'] = rec['output_rms_db'] - rec['input_rms_db']
                diag_sink.append(rec)

        enhanced_phase = noisy_phase

        if return_spp and return_gain:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history), np.array(gain_history)
        if return_spp:
            return enhanced_magnitude, enhanced_phase, np.array(spp_history)
        if return_gain:
            return enhanced_magnitude, enhanced_phase, np.array(gain_history)
        return enhanced_magnitude, enhanced_phase

    def reset(self):
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        if self.wind_detector is not None:
            self.wind_detector.reset()
        if self.transient_suppressor is not None:
            self.transient_suppressor.reset()
        self.gain_prev = None

    def get_params(self) -> dict:
        params = {
            'version': 'V4',
            'name': 'OMLSA + Wind Handler' if self.enable_wind_handler else 'OMLSA (wind off)',
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'enable_wind_handler': self.enable_wind_handler,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 10 * np.log10(self.gain_calculator.g_min),
            'alpha_g': self.gain_calculator.alpha_g,
            'use_asymmetric_smoothing': self.gain_calculator.use_asymmetric_smoothing,
            'alpha_attack': self.gain_calculator.alpha_attack,
            'alpha_decay': self.gain_calculator.alpha_decay,
            'num_init_frames': self.noise_estimator.num_init_frames,
        }
        if self.noise_method == 'mcra':
            params['alpha_s'] = self.noise_estimator.alpha_s
            params['alpha_d'] = self.noise_estimator.alpha_d
            params['alpha_p'] = self.noise_estimator.alpha_p
            params['L'] = self.noise_estimator.L
        return params

    def __repr__(self):
        p = self.get_params()
        return (f"OmlsaDenoiser(wind={p['enable_wind_handler']}, "
                f"alpha_xi={p['alpha_xi']}, g_min={p['g_min_db']:.1f}dB)")
