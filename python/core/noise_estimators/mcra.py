"""
MCRA-based Noise Estimator (MCRA-lite — NOT canonical IMCRA; see NOTE).

Minimum-tracking noise-PSD estimation (Cohen & Berdugo 2002). The
`accept_external_spp` constructor flag selects what drives the noise-update gate:

  accept_external_spp=True  (default — standalone NR):
    Gate uses the OM-LSA posterior SPP passed in from the denoiser (falling back
    to the internal min-stat SPP if none is given). The external DD-smoothed
    posterior gives more reliable per-bin speech protection than the internal
    binary min-ratio test, and pairs naturally with the OM-LSA gain.

  accept_external_spp=False  (AEC pipeline):
    Gate always uses the internal min-stat indicator. Use when the caller's
    OM-LSA posterior is unreliable (e.g. residual echo inflates the posterior in
    noise-only bins, which would freeze noise tracking).

NOTE — this is MCRA-lite, not canonical IMCRA. It does single-pass minimum
tracking + a posterior-gated recursive average, but deliberately OMITS IMCRA's
(Cohen 2003) distinctive additions: the two-iteration minimum smoothing
(rough-VAD exclusion before the minimum) and the B_min bias compensation.
Reconnecting the internal minimum-controlled gate as the noise-update driver
regressed speech (−0.632 PESQ / 824 VCTK) and is intentionally not used.

References:
    Cohen, I. & Berdugo, B. (2002). "Noise estimation by minima controlled
    recursive averaging." IEEE Signal Processing Letters, 9(1), 12-15.
    Cohen, I. (2003). "Noise spectrum estimation in adverse environments:
    Improved minima controlled recursive averaging." IEEE Trans. Signal
    Processing, 51(2), 466-475.  (IMCRA — NOT fully implemented here; see NOTE.)
"""

import numpy as np
from typing import Optional


def _spectral_flatness(power_band: np.ndarray) -> float:
    """Geometric-mean / arithmetic-mean spectral flatness of a power band (∈ (0,1]).
    ~0.1-0.2 for voiced/tonal content, ~0.5-0.7 for white noise."""
    p = power_band + 1e-20
    return np.exp(np.mean(np.log(p))) / np.mean(p)


class McraNoiseEstimator:
    """
    MCRA-lite 噪聲估計器（gate 由 accept_external_spp 控制，見 module docstring；非 canonical IMCRA）

    演算法步驟：
    1. 時間平滑：S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
    2. 最小值追蹤：S_min(k,l) = min{S(k,τ): l-L+1 ≤ τ ≤ l}
    3. 內部語音指示器：I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
    4. 內部 SPP 平滑：p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
    5. 噪聲更新 gate：
         external-gate (accept_external_spp=True):  spp_gate = external OM-LSA posterior (else self.spp)
         internal-gate (accept_external_spp=False): spp_gate = self.spp
       α̃_d = α_d + (1-α_d)·spp_gate
       N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²

    參數:
        alpha_s: 時間平滑因子 (0.85-0.95)
        alpha_d: 噪聲更新基礎速率 (0.70-0.90)
        alpha_p: 內部 SPP 平滑因子 (0.1-0.3)
        L: 最小值窗口長度（幀）
        delta_db: 語音偵測偏差補償（dB）
        num_init_frames: 初始化幀數
        accept_external_spp: True = IMCRA mode；False = plain MCRA mode
    """

    # Below this the 1e-10 epsilons in every consumer of noise_psd dominate it
    # (float32: 1e-10 + N == 1e-10 for N < ~6e-18), so the estimate can no
    # longer influence anything and, after a signal returns, can no longer be
    # updated either (see update()). Any real signal scale sits >30 orders
    # above it. Mirrored by MCRA_NOISE_PSD_INERT in the C port.
    NOISE_PSD_INERT = 1e-20

    # Consecutive miss frames the fricative-confirm guard tolerates without
    # discarding an in-progress streak (see update()'s scene-change block).
    # Only consulted when scene_change_confirm_frames > 0.
    SCENE_CHANGE_MISS_TOLERANCE = 3

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        broadband_threshold: float = 0.8,
        # 場景轉換偵測參數（高頻段 γ + spectral flatness 聯合判斷；
        # flatness 用於避免語音誤觸發，因語音 flatness 較低）
        scene_change_threshold_db: float = 10.0,
        scene_change_min_frames: int = 5,
        scene_change_blend: float = 0.5,
        scene_change_flatness_threshold: float = 0.4,
        # Fricative guard: a true broadband scene/noise-floor change (fan
        # turning on, mic moved) keeps hi_gamma+flatness elevated against the
        # still-stale noise estimate for as long as the estimate stays stale
        # -- i.e. indefinitely, until the reset itself updates it. A fricative
        # is bounded in duration (50-150 ms) and its own energy decays within
        # that span, so the SAME elevated-condition streak that triggers the
        # reset at scene_change_min_frames breaks on its own shortly after.
        # Measured on DNS2020 (150 files, no_reverb test set, 16 kHz), with a
        # FROZEN pre-fire noise floor and no miss tolerance (a lower bound,
        # not the live streak the shipped guard below actually sees): past
        # the normal fire point the condition extends a median of 2 and at
        # most 15 EXTRA frames (8 ms hop) on frames landing on real speech,
        # whereas a synthetic genuine step (+13.5..+30 dB, white noise)
        # never broke inside a lookahead of 62 frames. Driving the live
        # estimator end to end (not the frozen probe) across a 12-20 frame
        # sweep suppressed 94-99% of the DNS2020 false fires, consistent
        # with the probe; 12 is the recommended 16 kHz/256 operating value
        # (see KNOWN LIMITATION below for why 16, the probe-margin value,
        # is worse on non-white existence steps despite higher suppression:
        # 93.9% suppression / 0.974 oracle-gain ratio / pause-residual cost
        # median 0.000, mean 0.154 dB at confirm_frames=12, all comfortably
        # inside the registered limits). Requiring the condition to additionally hold for
        # `scene_change_confirm_frames` MORE consecutive frames before
        # committing the reset therefore separates the two by shape
        # (sustained vs. self-terminating), not by cooldown after the fact
        # (that is `V-hold`, tested separately and found to have no effect
        # because it does not touch the frame that fires the FIRST time)
        # and not by requiring a second, independent band to also show
        # elevated energy (that is `V-broadband`, tested and found to
        # suppress genuine low-pause-depth noise scenes outright because it
        # is a different, stricter trigger condition rather than a
        # confirmation of the existing one). 0 = off (default; bit-exact
        # with the shipped trigger). Not retimed across grids BY DESIGN --
        # UNLIKE scene_change_min_frames (which v3_2_mmse_lsa.py's 'full'
        # mode DOES retime via retime_frame_count() -- see the retiming
        # caveat on scene_change_confirm_window below), this is a raw hop
        # count validated per grid directly against McraNoiseEstimator (see
        # test_scene_change_confirm_frames.py), not a wall-clock value.
        #
        # KNOWN LIMITATION (measured, not resolved): the existence guard
        # (a genuine step must still recover within ~0.3 s) was validated
        # above only against WHITE-noise steps. A step whose amplitude is
        # itself modulated (e.g. +-3 dB at 3 Hz, a crude babble/wind proxy)
        # or 1/f-colored can dip the trigger condition below threshold for
        # longer than SCENE_CHANGE_MISS_TOLERANCE covers, which can delay
        # or prevent the first confirmation past the 0.3 s budget. At 16
        # kHz/256, confirm_frames=12 passed white (0/20 seeds), the +-3dB/
        # 3Hz AM proxy (0/20), and pink noise at a reduced but nonzero rate
        # (1/20); confirm_frames=16 (the probe-margin value) was WORSE on
        # pink (6/20) for no suppression benefit worth the risk (93.9% vs
        # 98.0%). At 16 kHz/512 and 48 kHz/1024 the SAME AM proxy failed
        # 100% of seeds tried at the operating values below (10, 18).
        #
        # "Safe at 16 kHz/256" is NOT a grid property -- it is a
        # confirmation-window-vs-modulation-period boundary that 256
        # happens to sit just inside of for the ONE AM rate tested (3 Hz).
        # From first principles: confirmation needs (min_frames + confirm)
        # hit frames with gaps <= SCENE_CHANGE_MISS_TOLERANCE; at
        # 256/confirm=12 that window is ~136 ms with a ~24 ms gap budget,
        # which just clears a 3 Hz half-period (~167 ms) but NOT a 4 Hz
        # one -- at 512/confirm=10 and 48k/1024/confirm=18 the window is
        # wider (~240-245 ms) and a 3 Hz half-period already fails it,
        # which is why those two grids show 100% AM failure while 256
        # shows 0%. The SAME latent boundary exists at 256; it has simply
        # not been hit by the one modulation frequency used in this
        # sweep. Syllabic/babble/wind modulation commonly runs 3-8 Hz,
        # i.e. partly ABOVE this boundary even at 256 -- consistent with
        # the pink-noise failure already measured here (1/20 at
        # confirm=12). Do not read "0/20 at 256" as "safe to enable at
        # 256"; read it as "not yet shown unsafe at 256, at the one rate
        # tried." This is a property of requiring a long CONTINUOUS run
        # rather than a fractional window, and is not fixed by raising
        # SCENE_CHANGE_MISS_TOLERANCE alone (tried up to 5; still fails).
        # Measured and reproduced structurally with a 50%-duty AM probe
        # (see scene_change_confirm_window's docstring, which replaces
        # this run-length test for the first fire of an episode and does
        # not have this failure mode, at the cost of weaker false-fire
        # rejection as the window widens past its matched-k point).
        #
        # The acceptance bar previously used to validate confirm_frames
        # also omitted a registered guard requiring an HF-only rise (e.g.
        # hiss/wind) to recover within ~0.4 s -- exactly what the
        # modulated-amplitude case above probes.
        #
        # Do NOT enable at ANY grid in production without testing against
        # modulation rates up to ~8 Hz (not just 3 Hz) and the full
        # registered acceptance bar, including the ~0.4 s HF-only
        # recovery guard.
        scene_change_confirm_frames: int = 0,
        # scene_change_confirm_frames requires an UNBROKEN RUN (up to
        # SCENE_CHANGE_MISS_TOLERANCE consecutive misses) of hit frames
        # before confirming. Measured (k_held_sweep, DNS2020 60 files,
        # 16 kHz/256): any single gap longer than the tolerance restarts
        # the run, so a step whose hit/miss pattern is scattered rather
        # than contiguous (ordinary measurement noise over a long required
        # run, or a modulated/colored source) can fail to accumulate the
        # run at all. A synthetic 50%-duty-cycle AM probe (depth deep
        # enough to cross scene_change_threshold on the trough, baseline
        # at the threshold) reproduces this structurally: the shipped
        # run-length mechanism at its 16 kHz/256 operating value
        # (confirm_frames=12) confirms a 3 Hz step but NEVER confirms at
        # 4-8 Hz within a 300-frame budget; at 16 kHz/512 and 48 kHz/1024
        # it fails at every rate 3-8 Hz including 3 Hz. The gentler
        # +-3 dB AM proxy this value was originally validated against
        # never actually dips the ENERGY half of the trigger below
        # threshold at all (duty cycle 1.0, measured) -- it was not
        # exercising this failure mode in the first place.
        #
        # scene_change_confirm_window replaces the run-length test for the
        # FIRST fire of an episode with a trailing-WINDOW true-frame
        # FRACTION: over the last (scene_change_min_frames +
        # scene_change_confirm_window) frames, at least
        # scene_change_confirm_frac of them must be hits (the same
        # hi_gamma+flatness decision the ordinary trigger already computes
        # every frame, pushed into a ring buffer every frame regardless of
        # branch). A scattered or periodic miss pattern only lowers the
        # window's hit fraction by its duty cycle; it does not restart a
        # run, so confirmation is RATE independent at a GIVEN duty cycle
        # (unlike run-length mode, which additionally depends on the
        # absolute dip duration against a fixed miss tolerance). On the
        # SAME 50%-duty AM probe, window mode at confirm_frac=0.5 (<= the
        # stimulus's own duty cycle) confirms at every rate 3-8 Hz within
        # budget at both grids tried.
        #
        # THE REAL LIMIT (measured): confirm_frac is a hard FLOOR on the
        # average hit fraction the window can ever reach -- waiting
        # longer or trying a different rate does not help. At
        # confirm_frac=0.773 (the value matched to legacy's own false-fire
        # suppression at 16 kHz/256, below), the SAME 50%-duty AM step
        # NEVER confirms at any rate within 2000 frames, because the
        # window's achievable hit count caps at ~50% of its size --
        # strictly below the 77.3% required. A frac high enough to match
        # legacy's fricative rejection and a duty cycle below that frac
        # are mutually exclusive; the windowed-fraction mechanism does not
        # escape that, it only makes the trade-off tunable along a
        # duty-cycle axis instead of failing outright above a fixed,
        # grid-dependent rate.
        #
        # MEASURED at 16 kHz/256 (W = min_frames + confirm_window swept,
        # required_hits = ceil(frac * W) per the formula below, DNS2020
        # 60 files, real denoiser, real false-fire log):
        #   W=17  (frac=1.00, confirm_window=12, required_hits=17) ->
        #         98.3% suppression (no miss tolerance at all -- stricter
        #         than legacy)
        #   W=22  (frac=0.773, confirm_window=17, required_hits=18 --
        #         ceil(0.773*22)=18, NOT the 17 this round's own narrative
        #         intended; left uncorrected below as a documentation note,
        #         not re-measured against the intended 17) -> 93.3%
        #         suppression, MATCHING legacy confirm_frames=12's 93.3% at
        #         its own k=17, while tolerating up to 4 misses anywhere in
        #         the window (22 - required_hits=18) instead of legacy's 3
        #         CONSECUTIVE (this number was measured by running the
        #         shipped formula, i.e. against the real required_hits=18,
        #         not the intended-but-never-shipped 17)
        #   W=27  (frac=0.630) -> 91.7%;  W=32 (frac=0.531) -> 86.7%;
        #         W=37 (frac=0.459) -> 78.3% (suppression degrades as the
        #         window widens past the matched-k point)
        # A2 (broadband, <=0.3s) and A3 (HF-only, <=0.4s) existence guards
        # both pass at all 3 project grids for a sustained step (duty 1.0)
        # at confirm_window/frac matched to each grid's legacy k -- a
        # continuous step reaches the required hit count at frame k
        # regardless of W, so W's cost shows up in false-fire suppression,
        # not in existence-guard recovery time.
        #
        # BUDGET WALL at 16 kHz/512 and 48 kHz/1024 (not a window-mode
        # deficiency -- this binds scene_change_confirm_frames equally):
        # legacy's own k there (15 / 23 hit frames) already consumes
        # ~240-245 ms of the 300 ms A2 budget, leaving ~0 ms of slack for
        # ANY dip tolerance -- window or run-length -- without lowering k
        # below legacy's own fricative-rejection strength. Neither
        # mechanism can hold legacy's suppression AND tolerate a
        # sub-100%-duty step at those two grids; this was not re-measured
        # per-grid beyond the arithmetic.
        #
        # NOT measured: pink noise (an attempted 1/f probe was a stimulus
        # bug -- 1/f noise puts negligible energy in the upper half-band
        # this trigger looks at, so the recovery metric never engaged for
        # EITHER mechanism; dropped rather than reported); the full
        # registered A1/A4/A5 bar closed-loop (pause-residual, oracle-gain
        # ratio, PESQ/STOI) for window mode specifically. Window mode and
        # legacy run-length mode are NOT nested in either direction on a
        # given hit/miss sequence -- legacy's N-CONSECUTIVE tolerance and
        # window's M-ANYWHERE tolerance each accept sequences the other
        # rejects (e.g. one long gap vs several short gaps totalling more
        # misses), so neither mode's validated numbers can be inherited
        # from the other by a dominance argument. A1/A4/A5 for window mode
        # require their own independent closed-loop run.
        #
        # RECOMMENDATION (not a shipped default): at 16 kHz/256 only,
        # confirm_window=17, confirm_frac=0.773 (required_hits=18, see the
        # measurement note above -- NOT 17 despite that being this round's
        # original intent) matches legacy's own fricative-rejection
        # strength with materially better modulation-rate robustness. Not
        # recommended at 512/48k (budget wall above).
        # Do NOT enable in production without the A1/A4/A5 closed-loop
        # re-run and a real (not pink) colored-noise check.
        #
        # 0 = off (default); when off, scene_change_confirm_frames
        # (run-length mode, itself also default 0 = the shipped unguarded
        # trigger) governs the first-fire gate exactly as before --
        # bit-exact to shipped behaviour (verified empirically against the
        # pre-this-change source, 64 configurations x 2000 frames, 0
        # mismatches): no new state is touched, no new codepath runs.
        # Mutually exclusive with scene_change_confirm_frames > 0 (window
        # mode fully replaces the first-fire run-length test, so a nonzero
        # confirm_frames alongside it would silently be dead code; enforced
        # at construction).
        # Re-fires within an already-confirmed episode always use the plain
        # scene_change_min_frames threshold in BOTH modes, same as today.
        # See test_scene_change_confirm_window.py.
        #
        # NOT REACHABLE FROM ANY SHIPPED CONFIG SURFACE: MmseLsaDenoiser
        # (denoisers/v3_2_mmse_lsa.py) and process_audio.py only plumb
        # scene_change_confirm_frames through to this estimator --
        # confirm_window/confirm_frac have no constructor parameter, CLI
        # flag, YAML key or NR_MODE_PRESETS entry anywhere in this repo.
        # Every number below was measured by constructing
        # McraNoiseEstimator directly, not by running the denoiser/
        # process_audio config path.
        #
        # RETIMING CAVEAT (applies to confirm_frames above too): the k/W
        # arithmetic quoted in both params' docstrings (k=17/15/23, W=22
        # required_hits=18, the "legacy's own k there (15/23 hit frames)"
        # budget-wall note) is computed with scene_change_min_frames=5 --
        # i.e. UNRETIMED (both test files also hardcode MIN_FRAMES=5). For
        # confirm_window this is forced: it has no path through the
        # denoiser at all (see above), so nothing that measured it could
        # have used a retimed min_frames. For confirm_frames it is NOT
        # forced -- confirm_frames IS plumbed through MmseLsaDenoiser, so a
        # live-estimator DNS2020 sweep run through the denoiser would have
        # used whatever min_frames the denoiser retimes to; which harness
        # path actually produced confirm_frames' live-estimator suppression
        # percentages is not recorded here.
        #
        # What IS verifiable from retime_frame_count() alone: MmseLsaDenoiser's
        # 'full' mode retimes the authored scene_change_min_frames=5
        # (config/v3_2_config.yaml) to 7 at 16 kHz/256, 4 at 16 kHz/512, 5 at
        # 48 kHz/1024 -- confirm_frames/confirm_window are deliberately NOT
        # retimed themselves. So the k/W arithmetic quoted above (computed at
        # min_frames=5) is not the required-hit count the denoiser would
        # actually enforce at the SAME confirm_frames/confirm_window value,
        # except by coincidence at 48 kHz/1024:
        #   16 kHz/256: quoted at k=17 / required_hits=18 -- the denoiser
        #     would enforce k=19 at confirm_frames=12, and required_hits=19
        #     at confirm_window=17/frac=0.773 (ceil(0.773*24)=19). The two
        #     mechanisms' denoiser-enforced thresholds coincide here, which
        #     is retiming-and-rounding arithmetic, not mechanism identity:
        #     the "NOT measured" paragraph above already establishes the
        #     two modes are not nested on a given hit/miss sequence, so an
        #     equal k does not make them decide alike on every input, only
        #     on the ones a real false-fire corpus happens to produce.
        #   16 kHz/512: quoted at k=15 -- the denoiser would enforce k=14
        #     at confirm_frames=10 (confirm_window has no 512 recommendation
        #     to compare).
        #   48 kHz/1024: quoted at k=23 -- the denoiser enforces k=23 too,
        #     unchanged (the only grid where authored and retimed
        #     min_frames coincide).
        # Neither mechanism's suppression/existence-guard percentages have
        # been re-measured at the denoiser-enforced k/required_hits; only
        # the arithmetic above follows directly from retime_frame_count().
        scene_change_confirm_window: int = 0,
        # Required hit fraction within the trailing
        # scene_change_confirm_window; only consulted when that window is
        # > 0. No single value is safe at every grid -- see the
        # measurements above. 0.773 is the only value this round actually
        # validated (at 16 kHz/256, confirm_window=17); the default here is
        # inert unless confirm_window is also set.
        scene_change_confirm_frac: float = 0.773,
        # IMCRA/MCRA mode switch
        accept_external_spp: bool = True,  # True=IMCRA, False=plain MCRA
        # Direction-aware noise update. None keeps the symmetric recursion.
        # When set, a bin whose power exceeds its current noise estimate (the
        # rising direction) is blended with this slower base rate instead of
        # alpha_d, so speech that the posterior only partly flags cannot
        # ratchet the floor upward; the falling direction keeps alpha_d.
        alpha_d_up: Optional[float] = None,
        # Speech-gated slow update. In a bin whose gating probability exceeds
        # speech_gate_p the base rate becomes alpha_d_speech and the estimate
        # may only FALL at the ordinary rate, never rise faster than the slow
        # one; bins below the gate keep the shipped symmetric update, so the
        # noise-only steady state is unbiased. None keeps the shipped path.
        alpha_d_speech: Optional[float] = None,
        speech_gate_p: float = 0.2,
        # Optional frame-level condition on the slow update: it engages only
        # when the mean gating probability over [gate_bin_start, gate_bin_end)
        # exceeds frame_gate_p, so bins in a noise-only frame keep the
        # ordinary symmetric update whatever their individual probability.
        frame_gate_p: Optional[float] = None,
        gate_bin_start: int = 0,
        gate_bin_end: Optional[int] = None,
        # Broadband-onset escape: when more than this fraction of bins is
        # gated in one frame the rise is a noise-scene change, not speech, and
        # the ordinary update is kept so a level step is still tracked.
        slow_mask_max_frac: Optional[float] = None,
        # arm 4 (R²→tracker decoupling, post-hoc variant): when the caller
        # passes `extra_noise_psd` into update(), the ordinary (unmodified)
        # recursion still runs first — this does NOT change tilde_alpha_d or
        # which spp drives it. Afterward, per bin, the fraction of THIS
        # frame's positive noise_psd rise that is explainable by the supplied
        # extra (R²-derived) power is subtracted back out. Only a bin whose
        # estimate rose AND whose frame power exceeded the pre-update estimate
        # is touched; a falling bin, or one with no extra power, is untouched.
        # Default False keeps update() exactly as shipped even if a caller
        # passes extra_noise_psd (belt-and-suspenders for callers that forget
        # to gate it).
        #
        # SCENE-CHANGE-TRIGGER INTERACTION, FIXED: this correction used to
        # only touch noise_psd, leaving the scene-change trigger's
        # hi_gamma computed on raw, echo-included power -- when the
        # supplied extra explained most of a bin's rise, the reset's own
        # action was undone by this correction while its trigger condition
        # (computed from uncorrected power) never cleared, so the reset
        # could fire every scene_change_min_frames for the whole echo
        # episode instead of once, re-stomping S_min/min_buffer with
        # echo-polluted power on every fire. hi_gamma's energy test (not
        # its flatness test -- see the comment at its computation site)
        # now uses the SAME echo-corrected power this correction implies,
        # and a fire's S_min/min_buffer write uses the same correction the
        # noise_psd write already receives, so this no longer happens:
        # reproduced on a synthetic sustained 95%-echo-explained rise
        # (80 fires over 400 frames before this fix, 0 after -- see
        # test_echo_dominated_rise_no_longer_refires_repeatedly).
        #
        # MEASURED on the real AEC-Challenge-2021-blind far-end-singletalk
        # files this flag's own acceptance round used (20 files, 16 kHz/
        # 256, through the real AEC+NR pipeline with inject_echo_psd):
        # genuine scene-change commits are rare on this corpus regardless
        # -- 1 total across all 20 files, identical before and after this
        # fix. The pooled-FS AECMOS echo-score CI this flag was rejected
        # on is UNCHANGED: [-0.0731, -0.0152] vs the prior round's
        # [-0.0723, -0.0152] at 16 kHz/256 (still FAILS the >= -0.05 CI
        # lower-bound bar), [-0.0607, -0.0091] vs [-0.0596, -0.0093] at
        # 16 kHz/512 (also still FAILS). This hazard was real (and is now
        # fixed) but was NOT the mechanism behind arm 4's FS-echo cost on
        # this corpus -- that cost comes from the ordinary per-frame
        # correction itself (holding noise_psd below the echo-inflated
        # level during sustained far-end-only echo, which lets more
        # residual echo through the gain stage), independent of whether
        # any scene-change reset ever fires. Still do NOT set this True in
        # production: the flag does not clear its acceptance bar, for a
        # different reason than previously documented here.
        remove_echo_explained_rise: bool = False,
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        if alpha_d_up is not None and not 0.0 <= alpha_d_up < 1.0:
            raise ValueError("alpha_d_up must be None or in [0, 1)")
        self.alpha_d_up = alpha_d_up
        if alpha_d_speech is not None and not 0.0 <= alpha_d_speech < 1.0:
            raise ValueError("alpha_d_speech must be None or in [0, 1)")
        if not 0.0 <= speech_gate_p <= 1.0:
            raise ValueError("speech_gate_p must be in [0, 1]")
        self.alpha_d_speech = alpha_d_speech
        self.speech_gate_p = speech_gate_p
        if frame_gate_p is not None and not 0.0 <= frame_gate_p <= 1.0:
            raise ValueError("frame_gate_p must be None or in [0, 1]")
        self.frame_gate_p = frame_gate_p
        self.gate_bin_start = int(gate_bin_start)
        self.gate_bin_end = gate_bin_end
        if slow_mask_max_frac is not None and not 0.0 < slow_mask_max_frac <= 1.0:
            raise ValueError("slow_mask_max_frac must be None or in (0, 1]")
        self.slow_mask_max_frac = slow_mask_max_frac
        self.remove_echo_explained_rise = remove_echo_explained_rise
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)  # 線性域的 delta
        self.num_init_frames = num_init_frames
        self.broadband_threshold = broadband_threshold

        # 場景轉換偵測（高頻段 γ + flatness 聯合）
        self.scene_change_threshold = 10 ** (scene_change_threshold_db / 10)
        self.scene_change_min_frames = scene_change_min_frames
        self.scene_change_blend = scene_change_blend
        self.scene_change_flatness_threshold = scene_change_flatness_threshold
        if scene_change_confirm_frames < 0:
            raise ValueError("scene_change_confirm_frames must be >= 0")
        self.scene_change_confirm_frames = scene_change_confirm_frames
        if scene_change_confirm_window < 0:
            raise ValueError("scene_change_confirm_window must be >= 0")
        if scene_change_confirm_window > 0 and scene_change_confirm_frames > 0:
            raise ValueError(
                "scene_change_confirm_window and scene_change_confirm_frames "
                "are alternative confirmation mechanisms for the first fire "
                "of an episode and cannot both be enabled -- a nonzero "
                "confirm_frames would be silently dead code once window "
                "mode takes over that decision")
        if not 0.0 < scene_change_confirm_frac <= 1.0:
            raise ValueError("scene_change_confirm_frac must be in (0, 1]")
        self.scene_change_confirm_window = scene_change_confirm_window
        self.scene_change_confirm_frac = scene_change_confirm_frac
        # Ring buffer of the last _window_size hit/miss decisions (the same
        # hi_gamma+flatness boolean the ordinary trigger computes every
        # frame) plus a running count of hits in it, so the window-fraction
        # test below is O(1) per frame. Only allocated/touched when window
        # mode is enabled -- bit-exact no-op otherwise.
        if scene_change_confirm_window > 0:
            self._window_size = self.scene_change_min_frames + scene_change_confirm_window
            self._window_required_hits = int(np.ceil(
                scene_change_confirm_frac * self._window_size))
            if self._window_required_hits <= self.scene_change_min_frames:
                raise ValueError(
                    "scene_change_confirm_window/scene_change_confirm_frac "
                    f"requires only {self._window_required_hits} hits out of "
                    f"a {self._window_size}-frame window, which is <= "
                    f"scene_change_min_frames ({self.scene_change_min_frames}) "
                    "-- this configuration can be satisfied on LESS evidence "
                    "than the unguarded baseline trigger, defeating the "
                    "confirmation guard's purpose. Raise "
                    "scene_change_confirm_frac or lower "
                    "scene_change_confirm_window.")
            self._window_buf = np.zeros(self._window_size, dtype=bool)
        else:
            self._window_size = 0
            self._window_required_hits = 0
            self._window_buf = None
        self._window_ptr = 0
        self._window_hit_count = 0
        self.scene_change_count = 0
        # Whether the CURRENT contiguous elevated episode has already fired
        # once (see the fricative-guard comment in update()). Cleared
        # whenever the trigger condition breaks, so each new episode is
        # re-confirmed from scratch.
        self._scene_change_confirmed = False
        self._scene_change_miss_run = 0
        self.accept_external_spp = accept_external_spp

        # 狀態變量
        self.noise_psd = None       # 噪聲功率譜密度
        self.S = None               # 時間平滑後的功率譜
        self.S_min = None           # 最小值
        self.min_buffer = None      # 最小值追蹤緩衝區 (L, n_freqs)
        self._buf_ptr = 0           # circular-buffer write pointer
        self.spp = None             # Speech Presence Probability

        self.is_initialized = False
        self.frame_count = 0

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        初始化噪聲估計

        取前 num_init_frames 幀功率的 30th 百分位數（第 k 小值，與 C quickselect 對齊）
        作為噪聲估計，避免語音幀導致過高估計。

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 初始噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_freqs = magnitude_spectrum.shape[1]

        # 使用前 N 幀初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2

        # 使用 30th 百分位數作初始噪聲估計（20th 太低容易過低估計）
        # v4.2.1 C-align: 改用 k-th 最小值（不做線性插值），與 C quickselect 語義一致。
        # 原 np.percentile(..., 30) 會在 sorted[k]/sorted[k+1] 之間做線性插值，C 則直接取 sorted[k]。
        N = power_spectrum.shape[0]
        k = ((N - 1) * 30) // 100
        init_psd = np.partition(power_spectrum, k, axis=0)[k]

        # 初始化狀態：S、S_min、min_buffer 必須從同一個統計量出發
        # 若 S 用均值而 S_min 用 P30，第一次 update 時 ratio = S/(S_min*delta) 會異常（>>1 或 <<1），
        # 導致 indicator 在純噪聲段誤觸發或誤壓
        self.noise_psd = init_psd.copy()
        self.S = self.noise_psd.copy()     # 與 S_min 一致，避免初始 ratio 異常
        self.S_min = self.noise_psd.copy()
        self.spp = np.zeros(n_freqs)

        # 初始化最小值追蹤緩衝區（用 init_psd 填滿）; _buf_ptr starts at last slot
        # so first update() advances to slot 0.
        self.min_buffer = np.tile(init_psd, (self.L, 1))
        self._buf_ptr = self.L - 1

        self.is_initialized = True
        self.frame_count = self.num_init_frames

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # 保持接口兼容（MCRA 內部判斷，忽略此參數）
        spp: Optional[np.ndarray] = None,  # v2.0: 支持外部 SPP（軟判決）
        slow_mask: Optional[np.ndarray] = None,  # per-bin override of the slow-update gate
        extra_noise_psd: Optional[np.ndarray] = None,  # arm 4: raw per-bin R²-derived
            # power added upstream THIS frame (same array the caller folded into
            # the gain-side noise floor); used only post-hoc, see
            # remove_echo_explained_rise above.
    ) -> np.ndarray:
        """
        MCRA 噪聲估計更新

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 忽略，MCRA 使用 SPP 判斷
            spp: 外部 SPP 值 (n_freqs,)，可選
            extra_noise_psd: arm 4 的事後修正用，R² 注入量（可選）

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # 1. 計算當前幀的功率譜
        power = magnitude ** 2

        # arm 4: snapshot the pre-update estimate. Captured here (before any of
        # steps 2-8, including the scene-change block) and consumed only after
        # the entire unmodified recursion below has run — mirrors the C
        # prototype's own before/after snapshot in res_nr_coupling_probe.c.
        apply_arm4 = self.remove_echo_explained_rise and extra_noise_psd is not None
        previous_noise_psd = self.noise_psd.copy() if apply_arm4 else None

        # 2. 時間平滑
        # S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
        self.S = self.alpha_s * self.S + (1 - self.alpha_s) * power

        # 3. 更新最小值緩衝區（circular buffer，避免每幀 np.roll 分配）
        self._buf_ptr = (self._buf_ptr + 1) % self.L
        self.min_buffer[self._buf_ptr] = self.S

        # 4. 計算最小值
        # S_min(k,l) = min{S(k,τ): l-L+1 ≤ τ ≤ l}
        self.S_min = np.min(self.min_buffer, axis=0)

        # 5. 語音指示器（基於最小值比）
        # I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
        # 注意：比值大於 delta 表示可能有語音
        ratio = self.S / (self.S_min * self.delta + 1e-10)
        indicator = (ratio > 1.0).astype(float)

        # 6. SPP 平滑
        # p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self.spp = self.alpha_p * self.spp + (1 - self.alpha_p) * indicator

        # 7. 場景轉換偵測
        # 條件：高頻 γ 高 AND 高頻 spectral flatness 高
        # - 高頻 γ 高：能量突然增加（可能是噪聲或語音）
        # - Spectral flatness 高：能量分布平坦（噪聲特徵，語音 ~0.1-0.2，白噪聲 ~0.5-0.7）
        # 兩者同時滿足才觸發，避免語音誤觸發
        n_freqs = len(power)
        hi_start = n_freqs // 2  # 上半頻段（~4kHz for 16kHz/512FFT）
        hi_power = power[hi_start:]
        # When remove_echo_explained_rise is active, the trigger must see
        # the same echo-corrected power its own post-hoc correction
        # implies, or it stays blind to echo and never clears while a
        # bin's rise is echo-explained -- firing every
        # scene_change_min_frames for the whole echo episode instead of
        # once (see remove_echo_explained_rise's docstring). Only the
        # ENERGY test (hi_gamma) is corrected here; flatness a few lines
        # down stays on the RAW spectrum (shape, not level) -- zeroing
        # many bins by subtraction can swing the geometric mean through
        # the 1e-20 floor in _spectral_flatness and falsely veto a genuine
        # broadband change that happens to co-occur with echo.
        # extra_noise_psd is 0 (or apply_arm4 False) on every ordinary
        # frame, so this is a no-op there -- bit-exact to shipped behaviour
        # unless remove_echo_explained_rise=True AND a caller actually
        # passes extra_noise_psd.
        hi_power_for_gamma = (
            np.maximum(hi_power - extra_noise_psd[hi_start:], 0.0)
            if apply_arm4 else hi_power)
        hi_gamma = np.mean(hi_power_for_gamma) / (np.mean(self.noise_psd[hi_start:]) + 1e-10)

        # Flatness contains one log per high-band bin.  It cannot affect the
        # decision unless the cheap energy-ratio gate passes, so defer it.
        # This is decision-identical and avoids the log pass on ordinary
        # frames (the common path on speech and stationary noise).
        hi_energy_candidate = hi_gamma > self.scene_change_threshold
        hi_flatness = (_spectral_flatness(hi_power)
                       if hi_energy_candidate else 0.0)
        hit_now = bool(hi_energy_candidate
                       and hi_flatness > self.scene_change_flatness_threshold)

        # Windowed-fraction confirmation bookkeeping: push this frame's
        # hit/miss decision into the trailing ring buffer
        # on EVERY frame (not just inside the hit branch below), so the
        # window reflects calendar time, not episode time -- a periodic
        # modulation's average duty cycle is what the fraction test reads,
        # regardless of how its individual dips compare to any one
        # miss-tolerance constant. Skipped entirely when window mode is
        # off, so this touches no state on the default (off) path.
        if self.scene_change_confirm_window > 0:
            evicted = self._window_buf[self._window_ptr]
            self._window_buf[self._window_ptr] = hit_now
            self._window_hit_count += int(hit_now) - int(evicted)
            self._window_ptr = (self._window_ptr + 1) % self._window_size

        if hit_now:
            self.scene_change_count += 1
            self._scene_change_miss_run = 0
            # Fricative guard, two alternative first-fire confirmation
            # mechanisms (mutually exclusive, validated at construction):
            #
            # scene_change_confirm_window > 0 (windowed-fraction mode): the
            # FIRST reset of an episode additionally requires that at least
            # scene_change_confirm_frac of the trailing window (sized
            # min_frames + confirm_window) be hits -- see that param's
            # docstring for why this replaces the run-length test rather
            # than layering on top of it.
            #
            # otherwise (legacy run-length mode, scene_change_confirm_frames
            # itself possibly 0 i.e. the shipped unguarded trigger): the
            # FIRST reset must additionally hold for scene_change_confirm_
            # frames MORE consecutive frames beyond the ordinary trigger
            # point.
            #
            # Once an episode has been confirmed once (either mode), later
            # re-triggers within the SAME episode revert to the ordinary
            # threshold: the blend below is partial (scene_change_blend),
            # so a genuine step can need several back-to-back resets to
            # fully converge, exactly as the shipped mechanism relies on
            # today -- re-confirming every one of those would only slow
            # that convergence (and, by letting the episode's own elevated
            # reading outlast its confirm window, can even chain into
            # unrelated later speech), without adding any discriminating
            # power versus a fricative (which never reaches the first
            # confirmed fire at all).
            if self._scene_change_confirmed:
                ready = self.scene_change_count >= self.scene_change_min_frames
            elif self.scene_change_confirm_window > 0:
                ready = self._window_hit_count >= self._window_required_hits
            else:
                ready = self.scene_change_count >= (
                    self.scene_change_min_frames + self.scene_change_confirm_frames)
            if ready:
                # 場景轉換確認：部分重置噪聲估計和最小值追蹤
                blend = self.scene_change_blend
                self.noise_psd = blend * self.noise_psd + (1 - blend) * power
                # The noise_psd write just above is corrected after the fact
                # by the post-hoc block at the end of update() (see
                # test_scene_change_write_is_also_corrected), but S_min
                # and min_buffer are stomped with self.S HERE and never
                # go through that post-hoc path at all -- so without
                # this, a corrected fire still leaves the min-tracker
                # seeded with echo-polluted power. Use the same
                # echo-corrected value consistently with the main write
                # whenever arm 4 is active; bit-exact to shipped when
                # it isn't.
                S_for_reset = (np.maximum(self.S - extra_noise_psd, 0.0)
                                if apply_arm4 else self.S)
                # np.maximum already allocates a fresh array -- only the
                # `else self.S` branch aliases self.S and needs the copy
                # before self.S_min is allowed to diverge from it.
                self.S_min = S_for_reset if apply_arm4 else S_for_reset.copy()
                self.min_buffer[:] = S_for_reset.reshape(1, -1)
                self._scene_change_confirmed = True
                # This `ready` decision spends the window's accumulated
                # evidence: the next confirmation must be earned with fresh
                # hits, not the same evidence re-read on a later frame.
                # Unconditional, like legacy run-length mode's
                # self.scene_change_count reset just below.
                if self.scene_change_confirm_window > 0:
                    self._window_buf[:] = False
                    self._window_hit_count = 0
                self.scene_change_count = 0
                self._scene_change_miss_run = 0
        else:
            # A longer confirm window has proportionally more chances for one
            # frame's hi_gamma to dip under threshold by ordinary measurement
            # noise even while a genuine step's energy has not actually
            # dropped (verified: at scene_change_confirm_frames=20/16kHz-256,
            # a near-threshold synthetic +13.5 dB step's recovery exceeded
            # the 0.3s existence guard in 10/20 seeds before this tolerance
            # was added, 0/20 after). Tolerate up to
            # SCENE_CHANGE_MISS_TOLERANCE consecutive miss frames without
            # discarding the streak -- only reset once misses outlast that,
            # which any real phoneme-to-phoneme gap (tens of ms) still does,
            # so two separate short fricatives still cannot bridge into one
            # episode. Only active when either confirmation mode is enabled
            # (legacy run-length's scene_change_confirm_frames, or windowed-
            # fraction's scene_change_confirm_window -- the two are mutually
            # exclusive by construction, so at most one of these is nonzero),
            # so the shipped default (both 0) remains bit-exact with the
            # shipped hard reset-on-miss.
            if ((self.scene_change_confirm_frames > 0
                    or self.scene_change_confirm_window > 0)
                    and self.scene_change_count > 0
                    and self._scene_change_miss_run < self.SCENE_CHANGE_MISS_TOLERANCE):
                self._scene_change_miss_run += 1
            else:
                self.scene_change_count = 0
                self._scene_change_miss_run = 0
                self._scene_change_confirmed = False

        # 8. 噪聲更新（SPP 門控）
        # external-gate (accept_external_spp=True): prefer OM-LSA posterior from the
        # denoiser — it uses DD-smoothed a priori SNR history, giving more reliable
        # per-bin speech protection than the internal binary ratio test.
        # internal-gate (accept_external_spp=False): always use internal indicator.
        # Use False in AEC pipeline contexts where residual echo inflates the
        # OM-LSA posterior in noise-only bins and would freeze noise tracking.
        spp_for_update = (spp if (self.accept_external_spp and spp is not None)
                          else self.spp)

        # 寬頻場景轉換偵測（舊方法，broadband_threshold < 1.0 時啟用）
        if self.broadband_threshold < 1.0:
            high_spp_ratio = np.mean(self.spp > 0.5)
            if high_spp_ratio > self.broadband_threshold:
                scale = max(0.0, 1.0 - (high_spp_ratio - self.broadband_threshold)
                            / (1.0 - self.broadband_threshold))
                spp_for_update = spp_for_update * scale

        # α̃_d(k,l) = α_d + (1-α_d)·p(k,l)
        # 當 SPP 高（語音段）時，α̃_d 接近 1，噪聲更新慢
        # 當 SPP 低（噪聲段）時，α̃_d 接近 α_d，噪聲更新快
        tilde_alpha_d = self.alpha_d + (1 - self.alpha_d) * spp_for_update

        # N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²
        noise_new = tilde_alpha_d * self.noise_psd + (1 - tilde_alpha_d) * power
        if self.alpha_d_up is not None:
            # Both blends are convex, so the estimate rises exactly when the
            # frame power exceeds it; only that direction takes the slow rate.
            tilde_up = self.alpha_d_up + (1 - self.alpha_d_up) * spp_for_update
            noise_up = tilde_up * self.noise_psd + (1 - tilde_up) * power
            noise_new = np.where(power > self.noise_psd, noise_up, noise_new)
        if self.alpha_d_speech is not None:
            speechy = (spp_for_update > self.speech_gate_p if slow_mask is None
                       else np.asarray(slow_mask, dtype=bool))
            if self.frame_gate_p is not None:
                gate_end = (len(spp_for_update) if self.gate_bin_end is None
                            else self.gate_bin_end)
                frame_mean = float(np.mean(
                    spp_for_update[self.gate_bin_start:gate_end]))
                if frame_mean <= self.frame_gate_p:
                    speechy = np.zeros_like(speechy)
            if (self.slow_mask_max_frac is not None
                    and np.mean(speechy) > self.slow_mask_max_frac):
                speechy = np.zeros_like(speechy)
            # Gated bins take the lower of the slow and ordinary candidates:
            # a fall keeps the ordinary rate, a rise is held to the slow one.
            # Only those bins are computed (the product gate covers a few LF
            # bins); noise_new is a fresh array here, so the write is in place.
            if speechy.any():
                tilde_sp = (self.alpha_d_speech
                            + (1 - self.alpha_d_speech) * spp_for_update[speechy])
                noise_slow = (tilde_sp * self.noise_psd[speechy]
                              + (1 - tilde_sp) * power[speechy])
                noise_new[speechy] = np.minimum(noise_slow, noise_new[speechy])
        self.noise_psd = noise_new

        # Dead-bin restart. A bin whose N has decayed below NOISE_PSD_INERT
        # (digital silence for a few seconds: N shrinks by α̃_d every frame with
        # nothing to pull it up) is numerically inert: every consumer adds
        # 1e-10 to N, so γ and the min-statistics ratio no longer see it. When
        # signal returns, γ = |Y|²/1e-10 saturates the posterior at exactly 1.0,
        # α̃_d becomes exactly 1.0 and the update above is a fixed point -- the
        # bin never tracks again and its gain stays at ~1. Restart such bins
        # with the ungated blend (p = 0); no other bin is touched, so streams
        # that never go numerically dead are bit-identical to before.
        dead = self.noise_psd < self.NOISE_PSD_INERT
        if np.any(dead):
            self.noise_psd[dead] = (self.alpha_d * self.noise_psd[dead]
                                    + (1 - self.alpha_d) * power[dead])

        # arm 4: post-hoc, per-bin subtractive correction. The update above
        # (steps 2-8 plus the dead-bin restart) ran completely unmodified —
        # this does not change tilde_alpha_d, the gate, or which spp drove it.
        # For a bin that rose this frame (tracked > previous) on a frame whose
        # power also exceeded the pre-update estimate, remove the fraction of
        # that rise explainable by the supplied extra (R²) power:
        #   excess = power - previous          (the rise the frame power could cause)
        #   fraction = min(extra / excess, 1.0) (how much of it extra explains)
        #   tracked = previous + (tracked - previous) * (1 - fraction)
        # A bin with no extra power, or one that fell, is untouched. This
        # corrects where the extra power LANDED in noise_psd; it does not
        # correct the update RATE itself (tilde_alpha_d still saw whatever spp
        # it was handed) — a partial fix by design, not a complete one.
        if apply_arm4:
            excess = power - previous_noise_psd
            rising = ((extra_noise_psd > 0.0)
                      & (self.noise_psd > previous_noise_psd)
                      & (excess > 0.0))
            if np.any(rising):
                fraction = np.minimum(extra_noise_psd[rising] / excess[rising], 1.0)
                self.noise_psd[rising] = (
                    previous_noise_psd[rising]
                    + (self.noise_psd[rising] - previous_noise_psd[rising])
                    * (1.0 - fraction)
                )

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """重置估計器狀態"""
        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.min_buffer = None
        self._buf_ptr = 0
        self.spp = None
        self.is_initialized = False
        self.frame_count = 0
        self.scene_change_count = 0
        self._scene_change_confirmed = False
        self._scene_change_miss_run = 0
        if self._window_buf is not None:
            self._window_buf[:] = False
        self._window_ptr = 0
        self._window_hit_count = 0

    def __repr__(self):
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L})")
