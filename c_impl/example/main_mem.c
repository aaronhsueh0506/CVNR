/**
 * main_mem.c - MMSE-LSA Denoiser Example (Hardware Memory / PCM Streaming)
 *
 * Demonstrates chunk-based PCM processing using pre-allocated memory buffers.
 * Adapted for Novatek embedded platform pattern (hd_common_mem).
 *
 * Compile with -DUSE_EXT_MEM to use external memory allocation for denoiser.
 *
 * Memory layout:
 *   share_mem[0] = PCM input  chunk (CHUNK_SIZE * sizeof(INT16))
 *   share_mem[1] = PCM output chunk (CHUNK_SIZE * sizeof(INT16))
 *   share_mem[2] = Denoiser internal buffers (USE_EXT_MEM only)
 *
 * Note: Input/output are raw 16-bit signed PCM (no WAV header).
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"

/* ========================================================================== */
/* Platform types — replace with your platform's actual typedefs             */
/* ========================================================================== */

typedef uint32_t UINT32;
typedef uint8_t  UINT8;
typedef int16_t  INT16;
typedef uintptr_t UINTPTR;
typedef char     CHAR;

/* ========================================================================== */
/* Memory range — matches Novatek hd_common_mem pattern                      */
/*                                                                            */
/* Real platform struct also has:                                             */
/*   HD_COMMON_MEM_VB_BLK blk;    // block handle for release                */
/* ========================================================================== */

typedef struct {
    UINTPTR va;         ///< Virtual address (CPU accessible)
    UINTPTR addr;       ///< Physical address (for DMA)
    UINT32  size;       ///< Buffer size in bytes
    /* HD_COMMON_MEM_VB_BLK blk; */  /* uncomment on real platform */
} MEM_RANGE;

#define CHUNK_SIZE      160     /* hop_size: 16kHz * 10ms = 160 samples */
#define DEFAULT_SRATE   16000

#ifdef USE_EXT_MEM
#define NUM_MEM_BLOCKS  3       /* [0]=input, [1]=output, [2]=denoiser */
#else
#define NUM_MEM_BLOCKS  2       /* [0]=input, [1]=output */
#endif

/* ========================================================================== */
/* Memory allocation — platform stub                                         */
/*                                                                            */
/* On real platform, replace calloc with:                                     */
/*   blk = hd_common_mem_get_block(HD_COMMON_MEM_USER_BLK, size, ddr_id);    */
/*   pa  = hd_common_mem_blk2pa(blk);                                        */
/*   va  = hd_common_mem_mmap(HD_COMMON_MEM_MEM_TYPE_CACHE, pa, size);       */
/* ========================================================================== */

static void share_memory_init(MEM_RANGE *p_mem, int count, UINT32 *sizes)
{
    for (int i = 0; i < count; i++) {
        p_mem[i].va   = 0;
        p_mem[i].addr = 0;
        p_mem[i].size = 0;
    }

    for (int i = 0; i < count; i++) {
        /* --- Platform: replace with hd_common_mem_get_block + mmap --- */
        /*
         * blk = hd_common_mem_get_block(HD_COMMON_MEM_USER_BLK, sizes[i], DDR_ID0);
         * pa  = hd_common_mem_blk2pa(blk);
         * va  = (UINTPTR)hd_common_mem_mmap(HD_COMMON_MEM_MEM_TYPE_CACHE, pa, sizes[i]);
         * p_mem[i].blk  = blk;
         * p_mem[i].addr = pa;
         * p_mem[i].va   = va;
         */
        void *buf = calloc(1, sizes[i]);
        if (!buf) {
            printf("err: calloc %d bytes fail\r\n", sizes[i]);
            return;
        }
        p_mem[i].va   = (UINTPTR)buf;
        p_mem[i].addr = 0;
        p_mem[i].size = sizes[i];
    }
}

static void share_memory_exit(MEM_RANGE *p_mem, int count)
{
    for (int i = 0; i < count; i++) {
        if (p_mem[i].va) {
            /* --- Platform: replace with hd_common_mem_munmap + release_block --- */
            /*
             * hd_common_mem_munmap((void *)p_mem[i].va, p_mem[i].size);
             * hd_common_mem_release_block(p_mem[i].blk);
             */
            free((void *)p_mem[i].va);
            p_mem[i].va   = 0;
            p_mem[i].addr = 0;
            p_mem[i].size = 0;
        }
    }
}

/* ========================================================================== */
/* PCM conversion                                                             */
/* ========================================================================== */

static void pcm16_to_float(const INT16 *in, float *out, int n)
{
    for (int i = 0; i < n; i++)
        out[i] = (float)in[i] / 32768.0f;
}

static void float_to_pcm16(const float *in, INT16 *out, int n)
{
    for (int i = 0; i < n; i++) {
        float s = in[i] * 32767.0f;
        if (s > 32767.0f)  s = 32767.0f;
        if (s < -32768.0f) s = -32768.0f;
        out[i] = (INT16)s;
    }
}

/* ========================================================================== */
/* Main                                                                       */
/* ========================================================================== */

int main(int argc, char *argv[])
{
    const char *in_path  = "/mnt/sd/input.pcm";   /* TODO: change to actual path */
    const char *out_path = "/mnt/sd/output.pcm";
    int sample_rate = DEFAULT_SRATE;
    int bypass = 0;
    MmseLsaNrMode nr_mode = MMSE_LSA_NR_BALANCED;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--bypass") == 0) {
            bypass = 1;
        } else if (strcmp(argv[i], "--nr-mode") == 0 && i + 1 < argc) {
            int m = atoi(argv[++i]);
            nr_mode = (m >= 0 && m <= 2) ? (MmseLsaNrMode)m : MMSE_LSA_NR_BALANCED;
        } else if (strcmp(argv[i], "--sr") == 0 && i + 1 < argc) {
            sample_rate = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0) {
            printf("Usage: %s [options]\n", argv[0]);
            printf("Options:\n");
            printf("  --bypass       Bypass mode (no processing)\n");
            printf("  --nr-mode <n>  0=mild, 1=balanced(default), 2=aggressive\n");
            printf("  --sr <rate>    Sample rate (default: %d)\n", DEFAULT_SRATE);
            return 0;
        }
    }

    /* ---- Open files ---- */
    FILE *fd_in = fopen(in_path, "rb");
    if (!fd_in) {
        printf("cannot read %s\r\n", in_path);
        return 1;
    }

    FILE *fd_out = fopen(out_path, "wb");
    if (!fd_out) {
        printf("cannot write %s\r\n", out_path);
        fclose(fd_in);
        return 1;
    }

    /* ---- Get file size for progress ---- */
    fseek(fd_in, 0, SEEK_END);
    UINT32 file_size = (UINT32)ftell(fd_in);
    fseek(fd_in, 0, SEEK_SET);
    UINT32 total_samples = file_size / sizeof(INT16);

    printf("Input:  %s (%d samples, %.2f sec)\n",
           in_path, total_samples, (float)total_samples / sample_rate);

    if (bypass)
        printf("\n*** BYPASS MODE - no processing ***\n\n");

    /* ---- Prepare config (needed for memory query) ---- */
    MmseLsaConfig config = mmse_lsa_config_for_mode(sample_rate, nr_mode);

    /* ---- Allocate shared memory ---- */
    MEM_RANGE share_mem[NUM_MEM_BLOCKS];
    UINT32 chunk_bytes = CHUNK_SIZE * sizeof(INT16);  /* 320 bytes */

    UINT32 mem_sizes[NUM_MEM_BLOCKS];
    mem_sizes[0] = chunk_bytes;   /* PCM input  */
    mem_sizes[1] = chunk_bytes;   /* PCM output */
#ifdef USE_EXT_MEM
    mem_sizes[2] = (!bypass) ? (UINT32)mmse_lsa_query_memsize(&config) : 0;
    printf("Denoiser memory: %u bytes\n", mem_sizes[2]);
#endif

    share_memory_init(share_mem, NUM_MEM_BLOCKS, mem_sizes);

    INT16 *pcm_in  = (INT16 *)share_mem[0].va;
    INT16 *pcm_out = (INT16 *)share_mem[1].va;

    /* ---- Create denoiser ---- */
    MmseLsaDenoiser *denoiser = NULL;
    float in_buf[CHUNK_SIZE];
    float out_buf[CHUNK_SIZE];

    if (!bypass) {
#ifdef USE_EXT_MEM
        /* External memory: denoiser uses share_mem[2] */
        denoiser = mmse_lsa_create(&config,
                                    (void *)share_mem[2].va,
                                    (size_t)share_mem[2].size);
#else
        /* Standard: denoiser uses internal calloc */
        denoiser = mmse_lsa_create(&config);
#endif
        if (!denoiser) {
            printf("err: create denoiser fail\r\n");
            fclose(fd_in);
            fclose(fd_out);
            share_memory_exit(share_mem, NUM_MEM_BLOCKS);
            return 1;
        }

        const char *mode_names[] = {"mild", "balanced", "aggressive"};
        int hop_size = mmse_lsa_get_hop_size(denoiser);
        printf("Denoiser: mode=%s, hop=%d, frame=%d, fft=%d, latency=%d samples\n",
               mode_names[nr_mode],
               hop_size,
               mmse_lsa_get_frame_size(denoiser),
               config.fft_size,
               mmse_lsa_get_latency(denoiser));
    }

    /* ---- Chunk-by-chunk processing ---- */
    UINT32 processed = 0;
    UINT32 n;

    while ((n = fread(pcm_in, sizeof(INT16), CHUNK_SIZE, fd_in)) > 0) {

        /* --- Platform: invalidate input cache (HW wrote → CPU reads) --- */
        /* hd_common_mem_flush_cache((VOID *)share_mem[0].va, chunk_bytes); */

        if (bypass) {
            /* Bypass: copy input directly to output */
            memcpy(pcm_out, pcm_in, n * sizeof(INT16));
        } else {
            /* INT16 → float */
            pcm16_to_float(pcm_in, in_buf, n);
            if (n < CHUNK_SIZE)
                memset(&in_buf[n], 0, (CHUNK_SIZE - n) * sizeof(float));

            /* Denoise */
            mmse_lsa_process(denoiser, in_buf, out_buf);

            /* float → INT16 */
            float_to_pcm16(out_buf, pcm_out, n);
        }

        /* --- Platform: flush output cache (CPU wrote → HW reads) --- */
        /* hd_common_mem_flush_cache((VOID *)share_mem[1].va, chunk_bytes); */

        /* Write chunk */
        fwrite(pcm_out, sizeof(INT16), n, fd_out);

        processed += n;

        /* Progress */
        if ((processed / CHUNK_SIZE) % 100 == 0) {
            printf("\r  Progress: %.1f%%",
                   (float)processed / total_samples * 100.0f);
            fflush(stdout);
        }
    }

    /* Flush tail (OLA delay) — skip if bypass */
    if (!bypass) {
        memset(in_buf, 0, sizeof(in_buf));
        for (int i = 0; i < 3; i++) {
            mmse_lsa_process(denoiser, in_buf, out_buf);
            float_to_pcm16(out_buf, pcm_out, CHUNK_SIZE);
            fwrite(pcm_out, sizeof(INT16), CHUNK_SIZE, fd_out);
        }
    }

    printf("\r  Progress: 100.0%%\n");
    printf("Output: %s (%d samples processed)\n", out_path, processed);

    /* ---- Cleanup ---- */
    if (denoiser) mmse_lsa_destroy(denoiser);
    fclose(fd_in);
    fclose(fd_out);
    share_memory_exit(share_mem, NUM_MEM_BLOCKS);

    return 0;
}
