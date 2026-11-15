/* Decision-directed speech-presence probability estimator (Cohen and Berdugo). */

#ifndef SPP_ESTIMATOR_H
#define SPP_ESTIMATOR_H

#include "anr_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SppEstimator SppEstimator;

/* Create heap state for n_freqs bins using alpha_xi, q and xi_min_db; returns NULL on error. */
SppEstimator* spp_create(int n_freqs, const AnrConfig* config);

/* Caller-owned memory: 16-byte aligned, at least spp_get_mem_size() bytes; no internal
 * allocation. */
size_t spp_get_mem_size(int n_freqs);
SppEstimator* spp_init(void* mem, size_t mem_size,
                       int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void spp_destroy(SppEstimator* self);

/* Estimates SPP, a-priori SNR xi and posterior SNR gamma, plus the gain stage's v = xi/(1+xi)*gamma
 * clamped to [1e-10, 700] (NaN passes) and xi/(1+xi). enhanced_psd_prev may be NULL: DD xi needs it
 * and a prior call, else xi = max(gamma - 1, xi_min). */
void spp_estimate(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out,
    float* v_out,
    float* ratio_out
);

/* Clear estimator history. */
void spp_reset(SppEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // SPP_ESTIMATOR_H
