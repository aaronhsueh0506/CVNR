/* Validate config ranges, overflow guards, pool alignment and gain APIs.
 * All shipped presets must pass; invalid inputs must leave pools intact.
 * Returns the failure count. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <limits.h>
#include <stdint.h>

#include "anr.h"
#include "anr_types.h"
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
static void expect_config_rejected(const AnrConfig* cfg, const char* label,
                                    void* big_aligned_buf, size_t big_buf_size) {
    char msg[256];

    size_t need = anr_get_mem_size(cfg);
    snprintf(msg, sizeof msg, "%s: get_mem_size() == 0", label);
    CHECK(need == 0, msg);

    AnrDenoiser* heap = anr_create(cfg);
    snprintf(msg, sizeof msg, "%s: create() == NULL", label);
    CHECK(heap == NULL, msg);
    if (heap) anr_destroy(heap);

    AnrDenoiser* stat = anr_init(big_aligned_buf, big_buf_size, cfg);
    snprintf(msg, sizeof msg, "%s: init() == NULL", label);
    CHECK(stat == NULL, msg);
}

int main(void) {
    printf("=== NR config validation / alignment guard tests ===\n\n");

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
            AnrConfig cfg = anr_default_config(bad_rates[i]);
            expect_config_rejected(&cfg, labels[i], big_buf, BIG_BUF);
        }

        int good_rates[] = { 8000, 16000, 48000 };
        for (size_t i = 0; i < sizeof(good_rates) / sizeof(good_rates[0]); i++) {
            AnrConfig cfg = anr_default_config(good_rates[i]);
            char msg[64];
            snprintf(msg, sizeof msg, "sr=%d: validate_config() accepts", good_rates[i]);
            CHECK(anr_validate_config(&cfg), msg);
            snprintf(msg, sizeof msg, "sr=%d: get_mem_size() > 0", good_rates[i]);
            CHECK(anr_get_mem_size(&cfg) > 0, msg);
        }
    }
    printf("\n");

    /* ---- 2. Framing consistency + L / num_init_frames bounds ---------- */
    printf("-- framing / L / num_init_frames bounds --\n");
    {
        AnrConfig cfg;

        cfg = anr_default_config(16000);
        cfg.fft_size = 300;  /* not a power of two */
        expect_config_rejected(&cfg, "fft_size not pow2", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.fft_size = 16384;  /* > 8192 cap */
        expect_config_rejected(&cfg, "fft_size too large", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.frame_size = cfg.fft_size + 1;  /* frame > fft */
        expect_config_rejected(&cfg, "frame_size > fft_size", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.hop_size = cfg.frame_size + 1;  /* hop > frame */
        expect_config_rejected(&cfg, "hop_size > frame_size", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.L = -1;
        expect_config_rejected(&cfg, "L negative", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.L = 100000;
        expect_config_rejected(&cfg, "L huge", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.num_init_frames = 0;
        expect_config_rejected(&cfg, "num_init_frames zero", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.num_init_frames = INT_MAX;
        expect_config_rejected(&cfg, "num_init_frames huge (INT_MAX)", big_buf, BIG_BUF);
    }
    printf("\n");

    /* Reject nonfinite/out-of-range tunables; validate every shipped preset. */
    printf("-- float tunable validation (R08) --\n");
    {
        AnrConfig cfg;

        /* (a) NaN / Inf, one representative field per struct section. */
        cfg = anr_default_config(16000); cfg.alpha_xi = NAN;
        expect_config_rejected(&cfg, "alpha_xi = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.q = INFINITY;
        expect_config_rejected(&cfg, "q = +Inf", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.xi_min_db = -INFINITY;
        expect_config_rejected(&cfg, "xi_min_db = -Inf", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.cross_band_speech_prior_max_q = NAN;
        expect_config_rejected(&cfg, "cross_band_speech_prior_max_q = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.cross_band_speech_prior_alpha = INFINITY;
        expect_config_rejected(&cfg, "cross_band_speech_prior_alpha = +Inf", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.noise_over_subtraction = NAN;
        expect_config_rejected(&cfg, "noise_over_subtraction = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.speech_protect_floor_db = NAN;
        expect_config_rejected(&cfg, "speech_protect_floor_db = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.speech_protect_threshold = INFINITY;
        expect_config_rejected(&cfg, "speech_protect_threshold = +Inf", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.speech_protect_frame_threshold = NAN;
        expect_config_rejected(&cfg, "speech_protect_frame_threshold = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.alpha_d = NAN;
        expect_config_rejected(&cfg, "alpha_d (noise update) = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.scene_change_blend = INFINITY;
        expect_config_rejected(&cfg, "scene_change_blend = +Inf", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.g_min_db = NAN;
        expect_config_rejected(&cfg, "g_min_db (gain) = NaN", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.alpha_g = INFINITY;
        expect_config_rejected(&cfg, "alpha_g = +Inf", big_buf, BIG_BUF);

        /* (b) Concrete out-of-range values. */
        cfg = anr_default_config(16000); cfg.q = 0.0f;
        expect_config_rejected(&cfg, "q = 0 (degenerate probability)", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.q = 1.5f;
        expect_config_rejected(&cfg, "q = 1.5 (> 1)", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.alpha_xi = -0.1f;
        expect_config_rejected(&cfg, "alpha_xi = -0.1 (negative)", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.alpha_xi = 1.5f;
        expect_config_rejected(&cfg, "alpha_xi = 1.5 (> 1)", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.cross_band_speech_prior = true;
        cfg.cross_band_speech_prior_max_q = cfg.q - 0.01f;
        expect_config_rejected(&cfg, "enabled cross-band max_q below q", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.cross_band_speech_prior_alpha = 1.0f;
        expect_config_rejected(&cfg, "cross_band_speech_prior_alpha = 1", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.noise_over_subtraction = 0.99f;
        expect_config_rejected(&cfg, "noise_over_subtraction below 1", big_buf, BIG_BUF);

        cfg = anr_default_config(16000);
        cfg.speech_protect_floor = true;
        cfg.speech_protect_floor_db = cfg.g_min_db - 1.0f;
        expect_config_rejected(&cfg, "enabled speech floor below g_min", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.speech_protect_threshold = 1.1f;
        expect_config_rejected(&cfg, "speech_protect_threshold above 1", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.speech_protect_frame_threshold = -0.1f;
        expect_config_rejected(&cfg, "speech_protect_frame_threshold below 0", big_buf, BIG_BUF);

        cfg = anr_default_config(16000); cfg.g_min_db = -200.0f;
        expect_config_rejected(&cfg, "g_min_db = -200 (out of range)", big_buf, BIG_BUF);

        /* (c) Every shipped config must validate, across every
         * supported sample rate: all four strength presets and the bare default. */
        AnrMode modes[] = { ANR_MODE_MILD, ANR_MODE_MODERATE,
                                   ANR_MODE_BALANCED, ANR_MODE_AGGRESSIVE };
        const char* mode_names[] = { "mild", "moderate", "balanced", "aggressive" };
        int sample_rates[] = { 8000, 16000, 48000 };

        for (size_t r = 0; r < sizeof(sample_rates) / sizeof(sample_rates[0]); r++) {
            for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
                char msg[96];
                AnrConfig preset = anr_config_for_mode(sample_rates[r], modes[i]);
                snprintf(msg, sizeof msg, "preset %s @ %dHz: validate_config() accepts",
                         mode_names[i], sample_rates[r]);
                CHECK(anr_validate_config(&preset), msg);
            }

            AnrConfig def = anr_default_config(sample_rates[r]);
            char msg[64];
            snprintf(msg, sizeof msg, "default @ %dHz: validate_config() accepts", sample_rates[r]);
            CHECK(anr_validate_config(&def), msg);

            anr_apply_speech_protection_experiment(&def);
            snprintf(msg, sizeof msg,
                     "speech-protection experiment @ %dHz: validate_config() accepts",
                     sample_rates[r]);
            CHECK(anr_validate_config(&def), msg);

            anr_apply_cross_band_speech_experiment(&def);
            snprintf(msg, sizeof msg,
                     "cross-band experiment @ %dHz: validate_config() accepts",
                     sample_rates[r]);
            CHECK(anr_validate_config(&def), msg);
        }

        /* Every supported grid keeps the preset wall-clock constants. */
        {
            const int grid_sr[] = {8000, 8000, 16000, 16000, 48000};
            const int grid_fft[] = {128, 256, 256, 512, 1024};
            for (size_t g = 0; g < sizeof(grid_sr) / sizeof(grid_sr[0]); ++g) {
                AnrConfig cfg = anr_config_for_mode_grid(
                    grid_sr[g], grid_fft[g], ANR_MODE_BALANCED);
                char msg[128];
                snprintf(msg, sizeof msg, "grid %d/%d: retimed config validates",
                         grid_sr[g], grid_fft[g]);
                CHECK(anr_validate_config(&cfg), msg);

                double hop_sec = (double)cfg.hop_size / (double)cfg.sample_rate;
                double min_window_sec = (double)cfg.L * hop_sec;
                double init_sec = (double)cfg.num_init_frames * hop_sec;
                double scene_sec = (double)cfg.scene_change_min_frames * hop_sec;
                /* Retiming preserves the 512 ms minimum-tracking window. */
                snprintf(msg, sizeof msg, "grid %d/%d: L preserves >=512ms",
                         grid_sr[g], grid_fft[g]);
                CHECK(min_window_sec >= 0.512 - 1e-9 &&
                      min_window_sec < 0.512 + hop_sec + 1e-9, msg);
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

        /* A caller overlay on each preset (L = 150 frames at 10 ms retimed, alpha_d 0.95,
         * alpha_attack 0.3, alpha_decay = alpha_g) must also validate. */
        for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); i++) {
            AnrConfig aec_chain = anr_config_for_mode(16000, modes[i]);
            aec_chain.L = anr_retime_frames(
                150, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_d = anr_retime_alpha(
                0.95f, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_attack = anr_retime_alpha(
                0.3f, aec_chain.sample_rate, aec_chain.hop_size);
            aec_chain.alpha_decay  = aec_chain.alpha_g;
            char msg[96];
            snprintf(msg, sizeof msg, "AEC-chain overlay (%s): validate_config() accepts",
                     mode_names[i]);
            CHECK(anr_validate_config(&aec_chain), msg);
        }
    }
    printf("\n");

    /* ---- 4. Alignment guard: misaligned base rejected, zero writes ---- */
    printf("-- alignment guard (anr_init) --\n");
    {
        AnrConfig cfg = anr_default_config(16000);
        size_t need = anr_get_mem_size(&cfg);
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

                AnrDenoiser* d = anr_init(misaligned, avail, &cfg);
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
            AnrDenoiser* d0 = anr_init(pad_buf, need, &cfg);
            CHECK(d0 != NULL, "offset +0 (aligned): init() succeeds");
            if (d0) anr_destroy(d0);

            free(pad_buf);
        }
    }
    printf("\n");

    /* ---- 5. Valid 16k config end-to-end: denoise 1s of synthetic noise - */
    printf("-- end-to-end denoise (valid 16kHz config) --\n");
    {
        AnrConfig cfg = anr_default_config(16000);
        AnrDenoiser* d = anr_create(&cfg);
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
                if (anr_process(d, spec_in, spec_out) < 0) { process_ok = 0; break; }
                fft_inverse(fft, spec_out, time_out);

                for (int n = 0; n < frame_size; n++) {
                    out_ola[start + n] += time_out[n] * win[n];
                }
            }
            CHECK(process_ok, "anr_process() succeeds on every frame");

            int all_finite = 1;
            for (int i = 0; i < out_len; i++) {
                if (!isfinite(out_ola[i])) { all_finite = 0; break; }
            }
            CHECK(all_finite, "denoised output is finite (no NaN/Inf)");
            CHECK(out_ola != NULL && out_len > 0, "denoised output is non-NULL / non-empty");

            free(signal); free(out_ola); free(win); free(frame_buf); free(time_out);
            free(spec_in); free(spec_out);
        }

        if (d) anr_destroy(d);
        if (fft) fft_destroy(fft);
    }
    printf("\n");

    /* ---- 6. anr_process_gain(..., NULL) matches a non-NULL call --- */
    printf("-- gain_out==NULL matches anr_get_gain() (Group 3) --\n");
    {
        AnrConfig cfg = anr_default_config(16000);
        AnrDenoiser* with_copy = anr_create(&cfg);
        AnrDenoiser* no_copy   = anr_create(&cfg);
        CHECK(with_copy != NULL && no_copy != NULL,
              "create() succeeds for both gain-borrow test instances");

        if (with_copy && no_copy) {
            int n_freqs = anr_get_n_freqs(with_copy);
            Complex* spec  = (Complex*)malloc((size_t)n_freqs * sizeof(Complex));
            float* extra   = (float*)malloc((size_t)n_freqs * sizeof(float));
            float* gain_out = (float*)malloc((size_t)n_freqs * sizeof(float));
            unsigned seed = 987654321u;
            int gain_ok = 1;
            int rc_ok = 1;

            for (int frame = 0; frame < 40 && spec && extra && gain_out;
                 ++frame) {
                for (int k = 0; k < n_freqs; ++k) {
                    seed = seed * 1103515245u + 12345u;
                    float r = ((float)((seed >> 8) & 0xFFFFu) / 65535.0f);
                    spec[k].r = (r - 0.5f) * 0.2f;
                    seed = seed * 1103515245u + 12345u;
                    float i = ((float)((seed >> 8) & 0xFFFFu) / 65535.0f);
                    spec[k].i = (i - 0.5f) * 0.2f;
                    extra[k] = r * r * 1e-4f;
                }
                /* Exercise both the extra_noise_psd==NULL and non-NULL
                 * branches across the run, identically on both instances. */
                const float* extra_arg = (frame % 2 == 0) ? extra : NULL;

                if (anr_process_gain(with_copy, spec, extra_arg,
                                          gain_out) < 0) rc_ok = 0;
                if (anr_process_gain(no_copy, spec, extra_arg,
                                          NULL) < 0) rc_ok = 0;
                if (!rc_ok) break;

                int nf_check = -1;
                const float* borrowed = anr_get_gain(no_copy, &nf_check);
                if (!borrowed || nf_check != n_freqs ||
                    memcmp(borrowed, gain_out,
                           (size_t)n_freqs * sizeof(float)) != 0) {
                    gain_ok = 0;
                    break;
                }
            }
            CHECK(rc_ok, "anr_process_gain(..., NULL) does not fail");
            CHECK(gain_ok,
                  "anr_process_gain(..., NULL)'s internal gain, read "
                  "via anr_get_gain(), is byte-identical every frame "
                  "to what a non-NULL call would have copied out");

            free(spec); free(extra); free(gain_out);
        }
        if (with_copy) anr_destroy(with_copy);
        if (no_copy) anr_destroy(no_copy);
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
