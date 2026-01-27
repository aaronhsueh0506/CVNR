/**
 * mmse_lsa_gain.c - MMSE-LSA Gain Calculator Implementation
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

#include "mmse_lsa_gain.h"
#include "fast_math.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

// Internal structure
struct MmseLsaGain {
    int n_freqs;

    float g_min;        // Minimum gain (linear)
    float log_g_min;    // log(g_min)
    float alpha_g;      // Symmetric smoothing factor
    float alpha_attack; // Attack smoothing (gain increasing)
    float alpha_decay;  // Decay smoothing (gain decreasing)

    bool use_asymmetric_smoothing;

    // State array [n_freqs]
    float* log_gain_prev;

    bool is_initialized;
};

MmseLsaGain* mmse_lsa_gain_create(int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    MmseLsaGain* self = (MmseLsaGain*)calloc(1, sizeof(MmseLsaGain));
    if (!self) return NULL;

    self->n_freqs = n_freqs;
    self->g_min = powf(10.0f, config->g_min_db / 10.0f);
    self->log_g_min = logf(self->g_min + 1e-10f);
    self->alpha_g = config->alpha_g;
    self->alpha_attack = config->alpha_attack;
    self->alpha_decay = config->alpha_decay;
    self->use_asymmetric_smoothing = true;

    // Allocate state array
    self->log_gain_prev = (float*)calloc(n_freqs, sizeof(float));
    if (!self->log_gain_prev) {
        mmse_lsa_gain_destroy(self);
        return NULL;
    }

    self->is_initialized = false;

    return self;
}

void mmse_lsa_gain_destroy(MmseLsaGain* self) {
    if (!self) return;

    if (self->log_gain_prev) free(self->log_gain_prev);
    free(self);
}

void mmse_lsa_gain_calculate(
    MmseLsaGain* self,
    const float* spp,
    const float* xi,
    const float* gamma,
    float* gain_out
) {
    if (!self || !spp || !xi || !gamma || !gain_out) return;

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
        float xi_ratio = xi_k / (1.0f + xi_k);
        float v = xi_ratio * gamma_k;

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
        if (self->is_initialized) {
            float log_gain_prev_k = self->log_gain_prev[k];

            if (self->use_asymmetric_smoothing) {
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
            } else {
                // Symmetric smoothing
                log_gain = self->alpha_g * log_gain_prev_k +
                          (1.0f - self->alpha_g) * log_gain;
            }
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

    self->is_initialized = true;
}

void mmse_lsa_gain_reset(MmseLsaGain* self) {
    if (!self) return;

    memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    self->is_initialized = false;
}

float mmse_lsa_gain_get_g_min(const MmseLsaGain* self) {
    return self ? self->g_min : 0.0f;
}

#ifdef USE_SHARED_XI_RATIO
void mmse_lsa_gain_calculate_ex(
    MmseLsaGain* self,
    const float* spp,
    const float* xi,
    const float* gamma,
    const float* v_in,
    float* gain_out
) {
    if (!self || !spp || !xi || !gamma || !gain_out) return;

    int n_freqs = self->n_freqs;
    float g_min = self->g_min;
    float log_g_min = self->log_g_min;
    float alpha_attack = self->alpha_attack;
    float alpha_decay = self->alpha_decay;

    for (int k = 0; k < n_freqs; k++) {
        float xi_k = xi[k];
        float gamma_k = gamma[k];
        float spp_k = spp[k];

        float v, xi_ratio;
        if (v_in != NULL) {
            // Use pre-computed v, recover xi_ratio from v/gamma
            v = v_in[k];
            xi_ratio = v / (gamma_k + 1e-10f);
        } else {
            // Compute as usual
            xi_ratio = xi_k / (1.0f + xi_k);
            v = xi_ratio * gamma_k;
        }

        // Clamp v to prevent overflow
        if (v < 1e-10f) v = 1e-10f;
        if (v > 700.0f) v = 700.0f;

        // Calculate E1(v) using 3-segment approximation
        float exp1_v = exp1_approx(v);

        // MMSE-LSA gain: G_H1 = (ξ/(1+ξ)) × exp(0.5 × E1(v))
        float gain_mmse = xi_ratio * fast_exp(0.5f * exp1_v);

        // Clamp gain_mmse to valid range
        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f) gain_mmse = 1.0f;

        // Log-domain SPP weighting
        float log_gain_mmse = fast_log(gain_mmse + 1e-10f);
        float log_gain = spp_k * log_gain_mmse + (1.0f - spp_k) * log_g_min;

        // Log-domain temporal smoothing
        if (self->is_initialized) {
            float log_gain_prev_k = self->log_gain_prev[k];

            if (self->use_asymmetric_smoothing) {
                float alpha;
                if (log_gain > log_gain_prev_k) {
                    alpha = alpha_attack;
                } else {
                    alpha = alpha_decay;
                }
                log_gain = alpha * log_gain_prev_k + (1.0f - alpha) * log_gain;
            } else {
                log_gain = self->alpha_g * log_gain_prev_k +
                          (1.0f - self->alpha_g) * log_gain;
            }
        }

        // Convert back to linear domain and clamp
#ifdef USE_FAST_GAIN_SMOOTHING
        float gain;
        float log_gain_save;
        if (log_gain < log_g_min) {
            gain = g_min;
            log_gain_save = log_g_min;
        } else if (log_gain > 0.0f) {
            gain = 1.0f;
            log_gain_save = 0.0f;
        } else {
            gain = fast_exp(log_gain);
            log_gain_save = log_gain;
        }
        gain_out[k] = gain;
        self->log_gain_prev[k] = log_gain_save;
#else
        float gain = fast_exp(log_gain);

#ifndef USE_SINGLE_CLAMP
        if (gain < g_min) gain = g_min;
        if (gain > 1.0f) gain = 1.0f;
#endif

        gain_out[k] = gain;
        self->log_gain_prev[k] = fast_log(gain + 1e-10f);
#endif
    }

    self->is_initialized = true;
}
#endif
