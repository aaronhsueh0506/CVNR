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

/* Allocate a heap instance; returns NULL on invalid config or allocation failure. */
AnrDenoiser* anr_create(const AnrConfig* config);

/* Static-memory path: one 16-byte-aligned block of at least anr_get_mem_size(config) bytes
 * holds the instance. Invalid config, alignment or capacity gives NULL (size query: 0). */
size_t anr_get_mem_size(const AnrConfig* config);
AnrDenoiser* anr_init(void* mem, size_t mem_size,
                                const AnrConfig* config);

/* Free a heap instance. Static instances retain caller-owned memory; destroy is a no-op. */
void anr_destroy(AnrDenoiser* self);

/* Applies the gain to spectrum_in[n_freqs]; in-place or disjoint buffers only. Returns 0, or -1
 * for NULL arguments. */
int anr_process(AnrDenoiser* self,
                     const Complex*   spectrum_in,
                     Complex*         spectrum_out);

/* Computes gain[n_freqs] without applying it. Optional extra_noise_psd[n_freqs] (input power
 * scale) raises only the SPP/SNR noise floor; the tracker still follows the input power. NULL
 * gain_out skips the copy (see anr_get_gain). Returns 0, or -1 for NULL input/handle. */
int anr_process_gain(AnrDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out);

/* Clears all internal state (use when switching audio streams). */
void anr_reset(AnrDenoiser* self);

/* Replaces the tuning scalars with target; noise, minimum-ring, SPP and gain state are kept.
 * Grid, L and num_init_frames must match the instance and target must pass
 * anr_validate_config(). Call between hops, not concurrently with processing. Returns 0, or -1
 * with nothing written. */
int anr_reconfigure(AnrDenoiser* self, const AnrConfig* target);

/* Applies the strength preset for the current grid through anr_reconfigure(). Returns 0, or -1
 * for NULL, invalid mode or rejected config. */
int anr_set_mode(AnrDenoiser* self, AnrMode mode);

/* Read-only queries. Sizes are in samples; n_freqs = fft_size/2 + 1. */
int anr_get_hop_size(const AnrDenoiser* self);
int anr_get_frame_size(const AnrDenoiser* self);
int anr_get_n_freqs(const AnrDenoiser* self);

/* Core latency in samples (0); the caller accounts for window/FFT/overlap-add. */
int anr_get_latency(const AnrDenoiser* self);

/* True once the noise estimator has completed its init frames. */
bool anr_is_initialized(const AnrDenoiser* self);

/* Speech presence probability per bin [n_freqs]. */
const float* anr_get_spp(const AnrDenoiser* self, int* n_freqs);

/* Noise PSD estimate (power units) [n_freqs]. */
const float* anr_get_noise_psd(const AnrDenoiser* self, int* n_freqs);

/* Frame speech gate in effect (ANR_SPEECH_PROTECT_ANCHOR_Q); follows anr_reconfigure(). */
float anr_get_speech_protect_frame_threshold(const AnrDenoiser* self);

/* Latest gain[n_freqs], linear in [g_min, 1]; valid after one processed frame and borrowed
 * until the next process call. */
const float* anr_get_gain(const AnrDenoiser* self, int* n_freqs);

/* Last-frame aggregate diagnostics, computed on request. */
typedef struct AnrDebugStatus {
    int   initialized;      /* noise-floor init done */
    float mean_gain_db;     /* dB, last frame */
    float min_gain_db;      /* dB, deepest bin */
    float mean_spp;         /* [0,1] */
    float noise_floor_db;   /* dB (power) */
} AnrDebugStatus;

/* Fills *out without changing DSP state; a NULL handle yields zero fields. */
void anr_debug_status(const AnrDenoiser* self, AnrDebugStatus* out);

#ifdef __cplusplus
}
#endif

#endif /* ANR_H */
