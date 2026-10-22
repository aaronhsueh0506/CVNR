/* Ordered scalar minimum: exact bits, including NaN payloads and zero ties. The NEON minimum takes
 * a lane-wise fast path and falls back to the scalar rule for NaN or a zero minimum; both paths
 * must reproduce the independent reference below for every array. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../src/noise_estimator.c"

static uint32_t rng = 123;

static uint32_t random_bits(void) {
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

static float from_bits(uint32_t bits) {
    float value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

static uint32_t to_bits(float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

static float scalar_minimum(const float* values, int n) {
    float result = values[0];
    for (int i = 1; i < n; ++i)
        if (values[i] < result) result = values[i];
    return result;
}

/* Finite non-zero value of random sign, magnitude from a log-uniform range, sometimes subnormal. */
static float random_nonzero(void) {
    uint32_t r = random_bits();
    uint32_t exponent = (r >> 8) % 60u + 70u;          /* 2^-57 .. 2^2 */
    uint32_t bits = (exponent << 23) | (random_bits() & 0x007fffffu);
    if ((r & 0xfu) == 0) bits = random_bits() & 0x007fffffu;   /* subnormal or zero */
    if ((bits & 0x7fffffffu) == 0) bits = 1u;
    if (r & 0x80u) bits |= 0x80000000u;
    return from_bits(bits);
}

typedef struct { unsigned long arrays, fast, fallback; } Counts;

static int check(const float* values, int n, const char* what, int trial, Counts* c) {
    float reference = scalar_minimum(values, n);
    float actual = noise_estimator_min_ordered(values, n);
    float twin = skr_min_ordered_scalar(values, n);
    if (to_bits(reference) != to_bits(actual) || to_bits(reference) != to_bits(twin)) {
        fprintf(stderr, "ordered minimum FAIL: class=%s n=%d trial=%d reference=%08x dispatch=%08x scalar=%08x\n",
                what, n, trial, to_bits(reference), to_bits(actual), to_bits(twin));
        return 1;
    }
#if SK_HAVE_NEON
    {
        float fast = 0.0f;
        float neon = skr_min_ordered_neon(values, n);
        if (to_bits(neon) != to_bits(reference)) {
            fprintf(stderr, "ordered minimum FAIL: class=%s n=%d trial=%d reference=%08x neon=%08x\n",
                    what, n, trial, to_bits(reference), to_bits(neon));
            return 1;
        }
        if (skr_min_ordered_fast_neon(values, n, &fast)) {
            ++c->fast;
            if (to_bits(fast) != to_bits(reference)) {
                fprintf(stderr, "ordered minimum FAIL: class=%s n=%d trial=%d fast path %08x != %08x\n",
                        what, n, trial, to_bits(fast), to_bits(reference));
                return 1;
            }
        } else {
            ++c->fallback;
        }
    }
#else
    (void)c;
#endif
    ++c->arrays;
    return 0;
}

int main(void) {
    const uint32_t special[] = {0u, 0x80000000u, 1u, 0x80000001u,
        0x3f800000u, 0xbf800000u, 0x7f800000u, 0xff800000u,
        0x7fc00000u, 0xffc00000u, 0x7f800001u, 0x7fc12345u};
    enum { MAX_N = 257, OFFSETS = 4 };
    float storage[MAX_N + OFFSETS];
    Counts counts = {0, 0, 0};
    for (int n = 1; n <= MAX_N; ++n) {
        for (int trial = 0; trial < 2400; ++trial) {
            float* values = storage + (trial % OFFSETS);   /* unaligned starts */
            const char* what;
            int cls = trial / 400;
            if (cls == 0) {                 /* random bit patterns, NaN included */
                what = "random-bits";
                for (int i = 0; i < n; ++i) values[i] = from_bits(random_bits());
            } else if (cls == 1) {          /* special pool: zeros, NaN payloads, infinities */
                what = "special-pool";
                for (int i = 0; i < n; ++i)
                    values[i] = from_bits(special[random_bits() % (sizeof(special) / sizeof(special[0]))]);
            } else if (cls == 2) {          /* finite non-zero values (fast path) with infinities */
                what = "finite-nonzero";
                for (int i = 0; i < n; ++i) {
                    values[i] = random_nonzero();
                    if ((random_bits() & 31u) == 0) values[i] = (random_bits() & 1u) ? from_bits(0x7f800000u) : from_bits(0xff800000u);
                }
            } else if (cls == 3) {          /* power-like positives with a repeated minimum and zeros above a negative */
                what = "positive-ties";
                float low = from_bits(0x3f800000u + (random_bits() & 0xffffu));
                for (int i = 0; i < n; ++i) values[i] = low * (1.0f + (float)(random_bits() & 1023u));
                int copies = 1 + (int)(random_bits() % 3u);
                for (int k = 0; k < copies; ++k) values[random_bits() % (uint32_t)n] = low;
                if (trial & 1) values[random_bits() % (uint32_t)n] = -low;   /* negative minimum */
                if (trial & 2) values[random_bits() % (uint32_t)n] = (trial & 4) ? 0.0f : from_bits(0x80000000u);
            } else if (cls == 4) {          /* zero minimum or mixed-sign zeros (scalar rule) */
                what = "zero-minimum";
                for (int i = 0; i < n; ++i) values[i] = 1.0f + (float)(random_bits() & 255u);
                for (int k = 0; k < 1 + (int)(random_bits() % 3u); ++k)
                    values[random_bits() % (uint32_t)n] = (random_bits() & 1u) ? 0.0f : from_bits(0x80000000u);
            } else {                        /* one NaN or sNaN anywhere (including index 0) in finite data */
                what = "single-nan";
                for (int i = 0; i < n; ++i) values[i] = random_nonzero();
                values[random_bits() % (uint32_t)n] = from_bits((random_bits() & 1u) ? 0x7fc00000u : 0xffc12345u);
            }
            if (check(values, n, what, trial, &counts)) return 1;
        }
    }
    printf("ordered minimum PASS: %lu arrays; random bits, NaN, signed zero, infinity, subnormal, ties, unaligned starts; NEON=%d fast-path=%lu fallback=%lu\n",
           counts.arrays, SK_HAVE_NEON, counts.fast, counts.fallback);
    return 0;
}
