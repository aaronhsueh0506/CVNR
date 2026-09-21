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

/**
 * Static-memory companions to mmse_lsa_create (no internal malloc). Sizes and
 * places the whole instance — struct, all spectral state arrays, and the
 * MCRA/SPP sub-modules — in a single caller-provided block:
 *
 *     size_t bytes = mmse_lsa_get_mem_size(&config);
 *     void*  buf   = ... a caller-provided memory block (>= bytes) ...
 *     MmseLsaDenoiser* d = mmse_lsa_init(buf, bytes, &config);
 *
 * mmse_lsa_get_mem_size() and mmse_lsa_init() must walk fields in identical
 * order to keep alignment + bytes consistent. Depends only on config
 * (fft_size/L/num_init_frames), so it can be evaluated once at startup.
 *
 * @param mem      Caller-provided buffer, 16-byte aligned
 * @param mem_size Size of buffer (>= mmse_lsa_get_mem_size(config))
 * @param config   Configuration parameters
 * @return Denoiser instance (points into mem), or NULL on error / undersized buffer
 */
size_t mmse_lsa_get_mem_size(const MmseLsaConfig* config);
MmseLsaDenoiser* mmse_lsa_init(void* mem, size_t mem_size,
                                const MmseLsaConfig* config);

/**
 * Destroy and free resources. No-op for an instance created via mmse_lsa_init()
 * (static memory) — the caller owns and releases the block. Safe to call on
 * both instance kinds.
 */
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
 * @param gain_out       Output per-bin gain [n_freqs], linear [g_min, 1], or
 *                        NULL to skip the copy -- the gain is always computed
 *                        and left readable via mmse_lsa_get_gain() regardless
 * @return 0 on success, <0 on error
 */
int mmse_lsa_process_gain(MmseLsaDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out);

/** Reset all internal state (call when switching audio streams). */
void mmse_lsa_reset(MmseLsaDenoiser* self);

/* ── Runtime reconfiguration ──────────────────────────────────────────────
 * Swap the tuning scalars on a RUNNING instance. Nothing is reallocated, so
 * the grid (sample_rate / frame_size / hop_size / fft_size) and the two
 * pool-sizing fields (L, num_init_frames) must equal the instance's current
 * values; `target` must also pass mmse_lsa_validate_config() in full.
 *
 * State is PRESERVED on purpose: the tracked noise floor, the MCRA
 * min-tracking ring and its scene-change run length, the SPP a-priori-SNR
 * history and the gain smoothing history all carry on. A strength change is
 * not a restart, and discarding the noise estimate mid-stream is a worse
 * artefact than whatever was being tuned away. Use mmse_lsa_reset() when a
 * restart is what you actually want.
 *
 * `target` is taken VERBATIM -- this entry point performs no preset lookup and
 * no overlay composition. That is deliberate: a caller whose configuration is
 * a preset plus its own overrides (as both shipped pipelines are) must rebuild
 * the whole composition and pass the result, or the overrides are silently
 * reverted to the canonical preset values.
 *
 * Call between hops, serialised with mmse_lsa_process(); not thread-safe.
 * Returns 0 on success, -1 on NULL, an invalid target, or a geometry
 * mismatch. On -1 NOTHING is written.
 */
int mmse_lsa_reconfigure(MmseLsaDenoiser* self, const MmseLsaConfig* target);

/* Convenience wrapper for the STANDALONE case: compose the canonical config
 * for `mode` on this instance's grid and hand it to mmse_lsa_reconfigure().
 *
 * The content axis is orthogonal to strength, so an instance built through
 * mmse_lsa_apply_stationary() has that overlay RE-APPLIED here -- a strength
 * change must not silently turn a stationary instance into a hybrid.
 *
 * NOT for a caller that layers its own overrides on top of the preset: this
 * composes the canonical config only, and would revert them. Such a caller
 * should rebuild its own composition and call mmse_lsa_reconfigure() directly.
 *
 * Returns 0, or -1 on NULL, an out-of-enum mode, or a rejected target. */
int mmse_lsa_set_mode(MmseLsaDenoiser* self, MmseLsaNrMode mode);

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

/**
 * Aggregate debug/status snapshot — a convenience over the per-bin query API
 * above, for an integrator to poll (e.g. once per second) to tell whether the
 * denoiser is behaving on an embedded target. All fields are reductions over
 * the existing gain/SPP/noise-PSD arrays of the last processed frame; nothing
 * extra is tracked between frames, so there is zero cost unless this is
 * actually called. (No frame counter exists in MmseLsaDenoiser, so
 * frames_processed from the original ask is dropped rather than added as new
 * per-frame state.)
 */
typedef struct MmseLsaDebugStatus {
    int   initialized;      /* noise-floor init done (== mmse_lsa_is_initialized) */
    float mean_gain_db;     /* 20*log10(mean linear gain), dB, last frame          */
    float min_gain_db;      /* 20*log10(deepest per-bin linear gain), dB, last frame */
    float mean_spp;         /* mean speech-presence probability [0,1], last frame  */
    float noise_floor_db;   /* 10*log10(mean noise PSD), dB (power), last frame    */
} MmseLsaDebugStatus;

/**
 * Fill *out with an aggregate snapshot of the denoiser's current per-bin
 * state. Read-only / const — does not perturb any DSP state (no mutation,
 * no fast_math approximations; this diagnostics path uses standard logf/
 * log10f for precision and simplicity over speed). The n_freqs-long
 * reduction only runs when the caller actually invokes this function.
 */
void mmse_lsa_debug_status(const MmseLsaDenoiser* self, MmseLsaDebugStatus* out);

#ifdef __cplusplus
}
#endif

#endif /* MMSE_LSA_DENOISER_H */
