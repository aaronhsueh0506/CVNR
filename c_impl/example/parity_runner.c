/* Offline gain runner: reads per-frame complex spectra from a binary file, computes each
 * frame's per-bin gain with anr_process_gain() (the gain is not applied) and writes the gains.
 *
 * Input and output layouts: see nrp2_io.h.
 *
 * Usage: parity_runner <in_spectra.bin> <out_c_gains.bin> [full] [<level>]
 *   The optional mode must be 'full'. <level> is the number 0 mild, 1 moderate, 2 balanced or
 *   3 aggressive and defaults to balanced.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "anr.h"
#include "anr_types.h"
#include "cli_level.h"
#include "fft_wrapper.h"
#include "nrp2_io.h"

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <in_spectra.bin> <out_c_gains.bin> "
                        "[full] [0|1|2|3]\n", argv[0]);
        return 1;
    }
    if (argc >= 4 && strcmp(argv[3], "full") != 0) {
        fprintf(stderr, "Error: unsupported mode '%s' (only 'full')\n", argv[3]);
        return 1;
    }
    AnrLevel nr_level = ANR_LEVEL_BALANCED;
    if (argc >= 5) {
        if (anr_cli_parse_level(argv[4], &nr_level) != 0) {
            fprintf(stderr, "Error: unknown NR level '%s' (0 mild, 1 moderate, 2 balanced, 3 aggressive)\n", argv[4]);
            return 2;
        }
    }

    FILE* fin = fopen(argv[1], "rb");
    if (!fin) {
        fprintf(stderr, "Error: cannot open input %s\n", argv[1]);
        return 1;
    }

    Nrp2Header header;
    Nrp2Status status = nrp2_read_header(fin, 1, &header);
    if (status == NRP2_SHORT_HEADER || status == NRP2_SHORT_RATE) {
        fprintf(stderr, status == NRP2_SHORT_RATE ? "Error: short NRP2 header\n"
                                                  : "Error: short header\n");
        fclose(fin);
        return 1;
    }
    if (status == NRP2_BAD_MAGIC) {
        fprintf(stderr, "Error: bad magic 0x%08x (expected 0x%08x or 0x%08x)\n",
                (unsigned)header.magic, (unsigned)NRP2_MAGIC, (unsigned)NRP2_MAGIC_V1);
        fclose(fin);
        return 1;
    }
    int n_frames = header.n_frames;
    int n_freqs  = header.n_freqs;
    int sample_rate = header.sample_rate;
    if (status == NRP2_BAD_VALUES) {
        fprintf(stderr, "Error: bad header frames=%d freqs=%d sr=%d\n",
                n_frames, n_freqs, sample_rate);
        fclose(fin);
        return 1;
    }

    int fft_size = (n_freqs - 1) * 2;

    /* The sample rate selects the retimed EMA and frame-count parameters. */
    AnrConfig config = anr_config_for_level_grid(
        sample_rate, fft_size, nr_level);

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
    const float* gain = NULL;   /* borrowed from the denoiser */
    float*   all_gains = (float*)malloc((size_t)n_frames * n_freqs * sizeof(float));
    if (!spec_in || !re || !im || !all_gains) {
        fprintf(stderr, "Error: malloc failed\n");
        free(spec_in); free(re); free(im); free(all_gains);
        anr_destroy(denoiser);
        fclose(fin);
        return 1;
    }

    /* Drive frame-by-frame: read X_re/X_im, compute gain (not applied). */
    for (int f = 0; f < n_frames; f++) {
        if (nrp2_read_frame(fin, n_freqs, re, im, spec_in) != 0) {
            fprintf(stderr, "Error: short spectra at frame %d\n", f);
            break;
        }
        gain = anr_process_gain(denoiser, spec_in);
        if (!gain) {
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
        free(spec_in); free(re); free(im); free(all_gains);
        anr_destroy(denoiser);
        return 1;
    }
    nrp2_write_gains(fout, n_frames, n_freqs, all_gains);
    fclose(fout);

    printf("[parity_runner] frames=%d n_freqs=%d sr=%d fft_size=%d -> %s\n",
           n_frames, n_freqs, sample_rate, fft_size, argv[2]);

    free(spec_in); free(re); free(im); free(all_gains);
    anr_destroy(denoiser);
    return 0;
}
