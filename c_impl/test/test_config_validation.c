/**
 * test_config_validation.c - Negative + positive tests for the F05/F07/R08
 * config-validation and static-memory alignment-guard remediation.
 *
 * F05: mmse_lsa_get_mem_size()/create()/init() (and the MCRA/SPP sub-module
 *      get_mem_size routines) must reject an invalid or adversarial config
 *      (bad sample_rate, negative or huge fft_size/L/num_init_frames,
 *      inconsistent frame/hop/fft framing) instead of overflowing the
 *      size-arithmetic into a wrapped/undersized byte count.
 * F07: mmse_lsa_init() (and mcra_init/spp_init) must reject a mis-aligned
 *      pool base BEFORE writing a single byte into it.
 * R08 (external re-review, NR side): mmse_lsa_validate_config() checked
 *      sample_rate + int dims only -- none of the 18 float tunables (SPP/
 *      MCRA/scene-change/gain/stationary-overlay knobs) were validated at
 *      all, so a NaN/Inf/sign-flipped/absurd-magnitude float could still
 *      reach the denoiser's arithmetic. See section 3 below.
 *
 * Standalone runner (no external test framework): each check is a plain
 * assertion; a failure prints to stderr and bumps a counter. main() returns
 * the failure count (0 == all passed), so `make test-config` fails loudly the
 * moment any check regresses.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <limits.h>
#include <stdint.h>

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "fft_wrapper.h"   /* Complex, fft_create/forward/inverse, mem_align.h */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static int g_failures = 0;

#define CHECK(cond, msg)                                                    \
    do {                                                                    \
        if (!(cond)) {                                                     \
            fprintf(stderr, "FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__); \
            g_failures++;                                                   \
        } else {                                                            \
            printf("  ok: %s\n", (msg));                                    \
        }                                                                   \
    } while (0)

/* Assert a config is rejected by all three entry points: get_mem_size() == 0,
 * create() == NULL, and init() == NULL (against a generic oversized aligned
 * scratch buffer — invalid configs never get far enough to need their "real"
 * size, since get_mem_size() itself returns 0 for them). */
static void expect_config_rejected(const MmseLsaConfig* cfg, const char* label,
                                    void* big_aligned_buf, size_t big_buf_size) {
    char msg[256];

    size_t need = mmse_lsa_get_mem_size(cfg);
    snprintf(msg, sizeof msg, "%s: get_mem_size() == 0", label);
    CHECK(need == 0, msg);

    MmseLsaDenoiser* heap = mmse_lsa_create(cfg);
    snprintf(msg, sizeof msg, "%s: create() == NULL", label);
    CHECK(heap == NULL, msg);
    if (heap) mmse_lsa_destroy(heap);

    MmseLsaDenoiser* stat = mmse_lsa_init(big_aligned_buf, big_buf_size, cfg);
    snprintf(msg, sizeof msg, "%s: init() == NULL", label);
    CHECK(stat == NULL, msg);
}

int main(void) {
    printf("=== NR config validation / alignment guard tests (F05/F07) ===\n\n");

    /* Generic oversized, 16-aligned scratch buffer reused by every rejection
     * check below. */
    enum { BIG_BUF = 1 << 20 };  /* 1 MiB */
    void* big_buf = NULL;
    if (posix_memalign(&big_buf, 16, BIG_BUF) != 0 || !big_buf) {
        fprintf(stderr, "posix_memalign failed\n");
        return 1;
    }

    /* ---- 1. Sample-rate whitelist ------------------------------------- */
    printf("-- sample_rate whitelist --\n");
    {
        int bad_rates[] = { 0, -1, 44100, INT_MAX };
        const char* labels[] = { "sr=0", "sr=-1", "sr=44100", "sr=INT_MAX" };
        for (size_t i = 0; i < sizeof(bad_rates) / sizeof(bad_rates[0]); i++) {
            MmseLsaConfig cfg = mmse_lsa_default_config(bad_rates[i]);
            expect_config_rejected(&cfg, labels[i], big_buf, BIG_BUF);
        }

        int good_rates[] = { 8000, 16000, 48000 };
        for (size_t i = 0; i < sizeof(good_rates) / sizeof(good_rates[0]); i++) {
            MmseLsaConfig cfg = mmse_lsa_default_config(good_rates[i]);
            char msg[64];
            snprintf(msg, sizeof msg, "sr=%d: validate_config() accepts", good_rates[i]);
            CHECK(mmse_lsa_validate_config(&cfg), msg);
            snprintf(msg, sizeof msg, "sr=%d: get_mem_size() > 0", good_rates[i]);
            CHECK(mmse_lsa_get_mem_size(&cfg) > 0, msg);
        }
    }
    printf("\n");

    /* ---- 2. Framing consistency + L / num_init_frames bounds ---------- */
    printf("-- framing / L / num_init_frames bounds --\n");
    {
        MmseLsaConfig cfg;

        cfg = mmse_lsa_default_config(16000);
        cfg.fft_size = 300;  /* not a power of two */
        expect_config_rejected(&cfg, "fft_size not pow2", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.fft_size = 16384;  /* > 8192 cap */
        expect_config_rejected(&cfg, "fft_size too large", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.frame_size = cfg.fft_size + 1;  /* frame > fft */
        expect_config_rejected(&cfg, "frame_size > fft_size", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.hop_size = cfg.frame_size + 1;  /* hop > frame */
        expect_config_rejected(&cfg, "hop_size > frame_size", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.L = -1;
        expect_config_rejected(&cfg, "L negative", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.L = 100000;
        expect_config_rejected(&cfg, "L huge", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.num_init_frames = 0;
        expect_config_rejected(&cfg, "num_init_frames zero", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000);
        cfg.num_init_frames = INT_MAX;
        expect_config_rejected(&cfg, "num_init_frames huge (INT_MAX)", big_buf, BIG_BUF);
    }
    printf("\n");

    /* ---- 3. Float tunable validation (R08, external re-review, NR side) --
     * mmse_lsa_validate_config() used to check sample_rate + int dims only;
     * none of the 18 float tunables (SPP/MCRA/scene-change/gain/stationary-
     * overlay knobs) were validated at all. This section checks: (a) NaN/Inf
     * in a representative spread of fields (one per struct section) are all
     * rejected; (b) a few concrete garbage values called out in the
     * remediation ask (degenerate q, out-of-range alpha_xi, absurd g_min_db,
     * non-positive/zero stationary-floor beta/exponent) are rejected; and
     * (c) every shipped config -- all four strength presets, each with the
     * stationary content-preservation overlay layered on top, the bare
     * default, and the AEC-chain caller's (Audio_ALG audio_pipeline.c
     * derive_dims_and_configs()) L/alpha_d/alpha_attack/alpha_decay overlay
     * -- across every supported sample rate, still validates. Rejecting
     * garbage must never reject anything shipped (byte-neutral). --------- */
    printf("-- float tunable validation (R08) --\n");
    {
        MmseLsaConfig cfg;

        /* (a) NaN / Inf, one representative field per struct section. */
        cfg = mmse_lsa_default_config(16000); cfg.alpha_xi = NAN;
        expect_config_rejected(&cfg, "alpha_xi = NaN", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.q = INFINITY;
        expect_config_rejected(&cfg, "q = +Inf", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.xi_min_db = -INFINITY;
        expect_config_rejected(&cfg, "xi_min_db = -Inf", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.alpha_d = NAN;
        expect_config_rejected(&cfg, "alpha_d (MCRA) = NaN", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.scene_change_blend = INFINITY;
        expect_config_rejected(&cfg, "scene_change_blend = +Inf", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.g_min_db = NAN;
        expect_config_rejected(&cfg, "g_min_db (gain) = NaN", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.alpha_g = INFINITY;
        expect_config_rejected(&cfg, "alpha_g = +Inf", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.stationary_floor_exponent = NAN;
        expect_config_rejected(&cfg, "stationary_floor_exponent = NaN", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.stationary_floor_beta = INFINITY;
        expect_config_rejected(&cfg, "stationary_floor_beta = +Inf", big_buf, BIG_BUF);

        /* (b) Concrete garbage values from the remediation ask. */
        cfg = mmse_lsa_default_config(16000); cfg.q = 0.0f;
        expect_config_rejected(&cfg, "q = 0 (degenerate probability)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.q = 1.5f;
        expect_config_rejected(&cfg, "q = 1.5 (> 1)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.alpha_xi = -0.1f;
        expect_config_rejected(&cfg, "alpha_xi = -0.1 (negative)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.alpha_xi = 1.5f;
        expect_config_rejected(&cfg, "alpha_xi = 1.5 (> 1)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.g_min_db = -200.0f;
        expect_config_rejected(&cfg, "g_min_db = -200 (out of range)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.stationary_floor_beta = 0.0f;
        expect_config_rejected(&cfg, "stationary_floor_beta = 0 (non-positive)", big_buf, BIG_BUF);

        cfg = mmse_lsa_default_config(16000); cfg.stationary_floor_exponent = 0.0f;
        expect_config_rejected(&cfg, "stationary_floor_exponent = 0 (below 0.5 floor)", big_buf, BIG_BUF);

        /* (c) Every shipped config must still validate, across every
         * supported sample rate: all four strength presets, each with the
         * stationary overlay on top, and the bare default. */
        MmseLsaNrMode modes[] = { MMSE_LSA_NR_MILD, MMSE_LSA_NR_MODERATE,
                                   MMSE_LSA_NR_BALANCED, MMSE_LSA_NR_AGGRESSIVE };
        const char* mode_names[] = { "mild", "moderate", "balanced", "aggressive" };
        int sample_rates[] = { 8000, 16000, 48000 };

        for (size_t r = 0; r < sizeof(sample_rates) / sizeof(sample_rates[0]); r++) {
            for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
                char msg[96];
                MmseLsaConfig preset = mmse_lsa_config_for_mode(sample_rates[r], modes[i]);
                snprintf(msg, sizeof msg, "preset %s @ %dHz: validate_config() accepts",
                         mode_names[i], sample_rates[r]);
                CHECK(mmse_lsa_validate_config(&preset), msg);

                MmseLsaConfig preset_st = preset;
                mmse_lsa_apply_stationary(&preset_st);
                snprintf(msg, sizeof msg, "preset %s+stationary @ %dHz: validate_config() accepts",
                         mode_names[i], sample_rates[r]);
                CHECK(mmse_lsa_validate_config(&preset_st), msg);
            }

            MmseLsaConfig def = mmse_lsa_default_config(sample_rates[r]);
            char msg[64];
            snprintf(msg, sizeof msg, "default @ %dHz: validate_config() accepts", sample_rates[r]);
            CHECK(mmse_lsa_validate_config(&def), msg);
        }

        /* The alternate 16-kHz/256 grid must preserve preset wall-clock
         * constants too; mutating only fft/frame/hop after construction is
         * intentionally no longer the supported construction path. */
        {
            const int grid_sr[] = {8000, 16000, 16000, 48000};
            const int grid_fft[] = {256, 256, 512, 1024};
            for (size_t g = 0; g < sizeof(grid_sr) / sizeof(grid_sr[0]); ++g) {
                MmseLsaConfig cfg = mmse_lsa_config_for_mode_grid(
                    grid_sr[g], grid_fft[g], MMSE_LSA_NR_BALANCED);
                char msg[128];
                snprintf(msg, sizeof msg, "grid %d/%d: retimed config validates",
                         grid_sr[g], grid_fft[g]);
                CHECK(mmse_lsa_validate_config(&cfg), msg);

                double hop_sec = (double)cfg.hop_size / (double)cfg.sample_rate;
                double min_window_sec = (double)cfg.L * hop_sec;
                double init_sec = (double)cfg.num_init_frames * hop_sec;
                double scene_sec = (double)cfg.scene_change_min_frames * hop_sec;
                snprintf(msg, sizeof msg, "grid %d/%d: L preserves >=320ms",
                         grid_sr[g], grid_fft[g]);
                CHECK(min_window_sec >= 0.320 - 1e-9 &&
                      min_window_sec < 0.320 + hop_sec + 1e-9, msg);
                snprintf(msg, sizeof msg, "grid %d/%d: init preserves >=200ms",
                         grid_sr[g], grid_fft[g]);
                CHECK(init_sec >= 0.200 - 1e-9 &&
                      init_sec < 0.200 + hop_sec + 1e-9, msg);
                snprintf(msg, sizeof msg, "grid %d/%d: scene gate preserves >=50ms",
                         grid_sr[g], grid_fft[g]);
                CHECK(scene_sec >= 0.050 - 1e-9 &&
                      scene_sec < 0.050 + hop_sec + 1e-9, msg);

                double decay_1s = pow((double)cfg.alpha_s,
                                      1.0 / hop_sec);
                snprintf(msg, sizeof msg, "grid %d/%d: alpha_s keeps 1s decay",
                         grid_sr[g], grid_fft[g]);
                CHECK(fabs(decay_1s - pow(0.95, 100.0)) < 2e-6, msg);
            }
        }

        /* AEC-chain caller overlay (Audio_ALG pipelines' audio_pipeline.c
         * derive_dims_and_configs(): L=150, alpha_d=0.95, alpha_attack=0.3,
         * alpha_decay=alpha_g) must also validate for every strength preset. */
        for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
            MmseLsaConfig aec_chain = mmse_lsa_config_for_mode(16000, modes[i]);
            aec_chain.L = mmse_lsa_retime_frames(
                150, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_d = mmse_lsa_retime_alpha(
                0.95f, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_attack = mmse_lsa_retime_alpha(
                0.3f, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_decay  = aec_chain.alpha_g;
            char msg[96];
            snprintf(msg, sizeof msg, "AEC-chain overlay (%s): validate_config() accepts",
                     mode_names[i]);
            CHECK(mmse_lsa_validate_config(&aec_chain), msg);
        }
    }
    printf("\n");

    /* ---- 4. Alignment guard: misaligned base rejected, zero writes ---- */
    printf("-- alignment guard (mmse_lsa_init) --\n");
    {
        MmseLsaConfig cfg = mmse_lsa_default_config(16000);
        size_t need = mmse_lsa_get_mem_size(&cfg);
        CHECK(need > 0, "valid 16k config sizes > 0");

        size_t pad_buf_size = need + 16;
        uint8_t* pad_buf = NULL;
        if (posix_memalign((void**)&pad_buf, 16, pad_buf_size) != 0 || !pad_buf) {
            fprintf(stderr, "posix_memalign failed (pad buffer)\n");
            g_failures++;
        } else {
            for (int off = 1; off < 16; off++) {
                memset(pad_buf, 0xA5, pad_buf_size);
                void*  misaligned = (void*)(pad_buf + off);
                size_t avail      = pad_buf_size - (size_t)off;

                MmseLsaDenoiser* d = mmse_lsa_init(misaligned, avail, &cfg);
                char msg[64];
                snprintf(msg, sizeof msg, "offset +%d: init() == NULL", off);
                CHECK(d == NULL, msg);

                int untouched = 1;
                for (size_t i = 0; i < pad_buf_size; i++) {
                    if (pad_buf[i] != (uint8_t)0xA5) { untouched = 0; break; }
                }
                snprintf(msg, sizeof msg, "offset +%d: buffer untouched (0xA5 intact)", off);
                CHECK(untouched, msg);
            }

            /* Control: offset 0 (properly aligned, properly sized) must
             * succeed — proves the rejections above are about alignment,
             * not some other defect in the buffer/config. */
            MmseLsaDenoiser* d0 = mmse_lsa_init(pad_buf, need, &cfg);
            CHECK(d0 != NULL, "offset +0 (aligned): init() succeeds");
            if (d0) mmse_lsa_destroy(d0);

            free(pad_buf);
        }
    }
    printf("\n");

    /* ---- 5. Valid 16k config end-to-end: denoise 1s of synthetic noise - */
    printf("-- end-to-end denoise (valid 16kHz config) --\n");
    {
        MmseLsaConfig cfg = mmse_lsa_default_config(16000);
        MmseLsaDenoiser* d = mmse_lsa_create(&cfg);
        CHECK(d != NULL, "create() succeeds for valid 16k config");

        FftHandle* fft = fft_create(cfg.fft_size);
        CHECK(fft != NULL, "fft_create() succeeds");

        if (d && fft) {
            int sample_rate = 16000;
            int n_samples   = sample_rate;  /* 1 second */
            int frame_size  = cfg.frame_size;
            int hop         = cfg.hop_size;
            int fft_size    = cfg.fft_size;
            int n_freqs     = fft_size / 2 + 1;

            float* signal = (float*)malloc((size_t)n_samples * sizeof(float));
            unsigned seed = 12345u;
            for (int i = 0; i < n_samples; i++) {
                seed = seed * 1103515245u + 12345u;
                float r = ((float)((seed >> 8) & 0xFFFFu) / 65535.0f) * 2.0f - 1.0f;
                signal[i] = 0.1f * r;  /* synthetic white noise */
            }

            int n_frames = (n_samples <= frame_size)
                         ? 1
                         : (n_samples - frame_size + hop - 1) / hop + 1;
            int out_len = (n_frames - 1) * hop + frame_size;

            float*   out_ola  = (float*)calloc((size_t)out_len, sizeof(float));
            float*   win       = (float*)malloc((size_t)frame_size * sizeof(float));
            float*   frame_buf = (float*)malloc((size_t)fft_size * sizeof(float));
            float*   time_out  = (float*)malloc((size_t)fft_size * sizeof(float));
            Complex* spec_in   = (Complex*)malloc((size_t)n_freqs * sizeof(Complex));
            Complex* spec_out  = (Complex*)malloc((size_t)n_freqs * sizeof(Complex));

            for (int n = 0; n < frame_size; n++) {
                double h = 0.5 - 0.5 * cos(2.0 * M_PI * n / frame_size);
                win[n] = (float)sqrt(h);
            }

            int process_ok = 1;
            for (int f = 0; f < n_frames; f++) {
                int start = f * hop;
                for (int n = 0; n < frame_size; n++) {
                    int idx = start + n;
                    float s = (idx < n_samples) ? signal[idx] : 0.0f;
                    frame_buf[n] = s * win[n];
                }
                for (int n = frame_size; n < fft_size; n++) frame_buf[n] = 0.0f;

                fft_forward(fft, frame_buf, spec_in);
                if (mmse_lsa_process(d, spec_in, spec_out) < 0) { process_ok = 0; break; }
                fft_inverse(fft, spec_out, time_out);

                for (int n = 0; n < frame_size; n++) {
                    out_ola[start + n] += time_out[n] * win[n];
                }
            }
            CHECK(process_ok, "mmse_lsa_process() succeeds on every frame");

            int all_finite = 1;
            for (int i = 0; i < out_len; i++) {
                if (!isfinite(out_ola[i])) { all_finite = 0; break; }
            }
            CHECK(all_finite, "denoised output is finite (no NaN/Inf)");
            CHECK(out_ola != NULL && out_len > 0, "denoised output is non-NULL / non-empty");

            free(signal); free(out_ola); free(win); free(frame_buf); free(time_out);
            free(spec_in); free(spec_out);
        }

        if (d) mmse_lsa_destroy(d);
        if (fft) fft_destroy(fft);
    }
    printf("\n");

    free(big_buf);

    if (g_failures == 0) {
        printf("ALL CHECKS PASSED\n");
        return 0;
    } else {
        printf("%d CHECK(S) FAILED\n", g_failures);
        return 1;
    }
}
