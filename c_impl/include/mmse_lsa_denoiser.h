/**
 * mmse_lsa_denoiser.h - MMSE-LSA Denoiser API (Frequency-Domain I/O)
 *
 * V3-2 MMSE-LSA Speech Denoiser — freq-domain variant.
 * Caller owns FFT / IFFT / windowing / OLA.
 * Input and output are complex spectra: Complex[n_freqs] per hop.
 *
 * Based on Ephraim-Malah 1985.
 */

#ifndef MMSE_LSA_DENOISER_H
#define MMSE_LSA_DENOISER_H

#include "mmse_lsa_types.h"
#include "fft_wrapper.h"    /* Complex type, fft_power, fft_apply_gain */
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque denoiser handle */
typedef struct MmseLsaDenoiser MmseLsaDenoiser;

/* ============================================================================
 * Core API
 * ========================================================================== */

/**
 * Create denoiser (heap allocation).
 */
MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config);

/** Destroy and free resources. */
void mmse_lsa_destroy(MmseLsaDenoiser* self);

/**
 * Process one FFT frame (frequency-domain I/O).
 *
 * Caller is responsible for windowing, forward FFT, inverse FFT, and OLA.
 * May be called in-place (spectrum_out == spectrum_in).
 *
 * @param self         Denoiser instance
 * @param spectrum_in  Complex input  [n_freqs]  — caller's FFT output
 * @param spectrum_out Complex output [n_freqs]  — NR gain applied
 * @return 0 on success, <0 on error
 */
int mmse_lsa_process(MmseLsaDenoiser* self,
                     const Complex*   spectrum_in,
                     Complex*         spectrum_out);

/** Reset all internal state (call when switching audio streams). */
void mmse_lsa_reset(MmseLsaDenoiser* self);

/* ============================================================================
 * Query API
 * ========================================================================== */

/** hop_size from config (samples; for caller reference only). */
int mmse_lsa_get_hop_size(const MmseLsaDenoiser* self);

/** frame_size from config (samples; for caller reference only). */
int mmse_lsa_get_frame_size(const MmseLsaDenoiser* self);

/** Number of frequency bins (fft_size/2 + 1). */
int mmse_lsa_get_n_freqs(const MmseLsaDenoiser* self);

/**
 * Algorithmic latency in samples.
 * Freq-domain NR itself has zero latency; returns 0.
 * Caller's IFFT+OLA adds frame_size latency — caller accounts for that.
 */
int mmse_lsa_get_latency(const MmseLsaDenoiser* self);

/** True once the noise estimator has completed its init frames. */
bool mmse_lsa_is_initialized(const MmseLsaDenoiser* self);

/** Current Speech Presence Probability per bin [n_freqs]. */
const float* mmse_lsa_get_spp(const MmseLsaDenoiser* self, int* n_freqs);

/** Current noise PSD estimate (power units) [n_freqs]. */
const float* mmse_lsa_get_noise_psd(const MmseLsaDenoiser* self, int* n_freqs);

/**
 * Most recent per-bin MMSE-LSA gain (linear, [g_min, 1]) [n_freqs].
 * Valid after at least one frame has been processed.
 */
const float* mmse_lsa_get_gain(const MmseLsaDenoiser* self, int* n_freqs);

#ifdef __cplusplus
}
#endif

#endif /* MMSE_LSA_DENOISER_H */
