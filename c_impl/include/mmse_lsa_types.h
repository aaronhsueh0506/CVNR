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

#ifdef __cplusplus
extern "C" {
#endif

/**
 * NR strength mode
 */
typedef enum {
    MMSE_LSA_NR_MILD       = 0,   // Less aggressive, preserve speech detail
    MMSE_LSA_NR_BALANCED   = 1,   // Default
    MMSE_LSA_NR_AGGRESSIVE = 2    // More aggressive noise removal
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
    // Default (all off / full) is byte-identical to the shipped V3-2. The `stationary`
    // preset (mmse_lsa_config_stationary) turns these on. Mirrors Python core/nr_modes.py.
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
    int frame_size = sample_rate * 20 / 1000;  // 320 @ 16kHz
    int fft_size = 256;
    while (fft_size < frame_size) {
        fft_size *= 2;
    }
    config.frame_size = frame_size;       // 320 @ 16kHz (20ms)
    config.hop_size = frame_size / 2;     // 160 @ 16kHz (10ms)
    config.fft_size = fft_size;           // 512 @ 16kHz (next pow2 >= frame_size)

    // SPP parameters (sync with Python v3_2_config.yaml)
    config.alpha_xi = 0.88f;
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
 * (g_min in amplitude dB, /20 convention)
 * MILD:       g_min=-20dB, preserve speech, slower noise tracking
 * BALANCED:   g_min=-30dB, default (same as mmse_lsa_default_config)
 * AGGRESSIVE: g_min=-40dB, stronger suppression, faster noise tracking
 */
static inline MmseLsaConfig mmse_lsa_config_for_mode(int sample_rate, MmseLsaNrMode mode) {
    MmseLsaConfig config = mmse_lsa_default_config(sample_rate);

    switch (mode) {
    case MMSE_LSA_NR_MILD:
        config.g_min_db      = -20.0f;   /* amplitude dB (/20); = old -10 @ /10 */
        config.q             = 0.6f;
        config.xi_min_db     = -15.0f;
        config.alpha_d       = 0.85f;
        config.alpha_g       = 0.92f;
        config.alpha_attack  = 0.4f;
        config.alpha_decay   = 0.92f;
        break;

    case MMSE_LSA_NR_AGGRESSIVE:
        config.g_min_db      = -40.0f;   /* amplitude dB (/20); = old -20 @ /10 */
        config.q             = 0.35f;
        config.xi_min_db     = -25.0f;
        config.alpha_d       = 0.5f;
        config.alpha_g       = 0.75f;
        config.alpha_attack  = 0.15f;
        config.alpha_decay   = 0.85f;
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

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_TYPES_H
