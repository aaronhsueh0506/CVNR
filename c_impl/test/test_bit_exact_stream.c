/* Synthetic per-hop state/output stream; no external audio or persistent trace. */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/anr.c"
#include "../src/mcra_noise_estimator.c"
#include "../src/spp_estimator.c"

#define STREAM_MAGIC 0x414e5231u
#define RECORD_MAGIC 0x414e5232u
#define FRAMES 256

static uint32_t rng;

static float random_sample(void) {
    rng = rng * 1664525u + 1013904223u;
    return (float)(rng >> 8) * (1.0f / 16777216.0f) - 0.5f;
}

static void write_words(const void* values, size_t count) {
    if (fwrite(values, sizeof(uint32_t), count, stdout) != count) exit(2);
}

static void record(const uint32_t* context, uint32_t field,
                   const void* values, uint32_t count) {
    uint32_t header[7] = {RECORD_MAGIC, context[0], context[1], context[2],
                          context[3], field, count};
    write_words(header, 7);
    write_words(values, count);
}

static void dump_state(const uint32_t* context, const AnrDenoiser* s,
                       const Complex* output, const float* returned_gain) {
    const float* arrays[] = {s->power, s->spp, s->xi, s->gamma, s->gain,
        s->gain_prev, s->enhanced_psd_prev, s->log_gain_prev,
        anr_get_noise_psd(s, NULL), s->noise_est->S, s->noise_est->S_min,
        s->noise_est->spp, s->spp_est->gamma_prev, s->spp_est->noise_psd_prev};
    uint32_t nf = (uint32_t)s->n_freqs;
    for (uint32_t i = 0; i < sizeof(arrays) / sizeof(arrays[0]); ++i)
        record(context, i, arrays[i], nf);
    record(context, 14, output, 2 * nf);
    record(context, 15, returned_gain, nf);
    const float scalars[] = {s->cross_band_prior_state, s->cross_band_prior_lift,
        s->makeup_prior_state, s->spp_est->alpha, s->spp_est->q,
        s->spp_est->xi_min, s->spp_est->prior_ratio};
    record(context, 16, scalars, sizeof(scalars) / sizeof(scalars[0]));
    const uint32_t flags[] = {(uint32_t)s->init_frame_count,
        (uint32_t)s->is_initialized, (uint32_t)s->gain_initialized,
        (uint32_t)s->slow_lf_rise, (uint32_t)s->speech_protect_frame_active,
        (uint32_t)s->noise_est->ring_idx, (uint32_t)s->noise_est->scene_change_count,
        (uint32_t)s->noise_est->is_initialized, (uint32_t)s->spp_est->is_initialized};
    record(context, 17, flags, sizeof(flags) / sizeof(flags[0]));
    if (s->noise_est->ring_idx == 0)
        record(context, 18, s->noise_est->min_buffer, nf * (uint32_t)s->config.L);
}

static void run_case(uint32_t grid, int sr, int fft, AnrMode strength,
                     uint32_t feature, int static_memory) {
    AnrConfig config = anr_config_for_mode_grid(sr, fft, strength);
    if (feature == 1) config.dd_from_gmmse = true;
    if (feature == 2) {
        anr_apply_cross_band_speech_experiment(&config);
        config.makeup_gain = true;
    }
    void* pool = NULL;
    AnrDenoiser* s;
    if (static_memory) {
        size_t bytes = anr_get_mem_size(&config);
        if (!bytes || posix_memalign(&pool, 16, bytes)) exit(3);
        s = anr_init(pool, bytes, &config);
    } else {
        s = anr_create(&config);
    }
    if (!s) exit(4);
    int nf = fft / 2 + 1;
    Complex* input = (Complex*)malloc((size_t)nf * sizeof(Complex));
    Complex* output = (Complex*)malloc((size_t)nf * sizeof(Complex));
    float* extra = (float*)malloc((size_t)nf * sizeof(float));
    float* returned_gain = (float*)malloc((size_t)nf * sizeof(float));
    if (!input || !output || !extra || !returned_gain) exit(5);
    rng = 918273u + grid * 101u + (uint32_t)strength * 17u + feature;
    for (uint32_t frame = 0; frame < FRAMES; ++frame) {
        float scale = frame < 48 ? 0.05f : frame < 112 ? 2.0f
                    : frame < 176 ? 0.2f : frame < 224 ? 0.0f : 0.5f;
        for (int k = 0; k < nf; ++k) {
            input[k].r = random_sample() * scale;
            input[k].i = random_sample() * scale;
            extra[k] = 0.01f * (1.0f + random_sample());
            returned_gain[k] = -123.0f;
        }
        if (frame >= 48 && frame < 176) {
            input[3].r += 2.0f;
            input[7].i += 1.0f;
        }
        if (feature && frame == 88) anr_reset(s);
        if (feature && frame == 160) {
            config.q = 0.48f;
            if (anr_reconfigure(s, &config)) exit(6);
        }
        if (feature && frame == 208 && anr_set_mode(s, ANR_MODE_AGGRESSIVE)) exit(7);
        memset(output, 0, (size_t)nf * sizeof(Complex));
        if ((frame & 3u) == 0) {
            if (anr_process(s, input, input)) exit(8);
            memcpy(output, input, (size_t)nf * sizeof(Complex));
        } else if ((frame & 3u) == 1) {
            if (anr_process(s, input, output)) exit(9);
        } else {
            const float* external = (frame & 4u) ? extra : NULL;
            float* gain_out = (frame & 8u) ? returned_gain : NULL;
            if (anr_process_gain(s, input, external, gain_out)) exit(10);
        }
        uint32_t context[] = {grid, (uint32_t)strength,
                              feature + (static_memory ? 4u : 0u), frame};
        dump_state(context, s, output, returned_gain);
    }
    free(input);
    free(output);
    free(extra);
    free(returned_gain);
    anr_destroy(s);
    free(pool);
}

int main(void) {
    if (sizeof(float) != sizeof(uint32_t) || sizeof(Complex) != 2 * sizeof(float)) return 1;
    setvbuf(stdout, NULL, _IOFBF, 65536);
#if defined(USE_FAST_GAIN_SMOOTHING) && ANR_VECTOR
    const uint32_t vector_gain = 1;
#else
    const uint32_t vector_gain = 0;
#endif
    const uint32_t info[] = {STREAM_MAGIC, SK_HAVE_NEON, vector_gain, FRAMES};
    write_words(info, 4);
    const int rates[] = {16000, 16000, 48000};
    const int sizes[] = {256, 512, 1024};
    for (uint32_t grid = 0; grid < 3; ++grid) {
        for (int strength = ANR_MODE_MILD; strength <= ANR_MODE_AGGRESSIVE; ++strength)
            run_case(grid, rates[grid], sizes[grid], (AnrMode)strength, 0, 0);
        for (uint32_t feature = 1; feature <= 2; ++feature)
            run_case(grid, rates[grid], sizes[grid], ANR_MODE_BALANCED, feature, 0);
        run_case(grid, rates[grid], sizes[grid], ANR_MODE_BALANCED, 0, 1);
    }
    return fflush(stdout) == 0 ? 0 : 11;
}
