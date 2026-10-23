/* The startup rows and the minimum ring share one region in the integrated denoiser's tracker.
 * Pins that (1) the standalone tracker keeps separate storage and stays re-initializable,
 * (2) the shared-startup tracker is observably identical to it when the startup rows are
 * re-accumulated after every reset, heap and static, and (3) it ignores startup calls once the ring
 * owns the region. */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "noise_estimator.h"
#include "anr_types.h"
#include "../src/anr_internal.h"
#include "utility/mem_align.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

static uint32_t g_rng;
static float rnd01(void) {
    g_rng = g_rng * 1664525u + 1013904223u;
    return (float)(g_rng >> 8) * (1.0f / 16777216.0f);
}

/* Noise-like power with a periodic speech-like low band; burst != 0 adds a flat loud high band
 * that fires the scene-change reset. */
static void make_power(float* p, int nf, int t, int burst) {
    for (int k = 0; k < nf; ++k) p[k] = 0.01f * (0.5f + rnd01());
    if ((t % 400) >= 250 && (t % 400) < 330)
        for (int k = 2; k < nf / 4; k += 3) p[k] += 4.0f;
    if (burst)
        for (int k = nf / 2; k < nf; ++k) p[k] = 9.0f;
}

typedef struct { NoiseEstimator* est; void* mem; } Tracker;

static Tracker make_tracker(int nf, const AnrConfig* cfg, int shared, int is_static) {
    Tracker t = {NULL, NULL};
    if (is_static) {
        size_t bytes = shared ? noise_estimator_get_mem_size_shared_startup(nf, cfg)
                              : noise_estimator_get_mem_size(nf, cfg);
        if (!bytes || posix_memalign(&t.mem, 16, bytes)) return t;
        t.est = shared ? noise_estimator_init_shared_startup(t.mem, bytes, nf, cfg)
                       : noise_estimator_init(t.mem, bytes, nf, cfg);
    } else {
        t.est = shared ? noise_estimator_create_shared_startup(nf, cfg)
                       : noise_estimator_create(nf, cfg);
    }
    return t;
}

static void free_tracker(Tracker* t) {
    noise_estimator_destroy(t->est);
    free(t->mem);
}

static int same_noise(const NoiseEstimator* a, const NoiseEstimator* b, int nf) {
    return memcmp(noise_estimator_get_noise_psd(a), noise_estimator_get_noise_psd(b),
                  (size_t)nf * sizeof(float)) == 0;
}

static void accumulate_and_init(NoiseEstimator* a, NoiseEstimator* b, int nf, int rows,
                                int* t) {
    float p[1100], sum[1100];
    memset(sum, 0, sizeof sum);
    for (int f = 0; f < rows; ++f) {
        make_power(p, nf, (*t)++, 0);
        for (int k = 0; k < nf; ++k) sum[k] += p[k];
        noise_estimator_accumulate_init_power(a, p, f);
        noise_estimator_accumulate_init_power(b, p, f);
    }
    noise_estimator_init_noise(a, sum, rows);
    noise_estimator_init_noise(b, sum, rows);
}

/* Drive a separate-storage tracker and a shared-startup tracker through the same startup / steady
 * / burst / reset cycles and require identical observable noise PSD after every call. */
static void compare_trackers(int sr, int fft, int L, int init, int is_static, const char* label) {
    AnrConfig cfg = anr_default_config_for_grid(sr, fft);
    int nf = fft / 2 + 1;
    float p[1100];
    int t = 0, mismatches = 0;
    if (L) cfg.L = L;
    if (init) cfg.num_init_frames = init;
    Tracker a = make_tracker(nf, &cfg, 0, is_static);
    Tracker b = make_tracker(nf, &cfg, 1, is_static);
    CHECK(a.est && b.est, "%s: trackers created", label);
    if (!a.est || !b.est) return;
    g_rng = 12345u + (uint32_t)(sr + fft + cfg.L + cfg.num_init_frames);
    for (int cycle = 0; cycle < 5; ++cycle) {
        if (cycle == 2) {   /* abandon a partly filled startup, then restart */
            float q[1100];
            for (int f = 0; f < cfg.num_init_frames / 2; ++f) {
                make_power(q, nf, t++, 0);
                noise_estimator_accumulate_init_power(a.est, q, f);
                noise_estimator_accumulate_init_power(b.est, q, f);
            }
            noise_estimator_reset(a.est);
            noise_estimator_reset(b.est);
            if (!same_noise(a.est, b.est, nf)) mismatches++;
        }
        accumulate_and_init(a.est, b.est, nf, cfg.num_init_frames, &t);
        if (!same_noise(a.est, b.est, nf)) mismatches++;
        for (int h = 0; h < 1500; ++h, ++t) {
            int burst = (h >= 600 && h < 600 + cfg.scene_change_min_frames + 3) ||
                        (h >= 1100 && h < 1100 + cfg.scene_change_min_frames - 1);
            make_power(p, nf, t, burst);
            noise_estimator_update_ex(a.est, p, NULL, (h & 1) != 0, nf / 8, 0.9f);
            noise_estimator_update_ex(b.est, p, NULL, (h & 1) != 0, nf / 8, 0.9f);
            if (!same_noise(a.est, b.est, nf)) mismatches++;
        }
        noise_estimator_reset(a.est);
        noise_estimator_reset(b.est);
        if (!same_noise(a.est, b.est, nf)) mismatches++;
    }
    CHECK(mismatches == 0, "%s: shared-startup tracker differs from separate storage in %d calls",
          label, mismatches);
    free_tracker(&a);
    free_tracker(&b);
}

static void check_sizes(int sr, int fft, int L, int init) {
    AnrConfig cfg = anr_default_config_for_grid(sr, fft);
    int nf = fft / 2 + 1;
    if (L) cfg.L = L;
    if (init) cfg.num_init_frames = init;
    size_t sep = noise_estimator_get_mem_size(nf, &cfg);
    size_t sh = noise_estimator_get_mem_size_shared_startup(nf, &cfg);
    size_t rows_save = cfg.L >= cfg.num_init_frames ? (size_t)cfg.num_init_frames
                                                     : (size_t)cfg.L;
    CHECK(sep && sh, "sr=%d fft=%d: sizes are non-zero", sr, fft);
#ifdef USE_FAST_PERCENTILE
    (void)rows_save;
    CHECK(sh == sep, "sr=%d fft=%d: fast percentile keeps no startup rows (%zu vs %zu)",
          sr, fft, sh, sep);
#else
    /* The shared region is the larger of the two row blocks. */
    CHECK(sep - sh == ALIGN16(rows_save * (size_t)nf * sizeof(float)),
          "sr=%d fft=%d L=%d init=%d: saving %zu != smaller row block %zu",
          sr, fft, cfg.L, cfg.num_init_frames, sep - sh,
          (size_t)ALIGN16(rows_save * (size_t)nf * sizeof(float)));
#endif
}

/* Public contract: the standalone tracker may be re-initialized from its retained startup rows
 * after steady state or a reset, and accumulating while tracking does not disturb tracking. */
static void check_standalone_reinit(int is_static) {
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    int nf = 257, n = cfg.num_init_frames, t = 0;
    float p[300], sum[300], first[300];
    Tracker x = make_tracker(nf, &cfg, 0, is_static);
    Tracker twin = make_tracker(nf, &cfg, 0, is_static);   /* never sees the late accumulate calls */
    CHECK(x.est && twin.est, "standalone trackers created");
    if (!x.est || !twin.est) return;
    g_rng = 99u;
    memset(sum, 0, sizeof sum);
    for (int f = 0; f < n; ++f) {
        make_power(p, nf, t++, 0);
        for (int k = 0; k < nf; ++k) sum[k] += p[k];
        noise_estimator_accumulate_init_power(x.est, p, f);
        noise_estimator_accumulate_init_power(twin.est, p, f);
    }
    noise_estimator_init_noise(x.est, sum, n);
    noise_estimator_init_noise(twin.est, sum, n);
    memcpy(first, noise_estimator_get_noise_psd(x.est), (size_t)nf * sizeof(float));
    for (int h = 0; h < 800; ++h, ++t) {
        make_power(p, nf, t, 0);
        noise_estimator_update_ex(x.est, p, NULL, false, 0, 0.0f);
        noise_estimator_update_ex(twin.est, p, NULL, false, 0, 0.0f);
        noise_estimator_accumulate_init_power(x.est, p, h % n);   /* overwrites a startup row */
        if (!same_noise(x.est, twin.est, nf)) {
            CHECK(0, "standalone tracking disturbed by accumulate at hop %d", h);
            break;
        }
    }
    /* Restore the original rows, then re-initialize without a reset. */
    g_rng = 99u;
    for (int f = 0; f < n; ++f) {
        make_power(p, nf, f, 0);
        noise_estimator_accumulate_init_power(x.est, p, f);
    }
    noise_estimator_init_noise(x.est, sum, n);
    CHECK(memcmp(first, noise_estimator_get_noise_psd(x.est), (size_t)nf * sizeof(float)) == 0,
          "standalone re-init after steady state reproduces the first initialization");
    noise_estimator_reset(x.est);
    noise_estimator_init_noise(x.est, sum, n);   /* retained rows survive a reset */
    CHECK(memcmp(first, noise_estimator_get_noise_psd(x.est), (size_t)nf * sizeof(float)) == 0,
          "standalone init after reset uses the retained rows");
    free_tracker(&x);
    free_tracker(&twin);
}

#ifndef USE_FAST_PERCENTILE
/* Once initialized, the ring owns the shared region: startup calls must not disturb it. The fast
 * percentile build keeps no startup rows, so there is nothing to protect. */
static void check_shared_ignores_startup_calls(void) {
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    int nf = 257, n = cfg.num_init_frames, t = 0;
    float p[300], q[300], sum[300];
    Tracker a = make_tracker(nf, &cfg, 1, 1);
    Tracker b = make_tracker(nf, &cfg, 1, 1);
    CHECK(a.est && b.est, "shared trackers created");
    if (!a.est || !b.est) return;
    g_rng = 4242u;
    accumulate_and_init(a.est, b.est, nf, n, &t);
    memset(sum, 0, sizeof sum);
    for (int k = 0; k < nf; ++k) sum[k] = 1.0f;
    for (int h = 0; h < 600; ++h, ++t) {
        make_power(p, nf, t, 0);
        for (int k = 0; k < nf; ++k) q[k] = 1000.0f;
        noise_estimator_accumulate_init_power(a.est, q, h % n);
        if (h % 50 == 7) noise_estimator_init_noise(a.est, sum, n);
        noise_estimator_update_ex(a.est, p, NULL, false, 0, 0.0f);
        noise_estimator_update_ex(b.est, p, NULL, false, 0, 0.0f);
        if (!same_noise(a.est, b.est, nf)) {
            CHECK(0, "shared tracker disturbed by a startup call at hop %d", h);
            break;
        }
    }
    free_tracker(&a);
    free_tracker(&b);
}
#endif

/* A tracker cannot be built from a zero-length ring or an empty startup window. */
static void check_rejects_degenerate_geometry(void) {
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    int nf = 512 / 2 + 1;
    cfg.L = 0;
    CHECK(!noise_estimator_create(nf, &cfg), "create accepts L=0");
    CHECK(!noise_estimator_create_shared_startup(nf, &cfg), "shared create accepts L=0");
#ifndef USE_FAST_PERCENTILE
    cfg = anr_default_config_for_grid(16000, 512);
    cfg.num_init_frames = 0;
    CHECK(!noise_estimator_create(nf, &cfg), "create accepts num_init_frames=0");
    CHECK(!noise_estimator_create_shared_startup(nf, &cfg),
          "shared create accepts num_init_frames=0");
#endif
}

int main(void) {
    const int rates[] = {8000, 8000, 16000, 16000, 48000};
    const int sizes[] = {128, 256, 256, 512, 1024};
    const int geo[][2] = {{0, 0}, {6, 30}, {30, 6}, {12, 12}};   /* {L, init}; 0 = default */
    for (int g = 0; g < 5; ++g) {
        for (int v = 0; v < 4; ++v) {
            char label[96];
            check_sizes(rates[g], sizes[g], geo[v][0], geo[v][1]);
            for (int is_static = 0; is_static < 2; ++is_static) {
                snprintf(label, sizeof label, "sr=%d fft=%d L=%d init=%d %s", rates[g], sizes[g],
                         geo[v][0], geo[v][1], is_static ? "static" : "heap");
                compare_trackers(rates[g], sizes[g], geo[v][0], geo[v][1], is_static, label);
            }
        }
    }
    check_standalone_reinit(0);
    check_standalone_reinit(1);
    check_rejects_degenerate_geometry();
#ifndef USE_FAST_PERCENTILE
    check_shared_ignores_startup_calls();
#endif
    printf(g_fail ? ">>> FAIL\n" : ">>> PASS\n");
    return g_fail;
}
