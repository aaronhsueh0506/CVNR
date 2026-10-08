/* After five seconds of digital silence, a stationary tone must reach
 * the same steady gain as a tone without leading silence. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "anr.h"
#include "anr_types.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

/* Mean gain of the 1 kHz bin over the last second of a `tone_s`-second tone
 * preceded by `silence_s` seconds of exact-zero spectra. */
static double tone_gain(const AnrConfig* cfg, int sr, double silence_s, double tone_s) {
    AnrDenoiser* d = anr_create(cfg);
    int nf, hop, fft, bin, n_sil, n_tone, last, h;
    Complex* spec; float* gain; double acc = 0.0;
    if (!d) return -1.0;
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d); fft = anr_get_frame_size(d);
    bin = (int)lrint(1000.0 * fft / sr);
    n_sil = (int)(silence_s * sr / hop); n_tone = (int)(tone_s * sr / hop); last = sr / hop;
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex)); gain = (float*)calloc((size_t)nf, sizeof(float));
    for (h = 0; h < n_sil; ++h) { memset(spec, 0, (size_t)nf * sizeof(Complex)); anr_process_gain(d, spec, NULL, gain); }
    for (h = 0; h < n_tone; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        spec[bin].r = 0.03f * 32768.0f * (float)(fft / 2);   /* -30 dBFS tone, int16-scale FFT */
        anr_process_gain(d, spec, NULL, gain);
        if (h >= n_tone - last) acc += gain[bin];
    }
    free(spec); free(gain); anr_destroy(d);
    return acc / last;
}

static void run_case(const char* label, AnrConfig cfg, int sr) {
    double control = tone_gain(&cfg, sr, 0.0, 10.0);
    double after = tone_gain(&cfg, sr, 5.0, 10.0);
    printf("%-40s control %.4f (%.1f dB)  after 5 s silence %.4f (%.1f dB)\n", label,
           control, 20.0 * log10(control + 1e-12), after, 20.0 * log10(after + 1e-12));
    CHECK(control >= 0.0 && after >= 0.0, "%s: create failed", label);
    /* Above the speech guard, steady gain must stay within 4x the preset floor. */
    double floor_gain = pow(10.0, cfg.g_min_db / 20.0);
    CHECK(control < 4.0 * floor_gain, "%s: stationary tone is not sufficiently suppressed (control %.3f, floor %.3f)", label, control, floor_gain);
    CHECK(after < 4.0 * floor_gain, "%s: tone after digital silence stays unsuppressed (%.3f, floor %.3f)", label, after, floor_gain);
    CHECK(fabs(after - control) < 0.02, "%s: silence-first gain %.3f != control %.3f", label, after, control);
}

int main(void) {
    static const int rates[2] = { 16000, 48000 };
    int r;
    for (r = 0; r < 2; ++r) {
        char label[64];
        AnrConfig def = anr_default_config(rates[r]);
        AnrConfig bb = def; bb.broadband_threshold = 0.8f;
        snprintf(label, sizeof(label), "%d Hz library default", rates[r]);
        run_case(label, def, rates[r]);
        snprintf(label, sizeof(label), "%d Hz broadband gate 0.8", rates[r]);
        run_case(label, bb, rates[r]);
    }
    if (g_fail) { printf(">>> FAIL\n"); return 1; }
    printf(">>> PASS\n");
    return 0;
}
