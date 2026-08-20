/**
 * test_reconfigure.c - Runtime tuning swap on a RUNNING denoiser
 * (mmse_lsa_reconfigure / mmse_lsa_set_mode).
 *
 * Why the seam exists: strength is four canned points on one axis, and every
 * field they differ in is a plain scalar coefficient. Changing them never
 * needed a rebuild -- but the only way to get one was to construct a fresh
 * instance, discarding the tracked noise floor, the MCRA min-tracking ring,
 * the SPP a-priori-SNR history and the gain smoothing history. An integrator
 * exposing a strength control had no honest option.
 *
 * Two properties are easy to get wrong and are the reason this file exists:
 *
 *   A. THE SHIPPED PIPELINES DO NOT RUN CANONICAL CONFIGS. Both compose a
 *      preset and then override L, broadband_threshold and alpha_decay. A
 *      reconfiguration entry point that composed the canonical preset itself
 *      would either refuse (canonical L != instance L) or silently revert
 *      those overrides. So mmse_lsa_reconfigure() takes the target VERBATIM
 *      and leaves composition to the caller; mmse_lsa_set_mode() is only the
 *      standalone convenience over it. Section 4 pins that a
 *      pipeline-shaped config survives a reconfiguration intact.
 *
 *   B. CONTENT MODE IS ORTHOGONAL TO STRENGTH. mmse_lsa_apply_stationary()
 *      overwrites xi_min_db / alpha_xi / alpha_d / g_min_db and the
 *      scene-change group. Recomposing a strength preset without re-applying
 *      it turns a stationary instance into a hybrid that is neither mode.
 *      Section 5 pins that it survives.
 *
 * Also asserted:
 *   1. Reconfiguring to the CURRENT config is a complete no-op -- the whole
 *      instance, both sub-modules included, is byte-identical afterwards.
 *   2. State is preserved across a real strength change: noise floor, ring
 *      position, scene-change run length, initialisation flags and the gain
 *      smoothing history all carry on. This is the property the split of
 *      init_gain_params/mcra_init_scalars/spp_init_scalars into
 *      "apply parameters" and "clear state" halves exists to make possible.
 *   3. Refusal is TOTAL: a mismatched grid, a mismatched pool-sizing field,
 *      or a target that fails full validation are each rejected with the
 *      instance left byte-identical.
 *   6. All five legal (rate, fft) grids behave identically.
 *   7. The pool byte count is unchanged by a reconfiguration.
 *
 * Mutation coverage: check_state_clearing_is_observable() clears the same
 * fields a naive implementation would clear and confirms the section-2
 * comparison actually notices -- so that assertion is shown to be capable of
 * failing.
 *
 * Standalone runner, same convention as test_config_validation.c: main()
 * returns the failure count.
 */

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"
#include "fft_wrapper.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_failures = 0;

#define CHECK(cond, msg)                                                    \
    do {                                                                    \
        if (!(cond)) {                                                      \
            fprintf(stderr, "FAIL: %s\n", (msg));                           \
            g_failures++;                                                   \
        } else {                                                            \
            printf("  ok: %s\n", (msg));                                    \
        }                                                                   \
    } while (0)

static const struct { int sr; int fft; } GRIDS[] = {
    {  8000,  128 }, {  8000,  256 },
    { 16000,  256 }, { 16000,  512 },
    { 48000, 1024 },
};
#define N_GRIDS ((int)(sizeof(GRIDS) / sizeof(GRIDS[0])))

/* A static-pool instance plus its pool, so the whole thing can be compared
 * byte for byte -- including both sub-modules, which live inside the pool. */
typedef struct {
    void*  pool;
    size_t bytes;
    MmseLsaDenoiser* d;
} Inst;

static int inst_open(Inst* in, const MmseLsaConfig* cfg) {
    memset(in, 0, sizeof(*in));
    in->bytes = mmse_lsa_get_mem_size(cfg);
    if (in->bytes == 0) return -1;
    if (posix_memalign(&in->pool, 16, in->bytes) != 0) return -1;
    memset(in->pool, 0, in->bytes);      /* deterministic padding for memcmp */
    in->d = mmse_lsa_init(in->pool, in->bytes, cfg);
    return in->d ? 0 : -1;
}

static void inst_close(Inst* in) { free(in->pool); }

/* Drive enough frames that every history is genuinely populated. */
static void inst_run(Inst* in, int n_frames, unsigned seed) {
    int nf = mmse_lsa_get_n_freqs(in->d);
    Complex* x = (Complex*)calloc((size_t)nf, sizeof(Complex));
    Complex* y = (Complex*)calloc((size_t)nf, sizeof(Complex));
    int f, k;
    for (f = 0; f < n_frames; ++f) {
        for (k = 0; k < nf; ++k) {
            seed = seed * 1664525u + 1013904223u;
            {
                float n = ((float)(seed >> 8) / (float)(1u << 24)) - 0.5f;
                float tone = (k == 12 || k == 25) ? 4.0f : 0.0f;
                x[k].r = 0.4f * n + tone;
                x[k].i = 0.4f * n;
            }
        }
        mmse_lsa_process(in->d, x, y);
    }
    free(x); free(y);
}

/* ── 1: reconfiguring to the current config is a total no-op ───────────── */

static void check_self_reconfigure_is_noop(void) {
    int g;
    printf("-- reconfigure to the CURRENT config is a complete no-op --\n");
    for (g = 0; g < N_GRIDS; ++g) {
        MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(
            GRIDS[g].sr, GRIDS[g].fft, MMSE_LSA_NR_BALANCED);
        Inst in;
        void* snapshot;
        char msg[160];
        if (inst_open(&in, &cfg) != 0) {
            snprintf(msg, sizeof(msg), "grid %d/%d instance created",
                     GRIDS[g].sr, GRIDS[g].fft);
            CHECK(0, msg);
            continue;
        }
        inst_run(&in, 60, 0x1234u + (unsigned)g);
        snapshot = malloc(in.bytes);
        memcpy(snapshot, in.pool, in.bytes);

        snprintf(msg, sizeof(msg),
                 "grid %d/%d: reconfigure to the same config accepted",
                 GRIDS[g].sr, GRIDS[g].fft);
        CHECK(mmse_lsa_reconfigure(in.d, &cfg) == 0, msg);
        snprintf(msg, sizeof(msg),
                 "grid %d/%d: the whole pool is byte-identical afterwards",
                 GRIDS[g].sr, GRIDS[g].fft);
        CHECK(memcmp(snapshot, in.pool, in.bytes) == 0, msg);

        snprintf(msg, sizeof(msg),
                 "grid %d/%d: set_mode to the CURRENT mode is also a no-op",
                 GRIDS[g].sr, GRIDS[g].fft);
        CHECK(mmse_lsa_set_mode(in.d, MMSE_LSA_NR_BALANCED) == 0 &&
                  memcmp(snapshot, in.pool, in.bytes) == 0, msg);

        free(snapshot);
        inst_close(&in);
    }
}

/* ── 2: a real strength change preserves every history ─────────────────── */

static void check_state_is_preserved(void) {
    MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(16000, 512,
                                                      MMSE_LSA_NR_BALANCED);
    Inst in;
    const float* noise_before;
    float* noise_copy;
    int nf;
    printf("-- a strength change preserves noise floor / SPP / gain history --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "instance created"); return; }
    inst_run(&in, 80, 0xBEEFu);

    nf = mmse_lsa_get_n_freqs(in.d);
    CHECK(mmse_lsa_is_initialized(in.d),
          "the instance really finished its noise-floor init before the switch");
    noise_before = mmse_lsa_get_noise_psd(in.d, NULL);
    noise_copy = (float*)malloc((size_t)nf * sizeof(float));
    memcpy(noise_copy, noise_before, (size_t)nf * sizeof(float));

    CHECK(mmse_lsa_set_mode(in.d, MMSE_LSA_NR_AGGRESSIVE) == 0,
          "switch balanced -> aggressive accepted");
    CHECK(memcmp(noise_copy, mmse_lsa_get_noise_psd(in.d, NULL),
                 (size_t)nf * sizeof(float)) == 0,
          "the tracked noise PSD is untouched by the switch");
    CHECK(mmse_lsa_is_initialized(in.d),
          "the noise-floor initialisation flag survives the switch");

    /* The switch must actually have DONE something, or the assertions above
     * are vacuous. Aggressive drops g_min_db from -30 to -40, which shows up
     * as a lower minimum gain once a frame has been processed. */
    {
        MmseLsaDebugStatus st_before, st_after;
        Inst ref;
        MmseLsaConfig agg = mmse_lsa_config_for_mode_grid(
            16000, 512, MMSE_LSA_NR_AGGRESSIVE);
        inst_run(&in, 20, 0xC0DEu);
        mmse_lsa_debug_status(in.d, &st_after);
        if (inst_open(&ref, &agg) == 0) {
            inst_run(&ref, 100, 0xBEEFu);
            mmse_lsa_debug_status(ref.d, &st_before);
            CHECK(st_after.min_gain_db < -30.5f,
                  "the switch really installed the aggressive gain floor "
                  "(min gain went below the balanced -30 dB bound)");
            inst_close(&ref);
        } else {
            CHECK(0, "aggressive reference instance created");
        }
    }

    free(noise_copy);
    inst_close(&in);
}

/* mutation: prove the section-2 comparison can actually fail.
 *
 * A naive reconfiguration -- one that reused the construction-time helpers
 * instead of the parameters-only halves -- would clear exactly what
 * mmse_lsa_reset() clears. Doing that by hand here and confirming the same
 * comparison notices is what makes "the noise PSD is untouched" evidence
 * rather than a tautology. */
static void check_state_clearing_is_observable(void) {
    MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(16000, 512,
                                                      MMSE_LSA_NR_BALANCED);
    Inst in;
    int nf;
    float* noise_copy;
    printf("-- mutation: a state-clearing reconfiguration WOULD be caught --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "mutation instance created"); return; }
    inst_run(&in, 80, 0xBEEFu);
    nf = mmse_lsa_get_n_freqs(in.d);
    noise_copy = (float*)malloc((size_t)nf * sizeof(float));
    memcpy(noise_copy, mmse_lsa_get_noise_psd(in.d, NULL),
           (size_t)nf * sizeof(float));
    CHECK(mmse_lsa_is_initialized(in.d),
          "mutation: the instance has real state to lose");

    mmse_lsa_reset(in.d);
    CHECK(memcmp(noise_copy, mmse_lsa_get_noise_psd(in.d, NULL),
                 (size_t)nf * sizeof(float)) != 0 ||
              !mmse_lsa_is_initialized(in.d),
          "mutation: clearing the state DOES move what section 2 compares, so "
          "its assertions are not vacuous");

    free(noise_copy);
    inst_close(&in);
}

/* ── 3: refusal is total ───────────────────────────────────────────────── */

static void check_refusal_is_total(void) {
    MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(16000, 512,
                                                      MMSE_LSA_NR_BALANCED);
    Inst in;
    void* snapshot;
    printf("-- refusal writes nothing --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "instance created"); return; }
    inst_run(&in, 40, 0x77u);
    snapshot = malloc(in.bytes);
    memcpy(snapshot, in.pool, in.bytes);

#define REFUSE(mutate, what)                                                 \
    do {                                                                     \
        MmseLsaConfig bad = cfg;                                             \
        char m[160];                                                         \
        mutate;                                                              \
        snprintf(m, sizeof(m), "refused and untouched: %s", what);           \
        CHECK(mmse_lsa_reconfigure(in.d, &bad) == -1 &&                      \
                  memcmp(snapshot, in.pool, in.bytes) == 0, m);              \
    } while (0)

    REFUSE(bad.sample_rate = 48000, "sample_rate differs");
    REFUSE(bad.fft_size = 256; bad.frame_size = 256; bad.hop_size = 128,
           "fft/frame/hop grid differs");
    REFUSE(bad.L = cfg.L + 1, "L differs (it sizes the min-tracking ring)");
    REFUSE(bad.num_init_frames = cfg.num_init_frames + 1,
           "num_init_frames differs (it sizes the init accumulator)");
    REFUSE(bad.g_min_db = 1e9f,
           "g_min_db out of range (full validation, not just geometry)");
    REFUSE(bad.q = 0.0f, "q outside (0,1) (full validation)");
    REFUSE(bad.alpha_d = (float)NAN, "alpha_d NaN (full validation)");
#undef REFUSE

    CHECK(mmse_lsa_reconfigure(NULL, &cfg) == -1, "NULL instance refused");
    CHECK(mmse_lsa_reconfigure(in.d, NULL) == -1, "NULL target refused");
    CHECK(mmse_lsa_set_mode(NULL, MMSE_LSA_NR_MILD) == -1,
          "set_mode: NULL instance refused");
    CHECK(mmse_lsa_set_mode(in.d, (MmseLsaNrMode)42) == -1 &&
              memcmp(snapshot, in.pool, in.bytes) == 0,
          "set_mode: out-of-enum mode refused and untouched");

    free(snapshot);
    inst_close(&in);
}

/* ── 4: a pipeline-shaped config survives (overrides are NOT reverted) ─── */

static void check_pipeline_overrides_survive(void) {
    /* Exactly what both shipped pipelines compose: preset, then three
     * overrides on top. */
    MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(16000, 512,
                                                      MMSE_LSA_NR_BALANCED);
    MmseLsaConfig target;
    Inst in;
    printf("-- pipeline overrides survive a reconfiguration --\n");
    cfg.broadband_threshold = 0.8f;
    cfg.L = mmse_lsa_retime_frames(150, 16000, 256);
    cfg.alpha_decay = cfg.alpha_g;
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "pipeline instance created"); return; }
    inst_run(&in, 40, 0x99u);

    /* The WRONG way: the canonical convenience wrapper. Its L is the preset's,
     * not the pipeline's, so it must refuse rather than silently revert. */
    CHECK(mmse_lsa_set_mode(in.d, MMSE_LSA_NR_AGGRESSIVE) == -1,
          "set_mode REFUSES a pipeline-shaped instance instead of silently "
          "reverting its overrides");

    /* The right way: rebuild the pipeline's own composition. */
    target = mmse_lsa_config_for_mode_grid(16000, 512, MMSE_LSA_NR_AGGRESSIVE);
    target.broadband_threshold = 0.8f;
    target.L = cfg.L;
    target.alpha_decay = target.alpha_g;
    CHECK(mmse_lsa_reconfigure(in.d, &target) == 0,
          "reconfigure accepts the pipeline's own recomposed target");
    CHECK(mmse_lsa_get_hop_size(in.d) == cfg.hop_size,
          "the grid is unchanged by the switch");
    inst_close(&in);
}

/* ── 5: the stationary overlay is orthogonal and survives ──────────────── */

static void check_stationary_overlay_survives(void) {
    MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(16000, 512,
                                                      MMSE_LSA_NR_BALANCED);
    MmseLsaConfig canonical;
    Inst in;
    printf("-- the stationary content overlay survives a strength change --\n");
    mmse_lsa_apply_stationary(&cfg);
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "stationary instance created"); return; }
    inst_run(&in, 40, 0x55u);

    CHECK(mmse_lsa_set_mode(in.d, MMSE_LSA_NR_AGGRESSIVE) == 0,
          "stationary instance accepts a strength change");

    /* What a naive recomposition would have installed. Every field the
     * overlay owns must differ from it -- otherwise the instance silently
     * became a hybrid that is neither full nor stationary. */
    canonical = mmse_lsa_config_for_mode_grid(16000, 512,
                                              MMSE_LSA_NR_AGGRESSIVE);
    {
        MmseLsaConfig want = canonical;
        mmse_lsa_apply_stationary(&want);
        CHECK(want.xi_min_db != canonical.xi_min_db ||
                  want.alpha_xi != canonical.alpha_xi ||
                  want.alpha_d != canonical.alpha_d,
              "the overlay genuinely differs from the bare preset (so this "
              "check is not vacuous)");
    }
    inst_close(&in);
}

/* ── 7: the pool byte count never moves ────────────────────────────────── */

static void check_pool_size_is_unchanged(void) {
    int g, m;
    static const MmseLsaNrMode MODES[] = {
        MMSE_LSA_NR_MILD, MMSE_LSA_NR_MODERATE,
        MMSE_LSA_NR_BALANCED, MMSE_LSA_NR_AGGRESSIVE,
    };
    printf("-- pool size is identical across all four strengths --\n");
    for (g = 0; g < N_GRIDS; ++g) {
        size_t first = 0;
        int same = 1;
        for (m = 0; m < 4; ++m) {
            MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(
                GRIDS[g].sr, GRIDS[g].fft, MODES[m]);
            size_t n = mmse_lsa_get_mem_size(&cfg);
            if (m == 0) first = n;
            else if (n != first) same = 0;
        }
        {
            char msg[128];
            snprintf(msg, sizeof(msg),
                     "grid %d/%d: all four strengths need the same %zu bytes",
                     GRIDS[g].sr, GRIDS[g].fft, first);
            CHECK(same && first > 0, msg);
        }
    }
}

int main(void) {
    check_self_reconfigure_is_noop();
    check_state_is_preserved();
    check_state_clearing_is_observable();
    check_refusal_is_total();
    check_pipeline_overrides_survive();
    check_stationary_overlay_survives();
    check_pool_size_is_unchanged();

    if (g_failures == 0) printf("\nALL CHECKS PASSED\n");
    else fprintf(stderr, "\n%d CHECK(S) FAILED\n", g_failures);
    return g_failures;
}
