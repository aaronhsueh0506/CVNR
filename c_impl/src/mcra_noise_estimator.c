/* MCRA noise tracking (Cohen and Berdugo): S = α_s*S_prev + (1-α_s)*power; S_min is the
 * L-frame minimum; I = [S/(δ*S_min) > 1]; p = α_p*p_prev + (1-α_p)*I; α̃_d = α_d + (1-α_d)*p;
 * N = α̃_d*N_prev + (1-α̃_d)*power.
 */

#include "mcra_noise_estimator.h"
#include "fast_math.h"
#include "fft_wrapper.h"   /* ALIGN16 */
#include "simd_kernels.h"  /* Non-fused, bit-exact SIMD EMA/noise kernels; requires -ffp-contract=off. */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include "anr_internal.h"

/* Below this floor, consumer epsilons dominate the PSD and posterior gating can prevent
 * recovery. Such bins restart with an ungated update.
 */
#define MCRA_NOISE_PSD_INERT 1e-20f

// Internal structure
struct McraNoiseEstimator {
    int n_freqs;
    int L;              // Min tracking window length

    float alpha_s;      // Time smoothing factor
    float alpha_d;      // Noise update base rate
    float alpha_p;      // SPP smoothing factor
    float delta;        // Detection threshold (linear)

    // State arrays [n_freqs]
    float* noise_psd;   // Current noise PSD estimate
    float* S;           // Time-smoothed power spectrum
    float* S_min;       // Minimum tracked values
    float* spp;         // Internal SPP (for min tracking)

    // Minimum tracking buffer [L * n_freqs]
#ifdef USE_OPTIMIZED_MIN_BUFFER
    // Frequency-major layout: min_buffer[freq_idx * L + frame_idx]
    // All L values for the same frequency are contiguous (better cache locality)
#else
    // Frame-major layout: min_buffer[frame_idx * n_freqs + freq_idx]
#endif
    float* min_buffer;
    int ring_idx;       // Current write position in ring buffer

    // Scratch [n_freqs] for the vectorized log pass in spectral_flatness()
    // and the hi-freq scene-change flatness computation -- both are
    // log-sum-exp geometric means over disjoint sub-ranges of `power`
    // within one mcra_update() call, never used concurrently, so one
    // n_freqs-sized buffer (the largest either call needs) covers both.
    float* flatness_scratch;

    bool is_initialized;

    // Scene change detection (hi-freq gamma + spectral flatness)
    float scene_change_threshold;           // Linear threshold for hi-freq gamma
    int scene_change_min_frames;            // Consecutive frames required
    float scene_change_blend;               // Noise reset blend factor
    float scene_change_flatness_threshold;  // Hi-freq flatness threshold
    int scene_change_count;                 // Current consecutive count
    float broadband_threshold;              // Broadband scene-reset gate (<1.0 enables)

#ifndef USE_FAST_PERCENTILE
    // Buffer for exact percentile calculation during initialization
    // Layout: init_power_buffer[frame_idx * n_freqs + freq_idx]
    float* init_power_buffer;
    int num_init_frames;    // Max number of init frames (from config)
    // Per-bin gather + quickselect scratch [num_init_frames] — pre-allocated so
    // the exact-percentile init path never calls malloc (matters on the static
    // memory path).
    float* percentile_scratch;
#endif

    bool is_static;      // 1 == placed via mcra_init() (caller-owned memory);
                         // 0 == heap instance from mcra_create() (owns its mallocs)
};

/* Geometric/arithmetic mean flatness of power[start:end], with +1e-20. Use standard expf at
 * the hard decision threshold. scratch holds end-start floats; SIMD log runs in-place. Both
 * reductions retain increasing-bin scalar order for bit-exactness.
 */
static float spectral_flatness(const float* power, int start, int end, float* scratch) {
    int n = end - start;
    float arith_sum = 0.0f;
    for (int k = 0; k < n; k++) {
        float p = power[start + k] + 1e-20f;
        scratch[k] = p;
        arith_sum += p;
    }
    sk_fast_log_f32(scratch, scratch, n);
    float log_sum = 0.0f;
    for (int k = 0; k < n; k++) log_sum += scratch[k];
    float inv_n = 1.0f / (float)n;
    return expf(log_sum * inv_n) / (arith_sum * inv_n);
}

/* On confirmed scene change, blend noise toward current power and reseed minima from S. */
static void mcra_reset_noise_floor(McraNoiseEstimator* self, const float* power) {
    int n_freqs = self->n_freqs;
    int L = self->L;
    float blend = self->scene_change_blend;
    float one_minus_blend = 1.0f - blend;
    for (int k = 0; k < n_freqs; k++) {
        self->noise_psd[k] = blend * self->noise_psd[k] + one_minus_blend * power[k];
        self->S_min[k] = self->S[k];
    }
#ifdef USE_OPTIMIZED_MIN_BUFFER
    for (int k = 0; k < n_freqs; k++) {
        float* freq_buf = &self->min_buffer[k * L];
        for (int l = 0; l < L; l++) freq_buf[l] = self->S[k];
    }
#else
    for (int l = 0; l < L; l++)
        for (int k = 0; k < n_freqs; k++)
            self->min_buffer[l * n_freqs + k] = self->S[k];
#endif
}

/* Shared scalar initialization; caller zeroes arrays. */
/* Update only tuning scalars; preserve tracker state. L and num_init_frames must already match
 * allocated geometry.
 */
void mcra_apply_config_scalars(McraNoiseEstimator* self,
                               const AnrConfig* config) {
    self->L = config->L;
    self->alpha_s = config->alpha_s;
    self->alpha_d = config->alpha_d;
    self->alpha_p = config->alpha_p;
    self->delta = powf(10.0f, config->delta_db / 10.0f);

    // Scene change detection
    self->scene_change_threshold = powf(10.0f, config->scene_change_threshold_db / 10.0f);
    self->scene_change_min_frames = config->scene_change_min_frames;
    self->scene_change_blend = config->scene_change_blend;
    self->scene_change_flatness_threshold = config->scene_change_flatness_threshold;
    self->broadband_threshold = config->broadband_threshold;

#ifndef USE_FAST_PERCENTILE
    self->num_init_frames = config->num_init_frames;
#endif
}

#ifdef USE_OPTIMIZED_MIN_BUFFER
/* Ordered minimum: start from values[0] and replace on a strict '<'. A NaN never replaces and
 * a NaN in values[0] is never replaced; among equal values the earliest stays, so +0 and -0
 * keep their position-dependent identity.
 */
static inline float mcra_min_ordered_scalar(const float* values, int n) {
    float minimum = values[0];
    for (int i = 1; i < n; ++i)
        if (values[i] < minimum) minimum = values[i];
    return minimum;
}

#if SK_HAVE_NEON
ANR_TWIN float32x4_t mcra_vmin_lt(float32x4_t a, float32x4_t b) {
    return vbslq_f32(vcltq_f32(b, a), b, a);   /* b where b < a, else a */
}

/* Minimum through independent lane-wise running minima, seeded from the first vectors. A NaN
 * after the seed never replaces a minimum, exactly like the scalar rule, so only the seed needs
 * a NaN check. The result equals the ordered minimum whenever the seed holds no NaN and the
 * minimum is not a zero: equal non-zero floats have equal bits, so the order of comparison
 * cannot change it. Returns false (result untouched) otherwise, which needs the scalar rule.
 */
ANR_TWIN bool mcra_min_ordered_fast_neon(const float* values, int n, float* result) {
    if (n < 4) return false;
    float32x4_t a0, a1, a2, a3;
    uint32x4_t seed_valid;
    int i;
    if (n >= 16) {
        a0 = vld1q_f32(values);
        a1 = vld1q_f32(values + 4);
        a2 = vld1q_f32(values + 8);
        a3 = vld1q_f32(values + 12);
        seed_valid = vandq_u32(vandq_u32(vceqq_f32(a0, a0), vceqq_f32(a1, a1)),
                               vandq_u32(vceqq_f32(a2, a2), vceqq_f32(a3, a3)));
        for (i = 16; i + 16 <= n; i += 16) {
            a0 = mcra_vmin_lt(a0, vld1q_f32(values + i));
            a1 = mcra_vmin_lt(a1, vld1q_f32(values + i + 4));
            a2 = mcra_vmin_lt(a2, vld1q_f32(values + i + 8));
            a3 = mcra_vmin_lt(a3, vld1q_f32(values + i + 12));
        }
        a0 = mcra_vmin_lt(a0, a1);
        a2 = mcra_vmin_lt(a2, a3);
        a0 = mcra_vmin_lt(a0, a2);
    } else {
        a0 = vld1q_f32(values);
        seed_valid = vceqq_f32(a0, a0);
        i = 4;
    }
    for (; i + 4 <= n; i += 4) a0 = mcra_vmin_lt(a0, vld1q_f32(values + i));
    a0 = mcra_vmin_lt(a0, vextq_f32(a0, a0, 2));
    a0 = mcra_vmin_lt(a0, vextq_f32(a0, a0, 1));
    float minimum = vgetq_lane_f32(a0, 0);
    for (; i < n; ++i)
        if (values[i] < minimum) minimum = values[i];
    if (vminvq_u32(seed_valid) == 0 || minimum == 0.0f) return false;
    *result = minimum;
    return true;
}

ANR_TWIN float mcra_min_ordered_neon(const float* values, int n) {
    float minimum;
    if (mcra_min_ordered_fast_neon(values, n, &minimum)) return minimum;
    return mcra_min_ordered_scalar(values, n);
}
#endif

ANR_TWIN float mcra_min_ordered(const float* values, int n) {
#if ANR_VECTOR
    return mcra_min_ordered_neon(values, n);
#else
    return mcra_min_ordered_scalar(values, n);
#endif
}
#endif

static void mcra_init_scalars(McraNoiseEstimator* self, int n_freqs,
                              const AnrConfig* config) {
    self->n_freqs = n_freqs;
    mcra_apply_config_scalars(self, config);

    self->ring_idx = 0;
    self->is_initialized = false;
    self->scene_change_count = 0;
}

/* Static allocation. */

size_t mcra_get_mem_size(int n_freqs, const AnrConfig* config) {
    /* Check dimensions and saturating size arithmetic before allocation. */
    if (n_freqs <= 0 || !config) return 0;
    if (config->L <= 0) return 0;
#ifndef USE_FAST_PERCENTILE
    if (config->num_init_frames <= 0) return 0;
#endif

    size_t total = ALIGN16(sizeof(McraNoiseEstimator));
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* noise_psd  */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* S          */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* S_min      */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* spp        */
    total = ck_field_size(total, ck_mul_size((size_t)config->L, (size_t)n_freqs),
                          sizeof(float));                            /* min_buffer */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* flatness_scratch */
#ifndef USE_FAST_PERCENTILE
    total = ck_field_size(total, ck_mul_size((size_t)config->num_init_frames, (size_t)n_freqs),
                          sizeof(float));                            /* init_power_buffer  */
    total = ck_field_size(total, (size_t)config->num_init_frames, sizeof(float)); /* percentile_scratch */
#endif
    return MEM_SIZE_INVALID(total) ? 0 : total;
}

McraNoiseEstimator* mcra_init(void* mem, size_t mem_size,
                              int n_freqs, const AnrConfig* config) {
    if (n_freqs <= 0 || !config || !mem) return NULL;
    /* Reject unaligned memory before writing. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    size_t need = mcra_get_mem_size(n_freqs, config);
    if (need == 0 || mem_size < need) return NULL;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;

    McraNoiseEstimator* self = (McraNoiseEstimator*)cursor;
    cursor += ALIGN16(sizeof(McraNoiseEstimator));

    mcra_init_scalars(self, n_freqs, config);
    self->is_static = true;

    self->noise_psd  = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->S          = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->S_min      = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->spp        = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->min_buffer = (float*)cursor; cursor += ALIGN16((size_t)self->L * n_freqs * sizeof(float));
    self->flatness_scratch = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
#ifndef USE_FAST_PERCENTILE
    self->init_power_buffer = (float*)cursor;
    cursor += ALIGN16((size_t)self->num_init_frames * n_freqs * sizeof(float));
    self->percentile_scratch = (float*)cursor;
    cursor += ALIGN16((size_t)self->num_init_frames * sizeof(float));
#endif

    /* Size query and carve must end at the same byte offset. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    return self;
}

/* Heap allocation. */

McraNoiseEstimator* mcra_create(int n_freqs, const AnrConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    McraNoiseEstimator* self = (McraNoiseEstimator*)calloc(1, sizeof(McraNoiseEstimator));
    if (!self) return NULL;

    mcra_init_scalars(self, n_freqs, config);
    self->is_static = false;

    // Allocate state arrays
    self->noise_psd = (float*)calloc(n_freqs, sizeof(float));
    self->S = (float*)calloc(n_freqs, sizeof(float));
    self->S_min = (float*)calloc(n_freqs, sizeof(float));
    self->spp = (float*)calloc(n_freqs, sizeof(float));

    // Allocate min tracking buffer
    self->min_buffer = (float*)calloc(self->L * n_freqs, sizeof(float));
    self->flatness_scratch = (float*)calloc(n_freqs, sizeof(float));

    if (!self->noise_psd || !self->S || !self->S_min ||
        !self->spp || !self->min_buffer || !self->flatness_scratch) {
        mcra_destroy(self);
        return NULL;
    }

#ifndef USE_FAST_PERCENTILE
    // Allocate buffer for exact percentile calculation + its quickselect scratch
    self->init_power_buffer = (float*)calloc(self->num_init_frames * n_freqs, sizeof(float));
    self->percentile_scratch = (float*)calloc(self->num_init_frames, sizeof(float));
    if (!self->init_power_buffer || !self->percentile_scratch) {
        mcra_destroy(self);
        return NULL;
    }
#endif

    return self;
}

void mcra_destroy(McraNoiseEstimator* self) {
    if (!self) return;
    if (self->is_static) return;  /* caller owns the block; nothing to free */

    if (self->noise_psd) free(self->noise_psd);
    if (self->S) free(self->S);
    if (self->S_min) free(self->S_min);
    if (self->spp) free(self->spp);
    if (self->min_buffer) free(self->min_buffer);
    if (self->flatness_scratch) free(self->flatness_scratch);
#ifndef USE_FAST_PERCENTILE
    if (self->init_power_buffer) free(self->init_power_buffer);
    if (self->percentile_scratch) free(self->percentile_scratch);
#endif

    free(self);
}

#ifndef USE_FAST_PERCENTILE
/* Save initialization power for exact percentile selection. */
void mcra_accumulate_init_power(McraNoiseEstimator* self, const float* power, int frame_idx) {
    if (!self || !power || !self->init_power_buffer) return;
    if (frame_idx < 0 || frame_idx >= self->num_init_frames) return;

    int n_freqs = self->n_freqs;
    int offset = frame_idx * n_freqs;
    memcpy(self->init_power_buffer + offset, power, n_freqs * sizeof(float));
}

/* Partition around the midpoint pivot; returns its final index. */
static int quickselect_partition(float* arr, int left, int right) {
    // Midpoint pivot.
    int mid = left + (right - left) / 2;
    float pivot = arr[mid];

    // Move pivot to end
    float tmp = arr[mid];
    arr[mid] = arr[right];
    arr[right] = tmp;

    int store_idx = left;
    for (int i = left; i < right; i++) {
        if (arr[i] < pivot) {
            tmp = arr[i];
            arr[i] = arr[store_idx];
            arr[store_idx] = tmp;
            store_idx++;
        }
    }

    // Move pivot to its final place
    tmp = arr[store_idx];
    arr[store_idx] = arr[right];
    arr[right] = tmp;

    return store_idx;
}

/* Select the kth smallest value in-place; O(n) average complexity. */
static float quickselect(float* arr, int n, int k) {
    if (n == 1) return arr[0];
    if (k < 0) k = 0;
    if (k >= n) k = n - 1;

    int left = 0;
    int right = n - 1;

    while (left < right) {
        int pivot_idx = quickselect_partition(arr, left, right);

        if (pivot_idx == k) {
            return arr[pivot_idx];
        } else if (pivot_idx < k) {
            left = pivot_idx + 1;
        } else {
            right = pivot_idx - 1;
        }
    }

    return arr[left];
}

/* In-place percentile selection over disposable data[n]; p is in [0,100]. */
static float calculate_percentile(float* data, int n, int p) {
    if (n <= 0) return 0.0f;
    if (n == 1) return data[0];

    // k = floor((n-1) * p / 100)
    int k = ((n - 1) * p) / 100;

    return quickselect(data, n, k);
}
#else
/* No accumulation needed for the fast-percentile path. */
void mcra_accumulate_init_power(McraNoiseEstimator* self, const float* power, int frame_idx) {
    (void)self;
    (void)power;
    (void)frame_idx;
    // No-op when using fast approximation
}
#endif

void mcra_init_noise(McraNoiseEstimator* self, const float* power_sum, int n_frames) {
    if (!self || !power_sum || n_frames <= 0) return;

    int n_freqs = self->n_freqs;

#ifdef USE_FAST_PERCENTILE
    // Low-memory empirical stand-in for the configured 30th percentile.
    for (int k = 0; k < n_freqs; k++) {
        float avg_power = power_sum[k] / (float)n_frames;
        float init_psd = avg_power * 0.23f;

        if (init_psd < 1e-10f) init_psd = 1e-10f;

        self->noise_psd[k] = init_psd;
        self->S[k] = init_psd;
        self->S_min[k] = init_psd;
        self->spp[k] = 0.0f;
    }
#else
    // Exact 30th percentile using quickselect
    // Requires init_power_buffer to be filled via mcra_accumulate_init_power()

    // Per-bin gather + quickselect scratch — pre-allocated, no malloc.
    float* freq_powers = self->percentile_scratch;
    if (!freq_powers) {
        // Fallback to approximation if the scratch is unavailable
        for (int k = 0; k < n_freqs; k++) {
            float avg_power = power_sum[k] / (float)n_frames;
            float init_psd = avg_power * 0.23f;  // Approximate 30th percentile
            if (init_psd < 1e-10f) init_psd = 1e-10f;
            self->noise_psd[k] = init_psd;
            self->S[k] = init_psd;
            self->S_min[k] = init_psd;
            self->spp[k] = 0.0f;
        }
    } else {
        for (int k = 0; k < n_freqs; k++) {
            // Collect power values for this frequency bin across all frames
            for (int f = 0; f < n_frames; f++) {
                freq_powers[f] = self->init_power_buffer[f * n_freqs + k];
            }

            // Exact 30th percentile
            float init_psd = calculate_percentile(freq_powers, n_frames, 30);

            if (init_psd < 1e-10f) init_psd = 1e-10f;

            self->noise_psd[k] = init_psd;
            self->S[k] = init_psd;
            self->S_min[k] = init_psd;
            self->spp[k] = 0.0f;
        }
        // no free — percentile_scratch is owned by the estimator
    }
#endif

    // Fill min_buffer with initial noise estimate
#ifdef USE_OPTIMIZED_MIN_BUFFER
    // Frequency-major layout: [freq_idx * L + frame_idx]
    for (int k = 0; k < n_freqs; k++) {
        float* freq_buf = &self->min_buffer[k * self->L];
        for (int l = 0; l < self->L; l++) {
            freq_buf[l] = self->noise_psd[k];
        }
    }
#else
    // Frame-major layout: [frame_idx * n_freqs + freq_idx]
    for (int l = 0; l < self->L; l++) {
        for (int k = 0; k < n_freqs; k++) {
            self->min_buffer[l * n_freqs + k] = self->noise_psd[k];
        }
    }
#endif

    self->ring_idx = 0;
    self->is_initialized = true;
}

#if defined(USE_OPTIMIZED_MIN_BUFFER) && defined(USE_INCREMENTAL_MIN)
/* Ring write and incremental minimum for bins [0, n): store the new smoothed power S in slot
 * ring_pos of each bin's row (row k starts at ring[k * L]), keep S_min when S is a new minimum,
 * and rescan the row only when the evicted value was at most S_min * (1 + 1e-6).
 */
static inline void mcra_ring_min_elem(float* s_min, float new_s, float* row, int ring_pos,
                                      bool* rescan) {
    float old_val = row[ring_pos];
    row[ring_pos] = new_s;
    *rescan = false;
    if (new_s <= *s_min) {
        *s_min = new_s;
    } else if (old_val <= *s_min * (1.0f + 1e-6f)) {
        *rescan = true;
    }
}

ANR_TWIN void mcra_ring_min_scalar(float* s_min, const float* s,
                                   float* ring, int L, int ring_pos,
                                   int n) {
    for (int k = 0; k < n; k++) {
        bool rescan;
        mcra_ring_min_elem(s_min + k, s[k], ring + (size_t)k * L, ring_pos, &rescan);
        if (rescan) s_min[k] = mcra_min_ordered_scalar(ring + (size_t)k * L, L);
    }
}

#if SK_HAVE_NEON
/* Block of bins processed before the deferred rescans; bounds the pending-bin list. */
#define MCRA_RING_BLOCK 128

/* Per 4-bit lane mask: ascending numbers of the set lanes (unused entries 0) and their count. */
static const uint16_t mcra_lane_list[16][4] = {
    {0, 0, 0, 0}, {0, 0, 0, 0}, {1, 0, 0, 0}, {0, 1, 0, 0},
    {2, 0, 0, 0}, {0, 2, 0, 0}, {1, 2, 0, 0}, {0, 1, 2, 0},
    {3, 0, 0, 0}, {0, 3, 0, 0}, {1, 3, 0, 0}, {0, 1, 3, 0},
    {2, 3, 0, 0}, {0, 2, 3, 0}, {1, 2, 3, 0}, {0, 1, 2, 3}};
static const uint8_t mcra_lane_count[16] = {0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4};

/* Same result as the scalar twin (except the payload bits of a NaN): the compare and select run
 * on four bins at once, the bins that need a rescan are collected without a data-dependent
 * branch and rescanned after each block.
 */
ANR_TWIN void mcra_ring_min_neon(float* s_min, const float* s, float* ring, int L,
                                 int ring_pos, int n) {
    const float32x4_t growth = vdupq_n_f32(1.0f + 1e-6f);
    const uint32_t lane_bits[4] = {1u, 2u, 4u, 8u};
    const uint32x4_t weights = vld1q_u32(lane_bits);
    uint16_t pending[MCRA_RING_BLOCK + 4];
    for (int base = 0; base < n; base += MCRA_RING_BLOCK) {
        const int end = base + MCRA_RING_BLOCK < n ? base + MCRA_RING_BLOCK : n;
        int count = 0;
        int k = base;
        for (; k + 4 <= end; k += 4) {
            float* p0 = ring + (size_t)k * L + ring_pos;
            float* p1 = p0 + L;
            float* p2 = p1 + L;
            float* p3 = p2 + L;
            float32x4_t old_val = vld1q_lane_f32(p0, vdupq_n_f32(0.0f), 0);
            old_val = vld1q_lane_f32(p1, old_val, 1);
            old_val = vld1q_lane_f32(p2, old_val, 2);
            old_val = vld1q_lane_f32(p3, old_val, 3);
            float32x4_t new_s = vld1q_f32(s + k);
            vst1q_lane_f32(p0, new_s, 0);
            vst1q_lane_f32(p1, new_s, 1);
            vst1q_lane_f32(p2, new_s, 2);
            vst1q_lane_f32(p3, new_s, 3);
            float32x4_t current = vld1q_f32(s_min + k);
            uint32x4_t is_min = vcleq_f32(new_s, current);
            uint32x4_t stale = vbicq_u32(vcleq_f32(old_val, vmulq_f32(current, growth)), is_min);
            vst1q_f32(s_min + k, vbslq_f32(is_min, new_s, current));
            uint32_t bits = vaddvq_u32(vandq_u32(stale, weights));
            vst1_u16(pending + count, vadd_u16(vld1_u16(mcra_lane_list[bits]),
                                               vdup_n_u16((uint16_t)k)));
            count += mcra_lane_count[bits];
        }
        for (; k < end; k++) {
            bool rescan;
            mcra_ring_min_elem(s_min + k, s[k], ring + (size_t)k * L, ring_pos, &rescan);
            if (rescan) pending[count++] = (uint16_t)k;
        }
        for (int i = 0; i < count; i++)
            s_min[pending[i]] = mcra_min_ordered_neon(ring + (size_t)pending[i] * L, L);
    }
}
#endif

static inline void mcra_ring_min(float* s_min, const float* s, float* ring, int L, int ring_pos,
                                 int n) {
#if ANR_VECTOR
    mcra_ring_min_neon(s_min, s, ring, L, ring_pos, n);
#else
    mcra_ring_min_scalar(s_min, s, ring, L, ring_pos, n);
#endif
}
#endif

/* Restart inert bins with p=0 so a returning signal can update the floor. The update keeps
 * the non-fused order alpha_d*N + (1-alpha_d)*power; other bins are left unchanged.
 */
static inline void mcra_restart_inert_elem(float* noise, float power, float alpha_d) {
    if (*noise < MCRA_NOISE_PSD_INERT)
        *noise = alpha_d * *noise + (1.0f - alpha_d) * power;
}

ANR_TWIN void mcra_restart_inert_scalar(float* noise, const float* power,
                                        float alpha_d, int n) {
    for (int k = 0; k < n; k++) mcra_restart_inert_elem(noise + k, power[k], alpha_d);
}

#if SK_HAVE_NEON
ANR_TWIN void mcra_restart_inert_neon(float* noise, const float* power, float alpha_d,
                                      int n) {
    const float32x4_t floor_psd = vdupq_n_f32(MCRA_NOISE_PSD_INERT);
    const float32x4_t alpha = vdupq_n_f32(alpha_d);
    const float32x4_t one_minus = vdupq_n_f32(1.0f - alpha_d);
    int k = 0;
    for (; k + 4 <= n; k += 4) {
        float32x4_t current = vld1q_f32(noise + k);
        float32x4_t restarted = vaddq_f32(vmulq_f32(alpha, current),
                                          vmulq_f32(one_minus, vld1q_f32(power + k)));
        vst1q_f32(noise + k, vbslq_f32(vcltq_f32(current, floor_psd), restarted, current));
    }
    for (; k < n; k++) mcra_restart_inert_elem(noise + k, power[k], alpha_d);
}
#endif

static inline void mcra_restart_inert(float* noise, const float* power, float alpha_d, int n) {
#if ANR_VECTOR
    mcra_restart_inert_neon(noise, power, alpha_d, n);
#else
    mcra_restart_inert_scalar(noise, power, alpha_d, n);
#endif
}

void mcra_update_ex(McraNoiseEstimator* self,
                    const float* power,
                    const float* spp_ext,
                    bool slow_lf_rise,
                    int slow_lf_bins,
                    float alpha_d_speech) {
    if (!self || !power || !self->is_initialized) return;

    int n_freqs = self->n_freqs;
    int L = self->L;
    float alpha_s = self->alpha_s;
    float alpha_d = self->alpha_d;
    float alpha_p = self->alpha_p;
    float delta = self->delta;

    // Time EMA; preserve non-fused scalar operation order.
    sk_ema_f32(self->S, power, alpha_s, 1.0f - alpha_s, n_freqs);

    // Ring update and incremental minima.
    int ring_pos = self->ring_idx;
#if defined(USE_OPTIMIZED_MIN_BUFFER) && defined(USE_INCREMENTAL_MIN)
    mcra_ring_min(self->S_min, self->S, self->min_buffer, L, ring_pos, n_freqs);
#else
    for (int k = 0; k < n_freqs; k++) {
        float new_S = self->S[k];

        // Read old value before overwriting, then write new value
#ifdef USE_OPTIMIZED_MIN_BUFFER
        float* buf_ptr = &self->min_buffer[k * L + ring_pos];
#else
        float* buf_ptr = &self->min_buffer[ring_pos * n_freqs + k];
#endif
#ifdef USE_INCREMENTAL_MIN
        float old_val = *buf_ptr;
#endif
        *buf_ptr = new_S;

#ifdef USE_INCREMENTAL_MIN
        // Incremental min tracking: O(1) average, O(L) worst case
        if (new_S <= self->S_min[k]) {
            // New value is the minimum
            self->S_min[k] = new_S;
        } else if (old_val <= self->S_min[k] * (1.0f + 1e-6f)) {
            // Evicted value was (approximately) the minimum — must rescan
#ifdef USE_OPTIMIZED_MIN_BUFFER
            float* freq_buf = &self->min_buffer[k * L];
            float min_val = mcra_min_ordered(freq_buf, L);
#else
            float min_val = FLT_MAX;
            for (int l = 0; l < L; l++) {
                float val = self->min_buffer[l * n_freqs + k];
                if (val < min_val) min_val = val;
            }
#endif
            self->S_min[k] = min_val;
        }
        // else: S_min unchanged
#else
        // Full scan: always find minimum over all L frames
#ifdef USE_OPTIMIZED_MIN_BUFFER
        {
            float* freq_buf = &self->min_buffer[k * L];
            float min_val = mcra_min_ordered(freq_buf, L);
            self->S_min[k] = min_val;
        }
#else
        {
            float min_val = FLT_MAX;
            for (int l = 0; l < L; l++) {
                float val = self->min_buffer[l * n_freqs + k];
                if (val < min_val) min_val = val;
            }
            self->S_min[k] = min_val;
        }
#endif
#endif  // USE_INCREMENTAL_MIN
    }
#endif

    // Advance ring index
    self->ring_idx = (self->ring_idx + 1) % L;

    // Speech-indicator smoothing precedes scene resets and the noise update.
    for (int k = 0; k < n_freqs; k++) {
        // Speech indicator: I(k,l) = 1 if S(k,l)/(S_min(k,l)·δ) > 1
        float ratio = self->S[k] / (self->S_min[k] * delta + 1e-10f);
        float indicator = (ratio > 1.0f) ? 1.0f : 0.0f;

        // SPP smoothing: p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self->spp[k] = alpha_p * self->spp[k] + (1.0f - alpha_p) * indicator;
    }

    // Scene detection uses the pre-update noise floor.
    {
        int hi_start = n_freqs / 2;  // Upper half (~4kHz for 16kHz/512FFT)

        /* Check the energy gate before the more expensive flatness calculation. */
        float hi_power_sum = 0.0f;
        float hi_noise_sum = 0.0f;
        for (int k = hi_start; k < n_freqs; k++) {
            hi_power_sum += power[k];
            hi_noise_sum += self->noise_psd[k];
        }
        float hi_gamma = hi_power_sum / (hi_noise_sum + 1e-10f);
        bool hi_energy_candidate = hi_gamma > self->scene_change_threshold;
        float hi_flatness = hi_energy_candidate
            ? spectral_flatness(power, hi_start, n_freqs,
                                self->flatness_scratch)
            : 0.0f;

        if (hi_energy_candidate &&
            hi_flatness > self->scene_change_flatness_threshold) {
            // Saturate the run counter at its configured limit to avoid signed overflow.
            if (self->scene_change_count < self->scene_change_min_frames)
                self->scene_change_count++;
            if (self->scene_change_count >= self->scene_change_min_frames) {
                mcra_reset_noise_floor(self, power);
                self->scene_change_count = 0;
            }
        } else {
            self->scene_change_count = 0;
        }
    }

    // Broadband onset: internal-SPP active fraction controls the gate; the noise update may
    // use external SPP. Disabled at threshold >= 1.
    const float* spp_for_update = spp_ext ? spp_ext : self->spp;
    float bb_scale = 1.0f;
    if (self->broadband_threshold < 1.0f) {
        int high = 0;
        for (int k = 0; k < n_freqs; k++)
            if (self->spp[k] > 0.5f) high++;
        float high_spp_ratio = (float)high / (float)n_freqs;
        if (high_spp_ratio > self->broadband_threshold) {
            bb_scale = 1.0f - (high_spp_ratio - self->broadband_threshold)
                              / (1.0f - self->broadband_threshold);
            if (bb_scale < 0.0f) bb_scale = 0.0f;
        }
    }

    // After scene resets: alpha_tilde = alpha_d + (1-alpha_d)*(spp*bb_scale); apply the
    // non-fused noise EMA.
    int slow_end = slow_lf_rise ? slow_lf_bins : 0;
    if (slow_end < 0) slow_end = 0;
    if (slow_end > n_freqs) slow_end = n_freqs;
    for (int k = 0; k < slow_end; k++) {
        float p = spp_for_update[k] * bb_scale;
        float alpha = alpha_d + (1.0f - alpha_d) * p;
        float ordinary = alpha * self->noise_psd[k]
                       + (1.0f - alpha) * power[k];
        float alpha_speech = alpha_d_speech
                           + (1.0f - alpha_d_speech) * p;
        float held = alpha_speech * self->noise_psd[k]
                   + (1.0f - alpha_speech) * power[k];
        self->noise_psd[k] = held < ordinary ? held : ordinary;
    }
    if (slow_end < n_freqs) {
        sk_mcra_noise_update_f32(self->noise_psd + slow_end,
                                  spp_for_update + slow_end,
                                  power + slow_end,
                                  alpha_d, bb_scale, n_freqs - slow_end);
    }

    mcra_restart_inert(self->noise_psd, power, alpha_d, n_freqs);
}

void mcra_update(McraNoiseEstimator* self, const float* power, const float* spp_ext) {
    mcra_update_ex(self, power, spp_ext, false, 0, 0.0f);
}

const float* mcra_get_noise_psd(const McraNoiseEstimator* self) {
    return self ? self->noise_psd : NULL;
}

const float* mcra_get_internal_spp(const McraNoiseEstimator* self) {
    return self ? self->spp : NULL;
}

bool mcra_is_initialized(const McraNoiseEstimator* self) {
    return self ? self->is_initialized : false;
}

void mcra_reset(McraNoiseEstimator* self) {
    if (!self) return;

    int n_freqs = self->n_freqs;

    memset(self->noise_psd, 0, n_freqs * sizeof(float));
    memset(self->S, 0, n_freqs * sizeof(float));
    memset(self->S_min, 0, n_freqs * sizeof(float));
    memset(self->spp, 0, n_freqs * sizeof(float));
    memset(self->min_buffer, 0, self->L * n_freqs * sizeof(float));

    self->ring_idx = 0;
    self->is_initialized = false;
    self->scene_change_count = 0;
}
