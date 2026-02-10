#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

// 設定參數
#define SAMPLE_RATE     16000   // 取樣率 (Hz)
#define FRAME_MS        20      // 幀長度 (ms)
#define SAMPLES_PER_FRAME (SAMPLE_RATE * FRAME_MS / 1000)  // 每幀樣本數 (320 @ 16kHz, 20ms)

/**
 * 讀取 PCM 音檔並逐幀處理
 *
 * PCM 格式假設：16-bit signed, mono, little-endian
 */
int main(int argc, char *argv[]) {
    FILE *fp = NULL;
    int16_t buffer[SAMPLES_PER_FRAME];
    size_t samples_read;
    int frame_count = 0;
    long total_samples = 0;

    // 檢查參數
    if (argc < 2) {
        printf("Usage: %s <input.pcm>\n", argv[0]);
        printf("\nExpected format: 16-bit signed, mono, %d Hz\n", SAMPLE_RATE);
        printf("Frame size: %d ms (%d samples)\n", FRAME_MS, SAMPLES_PER_FRAME);
        return 1;
    }

    // 開啟檔案
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        printf("Error: Cannot open file '%s'\n", argv[1]);
        return 1;
    }

    // 取得檔案大小
    fseek(fp, 0, SEEK_END);
    long file_size = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    long total_samples_in_file = file_size / sizeof(int16_t);
    double duration_sec = (double)total_samples_in_file / SAMPLE_RATE;

    printf("File: %s\n", argv[1]);
    printf("Size: %ld bytes\n", file_size);
    printf("Duration: %.2f seconds\n", duration_sec);
    printf("Processing with %d ms frames (%d samples/frame)...\n\n", FRAME_MS, SAMPLES_PER_FRAME);

    // 逐幀讀取
    while ((samples_read = fread(buffer, sizeof(int16_t), SAMPLES_PER_FRAME, fp)) > 0) {
        frame_count++;
        total_samples += samples_read;

        // ========================================
        // Do something heres
        // ========================================

        // 計算這一幀的一些基本資訊（示範用）
        int16_t max_val = 0;
        int16_t min_val = 0;
        int64_t sum = 0;

        for (size_t i = 0; i < samples_read; i++) {
            if (buffer[i] > max_val) max_val = buffer[i];
            if (buffer[i] < min_val) min_val = buffer[i];
            sum += buffer[i];
        }

        double avg = (double)sum / samples_read;
        double time_ms = (double)(total_samples - samples_read) * 1000 / SAMPLE_RATE;

        // 每 50 幀輸出一次狀態（避免輸出過多）
        if (frame_count % 50 == 0 || samples_read < SAMPLES_PER_FRAME) {
            printf("Frame %4d | Time: %7.1f ms | Samples: %3zu | Max: %6d | Min: %6d | Avg: %7.1f\n",
                   frame_count, time_ms, samples_read, max_val, min_val, avg);
        }

        // 如果讀取的樣本數少於預期，表示是最後一幀（可能不完整）
        if (samples_read < SAMPLES_PER_FRAME) {
            printf("\n[Last frame is incomplete: %zu/%d samples]\n", samples_read, SAMPLES_PER_FRAME);
        }
    }

    // 關閉檔案
    fclose(fp);

    // 輸出總結
    printf("\n========================================\n");
    printf("Processing complete!\n");
    printf("Total frames: %d\n", frame_count);
    printf("Total samples: %ld\n", total_samples);
    printf("Duration processed: %.3f seconds\n", (double)total_samples / SAMPLE_RATE);
    printf("========================================\n");

    return 0;
}
