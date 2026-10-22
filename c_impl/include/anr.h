/* ANR frequency-domain API. Input/output: Complex[n_freqs] per hop. Caller owns windowing,
 * FFT/IFFT and overlap-add.
 */

#ifndef ANR_H
#define ANR_H

#include "anr_types.h"
#include "fft_wrapper.h"    /* Complex spectrum type. */
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handle. */
typedef struct AnrDenoiser AnrDenoiser;

/* Lifecycle and processing. */

/* Allocate a heap instance; returns NULL on invalid config or allocation failure. */
AnrDenoiser* anr_create(const AnrConfig* config);

/* Caller-owned instance and all noise-tracker/SPP state use one 16-byte-aligned block. Query
 * bytes once with anr_get_mem_size(config), then supply at least that size to anr_init(). Size
 * and carve order must match. Invalid config, alignment or capacity returns NULL (size query
 * returns 0).
 */
size_t anr_get_mem_size(const AnrConfig* config);
AnrDenoiser* anr_init(void* mem, size_t mem_size,
                                const AnrConfig* config);

/* Free a heap instance. Static instances retain caller-owned memory; destroy is a no-op. */
void anr_destroy(AnrDenoiser* self);

/* Process one Complex[n_freqs] spectrum; output has NR gain applied. Exact in-place aliasing
 * and disjoint buffers are supported; partial overlap is unsupported. Returns 0 on success, -1
 * for NULL input/output/handle.
 */
int anr_process(AnrDenoiser* self,
                     const Complex*   spectrum_in,
                     Complex*         spectrum_out);

/* Compute gain[n_freqs] without applying it. Optional extra_noise_psd[n_freqs] uses the input
 * power scale and augments only the SPP/SNR noise floor (N² + R²); the noise tracker follows
 * the input power independently. NULL extra_noise_psd selects ordinary NR. NULL gain_out skips
 * the copy; anr_get_gain() still exposes the result. Returns 0 on success, -1 for NULL
 * input/handle.
 */
int anr_process_gain(AnrDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out);

/** Reset all internal state (call when switching audio streams). */
void anr_reset(AnrDenoiser* self);

/* Replace tuning scalars verbatim; no preset lookup, overlay composition or allocation. Grid,
 * L and num_init_frames must match the instance, and target must pass anr_validate_config().
 * Noise, minimum-ring, SPP and gain state are preserved. Call between hops, serialized with
 * processing; not thread-safe. Returns 0, or -1 with no writes for NULL, invalid config or
 * geometry mismatch.
 */
int anr_reconfigure(AnrDenoiser* self, const AnrConfig* target);

/* Compose the canonical strength preset on the current grid, then reconfigure. Caller-specific
 * overlays require anr_reconfigure() instead.
 * Returns 0, or -1 for NULL, invalid mode or rejected config.
 */
int anr_set_mode(AnrDenoiser* self, AnrMode mode);

/* Read-only queries. */

/** hop_size from config (samples; for caller reference only). */
int anr_get_hop_size(const AnrDenoiser* self);

/** frame_size from config (samples; for caller reference only). */
int anr_get_frame_size(const AnrDenoiser* self);

/** Number of frequency bins (fft_size/2 + 1). */
int anr_get_n_freqs(const AnrDenoiser* self);

/* Frequency-domain core latency: 0 samples. Caller accounts for window/FFT/overlap-add
 * latency.
 */
int anr_get_latency(const AnrDenoiser* self);

/** True once the noise estimator has completed its init frames. */
bool anr_is_initialized(const AnrDenoiser* self);

/** Current Speech Presence Probability per bin [n_freqs]. */
const float* anr_get_spp(const AnrDenoiser* self, int* n_freqs);

/** Current noise PSD estimate (power units) [n_freqs]. */
const float* anr_get_noise_psd(const AnrDenoiser* self, int* n_freqs);

/** The frame speech gate as applied (see ANR_SPEECH_PROTECT_ANCHOR_Q);
 * tracks anr_reconfigure(). */
float anr_get_speech_protect_frame_threshold(const AnrDenoiser* self);

/* Most recent gain[n_freqs], linear [g_min, 1]. Valid after one processed frame; pointer is
 * borrowed until the next process call.
 */
const float* anr_get_gain(const AnrDenoiser* self, int* n_freqs);

/* Last-frame aggregate diagnostics. Computed on request from current gain/SPP/noise arrays; no
 * extra per-hop state.
 */
typedef struct AnrDebugStatus {
    int   initialized;      /* noise-floor init done (== anr_is_initialized) */
    float mean_gain_db;     /* 20*log10(mean linear gain), dB, last frame          */
    float min_gain_db;      /* 20*log10(deepest per-bin linear gain), dB, last frame */
    float mean_spp;         /* mean speech-presence probability [0,1], last frame  */
    float noise_floor_db;   /* 10*log10(mean noise PSD), dB (power), last frame    */
} AnrDebugStatus;

/* Fill *out without changing DSP state. NULL handle produces zero fields. Uses standard log
 * math; reduction runs only on request.
 */
void anr_debug_status(const AnrDenoiser* self, AnrDebugStatus* out);

#ifdef __cplusplus
}
#endif

#endif /* ANR_H */
