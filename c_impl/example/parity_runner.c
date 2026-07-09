/**
 * parity_runner.c — C side of the Python<->C NR parity harness.
 *
 * Reads the per-frame complex input spectra dumped by tools/parity_nr.py,
 * drives the C lib mmse_lsa_process_gain() frame-by-frame (computing the per-bin
 * gain WITHOUT applying it), and writes the C gains to a file. Because both
 * Python and C consume byte-identical input spectra, any gain delta is purely
 * the ported gain / SPP / MCRA arithmetic — FFT differences are excluded.
 *
 * The denoiser is created with the Python V3-2 standalone config (mmse_lsa
 * default/balanced) and its framing forced to fft_size derived from n_freqs
 * (n_freqs = fft_size/2 + 1), matching tools/parity_nr.py (512/256/512).
 *
 * Input file layout (little-endian, from parity_nr.py 'dump'):
 *   [magic=0x4e525031][n_frames][n_freqs]                (3 x int32)
 *   per frame f:  X_re[n_freqs] (float32), X_im[n_freqs] (float32)
 *   per frame f:  G_py[n_freqs] (float32)                (ignored here)
 *
 * Output file layout (this program):
 *   [n_frames][n_freqs]                                  (2 x int32)
 *   per frame f:  G_c[n_freqs] (float32)
 *
 * Usage: parity_runner <in_spectra.bin> <out_c_gains.bin> [full|stationary]
 *   The optional mode selects the C config (default full = balanced V3-2); pass
 *   'stationary' to mirror parity_nr.py dump --mode stationary.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "fft_wrapper.h"

#define PARITY_MAGIC 0x4E525031  /* 'NRP1' */

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <in_spectra.bin> <out_c_gains.bin> "
                        "[full|stationary] [mild|moderate|balanced|aggressive]\n", argv[0]);
        return 1;
    }
    int stationary = (argc >= 4 && strcmp(argv[3], "stationary") == 0);
    MmseLsaNrMode nr_mode = MMSE_LSA_NR_BALANCED;
    if (argc >= 5) {
        if (strcmp(argv[4], "mild") == 0)            nr_mode = MMSE_LSA_NR_MILD;
        else if (strcmp(argv[4], "moderate") == 0)   nr_mode = MMSE_LSA_NR_MODERATE;
        else if (strcmp(argv[4], "aggressive") == 0) nr_mode = MMSE_LSA_NR_AGGRESSIVE;
        else                                         nr_mode = MMSE_LSA_NR_BALANCED;
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
    if (header[0] != PARITY_MAGIC) {
        fprintf(stderr, "Error: bad magic 0x%08x (expected 0x%08x)\n",
                (unsigned)header[0], (unsigned)PARITY_MAGIC);
        fclose(fin);
        return 1;
    }
    int n_frames = header[1];
    int n_freqs  = header[2];
    if (n_frames <= 0 || n_freqs <= 1) {
        fprintf(stderr, "Error: bad dims frames=%d freqs=%d\n", n_frames, n_freqs);
        fclose(fin);
        return 1;
    }

    /* n_freqs = fft_size/2 + 1  ->  fft_size = (n_freqs - 1) * 2 */
    int fft_size = (n_freqs - 1) * 2;

    /* Build the production V3-2 config, framing forced to match Python
     * (512/256/512 for n_freqs=257). Sample rate is irrelevant to the gain math
     * here (spectra are supplied directly); pass 16000 for the default knobs.
     * strength = depth preset; stationary → overlay the content preset on top. */
    MmseLsaConfig config = mmse_lsa_config_for_mode(16000, nr_mode);
    if (stationary) mmse_lsa_apply_stationary(&config);
    config.fft_size   = fft_size;
    config.frame_size = fft_size;   /* 512 */
    config.hop_size   = fft_size / 2;

    MmseLsaDenoiser* denoiser = mmse_lsa_create(&config);
    if (!denoiser) {
        fprintf(stderr, "Error: mmse_lsa_create failed\n");
        fclose(fin);
        return 1;
    }
    int nf_check = mmse_lsa_get_n_freqs(denoiser);
    if (nf_check != n_freqs) {
        fprintf(stderr, "Error: denoiser n_freqs=%d != file n_freqs=%d\n",
                nf_check, n_freqs);
        mmse_lsa_destroy(denoiser);
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
        mmse_lsa_destroy(denoiser);
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
        if (mmse_lsa_process_gain(denoiser, spec_in, NULL, gain) < 0) {
            fprintf(stderr, "Error: mmse_lsa_process_gain failed at frame %d\n", f);
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
        mmse_lsa_destroy(denoiser);
        return 1;
    }
    int32_t out_header[2] = { n_frames, n_freqs };
    fwrite(out_header, sizeof(int32_t), 2, fout);
    fwrite(all_gains, sizeof(float), (size_t)n_frames * n_freqs, fout);
    fclose(fout);

    printf("[parity_runner] frames=%d n_freqs=%d fft_size=%d -> %s\n",
           n_frames, n_freqs, fft_size, argv[2]);

    free(spec_in); free(re); free(im); free(gain); free(all_gains);
    mmse_lsa_destroy(denoiser);
    return 0;
}
