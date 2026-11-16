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

/* Frozen-bin reseed run: NR_FROZEN_REF_FRAMES hops authored at NR_FROZEN_REF_HOP_MS, retimed to the grid and
 * rounded up (2.048 s, four of the default minimum-statistics windows). */
#ifndef NR_FROZEN_REF_FRAMES
#define NR_FROZEN_REF_FRAMES 128
#endif
#define NR_FROZEN_REF_HOP_MS 16

/* The standalone get_mem_size/init/create are the test oracle; production uses the *_shared_startup variants. */
/* Heap instance for n_freqs bins; NULL on invalid dimensions or allocation failure. */
NoiseEstimator* noise_estimator_create(int n_freqs, const AnrConfig* config);

/* Caller-owned memory: 16-byte aligned, at least noise_estimator_get_mem_size() bytes; no
 * internal allocation. */
size_t noise_estimator_get_mem_size(int n_freqs, const AnrConfig* config);
NoiseEstimator* noise_estimator_init(void* mem, size_t mem_size,
                                     int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void noise_estimator_destroy(NoiseEstimator* self);

/* Stores power[n_freqs] for init frame frame_idx in [0, num_init_frames). */
void noise_estimator_accumulate_init_power(NoiseEstimator* self, const float* power,
                                           int frame_idx);

/* Initializes each bin to the 30th percentile of the n_frames stored rows. */
void noise_estimator_init_noise(NoiseEstimator* self, int n_frames);

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
