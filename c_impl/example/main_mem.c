/**
 * main_mem.c - MMSE-LSA Denoiser runner, STATIC-MEMORY build
 *
 * Same freq-domain NR core and framing as main.c, but demonstrates the
 * embedded "no malloc" contract: the NR engine, its MCRA/SPP sub-modules, the
 * FFT, and every per-frame scratch buffer live in STATIC memory that is sized
 * ONCE up front. After start-up there is not a single malloc/free on the audio
 * path — exactly what an embedded target needs (the static pools below would
 * instead be a caller-provided platform memory block on the device, e.g. a
 * DMA-capable region handed down from the platform's memory manager).
 *
 * The pattern is:
 *     size_t need = mmse_lsa_get_mem_size(&config);   // how much do I need?
 *     ... ensure a pre-allocated block is >= need ...
 *     MmseLsaDenoiser* d = mmse_lsa_init(pool, sizeof pool, &config); // no malloc
 *     ... process ...                                                  // no malloc
 *     mmse_lsa_destroy(d);   // no-op for a static-memory instance (caller owns pool)
 *
 * Build:  make mem            (links this file against the same objects as
 *                              denoise_wav — the malloc and static-memory paths
 *                              are both always compiled now, see
 *                              mmse_lsa_get_mem_size()/mmse_lsa_init())
 * Framing is identical to main.c / the Python V3-2 reference, so the output is
 * byte-for-byte identical to `denoise_wav` — that IS the correctness check:
 * static-memory allocation changes nothing numerically.
 *
 * Usage: denoise_mem <input.wav> <output.wav> [options]   (same options as main.c)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "fft_wrapper.h"
#include "wav_io.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ---- Fixed framing (matches Python config/v3_2_config.yaml exactly) ------- */
#define FRAME_SIZE 512
#define HOP        256
#define FFT_SIZE   512
#define N_FREQS    (FFT_SIZE / 2 + 1)

/* ---- Static memory pools — sized ONCE, never malloc'd -------------------- *
 * On an embedded target these would be caller-provided platform memory blocks;
 * here they are plain static arrays. Sized to a measured figure + modest
 * headroom for the fixed framing above and checked at run-time against the
 * exact get_mem_size() figure:
 *   - denoiser+MCRA+SPP measured 72,736 bytes (fft_size=512, all 4 nr-mode
 *     presets + stationary — identical struct layout, only scalars differ)
 *     -> 96 KB pool.
 *   - FFT measured 16,976 bytes (KISS backend) / ~4.2 KB (NE10 backend)
 *     -> 24 KB pool (covers either backend with headroom).
 * The runtime `need > sizeof(pool)` guards below are the real safety net if
 * a config change ever grows past these figures. */
#define DENOISER_POOL_BYTES ( 96 * 1024)   /* NR engine + MCRA + SPP           */
#define FFT_POOL_BYTES      ( 24 * 1024)   /* FFT backend configs + work bufs  */

static uint8_t g_denoiser_pool[DENOISER_POOL_BYTES] __attribute__((aligned(16)));
static uint8_t g_fft_pool[FFT_POOL_BYTES]           __attribute__((aligned(16)));

/* Per-frame scratch (fixed framing) — also static, no malloc. */
static float   g_win[FRAME_SIZE];
static float   g_frame_buf[FFT_SIZE];
static float   g_time_out[FFT_SIZE];
static Complex g_spec_in[N_FREQS];
static Complex g_spec_out[N_FREQS];

/* Whole-file I/O buffers. These scale with the clip length, so they are capped
 * static arrays here (a real device streams PCM in fixed chunks instead). */
#define MAX_SECONDS 60
#define MAX_SAMPLES (48000 * MAX_SECONDS)
static float   g_signal[MAX_SAMPLES];
/* OLA output can overshoot n_samples by up to HOP-1 samples (out_len is rounded
 * up to a whole number of hops past the last frame) — pad past MAX_SAMPLES so
 * the write loop below never overruns even when n_samples == MAX_SAMPLES. */
static float   g_out_ola[MAX_SAMPLES + FRAME_SIZE];

void print_usage(const char* prog) {
    printf("MMSE-LSA Speech Denoiser (V3-2 C, STATIC-MEMORY build)\n\n");
    printf("Usage: %s <input.wav> <output.wav> [options]\n\n", prog);
    printf("Options:\n");
    printf("  --bypass       Bypass mode (copy input to output)\n");
    printf("  --nr-mode <m>  NR strength: mild|moderate|balanced|aggressive (default: balanced)\n");
    printf("  --stationary   Content-preservation mode (layered on --nr-mode)\n");
    printf("  --debug        Print one mmse_lsa_debug_status() line per second of audio\n\n");
    printf("All state is pre-allocated in static memory; no malloc on the audio path.\n");
    printf("Output is byte-identical to denoise_wav (framing 512/256/512, sqrt-Hann).\n");
}

/* sqrt(periodic Hann) — bit-matches np.sqrt(hann(N, sym=False)). */
static void build_sqrt_hann(float* w, int N) {
    for (int n = 0; n < N; n++) {
        float h = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * (float)n / (float)N);
        w[n] = sqrtf(h);
    }
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char* input_path  = argv[1];
    const char* output_path = argv[2];
    int bypass = 0;
    int stationary = 0;
    int debug = 0;
    MmseLsaNrMode nr_mode = MMSE_LSA_NR_BALANCED;

    for (int i = 3; i < argc; i++) {
        if (strcmp(argv[i], "--bypass") == 0) {
            bypass = 1;
        } else if (strcmp(argv[i], "--stationary") == 0) {
            stationary = 1;
        } else if (strcmp(argv[i], "--debug") == 0) {
            debug = 1;
        } else if (strcmp(argv[i], "--nr-mode") == 0 && i + 1 < argc) {
            const char* m = argv[++i];
            if (strcmp(m, "mild") == 0)             nr_mode = MMSE_LSA_NR_MILD;
            else if (strcmp(m, "moderate") == 0)    nr_mode = MMSE_LSA_NR_MODERATE;
            else if (strcmp(m, "aggressive") == 0)  nr_mode = MMSE_LSA_NR_AGGRESSIVE;
            else                                    nr_mode = MMSE_LSA_NR_BALANCED;
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

    /* 3. Config — framing forced to the reference so output is parity-comparable. */
    MmseLsaConfig config = mmse_lsa_config_for_mode(sample_rate, nr_mode);
    if (stationary) mmse_lsa_apply_stationary(&config);
    config.frame_size = FRAME_SIZE;
    config.hop_size   = HOP;
    config.fft_size   = FFT_SIZE;

    /* 4. Size the static pools against the exact requirement (the no-malloc step). */
    size_t need_denoiser = mmse_lsa_get_mem_size(&config);
    size_t need_fft      = fft_get_mem_size(FFT_SIZE);
    printf("\nStatic memory footprint:\n");
    printf("  Denoiser+MCRA+SPP: %zu bytes  (pool %d)\n", need_denoiser, DENOISER_POOL_BYTES);
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
    MmseLsaDenoiser* denoiser = mmse_lsa_init(g_denoiser_pool, sizeof(g_denoiser_pool), &config);
    FftHandle*       fft      = fft_init(g_fft_pool, sizeof(g_fft_pool), FFT_SIZE);
    if (!denoiser || !fft) {
        fprintf(stderr, "Error: Failed to create denoiser/FFT in static memory\n");
        wav_close_write(wav_out);
        return 1;
    }

    const char* mode_names[] = {"mild", "moderate", "balanced", "aggressive"};
    printf("  NR mode: %s\n", stationary ? "stationary (content-preservation)"
                                          : mode_names[nr_mode]);

    /* 6. Framing (identical rule to main.c / Python FrameProcessor). */
    int n_frames = (n_samples <= FRAME_SIZE)
                 ? 1
                 : (n_samples - FRAME_SIZE + HOP - 1) / HOP + 1;
    int out_len = (n_frames - 1) * HOP + FRAME_SIZE;

    /* out_len can exceed n_samples by up to HOP-1 samples (last-frame rounding),
     * so g_out_ola is sized MAX_SAMPLES + FRAME_SIZE, not just MAX_SAMPLES — but
     * check at runtime too rather than trust the static headroom silently. */
    if (out_len > (int)(sizeof(g_out_ola) / sizeof(float))) {
        fprintf(stderr, "Error: out_len %d > g_out_ola capacity %zu. Raise MAX_SECONDS.\n",
                out_len, sizeof(g_out_ola) / sizeof(float));
        wav_close_write(wav_out);
        return 1;
    }

    memset(g_out_ola, 0, (size_t)out_len * sizeof(float));
    build_sqrt_hann(g_win, FRAME_SIZE);

    printf("\nProcessing %d frames (static memory, no malloc on audio path)...\n", n_frames);
    int debug_last_sec = -1;
    for (int f = 0; f < n_frames; f++) {
        int start = f * HOP;

        for (int n = 0; n < FRAME_SIZE; n++) {
            int idx = start + n;
            float s = (idx < n_samples) ? g_signal[idx] : 0.0f;
            g_frame_buf[n] = s * g_win[n];
        }
        for (int n = FRAME_SIZE; n < FFT_SIZE; n++) g_frame_buf[n] = 0.0f;

        fft_forward(fft, g_frame_buf, g_spec_in);

        if (mmse_lsa_process(denoiser, g_spec_in, g_spec_out) < 0) {
            fprintf(stderr, "Error: mmse_lsa_process failed at frame %d\n", f);
            break;
        }

        fft_inverse(fft, g_spec_out, g_time_out);

        for (int n = 0; n < FRAME_SIZE; n++) {
            g_out_ola[start + n] += g_time_out[n] * g_win[n];
        }

        if (debug) {
            int cur_sec = start / sample_rate;
            if (cur_sec != debug_last_sec) {
                debug_last_sec = cur_sec;
                MmseLsaDebugStatus st;
                mmse_lsa_debug_status(denoiser, &st);
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
    mmse_lsa_destroy(denoiser);
    fft_destroy(fft);
    wav_close_write(wav_out);
    return 0;
}
