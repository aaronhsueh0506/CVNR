/* Per-hop cost of the ANR core on frozen synthetic spectra.
 *
 * usage: bench_anr [passes [warmup [hops]]]   table to stdout
 *        bench_anr --medians [passes [warmup [hops]]]   one tab-separated line of medians (us/hop)
 *
 * Input is a deterministic speech-like signal (stationary coloured noise plus gated harmonic bursts,
 * 16-bit sample scale) transformed to spectra before timing; only anr_process() and
 * anr_process_gain() are timed. Every pass starts from a fresh instance, so each pass processes
 * the same state sequence. A row reports the median, quartiles and minimum of the per-pass cost.
 * The numbers describe the machine and compiler that built this binary; they are not a target
 * platform figure.
 */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "anr.h"
#include "anr_types.h"
#include "fft_wrapper.h"
#include "audio_window.h"
#include "utility/simd_kernels.h"

#define MAX_PASSES 4096

static uint32_t rng_state = 20240611u;

static float rng_uniform(void) {
    rng_state = rng_state * 1664525u + 1013904223u;
    return (float)(rng_state >> 8) * (1.0f / 16777216.0f) - 0.5f;
}

static double now_seconds(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
}

static int compare_double(const void* a, const void* b) {
    double x = *(const double*)a, y = *(const double*)b;
    return (x > y) - (x < y);
}

static double quantile(const double* sorted, int n, double q) {
    double pos = q * (double)(n - 1);
    int lo = (int)pos;
    int hi = lo + 1 < n ? lo + 1 : lo;
    return sorted[lo] + (pos - (double)lo) * (sorted[hi] - sorted[lo]);
}

/* Spectra of `hops` consecutive frames of the synthetic signal; n_freqs bins each. */
static Complex* make_spectra(const AnrConfig* cfg, int hops) {
    const int frame = cfg->frame_size, hop = cfg->hop_size, nf = cfg->fft_size / 2 + 1;
    const double sr = (double)cfg->sample_rate;
    const long samples = (long)(hops - 1) * hop + frame;
    float* x = (float*)malloc((size_t)samples * sizeof(float));
    float* window = (float*)malloc((size_t)frame * sizeof(float));
    float* buffer = (float*)calloc((size_t)cfg->fft_size, sizeof(float));
    Complex* spectra = (Complex*)malloc((size_t)hops * nf * sizeof(Complex));
    FftHandle* fft = fft_create(cfg->fft_size);
    if (!x || !window || !buffer || !spectra || !fft) exit(2);

    double colour = 0.0;
    for (long n = 0; n < samples; ++n) {
        double t = (double)n / sr;
        colour = 0.97 * colour + 0.03 * (double)rng_uniform();
        double burst = fmod(t, 0.9) < 0.5 ? 1.0 : 0.0;
        double f0 = 110.0 + 70.0 * (0.5 + 0.5 * sin(2.0 * M_PI * 0.7 * t));
        double voiced = 0.0;
        for (int h = 1; h <= 24; ++h) {
            if (h * f0 > 0.45 * sr) break;
            voiced += sin(2.0 * M_PI * h * f0 * t + 0.3 * h) / (double)h;
        }
        x[n] = (float)(400.0 * (double)rng_uniform() + 6000.0 * colour + 2500.0 * burst * voiced);
    }
    ac_window_build(window, frame);
    for (int k = 0; k < hops; ++k) {
        for (int i = 0; i < frame; ++i) buffer[i] = x[(long)k * hop + i] * window[i];
        fft_forward(fft, buffer, spectra + (size_t)k * nf);
    }
    fft_destroy(fft);
    free(x);
    free(window);
    free(buffer);
    return spectra;
}

typedef struct { double median, p25, p75, minimum; } Stats;

/* entry 0: anr_process (out of place); entry 1: anr_process_gain with an extra noise PSD. */
static Stats time_cell(const AnrConfig* cfg, const Complex* spectra, int hops, int entry,
                       int passes, int warmup) {
    const int nf = cfg->fft_size / 2 + 1;
    static double per_pass[MAX_PASSES];
    Complex* out = (Complex*)calloc((size_t)nf, sizeof(Complex));
    float* extra = (float*)malloc((size_t)nf * sizeof(float));
    float* gain = (float*)calloc((size_t)nf, sizeof(float));
    if (!out || !extra || !gain) exit(2);
    double mean_power = 0.0;
    for (int k = 0; k < nf; ++k)
        mean_power += (double)spectra[k].r * spectra[k].r + (double)spectra[k].i * spectra[k].i;
    for (int k = 0; k < nf; ++k) extra[k] = (float)(0.25 * mean_power / nf);

    volatile float sink = 0.0f;
    for (int p = 0; p < passes + warmup; ++p) {
        AnrDenoiser* d = anr_create(cfg);
        if (!d) exit(3);
        double t0 = now_seconds();
        if (entry == 0) {
            for (int k = 0; k < hops; ++k) anr_process(d, spectra + (size_t)k * nf, out);
        } else {
            for (int k = 0; k < hops; ++k)
                anr_process_gain(d, spectra + (size_t)k * nf, extra, gain);
        }
        double t1 = now_seconds();
        sink += out[nf / 3].r + gain[nf / 3];
        anr_destroy(d);
        if (p >= warmup) per_pass[p - warmup] = (t1 - t0) / (double)hops * 1e6;
    }
    (void)sink;
    qsort(per_pass, (size_t)passes, sizeof(double), compare_double);
    Stats s = {quantile(per_pass, passes, 0.5), quantile(per_pass, passes, 0.25),
               quantile(per_pass, passes, 0.75), per_pass[0]};
    free(out);
    free(extra);
    free(gain);
    return s;
}

int main(int argc, char** argv) {
    int medians_only = argc > 1 && strcmp(argv[1], "--medians") == 0;
    int arg = medians_only ? 2 : 1;
    int passes = argc > arg ? atoi(argv[arg]) : 30;
    int warmup = argc > arg + 1 ? atoi(argv[arg + 1]) : 5;
    int hops = argc > arg + 2 ? atoi(argv[arg + 2]) : 600;
    if (passes < 1 || passes > MAX_PASSES || warmup < 0 || hops < 100) return 1;

    static const int rates[] = {16000, 16000, 48000};
    static const int sizes[] = {256, 512, 1024};
    static const AnrMode modes[] = {ANR_MODE_BALANCED, ANR_MODE_AGGRESSIVE};
    static const char* const mode_names[] = {"balanced", "aggressive"};
    static const char* const entry_names[] = {"process", "process_gain+extra"};

    if (!medians_only) {
        printf("bench-anr: %d timed passes after %d warm-up passes, %d hops per pass; us per hop\n",
               passes, warmup, hops);
        printf("host timing of this build (NEON kernels %s); not a target-platform figure\n",
               SK_HAVE_NEON ? "on" : "off");
        printf("%-10s %-11s %-19s %9s %9s %9s %9s\n", "grid", "mode", "entry", "median", "p25",
               "p75", "min");
    }
    for (int g = 0; g < 3; ++g) {
        for (int m = 0; m < 2; ++m) {
            AnrConfig cfg = anr_config_for_mode_grid(rates[g], sizes[g], modes[m]);
            if (!anr_validate_config(&cfg)) return 4;
            Complex* spectra = make_spectra(&cfg, hops);
            for (int e = 0; e < 2; ++e) {
                Stats s = time_cell(&cfg, spectra, hops, e, passes, warmup);
                if (medians_only) {
                    printf("%s%.5f", (g | m | e) ? "\t" : "", s.median);
                } else {
                    char grid[16];
                    snprintf(grid, sizeof(grid), "%d/%d", rates[g] / 1000, sizes[g]);
                    printf("%-10s %-11s %-19s %9.4f %9.4f %9.4f %9.4f\n", grid, mode_names[m],
                           entry_names[e], s.median, s.p25, s.p75, s.minimum);
                }
            }
            free(spectra);
        }
    }
    if (medians_only) printf("\n");
    return 0;
}
