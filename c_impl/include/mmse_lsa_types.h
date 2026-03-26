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
    float scene_change_threshold_db;  // Hi-freq gamma threshold in dB (10.0)
    int scene_change_min_frames;      // Consecutive frames required (5)
    float scene_change_blend;         // Noise reset blend factor (0.5)

    // Gain parameters
    float g_min_db;         // Minimum gain in dB (-15.0)
    float alpha_g;          // Gain smoothing (0.88)
    float alpha_attack;     // Asymmetric attack (0.3)
    float alpha_decay;      // Asymmetric decay (0.88 = alpha_g)
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
    config.L = 150;              // 150 × 10ms = 1.5s minima window
    config.delta_db = 10.0f;
    config.num_init_frames = 20;

    // MCRA scene change detection
    config.scene_change_threshold_db = 10.0f;
    config.scene_change_min_frames = 5;
    config.scene_change_blend = 0.5f;

    // Gain parameters (sync with Python v3_2_config.yaml)
    config.g_min_db = -15.0f;
    config.alpha_g = 0.88f;
    config.alpha_attack = 0.3f;
    config.alpha_decay = 0.88f;     // Match Python (= alpha_g)

    return config;
}

/**
 * Create configuration for given NR strength mode
 *
 * MILD:       g_min=-10dB, preserve speech, slower noise tracking
 * BALANCED:   g_min=-15dB, default (same as mmse_lsa_default_config)
 * AGGRESSIVE: g_min=-20dB, stronger suppression, faster noise tracking
 */
static inline MmseLsaConfig mmse_lsa_config_for_mode(int sample_rate, MmseLsaNrMode mode) {
    MmseLsaConfig config = mmse_lsa_default_config(sample_rate);

    switch (mode) {
    case MMSE_LSA_NR_MILD:
        config.g_min_db      = -10.0f;
        config.q             = 0.6f;
        config.xi_min_db     = -15.0f;
        config.alpha_d       = 0.85f;
        config.alpha_g       = 0.92f;
        config.alpha_attack  = 0.4f;
        config.alpha_decay   = 0.92f;
        break;

    case MMSE_LSA_NR_AGGRESSIVE:
        config.g_min_db      = -20.0f;
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

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_TYPES_H
