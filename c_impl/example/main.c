/* ANR WAV runner. Caller owns sqrt(periodic Hann), FFT and overlap-add.
 * Frame equals FFT size; hop is frame/2. Zero-pad the last frame and crop
 * output to input length. Usage: denoise_wav input.wav output.wav [options]. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "anr.h"
#include "anr_types.h"
#include "fft_wrapper.h"
#include "audio_window.h"
#include "wav_io.h"

void print_usage(const char* prog) {
    printf("ANR (C implementation, frequency-domain runner)\n");
    printf("\n");
    printf("Usage: %s <input.wav> <output.wav> [options]\n", prog);
    printf("\n");
    printf("Arguments:\n");
    printf("  input.wav    Input noisy WAV file\n");
    printf("  output.wav   Output denoised WAV file\n");
    printf("\n");
    printf("Options:\n");
    printf("  --bypass       Bypass mode (no processing, copy input to output)\n");
    printf("  --nr-mode <m>  NR strength: 0|1|2|3 or mild|moderate|balanced|aggressive (default: balanced)\n");
    printf("  --debug        Print one anr_debug_status() line per second of audio\n");
    printf("  --fft-size <n> Select project grid (256/512 @16k; 1024 @48k)\n");
    printf("\n");
    printf("Frame equals FFT size; hop is frame/2; transform input is never zero-padded.\n");
    printf("\n");
    printf("Supported input formats:\n");
    printf("  - 16-bit PCM WAV\n");
    printf("  - 32-bit float WAV\n");
    printf("  - Mono or stereo (first channel used)\n");
    printf("\n");
    printf("Example:\n");
    printf("  %s noisy.wav clean.wav\n", prog);
    printf("  %s noisy.wav clean.wav --bypass\n", prog);
}

/* Periodic sqrt-Hann window. */
static void build_sqrt_hann(float* w, int N) {
    ac_window_build(w, N);
}

/* Read the whole (first-channel) signal into a malloc'd float buffer. */
static float* read_whole_signal(WavReader* wav_in, int* out_n) {
    int n = wav_in->info.num_samples;
    float* sig = (float*)malloc((n > 0 ? n : 1) * sizeof(float));
    if (!sig) { *out_n = 0; return NULL; }
    int got = 0;
    float tmp[1024];
    while (got < n) {
        int want = n - got;
        if (want > 1024) want = 1024;
        int r = wav_read_float(wav_in, tmp, want);
        if (r <= 0) break;
        memcpy(sig + got, tmp, r * sizeof(float));
        got += r;
    }
    *out_n = got;
    return sig;
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char* input_path = argv[1];
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

    /* 1. Open input WAV and read the whole first channel. */
    WavReader* wav_in = wav_open_read(input_path);
    if (!wav_in) {
        fprintf(stderr, "Error: Cannot open input file: %s\n", input_path);
        return 1;
    }

    int sample_rate = wav_in->info.sample_rate;
    printf("Input: %s\n", input_path);
    printf("  Sample rate: %d Hz\n", sample_rate);
    printf("  Channels: %d\n", wav_in->info.channels);
    printf("  Bits per sample: %d\n", wav_in->info.bits_per_sample);
    printf("  Duration: %.2f sec\n",
           (float)wav_in->info.num_samples / sample_rate);

    int n_samples = 0;
    float* signal = read_whole_signal(wav_in, &n_samples);
    wav_close_read(wav_in);
    if (!signal || n_samples <= 0) {
        fprintf(stderr, "Error: Failed to read input samples\n");
        free(signal);
        return 1;
    }

    /* 2. Open output WAV (16-bit PCM mono at input rate). */
    WavWriter* wav_out = wav_open_write(output_path, sample_rate, 1);
    if (!wav_out) {
        fprintf(stderr, "Error: Cannot open output file: %s\n", output_path);
        free(signal);
        return 1;
    }

    /* 3. Bypass = passthrough, write input straight back. */
    if (bypass) {
        printf("\n*** BYPASS MODE - no processing ***\n");
        wav_write_float(wav_out, signal, n_samples);
        wav_close_write(wav_out);
        free(signal);
        printf("Output: %s\n", output_path);
        return 0;
    }

    /* 4. Build config on the no-padding project grid. */
    int selected_fft = fft_size_override > 0
                     ? fft_size_override : anr_default_fft_size(sample_rate);
    AnrConfig config = anr_config_for_mode_grid(
        sample_rate, selected_fft, nr_mode);

    /* Reject unsupported grids before creating the denoiser. */
    if (!anr_validate_config(&config)) {
        fprintf(stderr,
                "Error: unsupported sample rate %d Hz for NR processing "
                "(supported: 8000, 16000, 48000 Hz)\n", sample_rate);
        wav_close_write(wav_out);
        free(signal);
        return 1;
    }

    const int frame_size = config.frame_size;
    const int hop        = config.hop_size;
    const int fft_size   = config.fft_size;
    const int n_freqs    = fft_size / 2 + 1;

    AnrDenoiser* denoiser = anr_create(&config);
    FftHandle*       fft      = fft_create(fft_size);
    if (!denoiser || !fft) {
        fprintf(stderr, "Error: Failed to create denoiser/FFT\n");
        if (denoiser) anr_destroy(denoiser);
        if (fft) fft_destroy(fft);
        wav_close_write(wav_out);
        free(signal);
        return 1;
    }

    const char *mode_names[] = {"mild", "moderate", "balanced", "aggressive"};
    printf("\nDenoiser configuration (freq-domain runner):\n");
    printf("  NR mode: %s\n", mode_names[nr_mode]);
    printf("  Frame size: %d samples (%.1f ms)\n", frame_size, frame_size * 1000.0f / sample_rate);
    printf("  Hop size: %d samples (%.1f ms)\n", hop, hop * 1000.0f / sample_rate);
    printf("  FFT size: %d  Frequency bins: %d\n", fft_size, n_freqs);
    printf("  Window: sqrt(periodic Hann), sqrt-Hann^2 @ 50%% = COLA\n");

    /* 5. Framing: n_frames = max(1, ceil(max(N - frame, 0) / hop) + 1); the last frame is
     *    zero-padded. */
    int n_frames;
    if (n_samples <= frame_size) {
        n_frames = 1;
    } else {
        n_frames = (n_samples - frame_size + hop - 1) / hop + 1;
    }

    int out_len = (n_frames - 1) * hop + frame_size;  /* OLA length before crop */
    float* out_ola = (float*)calloc(out_len, sizeof(float));
    float* win      = (float*)malloc(frame_size * sizeof(float));
    float* frame_buf = (float*)malloc(fft_size  * sizeof(float));  /* windowed + zero-pad to fft */
    float* time_out  = (float*)malloc(fft_size  * sizeof(float));  /* iFFT output [fft_size] */
    Complex* spec_in  = (Complex*)malloc(n_freqs * sizeof(Complex));
    Complex* spec_out = (Complex*)malloc(n_freqs * sizeof(Complex));

    if (!out_ola || !win || !frame_buf || !time_out || !spec_in || !spec_out) {
        fprintf(stderr, "Error: Memory allocation failed\n");
        free(out_ola); free(win); free(frame_buf); free(time_out);
        free(spec_in); free(spec_out);
        anr_destroy(denoiser); fft_destroy(fft);
        wav_close_write(wav_out); free(signal);
        return 1;
    }

    build_sqrt_hann(win, frame_size);

    /* 6. Per-frame: window -> rFFT -> anr_process -> iFFT -> window -> OLA. */
    printf("\nProcessing %d frames...\n", n_frames);
    int debug_last_sec = -1;
    for (int f = 0; f < n_frames; f++) {
        int start = f * hop;

        /* Analysis window + zero-pad to fft_size (frame==fft here, no pad). */
        for (int n = 0; n < frame_size; n++) {
            int idx = start + n;
            float s = (idx < n_samples) ? signal[idx] : 0.0f;  /* zero-pad tail */
            frame_buf[n] = s * win[n];
        }
        for (int n = frame_size; n < fft_size; n++) frame_buf[n] = 0.0f;

        /* Forward rFFT -> Complex[n_freqs]. */
        fft_forward(fft, frame_buf, spec_in);

        /* NR core: apply per-bin gain to the complex spectrum (phase preserved). */
        if (anr_process(denoiser, spec_in, spec_out) < 0) {
            fprintf(stderr, "Error: anr_process failed at frame %d\n", f);
            break;
        }

        /* Inverse FFT -> time domain [fft_size], take first frame_size. */
        fft_inverse(fft, spec_out, time_out);

        /* Synthesis window (sqrt-Hann) + overlap-add. */
        for (int n = 0; n < frame_size; n++) {
            out_ola[start + n] += time_out[n] * win[n];
        }

        if ((f % 100) == 0) {
            printf("\r  Progress: %.1f%%", 100.0f * (f + 1) / n_frames);
            fflush(stdout);
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
    printf("\r  Progress: 100.0%%\n");

    /* 7. Crop to original input length and write. */
    int write_len = (out_len < n_samples) ? out_len : n_samples;
    wav_write_float(wav_out, out_ola, write_len);

    printf("\nDone!\n");
    printf("  Input samples: %d\n", n_samples);
    printf("  Output samples: %d\n", write_len);
    printf("  Frames processed: %d\n", n_frames);
    printf("Output: %s\n", output_path);

    /* 8. Cleanup. */
    free(out_ola); free(win); free(frame_buf); free(time_out);
    free(spec_in); free(spec_out);
    free(signal);
    anr_destroy(denoiser);
    fft_destroy(fft);
    wav_close_write(wav_out);

    return 0;
}
