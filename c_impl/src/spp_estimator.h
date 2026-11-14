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

/* Estimates SPP, a-priori SNR xi and posterior SNR gamma over n_freqs entries; v_out receives
 * v = xi/(1+xi) * gamma and may be NULL, as may gain_prev/enhanced_psd_prev. The decision-directed
 * xi needs both previous-hop inputs and a prior call; otherwise xi = max(gamma - 1, xi_min). */
void spp_estimate(
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

/* Clear estimator history. */
void spp_reset(SppEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // SPP_ESTIMATOR_H
