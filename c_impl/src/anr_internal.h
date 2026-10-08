/* Private cross-TU tuning updates. Not part of the public ANR API. */
#ifndef ANR_INTERNAL_H
#define ANR_INTERNAL_H

#include "anr_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"

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
