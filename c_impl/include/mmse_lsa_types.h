/**
 * mmse_lsa_types.h - Common types and configuration for MMSE-LSA denoiser
 *
 * V3-2 MMSE-LSA C Implementation
 * Based on Ephraim-Malah 1985
 */

#ifndef MMSE_LSA_TYPES_H
#define MMSE_LSA_TYPES_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <limits.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * NR strength mode
 */
typedef enum {
    MMSE_LSA_NR_MILD       = 0,   // Gentlest, preserve speech detail (g_min -20)
    MMSE_LSA_NR_MODERATE   = 1,   // Between mild and balanced (g_min -25)
    MMSE_LSA_NR_BALANCED   = 2,   // Default (g_min -30)
    MMSE_LSA_NR_AGGRESSIVE = 3    // Deepest noise removal (g_min -40)
} MmseLsaNrMode;

/* The mode whitelist, in one place. Every runtime entry point that accepts a
 * mode needs to REFUSE an out-of-enum value rather than let it reach
 * mmse_lsa_config_for_mode_grid(), whose `default:` silently yields balanced.
 * Declared beside the enum so a fifth mode is one edit, not one per setter. */
static inline bool mmse_lsa_nr_mode_is_valid(MmseLsaNrMode mode) {
    return mode == MMSE_LSA_NR_MILD || mode == MMSE_LSA_NR_MODERATE ||
           mode == MMSE_LSA_NR_BALANCED || mode == MMSE_LSA_NR_AGGRESSIVE;
}

/* Name <-> enum for command lines and configs. Kept beside the enum so a
 * fifth mode is one edit here, not one per tool (the two shipped CLIs each
 * carried a hand-copied table and both silently lacked `moderate`).
 * mmse_lsa_nr_mode_from_name returns -1 for an unknown name; callers decide
 * whether that falls back to balanced or is rejected. */
static inline int mmse_lsa_nr_mode_from_name(const char *name) {
    if (!name) return -1;
    if (strcmp(name, "mild") == 0)       return MMSE_LSA_NR_MILD;
    if (strcmp(name, "moderate") == 0)   return MMSE_LSA_NR_MODERATE;
    if (strcmp(name, "balanced") == 0)   return MMSE_LSA_NR_BALANCED;
    if (strcmp(name, "aggressive") == 0) return MMSE_LSA_NR_AGGRESSIVE;
    return -1;
}

static inline const char *mmse_lsa_nr_mode_name(MmseLsaNrMode mode) {
    switch (mode) {
        case MMSE_LSA_NR_MILD:       return "mild";
        case MMSE_LSA_NR_MODERATE:   return "moderate";
        case MMSE_LSA_NR_BALANCED:   return "balanced";
        case MMSE_LSA_NR_AGGRESSIVE: return "aggressive";
        default:                     return "invalid";
    }
}

/**
 * Configuration structure for MMSE-LSA denoiser
 */
typedef struct {
    int sample_rate;        // Sample rate (8000, 16000, 48000)
    int frame_size;         // Frame length in samples; equal to fft_size
    int hop_size;           // 50% overlap; equal to frame_size / 2
    int fft_size;           // Whitelisted power-of-two transform size

    // SPP parameters
    float alpha_xi;         // A priori SNR smoothing; 0.92 at the 16 ms tuning anchor
    float q;                // Speech prior probability (0.5)
    float xi_min_db;        // A priori SNR floor in dB (-20)

    // MCRA parameters
    float alpha_s;          // Time smoothing (0.95)
    float alpha_d;          // Noise update (0.7)
    float alpha_p;          // SPP smoothing (0.2)
    int L;                  // Minimum tracking window (~320 ms, grid-retimed)
    float delta_db;         // Bias compensation in dB (10.0)
    int num_init_frames;    // Noise initialization (~200 ms, grid-retimed)

    // MCRA scene change detection
    float scene_change_threshold_db;     // Hi-freq gamma threshold in dB (10.0)
    int scene_change_min_frames;         // Consecutive duration (~50 ms by default)
    float scene_change_blend;            // Noise reset blend factor (0.5)
    float scene_change_flatness_threshold; // Hi-freq spectral flatness threshold (0.4)
    float broadband_threshold;           // Broadband scene-reset gate; 1.0 disables it

    // Gain parameters
    float g_min_db;         // Minimum gain in amplitude dB, /20 (-30.0)
    float alpha_g;          // Symmetric log-gain smoothing of the Python
                            // reference's use_asymmetric_smoothing=False mode
                            // (0.88). The C port implements only the
                            // asymmetric attack/decay pair below, so this
                            // field is NOT read by the gain path; it is kept
                            // because every preset derives alpha_decay from
                            // it (alpha_decay = alpha_g) and the config-parity
                            // test compares it. Tune alpha_decay, not this.
    float alpha_attack;     // Asymmetric attack (0.3)
    float alpha_decay;      // Asymmetric decay (0.88 = alpha_g)

    // Content-preservation mode (full | stationary) — orthogonal to the strength axis.
    // Default (all off / full) leaves the strength preset untouched. The `stationary`
    // preset (mmse_lsa_apply_stationary) turns these on. Mirrors Python core/nr_modes.py.
    bool  stationary_floor;              // Wiener gain lower-bound gain>=(ξ/(β+ξ))^p (default off)
    float stationary_floor_exponent;     // p (1.0 = pure Wiener; stationary preset uses 2.0)
    float stationary_floor_beta;         // β (1.0 = remove exactly the stationary floor N)
    bool  scene_change_tonal_veto;       // skip scene reset when the LOW band is tonal (music-safe)
    float scene_change_lo_flatness_max;  // lo-band flatness below this => tonal => veto (0.4)
} MmseLsaConfig;

/**
 * Create default configuration for a supported sample rate and its default
 * no-padding power-of-two FFT grid.
 *
 * The low-latency 8-ms-hop grid is the default at 8/16 kHz. The 16-ms-hop
 * grids (8kHz/256 and 16kHz/512) remain supported alternatives; see
 * mmse_lsa_validate_config().
 */
static inline int mmse_lsa_default_fft_size(int sample_rate) {
    return (sample_rate == 48000) ? 1024
         : (sample_rate == 16000) ? 256
         : (sample_rate == 8000) ? 128 : 0;
}

/** Convert a coefficient tuned at `ref_hop_seconds`-per-update to this grid's
 * hop. Mirrors Python's core/signal_grid.py retime_ema_alpha(...,
 * authored_hop_seconds=...). `ref_hop_seconds` is `double` (not `float`): a
 * `0.016f` literal's ~7-digit precision is fine for this self-cancelling
 * pow() ratio at the anchor grid, but the matching frames_ref() below is a
 * ceil() step function -- the same float32 rounding of "16ms" pushed its
 * anchor-grid ratio a few ULPs past an exact integer and flipped the result
 * by a whole frame (e.g. L=32 -> 33 at 16kHz/512). Both now take double for
 * the same double-precision "16ms"/"10ms" Python itself uses natively. */
static inline float mmse_lsa_retime_alpha_ref(float alpha_ref,
                                               int sample_rate, int hop_size,
                                               double ref_hop_seconds) {
    if (!(alpha_ref >= 0.0f && alpha_ref <= 1.0f) ||
        sample_rate <= 0 || hop_size <= 0 || ref_hop_seconds <= 0.0) {
        return alpha_ref;
    }
    double exponent = ((double)hop_size / (double)sample_rate) / ref_hop_seconds;
    return powf(alpha_ref, (float)exponent);
}

/** Convert a coefficient tuned at 10-ms updates to this grid's hop. */
static inline float mmse_lsa_retime_alpha(float alpha_10ms,
                                           int sample_rate, int hop_size) {
    return mmse_lsa_retime_alpha_ref(alpha_10ms, sample_rate, hop_size, 0.010);
}

/** Convert a legacy frame count (authored at ref_hop_seconds/frame) without
 * shortening real duration. Mirrors Python's retime_frame_count(...,
 * authored_hop_seconds=...). See mmse_lsa_retime_alpha_ref()'s comment above
 * for why ref_hop_seconds must be double here. */
static inline int mmse_lsa_retime_frames_ref(int frames_ref,
                                             int sample_rate, int hop_size,
                                             double ref_hop_seconds) {
    double seconds, frames_d;
    if (frames_ref <= 0 || sample_rate <= 0 || hop_size <= 0 ||
        ref_hop_seconds <= 0.0) {
        return 0;
    }
    seconds = (double)frames_ref * ref_hop_seconds;
    frames_d = ceil(seconds * (double)sample_rate / (double)hop_size - 1e-12);
    if (frames_d < 1.0) frames_d = 1.0;
    return frames_d > (double)INT_MAX ? 0 : (int)frames_d;
}

/** Convert a legacy 10-ms frame count without shortening real duration. */
static inline int mmse_lsa_retime_frames(int frames_10ms,
                                         int sample_rate, int hop_size) {
    if (frames_10ms <= 0 || sample_rate <= 0 || hop_size <= 0) return 0;
    int64_t numerator = (int64_t)frames_10ms * (int64_t)sample_rate;
    int64_t denominator = (int64_t)100 * (int64_t)hop_size;
    int64_t frames = (numerator + denominator - 1) / denominator;
    return frames > INT_MAX ? 0 : (int)frames;
}

/** Build the default preset directly on one whitelisted no-padding grid. */
static inline MmseLsaConfig mmse_lsa_default_config_for_grid(
        int sample_rate, int fft_size) {
    MmseLsaConfig config;

    config.sample_rate = sample_rate;

    // Power-of-two frame/FFT, 50% overlap, no transform zero-padding.
    //
    // Invalid rate/grid pairs are left structurally visible here and rejected
    // by mmse_lsa_validate_config() before sizing or construction.
    config.frame_size = fft_size;
    config.hop_size = fft_size / 2;
    config.fft_size = fft_size;

    // SPP parameters (sync with Python v3_2_config.yaml)
    // This value was authored at a 16-ms hop. Retiming it from the 10-ms
    // reference would change the validated anchor value (0.92 -> ~0.875 at
    // 16kHz/512).
    config.alpha_xi = mmse_lsa_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
                                 // DD ξ smoothing shared by all strengths.
    config.q = 0.5f;
    config.xi_min_db = -20.0f;

    // MCRA parameters (sync with Python v3_2_config.yaml)
    config.alpha_s = mmse_lsa_retime_alpha(0.95f, sample_rate, config.hop_size);
    /* 0.903414 (10 ms domain) = 0.85 on the 16 ms grid: the 2026-09-03
     * balanced retune (mirrors config/v3_2_config.yaml). Was 0.7 = 0.565 at
     * 16 ms, whose fast noise tracking is what hurt speech at balanced. */
    config.alpha_d = mmse_lsa_retime_alpha(0.903414f, sample_rate, config.hop_size);
    config.alpha_p = mmse_lsa_retime_alpha(0.2f, sample_rate, config.hop_size);
    // L=32 is documented in Python's config/v3_2_config.yaml as authored
    // directly against the 16ms hop ("32 幀 × 16ms/hop = 512ms") -- unlike
    // alpha_s/alpha_p/num_init_frames below, which carry no such hop-basis
    // evidence and stay on the 10-ms reference. This must mirror Python's
    // denoisers/v3_2_mmse_lsa.py.
    config.L = mmse_lsa_retime_frames_ref(32, sample_rate, config.hop_size, 0.016);
    config.delta_db = 10.0f;
    config.num_init_frames = mmse_lsa_retime_frames(20, sample_rate, config.hop_size);

    // MCRA scene change detection
    config.scene_change_threshold_db = 10.0f;
    config.scene_change_min_frames = mmse_lsa_retime_frames(5, sample_rate, config.hop_size);
    config.scene_change_blend = 0.5f;
    config.scene_change_flatness_threshold = 0.4f;
    config.broadband_threshold = 1.0f;   // <1.0 enables broadband scene reset; 1.0 == disabled.
                                          // Matches Python's own config/v3_2_config.yaml default
                                          // (320-ms L tracks fast enough). The Audio_ALG AEC-residual
                                          // pipeline wants 0.8 for faster post-echo-burst adaptation --
                                          // that is an explicit pipeline-layer overlay (see
                                          // aec_nr_pipeline.py:_build_denoiser / audio_pipeline.c /
                                          // 4aec_nr_res.c), not this standalone default.

    // Gain parameters (sync with Python v3_2_config.yaml)
    config.g_min_db = -30.0f;   /* amplitude dB (/20); = old -15 @ /10 → same 0.0316 floor */
    config.alpha_g = mmse_lsa_retime_alpha(0.88f, sample_rate, config.hop_size);
    // alpha_attack is authored at a 16-ms hop and is fixed in code rather
    // than loaded from YAML. alpha_g/alpha_decay use the 10-ms reference.
    config.alpha_attack = mmse_lsa_retime_alpha_ref(0.3f, sample_rate, config.hop_size, 0.016);
    config.alpha_decay = mmse_lsa_retime_alpha(0.88f, sample_rate, config.hop_size);

    // Content-preservation mode: default = full (all overlay levers off).
    config.stationary_floor            = false;
    config.stationary_floor_exponent   = 1.0f;
    config.stationary_floor_beta       = 1.0f;
    config.scene_change_tonal_veto     = false;
    config.scene_change_lo_flatness_max = 0.4f;

    return config;
}

static inline MmseLsaConfig mmse_lsa_default_config(int sample_rate) {
    return mmse_lsa_default_config_for_grid(
        sample_rate, mmse_lsa_default_fft_size(sample_rate));
}

/**
 * Create configuration for given NR strength mode
 *
 * (g_min in amplitude dB, /20 convention; mirrors Python core/nr_strength.py)
 * MILD:       g_min=-20dB, gentlest, preserve speech, slower noise tracking
 * MODERATE:   g_min=-25dB, between mild and balanced
 * BALANCED:   g_min=-30dB, default (same as mmse_lsa_default_config)
 * AGGRESSIVE: g_min=-40dB, deepest suppression, faster noise tracking, extra gain smoothing
 */
static inline MmseLsaConfig mmse_lsa_config_for_mode_grid(
        int sample_rate, int fft_size, MmseLsaNrMode mode) {
    MmseLsaConfig config = mmse_lsa_default_config_for_grid(sample_rate, fft_size);

    // MILD/MODERATE/AGGRESSIVE's alpha_d/alpha_g/alpha_attack/alpha_decay
    // overlay values were authored directly against a 16-ms hop, not the
    // 10-ms reference mmse_lsa_retime_alpha() assumes. Retiming them from
    // 10 ms silently double-corrects (e.g. mild's alpha_g=0.92
    // becomes ~0.875 at the default 16kHz/512 grid, the exact pre-fix
    // value). BALANCED is an empty overlay (falls through to `default`
    // below) so its inherited alpha_d/alpha_g/alpha_decay stay on
    // mmse_lsa_default_config_for_grid()'s genuinely-10ms-authored base
    // values, correctly left on the 10ms reference -- alpha_attack is the
    // one exception: its base 0.3 default is ALSO 16ms-authored (see the
    // dedicated comment on mmse_lsa_default_config_for_grid()'s alpha_attack
    // line), so it is unconditionally 16ms in every mode including BALANCED.
    // This must mirror Python's core/nr_strength.py and
    // denoisers/v3_2_mmse_lsa.py.
    switch (mode) {
    case MMSE_LSA_NR_MILD:
        config.g_min_db      = -20.0f;   /* amplitude dB (/20) → 0.10 floor */
        config.q             = 0.6f;
        config.xi_min_db     = -15.0f;
        config.alpha_d       = mmse_lsa_retime_alpha_ref(0.85f, sample_rate, config.hop_size, 0.016);
        config.alpha_g       = mmse_lsa_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
        config.alpha_attack  = mmse_lsa_retime_alpha_ref(0.4f, sample_rate, config.hop_size, 0.016);
        config.alpha_decay   = mmse_lsa_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
        break;

    case MMSE_LSA_NR_MODERATE:
        config.g_min_db      = -25.0f;   /* amplitude dB (/20) → 0.056 floor (mild ↔ balanced) */
        config.q             = 0.55f;
        config.xi_min_db     = -18.0f;
        config.alpha_d       = mmse_lsa_retime_alpha_ref(0.85f, sample_rate, config.hop_size, 0.016);
        config.alpha_g       = mmse_lsa_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
        config.alpha_attack  = mmse_lsa_retime_alpha_ref(0.4f, sample_rate, config.hop_size, 0.016);
        config.alpha_decay   = mmse_lsa_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
        break;

    case MMSE_LSA_NR_AGGRESSIVE:
        config.g_min_db      = -40.0f;   /* amplitude dB (/20) → 0.01 floor */
        config.q             = 0.35f;
        config.xi_min_db     = -25.0f;
        config.alpha_d       = mmse_lsa_retime_alpha_ref(0.5f, sample_rate, config.hop_size, 0.016);
        config.alpha_g       = mmse_lsa_retime_alpha_ref(0.85f, sample_rate, config.hop_size, 0.016);
        config.alpha_attack  = mmse_lsa_retime_alpha_ref(0.15f, sample_rate, config.hop_size, 0.016);
        config.alpha_decay   = mmse_lsa_retime_alpha_ref(0.88f, sample_rate, config.hop_size, 0.016);
        break;

    case MMSE_LSA_NR_BALANCED:
    default:
        break;  // == the base config above (its alpha_d carries the 2026-09-03 retune)
    }

    return config;
}

static inline MmseLsaConfig mmse_lsa_config_for_mode(
        int sample_rate, MmseLsaNrMode mode) {
    return mmse_lsa_config_for_mode_grid(
        sample_rate, mmse_lsa_default_fft_size(sample_rate), mode);
}

/**
 * Overlay the `stationary` content-preservation preset onto an already-built config.
 *
 * ReSpeaker-like: remove ONLY the stationary noise floor, preserve non-stationary
 * content (speech / music / transients). Realised by the Wiener gain lower-bound
 * (ξ/(β+ξ))^p plus a slower noise update and a music-aware (tonal-veto) scene-change.
 *
 * This is the C mirror of Python core/nr_modes.py apply_mode(params, 'stationary'):
 * content mode is an ORTHOGONAL overlay on any strength base (mild/balanced/aggressive),
 * not a separate config — `full` overlays nothing. On the balanced default it yields a
 * config with the same real-time constants as the 10-ms tuned path.
 */
static inline void mmse_lsa_apply_stationary(MmseLsaConfig* config) {
    // the mechanism: Wiener gain lower-bound (ξ/(β+ξ))^p
    config->stationary_floor          = true;
    config->stationary_floor_exponent = 2.0f;   // p=2 deepens noise removal; music retention ~0
    config->stationary_floor_beta     = 1.0f;   // remove exactly N
    // residual-noise depth is set by xi_min (NOT g_min); leave natural comfort noise
    config->xi_min_db                 = -22.0f;
    // This overlay was authored at a 16-ms hop and mirrors Python
    // core/nr_modes.py; do not retime it from the 10-ms reference.
    config->alpha_xi = mmse_lsa_retime_alpha_ref(
        0.92f, config->sample_rate, config->hop_size, 0.016);
    config->g_min_db                  = -30.0f;  // amplitude dB (/20); mostly inert under the bound
    // keep N an honest STATIONARY floor: slow the posterior-gated recursive average so
    // music phrases aren't absorbed (which would collapse ξ and defeat the bound)
    config->alpha_d = mmse_lsa_retime_alpha_ref(
        0.95f, config->sample_rate, config->hop_size, 0.016);
    // music-aware scene-change: percussion can't confirm; tonal (music) low band is vetoed
    config->scene_change_min_frames = mmse_lsa_retime_frames_ref(
        30, config->sample_rate, config->hop_size, 0.016);
    config->scene_change_flatness_threshold = 0.6f;
    config->scene_change_tonal_veto        = true;
    config->scene_change_lo_flatness_max   = 0.4f;
}

/**
 * Validate a config before it is used to size or construct a denoiser
 * instance. This is the single gate mmse_lsa_get_mem_size() / mmse_lsa_create()
 * / mmse_lsa_init() all consult before touching any config field, so an
 * out-of-range or adversarial config — e.g. a huge/negative fft_size, L, or
 * num_init_frames that would otherwise drive the get_mem_size size-arithmetic
 * into overflow (F05), or a sample_rate this port's framing has never been
 * verified against — is rejected up front instead of silently producing a
 * wrapped/undersized byte count or being carved into by mmse_lsa_init (F07).
 *
 * Bounds are deliberately generous — wide enough to cover every shipped
 * preset (mild/moderate/balanced/aggressive x stationary, all three sample
 * rates, and all four whitelisted signal grids) with headroom for
 * legitimate re-tuning, not tight enough to constrain it. A config built by
 * mmse_lsa_default_config_for_grid() / mmse_lsa_config_for_mode_grid(), for
 * any supported rate/grid pair, always passes.
 *
 * Float tunables: the int/dimension checks above were previously the whole
 * gate — none of the 18 float fields (SPP/MCRA/
 * scene-change/gain/stationary-overlay knobs) were checked at all, so a NaN/
 * Inf/sign-flipped/absurd-magnitude value in any of them (adversarial input,
 * or a caller bug building the config by hand) would sail straight through
 * into mmse_lsa_create()/mmse_lsa_init() and the denoiser's own arithmetic.
 * Beyond the integer/dimension checks above, every float tunable is now also
 * checked here: NaN/Inf are rejected outright, and each field is bounded to a
 * wide sanity range (same "reject garbage, not policy" design as the int
 * bounds) — see the per-field comments below for the exact domain and why.
 *
 * @return true iff config is safe to pass to mmse_lsa_get_mem_size(),
 *         mmse_lsa_create(), or mmse_lsa_init().
 */
static inline bool mmse_lsa_validate_config(const MmseLsaConfig* config) {
    if (!config) return false;

    // Sample rate: only the rates this port's framing/coefficients have
    // actually been verified against.
    if (config->sample_rate != 8000 &&
        config->sample_rate != 16000 &&
        config->sample_rate != 48000) {
        return false;
    }

    // All int fields non-negative — a negative dimension cast to size_t in
    // the get_mem_size size-arithmetic becomes a huge (wrapped) allocation
    // request instead of an error.
    if (config->frame_size < 0 || config->hop_size < 0 || config->fft_size < 0 ||
        config->L < 0 || config->num_init_frames < 0 ||
        config->scene_change_min_frames < 0) {
        return false;
    }

    // fft_size: positive power of two, bounded. 8192 is 8x the largest
    // shipped fft_size (1024 @ 48kHz) — enough headroom for real tuning
    // while still bounding the per-bin array walk in get_mem_size().
    if (config->fft_size <= 0 || config->fft_size > 8192 ||
        (config->fft_size & (config->fft_size - 1)) != 0) {
        return false;
    }

    // No-padding project grids: frame == FFT and hop == frame/2. 8 kHz and
    // 16 kHz each support a low-latency 8-ms-hop default and a 16-ms-hop
    // alternate.
    if (config->frame_size <= 0 || config->frame_size != config->fft_size) {
        return false;
    }
    if (config->hop_size <= 0 || config->frame_size != 2 * config->hop_size) {
        return false;
    }
    if (!((config->sample_rate == 8000 &&
           (config->fft_size == 128 || config->fft_size == 256)) ||
          (config->sample_rate == 16000 &&
           (config->fft_size == 256 || config->fft_size == 512)) ||
          (config->sample_rate == 48000 && config->fft_size == 1024))) {
        return false;
    }

    // L (MCRA minima-tracking window) and num_init_frames: generous but
    // finite bounds — 10x the shipped default (32 / 20) catches an
    // accidental huge or negative value without constraining real tuning.
    if (config->L <= 0 || config->L > 320) {
        return false;
    }
    if (config->num_init_frames <= 0 || config->num_init_frames > 200) {
        return false;
    }

    // ---- Float tunables --------------------------------------------------
    // Every float knob below must be finite (no NaN/Inf), and land inside a
    // wide sanity range. Same design rule as the int bounds above: these
    // exist to reject garbage — NaN/Inf, a flipped sign, a stray extra zero
    // — not to constrain legitimate re-tuning. Every value
    // mmse_lsa_default_config() / mmse_lsa_config_for_mode() (all four
    // strength presets) / mmse_lsa_apply_stationary() ever sets, and every
    // value the Audio_ALG pipeline's derive_dims_and_configs() overlays on
    // top (L/alpha_d/alpha_attack/alpha_decay), falls comfortably inside its
    // range.

    // SPP parameters: alpha_xi is a [0,1] smoothing coefficient. q is a
    // speech-prior PROBABILITY, so it must be a proper open (0,1) value —
    // 0 or 1 would degenerate the SPP recursion into a permanent
    // silence/speech lock. xi_min_db is an a priori SNR floor in dB.
    if (!isfinite(config->alpha_xi) || config->alpha_xi < 0.0f || config->alpha_xi > 1.0f) {
        return false;
    }
    if (!isfinite(config->q) || config->q <= 0.0f || config->q >= 1.0f) {
        return false;
    }
    if (!isfinite(config->xi_min_db) ||
        config->xi_min_db < -80.0f || config->xi_min_db > 80.0f) {
        return false;
    }

    // MCRA parameters: alpha_s/alpha_d/alpha_p are [0,1] smoothing
    // coefficients; delta_db is a bias-compensation term in dB.
    if (!isfinite(config->alpha_s) || config->alpha_s < 0.0f || config->alpha_s > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_d) || config->alpha_d < 0.0f || config->alpha_d > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_p) || config->alpha_p < 0.0f || config->alpha_p > 1.0f) {
        return false;
    }
    if (!isfinite(config->delta_db) ||
        config->delta_db < -80.0f || config->delta_db > 80.0f) {
        return false;
    }

    // MCRA scene-change detection: threshold is in dB; blend/flatness/
    // broadband are all [0,1] proportions (broadband_threshold's "<1.0
    // enables, 1.0 disables" semantics documented in
    // mmse_lsa_default_config() still fits inside [0,1]).
    if (!isfinite(config->scene_change_threshold_db) ||
        config->scene_change_threshold_db < -80.0f ||
        config->scene_change_threshold_db > 80.0f) {
        return false;
    }
    if (!isfinite(config->scene_change_blend) ||
        config->scene_change_blend < 0.0f || config->scene_change_blend > 1.0f) {
        return false;
    }
    if (!isfinite(config->scene_change_flatness_threshold) ||
        config->scene_change_flatness_threshold < 0.0f ||
        config->scene_change_flatness_threshold > 1.0f) {
        return false;
    }
    if (!isfinite(config->broadband_threshold) ||
        config->broadband_threshold < 0.0f || config->broadband_threshold > 1.0f) {
        return false;
    }

    // Gain parameters: g_min_db is an amplitude-dB (/20 convention) floor;
    // alpha_g/alpha_attack/alpha_decay are [0,1] smoothing coefficients.
    if (!isfinite(config->g_min_db) ||
        config->g_min_db < -80.0f || config->g_min_db > 80.0f) {
        return false;
    }
    if (!isfinite(config->alpha_g) || config->alpha_g < 0.0f || config->alpha_g > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_attack) ||
        config->alpha_attack < 0.0f || config->alpha_attack > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_decay) ||
        config->alpha_decay < 0.0f || config->alpha_decay > 1.0f) {
        return false;
    }

    // Content-preservation (stationary) overlay: exponent p and beta shape
    // the Wiener gain lower bound (xi/(beta+xi))^p — p ranges 1.0 (base/
    // full) to 2.0 (stationary preset); beta must stay strictly positive (it
    // is a denominator term, see mmse_lsa_apply_stationary()).
    // scene_change_lo_flatness_max is a [0,1] flatness threshold, same
    // domain as scene_change_flatness_threshold above.
    if (!isfinite(config->stationary_floor_exponent) ||
        config->stationary_floor_exponent < 0.5f ||
        config->stationary_floor_exponent > 8.0f) {
        return false;
    }
    if (!isfinite(config->stationary_floor_beta) ||
        config->stationary_floor_beta <= 0.0f ||
        config->stationary_floor_beta > 16.0f) {
        return false;
    }
    if (!isfinite(config->scene_change_lo_flatness_max) ||
        config->scene_change_lo_flatness_max < 0.0f ||
        config->scene_change_lo_flatness_max > 1.0f) {
        return false;
    }

    return true;
}

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_TYPES_H
