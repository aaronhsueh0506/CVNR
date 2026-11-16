/* Exact-zero (digital silence) frames carry no noise statistics:
 *  - they neither count toward initialization nor advance the tracker, so a stream that starts
 *    with silence initializes on the signal that follows and a converged floor survives a gap;
 *  - after five seconds of silence a stationary tone whose first frame is a partial onset frame
 *    reaches the same steady gain as the same tone without leading silence;
 *  - bins that are exactly zero for long enough to reach the inert floor, while the rest of the
 *    frame stays live, track the signal again when it returns (three grids, with and without the
 *    broadband gate);
 *  - bins that were zero for 1 to 10 s (the estimate has decayed but is above the inert floor)
 *    reach the gain of a stream without the gap within the frozen-bin run length plus the gain
 *    smoothing, because a bin whose power stays far above its estimate is reseeded;
 *  - that reseed needs an uninterrupted run, is not triggered below the power ratio, and leaves
 *    the other bins alone;
 *  - the first frame after initialization is not pushed to the gain floor by an a-priori SNR
 *    estimate that lacks the floor of later frames.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "anr.h"
#include "anr_types.h"
#include "noise_estimator.h"
#include "utility/simd_nr.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

/* Mean gain of the 1 kHz bin over the last second of a `tone_s`-second tone preceded by
 * `silence_s` seconds of exact-zero spectra. The first tone frame has amplitude
 * `onset` times the steady amplitude (a frame straddling the waveform onset). */
static double tone_gain(const AnrConfig* cfg, int sr, double silence_s, double tone_s, double onset) {
    AnrDenoiser* d = anr_create(cfg);
    int nf, hop, fft, bin, n_sil, n_tone, last, h;
    Complex* spec; const float* gain = NULL; double acc = 0.0;
    if (!d) return -1.0;
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d); fft = anr_get_frame_size(d);
    bin = (int)lrint(1000.0 * fft / sr);
    n_sil = (int)(silence_s * sr / hop); n_tone = (int)(tone_s * sr / hop); last = sr / hop;
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    for (h = 0; h < n_sil; ++h) { memset(spec, 0, (size_t)nf * sizeof(Complex)); gain = anr_process_gain(d, spec); }
    for (h = 0; h < n_tone; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        spec[bin].r = (float)(onset > 0.0 && h == 0 ? onset : 1.0) * 0.03f * 32768.0f * (float)(fft / 2);   /* -30 dBFS tone, int16-scale FFT */
        gain = anr_process_gain(d, spec);
        if (h >= n_tone - last) acc += gain[bin];
    }
    free(spec); anr_destroy(d);
    return acc / last;
}

static void run_case(const char* label, AnrConfig cfg, int sr, double onset) {
    double control = tone_gain(&cfg, sr, 0.0, 10.0, onset);
    double after = tone_gain(&cfg, sr, 5.0, 10.0, onset);
    printf("%-40s onset %.2f  control %.4f (%.1f dB)  after 5 s silence %.4f (%.1f dB)\n", label, onset,
           control, 20.0 * log10(control + 1e-12), after, 20.0 * log10(after + 1e-12));
    CHECK(control >= 0.0 && after >= 0.0, "%s: create failed", label);
    /* Above the speech guard, steady gain must stay within 4x the level floor. */
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
    Complex* spec; const float* gain = NULL; AnrDebugStatus before, after;
    if (!d) { CHECK(0, "%s: create failed", label); return; }
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d);
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    n_sil = (int)(5.0 * cfg.sample_rate / hop);

    for (h = 0; h < n_sil; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        gain = anr_process_gain(d, spec);
    }
    CHECK(!anr_is_initialized(d), "%s: silence counted toward noise initialization", label);
    for (k = 0, bad = 0; k < nf; ++k) bad += gain[k] != 1.0f;
    CHECK(bad == 0, "%s: %d of %d silent-frame gains differ from 1", label, bad, nf);

    n_noise = 3 * cfg.num_init_frames;
    for (h = 0; h < n_noise; ++h) {
        for (k = 0; k < nf; ++k) { spec[k].r = 400.0f + (float)((k * 7 + h * 3) % 11); spec[k].i = 0.0f; }
        gain = anr_process_gain(d, spec);
    }
    CHECK(anr_is_initialized(d), "%s: not initialized after %d signal frames", label, n_noise);
    anr_debug_status(d, &before);
    for (h = 0; h < n_sil; ++h) {
        memset(spec, 0, (size_t)nf * sizeof(Complex));
        gain = anr_process_gain(d, spec);
    }
    anr_debug_status(d, &after);
    printf("%-40s noise floor %.3f dB -> %.3f dB across 5 s silence\n", label, before.noise_floor_db, after.noise_floor_db);
    CHECK(before.noise_floor_db == after.noise_floor_db,
          "%s: silence moved the noise floor (%.4f -> %.4f dB)", label, before.noise_floor_db, after.noise_floor_db);
    free(spec); anr_destroy(d);
}

/* Mean gain of the upper half of the spectrum over the last second of a stationary signal that
 * follows `zero_s` seconds in which those bins are exactly zero while the lower half stays live
 * (not digital silence, so the tracker runs). The sparse spikes keep the upper half below the
 * scene-change flatness threshold, so the scene reset cannot mask the tracker. */
#define ZERO_GAP_S 20.0

static double half_zero_gain(const AnrConfig* cfg, double zero_s) {
    AnrDenoiser* d = anr_create(cfg);
    int nf, hop, hi, n_conv, n_zero, n_back, last, h, k;
    Complex* spec; const float* gain = NULL; double acc = 0.0;
    if (!d) return -1.0;
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d); hi = nf / 2;
    n_conv = 4 * cfg->num_init_frames; n_zero = (int)(zero_s * cfg->sample_rate / hop);
    n_back = (int)(10.0 * cfg->sample_rate / hop); last = cfg->sample_rate / hop;
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    for (h = 0; h < n_conv + n_zero + n_back; ++h) {
        int zeroed = h >= n_conv && h < n_conv + n_zero;
        for (k = 0; k < nf; ++k) {
            spec[k].r = (zeroed && k >= hi) ? 0.0f : (k % 16 == 0 ? 12000.0f : 400.0f) + (float)((k * 7 + h * 3) % 11);
            spec[k].i = 0.0f;
        }
        gain = anr_process_gain(d, spec);
        if (h >= n_conv + n_zero + n_back - last)
            for (k = hi; k < nf; ++k) acc += gain[k];
    }
    free(spec); anr_destroy(d);
    return acc / ((double)last * (nf - hi));
}

/* Zero bins decay by about 0.96 per hop; ZERO_GAP_S puts them below the inert floor on every
 * grid. They must then track the returning signal with the gain of a stream without the gap. */
static void run_zero_bins_case(const char* label, AnrConfig cfg) {
    double control = half_zero_gain(&cfg, 0.0);
    double after = half_zero_gain(&cfg, ZERO_GAP_S);
    printf("%-40s control %.4f  after %.0f s zero upper half %.4f\n", label, control, ZERO_GAP_S, after);
    CHECK(control >= 0.0 && after >= 0.0, "%s: create failed", label);
    CHECK(fabs(after - control) < 0.02, "%s: zeroed bins return at gain %.3f, control %.3f", label, after, control);
}


/* Seconds after the gap until the mean upper-half gain stays within 0.02 of `control`; -1 on a create failure or if it never does. */
static double zero_bins_settle_s(const AnrConfig* cfg, double zero_s, double control) {
    AnrDenoiser* d = anr_create(cfg);
    int nf, hop, hi, n_conv, n_zero, n_back, h, k, settle = -1;
    Complex* spec; const float* gain = NULL; double* mean;
    if (!d) return -1.0;
    nf = anr_get_n_freqs(d); hop = anr_get_hop_size(d); hi = nf / 2;
    n_conv = 4 * cfg->num_init_frames; n_zero = (int)(zero_s * cfg->sample_rate / hop);
    n_back = (int)(15.0 * cfg->sample_rate / hop);
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    mean = (double*)calloc((size_t)n_back, sizeof(double));
    for (h = 0; h < n_conv + n_zero + n_back; ++h) {
        int zeroed = h >= n_conv && h < n_conv + n_zero;
        for (k = 0; k < nf; ++k) {
            spec[k].r = (zeroed && k >= hi) ? 0.0f : (k % 16 == 0 ? 12000.0f : 400.0f) + (float)((k * 7 + h * 3) % 11);
            spec[k].i = 0.0f;
        }
        gain = anr_process_gain(d, spec);
        if (h >= n_conv + n_zero) {
            double acc = 0.0;
            for (k = hi; k < nf; ++k) acc += gain[k];
            mean[h - n_conv - n_zero] = acc / (nf - hi);
        }
    }
    for (h = n_back - 1; h >= 0; --h)
        if (fabs(mean[h] - control) >= 0.02) { settle = h + 1; break; }
    if (settle < 0) settle = 0;
    if (fabs(mean[n_back - 1] - control) >= 0.02) settle = -1;
    free(spec); free(mean); anr_destroy(d);
    return settle < 0 ? -1.0 : (double)settle * hop / cfg->sample_rate;
}

/* The reseed run is 2.048 s; the control gain itself needs about 0.2 s to fall from 1 to its steady value. */
#define FROZEN_SETTLE_EXTRA_S 0.3

static void run_frozen_gap_case(const char* label, AnrConfig cfg) {
    static const double gaps[5] = { 1.0, 3.0, 5.0, 8.0, 10.0 };
    int g;
    double control = half_zero_gain(&cfg, 0.0);
    double run_s = (double)anr_retime_frames_ms(NR_FROZEN_REF_FRAMES, cfg.sample_rate, cfg.hop_size, NR_FROZEN_REF_HOP_MS) * cfg.hop_size / cfg.sample_rate;
    for (g = 0; g < 5; ++g) {
        double t = zero_bins_settle_s(&cfg, gaps[g], control);
        printf("%-40s gap %4.1f s: gain settles %.3f s after return (run %.3f s)\n", label, gaps[g], t, run_s);
        CHECK(t >= 0.0, "%s: gap %.0f s: zeroed bins never return to the control gain", label, gaps[g]);
        CHECK(t <= run_s + FROZEN_SETTLE_EXTRA_S, "%s: gap %.0f s: settles after %.3f s, limit %.3f s", label, gaps[g], t, run_s + FROZEN_SETTLE_EXTRA_S);
    }
}

/* Estimator level, posterior 1 (the estimate cannot move by itself): after the hops of `pattern`, the estimate of
 * bin 0 (every 8th bin has `high` times the level in an 'H' hop; 'L' is a hop at the level) and of bin 1 (untouched). */
#define FZ_N_FREQS 257
#define FZ_LEVEL 1000.0f
static void frozen_pattern(float high, const char* pattern, float* spiked, float* other) {
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    NoiseEstimator* est = noise_estimator_create(FZ_N_FREQS, &cfg);
    float power[FZ_N_FREQS], spp[FZ_N_FREQS];
    int f, k;
    *spiked = *other = -1.0f;
    if (!est) return;
    for (k = 0; k < FZ_N_FREQS; ++k) { power[k] = FZ_LEVEL; spp[k] = 1.0f; }
    for (f = 0; f < cfg.num_init_frames; ++f) noise_estimator_accumulate_init_power(est, power, f);
    noise_estimator_init_noise(est, cfg.num_init_frames);
    for (; *pattern; ++pattern) {
        for (k = 0; k < FZ_N_FREQS; ++k) power[k] = (*pattern == 'H' && k % 8 == 0) ? high * FZ_LEVEL : FZ_LEVEL;
        noise_estimator_update_ex(est, power, spp, false, 0, 0.0f);
    }
    *spiked = noise_estimator_get_noise_psd(est)[0];
    *other = noise_estimator_get_noise_psd(est)[1];
    noise_estimator_destroy(est);
}

static void repeat_into(char* dst, char c, int n) { memset(dst, c, (size_t)n); dst[n] = 0; }

static void run_frozen_run_case(void) {
    AnrConfig cfg = anr_default_config_for_grid(16000, 512);
    int run = anr_retime_frames_ms(NR_FROZEN_REF_FRAMES, cfg.sample_rate, cfg.hop_size, NR_FROZEN_REF_HOP_MS);
    char pat[1024], pat2[1024];
    float spiked, other, below = SKR_FROZEN_POWER_RATIO * 0.9f, above = SKR_FROZEN_POWER_RATIO * 1.1f;
    CHECK(run > 2 && run < 400, "run length %d is out of the expected range", run);
    if (run <= 2 || run >= 400) return;

    repeat_into(pat, 'H', run - 1);
    frozen_pattern(above, pat, &spiked, &other);
    printf("%-40s %d hops above the ratio: estimate %.1f (start %.1f)\n", "frozen run, one hop short", run - 1, spiked, FZ_LEVEL);
    CHECK(spiked == FZ_LEVEL && other == FZ_LEVEL, "estimate moved before the run length (%.3f, %.3f)", spiked, other);

    repeat_into(pat, 'H', run);
    frozen_pattern(above, pat, &spiked, &other);
    printf("%-40s %d hops above the ratio: estimate %.1f\n", "frozen run, complete", run, spiked);
    CHECK(spiked > 10.0f * FZ_LEVEL, "estimate %.3f was not reseeded toward the power after %d hops", spiked, run);
    CHECK(spiked < above * FZ_LEVEL, "estimate %.3f is above the power", spiked);
    CHECK(other == FZ_LEVEL, "an untouched bin moved (%.3f)", other);

    repeat_into(pat, 'H', run * 6);
    frozen_pattern(below, pat, &spiked, &other);
    printf("%-40s %d hops at 0.9 x the ratio: estimate %.1f\n", "frozen run, below the ratio", run * 6, spiked);
    CHECK(spiked == FZ_LEVEL, "estimate %.3f was reseeded below the power ratio", spiked);

    /* One quiet hop clears the run: run-1 hops, a quiet hop, run-1 hops must not reseed; one more must. */
    repeat_into(pat, 'H', run - 1);
    snprintf(pat2, sizeof(pat2), "%sL%s", pat, pat);
    frozen_pattern(above, pat2, &spiked, &other);
    CHECK(spiked == FZ_LEVEL, "an interrupted run reseeded the estimate (%.3f)", spiked);
    snprintf(pat2, sizeof(pat2), "%sL%sH", pat, pat);
    frozen_pattern(above, pat2, &spiked, &other);
    CHECK(spiked > 10.0f * FZ_LEVEL, "a complete run after an interruption did not reseed (%.3f)", spiked);
}

/* Posterior SNR below 1 on every bin (the residual-echo PSD far above the signal): the first
 * frame after initialization must not sit at the gain floor while the next frames settle higher.
 * Frames 0..num_init-1 are the unity bypass. */
static void run_first_frame_case(const char* label, AnrConfig cfg) {
    AnrDenoiser* d = anr_create(&cfg);
    int nf, h, k, n_frames, ni = cfg.num_init_frames;
    Complex* spec; const float* gain = NULL; float* residual_echo_psd; double first = 0.0, settled = 0.0; int bad = 0;
    if (!d) { CHECK(0, "%s: create failed", label); return; }
    nf = anr_get_n_freqs(d); n_frames = ni + 20;
    spec = (Complex*)calloc((size_t)nf, sizeof(Complex));
    residual_echo_psd = (float*)calloc((size_t)nf, sizeof(float));
    for (k = 0; k < nf; ++k) residual_echo_psd[k] = 1.0e8f;
    for (h = 0; h < n_frames; ++h) {
        double acc = 0.0;
        for (k = 0; k < nf; ++k) { spec[k].r = 400.0f + (float)((k * 7 + h * 3) % 11); spec[k].i = 0.0f; }
        gain = anr_process_gain_with_residual_psd(d, spec, residual_echo_psd);
        for (k = 0; k < nf; ++k) { acc += 20.0 * log10((double)gain[k] + 1e-6); if (h < ni) bad += gain[k] != 1.0f; }
        acc /= nf;
        if (h == ni) first = acc;
        if (h >= ni + 10) settled += acc / 10.0;
    }
    printf("%-40s first tracked frame %.1f dB, settled %.1f dB\n", label, first, settled);
    CHECK(bad == 0, "%s: initialization frames are not unity", label);
    CHECK(first > settled - 1.0, "%s: first tracked frame %.1f dB lies below the settled %.1f dB", label, first, settled);
    free(spec); free(residual_echo_psd); anr_destroy(d);
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
    {
        static const int sr_of[3] = { 16000, 16000, 48000 };
        static const int fft_of[3] = { 256, 512, 1024 };
        for (r = 0; r < 3; ++r) {
            char label[64];
            AnrConfig cfg = anr_config_for_level_grid(sr_of[r], fft_of[r], ANR_LEVEL_BALANCED);
            AnrConfig bb = cfg; bb.broadband_threshold = 0.8f;
            snprintf(label, sizeof(label), "%d Hz %d zero bins, library", sr_of[r], fft_of[r]);
            run_zero_bins_case(label, cfg);
            snprintf(label, sizeof(label), "%d Hz %d zero bins, gate 0.8", sr_of[r], fft_of[r]);
            run_zero_bins_case(label, bb);
            snprintf(label, sizeof(label), "%d Hz %d frozen bins, library", sr_of[r], fft_of[r]);
            run_frozen_gap_case(label, cfg);
            snprintf(label, sizeof(label), "%d Hz %d frozen bins, gate 0.8", sr_of[r], fft_of[r]);
            run_frozen_gap_case(label, bb);
        }
    }
    run_frozen_run_case();
    run_first_frame_case("16000 Hz 256 first frame", anr_config_for_level_grid(16000, 256, ANR_LEVEL_BALANCED));
    run_first_frame_case("16000 Hz 512 first frame", anr_config_for_level_grid(16000, 512, ANR_LEVEL_BALANCED));
    run_first_frame_case("48000 Hz 1024 first frame", anr_config_for_level_grid(48000, 1024, ANR_LEVEL_BALANCED));
    if (g_fail) { printf(">>> FAIL\n"); return 1; }
    printf(">>> PASS\n");
    return 0;
}
