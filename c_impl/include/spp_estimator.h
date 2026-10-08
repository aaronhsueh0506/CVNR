/* Decision-directed speech-presence probability estimator (Cohen and Berdugo). */

#ifndef SPP_ESTIMATOR_H
#define SPP_ESTIMATOR_H

#include "anr_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque structure
typedef struct SppEstimator SppEstimator;

/* Create heap state for n_freqs bins using alpha_xi, q and xi_min_db; returns NULL on error. */
SppEstimator* spp_create(int n_freqs, const AnrConfig* config);

/* Query size, then initialize in caller-owned memory. Buffer must be 16-byte aligned and at
 * least spp_get_mem_size() bytes; no internal allocation.
 */
size_t spp_get_mem_size(int n_freqs);
SppEstimator* spp_init(void* mem, size_t mem_size,
                       int n_freqs, const AnrConfig* config);

/* Free heap state; static memory remains caller-owned. */
void spp_destroy(SppEstimator* self);

/* Estimate SPP, a-priori SNR xi and posterior SNR gamma. All arrays have n_freqs entries.
 * Y_psd/noise_psd and output arrays are required. gain_prev/enhanced_psd_prev may be NULL;
 * enhanced PSD selects the DD power estimate, otherwise gain² * previous gamma is used.
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
/* Extended estimate also writes v = ξ/(1+ξ) * gamma when v_out is non-NULL, allowing gain
 * calculation to reuse the ratio.
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

/* Clear estimator history. */
void spp_reset(SppEstimator* self);

/* Frequency-bin count. */
int spp_get_n_freqs(const SppEstimator* self);

#ifdef __cplusplus
}
#endif

#endif // SPP_ESTIMATOR_H
