/* Gain API: anr_process_gain() and anr_process_gain_with_residual_psd() return the internal gain
 * vector. The golden hashes were captured from a reference run on the same inputs, so a mismatch
 * means the gains moved. */

#include "anr.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

static const float* gain_plain(AnrDenoiser* d, const Complex* s) {
    return anr_process_gain(d, s);
}
static const float* gain_with_residual(AnrDenoiser* d, const Complex* s, const float* r) {
    return anr_process_gain_with_residual_psd(d, s, r);
}

enum { MODE_PLAIN = 0, MODE_RESIDUAL = 1, MODE_ALTERNATE = 2 };

static uint32_t fnv1a(uint32_t h, const void* p, size_t n) {
    const unsigned char* b = (const unsigned char*)p;
    for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= 16777619u; }
    return h;
}

/* Runs n_frames hops of a deterministic noisy spectrum (frames 30..33 are digital silence) and
 * hashes every returned gain vector. Returns the hash and the largest/smallest gain seen. */
static uint32_t run_case(int sample_rate, AnrLevel level, int mode, int n_frames,
                         float* gmin_seen, float* gmax_seen) {
    AnrConfig cfg = anr_default_config(sample_rate);
    AnrDenoiser* d;
    uint32_t h = 2166136261u, seed = 0x1234567u;
    int nf, k, frame;
    Complex* spec;
    float* residual;
    *gmin_seen = 2.0f; *gmax_seen = -1.0f;
    d = anr_create(&cfg);
    if (!d || anr_set_level(d, level)) { CHECK(0, "create/set_level failed"); return 0; }
    nf = anr_get_n_freqs(d);
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    residual = (float*)calloc((size_t)nf, sizeof(float));
    for (frame = 0; frame < n_frames; frame++) {
        const float* g;
        const float* res = NULL;
        int silent = frame >= 30 && frame < 34;
        for (k = 0; k < nf; k++) {
            float re, im, amp = (frame >= 60 && k > 3 && k < 12) ? 6.0f : 0.2f;
            seed = seed * 1103515245u + 12345u;
            re = ((float)((seed >> 8) & 0xFFFFu) / 65535.0f - 0.5f) * amp;
            seed = seed * 1103515245u + 12345u;
            im = ((float)((seed >> 8) & 0xFFFFu) / 65535.0f - 0.5f) * amp;
            spec[k].r = silent ? 0.0f : re;
            spec[k].i = silent ? 0.0f : im;
            residual[k] = (re * re + im * im) * (0.1f + 0.4f * (float)(k % 5));
        }
        if (mode == MODE_RESIDUAL || (mode == MODE_ALTERNATE && (frame & 1) == 0)) res = residual;
        g = (mode == MODE_PLAIN) ? gain_plain(d, spec) : gain_with_residual(d, spec, res);
        CHECK(g != NULL, "gain returned NULL at frame %d", frame);
        if (!g) break;
        h = fnv1a(h, g, (size_t)nf * sizeof(float));
        for (k = 0; k < nf; k++) {
            if (g[k] < *gmin_seen) *gmin_seen = g[k];
            if (g[k] > *gmax_seen) *gmax_seen = g[k];
        }
    }
    free(spec); free(residual); anr_destroy(d);
    return h;
}

typedef struct { const char* name; int sr; AnrLevel level; int mode; uint32_t golden; } Case;

static const Case kCases[] = {
    {"16k balanced  anr_process_gain",              16000, ANR_LEVEL_BALANCED,   MODE_PLAIN,     0xec100a06u},
    {"16k balanced  residual PSD every hop",        16000, ANR_LEVEL_BALANCED,   MODE_RESIDUAL,  0x8310dee5u},
    {"16k balanced  residual PSD / NULL alternating", 16000, ANR_LEVEL_BALANCED, MODE_ALTERNATE, 0xd0a5741eu},
    {"48k aggressive residual PSD every hop",       48000, ANR_LEVEL_AGGRESSIVE, MODE_RESIDUAL,  0x67a3a05eu},
    {"48k mild      anr_process_gain",              48000, ANR_LEVEL_MILD,       MODE_PLAIN,     0x8fc62e8bu},
};
#define N_CASES ((int)(sizeof(kCases) / sizeof(kCases[0])))
#define N_FRAMES 120

static void test_arguments(void) {
    AnrConfig cfg = anr_default_config(16000);
    AnrDenoiser* a = anr_create(&cfg);
    AnrDenoiser* b = anr_create(&cfg);
    int nf, k, frame, same = 1, stable = 1;
    Complex* spec;
    float* residual;
    const float* first = NULL;
    if (!a || !b) { CHECK(0, "create failed"); return; }
    nf = anr_get_n_freqs(a);
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    residual = (float*)calloc((size_t)nf, sizeof(float));
    for (k = 0; k < nf; k++) spec[k].r = 0.05f + 0.001f * (float)k;

    CHECK(anr_process_gain(NULL, spec) == NULL, "anr_process_gain(NULL handle) is not NULL");
    CHECK(anr_process_gain(a, NULL) == NULL, "anr_process_gain(NULL spectrum) is not NULL");
    CHECK(anr_process_gain_with_residual_psd(NULL, spec, residual) == NULL,
          "with_residual_psd(NULL handle) is not NULL");
    CHECK(anr_process_gain_with_residual_psd(a, NULL, residual) == NULL,
          "with_residual_psd(NULL spectrum) is not NULL");

    /* Refused calls leave the state untouched: a and b still produce identical gains, and a
     * NULL residual PSD is exactly anr_process_gain(). */
    for (frame = 0; frame < 60; frame++) {
        const float* ga;
        const float* gb;
        for (k = 0; k < nf; k++) spec[k].i = 0.02f * (float)((frame * 7 + k * 3) % 11);
        if (frame % 5 == 0) {
            (void)anr_process_gain(a, NULL);
            (void)anr_process_gain_with_residual_psd(a, NULL, residual);
        }
        ga = anr_process_gain(a, spec);
        gb = anr_process_gain_with_residual_psd(b, spec, NULL);
        if (!ga || !gb || memcmp(ga, gb, (size_t)nf * sizeof(float)) != 0) same = 0;
        if (frame == 0) first = ga;
        else if (ga != first) stable = 0;
    }
    CHECK(same, "anr_process_gain differs from with_residual_psd(NULL) or a refused call moved state");
    CHECK(stable, "the returned gain pointer is not the instance's stable internal buffer");
    free(spec); free(residual);
    anr_destroy(a); anr_destroy(b);
}

int main(void) {
    uint32_t hashes[N_CASES];
    int i;
    for (i = 0; i < N_CASES; i++) {
        const Case* c = &kCases[i];
        float gmin, gmax;
        hashes[i] = run_case(c->sr, c->level, c->mode, N_FRAMES, &gmin, &gmax);
        printf("%-48s hash 0x%08x  gain [%.5f, %.5f]\n", c->name, hashes[i], gmin, gmax);
#ifndef USE_STANDARD_MATH      /* the goldens are the default (fast-math) build's; the libm build differs in the last bits */
        CHECK(hashes[i] == c->golden, "%s: gain hash 0x%08x != golden 0x%08x", c->name, hashes[i], c->golden);
#endif
        CHECK(isfinite(gmin) && isfinite(gmax) && gmin > 0.0f && gmax <= 1.0f,
              "%s: gain outside (0, 1]", c->name);
    }
    CHECK(hashes[0] != hashes[1], "a residual PSD did not change the gain (case is vacuous)");
    CHECK(hashes[1] != hashes[2], "alternating residual PSD equals every-hop residual PSD");
    test_arguments();
    if (g_fail) { printf("test_gain_api: FAIL\n"); return 1; }
    printf("test_gain_api: PASS\n");
    return 0;
}
