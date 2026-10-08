/* Dump canonical configs for three grids and four strengths as CSV.
 * Consumed by python/tests/test_config_parity.py. */
#include "anr_types.h"

#include <stdio.h>

typedef struct { int sample_rate, fft_size; } Grid;
static const Grid GRIDS[] = {
    {16000, 256}, {16000, 512}, {48000, 1024},
};

typedef struct { AnrMode mode; const char* name; } Strength;
static const Strength STRENGTHS[] = {
    {ANR_MODE_MILD,       "mild"},
    {ANR_MODE_MODERATE,   "moderate"},
    {ANR_MODE_BALANCED,   "balanced"},
    {ANR_MODE_AGGRESSIVE, "aggressive"},
};

int main(void) {
    printf("sample_rate,fft_size,hop_size,strength,alpha_xi,q,xi_min_db,"
           "g_min_db,alpha_g,alpha_attack,alpha_decay,num_init_frames,"
           "alpha_s,alpha_d,alpha_p,L,broadband_threshold,delta_db,"
           "scene_change_threshold_db,scene_change_min_frames,"
           "scene_change_blend,scene_change_flatness_threshold,"
           "noise_over_subtraction,speech_protect_floor,"
           "speech_protect_floor_db,speech_protect_threshold,"
           "speech_protect_frame_threshold,dd_from_gmmse,speech_aware_noise_tracking,"
           "alpha_d_speech,noise_gate_xi_db,noise_gate_lf_hz,"
           "noise_gate_frame_frac,makeup_gain,makeup_prior_xi_db,"
           "makeup_blim,makeup_up_slope,makeup_down_slope\n");

    for (size_t g = 0; g < sizeof(GRIDS) / sizeof(GRIDS[0]); ++g) {
        for (size_t s = 0; s < sizeof(STRENGTHS) / sizeof(STRENGTHS[0]); ++s) {
            AnrConfig c = anr_config_for_mode_grid(
                GRIDS[g].sample_rate, GRIDS[g].fft_size, STRENGTHS[s].mode);
            printf("%d,%d,%d,%s,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,"
                   "%.9g,%.9g,%.9g,%d,%.9g,%.9g,%.9g,%d,%.9g,%.9g,"
                   "%.9g,%d,%.9g,%.9g,%.9g,%d,%d,%.9g,%.9g,%.9g,%.9g,%d,%.9g,%.9g,%.9g,%.9g\n",
                   c.sample_rate, c.fft_size, c.hop_size, STRENGTHS[s].name,
                   c.alpha_xi, c.q, c.xi_min_db, c.g_min_db, c.alpha_g,
                   c.alpha_attack, c.alpha_decay, c.num_init_frames,
                   c.alpha_s, c.alpha_d, c.alpha_p, c.L,
                   c.broadband_threshold, c.delta_db,
                   c.scene_change_threshold_db, c.scene_change_min_frames,
                   c.scene_change_blend, c.scene_change_flatness_threshold,
                   c.noise_over_subtraction, c.speech_protect_floor ? 1 : 0,
                   c.speech_protect_floor_db, c.speech_protect_threshold,
                   c.speech_protect_frame_threshold, c.dd_from_gmmse ? 1 : 0,
                   c.speech_aware_noise_tracking ? 1 : 0, c.alpha_d_speech,
                   c.noise_gate_xi_db, c.noise_gate_lf_hz,
                   c.noise_gate_frame_frac, c.makeup_gain ? 1 : 0,
                   c.makeup_prior_xi_db, c.makeup_blim,
                   c.makeup_up_slope, c.makeup_down_slope);
        }
    }
    return 0;
}
