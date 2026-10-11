/* Private cross-TU tuning updates. Not part of the public ANR API. */
#ifndef ANR_INTERNAL_H
#define ANR_INTERNAL_H

#include "anr_types.h"
#include "mcra_noise_estimator.h"
#include "simd_kernels.h"  /* SK_HAVE_NEON */
#include "spp_estimator.h"

/* ANR_VECTOR selects the NEON twin of every kernel in this library. Each kernel is a static
 * function pair: <name>_scalar defines the arithmetic, <name>_neon reproduces it bit for bit.
 * ANR_REFERENCE_KERNELS forces the scalar path so one build can be compared with another.
 */
#if SK_HAVE_NEON && !defined(ANR_REFERENCE_KERNELS)
#define ANR_VECTOR 1
#else
#define ANR_VECTOR 0
#endif

/* Scalar twins are compiled in every build; the vector build calls them only from tests. */
#if defined(__GNUC__) || defined(__clang__)
#define ANR_MAYBE_UNUSED __attribute__((unused))
#else
#define ANR_MAYBE_UNUSED
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Update MCRA scalars while preserving noise/min-ring/init/scene state. Caller must keep L and
 * num_init_frames unchanged.
 */
void mcra_apply_config_scalars(McraNoiseEstimator* self,
                               const AnrConfig* config);

/* Update SPP scalars while preserving a-priori-SNR history. */
void spp_apply_config_scalars(SppEstimator* self,
                              const AnrConfig* config);

#ifdef __cplusplus
}
#endif

#endif /* ANR_INTERNAL_H */
