/**
 * pyc_gain_driver.c -- C side of the Python<->C NR numeric parity tool (python/tools/pyc_parity_nr.py).
 *
 * Same job as example/parity_runner.c (read NRP2 spectra, drive anr_process_gain() frame by frame,
 * write the per-bin gains) plus the two things that runner cannot do:
 *   - config overrides given as key=value, so that both sides can run with a non-default feature
 *     (currently makeup_gain), and
 *   - strict argument handling: an unknown level number or a config that fails
 *     anr_validate_config() is an error, never a silent fallback to balanced.
 * With no overrides the output is byte-identical to parity_runner's; pyc_parity_nr.sh checks this
 * on every run.
 *
 * Usage: pyc_gain_driver <in.nrp2> <out.gains> <0|1|2|3> [makeup_gain=0|1]
 *   The level is the number 0 mild, 1 moderate, 2 balanced or 3 aggressive.
 * Input/output layouts: see example/nrp2_io.h.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "anr.h"
#include "anr_types.h"
#include "cli_level.h"
#include "nrp2_io.h"

static int fail(const char* msg) {
    fprintf(stderr, "pyc_gain_driver: %s\n", msg);
    return 1;
}

int main(int argc, char** argv) {
    if (argc < 4) return fail("usage: pyc_gain_driver <in.nrp2> <out.gains> <level> [makeup_gain=0|1]");
    AnrLevel level;
    if (anr_cli_parse_level(argv[3], &level) != 0) return fail("unknown level (expected 0 mild, 1 moderate, 2 balanced, 3 aggressive)");

    FILE* fin = fopen(argv[1], "rb");
    if (!fin) return fail("cannot open input");
    Nrp2Header h;
    Nrp2Status status = nrp2_read_header(fin, 0, &h);
    if (status == NRP2_SHORT_HEADER || status == NRP2_SHORT_RATE || status == NRP2_BAD_MAGIC) {
        fclose(fin);
        return fail("bad NRP2 header");
    }
    if (status == NRP2_BAD_VALUES) {
        fclose(fin);
        return fail("bad NRP2 header values");
    }
    const int n_frames = h.n_frames, n_freqs = h.n_freqs, sample_rate = h.sample_rate;
    const int fft_size = (n_freqs - 1) * 2;

    AnrConfig config = anr_config_for_level_grid(sample_rate, fft_size, (AnrLevel)level);
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
        if (nrp2_read_frame(fin, n_freqs, re, im, spec) != 0) {
            fail("short spectra");
            goto done;
        }
        const float* gain = anr_process_gain(dn, spec);
        if (!gain) {
            fail("anr_process_gain failed");
            goto done;
        }
        memcpy(all + (size_t)f * (size_t)n_freqs, gain, (size_t)n_freqs * sizeof(float));
    }
    FILE* fout = fopen(argv[2], "wb");
    if (!fout) {
        fail("cannot open output");
        goto done;
    }
    if (nrp2_write_gains(fout, n_frames, n_freqs, all) != 0) {
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
