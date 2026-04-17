/**
 * spp_estimator.c - Speech Presence Probability Estimator
 *
 * Decision Directed method for SPP estimation
 * Based on Cohen & Berdugo (2001)
 *
 * SPP is a soft decision measure indicating the probability of
 * speech presence at each time-frequency bin.
 */

#include "spp_estimator.h"
#include "fft_wrapper.h"  /* ALIGN16 */
#include "fast_math.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

// Internal structure
struct SppEstimator {
    int n_freqs;
    int is_static;      // 1 = placed in external memory, skip free

    float alpha;        // A priori SNR smoothing factor
    float q;            // Prior speech probability
    float xi_min;       // Minimum a priori SNR (linear)
    float prior_ratio;  // (1-q)/q precomputed

    // State arrays [n_freqs]
    float* xi_prev;     // Previous frame a priori SNR
    float* gamma_prev;  // Previous frame a posteriori SNR
    float* noise_psd_prev;  // Previous frame noise PSD (for DD xi_dd_term1)

    bool is_initialized;
    int frame_count;
};

SppEstimator* spp_create(int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    SppEstimator* self = (SppEstimator*)calloc(1, sizeof(SppEstimator));
    if (!self) return NULL;

    self->n_freqs = n_freqs;
    self->alpha = config->alpha_xi;
    // Fix #9: clip q to (eps, 1-eps) so prior_ratio is well defined
    {
        const float _eps = 1e-6f;
        float q_clipped = config->q;
        if (q_clipped < _eps) q_clipped = _eps;
        if (q_clipped > 1.0f - _eps) q_clipped = 1.0f - _eps;
        self->q = q_clipped;
        self->prior_ratio = (1.0f - q_clipped) / q_clipped;
    }
    self->xi_min = powf(10.0f, config->xi_min_db / 10.0f);

    // Allocate state arrays
    self->xi_prev = (float*)calloc(n_freqs, sizeof(float));
    self->gamma_prev = (float*)calloc(n_freqs, sizeof(float));
    self->noise_psd_prev = (float*)calloc(n_freqs, sizeof(float));

    if (!self->xi_prev || !self->gamma_prev || !self->noise_psd_prev) {
        spp_destroy(self);
        return NULL;
    }

    self->is_initialized = false;
    self->frame_count = 0;

    return self;
}

/* --- Static memory API --- */

size_t spp_get_mem_size(int n_freqs) {
    size_t total = 0;
    total += ALIGN16(sizeof(SppEstimator));
    total += ALIGN16(n_freqs * sizeof(float));  /* xi_prev */
    total += ALIGN16(n_freqs * sizeof(float));  /* gamma_prev */
    total += ALIGN16(n_freqs * sizeof(float));  /* noise_psd_prev (Fix #3) */
    return total;
}

SppEstimator* spp_init(void* mem, size_t mem_size, int n_freqs, const MmseLsaConfig* config) {
    if (!mem || !config || n_freqs <= 0) return NULL;
    if (mem_size < spp_get_mem_size(n_freqs)) return NULL;

    uint8_t* ptr = (uint8_t*)mem;

    SppEstimator* self = (SppEstimator*)ptr;
    ptr += ALIGN16(sizeof(SppEstimator));
    memset(self, 0, sizeof(SppEstimator));

    self->n_freqs = n_freqs;
    self->is_static = 1;
    self->alpha = config->alpha_xi;
    // Fix #9: clip q to (eps, 1-eps) so prior_ratio is well defined
    {
        const float _eps = 1e-6f;
        float q_clipped = config->q;
        if (q_clipped < _eps) q_clipped = _eps;
        if (q_clipped > 1.0f - _eps) q_clipped = 1.0f - _eps;
        self->q = q_clipped;
        self->prior_ratio = (1.0f - q_clipped) / q_clipped;
    }
    self->xi_min = powf(10.0f, config->xi_min_db / 10.0f);

    self->xi_prev = (float*)ptr;
    ptr += ALIGN16(n_freqs * sizeof(float));
    memset(self->xi_prev, 0, n_freqs * sizeof(float));

    self->gamma_prev = (float*)ptr;
    ptr += ALIGN16(n_freqs * sizeof(float));
    memset(self->gamma_prev, 0, n_freqs * sizeof(float));

    self->noise_psd_prev = (float*)ptr;
    /* ptr += ALIGN16(n_freqs * sizeof(float)); */
    memset(self->noise_psd_prev, 0, n_freqs * sizeof(float));

    self->is_initialized = false;
    self->frame_count = 0;

    return self;
}

void spp_destroy(SppEstimator* self) {
    if (!self) return;
    if (self->is_static) return;

    if (self->xi_prev) free(self->xi_prev);
    if (self->gamma_prev) free(self->gamma_prev);
    if (self->noise_psd_prev) free(self->noise_psd_prev);

    free(self);
}

void spp_estimate(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* gain_prev,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out
) {
    if (!self || !Y_psd || !noise_psd || !spp_out || !xi_out || !gamma_out) return;

    int n_freqs = self->n_freqs;
    float alpha = self->alpha;
    float xi_min = self->xi_min;
    float prior_ratio = self->prior_ratio;

    // Fix #3: DD xi_dd_term1 should use previous frame's noise_psd.
    // On the first DD call (after one estimate()), noise_psd_prev already holds
    // the prior frame's noise; if not yet populated, fall back to current noise.
    const float* noise_for_dd = self->is_initialized ? self->noise_psd_prev : noise_psd;

    for (int k = 0; k < n_freqs; k++) {
        // 1. Calculate a posteriori SNR
        // γ = |Y|² / λ_n
        float gamma = Y_psd[k] / (noise_psd[k] + 1e-10f);
        gamma_out[k] = gamma;

        // 2. Estimate a priori SNR using Decision Directed method
        float xi;
        if (!self->is_initialized || gain_prev == NULL) {
            // First frame: direct estimate
            xi = gamma > 1.0f ? gamma - 1.0f : 0.0f;
        } else {
            // DD method: ξ = α·|X̂_{n-1}|²/λ_n_prev + (1-α)·max(γ-1, 0)
            float xi_dd_term1;
            if (enhanced_psd_prev != NULL) {
                // Use provided enhanced PSD (recommended)
                xi_dd_term1 = enhanced_psd_prev[k] / (noise_for_dd[k] + 1e-10f);
            } else {
                // Fallback: use gain²·γ_prev approximation
                float g2 = gain_prev[k] * gain_prev[k];
                xi_dd_term1 = g2 * self->gamma_prev[k];
            }

            float max_gamma_m1 = gamma > 1.0f ? gamma - 1.0f : 0.0f;
            float xi_dd = alpha * xi_dd_term1 + (1.0f - alpha) * max_gamma_m1;

            // Apply minimum constraint
            xi = xi_dd > xi_min ? xi_dd : xi_min;
        }
        xi_out[k] = xi;

        // 3. Calculate log-likelihood ratio
        // v = ξ/(1+ξ)·γ
        float v = xi / (1.0f + xi) * gamma;

        // 4. Calculate SPP using Cohen & Berdugo formula
        // SPP = 1 / (1 + prior_ratio × (1+ξ) × exp(-v))
        float term_xi = 1.0f + xi;
        float exp_neg_v = fast_exp_neg(v);
        spp_out[k] = 1.0f / (1.0f + prior_ratio * term_xi * exp_neg_v);

        // Save for next frame
        self->xi_prev[k] = xi;
        self->gamma_prev[k] = gamma;
    }

    // Fix #3: save current noise_psd for next frame's DD term
    memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));

    self->is_initialized = true;
    self->frame_count++;
}

void spp_reset(SppEstimator* self) {
    if (!self) return;

    memset(self->xi_prev, 0, self->n_freqs * sizeof(float));
    memset(self->gamma_prev, 0, self->n_freqs * sizeof(float));
    memset(self->noise_psd_prev, 0, self->n_freqs * sizeof(float));

    self->is_initialized = false;
    self->frame_count = 0;
}

bool spp_is_initialized(const SppEstimator* self) {
    return self ? self->is_initialized : false;
}

#ifdef USE_SHARED_XI_RATIO
void spp_estimate_ex(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* gain_prev,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out,
    float* v_out
) {
    if (!self || !Y_psd || !noise_psd || !spp_out || !xi_out || !gamma_out) return;

    int n_freqs = self->n_freqs;
    float alpha = self->alpha;
    float xi_min = self->xi_min;
    float prior_ratio = self->prior_ratio;

    // Fix #3: DD xi_dd_term1 uses previous frame's noise_psd
    const float* noise_for_dd = self->is_initialized ? self->noise_psd_prev : noise_psd;

    for (int k = 0; k < n_freqs; k++) {
        // 1. Calculate a posteriori SNR
        float gamma = Y_psd[k] / (noise_psd[k] + 1e-10f);
        gamma_out[k] = gamma;

        // 2. Estimate a priori SNR using Decision Directed method
        float xi;
        if (!self->is_initialized || gain_prev == NULL) {
            xi = gamma > 1.0f ? gamma - 1.0f : 0.0f;
        } else {
            float xi_dd_term1;
            if (enhanced_psd_prev != NULL) {
                xi_dd_term1 = enhanced_psd_prev[k] / (noise_for_dd[k] + 1e-10f);
            } else {
                float g2 = gain_prev[k] * gain_prev[k];
                xi_dd_term1 = g2 * self->gamma_prev[k];
            }

            float max_gamma_m1 = gamma > 1.0f ? gamma - 1.0f : 0.0f;
            float xi_dd = alpha * xi_dd_term1 + (1.0f - alpha) * max_gamma_m1;
            xi = xi_dd > xi_min ? xi_dd : xi_min;
        }
        xi_out[k] = xi;

        // 3. Calculate v = ξ/(1+ξ)·γ (compute term_xi once)
        float term_xi = 1.0f + xi;
        float v = (xi / term_xi) * gamma;

        // Output v for gain calculator to reuse
        if (v_out) {
            v_out[k] = v;
        }

        // 4. Calculate SPP
        float exp_neg_v = fast_exp_neg(v);
        spp_out[k] = 1.0f / (1.0f + prior_ratio * term_xi * exp_neg_v);

        // Save for next frame
        self->xi_prev[k] = xi;
        self->gamma_prev[k] = gamma;
    }

    // Fix #3: save current noise_psd for next frame's DD term
    memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));

    self->is_initialized = true;
    self->frame_count++;
}
#endif
