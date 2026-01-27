/**
 * mmse_lsa_gain.h - MMSE-LSA Gain Calculator
 *
 * Minimum Mean Square Error Log-Spectral Amplitude estimator
 * Based on Ephraim-Malah 1985
 */

#ifndef MMSE_LSA_GAIN_H
#define MMSE_LSA_GAIN_H

#include "mmse_lsa_types.h"

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct MmseLsaGain MmseLsaGain;

/**
 * Create MMSE-LSA gain calculator
 *
 * @param n_freqs Number of frequency bins
 * @param config Configuration parameters
 * @return Calculator instance, or NULL on error
 */
MmseLsaGain* mmse_lsa_gain_create(int n_freqs, const MmseLsaConfig* config);

/**
 * Destroy gain calculator
 */
void mmse_lsa_gain_destroy(MmseLsaGain* self);

/**
 * Calculate MMSE-LSA gain with SPP weighting
 *
 * @param self Calculator instance
 * @param spp Speech presence probability [n_freqs]
 * @param xi A priori SNR [n_freqs]
 * @param gamma A posteriori SNR [n_freqs]
 * @param gain_out Output gain [n_freqs]
 */
void mmse_lsa_gain_calculate(
    MmseLsaGain* self,
    const float* spp,
    const float* xi,
    const float* gamma,
    float* gain_out
);

#ifdef USE_SHARED_XI_RATIO
/**
 * Extended gain calculation with pre-computed v values
 * Avoids recomputing xi_ratio = xi/(1+xi)
 *
 * @param v_in Pre-computed v = xi/(1+xi) * gamma [n_freqs] (can be NULL)
 */
void mmse_lsa_gain_calculate_ex(
    MmseLsaGain* self,
    const float* spp,
    const float* xi,
    const float* gamma,
    const float* v_in,
    float* gain_out
);
#endif

/**
 * Reset calculator state
 */
void mmse_lsa_gain_reset(MmseLsaGain* self);

/**
 * Get number of frequency bins
 */
int mmse_lsa_gain_get_n_freqs(const MmseLsaGain* self);

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_GAIN_H
