/* Scalar twin versus NEON twin of the ANR kernels: output bit patterns must match for every input,
 * including NaN, signed zero, infinity, subnormal and values at each comparison boundary.
 * A NaN result that differs from the twin only in its payload is counted separately; any other
 * difference fails. Builds without NEON compile no vector twin and report so.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../src/anr.c"
#include "../src/mcra_noise_estimator.c"
#include "../src/spp_estimator.c"

#if SK_HAVE_NEON

#define MAX_N 600
#define OFFSETS 4

static uint32_t rng_state = 2463534242u;

static uint32_t random_bits(void) {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}

static float from_bits(uint32_t bits) {
    float value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static uint32_t to_bits(float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static float next_up(float value) { return nextafterf(value, INFINITY); }
static float next_down(float value) { return nextafterf(value, -INFINITY); }

static float uniform(float lo, float hi) {
    return lo + (hi - lo) * ((float)(random_bits() >> 8) * (1.0f / 16777216.0f));
}

static const uint32_t SPECIAL_BITS[] = {
    0x00000000u, 0x80000000u, 0x00000001u, 0x80000001u, 0x007fffffu, 0x807fffffu,
    0x00800000u, 0x80800000u, 0x3f800000u, 0xbf800000u, 0x7f7fffffu, 0xff7fffffu,
    0x7f800000u, 0xff800000u, 0x7fc00000u, 0xffc00000u, 0x7f800001u, 0x7fc12345u, 0xffc54321u};

/* Draw from a realistic range, the boundaries of the kernel under test, generic special values,
 * or a random bit pattern.
 */
static float draw(float lo, float hi, const float* edges, int n_edges) {
    uint32_t r = random_bits();
    uint32_t pick = r & 15u;
    if (pick < 8) return uniform(lo, hi);
    if (pick < 11 && n_edges > 0) {
        float e = edges[(r >> 8) % (uint32_t)n_edges];
        switch ((r >> 20) % 3u) {
        case 0: return e;
        case 1: return next_up(e);
        default: return next_down(e);
        }
    }
    if (pick < 14) return from_bits(SPECIAL_BITS[(r >> 8) % (sizeof(SPECIAL_BITS) / sizeof(SPECIAL_BITS[0]))]);
    return from_bits(random_bits());
}

typedef struct {
    unsigned long calls, lanes, payload_only, nan_lanes, inf_lanes, zero_lanes, subnormal_lanes;
} Stats;

static int is_nan_bits(uint32_t bits) {
    return (bits & 0x7f800000u) == 0x7f800000u && (bits & 0x007fffffu) != 0;
}

/* Compare two result arrays; count output classes of the reference. Returns non-zero on a mismatch. */
static int compare_arrays(const char* kernel, const char* array, const float* ref, const float* got,
                          int n, int trial, Stats* stats) {
    for (int i = 0; i < n; ++i) {
        uint32_t a = to_bits(ref[i]), b = to_bits(got[i]);
        uint32_t magnitude = a & 0x7fffffffu;
        stats->lanes++;
        if (is_nan_bits(a)) stats->nan_lanes++;
        else if (magnitude == 0x7f800000u) stats->inf_lanes++;
        else if (magnitude == 0) stats->zero_lanes++;
        else if (magnitude < 0x00800000u) stats->subnormal_lanes++;
        if (a == b) continue;
        if (is_nan_bits(a) && is_nan_bits(b)) {
            stats->payload_only++;
            continue;
        }
        fprintf(stderr, "%s FAIL: %s[%d] n=%d trial=%d scalar=%08x neon=%08x\n", kernel, array, i, n,
                trial, a, b);
        return 1;
    }
    return 0;
}

static void report(const char* kernel, const Stats* s) {
    printf("%s PASS: %lu calls, %lu lanes (NaN %lu, inf %lu, zero %lu, subnormal %lu); NaN payload-only differences %lu; NEON=%d\n",
           kernel, s->calls, s->lanes, s->nan_lanes, s->inf_lanes, s->zero_lanes,
           s->subnormal_lanes, s->payload_only, SK_HAVE_NEON);
}

static int test_size(int trial) {
    static const int fixed[] = {1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 33, 64, 65, 127, 128, 129,
                                255, 256, 257, 513, 513 + 4};
    if (trial % 3 == 0) return fixed[(trial / 3) % (int)(sizeof(fixed) / sizeof(fixed[0]))];
    return 1 + (int)(random_bits() % 80u);
}

#define TRIALS 6000

#ifdef USE_SHARED_XI_RATIO
static int test_gain_prepare(void) {
    static float v_in_s[MAX_N + OFFSETS], gamma_s[MAX_N + OFFSETS];
    static float v_ref[MAX_N], ratio_ref[MAX_N], v_neon[MAX_N], ratio_neon[MAX_N];
    const float edges[] = {1e-10f, 700.0f, 0.0f, -1e-10f, 1.0f};
    Stats stats = {0};
    for (int trial = 0; trial < TRIALS; ++trial) {
        int n = test_size(trial);
        float* v_in = v_in_s + trial % OFFSETS;
        float* gamma = gamma_s + (trial / OFFSETS) % OFFSETS;
        for (int i = 0; i < n; ++i) {
            v_in[i] = draw(0.0f, 900.0f, edges, 5);
            gamma[i] = draw(-0.5f, 2000.0f, edges, 5);
        }
        gain_prepare_scalar(v_in, gamma, v_ref, ratio_ref, n);
        gain_prepare_neon(v_in, gamma, v_neon, ratio_neon, n);
        stats.calls++;
        if (compare_arrays("gain_prepare", "v", v_ref, v_neon, n, trial, &stats) ||
            compare_arrays("gain_prepare", "ratio", ratio_ref, ratio_neon, n, trial, &stats))
            return 1;
    }
    report("gain_prepare", &stats);
    return 0;
}
#endif

#ifdef USE_FAST_GAIN_SMOOTHING
static FinalGainParams random_params(int trial) {
    FinalGainParams g;
    g.log_g_min = uniform(-8.0f, -0.5f);
    if (trial % 11 == 0) g.log_g_min = from_bits(SPECIAL_BITS[random_bits() % 8u]);
    g.g_min = expf(g.log_g_min);
    g.alpha_attack = uniform(0.0f, 1.0f);
    g.alpha_decay = uniform(0.0f, 1.0f);
    g.prior_lift = uniform(-0.5f, 0.5f);
    g.cross_band_prior = (trial & 1) != 0;
    g.smooth = (trial & 2) != 0;
    g.dd_from_gmmse = (trial & 4) != 0;
    return g;
}

static int test_final_gain(void) {
    static float post_s[MAX_N + OFFSETS], saved_s[MAX_N + OFFSETS];
    static float log_ref[MAX_N], log_neon[MAX_N], em_ref[MAX_N], em_neon[MAX_N];
    static float lg_in_s[MAX_N + OFFSETS], cond[MAX_N], power[MAX_N];
    static float exp_ref[MAX_N], exp_neon[MAX_N], sv_ref[MAX_N], sv_neon[MAX_N];
    static float pg_ref[MAX_N], pg_neon[MAX_N], pp_ref[MAX_N], pp_neon[MAX_N];
    Stats blend = {0}, store = {0};
    for (int trial = 0; trial < TRIALS; ++trial) {
        int n = test_size(trial);
        FinalGainParams g = random_params(trial);
        float* post = post_s + trial % OFFSETS;
        float* saved = saved_s + (trial / OFFSETS) % OFFSETS;
        float* lg_in = lg_in_s + (trial / 2) % OFFSETS;
        const float edges[] = {g.log_g_min, 0.0f, 1.0f};
        for (int i = 0; i < n; ++i) {
            post[i] = draw(0.0f, 1.0f, edges, 3);
            saved[i] = draw(-8.0f, 0.5f, edges, 3);
            log_ref[i] = log_neon[i] = draw(-12.0f, 1.0f, edges, 3);
            lg_in[i] = draw(-12.0f, 1.0f, edges, 3);
            cond[i] = draw(0.0f, 1.0f, edges, 3);
            power[i] = draw(0.0f, 1e6f, edges, 3);
            exp_ref[i] = exp_neon[i] = draw(0.0f, 1.0f, edges, 3);
        }
        final_blend_scalar(&g, post, log_ref, saved, em_ref, n);
        final_blend_neon(&g, post, log_neon, saved, em_neon, n);
        blend.calls++;
        if (compare_arrays("final_blend", "log_gain", log_ref, log_neon, n, trial, &blend) ||
            compare_arrays("final_blend", "emitted", em_ref, em_neon, n, trial, &blend))
            return 1;
        final_store_scalar(&g, lg_in, exp_ref, sv_ref, pg_ref, pp_ref, cond, power, n);
        final_store_neon(&g, lg_in, exp_neon, sv_neon, pg_neon, pp_neon, cond, power, n);
        store.calls++;
        if (compare_arrays("final_store", "gain", exp_ref, exp_neon, n, trial, &store) ||
            compare_arrays("final_store", "saved_log", sv_ref, sv_neon, n, trial, &store) ||
            compare_arrays("final_store", "previous_gain", pg_ref, pg_neon, n, trial, &store) ||
            compare_arrays("final_store", "previous_psd", pp_ref, pp_neon, n, trial, &store))
            return 1;
    }
    report("final_blend", &blend);
    report("final_store", &store);
    return 0;
}
#endif

static int test_restart_inert(void) {
    static float noise_s[MAX_N + OFFSETS], power_s[MAX_N + OFFSETS];
    static float ref[MAX_N], neon[MAX_N];
    const float edges[] = {MCRA_NOISE_PSD_INERT, 0.0f, 1e-10f, 1.0f};
    Stats stats = {0};
    for (int trial = 0; trial < TRIALS; ++trial) {
        int n = test_size(trial);
        float* noise = noise_s + trial % OFFSETS;
        float* power = power_s + (trial / OFFSETS) % OFFSETS;
        float alpha_d = (trial % 13 == 0) ? from_bits(SPECIAL_BITS[random_bits() % 8u]) : uniform(0.0f, 1.0f);
        for (int i = 0; i < n; ++i) {
            noise[i] = draw(0.0f, 4e-20f, edges, 4);
            power[i] = draw(0.0f, 1e6f, edges, 4);
            ref[i] = neon[i] = noise[i];
        }
        mcra_restart_inert_scalar(ref, power, alpha_d, n);
        mcra_restart_inert_neon(neon, power, alpha_d, n);
        stats.calls++;
        if (compare_arrays("restart_inert", "noise", ref, neon, n, trial, &stats)) return 1;
    }
    report("restart_inert", &stats);
    return 0;
}

static int test_spp_dd(void) {
    static float power_s[MAX_N + OFFSETS], noise_s[MAX_N + OFFSETS], prev_s[MAX_N + OFFSETS];
    static float enh_s[MAX_N + OFFSETS];
    static float gamma_ref[MAX_N], gamma_neon[MAX_N], xi_ref[MAX_N], xi_neon[MAX_N];
    static float v_ref[MAX_N], v_neon[MAX_N];
    const float edges[] = {1e-10f, 1.0f, 0.0f, -1e-10f};
    Stats stats = {0};
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    for (int trial = 0; trial < TRIALS; ++trial) {
        int n = test_size(trial);
        SppEstimator* a = spp_create(n, &cfg);
        SppEstimator* b = spp_create(n, &cfg);
        if (!a || !b) return 1;
        a->alpha = b->alpha = (trial % 17 == 0) ? from_bits(SPECIAL_BITS[random_bits() % 8u])
                                                : uniform(0.0f, 1.0f);
        a->xi_min = b->xi_min = (trial % 19 == 0) ? from_bits(SPECIAL_BITS[random_bits() % 8u])
                                                  : uniform(0.0f, 1.0f);
        float* power = power_s + trial % OFFSETS;
        float* noise = noise_s + (trial / 2) % OFFSETS;
        float* noise_prev = prev_s + (trial / 3) % OFFSETS;
        float* enhanced = enh_s + (trial / 5) % OFFSETS;
        for (int i = 0; i < n; ++i) {
            power[i] = draw(0.0f, 1e6f, edges, 4);
            noise[i] = draw(0.0f, 1e5f, edges, 4);
            noise_prev[i] = draw(0.0f, 1e5f, edges, 4);
            enhanced[i] = draw(0.0f, 1e6f, edges, 4);
        }
        int with_v = trial & 1;
        spp_dd_scalar(a, power, noise, noise_prev, enhanced, gamma_ref, xi_ref,
                      with_v ? v_ref : NULL, n);
        spp_dd_neon(b, power, noise, noise_prev, enhanced, gamma_neon, xi_neon,
                    with_v ? v_neon : NULL, n);
        stats.calls++;
        int bad = compare_arrays("spp_dd", "gamma", gamma_ref, gamma_neon, n, trial, &stats) ||
                  compare_arrays("spp_dd", "xi", xi_ref, xi_neon, n, trial, &stats) ||
                  compare_arrays("spp_dd", "v_scratch", a->v_scratch, b->v_scratch, n, trial, &stats) ||
                  compare_arrays("spp_dd", "term_xi", a->term_xi_scratch, b->term_xi_scratch, n, trial, &stats) ||
                  compare_arrays("spp_dd", "gamma_prev", a->gamma_prev, b->gamma_prev, n, trial, &stats) ||
                  (with_v && compare_arrays("spp_dd", "v_out", v_ref, v_neon, n, trial, &stats));
        spp_destroy(a);
        spp_destroy(b);
        if (bad) return 1;
    }
    report("spp_dd", &stats);
    return 0;
}

#if defined(USE_OPTIMIZED_MIN_BUFFER) && defined(USE_INCREMENTAL_MIN)
static int test_ring_min(void) {
    static const int lengths[] = {1, 2, 3, 4, 5, 8, 16, 31, 32, 48, 64};
    static float s_s[MAX_N + OFFSETS], smin_ref_s[MAX_N], smin_neon_s[MAX_N];
    static float ring_ref[MAX_N * 64], ring_neon[MAX_N * 64];
    Stats stats = {0};
    for (int trial = 0; trial < TRIALS / 2; ++trial) {
        int n = test_size(trial);
        int L = lengths[random_bits() % (sizeof(lengths) / sizeof(lengths[0]))];
        int ring_pos = (int)(random_bits() % (uint32_t)L);
        float* s = s_s + trial % OFFSETS;
        const float growth = 1.0f + 1e-6f;
        for (int k = 0; k < n; ++k) {
            float smin = draw(0.0f, 100.0f, NULL, 0);
            if (trial % 5 != 0 && !(smin == smin)) smin = 1.0f;   /* mostly ordinary minima */
            float edge = smin * growth;
            const float s_edges[] = {smin};
            const float o_edges[] = {edge, smin};
            s[k] = draw(0.0f, 100.0f, s_edges, 1);
            smin_ref_s[k] = smin_neon_s[k] = smin;
            for (int l = 0; l < L; ++l) ring_ref[(size_t)k * L + l] = draw(0.0f, 100.0f, NULL, 0);
            ring_ref[(size_t)k * L + ring_pos] = draw(0.0f, 100.0f, o_edges, 2);
        }
        memcpy(ring_neon, ring_ref, (size_t)n * L * sizeof(float));
        mcra_ring_min_scalar(smin_ref_s, s, ring_ref, L, ring_pos, n);
        mcra_ring_min_neon(smin_neon_s, s, ring_neon, L, ring_pos, n);
        stats.calls++;
        if (compare_arrays("ring_min", "S_min", smin_ref_s, smin_neon_s, n, trial, &stats) ||
            compare_arrays("ring_min", "ring", ring_ref, ring_neon, n * L, trial, &stats))
            return 1;
    }
    report("ring_min", &stats);
    return 0;
}
#endif

#endif /* SK_HAVE_NEON */

int main(void) {

#if SK_HAVE_NEON
#ifdef USE_SHARED_XI_RATIO
    if (test_gain_prepare()) return 1;
#endif
#ifdef USE_FAST_GAIN_SMOOTHING
    if (test_final_gain()) return 1;
#endif
    if (test_restart_inert()) return 1;
    if (test_spp_dd()) return 1;
#if defined(USE_OPTIMIZED_MIN_BUFFER) && defined(USE_INCREMENTAL_MIN)
    if (test_ring_min()) return 1;
#endif
#else
    printf("ANR kernels: scalar build, no vector twin compiled (NEON=0)\n");
#endif
    return 0;
}
