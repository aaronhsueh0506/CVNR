/* Private cross-TU tuning updates. Not part of the public ANR API. */
#ifndef ANR_INTERNAL_H
#define ANR_INTERNAL_H

#include "anr_types.h"
#include "noise_estimator.h"
#include "utility/simd_kernels.h"  /* SK_HAVE_NEON */
#include "spp_estimator.h"

/* ANR_VECTOR selects the NEON twin of every kernel: <name>_scalar defines the arithmetic,
 * <name>_neon matches it bit for bit except NaN payload bits. ANR_REFERENCE_KERNELS forces the
 * scalar twins. */
#if SK_HAVE_NEON && !defined(ANR_REFERENCE_KERNELS)
#define ANR_VECTOR 1
#else
#define ANR_VECTOR 0
#endif

/* Storage class of the kernel twins. The scalar twins of a vector build and the vector twins of a
 * reference build are compiled but may stay unreferenced.
 */
#if defined(__GNUC__) || defined(__clang__)
#define ANR_TWIN static inline __attribute__((unused))
#else
#define ANR_TWIN static inline
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Update noise-tracker scalars while preserving noise/min-ring/init/scene state. Caller must
 * keep L and num_init_frames unchanged.
 */
void noise_estimator_apply_config_scalars(NoiseEstimator* self,
                                          const AnrConfig* config);

/* Noise-tracker variants whose startup rows share the minimum ring's storage. Same contract as the
 * standalone get_mem_size/init/create, but accumulate_init_power() and init_noise() are ignored once
 * initialized: re-accumulate every startup row after noise_estimator_reset().
 */
size_t noise_estimator_get_mem_size_shared_startup(int n_freqs, const AnrConfig* config);
NoiseEstimator* noise_estimator_init_shared_startup(void* mem, size_t mem_size, int n_freqs,
                                                    const AnrConfig* config);
NoiseEstimator* noise_estimator_create_shared_startup(int n_freqs, const AnrConfig* config);

/* Update SPP scalars while preserving a-priori-SNR history. */
void spp_apply_config_scalars(SppEstimator* self,
                              const AnrConfig* config);

#ifdef __cplusplus
}
#endif

#endif /* ANR_INTERNAL_H */
