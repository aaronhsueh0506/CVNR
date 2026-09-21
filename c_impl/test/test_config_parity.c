/* test_config_parity.c -- dumps the C library's canonical effective
 * MmseLsaConfig for every (grid, strength) combination this project ships,
 * so a Python-side test can certify Python and C resolve to the SAME
 * effective config, not just "both produce finite output" (2026-08-03,
 * following the A/B tuning-provenance investigation that found the C mono/
 * 4ch pipelines had been silently overriding this canonical default back to
 * a stale, worse-measured legacy tuning -- see NR/CHANGELOG.md and
 * Audio_ALG/pipelines/mono_aec_nr_res/audio_pipeline.c's matching comment).
 *
 * This intentionally does NOT link aec.c or any pipeline code -- it only
 * exercises mmse_lsa_config_for_mode_grid(), the single function both
 * Audio_ALG C pipelines and (conceptually) process_audio.py's
 * build_v3_2_base_params()+apply_strength() are supposed to agree with.
 *
 * Output: one CSV line per (sample_rate, fft_size, strength) to stdout,
 * fields in a fixed order (see the header row this program prints first).
 * Grids match Audio_ALG/pipelines/4ch_aec_bf_nr_res/README.md's three checked-in
 * grids: 16k/256 (default, 8ms hop), 16k/512 (alternate, 16ms hop),
 * 48k/1024 (10.67ms hop). Consumed by NR/tests/test_config_parity.py.
 *
 * Build (standalone, mirrors test_delay_reset.c's style -- this file only
 * needs the header, no other translation unit):
 *   gcc -Wall -Wextra -O2 -ffp-contract=off -std=gnu99 -Iinclude \
 *       test/test_config_parity.c -lm -o bin/test_config_parity
 * Also wired into `make test-config-parity` (c_impl/Makefile).
 */
#include "mmse_lsa_types.h"

#include <stdio.h>

typedef struct { int sample_rate, fft_size; } Grid;
static const Grid GRIDS[] = {
    {16000, 256}, {16000, 512}, {48000, 1024},
};

typedef struct { MmseLsaNrMode mode; const char* name; } Strength;
static const Strength STRENGTHS[] = {
    {MMSE_LSA_NR_MILD,       "mild"},
    {MMSE_LSA_NR_MODERATE,   "moderate"},
    {MMSE_LSA_NR_BALANCED,   "balanced"},
    {MMSE_LSA_NR_AGGRESSIVE, "aggressive"},
};

int main(void) {
    printf("sample_rate,fft_size,hop_size,strength,alpha_xi,q,xi_min_db,"
           "g_min_db,alpha_g,alpha_attack,alpha_decay,num_init_frames,"
           "alpha_s,alpha_d,alpha_p,L,broadband_threshold,delta_db,"
           "scene_change_threshold_db,scene_change_min_frames,"
           "scene_change_blend,scene_change_flatness_threshold\n");

    for (size_t g = 0; g < sizeof(GRIDS) / sizeof(GRIDS[0]); ++g) {
        for (size_t s = 0; s < sizeof(STRENGTHS) / sizeof(STRENGTHS[0]); ++s) {
            MmseLsaConfig c = mmse_lsa_config_for_mode_grid(
                GRIDS[g].sample_rate, GRIDS[g].fft_size, STRENGTHS[s].mode);
            printf("%d,%d,%d,%s,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,"
                   "%.9g,%.9g,%.9g,%d,%.9g,%.9g,%.9g,%d,%.9g,%.9g\n",
                   c.sample_rate, c.fft_size, c.hop_size, STRENGTHS[s].name,
                   c.alpha_xi, c.q, c.xi_min_db, c.g_min_db, c.alpha_g,
                   c.alpha_attack, c.alpha_decay, c.num_init_frames,
                   c.alpha_s, c.alpha_d, c.alpha_p, c.L,
                   c.broadband_threshold, c.delta_db,
                   c.scene_change_threshold_db, c.scene_change_min_frames,
                   c.scene_change_blend, c.scene_change_flatness_threshold);
        }
    }
    return 0;
}
