/**
 * mmse_lsa_denoiser.h - MMSE-LSA Denoiser Main API
 *
 * V3-2 MMSE-LSA Speech Denoiser
 * Streaming by hop_size (frame_shift)
 *
 * Based on Ephraim-Malah 1985
 */

#ifndef MMSE_LSA_DENOISER_H
#define MMSE_LSA_DENOISER_H

#include "mmse_lsa_types.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque denoiser structure
typedef struct MmseLsaDenoiser MmseLsaDenoiser;

// ============================================================================
// Core API
// ============================================================================

#ifdef USE_EXT_MEM
/**
 * Query memory size needed for denoiser (for external allocation)
 */
size_t mmse_lsa_query_memsize(const MmseLsaConfig* config);

/**
 * Create denoiser using pre-allocated memory (no internal malloc)
 *
 * Note: mmse_lsa_destroy() will NOT free the buffer — caller manages it.
 */
MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config,
                                  void* mem, size_t mem_size);
#else
/**
 * Create MMSE-LSA denoiser
 *
 * @param config Configuration parameters
 * @return Denoiser instance, or NULL on error
 */
MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config);
#endif

/**
 * Destroy denoiser and free all resources
 */
void mmse_lsa_destroy(MmseLsaDenoiser* self);

/**
 * Process hop_size samples (streaming core)
 *
 * Input:  samples_in[hop_size]  - New input samples
 * Output: samples_out[hop_size] - Processed output samples
 *
 * Note: First few calls may output silence while initializing
 *
 * @param self Denoiser instance
 * @param samples_in Input samples [hop_size]
 * @param samples_out Output samples [hop_size]
 * @return 0 on success, <0 on error
 */
int mmse_lsa_process(
    MmseLsaDenoiser* self,
    const float* samples_in,
    float* samples_out
);

/**
 * Extended process with optional external inputs
 *
 * Pass NULL for internal computation, or provide external values to save computation
 *
 * @param self Denoiser instance
 * @param samples_in Input samples [hop_size]
 * @param samples_out Output samples [hop_size]
 * @param noise_psd_ext External noise PSD [n_freqs] or NULL
 * @param spp_ext External SPP [n_freqs] or NULL
 * @param xi_ext External a priori SNR [n_freqs] or NULL
 * @param gamma_ext External a posteriori SNR [n_freqs] or NULL
 * @return 0 on success, <0 on error
 */
int mmse_lsa_process_ex(
    MmseLsaDenoiser* self,
    const float* samples_in,
    float* samples_out,
    const float* noise_psd_ext,
    const float* spp_ext,
    const float* xi_ext,
    const float* gamma_ext
);

/**
 * Reset denoiser state (call when switching audio streams)
 */
void mmse_lsa_reset(MmseLsaDenoiser* self);

// ============================================================================
// Query API
// ============================================================================

/**
 * Get hop size (samples per process call)
 */
int mmse_lsa_get_hop_size(const MmseLsaDenoiser* self);

/**
 * Get frame size in samples
 */
int mmse_lsa_get_frame_size(const MmseLsaDenoiser* self);

/**
 * Get number of frequency bins
 */
int mmse_lsa_get_n_freqs(const MmseLsaDenoiser* self);

/**
 * Get latency in samples (due to OLA and initialization)
 */
int mmse_lsa_get_latency(const MmseLsaDenoiser* self);

/**
 * Check if noise estimation is initialized
 */
bool mmse_lsa_is_initialized(const MmseLsaDenoiser* self);

/**
 * Get current SPP (for visualization)
 *
 * @param self Denoiser instance
 * @param n_freqs Output: number of frequency bins
 * @return Pointer to SPP array [n_freqs], or NULL if not available
 */
const float* mmse_lsa_get_spp(const MmseLsaDenoiser* self, int* n_freqs);

/**
 * Get current noise PSD (for visualization)
 *
 * @param self Denoiser instance
 * @param n_freqs Output: number of frequency bins
 * @return Pointer to noise PSD array [n_freqs], or NULL if not available
 */
const float* mmse_lsa_get_noise_psd(const MmseLsaDenoiser* self, int* n_freqs);

#ifdef __cplusplus
}
#endif

#endif // MMSE_LSA_DENOISER_H
