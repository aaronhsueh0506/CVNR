"""
SPP Estimator - Speech Presence Probability 估計器
用於 V3 系列 (OM-LSA)
"""

import numpy as np
from typing import Tuple, Optional


def _band_slice(n_freqs, start, end):
    """Clamp an optional [start, end) bin range to the spectrum."""
    start = 0 if start is None else max(0, min(int(start), n_freqs - 1))
    end = n_freqs if end is None else max(start + 1, min(int(end), n_freqs))
    return start, end


def _ramp01(x, lo, hi):
    """(x - lo) / (hi - lo) clipped to [0, 1]."""
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


class SppEstimator:
    """
    估計語音存在機率 (Speech Presence Probability, SPP)

    SPP 是每個時頻點存在語音的機率，取值範圍 [0, 1]。
    這是一種軟判決方法，比硬判決（VAD）更平滑。

    參數:
        alpha: 先驗 SNR 平滑因子 (0.92-0.98)
        q: 語音先驗機率 (通常為 0.5)
        xi_min_db: 先驗 SNR 下限 (dB)

    參考文獻:
        Cohen & Berdugo (2001): "Speech Enhancement for Non-stationary Noise Environments"
    """

    def __init__(
        self,
        alpha: float = 0.98,
        q: float = 0.5,
        xi_min_db: float = -25.0,
        cross_band_prior_strength: float = 0.0,
        cross_band_prior_threshold: float = 0.50,
        cross_band_prior_full_scale: float = 0.70,
        cross_band_prior_max_q: float = 0.54,
        cross_band_prior_alpha: float = 0.90,
        cross_band_prior_bin_start: Optional[int] = None,
        cross_band_prior_bin_end: Optional[int] = None,
        # Frame-context speech prior (gain side only). When set, the speech
        # prior rises from q towards frame_prior_q_max as the mean fixed-prior
        # SPP over [frame_prior_bin_start, frame_prior_bin_end) climbs from
        # frame_prior_spp_lo to frame_prior_spp_hi. One scalar per frame; the
        # per-bin likelihood is unchanged, so weak bins in a frame with strong
        # speech evidence are released from the floor blend while noise-only
        # frames keep the fixed prior. None = shipped fixed prior.
        frame_prior_q_max: Optional[float] = None,
        frame_prior_spp_lo: float = 0.5,
        frame_prior_spp_hi: float = 0.8,
        frame_prior_bin_start: Optional[int] = None,
        frame_prior_bin_end: Optional[int] = None,
        # Track the frame prior (last_frame_prior) without re-prioring the
        # SPP, for consumers such as a frame-gated gain floor.
        frame_prior_track: bool = False,
    ):
        self.alpha = alpha
        # Clip q 到 (eps, 1-eps) 避免先驗比率的相撞歸零
        _eps = 1e-6
        self.q = float(np.clip(q, _eps, 1.0 - _eps))
        self.xi_min = 10 ** (xi_min_db / 10)

        # Experimental, low-cost frame/cross-band speech prior.  A zero
        # strength is the shipped path and deliberately bypasses every extra
        # reduction below.  The feature is computed from the fixed-prior SPP
        # that is already available in this function, so it adds no extra
        # exp/log; the embedded C implementation mirrors the same scalar path.
        if not 0.0 <= cross_band_prior_strength <= 1.0:
            raise ValueError("cross_band_prior_strength must be in [0, 1]")
        if not 0.0 < cross_band_prior_threshold < cross_band_prior_full_scale <= 1.0:
            raise ValueError(
                "cross-band prior thresholds must satisfy "
                "0 < threshold < full_scale <= 1"
            )
        if not 0.0 < cross_band_prior_max_q < 1.0:
            raise ValueError("cross_band_prior_max_q must be in (0, 1)")
        if (cross_band_prior_strength > 0.0
                and cross_band_prior_max_q < self.q):
            raise ValueError("enabled cross_band_prior_max_q must be >= q")
        if not 0.0 <= cross_band_prior_alpha < 1.0:
            raise ValueError("cross_band_prior_alpha must be in [0, 1)")
        self.cross_band_prior_strength = float(cross_band_prior_strength)
        self.cross_band_prior_threshold = float(cross_band_prior_threshold)
        self.cross_band_prior_full_scale = float(cross_band_prior_full_scale)
        self.cross_band_prior_max_q = float(cross_band_prior_max_q)
        self.cross_band_prior_alpha = float(cross_band_prior_alpha)
        self.cross_band_prior_bin_start = cross_band_prior_bin_start
        self.cross_band_prior_bin_end = cross_band_prior_bin_end
        self.cross_band_prior_state = 0.0
        self.last_effective_q = self.q
        self.last_fixed_prior_spp = None
        # Mean over the evidence band of the SPP this estimator returns (after
        # the frame prior, before the cross-band lift); None while the
        # cross-band prior is off.
        self.last_evidence_mean = None

        if frame_prior_q_max is not None and not self.q < frame_prior_q_max < 1.0:
            raise ValueError("frame_prior_q_max must be None or in (q, 1)")
        if not 0.0 <= frame_prior_spp_lo < frame_prior_spp_hi <= 1.0:
            raise ValueError("frame prior ramp must satisfy 0 <= lo < hi <= 1")
        self.frame_prior_q_max = (float(frame_prior_q_max)
                                  if frame_prior_q_max is not None else None)
        self.frame_prior_spp_lo = float(frame_prior_spp_lo)
        self.frame_prior_spp_hi = float(frame_prior_spp_hi)
        self.frame_prior_bin_start = frame_prior_bin_start
        self.frame_prior_bin_end = frame_prior_bin_end
        self.frame_prior_track = bool(frame_prior_track)
        self.last_frame_prior = 0.0

        # 狀態變量（用於 Decision Directed 方法）
        self.xi_prev = None         # 上一幀的先驗 SNR
        self.gamma_prev = None      # 上一幀的後驗 SNR
        self.noise_psd_prev = None  # 上一幀的噪聲 PSD（DD 需要同步）
        self.frame_count = 0

    def estimate(
        self,
        Y_psd: np.ndarray,
        noise_psd: np.ndarray,
        gain_prev: Optional[np.ndarray] = None,
        enhanced_psd_prev: Optional[np.ndarray] = None,
        alpha_override: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        估計 SPP

        v1.5.0: 修正 DD 公式使用當前幀噪聲 λ_n

        參數:
            Y_psd: 帶噪語音功率譜密度 (n_freqs,)
            noise_psd: 噪聲功率譜密度 (n_freqs,)
            gain_prev: 上一幀的增益（可選，用於 Decision Directed）
            enhanced_psd_prev: 上一幀增強後的功率譜 |X̂_{n-1}|²（可選，v1.5.0 新增）
              注意：DD 第一項 α·gain_prev²·Y_psd_prev 使用的是 PREVIOUS frame 的 λ_d（即
              enhanced_psd_prev / noise_psd_prev），此處以 gain_prev²·Y_psd 近似。

        返回:
            spp: 語音存在機率 (n_freqs,)
            xi: 先驗 SNR (n_freqs,)
            gamma: 後驗 SNR (n_freqs,)
        """
        # 1. 計算後驗 SNR (a posteriori SNR)
        gamma = Y_psd / (noise_psd + 1e-10)

        # 2. 估計先驗 SNR (a priori SNR) - Decision Directed 方法
        if self.xi_prev is None or gain_prev is None:
            # 初始化：使用直接估計
            xi = np.maximum(gamma - 1, 0)
        else:
            # Ephraim-Malah (1984) 標準 DD：
            #   ξ(k,l) = α · |X̂(k,l-1)|² / λ_d(k,l-1) + (1-α) · max(γ(k,l)-1, 0)
            # 分母必須用「上一幀」的 λ_d，因為 |X̂(k,l-1)|² 本身就是用 λ_d(k,l-1) 算出來的；
            # 兩者同步才能保持統計一致。若用當前幀 λ_d，噪聲更新後 ξ 會被錯誤縮放。
            assert enhanced_psd_prev is not None, \
                "enhanced_psd_prev must be provided for Decision Directed estimation"

            # noise_psd_prev 為 None 時（理論上不應發生，保險起見），降級到當前幀
            noise_for_dd = self.noise_psd_prev if self.noise_psd_prev is not None else noise_psd

            # 支援 alpha_override 做 per-bin 頻段自適應（可選；預設 None）
            alpha_effective = alpha_override if alpha_override is not None else self.alpha
            xi_dd_term1 = enhanced_psd_prev / (noise_for_dd + 1e-10)
            xi_dd = alpha_effective * xi_dd_term1 + \
                    (1 - alpha_effective) * np.maximum(gamma - 1, 0)
            xi = np.maximum(xi_dd, self.xi_min)

        # 3. 計算對數似然比
        # Λ(k,l) = ξ/(1+ξ) · γ
        log_likelihood = xi / (1 + xi) * gamma

        # [Old / Buggy Code]
        # spp = 1 / (1 + (self.q / (1 - self.q)) * np.exp(-log_likelihood))
        # 問題：
        # 1. q 的比率寫反了，導致 q 代表的意義顛倒。
        # 2. 少了 (1+xi) 項，這項在低 SNR 時能幫助壓低 SPP。

        # [Fixed Code]
        # 使用 Cohen & Berdugo (2001) 標準公式
        # 修正比率為 (1-q)/q，並加入 (1+xi) 項
        
        # 防止溢位: 限制 (1+xi) 不超過合理範圍
        term_xi = 1 + xi
        
        # 計算先驗比率 (1-q)/q
        # q 已在 __init__ 中 clip 到 (eps, 1-eps)，此處無需額外保護
        prior_ratio = (1 - self.q) / self.q

        # 組合公式: 1 / (1 + prior_ratio * (1+xi) * exp(-v))
        # 注意 log_likelihood 變數存的是 v (gamma * xi / (1+xi))
        exp_neg_likelihood = np.exp(-log_likelihood)
        spp = 1 / (1 + prior_ratio * term_xi * exp_neg_likelihood)
        # Preserve the fixed-prior posterior for the noise tracker.  The
        # cross-band prior is a gain-side speech-protection mechanism; feeding
        # it back into the noise update creates a positive feedback loop
        # (raised SPP freezes N, which raises later SPP again).
        self.last_fixed_prior_spp = spp

        if self.frame_prior_q_max is not None or self.frame_prior_track:
            start, end = _band_slice(spp.shape[0], self.frame_prior_bin_start,
                                     self.frame_prior_bin_end)
            frame_prior = _ramp01(float(np.mean(spp[start:end])),
                                  self.frame_prior_spp_lo, self.frame_prior_spp_hi)
            self.last_frame_prior = frame_prior
            if self.frame_prior_q_max is not None:
                q_frame = self.q + (self.frame_prior_q_max - self.q) * frame_prior
                spp = 1 / (1 + (1 - q_frame) / q_frame * term_xi * exp_neg_likelihood)

        # Cross-band protection: if speech evidence is coherent across the
        # configured speech band, lift the prior for weak bins in this same
        # frame.  This is intentionally protection-only: effective_q never
        # falls below the preset q, so a false negative cannot become worse
        # than the shipped fixed-prior path.  Strong bins are already near
        # SPP=1 and therefore barely change; the lift mostly helps weak
        # harmonics whose local likelihood alone is ambiguous.
        if self.cross_band_prior_strength > 0.0:
            start, end = _band_slice(spp.shape[0], self.cross_band_prior_bin_start,
                                     self.cross_band_prior_bin_end)
            evidence_mean = float(np.mean(spp[start:end]))
            self.last_evidence_mean = evidence_mean
            target = _ramp01(evidence_mean, self.cross_band_prior_threshold,
                             self.cross_band_prior_full_scale)
            a = self.cross_band_prior_alpha
            self.cross_band_prior_state = (
                a * self.cross_band_prior_state + (1.0 - a) * target
            )
            effective_q = self.q + (
                self.cross_band_prior_strength
                * self.cross_band_prior_state
                * (self.cross_band_prior_max_q - self.q)
            )
            effective_q = float(np.clip(effective_q, self.q,
                                        self.cross_band_prior_max_q))
            # First-order logit lift around the balanced q=0.5 point. It
            # matches exact re-prioring at SPP=0.5 and avoids a second vector
            # divide; q_max=0.54 keeps this approximation deliberately small.
            lift = 4.0 * (effective_q - self.q)
            spp = spp + lift * spp * (1.0 - spp)
            self.last_effective_q = effective_q
        else:
            self.last_effective_q = self.q
            self.last_evidence_mean = None

        # 保存當前值供下一幀使用
        self.xi_prev = xi
        self.gamma_prev = gamma
        self.noise_psd_prev = noise_psd.copy()  # DD 需要「上一幀」的噪聲 PSD
        self.frame_count += 1

        return spp, xi, gamma

    def reset(self):
        """重置狀態"""
        self.xi_prev = None
        self.gamma_prev = None
        self.noise_psd_prev = None
        self.frame_count = 0
        self.cross_band_prior_state = 0.0
        self.last_effective_q = self.q
        self.last_fixed_prior_spp = None
        self.last_evidence_mean = None
        self.last_frame_prior = 0.0

    def __repr__(self):
        return (f"SppEstimator(alpha={self.alpha}, q={self.q}, "
                f"xi_min={10 * np.log10(self.xi_min):.1f} dB)")


def compute_spp_batch(
    Y_psd: np.ndarray,
    noise_psd: np.ndarray,
    alpha: float = 0.98,
    q: float = 0.5,
    xi_min_db: float = -25.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    批量計算 SPP（用於離線處理）

    v1.5.0: 支持正確的 DD 計算（使用當前幀噪聲）

    參數:
        Y_psd: 帶噪語音功率譜密度 (n_frames, n_freqs)
        noise_psd: 噪聲功率譜密度 (n_frames, n_freqs) 或 (n_freqs,)
        alpha: 先驗 SNR 平滑因子
        q: 語音先驗機率
        xi_min_db: 先驗 SNR 下限 (dB)

    返回:
        spp: 語音存在機率 (n_frames, n_freqs)
        xi: 先驗 SNR (n_frames, n_freqs)
        gamma: 後驗 SNR (n_frames, n_freqs)
    """
    estimator = SppEstimator(alpha=alpha, q=q, xi_min_db=xi_min_db)

    n_frames = Y_psd.shape[0]
    n_freqs = Y_psd.shape[1]

    # 初始化輸出
    spp = np.zeros_like(Y_psd)
    xi = np.zeros_like(Y_psd)
    gamma = np.zeros_like(Y_psd)

    # v1.5.0: 追蹤增強功率譜
    gain_prev = None
    enhanced_psd_prev = None

    # 逐幀處理
    for i in range(n_frames):
        if noise_psd.ndim == 1:
            noise_frame = noise_psd
        else:
            noise_frame = noise_psd[i]

        spp[i], xi[i], gamma[i] = estimator.estimate(
            Y_psd[i],
            noise_frame,
            gain_prev,
            enhanced_psd_prev
        )

        # 簡單估計增益（用於下一幀）
        # 這裡使用 Wiener 增益作為近似
        gain_prev = xi[i] / (1 + xi[i])

        # v1.5.0: 計算增強功率譜供下一幀使用
        enhanced_psd_prev = (gain_prev ** 2) * Y_psd[i]

    return spp, xi, gamma
