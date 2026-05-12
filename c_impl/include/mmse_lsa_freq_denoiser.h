/**
 * mmse_lsa_freq_denoiser.h - MMSE-LSA Denoiser (Frequency-Domain I/O)
 *
 * Variant of the MMSE-LSA denoiser where caller owns FFT/IFFT/OLA/windowing.
 * Input and output are complex spectra (n_freqs = fft_size/2 + 1).
 *
 * Intended for pipeline integration where multiple algorithms share the same
 * FFT frame (e.g. AEC -> NR chaining in the frequency domain).
 *
 * Configuration fixed at: 16 kHz / frame=320 / hop=160 / fft=512 / n_freqs=257
 * (config.fft_size drives n_freqs; other freq-domain params are still used)
 */

#ifndef MMSE_LSA_FREQ_DENOISER_H
#define MMSE_LSA_FREQ_DENOISER_H

#include "mmse_lsa_types.h"
#include "fft_wrapper.h"   /* Complex type, fft_power, fft_apply_gain */
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handle */
typedef struct MmseLsaFreqDenoiser MmseLsaFreqDenoiser;

/* =========================================================================
 * Lifecycle
 * ========================================================================= */

/**
 * Create freq-domain denoiser (heap allocation).
 */
MmseLsaFreqDenoiser* mmse_lsa_freq_create(const MmseLsaConfig* config);

/**
 * Initialize freq-domain denoiser in pre-allocated memory (static/embedded).
 *
 * @param mem       16-byte aligned buffer
 * @param mem_size  Must be >= mmse_lsa_freq_get_mem_size(config)
 */
MmseLsaFreqDenoiser* mmse_lsa_freq_init(void* mem, size_t mem_size,
                                         const MmseLsaConfig* config);

/** Required buffer size for mmse_lsa_freq_init(). */
size_t mmse_lsa_freq_get_mem_size(const MmseLsaConfig* config);

/** Destroy and free (no-op if created via mmse_lsa_freq_init). */
void mmse_lsa_freq_destroy(MmseLsaFreqDenoiser* self);

/* =========================================================================
 * Processing
 * ========================================================================= */

/**
 * Process one FFT frame in the frequency domain.
 *
 * Caller is responsible for:
 *   - Windowing the time-domain frame (sqrt-Hann or equivalent)
 *   - Running the forward FFT  ->  spectrum_in
 *   - Calling this function    ->  spectrum_out (NR gain applied)
 *   - Running the inverse FFT  <-  spectrum_out
 *   - Overlap-add synthesis
 *
 * @param self         Denoiser instance
 * @param spectrum_in  Complex input spectrum [n_freqs]  (caller's FFT output)
 * @param spectrum_out Complex output spectrum [n_freqs] (NR gain applied)
 *                     May alias spectrum_in (in-place is supported).
 * @return 0 on success, <0 on error
 */
int mmse_lsa_freq_process(MmseLsaFreqDenoiser* self,
                           const Complex* spectrum_in,
                           Complex* spectrum_out);

/** Reset all internal state (call when switching audio streams). */
void mmse_lsa_freq_reset(MmseLsaFreqDenoiser* self);

/* =========================================================================
 * Query
 * ========================================================================= */

/** Number of frequency bins (fft_size/2 + 1). */
int mmse_lsa_freq_get_n_freqs(const MmseLsaFreqDenoiser* self);

/** True once the noise estimator has completed its initialization frames. */
bool mmse_lsa_freq_is_initialized(const MmseLsaFreqDenoiser* self);

/**
 * Get the most recent per-bin MMSE-LSA gain (linear, [g_min, 1]).
 * @param n_freqs  Optional output: number of bins (may be NULL).
 */
const float* mmse_lsa_freq_get_gain(const MmseLsaFreqDenoiser* self,
                                     int* n_freqs);

/**
 * Get the current noise PSD estimate (power units).
 * @param n_freqs  Optional output: number of bins (may be NULL).
 */
const float* mmse_lsa_freq_get_noise_psd(const MmseLsaFreqDenoiser* self,
                                          int* n_freqs);

/**
 * Get the current Speech Presence Probability per bin.
 * @param n_freqs  Optional output: number of bins (may be NULL).
 */
const float* mmse_lsa_freq_get_spp(const MmseLsaFreqDenoiser* self,
                                    int* n_freqs);

#ifdef __cplusplus
}
#endif

#endif /* MMSE_LSA_FREQ_DENOISER_H */
