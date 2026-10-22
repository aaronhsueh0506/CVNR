/* Noise PSD tracker. Smooths the input power, follows its minimum over a window of L frames,
 * marks a bin speech-active when the smoothed power exceeds that minimum by a threshold, and
 * averages the power into the noise estimate at a rate that slows where speech is marked.
 */

#ifndef NOISE_ESTIMATOR_H
#define NOISE_ESTIMATOR_H

#include "anr_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct NoiseEstimator NoiseEstimator;

/* Create heap state for n_freqs bins; returns NULL on invalid dimensions or allocation
 * failure.
 */
NoiseEstimator* noise_estimator_create(int n_freqs, const AnrConfig* config);

/* Query size, then initialize in caller-owned memory. Buffer must be 16-byte aligned and at
 * least noise_estimator_get_mem_size() bytes; no internal allocation.
 */
size_t noise_estimator_get_mem_size(int n_freqs, const AnrConfig* config);
NoiseEstimator* noise_estimator_init(void* mem, size_t mem_size,
                                     int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void noise_estimator_destroy(NoiseEstimator* self);

/* Accumulate power[n_freqs] at frame_idx in [0, num_init_frames). Used for exact
 * initialization unless USE_FAST_PERCENTILE is defined.
 */
void noise_estimator_accumulate_init_power(NoiseEstimator* self, const float* power,
                                           int frame_idx);

/* Initialize from power_sum[n_freqs] and n_frames. Exact path uses the accumulated 30th
 * percentile; USE_FAST_PERCENTILE uses mean * 0.23.
 */
void noise_estimator_init_noise(NoiseEstimator* self, const float* power_sum, int n_frames);

/* Update with power[n_freqs] and optional external SPP[n_freqs] (NULL selects internal SPP).
 * When slow_lf_rise is true, bins [0, slow_lf_bins) fall normally but rise no faster than
 * alpha_d_speech, protecting weak low-frequency speech.
 */
void noise_estimator_update_ex(NoiseEstimator* self,
                               const float* power,
                               const float* spp,
                               bool slow_lf_rise,
                               int slow_lf_bins,
                               float alpha_d_speech);

/* Borrowed noise PSD[n_freqs] in power units. */
const float* noise_estimator_get_noise_psd(const NoiseEstimator* self);

/* Clear tracking state. */
void noise_estimator_reset(NoiseEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // NOISE_ESTIMATOR_H
