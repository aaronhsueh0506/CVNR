/* The MCRA scene-change detector must take the same branch as the Python
 * reference (tests/test_scene_change_flatness_margin.py) on frames whose
 * high-band spectral flatness lies within a few 1e-4 of
 * scene_change_flatness_threshold.
 *
 * The detector fires after scene_change_min_frames consecutive frames with a
 * high-band energy ratio above scene_change_threshold_db AND a high-band
 * flatness above the threshold, then blends the noise floor toward the frame
 * power. The reference evaluates the geometric mean in double precision; a
 * cubic exp approximation (1.7e-3 relative) in this port once put DNS 2020
 * clip fileid_63 on the other side of the threshold (0.39991 vs 0.40061), so
 * the two trackers reset on different frames and the outputs diverged for
 * ~120 frames (16 dB waveform parity). Two synthetic bursts pin the decision
 * at +6e-4 and -6e-4 from the threshold with the same numbers as the Python
 * test: the first must fire, the second must not. Standalone runner, exit != 0
 * on any failure. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mcra_noise_estimator.h"
#include "mmse_lsa_types.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

#define N_FREQS    257        /* 16 kHz / FFT 512 */
#define HI_START   128        /* the detector's high band is the upper half */
/* 64 bins at HI_A, 65 at hi_b. Flatness is scale-free; the level puts the
 * mean log power at 5.52, whose fractional part (0.52, folded to -0.48) is
 * where a cubic Taylor exp over [-0.5, 0.5) is 0.33% low -- five times the
 * margins below (it computed 0.39928 for the frame that must fire). */
#define HI_A       1200.0f
#define HI_B_FIRE  53.02f     /* flatness 0.400612: +6.1e-4 above the 0.4 threshold */
#define HI_B_HOLD  52.68f     /* flatness 0.399426: -5.7e-4 below it */
#define N_INIT     8
#define MIN_FRAMES 4
#define FIRE_MIN   480.0f     /* a fired reset leaves the HI_A bins near 0.5 * (N + HI_A) */
#define HOLD_MAX   120.0f     /* the ordinary SPP-gated update stays far below that */

/* Min and max of the high-band noise PSD after MIN_FRAMES burst frames. */
static void hi_noise_after_burst(float hi_b, float* min_out, float* max_out) {
    MmseLsaConfig cfg = mmse_lsa_default_config_for_grid(16000, 512);
    McraNoiseEstimator* est;
    float power[N_FREQS], sum[N_FREQS];
    const float* noise;
    int f, k;
    cfg.scene_change_min_frames = MIN_FRAMES;
    est = mcra_create(N_FREQS, &cfg);
    *min_out = -1.0f; *max_out = -1.0f;
    if (!est) return;
    for (k = 0; k < N_FREQS; ++k) { power[k] = 1.0f; sum[k] = 0.0f; }
    for (f = 0; f < N_INIT; ++f) {
        for (k = 0; k < N_FREQS; ++k) sum[k] += power[k];
        mcra_accumulate_init_power(est, power, f);
    }
    mcra_init_noise(est, sum, N_INIT);
    for (k = HI_START; k < HI_START + 64; ++k) power[k] = HI_A;
    for (k = HI_START + 64; k < N_FREQS; ++k) power[k] = hi_b;
    for (f = 0; f < MIN_FRAMES; ++f) mcra_update(est, power, NULL);
    noise = mcra_get_noise_psd(est);
    *min_out = noise[HI_START]; *max_out = noise[HI_START];
    for (k = HI_START; k < N_FREQS; ++k) {
        if (noise[k] < *min_out) *min_out = noise[k];
        if (noise[k] > *max_out) *max_out = noise[k];
    }
    mcra_destroy(est);
}

int main(void) {
    float lo, hi;
    hi_noise_after_burst(HI_B_FIRE, &lo, &hi);
    printf("flatness +6e-4 above threshold: hi-band noise PSD after %d frames min %.1f max %.1f\n", MIN_FRAMES, lo, hi);
    CHECK(hi > FIRE_MIN, "the scene-change reset did not fire just above the flatness threshold (max %.1f)", hi);
    hi_noise_after_burst(HI_B_HOLD, &lo, &hi);
    printf("flatness -6e-4 below threshold: hi-band noise PSD after %d frames min %.1f max %.1f\n", MIN_FRAMES, lo, hi);
    CHECK(hi >= 0.0f && hi < HOLD_MAX, "the scene-change reset fired just below the flatness threshold (max %.1f)", hi);
    printf(g_fail ? ">>> FAIL\n" : ">>> PASS\n");
    return g_fail;
}
