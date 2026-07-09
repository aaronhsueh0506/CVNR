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

#ifdef USE_EXT_MEM
/**
 * Query the total memory size (bytes) needed for a denoiser instance, including
 * its MCRA and SPP sub-modules. Call this to size the single block you hand to
 * mmse_lsa_create(). Depends only on config (fft_size/L/num_init_frames), so it
 * can be evaluated once at startup.
 */
size_t mmse_lsa_query_memsize(const MmseLsaConfig* config);

/**
 * Create denoiser in caller-provided memory (no internal malloc). The whole
 * instance — struct, all spectral state arrays, and the MCRA/SPP sub-modules —
 * lives in `mem`. mmse_lsa_destroy() frees nothing; the caller owns and releases
 * the block (which may be a static array or a Novatek hd_common_mem block).
 *
 * @param config   Configuration parameters
 * @param mem      Pre-allocated buffer (NR_MEM_ALIGN-aligned)
 * @param mem_size Size of buffer (>= mmse_lsa_query_memsize(config))
 * @return Denoiser instance (points into mem), or NULL on error
 */
MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config,
                                 void* mem, size_t mem_size);
#else
/**
 * Create denoiser (heap allocation).
 */
MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config);
#endif

/** Destroy and free resources. Under USE_EXT_MEM this is a no-op (caller owns memory). */
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

/**
 * Compute the per-bin NR gain for one frame WITHOUT applying it, optionally
 * folding an external residual-echo PSD into the noise floor (the Speex/Habets
 * "echo-as-extra-noise" unified gain, ξ = S²/(N² + R²)). Mirrors the Python
 * denoise_spectrum(..., extra_noise_psd=R²): the augmented noise N²+R² feeds the
 * SPP / a-priori-SNR estimate, while the MCRA noise tracker keeps updating from
 * the clean power only (R² does not pollute the noise estimate).
 *
 * Use this to drive an external AEC(linear) → NR → RES combine: feed the AEC's
 * windowed error spectrum as spectrum_in and ctx.r2/32768² as extra_noise_psd,
 * then combine gain_out with the AEC3 res_gain downstream.
 *
 * @param self           Denoiser instance
 * @param spectrum_in    Complex input [n_freqs] — caller's FFT output (e.g. E(f))
 * @param extra_noise_psd Extra noise PSD [n_freqs] on the |spectrum_in|² scale,
 *                        or NULL to behave exactly like the plain noise-only NR
 * @param gain_out       Output per-bin gain [n_freqs], linear [g_min, 1]
 * @return 0 on success, <0 on error
 */
int mmse_lsa_process_gain(MmseLsaDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out);

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
