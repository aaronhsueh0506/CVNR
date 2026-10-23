/* Offline gain runner: reads per-frame complex spectra from a binary file, computes each
 * frame's per-bin gain with anr_process_gain() (the gain is not applied) and writes the gains.
 *
 * Input (little-endian): int32 magic 'NRP2' (0x4e525032; 'NRP1' = implicit 16 kHz), n_frames,
 * n_freqs and, for 'NRP2', sample_rate; then per frame X_re[n_freqs], X_im[n_freqs] (float32).
 * Trailing data is ignored. fft_size = (n_freqs - 1) * 2.
 * Output: int32 n_frames, n_freqs; then per frame gain[n_freqs] (float32).
 *
 * Usage: parity_runner <in_spectra.bin> <out_c_gains.bin> [full] [<strength>]
 *   The optional mode must be 'full'. <strength> is 0|1|2|3 or
 *   mild|moderate|balanced|aggressive and defaults to balanced.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "anr.h"
#include "anr_types.h"
#include "fft_wrapper.h"

#define PARITY_MAGIC_V1 0x4E525031  /* 'NRP1': implicit 16 kHz */
#define PARITY_MAGIC    0x4E525032  /* 'NRP2': carries the signal grid rate */

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <in_spectra.bin> <out_c_gains.bin> "
                        "[full] [0|1|2|3|mild|moderate|balanced|aggressive]\n", argv[0]);
        return 1;
    }
    if (argc >= 4 && strcmp(argv[3], "full") != 0) {
        fprintf(stderr, "Error: unsupported mode '%s' (only 'full')\n", argv[3]);
        return 1;
    }
    AnrMode nr_mode = ANR_MODE_BALANCED;
    if (argc >= 5) {
        /* Name or digit 0..3; an unrecognised value keeps the balanced default. */
        int m = anr_nr_mode_from_name(argv[4]);
        nr_mode = m >= 0 ? (AnrMode)m : ANR_MODE_BALANCED;
    }

    FILE* fin = fopen(argv[1], "rb");
    if (!fin) {
        fprintf(stderr, "Error: cannot open input %s\n", argv[1]);
        return 1;
    }

    int32_t header[3];
    if (fread(header, sizeof(int32_t), 3, fin) != 3) {
        fprintf(stderr, "Error: short header\n");
        fclose(fin);
        return 1;
    }
    if (header[0] != PARITY_MAGIC && header[0] != PARITY_MAGIC_V1) {
        fprintf(stderr, "Error: bad magic 0x%08x (expected 0x%08x or 0x%08x)\n",
                (unsigned)header[0], (unsigned)PARITY_MAGIC,
                (unsigned)PARITY_MAGIC_V1);
        fclose(fin);
        return 1;
    }
    int n_frames = header[1];
    int n_freqs  = header[2];
    int sample_rate = 16000;
    if (header[0] == PARITY_MAGIC &&
        fread(&sample_rate, sizeof(int32_t), 1, fin) != 1) {
        fprintf(stderr, "Error: short NRP2 header\n");
        fclose(fin);
        return 1;
    }
    if (n_frames <= 0 || n_freqs <= 1 || sample_rate <= 0) {
        fprintf(stderr, "Error: bad header frames=%d freqs=%d sr=%d\n",
                n_frames, n_freqs, sample_rate);
        fclose(fin);
        return 1;
    }

    int fft_size = (n_freqs - 1) * 2;

    /* The sample rate selects the retimed EMA and frame-count parameters. */
    AnrConfig config = anr_config_for_mode_grid(
        sample_rate, fft_size, nr_mode);

    AnrDenoiser* denoiser = anr_create(&config);
    if (!denoiser) {
        fprintf(stderr, "Error: anr_create failed\n");
        fclose(fin);
        return 1;
    }
    int nf_check = anr_get_n_freqs(denoiser);
    if (nf_check != n_freqs) {
        fprintf(stderr, "Error: denoiser n_freqs=%d != file n_freqs=%d\n",
                nf_check, n_freqs);
        anr_destroy(denoiser);
        fclose(fin);
        return 1;
    }

    Complex* spec_in = (Complex*)malloc(n_freqs * sizeof(Complex));
    float*   re      = (float*)malloc(n_freqs * sizeof(float));
    float*   im      = (float*)malloc(n_freqs * sizeof(float));
    float*   gain    = (float*)malloc(n_freqs * sizeof(float));
    float*   all_gains = (float*)malloc((size_t)n_frames * n_freqs * sizeof(float));
    if (!spec_in || !re || !im || !gain || !all_gains) {
        fprintf(stderr, "Error: malloc failed\n");
        free(spec_in); free(re); free(im); free(gain); free(all_gains);
        anr_destroy(denoiser);
        fclose(fin);
        return 1;
    }

    /* Drive frame-by-frame: read X_re/X_im, compute gain (not applied). */
    for (int f = 0; f < n_frames; f++) {
        if (fread(re, sizeof(float), n_freqs, fin) != (size_t)n_freqs ||
            fread(im, sizeof(float), n_freqs, fin) != (size_t)n_freqs) {
            fprintf(stderr, "Error: short spectra at frame %d\n", f);
            break;
        }
        for (int k = 0; k < n_freqs; k++) {
            spec_in[k].r = re[k];
            spec_in[k].i = im[k];
        }
        if (anr_process_gain(denoiser, spec_in, NULL, gain) < 0) {
            fprintf(stderr, "Error: anr_process_gain failed at frame %d\n", f);
            break;
        }
        memcpy(all_gains + (size_t)f * n_freqs, gain, n_freqs * sizeof(float));
    }
    fclose(fin);

    /* Write C gains. */
    FILE* fout = fopen(argv[2], "wb");
    if (!fout) {
        fprintf(stderr, "Error: cannot open output %s\n", argv[2]);
        free(spec_in); free(re); free(im); free(gain); free(all_gains);
        anr_destroy(denoiser);
        return 1;
    }
    int32_t out_header[2] = { n_frames, n_freqs };
    fwrite(out_header, sizeof(int32_t), 2, fout);
    fwrite(all_gains, sizeof(float), (size_t)n_frames * n_freqs, fout);
    fclose(fout);

    printf("[parity_runner] frames=%d n_freqs=%d sr=%d fft_size=%d -> %s\n",
           n_frames, n_freqs, sample_rate, fft_size, argv[2]);

    free(spec_in); free(re); free(im); free(gain); free(all_gains);
    anr_destroy(denoiser);
    return 0;
}
