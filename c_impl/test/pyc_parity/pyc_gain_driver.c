/**
 * pyc_gain_driver.c -- C side of the Python<->C NR numeric parity tool (python/tools/pyc_parity_nr.py).
 *
 * Same job as example/parity_runner.c (read NRP2 spectra, drive anr_process_gain() frame by frame,
 * write the per-bin gains) plus the two things that runner cannot do:
 *   - config overrides given as key=value, so that both sides can run with a non-default feature
 *     (currently makeup_gain), and
 *   - strict argument handling: an unknown strength name or a config that fails
 *     anr_validate_config() is an error, never a silent fallback to balanced.
 * With no overrides the output is byte-identical to parity_runner's; pyc_parity_nr.sh checks this
 * on every run.
 *
 * Usage: pyc_gain_driver <in.nrp2> <out.gains> <mild|moderate|balanced|aggressive> [makeup_gain=0|1]
 * Input/output layouts: see example/parity_runner.c.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "anr.h"
#include "anr_types.h"

#define PARITY_MAGIC 0x4E525032 /* 'NRP2' */

static int fail(const char* msg) {
    fprintf(stderr, "pyc_gain_driver: %s\n", msg);
    return 1;
}

int main(int argc, char** argv) {
    if (argc < 4) return fail("usage: pyc_gain_driver <in.nrp2> <out.gains> <strength> [makeup_gain=0|1]");
    int mode = anr_nr_mode_from_name(argv[3]);
    if (mode < 0) return fail("unknown strength (expected mild|moderate|balanced|aggressive)");

    FILE* fin = fopen(argv[1], "rb");
    if (!fin) return fail("cannot open input");
    int32_t h[4];
    if (fread(h, sizeof(int32_t), 4, fin) != 4 || h[0] != PARITY_MAGIC) {
        fclose(fin);
        return fail("bad NRP2 header");
    }
    const int n_frames = h[1], n_freqs = h[2], sample_rate = h[3];
    if (n_frames <= 0 || n_freqs <= 1 || sample_rate <= 0) {
        fclose(fin);
        return fail("bad NRP2 header values");
    }
    const int fft_size = (n_freqs - 1) * 2;

    AnrConfig config = anr_config_for_mode_grid(sample_rate, fft_size, (AnrMode)mode);
    for (int i = 4; i < argc; i++) {
        if (strcmp(argv[i], "makeup_gain=1") == 0) config.makeup_gain = true;
        else if (strcmp(argv[i], "makeup_gain=0") == 0) config.makeup_gain = false;
        else {
            fclose(fin);
            return fail("unknown override (supported: makeup_gain=0|1)");
        }
    }
    if (!anr_validate_config(&config)) {
        fclose(fin);
        return fail("config rejected by anr_validate_config");
    }
    AnrDenoiser* dn = anr_create(&config);
    if (!dn) {
        fclose(fin);
        return fail("anr_create failed");
    }
    if (anr_get_n_freqs(dn) != n_freqs) {
        anr_destroy(dn);
        fclose(fin);
        return fail("denoiser n_freqs differs from the file");
    }

    Complex* spec = (Complex*)malloc((size_t)n_freqs * sizeof(Complex));
    float* re = (float*)malloc((size_t)n_freqs * sizeof(float));
    float* im = (float*)malloc((size_t)n_freqs * sizeof(float));
    float* all = (float*)malloc((size_t)n_frames * (size_t)n_freqs * sizeof(float));
    int rc = 1;
    if (!spec || !re || !im || !all) {
        fail("malloc failed");
        goto done;
    }
    for (int f = 0; f < n_frames; f++) {
        if (fread(re, sizeof(float), (size_t)n_freqs, fin) != (size_t)n_freqs ||
            fread(im, sizeof(float), (size_t)n_freqs, fin) != (size_t)n_freqs) {
            fail("short spectra");
            goto done;
        }
        for (int k = 0; k < n_freqs; k++) {
            spec[k].r = re[k];
            spec[k].i = im[k];
        }
        if (anr_process_gain(dn, spec, NULL, all + (size_t)f * (size_t)n_freqs) < 0) {
            fail("anr_process_gain failed");
            goto done;
        }
    }
    FILE* fout = fopen(argv[2], "wb");
    if (!fout) {
        fail("cannot open output");
        goto done;
    }
    const int32_t oh[2] = {n_frames, n_freqs};
    if (fwrite(oh, sizeof(int32_t), 2, fout) != 2 ||
        fwrite(all, sizeof(float), (size_t)n_frames * (size_t)n_freqs, fout) !=
            (size_t)n_frames * (size_t)n_freqs) {
        fclose(fout);
        fail("short write");
        goto done;
    }
    if (fclose(fout) != 0) {
        fail("close failed");
        goto done;
    }
    rc = 0;
done:
    free(spec);
    free(re);
    free(im);
    free(all);
    anr_destroy(dn);
    fclose(fin);
    return rc;
}
