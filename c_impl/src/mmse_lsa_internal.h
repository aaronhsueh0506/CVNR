/**
 * mmse_lsa_internal.h - cross-TU helpers that are NOT public API.
 *
 * These exist only so mmse_lsa_reconfigure() can swap tuning scalars on a
 * running instance without going through the construction-time helpers, which
 * also clear state. They are deliberately kept out of include/ : an integrator
 * has no reason to reach a sub-module's scalars directly, and publishing them
 * would widen the released API surface for an internal collaboration.
 *
 * Lives in src/ so the three implementation files pick it up through the
 * quoted-include same-directory rule -- no extra -I path, and nothing
 * installed alongside the public headers.
 */
#ifndef MMSE_LSA_INTERNAL_H
#define MMSE_LSA_INTERNAL_H

#include "mmse_lsa_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Swap the MCRA tuning scalars on a RUNNING estimator without touching the
 * tracked noise floor, the min-tracking ring position, the init accumulation
 * or the scene-change run length. `config->L` and `config->num_init_frames`
 * size caller-owned buffers, so the caller must have established that both
 * are unchanged before calling this. */
void mcra_apply_config_scalars(McraNoiseEstimator* self,
                               const MmseLsaConfig* config);

/* Swap the SPP tuning scalars on a RUNNING estimator without discarding the
 * a-priori-SNR history. */
void spp_apply_config_scalars(SppEstimator* self,
                              const MmseLsaConfig* config);

#ifdef __cplusplus
}
#endif

#endif /* MMSE_LSA_INTERNAL_H */
