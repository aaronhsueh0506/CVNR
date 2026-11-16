/* nrp2_io.h -- NRP2 spectra input and gain output shared by the offline gain runners.
 *
 * Input (little-endian): int32 magic 'NRP2' (0x4e525032; 'NRP1' = implicit 16 kHz), n_frames,
 * n_freqs and, for 'NRP2', sample_rate; then per frame X_re[n_freqs], X_im[n_freqs] (float32).
 * Trailing data is ignored. fft_size = (n_freqs - 1) * 2.
 * Output: int32 n_frames, n_freqs; then per frame gain[n_freqs] (float32).
 */
#ifndef ANR_EXAMPLE_NRP2_IO_H
#define ANR_EXAMPLE_NRP2_IO_H

#include <stdint.h>
#include <stdio.h>

#include "anr.h"

#define NRP2_MAGIC_V1 0x4E525031  /* 'NRP1': implicit 16 kHz */
#define NRP2_MAGIC    0x4E525032  /* 'NRP2': carries the signal grid rate */

typedef struct {
    int32_t magic;
    int n_frames;
    int n_freqs;
    int sample_rate;
} Nrp2Header;

typedef enum {
    NRP2_OK = 0,
    NRP2_SHORT_HEADER,
    NRP2_SHORT_RATE,   /* 'NRP2' header ends before sample_rate */
    NRP2_BAD_MAGIC,    /* magic not accepted; h->magic holds what was read */
    NRP2_BAD_VALUES    /* n_frames <= 0, n_freqs <= 1, sample_rate <= 0 or a gain table beyond size_t */
} Nrp2Status;

/* Non-zero when n_frames * n_freqs floats (the gain table) fit in size_max bytes; no product wraps. */
static inline int nrp2_gains_fit(int n_frames, int n_freqs, size_t size_max) {
    if (n_frames <= 0 || n_freqs <= 0) return 0;
    if ((size_t)n_freqs > size_max / sizeof(float)) return 0;
    return (size_t)n_frames <= size_max / ((size_t)n_freqs * sizeof(float));
}

/* Reads the header; 'NRP1' is accepted only when accept_v1 is non-zero. */
static inline Nrp2Status nrp2_read_header(FILE* f, int accept_v1, Nrp2Header* h) {
    int32_t v[3];
    if (fread(v, sizeof(int32_t), 3, f) != 3) return NRP2_SHORT_HEADER;
    h->magic = v[0];
    if (v[0] != NRP2_MAGIC && !(accept_v1 && v[0] == NRP2_MAGIC_V1)) return NRP2_BAD_MAGIC;
    h->n_frames = v[1];
    h->n_freqs = v[2];
    h->sample_rate = 16000;
    if (v[0] == NRP2_MAGIC) {
        int32_t sample_rate;
        if (fread(&sample_rate, sizeof(int32_t), 1, f) != 1) return NRP2_SHORT_RATE;
        h->sample_rate = sample_rate;
    }
    if (h->n_frames <= 0 || h->n_freqs <= 1 || h->sample_rate <= 0) return NRP2_BAD_VALUES;
    if (!nrp2_gains_fit(h->n_frames, h->n_freqs, SIZE_MAX)) return NRP2_BAD_VALUES;
    return NRP2_OK;
}

/* Reads one frame into spec[n_freqs] through caller scratch re/im[n_freqs]; 0, or -1 when short. */
static inline int nrp2_read_frame(FILE* f, int n_freqs, float* re, float* im, Complex* spec) {
    if (fread(re, sizeof(float), (size_t)n_freqs, f) != (size_t)n_freqs ||
        fread(im, sizeof(float), (size_t)n_freqs, f) != (size_t)n_freqs)
        return -1;
    for (int k = 0; k < n_freqs; k++) {
        spec[k].r = re[k];
        spec[k].i = im[k];
    }
    return 0;
}

/* Writes the gain file body (header and all frames); 0, or -1 on a short write. */
static inline int nrp2_write_gains(FILE* f, int n_frames, int n_freqs, const float* gains) {
    const int32_t header[2] = {n_frames, n_freqs};
    const size_t count = (size_t)n_frames * (size_t)n_freqs;
    if (fwrite(header, sizeof(int32_t), 2, f) != 2) return -1;
    return fwrite(gains, sizeof(float), count, f) == count ? 0 : -1;
}

#endif
