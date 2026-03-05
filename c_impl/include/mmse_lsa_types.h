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
 * Configuration structure for MMSE-LSA denoiser
 */
typedef struct {
    int sample_rate;        // Sample rate (8000, 16000, 48000)
    int frame_size_ms;      // Frame length in ms (20)
    int frame_shift_ms;     // Frame shift in ms (10) = hop size
    int fft_size;           // FFT size (256, 512, 1024)

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
    config.frame_size_ms = 20;
    config.frame_shift_ms = 10;

    // Calculate frame_size and find appropriate FFT size
    // frame_size = sample_rate * frame_size_ms / 1000
    // fft_size must be >= frame_size (next power of 2)
    int frame_size = sample_rate * 20 / 1000;  // 20ms frame
    int fft_size = 256;  // minimum FFT size
    while (fft_size < frame_size) {
        fft_size *= 2;
    }
    config.fft_size = fft_size;

    // SPP parameters (sync with Python v3_2_config.yaml)
    config.alpha_xi = 0.88f;
    config.q = 0.5f;
    config.xi_min_db = -20.0f;

    // MCRA parameters (sync with Python v3_2_config.yaml)
    config.alpha_s = 0.95f;
    config.alpha_d = 0.7f;
    config.alpha_p = 0.2f;
    config.L = 32;               // 320ms scene tracking
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

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_TYPES_H
