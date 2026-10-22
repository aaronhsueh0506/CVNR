/* Runtime reconfiguration must retain state and caller-composed tunables.
 * Reject invalid or resized configs without writes.
 * Checks heap/static paths and unchanged pool sizes. Returns failure count. */

#include "anr.h"
#include "anr_types.h"
#include "noise_estimator.h"
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
    AnrDenoiser* d;
} Inst;

static int inst_open(Inst* in, const AnrConfig* cfg) {
    memset(in, 0, sizeof(*in));
    in->bytes = anr_get_mem_size(cfg);
    if (in->bytes == 0) return -1;
    if (posix_memalign(&in->pool, 16, in->bytes) != 0) return -1;
    memset(in->pool, 0, in->bytes);      /* deterministic padding for memcmp */
    in->d = anr_init(in->pool, in->bytes, cfg);
    return in->d ? 0 : -1;
}

static void inst_close(Inst* in) { free(in->pool); }

/* Drive enough frames that every history is genuinely populated. */
static void inst_run(Inst* in, int n_frames, unsigned seed) {
    int nf = anr_get_n_freqs(in->d);
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
        anr_process(in->d, x, y);
    }
    free(x); free(y);
}

/* inst_run() plus the mean gain (dB) averaged over the run's last 20 frames,
 * so a strength switch can be judged by its effect on the same input. */
static float inst_run_mean_gain_db(Inst* in, int n_frames, unsigned seed) {
    int nf = anr_get_n_freqs(in->d);
    Complex* x = (Complex*)calloc((size_t)nf, sizeof(Complex));
    Complex* y = (Complex*)calloc((size_t)nf, sizeof(Complex));
    AnrDebugStatus st;
    float acc = 0.0f;
    int f, k, tail = n_frames < 20 ? n_frames : 20;
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
        anr_process(in->d, x, y);
        if (f >= n_frames - tail) {
            anr_debug_status(in->d, &st);
            acc += st.mean_gain_db;
        }
    }
    free(x); free(y);
    return acc / (float)tail;
}

/* ── 1: reconfiguring to the current config is a total no-op ───────────── */

static void check_self_reconfigure_is_noop(void) {
    int g;
    printf("-- reconfigure to the CURRENT config is a complete no-op --\n");
    for (g = 0; g < N_GRIDS; ++g) {
        AnrConfig cfg = anr_config_for_mode_grid(
            GRIDS[g].sr, GRIDS[g].fft, ANR_MODE_BALANCED);
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
        CHECK(anr_reconfigure(in.d, &cfg) == 0, msg);
        snprintf(msg, sizeof(msg),
                 "grid %d/%d: the whole pool is byte-identical afterwards",
                 GRIDS[g].sr, GRIDS[g].fft);
        CHECK(memcmp(snapshot, in.pool, in.bytes) == 0, msg);

        snprintf(msg, sizeof(msg),
                 "grid %d/%d: set_mode to the CURRENT mode is also a no-op",
                 GRIDS[g].sr, GRIDS[g].fft);
        CHECK(anr_set_mode(in.d, ANR_MODE_BALANCED) == 0 &&
                  memcmp(snapshot, in.pool, in.bytes) == 0, msg);

        free(snapshot);
        inst_close(&in);
    }
}

/* ── 2: a real strength change preserves every history ─────────────────── */

static void check_state_is_preserved(void) {
    AnrConfig cfg = anr_config_for_mode_grid(16000, 512,
                                                      ANR_MODE_BALANCED);
    Inst in;
    const float* noise_before;
    float* noise_copy;
    void* pool_copy;
    float gain_before, gain_after;
    int nf;
    printf("-- a strength change preserves noise floor / SPP / gain history --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "instance created"); return; }
    gain_before = inst_run_mean_gain_db(&in, 80, 0xBEEFu);

    nf = anr_get_n_freqs(in.d);
    CHECK(anr_is_initialized(in.d),
          "the instance really finished its noise-floor init before the switch");
    noise_before = anr_get_noise_psd(in.d, NULL);
    noise_copy = (float*)malloc((size_t)nf * sizeof(float));
    memcpy(noise_copy, noise_before, (size_t)nf * sizeof(float));
    pool_copy = malloc(in.bytes);
    memcpy(pool_copy, in.pool, in.bytes);

    CHECK(anr_set_mode(in.d, ANR_MODE_AGGRESSIVE) == 0,
          "switch balanced -> aggressive accepted");
    CHECK(memcmp(noise_copy, anr_get_noise_psd(in.d, NULL),
                 (size_t)nf * sizeof(float)) == 0,
          "the tracked noise PSD is untouched by the switch");
    CHECK(anr_is_initialized(in.d),
          "the noise-floor initialisation flag survives the switch");
    CHECK(memcmp(pool_copy, in.pool, in.bytes) != 0,
          "the strength switch changed configuration scalars (not a no-op)");

    /* The switch must actually have DONE something, or the assertions above
     * are vacuous: the deeper preset has to lower the mean gain on the same
     * stationary input once its history has been re-driven. */
    gain_after = inst_run_mean_gain_db(&in, 100, 0xC0DEu);
    printf("   mean gain over the last 20 frames: balanced %.2f dB -> aggressive %.2f dB\n",
           gain_before, gain_after);
    CHECK(gain_after < gain_before - 0.5f,
          "the switch really installed the deeper preset (mean gain fell by > 0.5 dB)");

    free(pool_copy);
    free(noise_copy);
    inst_close(&in);
}

/* mutation: prove the section-2 comparison can actually fail.
 *
 * A naive reconfiguration -- one that reused the construction-time helpers
 * instead of the parameters-only halves -- would clear exactly what
 * anr_reset() clears. Doing that by hand here and confirming the same
 * comparison notices is what makes "the noise PSD is untouched" evidence
 * rather than a tautology. */
static void check_state_clearing_is_observable(void) {
    AnrConfig cfg = anr_config_for_mode_grid(16000, 512,
                                                      ANR_MODE_BALANCED);
    Inst in;
    int nf;
    float* noise_copy;
    printf("-- mutation: a state-clearing reconfiguration WOULD be caught --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "mutation instance created"); return; }
    inst_run(&in, 80, 0xBEEFu);
    nf = anr_get_n_freqs(in.d);
    noise_copy = (float*)malloc((size_t)nf * sizeof(float));
    memcpy(noise_copy, anr_get_noise_psd(in.d, NULL),
           (size_t)nf * sizeof(float));
    CHECK(anr_is_initialized(in.d),
          "mutation: the instance has real state to lose");

    anr_reset(in.d);
    CHECK(memcmp(noise_copy, anr_get_noise_psd(in.d, NULL),
                 (size_t)nf * sizeof(float)) != 0 ||
              !anr_is_initialized(in.d),
          "mutation: clearing the state DOES move what section 2 compares, so "
          "its assertions are not vacuous");

    free(noise_copy);
    inst_close(&in);
}

/* ── 3: refusal is total ───────────────────────────────────────────────── */

static void check_refusal_is_total(void) {
    AnrConfig cfg = anr_config_for_mode_grid(16000, 512,
                                                      ANR_MODE_BALANCED);
    Inst in;
    void* snapshot;
    printf("-- refusal writes nothing --\n");
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "instance created"); return; }
    inst_run(&in, 40, 0x77u);
    snapshot = malloc(in.bytes);
    memcpy(snapshot, in.pool, in.bytes);

#define REFUSE(mutate, what)                                                 \
    do {                                                                     \
        AnrConfig bad = cfg;                                             \
        char m[160];                                                         \
        mutate;                                                              \
        snprintf(m, sizeof(m), "refused and untouched: %s", what);           \
        CHECK(anr_reconfigure(in.d, &bad) == -1 &&                      \
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

    CHECK(anr_reconfigure(NULL, &cfg) == -1, "NULL instance refused");
    CHECK(anr_reconfigure(in.d, NULL) == -1, "NULL target refused");
    CHECK(anr_set_mode(NULL, ANR_MODE_MILD) == -1,
          "set_mode: NULL instance refused");
    CHECK(anr_set_mode(in.d, (AnrMode)42) == -1 &&
              memcmp(snapshot, in.pool, in.bytes) == 0,
          "set_mode: out-of-enum mode refused and untouched");

    free(snapshot);
    inst_close(&in);
}

/* ── 4: a pipeline-shaped config survives (overrides are NOT reverted) ─── */

static void check_pipeline_overrides_survive(void) {
    /* Exactly what both shipped pipelines compose: preset, then three
     * overrides on top. */
    AnrConfig cfg = anr_config_for_mode_grid(16000, 512,
                                                      ANR_MODE_BALANCED);
    AnrConfig target;
    Inst in;
    printf("-- pipeline overrides survive a reconfiguration --\n");
    cfg.broadband_threshold = 0.8f;
    cfg.L = anr_retime_frames(150, 16000, 256);
    cfg.alpha_decay = cfg.alpha_g;
    if (inst_open(&in, &cfg) != 0) { CHECK(0, "pipeline instance created"); return; }
    inst_run(&in, 40, 0x99u);

    /* The WRONG way: the canonical convenience wrapper. Its L is the preset's,
     * not the pipeline's, so it must refuse rather than silently revert. */
    CHECK(anr_set_mode(in.d, ANR_MODE_AGGRESSIVE) == -1,
          "set_mode REFUSES a pipeline-shaped instance instead of silently "
          "reverting its overrides");

    /* The right way: rebuild the pipeline's own composition. */
    target = anr_config_for_mode_grid(16000, 512, ANR_MODE_AGGRESSIVE);
    target.broadband_threshold = 0.8f;
    target.L = cfg.L;
    target.alpha_decay = target.alpha_g;
    CHECK(anr_reconfigure(in.d, &target) == 0,
          "reconfigure accepts the pipeline's own recomposed target");
    CHECK(anr_get_hop_size(in.d) == cfg.hop_size,
          "the grid is unchanged by the switch");
    inst_close(&in);
}

/* ── 7: the pool byte count never moves ────────────────────────────────── */

static void check_pool_size_is_unchanged(void) {
    int g, m;
    static const AnrMode MODES[] = {
        ANR_MODE_MILD, ANR_MODE_MODERATE,
        ANR_MODE_BALANCED, ANR_MODE_AGGRESSIVE,
    };
    printf("-- pool size is identical across all four strengths --\n");
    for (g = 0; g < N_GRIDS; ++g) {
        size_t first = 0;
        int same = 1;
        for (m = 0; m < 4; ++m) {
            AnrConfig cfg = anr_config_for_mode_grid(
                GRIDS[g].sr, GRIDS[g].fft, MODES[m]);
            size_t n = anr_get_mem_size(&cfg);
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

/* The frame speech gate follows q: config value + (q - anchor). Balanced is
 * the anchor and must reproduce the authored value bit for bit; the other
 * presets and a runtime reconfigure land on the same float32 sum. */
static void check_frame_gate_follows_q(void) {
    AnrConfig bal = anr_config_for_mode_grid(16000, 512, ANR_MODE_BALANCED);
    AnrConfig mild = anr_config_for_mode_grid(16000, 512, ANR_MODE_MILD);
    AnrConfig aggr = anr_config_for_mode_grid(16000, 512, ANR_MODE_AGGRESSIVE);
    AnrDenoiser* d = anr_create(&bal);
    AnrDenoiser* m = anr_create(&mild);
    float want_mild = mild.speech_protect_frame_threshold + (mild.q - ANR_SPEECH_PROTECT_ANCHOR_Q);
    float want_aggr = aggr.speech_protect_frame_threshold + (aggr.q - ANR_SPEECH_PROTECT_ANCHOR_Q);
    if (!d || !m) { CHECK(0, "frame gate: allocation"); goto out; }
    CHECK(bal.q == ANR_SPEECH_PROTECT_ANCHOR_Q, "balanced q is the gate anchor");
    CHECK(anr_get_speech_protect_frame_threshold(d) == bal.speech_protect_frame_threshold,
          "balanced: effective gate == authored value bit for bit");
    CHECK(anr_get_speech_protect_frame_threshold(m) == want_mild &&
          want_mild > bal.speech_protect_frame_threshold,
          "mild: gate = value + (q - anchor), above balanced");
    CHECK(anr_reconfigure(d, &aggr) == 0 &&
          anr_get_speech_protect_frame_threshold(d) == want_aggr &&
          want_aggr < bal.speech_protect_frame_threshold,
          "reconfigure to aggressive moves the gate with q, below balanced");
out:
    anr_destroy(d); anr_destroy(m);
}

int main(void) {
    check_self_reconfigure_is_noop();
    check_state_is_preserved();
    check_state_clearing_is_observable();
    check_refusal_is_total();
    check_pipeline_overrides_survive();
    check_pool_size_is_unchanged();
    check_frame_gate_follows_q();

    if (g_failures == 0) printf("\nALL CHECKS PASSED\n");
    else fprintf(stderr, "\n%d CHECK(S) FAILED\n", g_failures);
    return g_failures;
}
