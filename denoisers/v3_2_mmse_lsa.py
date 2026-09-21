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


# Frame speech gate anchor; mirrors C MMSE_LSA_SPEECH_PROTECT_ANCHOR_Q
# (mmse_lsa_types.h holds the rationale).
SPEECH_PROTECT_ANCHOR_Q = 0.52

def _hz_to_bin_ceil(hz, fft_size, sample_rate):
    """First FFT bin at or above hz."""
    return int(np.ceil(hz * fft_size / sample_rate))


def _hz_to_bin_floor_inclusive(hz, fft_size, sample_rate):
    """Number of FFT bins covering [0, hz] inclusive (a slice end)."""
    return int(np.floor(hz * fft_size / sample_rate)) + 1


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
        # NR strength selects suppression depth only. DD, tracker and gain
        # time constants are shared by every preset.
        strength: str = 'balanced',
        stationary_floor: bool = False,
        stationary_floor_exponent: float = 1.0,
        stationary_floor_beta: float = 1.0,
        scene_change_tonal_veto: bool = False,
        scene_change_lo_flatness_max: float = 0.4,
        # Experimental WebRTC-style frame/cross-band prior.  Defaults are a
        # strict no-op; the research branch enables these explicitly in the
        # ablation runner rather than changing any shipped preset.
        cross_band_prior_strength: float = 0.0,
        cross_band_prior_threshold: float = 0.50,
        cross_band_prior_full_scale: float = 0.70,
        cross_band_prior_max_q: float = 0.54,
        cross_band_prior_alpha: float = 0.90,
        noise_over_subtraction: float = 1.0,
        speech_protect_floor_db: Optional[float] = None,
        speech_protect_threshold: float = 0.5,
        speech_protect_frame_threshold: Optional[float] = None,
        # Direction-aware MCRA update: base rate for the RISING direction only
        # (authored at the 16 ms hop, retimed to the running grid). None keeps
        # the shipped symmetric recursion.
        alpha_noise_up: Optional[float] = None,
        # Speech-gated MCRA update: base rate used in bins whose gating
        # probability exceeds noise_speech_gate_p, where the estimate may fall
        # at the ordinary rate but rise no faster than this (authored at the
        # 16 ms hop, retimed). None keeps the shipped path.
        alpha_noise_speech: Optional[float] = None,
        noise_speech_gate_p: float = 0.2,
        # Frame-level condition for the speech-gated update: mean gating
        # probability over the 80-4000 Hz band must exceed this. None = off.
        noise_frame_gate_p: Optional[float] = None,
        # Alternative per-bin condition for the speech-gated update: the
        # decision-directed a-priori SNR must exceed this (dB). None = use the
        # SPP gate. The DD SNR separates speech from noise bins far better
        # than the fixed-prior posterior, which sits near 0.5 on both.
        noise_gate_xi_db: Optional[float] = None,
        # Broadband-onset escape for the speech-gated update: if more than this
        # fraction of bins is gated in a frame, the frame is treated as a noise
        # level change and updated at the ordinary rate. None = no escape.
        noise_gate_max_frac: Optional[float] = None,
        # Frame-level output energy make-up after the per-bin gain: the frame's
        # amplitude ratio g = sqrt(E_out/E_in) is scaled back up by
        # 1 + up_slope*(g - blim) when g > blim (never past unity) and eased
        # down by 1 - down_slope*(blim - g) when g < blim, blended by the
        # frame speech evidence (mean fixed-prior SPP over the speech band).
        # The DD state and the noise tracker see the unscaled gain.
        makeup_gain: bool = False,
        makeup_blim: float = 0.5,
        makeup_up_slope: float = 1.3,
        makeup_down_slope: float = 0.3,
        # Feed the decision-directed a-priori SNR from the clamped H1 gain
        # (Cohen 2001 eq. 18) instead of the floor-mixed output gain.
        dd_from_gmmse: bool = False,
        # Frame-context speech prior on the gain-side SPP (see SppEstimator):
        # the speech prior rises from q to frame_prior_q_max as the mean
        # fixed-prior SPP over frame_prior_band_hz climbs from spp_lo to
        # spp_hi. The noise tracker always sees the fixed-prior SPP.
        frame_prior_q_max: Optional[float] = None,
        frame_prior_spp_lo: float = 0.5,
        frame_prior_spp_hi: float = 0.8,
        frame_prior_band_hz: Tuple[float, float] = (300.0, 3400.0),
        # Frame-gated gain floor: g_min rises by this many dB times the frame
        # prior (0..1), so speech frames get a shallower floor while noise
        # frames keep the preset floor. Uses the same frame evidence as the
        # frame prior above; the SPP itself is unchanged unless
        # frame_prior_q_max is also set.
        frame_prior_gmin_lift_db: Optional[float] = None,
        # Floor blend domain in the gain calculator: 'log' | 'sqrt' | 'linear'.
        floor_blend: str = 'log',
        # Restrict the xi-gated slow noise rise to bins below this frequency
        # and switch it on for the whole band only when more than
        # noise_gate_frame_frac of the speech-band bins carry speech evidence
        # (DD xi above noise_gate_xi_db). None = per-bin xi gate.
        noise_gate_lf_hz: Optional[float] = None,
        noise_gate_frame_frac: float = 0.1,
        # Frame speech evidence that blends the make-up: 'spp' = mean
        # fixed-prior SPP over the speech band (shipped port), 'xi' = 0.1-EMA
        # of min(1, frac(DD xi > makeup_prior_xi_db)/0.15) over the speech band.
        makeup_prior: str = 'spp',
        makeup_prior_xi_db: float = 3.0,
    ):
        if alpha_noise_up is not None and not 0.0 <= alpha_noise_up < 1.0:
            raise ValueError("alpha_noise_up must be None or in [0, 1)")
        if alpha_noise_speech is not None and not 0.0 <= alpha_noise_speech < 1.0:
            raise ValueError("alpha_noise_speech must be None or in [0, 1)")
        if not (0.0 < makeup_blim < 1.0 and makeup_up_slope >= 0.0
                and 0.0 <= makeup_down_slope <= 1.0):
            raise ValueError(
                "makeup_blim must be in (0, 1), makeup_up_slope >= 0, "
                "and makeup_down_slope in [0, 1]"
            )
        self.noise_gate_xi = (10 ** (noise_gate_xi_db / 10)
                              if noise_gate_xi_db is not None else None)
        self.makeup_gain = bool(makeup_gain)
        self.makeup_blim = float(makeup_blim)
        self.makeup_up_slope = float(makeup_up_slope)
        self.makeup_down_slope = float(makeup_down_slope)
        self.dd_from_gmmse = bool(dd_from_gmmse)
        if makeup_prior not in ('spp', 'xi'):
            raise ValueError("makeup_prior must be 'spp' or 'xi'")
        if not 0.0 <= noise_gate_frame_frac <= 1.0:
            raise ValueError("noise_gate_frame_frac must be in [0, 1]")
        if noise_gate_lf_hz is not None and noise_gate_xi_db is None:
            raise ValueError("noise_gate_lf_hz requires noise_gate_xi_db")
        if frame_prior_gmin_lift_db is not None and not 0.0 <= frame_prior_gmin_lift_db <= -g_min_db:
            raise ValueError("frame_prior_gmin_lift_db must be in [0, -g_min_db]")
        self.frame_prior_gmin_lift_db = frame_prior_gmin_lift_db
        self.makeup_prior = makeup_prior
        self.makeup_prior_xi = 10 ** (makeup_prior_xi_db / 10)
        self.noise_gate_frame_frac = float(noise_gate_frame_frac)
        self._makeup_prior_state = 0.5
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
        if not np.isfinite(noise_over_subtraction) or noise_over_subtraction < 1.0:
            raise ValueError("noise_over_subtraction must be finite and >= 1")
        self.noise_over_subtraction = float(noise_over_subtraction)
        if (speech_protect_frame_threshold is not None
                and (not np.isfinite(speech_protect_frame_threshold)
                     or not 0.0 <= speech_protect_frame_threshold <= 1.0)):
            raise ValueError(
                "speech_protect_frame_threshold must be None or in [0, 1]"
            )
        self.speech_protect_frame_threshold = speech_protect_frame_threshold
        # Applied gate = authored value + (q - anchor), in float32 like the C
        # port (exactly the authored value at the anchor).
        self.speech_protect_frame_threshold_effective = (
            None if speech_protect_frame_threshold is None else
            float(np.float32(speech_protect_frame_threshold)
                  + (np.float32(q) - np.float32(SPEECH_PROTECT_ANCHOR_Q))))

        # Convert temporal coefficients once at the outer model boundary.
        # Strength presets contain no temporal keys. The base full-mode
        # alpha_d/alpha_g/alpha_decay values are authored at 10 ms; the
        # stationary overlay and alpha_attack are authored at 16 ms.
        alpha_d_effective = alpha_d if alpha_d is not None else alpha_noise
        if mode == 'stationary':
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
        alpha_g = retime_ema_alpha(
            alpha_g, sample_rate, frame_shift,
            authored_hop_seconds=_REFERENCE_HOP_SECONDS,
        )
        alpha_s = retime_ema_alpha(alpha_s, sample_rate, frame_shift)
        alpha_p = retime_ema_alpha(alpha_p, sample_rate, frame_shift)
        # alpha_attack is authored directly at the 16-ms product grid.
        alpha_attack = retime_ema_alpha(
            alpha_attack, sample_rate, frame_shift,
            authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS,
        )
        if alpha_decay is not None:
            alpha_decay = retime_ema_alpha(
                alpha_decay, sample_rate, frame_shift,
                authored_hop_seconds=_REFERENCE_HOP_SECONDS,
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

        n_freqs = fft_size // 2 + 1
        # Frame speech-evidence band (80-4000 Hz): the SPP mean and the DD-xi
        # fraction over these bins drive the LF gain floor, the tracker guard
        # and the research priors below.
        speech_bin_start = max(1, _hz_to_bin_ceil(80.0, fft_size, sample_rate))
        speech_bin_end = min(
            n_freqs,
            _hz_to_bin_floor_inclusive(min(4000.0, sample_rate / 2.0),
                                       fft_size, sample_rate),
        )
        self.speech_bin_start = speech_bin_start
        self.speech_bin_end = speech_bin_end

        # 創建噪聲估計器（根據配置選擇）
        if noise_method == 'mcra':
            alpha_d_up_effective = (
                retime_ema_alpha(alpha_noise_up, sample_rate, frame_shift,
                                 authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS)
                if alpha_noise_up is not None else None)
            alpha_d_speech_effective = (
                retime_ema_alpha(alpha_noise_speech, sample_rate, frame_shift,
                                 authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS)
                if alpha_noise_speech is not None else None)
            self.noise_estimator = McraNoiseEstimator(
                alpha_s=alpha_s,
                alpha_d=alpha_d_effective,
                alpha_d_up=alpha_d_up_effective,
                alpha_d_speech=alpha_d_speech_effective,
                speech_gate_p=noise_speech_gate_p,
                frame_gate_p=noise_frame_gate_p,
                gate_bin_start=speech_bin_start,
                gate_bin_end=speech_bin_end,
                slow_mask_max_frac=noise_gate_max_frac,
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
        self.noise_gate_lf_bin = (
            None if noise_gate_lf_hz is None
            else max(1, min(n_freqs, _hz_to_bin_ceil(noise_gate_lf_hz, fft_size, sample_rate)))
        )
        self.speech_protect_mask = np.zeros(n_freqs, dtype=bool)
        # The product speech guard is deliberately low-band only.  Its frame
        # evidence comes from the full speech band, but it must not lift
        # broadband noise or make every preset sound equally shallow. Without
        # noise_gate_lf_hz (a Python-only research configuration; the C port
        # always resolves the LF band) the floor covers the whole speech band.
        protect_end = (self.noise_gate_lf_bin
                       if self.noise_gate_lf_bin is not None else speech_bin_end)
        self.speech_protect_mask[1:protect_end] = True
        frame_prior_bin_start = max(
            1, _hz_to_bin_ceil(frame_prior_band_hz[0], fft_size, sample_rate))
        frame_prior_bin_end = min(
            n_freqs,
            _hz_to_bin_floor_inclusive(min(frame_prior_band_hz[1], sample_rate / 2.0),
                                       fft_size, sample_rate),
        )
        self.spp_estimator = SppEstimator(
            alpha=alpha_xi,
            q=q,
            xi_min_db=xi_min_db,
            cross_band_prior_strength=cross_band_prior_strength,
            cross_band_prior_threshold=cross_band_prior_threshold,
            cross_band_prior_full_scale=cross_band_prior_full_scale,
            cross_band_prior_max_q=cross_band_prior_max_q,
            cross_band_prior_alpha=cross_band_prior_alpha,
            cross_band_prior_bin_start=speech_bin_start,
            cross_band_prior_bin_end=speech_bin_end,
            frame_prior_q_max=frame_prior_q_max,
            frame_prior_spp_lo=frame_prior_spp_lo,
            frame_prior_spp_hi=frame_prior_spp_hi,
            frame_prior_bin_start=frame_prior_bin_start,
            frame_prior_bin_end=frame_prior_bin_end,
            frame_prior_track=frame_prior_gmin_lift_db is not None,
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
            spp_protect_floor_db=speech_protect_floor_db,
            spp_protect_threshold=speech_protect_threshold,
            floor_blend=floor_blend,
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
            if self.noise_over_subtraction != 1.0:
                noise_psd = self.noise_over_subtraction * noise_psd
            spp, xi, gamma = self.spp_estimator.estimate(
                Y_psd,
                noise_psd,
                self.gain_prev,
                enhanced_psd_prev
            )
            # SppEstimator returns the gain-side, cross-band-adjusted SPP but
            # retains the fixed-prior posterior separately.  MCRA must see the
            # latter; feeding the lifted posterior back into the tracker forms
            # a positive loop (lifted SPP freezes noise, which lifts later SPP
            # again) and diverges from the C streaming implementation.
            fixed_prior_spp = (
                self.spp_estimator.last_fixed_prior_spp
                if self.spp_estimator.last_fixed_prior_spp is not None
                else spp
            )
            if return_spp:
                spp_history.append(spp.copy())

            # Frame speech evidence: the mean SPP over the speech band (the
            # estimator's own evidence mean when it computed one) gates the LF
            # gain floor and blends the make-up; the fraction of speech-band
            # bins whose DD xi clears the gate drives the LF tracker guard.
            frame_spp_mean = self.spp_estimator.last_evidence_mean
            if frame_spp_mean is None:
                frame_spp_mean = self._speech_band_mean(fixed_prior_spp)
            speech_xi_fraction = (
                self._speech_band_mean(xi > self.noise_gate_xi)
                if self.noise_gate_xi is not None else None)
            protect_frame = (
                self.speech_protect_frame_threshold_effective is None
                or frame_spp_mean >= self.speech_protect_frame_threshold_effective
            )
            makeup_weight = frame_spp_mean
            if self.makeup_gain and self.makeup_prior == 'xi':
                indicator = min(
                    1.0, self._speech_band_mean(xi > self.makeup_prior_xi) / 0.15)
                self._makeup_prior_state += 0.1 * (indicator - self._makeup_prior_state)
                self._makeup_prior_state = max(self._makeup_prior_state, 0.01)
                makeup_weight = self._makeup_prior_state
            g_min_frame = None
            if self.frame_prior_gmin_lift_db is not None:
                g_min_frame = self.gain_calculator.g_min * 10 ** (
                    self.frame_prior_gmin_lift_db
                    * self.spp_estimator.last_frame_prior / 20.0)
            gain = self.gain_calculator.calculate(
                spp, xi, gamma,
                g_min=g_min_frame,
                spp_protect_enabled=protect_frame,
                spp_protect_mask=self.speech_protect_mask,
            )
            if return_noise_psd:
                # 估計器內部噪聲（尚未經 update()；即算此幀增益所用的噪聲底）
                noise_psd_history.append(self.noise_estimator.noise_psd.copy())

            enhanced_magnitude[i] = gain * noisy_magnitude[i]
            self.gain_prev = gain.copy()
            if self.dd_from_gmmse:
                enhanced_psd_prev = (
                    self.gain_calculator.last_gain_mmse * noisy_magnitude[i]) ** 2
            else:
                enhanced_psd_prev = enhanced_magnitude[i] ** 2

            applied_scale = 1.0
            if self.makeup_gain:
                e_in = float(np.sum(Y_psd))
                e_out = float(np.sum(enhanced_magnitude[i] ** 2))
                g_frame = np.sqrt(e_out / (e_in + 1e-20))
                scale_up = 1.0
                if g_frame > self.makeup_blim:
                    scale_up = 1.0 + self.makeup_up_slope * (g_frame - self.makeup_blim)
                    if g_frame * scale_up > 1.0:
                        scale_up = 1.0 / g_frame
                scale_down = 1.0
                if g_frame < self.makeup_blim:
                    g_floored = max(g_frame, self.gain_calculator.g_min)
                    scale_down = 1.0 - self.makeup_down_slope * (self.makeup_blim - g_floored)
                applied_scale = (
                    makeup_weight * scale_up
                    + (1.0 - makeup_weight) * scale_down
                )
                enhanced_magnitude[i] *= applied_scale
            if return_gain:
                # Report the gain that was actually applied. DD state above
                # intentionally retains the pre-makeup OM-LSA gain.
                gain_history.append((gain * applied_scale).copy())

            noise_update_spp = (fixed_prior_spp
                                if (self.spp_estimator.cross_band_prior_strength > 0.0
                                    or self.spp_estimator.frame_prior_q_max is not None)
                                else spp)
            if self.noise_gate_xi is None:
                self.noise_estimator.update(noisy_magnitude[i], spp=noise_update_spp)
            else:
                if self.noise_gate_lf_bin is None:
                    slow_mask = xi > self.noise_gate_xi
                else:
                    # One frame-level decision for every bin below the LF
                    # boundary, as in the C port.
                    slow_mask = np.zeros(xi.shape, dtype=bool)
                    if speech_xi_fraction > self.noise_gate_frame_frac:
                        slow_mask[:self.noise_gate_lf_bin] = True
                self.noise_estimator.update(noisy_magnitude[i], spp=noise_update_spp,
                                            slow_mask=slow_mask)

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

    def _speech_band_mean(self, x):
        """Mean of x over the 80-4000 Hz speech-evidence band."""
        return float(np.mean(x[self.speech_bin_start:self.speech_bin_end]))

    def reset(self):
        """重置降噪器狀態"""
        self.noise_estimator.reset()
        self.spp_estimator.reset()
        self.gain_calculator.reset()
        self.gain_prev = None
        self._makeup_prior_state = 0.5

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
            'cross_band_prior_strength': self.spp_estimator.cross_band_prior_strength,
            'cross_band_prior_threshold': self.spp_estimator.cross_band_prior_threshold,
            'cross_band_prior_full_scale': self.spp_estimator.cross_band_prior_full_scale,
            'cross_band_prior_max_q': self.spp_estimator.cross_band_prior_max_q,
            'cross_band_prior_alpha': self.spp_estimator.cross_band_prior_alpha,
            'noise_over_subtraction': self.noise_over_subtraction,
            'speech_protect_floor_db': self.gain_calculator.spp_protect_floor_db,
            'speech_protect_threshold': self.gain_calculator.spp_protect_threshold,
            'speech_protect_frame_threshold': self.speech_protect_frame_threshold,
            'speech_protect_frame_threshold_effective':
                self.speech_protect_frame_threshold_effective,
            'frame_prior_q_max': self.spp_estimator.frame_prior_q_max,
            'frame_prior_spp_lo': self.spp_estimator.frame_prior_spp_lo,
            'frame_prior_spp_hi': self.spp_estimator.frame_prior_spp_hi,
            'frame_prior_gmin_lift_db': self.frame_prior_gmin_lift_db,
            'floor_blend': self.gain_calculator.floor_blend,
            'noise_gate_lf_bin': self.noise_gate_lf_bin,
            'noise_gate_frame_frac': self.noise_gate_frame_frac,
            'noise_gate_xi_db': (None if self.noise_gate_xi is None
                                 else 10 * np.log10(self.noise_gate_xi)),
            'alpha_d_speech': (self.noise_estimator.alpha_d_speech
                               if self.noise_method == 'mcra' else None),
            'dd_from_gmmse': self.dd_from_gmmse,
            'makeup_gain': self.makeup_gain,
            'makeup_prior': self.makeup_prior,
            'makeup_prior_xi_db': 10 * np.log10(self.makeup_prior_xi),
            'makeup_blim': self.makeup_blim,
            'makeup_up_slope': self.makeup_up_slope,
            'makeup_down_slope': self.makeup_down_slope,
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
