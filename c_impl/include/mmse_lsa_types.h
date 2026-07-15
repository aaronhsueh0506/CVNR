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

/**
 * Configuration structure for MMSE-LSA denoiser
 */
typedef struct {
    int sample_rate;        // Sample rate (8000, 16000, 48000)
    int frame_size;         // Frame length in samples (320 @ 16kHz, 20ms)
    int hop_size;           // Hop size in samples (160 @ 16kHz, 10ms)
    int fft_size;           // FFT size (next pow2 >= frame_size, 512 @ 16kHz)

    // SPP parameters
    float alpha_xi;         // A priori SNR smoothing (0.88)
    float q;                // Speech prior probability (0.5)
    float xi_min_db;        // A priori SNR floor in dB (-20)

    // MCRA parameters
    float alpha_s;          // Time smoothing (0.95)
    float alpha_d;          // Noise update (0.7)
    float alpha_p;          // SPP smoothing (0.2)
    int L;                  // Minimum tracking window (32 frames = 320ms)
    float delta_db;         // Bias compensation in dB (10.0)
    int num_init_frames;    // Noise init frames (20)

    // MCRA scene change detection
    float scene_change_threshold_db;     // Hi-freq gamma threshold in dB (10.0)
    int scene_change_min_frames;         // Consecutive frames required (5)
    float scene_change_blend;            // Noise reset blend factor (0.5)
    float scene_change_flatness_threshold; // Hi-freq spectral flatness threshold (0.4)
    float broadband_threshold;           // Broadband scene-reset gate (0.8; <1.0 enables)

    // Gain parameters
    float g_min_db;         // Minimum gain in amplitude dB, /20 (-30.0)
    float alpha_g;          // Gain smoothing (0.88)
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
 * Create default configuration for given sample rate
 * FFT size is automatically calculated to be >= frame_size (next power of 2)
 */
static inline MmseLsaConfig mmse_lsa_default_config(int sample_rate) {
    MmseLsaConfig config;

    config.sample_rate = sample_rate;

    // 20ms frame, 10ms hop — unified with AEC pipeline
    //
    // F05 guard: don't multiply an unchecked sample_rate. A negative or
    // absurdly large sample_rate (adversarial input, or simply a caller bug)
    // must not be fed into `sample_rate * 20`, which is signed-int
    // multiplication — overflow there is undefined behaviour, not just a
    // wrong answer. `sample_rate > INT_MAX / 20` is exactly the guard that
    // makes the multiply safe (INT_MAX/20 truncates down, so anything <= it
    // times 20 fits in int). An invalid sample_rate instead leaves
    // frame_size/hop_size/fft_size at 0 — mmse_lsa_validate_config() rejects
    // that (in addition to rejecting sample_rate itself against the
    // {8000,16000,48000} whitelist), so no downstream consumer ever acts on
    // these degenerate fields.
    int frame_size;
    if (sample_rate > 0 && sample_rate <= INT_MAX / 20) {
        frame_size = sample_rate * 20 / 1000;  // 320 @ 16kHz
    } else {
        frame_size = 0;
    }
    int fft_size = 0;
    if (frame_size > 0) {
        fft_size = 256;
        while (fft_size < frame_size) {
            fft_size *= 2;
        }
    }
    config.frame_size = frame_size;       // 320 @ 16kHz (20ms)
    config.hop_size = frame_size / 2;     // 160 @ 16kHz (10ms)
    config.fft_size = fft_size;           // 512 @ 16kHz (next pow2 >= frame_size)

    // SPP parameters (sync with Python v3_2_config.yaml)
    config.alpha_xi = 0.92f;    // 2026-07 musical-noise fix (was 0.88): DD ξ-smoothing lever.
                                 // Shared across all strength presets; damps ξ→SPP jitter (the
                                 // isolated gain peaks = musical noise). ~free on speech (guard
                                 // PESQ −0.001). Stationary already used 0.92 → undisturbed.
    config.q = 0.5f;
    config.xi_min_db = -20.0f;

    // MCRA parameters (sync with Python v3_2_config.yaml)
    config.alpha_s = 0.95f;
    config.alpha_d = 0.7f;
    config.alpha_p = 0.2f;
    config.L = 32;               // 32 × 10ms = 320ms (sync with Python v3_2)
    config.delta_db = 10.0f;
    config.num_init_frames = 20;

    // MCRA scene change detection
    config.scene_change_threshold_db = 10.0f;
    config.scene_change_min_frames = 5;
    config.scene_change_blend = 0.5f;
    config.scene_change_flatness_threshold = 0.4f;
    config.broadband_threshold = 0.8f;   // <1.0 enables broadband scene reset.
                                          // NOTE: 0.8 matches the Audio_ALG pipeline path, NOT the
                                          // standalone Python YAML — config/v3_2_config.yaml uses
                                          // broadband_threshold: 1.0 (disabled; L=32 tracks fast enough).

    // Gain parameters (sync with Python v3_2_config.yaml)
    config.g_min_db = -30.0f;   /* amplitude dB (/20); = old -15 @ /10 → same 0.0316 floor */
    config.alpha_g = 0.88f;
    config.alpha_attack = 0.3f;
    config.alpha_decay = 0.88f;     // Match Python (= alpha_g)

    // Content-preservation mode: default = full (all levers off → byte-identical V3-2).
    config.stationary_floor            = false;
    config.stationary_floor_exponent   = 1.0f;
    config.stationary_floor_beta       = 1.0f;
    config.scene_change_tonal_veto     = false;
    config.scene_change_lo_flatness_max = 0.4f;

    return config;
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
static inline MmseLsaConfig mmse_lsa_config_for_mode(int sample_rate, MmseLsaNrMode mode) {
    MmseLsaConfig config = mmse_lsa_default_config(sample_rate);

    switch (mode) {
    case MMSE_LSA_NR_MILD:
        config.g_min_db      = -20.0f;   /* amplitude dB (/20) → 0.10 floor */
        config.q             = 0.6f;
        config.xi_min_db     = -15.0f;
        config.alpha_d       = 0.85f;
        config.alpha_g       = 0.92f;
        config.alpha_attack  = 0.4f;
        config.alpha_decay   = 0.92f;
        break;

    case MMSE_LSA_NR_MODERATE:
        config.g_min_db      = -25.0f;   /* amplitude dB (/20) → 0.056 floor (mild ↔ balanced) */
        config.q             = 0.55f;
        config.xi_min_db     = -18.0f;
        config.alpha_d       = 0.85f;
        config.alpha_g       = 0.92f;
        config.alpha_attack  = 0.4f;
        config.alpha_decay   = 0.92f;
        break;

    case MMSE_LSA_NR_AGGRESSIVE:
        config.g_min_db      = -40.0f;   /* amplitude dB (/20) → 0.01 floor */
        config.q             = 0.35f;
        config.xi_min_db     = -25.0f;
        config.alpha_d       = 0.5f;
        config.alpha_g       = 0.85f;    /* more downstream smoothing than old 0.75 (musical noise) */
        config.alpha_attack  = 0.15f;
        config.alpha_decay   = 0.88f;    /* was 0.85 */
        break;

    case MMSE_LSA_NR_BALANCED:
    default:
        break;  // already default
    }

    return config;
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
 * config byte-identical to the shipped standalone V3-2 stationary path.
 */
static inline void mmse_lsa_apply_stationary(MmseLsaConfig* config) {
    // the mechanism: Wiener gain lower-bound (ξ/(β+ξ))^p
    config->stationary_floor          = true;
    config->stationary_floor_exponent = 2.0f;   // p=2 deepens noise removal; music retention ~0
    config->stationary_floor_beta     = 1.0f;   // remove exactly N
    // residual-noise depth is set by xi_min (NOT g_min); leave natural comfort noise
    config->xi_min_db                 = -22.0f;
    config->alpha_xi                  = 0.92f;   // steadier ξ → steadier bound
    config->g_min_db                  = -30.0f;  // amplitude dB (/20); mostly inert under the bound
    // keep N an honest STATIONARY floor: slow the posterior-gated recursive average so
    // music phrases aren't absorbed (which would collapse ξ and defeat the bound)
    config->alpha_d                   = 0.95f;
    // music-aware scene-change: percussion can't confirm; tonal (music) low band is vetoed
    config->scene_change_min_frames        = 30;
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
 * rates, and the CLI's fixed 512/256/512 framing override) with headroom for
 * legitimate re-tuning, not tight enough to constrain it. A config built by
 * mmse_lsa_default_config() / mmse_lsa_config_for_mode() / the CLI's framing
 * override, for any of the three supported sample rates, always passes.
 *
 * Float tunables (R08, external re-review, NR side): the int/dimension
 * checks above were the whole gate — none of the 18 float fields (SPP/MCRA/
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

    // frame_size / hop_size: positive, consistent with fft_size (the frame
    // is zero-padded up to fft_size; hop must not exceed the frame it hops
    // through).
    if (config->frame_size <= 0 || config->frame_size > config->fft_size) {
        return false;
    }
    if (config->hop_size <= 0 || config->hop_size > config->frame_size) {
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
