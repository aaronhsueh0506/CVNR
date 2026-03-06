/**
 * mcra_noise_estimator.h - MCRA Noise Estimator
 *
 * Minima Controlled Recursive Averaging (MCRA)
 * Based on Cohen & Berdugo (2001)
 */

#ifndef MCRA_NOISE_ESTIMATOR_H
#define MCRA_NOISE_ESTIMATOR_H

#include "mmse_lsa_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct McraNoiseEstimator McraNoiseEstimator;

#ifdef USE_EXT_MEM
/**
 * Query memory size needed for MCRA estimator
 */
size_t mcra_query_memsize(int n_freqs, const MmseLsaConfig* config);

/**
 * Create MCRA estimator using pre-allocated memory
 */
McraNoiseEstimator* mcra_create(int n_freqs, const MmseLsaConfig* config,
                                 void* mem, size_t mem_size);
#else
/**
 * Create MCRA noise estimator
 *
 * @param n_freqs Number of frequency bins
 * @param config Configuration parameters
 * @return Estimator instance, or NULL on error
 */
McraNoiseEstimator* mcra_create(int n_freqs, const MmseLsaConfig* config);
#endif

/**
 * Destroy MCRA estimator
 */
void mcra_destroy(McraNoiseEstimator* self);

/**
 * Accumulate power spectrum for exact percentile calculation
 * Only available when USE_FAST_PERCENTILE is NOT defined.
 *
 * @param self Estimator instance
 * @param power Current power spectrum [n_freqs]
 * @param frame_idx Frame index (0 to num_init_frames-1)
 */
void mcra_accumulate_init_power(McraNoiseEstimator* self, const float* power, int frame_idx);

/**
 * Initialize noise estimate from accumulated power
 *
 * When USE_FAST_PERCENTILE is defined: Uses mean × 0.17 approximation
 * When USE_FAST_PERCENTILE is NOT defined: Uses exact 20th percentile via Quickselect
 *
 * @param self Estimator instance
 * @param power_sum Accumulated power spectrum [n_freqs]
 * @param n_frames Number of frames accumulated
 */
void mcra_init_noise(McraNoiseEstimator* self, const float* power_sum, int n_frames);

/**
 * Update noise estimate with new frame
 *
 * @param self Estimator instance
 * @param power Current power spectrum [n_freqs]
 * @param spp Speech presence probability [n_freqs] (can be NULL)
 */
void mcra_update(McraNoiseEstimator* self, const float* power, const float* spp);

/**
 * Get current noise PSD estimate
 *
 * @param self Estimator instance
 * @return Pointer to noise PSD array [n_freqs]
 */
const float* mcra_get_noise_psd(const McraNoiseEstimator* self);

/**
 * Get internal SPP from MCRA (speech indicator smoothed)
 *
 * @param self Estimator instance
 * @return Pointer to internal SPP array [n_freqs]
 */
const float* mcra_get_spp(const McraNoiseEstimator* self);

/**
 * Check if MCRA is initialized
 */
bool mcra_is_initialized(const McraNoiseEstimator* self);

/**
 * Reset estimator state
 */
void mcra_reset(McraNoiseEstimator* self);

/**
 * Get number of frequency bins
 */
int mcra_get_n_freqs(const McraNoiseEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // MCRA_NOISE_ESTIMATOR_H
