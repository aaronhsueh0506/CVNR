/**
 * spp_estimator.h - Speech Presence Probability Estimator
 *
 * Estimates SPP using Decision Directed method
 * Based on Cohen & Berdugo (2001)
 */

#ifndef SPP_ESTIMATOR_H
#define SPP_ESTIMATOR_H

#include "mmse_lsa_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct SppEstimator SppEstimator;

/**
 * Create SPP estimator
 *
 * @param n_freqs Number of frequency bins
 * @param config Configuration parameters (alpha_xi, q, xi_min_db)
 * @return Estimator instance, or NULL on error
 */
SppEstimator* spp_create(int n_freqs, const MmseLsaConfig* config);

/**
 * Destroy SPP estimator
 */
void spp_destroy(SppEstimator* self);

/**
 * Estimate SPP, a priori SNR (xi), and a posteriori SNR (gamma)
 *
 * @param self Estimator instance
 * @param Y_psd Noisy power spectrum [n_freqs]
 * @param noise_psd Noise PSD estimate [n_freqs]
 * @param gain_prev Previous frame gain [n_freqs] (can be NULL for first frame)
 * @param enhanced_psd_prev Previous enhanced PSD [n_freqs] (can be NULL)
 * @param spp_out Output SPP [n_freqs]
 * @param xi_out Output a priori SNR [n_freqs]
 * @param gamma_out Output a posteriori SNR [n_freqs]
 */
void spp_estimate(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* gain_prev,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out
);

#ifdef USE_SHARED_XI_RATIO
/**
 * Extended SPP estimate that also outputs v = xi/(1+xi) * gamma
 * This allows gain calculator to avoid recomputing xi_ratio
 *
 * @param v_out Output v values [n_freqs] (can be NULL)
 */
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
);
#endif

/**
 * Reset estimator state
 */
void spp_reset(SppEstimator* self);

/**
 * Get number of frequency bins
 */
int spp_get_n_freqs(const SppEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // SPP_ESTIMATOR_H
