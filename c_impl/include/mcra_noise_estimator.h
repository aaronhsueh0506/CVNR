/* MCRA noise estimator: minima-controlled recursive averaging (Cohen and Berdugo). */

#ifndef MCRA_NOISE_ESTIMATOR_H
#define MCRA_NOISE_ESTIMATOR_H

#include "anr_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct McraNoiseEstimator McraNoiseEstimator;

/* Create heap state for n_freqs bins; returns NULL on invalid dimensions or allocation
 * failure.
 */
McraNoiseEstimator* mcra_create(int n_freqs, const AnrConfig* config);

/* Query size, then initialize in caller-owned memory. Buffer must be 16-byte aligned and at
 * least mcra_get_mem_size() bytes; no internal allocation.
 */
size_t mcra_get_mem_size(int n_freqs, const AnrConfig* config);
McraNoiseEstimator* mcra_init(void* mem, size_t mem_size,
                              int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void mcra_destroy(McraNoiseEstimator* self);

/* Accumulate power[n_freqs] at frame_idx in [0, num_init_frames). Used for exact
 * initialization unless USE_FAST_PERCENTILE is defined.
 */
void mcra_accumulate_init_power(McraNoiseEstimator* self, const float* power, int frame_idx);

/* Initialize from power_sum[n_freqs] and n_frames. Exact path uses the accumulated 30th
 * percentile; USE_FAST_PERCENTILE uses mean * 0.23.
 */
void mcra_init_noise(McraNoiseEstimator* self, const float* power_sum, int n_frames);

/* Update with power[n_freqs] and optional external SPP[n_freqs] (NULL selects internal SPP). */
void mcra_update(McraNoiseEstimator* self, const float* power, const float* spp);

/* When slow_lf_rise is true, bins [0, slow_lf_bins) fall normally but rise no faster than
 * alpha_d_speech, protecting weak low-frequency speech.
 */
void mcra_update_ex(McraNoiseEstimator* self,
                    const float* power,
                    const float* spp,
                    bool slow_lf_rise,
                    int slow_lf_bins,
                    float alpha_d_speech);

/* Borrowed noise PSD[n_freqs] in power units. */
const float* mcra_get_noise_psd(const McraNoiseEstimator* self);

/* Borrowed smoothed internal speech indicator[n_freqs]. */
const float* mcra_get_spp(const McraNoiseEstimator* self);

/* True after noise initialization. */
bool mcra_is_initialized(const McraNoiseEstimator* self);

/* Clear tracking state. */
void mcra_reset(McraNoiseEstimator* self);

/* Frequency-bin count. */
int mcra_get_n_freqs(const McraNoiseEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // MCRA_NOISE_ESTIMATOR_H
