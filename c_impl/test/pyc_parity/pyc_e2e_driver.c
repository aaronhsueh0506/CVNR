/**
 * pyc_e2e_driver.c -- end-to-end C side of the Python<->C NR numeric parity tool
 * (python/tools/pyc_parity_nr.py): raw float32 samples in, raw float32 samples out, no 16-bit
 * quantisation. It repeats example/main.c steps 4-7 with the same framing (ceil framing,
 * zero-padded last frame, sqrt-periodic-Hann analysis and synthesis window, overlap-add), so the
 * result includes the C FFT/OLA path, which the gain-only driver deliberately excludes.
 *
 * Usage: pyc_e2e_driver <in.f32> <n_samples> <sample_rate> <fft_size> <strength> <out.f32>
 * The output holds min(n_samples, overlap-add length) floats.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "anr.h"
#include "anr_types.h"
#include "fft_wrapper.h"
#include "audio_window.h"

static int fail(const char* msg) {
    fprintf(stderr, "pyc_e2e_driver: %s\n", msg);
    return 1;
}

int main(int argc, char** argv) {
    if (argc != 7) return fail("usage: pyc_e2e_driver <in.f32> <n_samples> <sample_rate> <fft_size> <strength> <out.f32>");
    const int n_samples = atoi(argv[2]), sr = atoi(argv[3]), fft_size = atoi(argv[4]);
    const int mode = anr_nr_mode_from_name(argv[5]);
    if (n_samples <= 0 || sr <= 0 || fft_size <= 0) return fail("bad numeric argument");
    if (mode < 0) return fail("unknown strength (expected mild|moderate|balanced|aggressive)");

    AnrConfig cfg = anr_config_for_mode_grid(sr, fft_size, (AnrMode)mode);
    if (!anr_validate_config(&cfg)) return fail("config rejected by anr_validate_config");
    const int frame = cfg.frame_size, hop = cfg.hop_size, nf = fft_size / 2 + 1;
    const int n_frames = (n_samples <= frame) ? 1 : (n_samples - frame + hop - 1) / hop + 1;
    const int out_len = (n_frames - 1) * hop + frame;

    float* sig = (float*)malloc((size_t)n_samples * sizeof(float));
    float* ola = (float*)calloc((size_t)out_len, sizeof(float));
    float* win = (float*)malloc((size_t)frame * sizeof(float));
    float* fb = (float*)malloc((size_t)fft_size * sizeof(float));
    float* to = (float*)malloc((size_t)fft_size * sizeof(float));
    Complex* si = (Complex*)malloc((size_t)nf * sizeof(Complex));
    Complex* so = (Complex*)malloc((size_t)nf * sizeof(Complex));
    AnrDenoiser* dn = anr_create(&cfg);
    FftHandle* fft = fft_create(fft_size);
    int rc = 1;
    if (!sig || !ola || !win || !fb || !to || !si || !so || !dn || !fft) {
        fail("allocation failed");
        goto done;
    }
    FILE* fi = fopen(argv[1], "rb");
    if (!fi) {
        fail("cannot open input");
        goto done;
    }
    if (fread(sig, sizeof(float), (size_t)n_samples, fi) != (size_t)n_samples) {
        fclose(fi);
        fail("short input");
        goto done;
    }
    fclose(fi);
    ac_window_build(win, frame);
    for (int f = 0; f < n_frames; f++) {
        const int start = f * hop;
        for (int n = 0; n < frame; n++) {
            const int idx = start + n;
            fb[n] = (idx < n_samples ? sig[idx] : 0.0f) * win[n];
        }
        for (int n = frame; n < fft_size; n++) fb[n] = 0.0f;
        fft_forward(fft, fb, si);
        if (anr_process(dn, si, so) < 0) {
            fail("anr_process failed");
            goto done;
        }
        fft_inverse(fft, so, to);
        for (int n = 0; n < frame; n++) ola[start + n] += to[n] * win[n];
    }
    const int write_len = out_len < n_samples ? out_len : n_samples;
    FILE* fo = fopen(argv[6], "wb");
    if (!fo) {
        fail("cannot open output");
        goto done;
    }
    const size_t wrote = fwrite(ola, sizeof(float), (size_t)write_len, fo);
    if (fclose(fo) != 0 || wrote != (size_t)write_len) {
        fail("short write");
        goto done;
    }
    rc = 0;
done:
    free(sig);
    free(ola);
    free(win);
    free(fb);
    free(to);
    free(si);
    free(so);
    if (dn) anr_destroy(dn);
    if (fft) fft_destroy(fft);
    return rc;
}
