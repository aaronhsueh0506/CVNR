/**
 * main.c - MMSE-LSA Denoiser Example
 *
 * Demonstrates streaming processing with hop_size based I/O
 *
 * Usage: denoise_wav <input.wav> <output.wav> [sample_rate]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "wav_io.h"

void print_usage(const char* prog) {
    printf("MMSE-LSA Speech Denoiser (V3-2 C Implementation)\n");
    printf("\n");
    printf("Usage: %s <input.wav> <output.wav> [sample_rate]\n", prog);
    printf("\n");
    printf("Arguments:\n");
    printf("  input.wav    Input noisy WAV file\n");
    printf("  output.wav   Output denoised WAV file\n");
    printf("  sample_rate  Target sample rate (default: use input rate)\n");
    printf("\n");
    printf("Supported input formats:\n");
    printf("  - 16-bit PCM WAV\n");
    printf("  - 32-bit float WAV\n");
    printf("  - Mono or stereo (first channel used)\n");
    printf("\n");
    printf("Example:\n");
    printf("  %s noisy.wav clean.wav\n", prog);
    printf("  %s noisy.wav clean.wav 16000\n", prog);
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        print_usage(argv[0]);
        return 1;
    }

    const char* input_path = argv[1];
    const char* output_path = argv[2];
    int target_sample_rate = 0;

    if (argc >= 4) {
        target_sample_rate = atoi(argv[3]);
    }

    // 1. Open input WAV
    WavReader* wav_in = wav_open_read(input_path);
    if (!wav_in) {
        fprintf(stderr, "Error: Cannot open input file: %s\n", input_path);
        return 1;
    }

    int sample_rate = wav_in->info.sample_rate;
    if (target_sample_rate > 0 && target_sample_rate != sample_rate) {
        fprintf(stderr, "Warning: Resampling not implemented. Using input rate %d Hz\n",
                sample_rate);
    }

    printf("Input: %s\n", input_path);
    printf("  Sample rate: %d Hz\n", sample_rate);
    printf("  Channels: %d\n", wav_in->info.channels);
    printf("  Bits per sample: %d\n", wav_in->info.bits_per_sample);
    printf("  Duration: %.2f sec\n",
           (float)wav_in->info.num_samples / sample_rate);

    // 2. Create denoiser with default config
    MmseLsaConfig config = mmse_lsa_default_config(sample_rate);

    // Enable eta scene change detection and soft VAD for testing
    config.enable_eta = true;
    config.enable_soft_vad = true;

    MmseLsaDenoiser* denoiser = mmse_lsa_create(&config);

    if (!denoiser) {
        fprintf(stderr, "Error: Failed to create denoiser\n");
        wav_close_read(wav_in);
        return 1;
    }

    int hop_size = mmse_lsa_get_hop_size(denoiser);
    int frame_size = mmse_lsa_get_frame_size(denoiser);
    int n_freqs = mmse_lsa_get_n_freqs(denoiser);

    printf("\nDenoiser configuration:\n");
    printf("  Frame size: %d samples (%.1f ms)\n",
           frame_size, frame_size * 1000.0f / sample_rate);
    printf("  Hop size: %d samples (%.1f ms)\n",
           hop_size, hop_size * 1000.0f / sample_rate);
    printf("  FFT size: %d\n", config.fft_size);
    printf("  Frequency bins: %d\n", n_freqs);
    printf("  Latency: %d samples (%.1f ms)\n",
           mmse_lsa_get_latency(denoiser),
           mmse_lsa_get_latency(denoiser) * 1000.0f / sample_rate);

    // 3. Open output WAV
    WavWriter* wav_out = wav_open_write(output_path, sample_rate, 1);
    if (!wav_out) {
        fprintf(stderr, "Error: Cannot open output file: %s\n", output_path);
        mmse_lsa_destroy(denoiser);
        wav_close_read(wav_in);
        return 1;
    }

    // 4. Allocate buffers
    float* buf_in = (float*)malloc(hop_size * sizeof(float));
    float* buf_out = (float*)malloc(hop_size * sizeof(float));

    if (!buf_in || !buf_out) {
        fprintf(stderr, "Error: Memory allocation failed\n");
        if (buf_in) free(buf_in);
        if (buf_out) free(buf_out);
        mmse_lsa_destroy(denoiser);
        wav_close_read(wav_in);
        wav_close_write(wav_out);
        return 1;
    }

    // 5. Streaming processing
    printf("\nProcessing...\n");

    int total_in = 0;
    int total_out = 0;
    int frames_processed = 0;
    int frames_read;

    while ((frames_read = wav_read_float(wav_in, buf_in, hop_size)) > 0) {
        total_in += frames_read;

        // Zero-pad if not enough samples
        if (frames_read < hop_size) {
            memset(buf_in + frames_read, 0,
                   (hop_size - frames_read) * sizeof(float));
        }

        // Process hop_size samples
        int ret = mmse_lsa_process(denoiser, buf_in, buf_out);
        if (ret < 0) {
            fprintf(stderr, "Error: Processing failed with code %d\n", ret);
            break;
        }

        // Write output
        wav_write_float(wav_out, buf_out, hop_size);
        total_out += hop_size;
        frames_processed++;

        // Progress indicator
        if (frames_processed % 100 == 0) {
            float progress = (float)total_in / wav_in->info.num_samples * 100.0f;
            printf("\r  Progress: %.1f%%", progress);
            fflush(stdout);
        }
    }

    // Flush remaining samples (process a few more frames to get tail)
    memset(buf_in, 0, hop_size * sizeof(float));
    for (int i = 0; i < 3; i++) {  // Flush with silence
        mmse_lsa_process(denoiser, buf_in, buf_out);
        wav_write_float(wav_out, buf_out, hop_size);
        total_out += hop_size;
    }

    printf("\r  Progress: 100.0%%\n");
    printf("\nDone!\n");
    printf("  Input samples: %d\n", total_in);
    printf("  Output samples: %d\n", total_out);
    printf("  Frames processed: %d\n", frames_processed);
    printf("Output: %s\n", output_path);

    // 6. Cleanup
    free(buf_in);
    free(buf_out);
    mmse_lsa_destroy(denoiser);
    wav_close_read(wav_in);
    wav_close_write(wav_out);

    return 0;
}
