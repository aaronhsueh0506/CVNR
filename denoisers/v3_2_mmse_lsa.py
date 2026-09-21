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
from typing import Optional, Tuple
from core.signal_grid import (
    resolve_signal_grid,
    retime_ema_alpha,
    retime_frame_count,
    validate_signal_grid,
    _SIXTEEN_MS_HOP_SECONDS,
    _REFERENCE_HOP_SECONDS,
)


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
        frame_size: Optional[int] = None,
        frame_shift: Optional[int] = None,
        fft_size: Optional[int] = None,
        alpha_noise: float = 0.95,  # [Deprecated] 保留相容性；等同 alpha_d
        alpha_xi: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        g_min_db: float = -40.0,
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
        # IMCRA/MCRA mode: True = IMCRA (use OM-LSA posterior for noise gate,
        # default for standalone NR); False = plain MCRA (use in AEC pipeline
        # to prevent residual-echo from freezing noise tracking).
        mcra_accept_external_spp: bool = True,
        # NR mode ('full' | 'stationary'). Set by nr_modes.apply_mode() upstream; the
        # stationary-floor / scene-change params below carry the preset. Default 'full' +
        # all-off → byte-identical shipped V3-2.
        mode: str = 'full',
        # NR strength ('mild' | 'moderate' | 'balanced' | 'aggressive'). Set by
        # nr_strength.apply_strength() upstream. 'balanced' is an EMPTY overlay
        # (core/nr_strength.py) -- alpha_noise/alpha_g/alpha_decay at 'balanced'
        # are always the untouched pre-16ms-grid base YAML values (git-dated:
        # alpha_d/alpha_s/alpha_p 09e74d8 2026-01-08, alpha_g 02d7dc7/6bde3eb
        # 2026-01-02/05 -- all predate the 16ms-hop grid switch, 04edc42,
        # 2026-03-09); at any other strength they are always commit 6822129's
        # (2026-07-10, post-16ms-grid) preset overlay. Unlike `mode`, `strength`
        # alone disambiguates these three constants' provenance regardless of
        # mode (mode's stationary overlay, when active, still wins over
        # strength for alpha_noise -- see below). alpha_attack is NOT part of
        # this group -- see its own dedicated comment below; it has a
        # different provenance class (never YAML-sourced) and is unconditional.
        strength: str = 'balanced',
        stationary_floor: bool = False,
        stationary_floor_exponent: float = 1.0,
        stationary_floor_beta: float = 1.0,
        scene_change_tonal_veto: bool = False,
        scene_change_lo_flatness_max: float = 0.4,
    ):
        if frame_size is None and frame_shift is None:
            frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)
        elif None in (frame_size, frame_shift, fft_size):
            raise ValueError("frame_size, frame_shift, and fft_size must be set together")
        else:
            validate_signal_grid(sample_rate, frame_size, frame_shift, fft_size)
        super().__init__(sample_rate, n_fft=fft_size)
        self.noise_method = noise_method
        self.mode = mode
        self.strength = strength

        # Presets are authored in the legacy 10-ms frame domain. Convert every
        # temporal coefficient/count once at this outer model boundary so the
        # underlying estimators remain generic frame-domain components.
        # `strength != 'balanced'` (mild/moderate/aggressive) unambiguously
        # marks alpha_noise/alpha_g/alpha_decay as commit 6822129's
        # post-16ms-grid preset overlay (core/nr_strength.py's 'balanced'
        # entry is an EMPTY overlay, so at 'balanced' these three are always
        # the untouched pre-16ms-grid base YAML values -- see dated evidence
        # in the `strength` parameter's own docstring above). Composition
        # order is strength-then-mode (core/nr_modes.py docstring: "Applied
        # FIRST so the content mode composes on top"), so stationary mode's
        # own alpha_noise=0.95 overlay, when active, always wins last
        # regardless of strength. alpha_attack is excluded from this group --
        # see its own unconditional handling below.
        _strength_is_post_16ms_preset = strength != 'balanced'

        alpha_d_effective = alpha_d if alpha_d is not None else alpha_noise
        # alpha_noise=0.95 for mode=='stationary' is set unconditionally by
        # nr_modes.NR_MODE_PRESETS['stationary'], applied AFTER the strength
        # preset, so whenever mode=='stationary' this value is always that
        # 2026-07-05 stationary-mode commit's 16ms-grid-authored 0.95, never
        # the pre-16ms base/strength value -- same 16ms basis as a non-
        # 'balanced' strength preset (commit 6822129), so both conditions
        # share one call. Mirrors the C side (mmse_lsa_apply_stationary() in
        # mmse_lsa_types.h).
        if mode == 'stationary' or _strength_is_post_16ms_preset:
            alpha_d_effective = retime_ema_alpha(
                alpha_d_effective, sample_rate, frame_shift,
                authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
            )
        else:
            alpha_d_effective = retime_ema_alpha(
                alpha_d_effective, sample_rate, frame_shift
            )
        # alpha_xi is 16ms-native regardless of which strength/mode preset is
        # active: it is documented as "intentionally NOT set" by any strength
        # preset (core/nr_strength.py) -- always the shared base YAML value --
        # and that base value (0.92) was set by commit 6822129 (2026-07-10), a
        # musical-noise fix validated with a 12-file PESQ guard directly
        # against the live 16ms-hop grid (04edc42, 2026-03-09). Retiming it
        # again from the 10ms reference silently undoes that fix (0.92 ->
        # ~0.875 at the default 16kHz/512 grid, reintroducing nearly the
        # exact pre-fix value).
        alpha_xi = retime_ema_alpha(
            alpha_xi, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        # alpha_g/alpha_decay: same dual-provenance class as alpha_noise/
        # alpha_d above, disambiguated the same way via `strength` (untouched
        # by the mode/stationary overlay, only by strength).
        _preset_hop = (
            _SIXTEEN_MS_HOP_SECONDS if _strength_is_post_16ms_preset
            else _REFERENCE_HOP_SECONDS
        )
        alpha_g = retime_ema_alpha(
            alpha_g, sample_rate, frame_shift, authored_hop_seconds=_preset_hop
        )
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        # alpha_attack is UNCONDITIONALLY 16ms-authored, regardless of
        # `strength` -- unlike alpha_g/alpha_decay/alpha_noise above, it is
        # never YAML-sourced (config/v3_2_config.yaml explicitly documents
        # "the fast attack (0.3) is fixed in code, not configurable here");
        # its base 0.3 default was introduced by commit b913beb (2026-04-17),
        # which already postdates the 16ms-hop grid switch (04edc42,
        # 2026-03-09) by five weeks, so even the 'balanced' (non-overlaid)
        # case is 16ms-authored, not 10ms. The strength-preset overlay values
        # (0.4/0.4/0.15, commit 6822129, 2026-07-10) are likewise post-16ms.
        # The previous strength-conditional treatment of this field was wrong.
        alpha_attack = retime_ema_alpha(
            alpha_attack, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        if alpha_decay is not None:
            alpha_decay = retime_ema_alpha(
                alpha_decay, sample_rate, frame_shift,
                authored_hop_seconds=_preset_hop,
            )
        # L=32 is documented in the YAML as authored directly against the
        # 16ms hop ("32 幀 × 16ms/hop = 512ms" -- config/v3_2_config.yaml's
        # noise_estimation.L comment), unlike alpha_attack/alpha_s/alpha_p
        # (and num_init_frames below, which carries no such comment) which
        # have no hop-basis evidence and stay on the 10ms reference. L is
        # never touched by the strength overlay (core/nr_strength.py), so
        # this is unconditional -- no strength/mode branch needed.
        L = retime_frame_count(
            L, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        num_init_frames = retime_frame_count(
            num_init_frames, sample_rate, frame_shift
        )
        if mode == 'stationary':
            # scene_change_min_frames=30 for this mode is likewise set
            # unconditionally by nr_modes.NR_MODE_PRESETS['stationary']
            # (same 2026-07-05 commit, same 16ms-grid provenance as
            # alpha_noise above) -- same fix, same C-side mirror.
            scene_change_min_frames = retime_frame_count(
                scene_change_min_frames, sample_rate, frame_shift,
                authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
            )
        else:
            scene_change_min_frames = retime_frame_count(
                scene_change_min_frames, sample_rate, frame_shift
            )

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
                scene_change_tonal_veto=scene_change_tonal_veto,
                scene_change_lo_flatness_max=scene_change_lo_flatness_max,
                accept_external_spp=mcra_accept_external_spp,
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
            xi_min_db=xi_min_db,
        )

        # 創建 MMSE-LSA / OMLSA 增益計算器
        self.gain_calculator = MmseLsaGainCalculator(
            g_min_db=g_min_db,
            alpha_g=alpha_g,
            use_asymmetric_smoothing=use_asymmetric_smoothing,
            alpha_attack=alpha_attack,
            alpha_decay=alpha_decay,
            stationary_floor=stationary_floor,
            stationary_floor_exponent=stationary_floor_exponent,
            stationary_floor_beta=stationary_floor_beta,
        )

        # 存儲上一幀的增益（Decision Directed）
        self.gain_prev = None

    def denoise(self, noisy_signal: np.ndarray, return_spp: bool = False,
                return_gain: bool = False, return_noise_psd: bool = False):
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
        # denoise_spectrum 回傳 (mag, phase, [spp], [gain], [noise_psd])，附加項依旗標順序附加。
        result = self.denoise_spectrum(
            magnitudes, phases,
            return_spp=return_spp, return_gain=return_gain,
            return_noise_psd=return_noise_psd,
        )
        enhanced_magnitudes, enhanced_phases = result[0], result[1]
        extras = result[2:]  # spp / gain / noise_psd，順序與旗標一致

        # 3. 重建信號
        enhanced_signal = self.reconstructor.reconstruct_signal(
            enhanced_magnitudes,
            enhanced_phases,
            original_length=len(noisy_signal)
        )

        if extras:
            return (enhanced_signal, *extras)
        return enhanced_signal

    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray,
        return_spp: bool = False,
        return_gain: bool = False,
        return_noise_psd: bool = False,
        extra_noise_psd: np.ndarray = None
    ) -> tuple:  # (mag, phase, [spp], [gain], [noise_psd]) — extras per the return_* flags
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

        # SPP / Gain / noise-PSD 歷史記錄（用於可視化）
        spp_history = [] if return_spp else None
        gain_history = [] if return_gain else None
        # noise-PSD tracking：記錄每幀「用來算該幀增益」的估計噪聲 PSD（估計器內部值，
        # 不含 extra_noise_psd 的 echo 增量），供 music/noise 追蹤圖使用。
        noise_psd_history = [] if return_noise_psd else None

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
                if return_noise_psd:
                    noise_psd_history.append(self.noise_estimator.noise_psd.copy())
                enhanced_magnitude[i] = noisy_magnitude[i]
                # DD state：gain_prev = 1.0, enhanced_psd_prev = Y_psd
                self.gain_prev = gain.copy()
                enhanced_psd_prev = Y_psd.copy()
                continue

            # 正常處理
            noise_psd = self.noise_estimator.noise_psd
            # Echo-aware joint gain: fold the AEC residual-echo PSD R²(f) into the
            # noise floor THIS frame (a priori SNR ξ = S²/(N²+R²)) so the single
            # MMSE-LSA gain suppresses noise + residual echo per-bin. Does NOT
            # pollute the MCRA estimator's internal noise_psd (numpy + makes a
            # fresh array); update() below still tracks true noise.
            if extra_noise_psd is not None:
                noise_psd = noise_psd + extra_noise_psd[i]
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
            if return_noise_psd:
                # 估計器內部噪聲（尚未經 update()；即算此幀增益所用的噪聲底）
                noise_psd_history.append(self.noise_estimator.noise_psd.copy())

            enhanced_magnitude[i] = gain * noisy_magnitude[i]
            self.gain_prev = gain.copy()
            enhanced_psd_prev = enhanced_magnitude[i] ** 2

            self.noise_estimator.update(noisy_magnitude[i], spp=spp)

        # 相位保持不變
        enhanced_phase = noisy_phase

        # 動態組裝回傳：(mag, phase, [spp], [gain], [noise_psd])，附加項依旗標順序附加。
        # 無旗標時退化為既有的 (mag, phase) 2-tuple，向後相容。
        outputs = [enhanced_magnitude, enhanced_phase]
        if return_spp:
            outputs.append(np.array(spp_history))
        if return_gain:
            outputs.append(np.array(gain_history))
        if return_noise_psd:
            outputs.append(np.array(noise_psd_history))
        return tuple(outputs)

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
            'mode': self.mode,
            'stationary_floor': self.gain_calculator.stationary_floor,
            'sample_rate': self.sample_rate,
            'frame_size': self.processor.frame_size,
            'frame_shift': self.processor.frame_shift,
            'fft_size': self.processor.fft_size,
            'noise_method': self.noise_method,
            'alpha_xi': self.spp_estimator.alpha,
            'q': self.spp_estimator.q,
            'xi_min_db': 10 * np.log10(self.spp_estimator.xi_min),
            'g_min_db': 20 * np.log10(self.gain_calculator.g_min),
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
