/* Exact-zero (digital silence) frames carry no noise statistics:
 *  - they do not count toward noise initialization, so a stream that starts with silence
 *    initializes on the signal that follows;
 *  - they do not advance the tracker, so a converged noise floor survives a silent stretch;
 *  - after five seconds of silence a stationary tone whose first frame is a waveform onset
 *    (partial frame at reduced power) reaches the same steady gain as the same tone without
 *    leading silence.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "anr.h"
#include "anr_types.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

/* Mean gain of the 1 kHz bin over the last second of a `tone_s`-second tone preceded by
 * `silence_s` seconds of exact-zero spectra. The first tone frame has amplitude
 * `onset` times the steady amplitude (a frame straddling the waveform onset). */
static double tone_gain(const AnrConfig* cfg, int sr, double silence_s, double tone_s, double onset) {
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
        spec[bin].r = (float)(onset > 0.0 && h == 0 ? onset : 1.0) * 0.03f * 32768.0f * (float)(fft / 2);   /* -30 dBFS tone, int16-scale FFT */
        anr_process_gain(d, spec, NULL, gain);
        if (h >= n_tone - last) acc += gain[bin];
    }
    free(spec); free(gain); anr_destroy(d);
    return acc / last;
}

static void run_case(const char* label, AnrConfig cfg, int sr, double onset) {
    double control = tone_gain(&cfg, sr, 0.0, 10.0, onset);
    double after = tone_gain(&cfg, sr, 5.0, 10.0, onset);
    printf("%-40s onset %.2f  control %.4f (%.1f dB)  after 5 s silence %.4f (%.1f dB)\n", label, onset,
           control, 20.0 * log10(control + 1e-12), after, 20.0 * log10(after + 1e-12));
    CHECK(control >= 0.0 && after >= 0.0, "%s: create failed", label);
    /* Above the speech guard, steady gain must stay within 4x the preset floor. */
    double floor_gain = pow(10.0, cfg.g_min_db / 20.0);
    CHECK(control < 4.0 * floor_gain, "%s: stationary tone is not sufficiently suppressed (control %.3f, floor %.3f)", label, control, floor_gain);
    CHECK(after < 4.0 * floor_gain, "%s: tone after digital silence stays unsuppressed (%.3f, floor %.3f)", label, after, floor_gain);
    CHECK(fabs(after - control) < 0.02, "%s: silence-first gain %.3f != control %.3f", label, after, control);
}

/* Silence must not initialize the estimator, must pass through unchanged, and must not move a
 * converged noise floor. */
static void run_state_case(const char* label, AnrConfig cfg) {
    AnrDenoiser* d = anr_create(&cfg);
    int nf, hop, n_noise, n_sil, h, k, bad;
    Complex* spec; float* gain; AnrDebugStatus before, after;
    if (!d) { CHECK(0, "%s: create failed", label); return; }
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d);
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex)); gain = (float*)calloc((size_t)nf, sizeof(float));
    n_sil = (int)(5.0 * cfg.sample_rate / hop);

    for (h = 0; h < n_sil; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        anr_process_gain(d, spec, NULL, gain);
    }
    CHECK(!anr_is_initialized(d), "%s: silence counted toward noise initialization", label);
    for (k = 0, bad = 0; k < nf; ++k) bad += gain[k] != 1.0f;
    CHECK(bad == 0, "%s: %d of %d silent-frame gains differ from 1", label, bad, nf);

    n_noise = 3 * cfg.num_init_frames;
    for (h = 0; h < n_noise; ++h) {
        for (k = 0; k < nf; ++k) { spec[k].r = 400.0f + (float)((k * 7 + h * 3) % 11); spec[k].i = 0.0f; }
        anr_process_gain(d, spec, NULL, gain);
    }
    CHECK(anr_is_initialized(d), "%s: not initialized after %d signal frames", label, n_noise);
    anr_debug_status(d, &before);
    for (h = 0; h < n_sil; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        anr_process_gain(d, spec, NULL, gain);
    }
    anr_debug_status(d, &after);
    printf("%-40s noise floor %.3f dB -> %.3f dB across 5 s silence\n", label, before.noise_floor_db, after.noise_floor_db);
    CHECK(before.noise_floor_db == after.noise_floor_db,
          "%s: silence moved the noise floor (%.4f -> %.4f dB)", label, before.noise_floor_db, after.noise_floor_db);
    free(spec); free(gain); anr_destroy(d);
}

int main(void) {
    static const int rates[2] = { 16000, 48000 };
    static const double onsets[2] = { 1.0, 0.5 };
    int r, o;
    for (r = 0; r < 2; ++r) {
        char label[64];
        AnrConfig def = anr_default_config(rates[r]);
        AnrConfig bb = def; bb.broadband_threshold = 0.8f;
        for (o = 0; o < 2; ++o) {
            snprintf(label, sizeof(label), "%d Hz library default", rates[r]);
            run_case(label, def, rates[r], onsets[o]);
            snprintf(label, sizeof(label), "%d Hz broadband gate 0.8", rates[r]);
            run_case(label, bb, rates[r], onsets[o]);
        }
        snprintf(label, sizeof(label), "%d Hz state", rates[r]);
        run_state_case(label, def);
    }
    if (g_fail) { printf(">>> FAIL\n"); return 1; }
    printf(">>> PASS\n");
    return 0;
}
