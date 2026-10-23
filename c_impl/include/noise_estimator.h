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

typedef struct NoiseEstimator NoiseEstimator;

/* Heap instance for n_freqs bins; NULL on invalid dimensions or allocation failure. */
NoiseEstimator* noise_estimator_create(int n_freqs, const AnrConfig* config);

/* Caller-owned memory: 16-byte aligned, at least noise_estimator_get_mem_size() bytes; no
 * internal allocation. */
size_t noise_estimator_get_mem_size(int n_freqs, const AnrConfig* config);
NoiseEstimator* noise_estimator_init(void* mem, size_t mem_size,
                                     int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void noise_estimator_destroy(NoiseEstimator* self);

/* Stores power[n_freqs] for init frame frame_idx in [0, num_init_frames); no-op with
 * USE_FAST_PERCENTILE. */
void noise_estimator_accumulate_init_power(NoiseEstimator* self, const float* power,
                                           int frame_idx);

/* Initializes from power_sum[n_freqs] over n_frames: 30th percentile of the stored rows, or
 * mean * 0.23 with USE_FAST_PERCENTILE. */
void noise_estimator_init_noise(NoiseEstimator* self, const float* power_sum, int n_frames);

/* Updates with power[n_freqs] and optional external SPP[n_freqs] (NULL: internal SPP). With
 * slow_lf_rise, bins [0, slow_lf_bins) rise no faster than alpha_d_speech. */
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
