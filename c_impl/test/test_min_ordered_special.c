/* Ordered scalar minimum: exact bits, including NaN payloads and zero ties. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../src/mcra_noise_estimator.c"

static uint32_t rng = 123;

static uint32_t random_bits(void) {
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

static float scalar_minimum(const float* values, int n) {
    float result = values[0];
    for (int i = 1; i < n; ++i)
        if (values[i] < result) result = values[i];
    return result;
}

int main(void) {
    const uint32_t special[] = {0u, 0x80000000u, 1u, 0x80000001u,
        0x3f800000u, 0xbf800000u, 0x7f800000u, 0xff800000u,
        0x7fc00000u, 0xffc00000u, 0x7f800001u, 0x7fc12345u};
    float values[257];
    unsigned long cases = 0;
    for (int n = 1; n <= 257; ++n) {
        for (int trial = 0; trial < 2000; ++trial) {
            for (int i = 0; i < n; ++i) {
                uint32_t bits = trial < 1000 ? random_bits()
                    : special[random_bits() % (sizeof(special) / sizeof(special[0]))];
                memcpy(values + i, &bits, sizeof(bits));
            }
            float reference = scalar_minimum(values, n);
            float actual = mcra_min_ordered(values, n);
            uint32_t reference_bits, actual_bits;
            memcpy(&reference_bits, &reference, sizeof(reference_bits));
            memcpy(&actual_bits, &actual, sizeof(actual_bits));
            if (reference_bits != actual_bits) {
                fprintf(stderr, "ordered minimum FAIL: n=%d trial=%d %08x != %08x\n",
                        n, trial, reference_bits, actual_bits);
                return 1;
            }
            ++cases;
        }
    }
    printf("ordered minimum PASS: %lu arrays; random bits, NaN, signed zero, infinity, subnormal; NEON=%d\n",
           cases, SK_HAVE_NEON);
    return 0;
}
