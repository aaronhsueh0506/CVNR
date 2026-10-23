/* Static-memory ANR WAV runner with the same framing as main.c.
 * Size aligned pools with anr_get_mem_size(), then call anr_init().
 * anr_destroy() leaves caller-owned pools intact. */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

#include "anr.h"
#include "anr_types.h"
#include "fft_wrapper.h"
#include "audio_window.h"
#include "wav_io.h"

/* ---- Maximum supported no-padding grid (48 kHz / FFT 1024) -------------- */
#define MAX_FRAME_SIZE 1024
#define MAX_N_FREQS    (MAX_FRAME_SIZE / 2 + 1)

/* Aligned pools cover all project grids; runtime size checks guard capacity. */
#define DENOISER_POOL_BYTES (256 * 1024)   /* covers 513-bin 48 kHz config      */
#define FFT_POOL_BYTES      ( 48 * 1024)   /* covers the 1024-point NE10 FFT    */

static uint8_t g_denoiser_pool[DENOISER_POOL_BYTES] __attribute__((aligned(16)));
static uint8_t g_fft_pool[FFT_POOL_BYTES]           __attribute__((aligned(16)));

/* Per-frame scratch (fixed framing) — also static, no malloc. */
static float   g_win[MAX_FRAME_SIZE];
static float   g_frame_buf[MAX_FRAME_SIZE];
static float   g_time_out[MAX_FRAME_SIZE];
static Complex g_spec_in[MAX_N_FREQS];
static Complex g_spec_out[MAX_N_FREQS];

/* Whole-file I/O buffers. These scale with the clip length, so they are capped
 * static arrays here (a real device streams PCM in fixed chunks instead). */
#define MAX_SECONDS 60
#define MAX_SAMPLES (48000 * MAX_SECONDS)
static float   g_signal[MAX_SAMPLES];
/* The OLA output can overshoot n_samples by up to hop - 1 samples, so it is padded past
 * MAX_SAMPLES. */
static float   g_out_ola[MAX_SAMPLES + MAX_FRAME_SIZE];

void print_usage(const char* prog) {
    printf("ANR (C implementation, static-memory runner)\n\n");
    printf("Usage: %s <input.wav> <output.wav> [options]\n\n", prog);
    printf("Options:\n");
    printf("  --bypass       Bypass mode (copy input to output)\n");
    printf("  --nr-mode <m>  NR strength: 0|1|2|3 or mild|moderate|balanced|aggressive (default: balanced)\n");
    printf("  --debug        Print one anr_debug_status() line per second of audio\n\n");
    printf("  --fft-size <n> Select project grid (256/512 @16k; 1024 @48k)\n\n");
    printf("All state is pre-allocated in static memory; no malloc on the audio path.\n");
    printf("Output is byte-identical to denoise_wav (framing 512/256/512, sqrt-Hann).\n");
}

/* Periodic sqrt-Hann window. */
static void build_sqrt_hann(float* w, int N) {
    ac_window_build(w, N);
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char* input_path  = argv[1];
    const char* output_path = argv[2];
    int bypass = 0;
    int debug = 0;
    int fft_size_override = 0;
    AnrMode nr_mode = ANR_MODE_BALANCED;

    for (int i = 3; i < argc; i++) {
        if (strcmp(argv[i], "--bypass") == 0) {
            bypass = 1;
        } else if (strcmp(argv[i], "--debug") == 0) {
            debug = 1;
        } else if (strcmp(argv[i], "--fft-size") == 0 && i + 1 < argc) {
            fft_size_override = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--nr-mode") == 0 && i + 1 < argc) {
            /* Name or digit 0..3; an unrecognised value keeps the balanced default. */
            int m = anr_nr_mode_from_name(argv[++i]);
            nr_mode = m >= 0 ? (AnrMode)m : ANR_MODE_BALANCED;
        }
    }

    /* 1. Open input WAV and read the whole first channel into the static buffer. */
    WavReader* wav_in = wav_open_read(input_path);
    if (!wav_in) {
        fprintf(stderr, "Error: Cannot open input file: %s\n", input_path);
        return 1;
    }
    int sample_rate = wav_in->info.sample_rate;
    printf("Input: %s\n", input_path);
    printf("  Sample rate: %d Hz  Channels: %d  Bits: %d  Duration: %.2f sec\n",
           sample_rate, wav_in->info.channels, wav_in->info.bits_per_sample,
           (float)wav_in->info.num_samples / sample_rate);

    if (wav_in->info.num_samples > MAX_SAMPLES) {
        fprintf(stderr, "Error: clip has %d samples > static cap %d (%d s). "
                        "Raise MAX_SECONDS or stream in chunks.\n",
                wav_in->info.num_samples, MAX_SAMPLES, MAX_SECONDS);
        wav_close_read(wav_in);
        return 1;
    }

    int n_samples = 0;
    {
        float tmp[1024];
        int n = wav_in->info.num_samples;
        while (n_samples < n) {
            int want = n - n_samples;
            if (want > 1024) want = 1024;
            int r = wav_read_float(wav_in, tmp, want);
            if (r <= 0) break;
            memcpy(g_signal + n_samples, tmp, r * sizeof(float));
            n_samples += r;
        }
    }
    wav_close_read(wav_in);
    if (n_samples <= 0) {
        fprintf(stderr, "Error: Failed to read input samples\n");
        return 1;
    }

    /* 2. Open output WAV (16-bit PCM mono). */
    WavWriter* wav_out = wav_open_write(output_path, sample_rate, 1);
    if (!wav_out) {
        fprintf(stderr, "Error: Cannot open output file: %s\n", output_path);
        return 1;
    }

    if (bypass) {
        printf("\n*** BYPASS MODE - no processing ***\n");
        wav_write_float(wav_out, g_signal, n_samples);
        wav_close_write(wav_out);
        printf("Output: %s\n", output_path);
        return 0;
    }

    /* 3. Config — no-padding project grid. */
    int selected_fft = fft_size_override > 0
                     ? fft_size_override : anr_default_fft_size(sample_rate);
    AnrConfig config = anr_config_for_mode_grid(
        sample_rate, selected_fft, nr_mode);

    /* Reject unsupported grids with a clear message (anr_get_mem_size() would also reject them,
     * with a generic pool-size error). */
    if (!anr_validate_config(&config)) {
        fprintf(stderr,
                "Error: unsupported sample rate %d Hz for NR processing "
                "(supported: 8000, 16000, 48000 Hz)\n", sample_rate);
        wav_close_write(wav_out);
        return 1;
    }

    /* 4. Size the static pools against the exact requirement (the no-malloc step). */
    size_t need_denoiser = anr_get_mem_size(&config);
    const int frame_size = config.frame_size;
    const int hop = config.hop_size;
    const int fft_size = config.fft_size;
    size_t need_fft      = fft_get_mem_size(fft_size);
    printf("\nStatic memory footprint:\n");
    printf("  Denoiser+noise+SPP: %zu bytes  (pool %d)\n", need_denoiser, DENOISER_POOL_BYTES);
    printf("  FFT             : %zu bytes  (pool %d)\n", need_fft, FFT_POOL_BYTES);
    if (need_denoiser > sizeof(g_denoiser_pool)) {
        fprintf(stderr, "Error: denoiser needs %zu > pool %zu. Raise DENOISER_POOL_BYTES.\n",
                need_denoiser, sizeof(g_denoiser_pool));
        wav_close_write(wav_out);
        return 1;
    }
    if (need_fft > sizeof(g_fft_pool)) {
        fprintf(stderr, "Error: FFT needs %zu > pool %zu. Raise FFT_POOL_BYTES.\n",
                need_fft, sizeof(g_fft_pool));
        wav_close_write(wav_out);
        return 1;
    }

    /* 5. Create the engine IN the static pools — zero malloc. */
    AnrDenoiser* denoiser = anr_init(g_denoiser_pool, sizeof(g_denoiser_pool), &config);
    FftHandle*       fft      = fft_init(g_fft_pool, sizeof(g_fft_pool), fft_size);
    if (!denoiser || !fft) {
        fprintf(stderr, "Error: Failed to create denoiser/FFT in static memory\n");
        wav_close_write(wav_out);
        return 1;
    }

    const char* mode_names[] = {"mild", "moderate", "balanced", "aggressive"};
    printf("  NR mode: %s\n", mode_names[nr_mode]);

    /* 6. Framing (as in main.c). */
    int n_frames = (n_samples <= frame_size)
                 ? 1
                 : (n_samples - frame_size + hop - 1) / hop + 1;
    int out_len = (n_frames - 1) * hop + frame_size;

    /* out_len can exceed n_samples by up to hop - 1 samples; check the capacity at runtime. */
    if (out_len > (int)(sizeof(g_out_ola) / sizeof(float))) {
        fprintf(stderr, "Error: out_len %d > g_out_ola capacity %zu. Raise MAX_SECONDS.\n",
                out_len, sizeof(g_out_ola) / sizeof(float));
        wav_close_write(wav_out);
        return 1;
    }

    memset(g_out_ola, 0, (size_t)out_len * sizeof(float));
    build_sqrt_hann(g_win, frame_size);

    printf("\nProcessing %d frames (static memory, no malloc on audio path)...\n", n_frames);
    int debug_last_sec = -1;
    for (int f = 0; f < n_frames; f++) {
        int start = f * hop;

        for (int n = 0; n < frame_size; n++) {
            int idx = start + n;
            float s = (idx < n_samples) ? g_signal[idx] : 0.0f;
            g_frame_buf[n] = s * g_win[n];
        }
        for (int n = frame_size; n < fft_size; n++) g_frame_buf[n] = 0.0f;

        fft_forward(fft, g_frame_buf, g_spec_in);

        if (anr_process(denoiser, g_spec_in, g_spec_out) < 0) {
            fprintf(stderr, "Error: anr_process failed at frame %d\n", f);
            break;
        }

        fft_inverse(fft, g_spec_out, g_time_out);

        for (int n = 0; n < frame_size; n++) {
            g_out_ola[start + n] += g_time_out[n] * g_win[n];
        }

        if (debug) {
            int cur_sec = start / sample_rate;
            if (cur_sec != debug_last_sec) {
                debug_last_sec = cur_sec;
                AnrDebugStatus st;
                anr_debug_status(denoiser, &st);
                fprintf(stderr,
                    "[dbg %d.0s] init=%d gain(mean/min)=%.1f/%.1fdB spp=%.2f noise=%.1fdB\n",
                    cur_sec, st.initialized, st.mean_gain_db, st.min_gain_db,
                    st.mean_spp, st.noise_floor_db);
            }
        }
    }

    /* 7. Crop to original length and write. */
    int write_len = (out_len < n_samples) ? out_len : n_samples;
    wav_write_float(wav_out, g_out_ola, write_len);

    printf("Done! %d in / %d out / %d frames\n", n_samples, write_len, n_frames);
    printf("Output: %s\n", output_path);

    /* 8. Cleanup — no-op for static-memory instances (caller owns the pools). */
    anr_destroy(denoiser);
    fft_destroy(fft);
    wav_close_write(wav_out);
    return 0;
}
