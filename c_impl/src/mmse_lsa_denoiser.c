/**
 * mmse_lsa_denoiser.c - MMSE-LSA Denoiser Main Implementation
 *
 * V3-2 MMSE-LSA Speech Denoiser
 * Streaming by hop_size (frame_shift)
 *
 * Based on Ephraim-Malah 1985
 *
 * This file includes the gain calculation (merged from mmse_lsa_gain.c)
 */

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"
#include "fft_wrapper.h"
#include "fast_math.h"

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// Internal denoiser structure
struct MmseLsaDenoiser {
    MmseLsaConfig config;

    // Frame parameters (precomputed)
    int frame_size;         // Samples per frame
    int hop_size;           // Samples per process call
    int overlap;            // frame_size - hop_size
    int fft_size;
    int n_freqs;            // fft_size/2 + 1

    // Input buffer (accumulate samples until frame_size available)
    float* input_buffer;    // [frame_size]
    int input_samples;      // Number of samples in buffer

    // FFT related
    FftHandle* fft_handle;
    float* window;          // sqrt(Hann) window [frame_size]
    float* fft_in;          // Windowed frame [fft_size]
    Complex* spectrum;      // FFT output [n_freqs]

    // Spectrum buffers [n_freqs]
    float* power;           // |Y|²
    float* magnitude;       // |Y|
    float* phase;           // angle(Y)
    float* enhanced_mag;    // Enhanced magnitude

    // Sub-modules (MCRA and SPP only - gain calculation is now inline)
    McraNoiseEstimator* noise_est;
    SppEstimator* spp_est;

    // SPP/Gain buffers [n_freqs]
    float* spp;             // Speech presence probability
    float* xi;              // A priori SNR
    float* gamma;           // A posteriori SNR
    float* gain;            // Spectral gain

#ifdef USE_SHARED_XI_RATIO
    float* v;               // v = xi/(1+xi) * gamma, shared between SPP and Gain
#endif

    // OLA output buffer
    float* ola_buffer;      // [frame_size]

    // State for DD method [n_freqs]
    float* gain_prev;       // Previous frame gain
    float* enhanced_psd_prev; // Previous frame enhanced PSD

    // Noise initialization
    int init_frame_count;
    float* init_power_sum;  // [n_freqs] - accumulated power during init
    bool is_initialized;

    // === Gain calculation parameters (merged from MmseLsaGain) ===
    float g_min;            // Minimum gain (linear)
    float log_g_min;        // log(g_min)
    float alpha_g;          // Symmetric smoothing factor
    float alpha_attack;     // Attack smoothing (gain increasing)
    float alpha_decay;      // Decay smoothing (gain decreasing)
    float* log_gain_prev;   // Previous frame gain in log domain [n_freqs]
    bool gain_initialized;  // Whether gain calculator has processed first frame

#ifdef DEBUG_DUMP
    FILE* debug_fp;
    int debug_frame_idx;
#endif
};

// ============================================================================
// Helper functions
// ============================================================================

// Create sqrt(Hann) window for perfect reconstruction
static void create_sqrt_hann_window(float* window, int size) {
    for (int i = 0; i < size; i++) {
        float hann = 0.5f * (1.0f - cosf(2.0f * M_PI * i / (float)size));
        window[i] = sqrtf(hann);
    }
}

// ============================================================================
// Gain calculation (merged from mmse_lsa_gain.c)
// ============================================================================

/**
 * Initialize gain calculation parameters
 */
static void init_gain_params(MmseLsaDenoiser* self, const MmseLsaConfig* config) {
    self->g_min = powf(10.0f, config->g_min_db / 10.0f);
    self->log_g_min = logf(self->g_min + 1e-10f);
    self->alpha_g = config->alpha_g;
    self->alpha_attack = config->alpha_attack;
    self->alpha_decay = config->alpha_decay;
    self->gain_initialized = false;
}

/**
 * Reset gain calculation state
 */
static void reset_gain_state(MmseLsaDenoiser* self) {
    if (self->log_gain_prev) {
        memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    }
    self->gain_initialized = false;
}

/**
 * Calculate MMSE-LSA gain with SPP weighting
 *
 * Based on Ephraim-Malah 1985:
 * G = (ξ/(1+ξ)) × exp(0.5 × E1(v))
 *
 * Where:
 *   v = ξ/(1+ξ) × γ
 *   E1(v) = ∫[v,∞] (e^(-t)/t) dt (Exponential Integral)
 *
 * With SPP weighting (OMLSA style):
 *   log(G) = p × log(G_H1) + (1-p) × log(G_min)
 *
 * And asymmetric smoothing:
 *   Attack: fast response (α_attack)
 *   Decay: slow to reduce musical noise (α_decay)
 */
static void calculate_gain(
    MmseLsaDenoiser* self,
    const float* spp,
    const float* xi,
    const float* gamma,
    const float* v_in,  // Can be NULL if not using shared xi_ratio
    float* gain_out
) {
    int n_freqs = self->n_freqs;
    float g_min = self->g_min;
    float log_g_min = self->log_g_min;
    float alpha_attack = self->alpha_attack;
    float alpha_decay = self->alpha_decay;

    for (int k = 0; k < n_freqs; k++) {
        float xi_k = xi[k];
        float gamma_k = gamma[k];
        float spp_k = spp[k];

        // 1. Calculate v = ξ/(1+ξ) × γ
        float v, xi_ratio;
#ifdef USE_SHARED_XI_RATIO
        if (v_in != NULL) {
            // Use pre-computed v, recover xi_ratio from v/gamma
            v = v_in[k];
            xi_ratio = v / (gamma_k + 1e-10f);
        } else {
            // Compute as usual
            xi_ratio = xi_k / (1.0f + xi_k);
            v = xi_ratio * gamma_k;
        }
#else
        (void)v_in;  // Unused
        xi_ratio = xi_k / (1.0f + xi_k);
        v = xi_ratio * gamma_k;
#endif

        // Clamp v to prevent overflow
        if (v < 1e-10f) v = 1e-10f;
        if (v > 700.0f) v = 700.0f;

        // 2. Calculate E1(v) using 3-segment approximation
        float exp1_v = exp1_approx(v);

        // 3. MMSE-LSA gain: G_H1 = (ξ/(1+ξ)) × exp(0.5 × E1(v))
        float gain_mmse = xi_ratio * fast_exp(0.5f * exp1_v);

        // Clamp gain_mmse to valid range
        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f) gain_mmse = 1.0f;

        // 4. Log-domain SPP weighting (OMLSA style)
        // log(G) = p × log(G_H1) + (1-p) × log(G_min)
        float log_gain_mmse = fast_log(gain_mmse + 1e-10f);
        float log_gain = spp_k * log_gain_mmse + (1.0f - spp_k) * log_g_min;

        // 5. Log-domain temporal smoothing
        if (self->gain_initialized) {
            float log_gain_prev_k = self->log_gain_prev[k];

            // Asymmetric smoothing: Attack fast, Decay slow
            float alpha;
            if (log_gain > log_gain_prev_k) {
                // Attack: gain increasing
                alpha = alpha_attack;
            } else {
                // Decay: gain decreasing
                alpha = alpha_decay;
            }
            log_gain = alpha * log_gain_prev_k + (1.0f - alpha) * log_gain;
        }

        // 6. Convert back to linear domain and clamp
#ifdef USE_FAST_GAIN_SMOOTHING
        // Optimization: perform clamping in log domain to avoid redundant exp→log
        // log(g_min) = log_g_min, log(1.0) = 0
        float gain;
        float log_gain_save;
        if (log_gain < log_g_min) {
            // Clamp to g_min
            gain = g_min;
            log_gain_save = log_g_min;
        } else if (log_gain > 0.0f) {
            // Clamp to 1.0
            gain = 1.0f;
            log_gain_save = 0.0f;
        } else {
            // No clamping needed - normal case
            gain = fast_exp(log_gain);
            log_gain_save = log_gain;
        }
        gain_out[k] = gain;
        self->log_gain_prev[k] = log_gain_save;
#else
        // Original version
        float gain = fast_exp(log_gain);

#ifndef USE_SINGLE_CLAMP
        // 7. Clamp to valid range (redundant if gain_mmse already clamped)
        if (gain < g_min) gain = g_min;
        if (gain > 1.0f) gain = 1.0f;
#endif

        gain_out[k] = gain;

        // Save log-domain gain for next frame
        self->log_gain_prev[k] = fast_log(gain + 1e-10f);
#endif
    }

    self->gain_initialized = true;
}

// ============================================================================
// Denoiser implementation
// ============================================================================

MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config) {
    if (!config) return NULL;

    MmseLsaDenoiser* self = (MmseLsaDenoiser*)calloc(1, sizeof(MmseLsaDenoiser));
    if (!self) return NULL;

    // Copy config
    self->config = *config;

    // Frame parameters (already in samples)
    self->frame_size = config->frame_size;
    self->hop_size = config->hop_size;
    self->overlap = self->frame_size - self->hop_size;
    self->fft_size = config->fft_size;
    self->n_freqs = config->fft_size / 2 + 1;

    // Warning: if frame_size > fft_size, only fft_size samples will be processed per frame
    if (self->frame_size > self->fft_size) {
        fprintf(stderr, "Warning: frame_size (%d) > fft_size (%d). "
                "Only first %d samples will be used. Consider using fft_size >= frame_size.\n",
                self->frame_size, self->fft_size, self->fft_size);
    }

    // Allocate input buffer
    self->input_buffer = (float*)calloc(self->frame_size, sizeof(float));
    self->input_samples = 0;

    // Create FFT handle
    self->fft_handle = fft_create(self->fft_size);

    // Create window
    self->window = (float*)calloc(self->frame_size, sizeof(float));
    create_sqrt_hann_window(self->window, self->frame_size);

    // Allocate FFT buffers
    self->fft_in = (float*)calloc(self->fft_size, sizeof(float));
    self->spectrum = (Complex*)calloc(self->n_freqs, sizeof(Complex));

    // Allocate spectrum buffers
    self->power = (float*)calloc(self->n_freqs, sizeof(float));
    self->magnitude = (float*)calloc(self->n_freqs, sizeof(float));
    self->phase = (float*)calloc(self->n_freqs, sizeof(float));
    self->enhanced_mag = (float*)calloc(self->n_freqs, sizeof(float));

    // Create sub-modules (MCRA and SPP only)
    self->noise_est = mcra_create(self->n_freqs, config);
    self->spp_est = spp_create(self->n_freqs, config);

    // Allocate SPP/gain buffers
    self->spp = (float*)calloc(self->n_freqs, sizeof(float));
    self->xi = (float*)calloc(self->n_freqs, sizeof(float));
    self->gamma = (float*)calloc(self->n_freqs, sizeof(float));
    self->gain = (float*)calloc(self->n_freqs, sizeof(float));
#ifdef USE_SHARED_XI_RATIO
    self->v = (float*)calloc(self->n_freqs, sizeof(float));
#endif

    // Allocate OLA buffer
    self->ola_buffer = (float*)calloc(self->frame_size, sizeof(float));

    // Allocate state buffers
    self->gain_prev = (float*)calloc(self->n_freqs, sizeof(float));
    self->enhanced_psd_prev = (float*)calloc(self->n_freqs, sizeof(float));

    // Noise initialization buffer
    self->init_power_sum = (float*)calloc(self->n_freqs, sizeof(float));
    self->init_frame_count = 0;
    self->is_initialized = false;

    // Initialize gain calculation parameters
    init_gain_params(self, config);
    self->log_gain_prev = (float*)calloc(self->n_freqs, sizeof(float));

#ifdef DEBUG_DUMP
    self->debug_fp = fopen("/tmp/c_debug_dump.bin", "wb");
    self->debug_frame_idx = 0;
    if (self->debug_fp) {
        // Write header: n_freqs (int32)
        fwrite(&self->n_freqs, sizeof(int), 1, self->debug_fp);
    }
#endif

    // Verify all allocations
    if (!self->input_buffer || !self->fft_handle || !self->window ||
        !self->fft_in || !self->spectrum || !self->power ||
        !self->magnitude || !self->phase || !self->enhanced_mag ||
        !self->noise_est || !self->spp_est ||
        !self->spp || !self->xi || !self->gamma || !self->gain ||
        !self->ola_buffer || !self->gain_prev || !self->enhanced_psd_prev ||
        !self->init_power_sum || !self->log_gain_prev
#ifdef USE_SHARED_XI_RATIO
        || !self->v
#endif
        ) {
        mmse_lsa_destroy(self);
        return NULL;
    }

    return self;
}

void mmse_lsa_destroy(MmseLsaDenoiser* self) {
    if (!self) return;

    if (self->input_buffer) free(self->input_buffer);
    if (self->fft_handle) fft_destroy(self->fft_handle);
    if (self->window) free(self->window);
    if (self->fft_in) free(self->fft_in);
    if (self->spectrum) free(self->spectrum);
    if (self->power) free(self->power);
    if (self->magnitude) free(self->magnitude);
    if (self->phase) free(self->phase);
    if (self->enhanced_mag) free(self->enhanced_mag);
    if (self->noise_est) mcra_destroy(self->noise_est);
    if (self->spp_est) spp_destroy(self->spp_est);
    if (self->spp) free(self->spp);
    if (self->xi) free(self->xi);
    if (self->gamma) free(self->gamma);
    if (self->gain) free(self->gain);
#ifdef USE_SHARED_XI_RATIO
    if (self->v) free(self->v);
#endif
    if (self->ola_buffer) free(self->ola_buffer);
    if (self->gain_prev) free(self->gain_prev);
    if (self->enhanced_psd_prev) free(self->enhanced_psd_prev);
    if (self->init_power_sum) free(self->init_power_sum);
    if (self->log_gain_prev) free(self->log_gain_prev);

#ifdef DEBUG_DUMP
    if (self->debug_fp) fclose(self->debug_fp);
#endif

    free(self);
}

// Process a single frame (internal)
static void process_frame(MmseLsaDenoiser* self) {
    int frame_size = self->frame_size;
    int fft_size = self->fft_size;
    int n_freqs = self->n_freqs;

    // 1. Apply window and prepare for FFT
    // Note: If frame_size > fft_size, only use the first fft_size samples (truncation)
    //       If frame_size < fft_size, zero-pad the rest
    memset(self->fft_in, 0, fft_size * sizeof(float));
    int copy_len = (frame_size < fft_size) ? frame_size : fft_size;
    for (int i = 0; i < copy_len; i++) {
        self->fft_in[i] = self->input_buffer[i] * self->window[i];
    }

    // 2. FFT
    fft_forward(self->fft_handle, self->fft_in, self->spectrum);

    // 3. Calculate power spectrum (magnitude computed only for DEBUG_DUMP)
    fft_power(self->spectrum, self->power, n_freqs);

    // 4. Noise initialization or normal processing
    if (!self->is_initialized) {
        // Accumulate power for noise initialization
        for (int k = 0; k < n_freqs; k++) {
            self->init_power_sum[k] += self->power[k];
        }

        // For exact percentile calculation, also store each frame's power
        // (This is a no-op when USE_FAST_PERCENTILE is defined)
        mcra_accumulate_init_power(self->noise_est, self->power, self->init_frame_count);

        self->init_frame_count++;

        if (self->init_frame_count >= self->config.num_init_frames) {
            // Initialize noise estimator
            mcra_init_noise(self->noise_est, self->init_power_sum,
                           self->init_frame_count);
            self->is_initialized = true;
        }

        // During init: pass through with unity gain
        for (int k = 0; k < n_freqs; k++) {
            self->gain[k] = 1.0f;
        }
    } else {
        // Normal processing: MCRA -> SPP -> MMSE-LSA gain

        // Get current noise estimate
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);

#ifdef USE_SHARED_XI_RATIO
        // Estimate SPP, xi, gamma, and v (to share with gain calculator)
        spp_estimate_ex(self->spp_est,
                       self->power,
                       noise_psd,
                       self->gain_prev,
                       self->enhanced_psd_prev,
                       self->spp,
                       self->xi,
                       self->gamma,
                       self->v);

        // Calculate MMSE-LSA gain (with pre-computed v)
        calculate_gain(self, self->spp, self->xi, self->gamma, self->v, self->gain);
#else
        // Estimate SPP, xi, gamma
        spp_estimate(self->spp_est,
                    self->power,
                    noise_psd,
                    self->gain_prev,
                    self->enhanced_psd_prev,
                    self->spp,
                    self->xi,
                    self->gamma);

        // Calculate MMSE-LSA gain
        calculate_gain(self, self->spp, self->xi, self->gamma, NULL, self->gain);
#endif

        // Update noise estimate with SPP
        mcra_update(self->noise_est, self->power, self->spp);
    }

    // 5. Save state for next frame (gain_prev + enhanced_psd_prev)
    for (int k = 0; k < n_freqs; k++) {
        float g = self->gain[k];
        self->gain_prev[k] = g;
        self->enhanced_psd_prev[k] = g * g * self->power[k];
    }

#ifdef DEBUG_DUMP
    // Dump per-frame intermediate values
    if (self->debug_fp) {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);
        // Compute magnitude and enhanced_mag only for debug dump
        for (int k = 0; k < n_freqs; k++) {
            self->magnitude[k] = sqrtf(self->power[k]);
            self->enhanced_mag[k] = self->gain[k] * self->magnitude[k];
        }
        // Record format per frame:
        //   frame_idx (int32)
        //   is_initialized (int32)
        //   noise_psd[n_freqs] (float32)
        //   magnitude[n_freqs] (float32) - input magnitude (before gain)
        //   spp[n_freqs] (float32)
        //   xi[n_freqs] (float32)
        //   gamma[n_freqs] (float32)
        //   gain[n_freqs] (float32)
        //   gain_prev[n_freqs] (float32) - saved for next frame DD
        //   enhanced_mag[n_freqs] (float32)
        int fidx = self->debug_frame_idx;
        int init = self->is_initialized ? 1 : 0;
        fwrite(&fidx, sizeof(int), 1, self->debug_fp);
        fwrite(&init, sizeof(int), 1, self->debug_fp);
        fwrite(noise_psd, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->magnitude, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->spp, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->xi, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->gamma, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->gain, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->gain_prev, sizeof(float), n_freqs, self->debug_fp);
        fwrite(self->enhanced_mag, sizeof(float), n_freqs, self->debug_fp);
    }
    self->debug_frame_idx++;
#endif

    // 6. Reconstruct spectrum with original phase
    // Apply gain directly to complex spectrum (preserves phase)
    fft_apply_gain(self->spectrum, self->gain, n_freqs);

    // 7. IFFT
    fft_inverse(self->fft_handle, self->spectrum, self->fft_in);

    // 8. Apply window for OLA (synthesis window)
    // Note: Only process min(frame_size, fft_size) samples
    int ola_len = (frame_size < fft_size) ? frame_size : fft_size;
    for (int i = 0; i < ola_len; i++) {
        self->fft_in[i] *= self->window[i];
    }

    // 9. Overlap-Add
    for (int i = 0; i < ola_len; i++) {
        self->ola_buffer[i] += self->fft_in[i];
    }
}

int mmse_lsa_process(
    MmseLsaDenoiser* self,
    const float* samples_in,
    float* samples_out
) {
    return mmse_lsa_process_ex(self, samples_in, samples_out,
                               NULL, NULL, NULL, NULL);
}

int mmse_lsa_process_ex(
    MmseLsaDenoiser* self,
    const float* samples_in,
    float* samples_out,
    const float* noise_psd_ext,
    const float* spp_ext,
    const float* xi_ext,
    const float* gamma_ext
) {
    if (!self || !samples_in || !samples_out) return -1;

    int hop_size = self->hop_size;
    int frame_size = self->frame_size;

    // 1. Append new samples to input buffer
    // Shift existing samples left if needed
    if (self->input_samples + hop_size > frame_size) {
        // Should not happen in normal operation
        return -2;
    }

    memcpy(self->input_buffer + self->input_samples,
           samples_in,
           hop_size * sizeof(float));
    self->input_samples += hop_size;

    // 2. Check if we have enough samples for a frame
    if (self->input_samples >= frame_size) {
        // Process frame
        // Note: In extended version, external noise/spp could be used
        // For now, we use internal computation
        (void)noise_psd_ext;
        (void)spp_ext;
        (void)xi_ext;
        (void)gamma_ext;

        process_frame(self);

        // 3. Output hop_size samples from OLA buffer
        memcpy(samples_out, self->ola_buffer, hop_size * sizeof(float));

        // 4. Shift OLA buffer left by hop_size
        memmove(self->ola_buffer, self->ola_buffer + hop_size,
                (frame_size - hop_size) * sizeof(float));
        // Zero the freed portion
        memset(self->ola_buffer + (frame_size - hop_size), 0,
               hop_size * sizeof(float));

        // 5. Shift input buffer left by hop_size (keep overlap)
        memmove(self->input_buffer, self->input_buffer + hop_size,
                (frame_size - hop_size) * sizeof(float));
        self->input_samples -= hop_size;
    } else {
        // Not enough samples yet - output silence
        memset(samples_out, 0, hop_size * sizeof(float));
    }

    return 0;
}

void mmse_lsa_reset(MmseLsaDenoiser* self) {
    if (!self) return;

    // Reset input buffer
    memset(self->input_buffer, 0, self->frame_size * sizeof(float));
    self->input_samples = 0;

    // Reset OLA buffer
    memset(self->ola_buffer, 0, self->frame_size * sizeof(float));

    // Reset sub-modules
    mcra_reset(self->noise_est);
    spp_reset(self->spp_est);

    // Reset gain calculation state
    reset_gain_state(self);

    // Reset state buffers
    memset(self->gain_prev, 0, self->n_freqs * sizeof(float));
    memset(self->enhanced_psd_prev, 0, self->n_freqs * sizeof(float));

    // Reset noise initialization
    memset(self->init_power_sum, 0, self->n_freqs * sizeof(float));
    self->init_frame_count = 0;
    self->is_initialized = false;
}

// Query functions
int mmse_lsa_get_hop_size(const MmseLsaDenoiser* self) {
    return self ? self->hop_size : 0;
}

int mmse_lsa_get_frame_size(const MmseLsaDenoiser* self) {
    return self ? self->frame_size : 0;
}

int mmse_lsa_get_n_freqs(const MmseLsaDenoiser* self) {
    return self ? self->n_freqs : 0;
}

int mmse_lsa_get_latency(const MmseLsaDenoiser* self) {
    if (!self) return 0;
    // Latency = frame_size (OLA buffering only)
    // Note: init period is pass-through, not counted as latency
    return self->frame_size;
}

bool mmse_lsa_is_initialized(const MmseLsaDenoiser* self) {
    return self ? self->is_initialized : false;
}

const float* mmse_lsa_get_spp(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self) {
        if (n_freqs) *n_freqs = 0;
        return NULL;
    }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->spp;
}

const float* mmse_lsa_get_noise_psd(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self || !self->noise_est) {
        if (n_freqs) *n_freqs = 0;
        return NULL;
    }
    if (n_freqs) *n_freqs = self->n_freqs;
    return mcra_get_noise_psd(self->noise_est);
}

const float* mmse_lsa_get_gain(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self) {
        if (n_freqs) *n_freqs = 0;
        return NULL;
    }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->gain;
}
