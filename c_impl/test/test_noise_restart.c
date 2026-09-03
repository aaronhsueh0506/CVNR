/* The MCRA noise tracker must recover after digital silence (mirror of
 * tests/test_noise_tracker_restart.py on the C port).
 *
 * A bin whose noise estimate has decayed below MCRA_NOISE_PSD_INERT (a few
 * seconds of exact-zero input) used to be stuck for good: the 1e-10f
 * epsilons hide such a tiny N, so when a signal returns the posterior
 * saturates at exactly 1.0f, tilde_alpha_d becomes exactly 1.0f and the
 * update is a fixed point -- the bin's gain stays near unity instead of
 * falling to the floor. mcra_update()'s dead-bin restart re-seeds such bins.
 *
 * Drive mmse_lsa_process_gain() with 5 s of all-zero spectra followed by
 * 10 s of a stationary single-bin tone, for the library default config and
 * for the shipped presets at 16 kHz and 48 kHz, and require the tone bin's
 * gain over the last second to match the same tone without leading silence.
 * With the restart removed the silence-first gain sits at ~0.93 (-0.6 dB)
 * while the control reaches ~0.05 (-26 dB). Standalone runner, exit != 0 on
 * any failure. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

/* Mean gain of the 1 kHz bin over the last second of a `tone_s`-second tone
 * preceded by `silence_s` seconds of exact-zero spectra. */
static double tone_gain(const MmseLsaConfig* cfg, int sr, double silence_s, double tone_s) {
    MmseLsaDenoiser* d = mmse_lsa_create(cfg);
    int nf, hop, fft, bin, n_sil, n_tone, last, h;
    Complex* spec; float* gain; double acc = 0.0;
    if (!d) return -1.0;
    nf = mmse_lsa_get_n_freqs(d); hop = mmse_lsa_get_hop_size(d); fft = mmse_lsa_get_frame_size(d);
    bin = (int)lrint(1000.0 * fft / sr);
    n_sil = (int)(silence_s * sr / hop); n_tone = (int)(tone_s * sr / hop); last = sr / hop;
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex)); gain = (float*)calloc((size_t)nf, sizeof(float));
    for (h = 0; h < n_sil; ++h) { memset(spec, 0, (size_t)nf * sizeof(Complex)); mmse_lsa_process_gain(d, spec, NULL, gain); }
    for (h = 0; h < n_tone; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        spec[bin].r = 0.03f * 32768.0f * (float)(fft / 2);   /* -30 dBFS tone, int16-scale FFT */
        mmse_lsa_process_gain(d, spec, NULL, gain);
        if (h >= n_tone - last) acc += gain[bin];
    }
    free(spec); free(gain); mmse_lsa_destroy(d);
    return acc / last;
}

static void run_case(const char* label, MmseLsaConfig cfg, int sr) {
    double control = tone_gain(&cfg, sr, 0.0, 10.0);
    double after = tone_gain(&cfg, sr, 5.0, 10.0);
    printf("%-40s control %.4f (%.1f dB)  after 5 s silence %.4f (%.1f dB)\n", label,
           control, 20.0 * log10(control + 1e-12), after, 20.0 * log10(after + 1e-12));
    CHECK(control >= 0.0 && after >= 0.0, "%s: create failed", label);
    CHECK(control < 0.1, "%s: a stationary tone must sit at the floor (control %.3f)", label, control);
    CHECK(after < 0.1, "%s: tone after digital silence stays unsuppressed (%.3f)", label, after);
    CHECK(fabs(after - control) < 0.02, "%s: silence-first gain %.3f != control %.3f", label, after, control);
}

int main(void) {
    static const int rates[2] = { 16000, 48000 };
    int r;
    for (r = 0; r < 2; ++r) {
        char label[64];
        MmseLsaConfig def = mmse_lsa_default_config(rates[r]);
        MmseLsaConfig bb = def; bb.broadband_threshold = 0.8f;
        snprintf(label, sizeof(label), "%d Hz library default", rates[r]);
        run_case(label, def, rates[r]);
        snprintf(label, sizeof(label), "%d Hz broadband gate 0.8", rates[r]);
        run_case(label, bb, rates[r]);
    }
    if (g_fail) { printf(">>> FAIL\n"); return 1; }
    printf(">>> PASS\n");
    return 0;
}
