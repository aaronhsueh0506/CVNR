/* NRP2 header limits of the offline gain runners (example/nrp2_io.h): a header whose gain table
 * n_frames * n_freqs * sizeof(float) does not fit in size_t is rejected before any runner
 * allocates it. A 64-bit host cannot wrap that product, so NRP2_SIZE_LIMIT stands in for a 32-bit
 * size_t: the helper and nrp2_read_header() are both checked against it. The last block lifts the
 * limit to check the int range of fft_size. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define LIMIT32 0xFFFFFFFFu
static size_t g_size_limit = LIMIT32;
#define NRP2_SIZE_LIMIT g_size_limit
#include "../example/nrp2_io.h"

static int g_fail = 0;
#define CHECK(cond, ...) do { if (!(cond)) { printf("FAIL: "); printf(__VA_ARGS__); printf("\n"); g_fail = 1; } } while (0)

/* Writes an 'NRP2' header into a temporary file and reads it back. */
static Nrp2Status read_header(int32_t n_frames, int32_t n_freqs, int32_t sample_rate, Nrp2Header* h) {
    const int32_t v[4] = {NRP2_MAGIC, n_frames, n_freqs, sample_rate};
    FILE* f = tmpfile();
    Nrp2Status st;
    if (!f || fwrite(v, sizeof(int32_t), 4, f) != 4) { printf("FAIL: tmpfile\n"); g_fail = 1; if (f) fclose(f); return NRP2_SHORT_HEADER; }
    rewind(f);
    st = nrp2_read_header(f, 0, h);
    fclose(f);
    return st;
}

int main(void) {
    Nrp2Header h;

    /* The wrap cases of a 32-bit size_t: 2^30 * 129 * 4 == 0 and 266354561 * 129 * 4 == 4 (mod 2^32). */
    CHECK(!nrp2_gains_fit(1 << 30, 129, LIMIT32), "2^30 frames x 129 bins must not fit in 32 bits");
    CHECK(!nrp2_gains_fit(266354561, 129, LIMIT32), "266354561 frames x 129 bins must not fit in 32 bits");
    /* Boundary at n_freqs = 129: 516 bytes per frame, floor(0xFFFFFFFF / 516) = 8323580 frames. */
    CHECK(nrp2_gains_fit(8323580, 129, LIMIT32), "8323580 frames x 129 bins fit in 32 bits");
    CHECK(!nrp2_gains_fit(8323581, 129, LIMIT32), "8323581 frames x 129 bins exceed 32 bits");
    CHECK(!nrp2_gains_fit(1, 0x40000000, LIMIT32), "one frame of 2^30 bins exceeds 32 bits");
    CHECK(nrp2_gains_fit(1, 1025, LIMIT32) && nrp2_gains_fit(100000, 513, LIMIT32), "ordinary tables fit in 32 bits");
    CHECK(!nrp2_gains_fit(0, 129, LIMIT32) && !nrp2_gains_fit(5, 0, LIMIT32) && !nrp2_gains_fit(-1, 129, LIMIT32),
          "non-positive sizes never fit");

    /* The header path, with the same limit. */
    CHECK(read_header(6, 129, 16000, &h) == NRP2_OK && h.n_frames == 6 && h.n_freqs == 129 && h.sample_rate == 16000,
          "an ordinary header is accepted");
    CHECK(read_header(0, 129, 16000, &h) == NRP2_BAD_VALUES, "n_frames 0 is rejected");
    CHECK(read_header(6, 1, 16000, &h) == NRP2_BAD_VALUES, "n_freqs 1 is rejected");
    CHECK(read_header(6, 129, 0, &h) == NRP2_BAD_VALUES, "sample_rate 0 is rejected");
    CHECK(read_header(1 << 30, 129, 16000, &h) == NRP2_BAD_VALUES, "2^30 x 129 header is rejected");
    CHECK(read_header(266354561, 129, 16000, &h) == NRP2_BAD_VALUES, "266354561 x 129 header is rejected");
    CHECK(read_header(8323580, 129, 16000, &h) == NRP2_OK, "the largest table that fits is accepted");
    CHECK(read_header(8323581, 129, 16000, &h) == NRP2_BAD_VALUES, "one frame more is rejected");

    /* fft_size = (n_freqs - 1) * 2 must fit in int, whatever the size_t: 2^30 bins is the most. */
    g_size_limit = SIZE_MAX;
    CHECK(read_header(1, 0x40000000, 16000, &h) == NRP2_OK, "2^30 bins (fft_size 2147483646) is accepted");
    CHECK(read_header(1, 0x40000001, 16000, &h) == NRP2_BAD_VALUES, "2^30 + 1 bins would overflow fft_size");
    CHECK(read_header(1, 0x7FFFFFFF, 16000, &h) == NRP2_BAD_VALUES, "INT_MAX bins would overflow fft_size");

    if (g_fail) { printf("test_nrp2_io: FAIL\n"); return 1; }
    printf("test_nrp2_io: PASS\n");
    return 0;
}
