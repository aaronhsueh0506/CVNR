/* Noise PSD tracker, per bin: S = α_s*S_prev + (1-α_s)*power; S_min is the minimum of S over
 * the last L frames; I = [S/(δ*S_min) > 1]; p = α_p*p_prev + (1-α_p)*I;
 * α̃_d = α_d + (1-α_d)*p; N = α̃_d*N_prev + (1-α̃_d)*power.
 */

#include "noise_estimator.h"
#include "utility/fast_math.h"
#include "fft_wrapper.h"
#include "utility/mem_align.h"
#include "utility/simd_kernels.h"  /* Requires -ffp-contract=off. */
#include "utility/simd_nr.h"
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include "anr_internal.h"

struct NoiseEstimator {
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

    // Minimum-tracking ring [L * n_freqs]; frequency-major with USE_OPTIMIZED_MIN_BUFFER, else frame-major
#ifdef USE_OPTIMIZED_MIN_BUFFER
#else
#endif
    float* min_buffer;
    int ring_idx;       // Current write position in ring buffer

    // Scratch [n_freqs] for the log pass of spectral_flatness().
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
    // Init rows [frame_idx * n_freqs + freq_idx]; in the shared-startup layout this is min_buffer.
    float* init_power_buffer;
    int num_init_frames;    // Max number of init frames (from config)
    // Per-bin quickselect scratch [num_init_frames]; preallocated so init never allocates.
    float* percentile_scratch;
#endif

    bool is_static;      // true: caller-owned memory; false: heap
};

/* Ratio of the geometric to the arithmetic mean of power[start:end] (+1e-20 per bin); expf is
 * used at the hard decision threshold. scratch holds end-start floats. */
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
static void noise_estimator_reset_noise_floor(NoiseEstimator* self, const float* power) {
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

/* Update only tuning scalars; preserve tracker state. L and num_init_frames must already match
 * allocated geometry.
 */
void noise_estimator_apply_config_scalars(NoiseEstimator* self,
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
ANR_TWIN float noise_estimator_min_ordered(const float* values, int n) {
#if ANR_VECTOR
    return skr_min_ordered_neon(values, n);
#else
    return skr_min_ordered_scalar(values, n);
#endif
}
#endif

static void noise_estimator_init_scalars(NoiseEstimator* self, int n_freqs,
                                         const AnrConfig* config) {
    self->n_freqs = n_freqs;
    noise_estimator_apply_config_scalars(self, config);

    self->ring_idx = 0;
    self->is_initialized = false;
    self->scene_change_count = 0;
}

/* Rows of the minimum ring's region: L, or under shared startup at least num_init_frames. */
static size_t noise_estimator_ring_rows(const AnrConfig* config, bool shared_startup) {
    size_t rows = (size_t)config->L;
#ifndef USE_FAST_PERCENTILE
    if (shared_startup && (size_t)config->num_init_frames > rows)
        rows = (size_t)config->num_init_frames;
#else
    (void)shared_startup;
#endif
    return rows;
}

/* shared_startup places the init rows and the minimum ring in one region (the larger of the
 * two). Only the integrated denoiser uses it: it accumulates before initialization only and
 * re-accumulates every row after a reset. */
static size_t noise_estimator_mem_size_impl(int n_freqs, const AnrConfig* config,
                                            bool shared_startup) {
    if (n_freqs <= 0 || !config) return 0;
    if (config->L <= 0) return 0;
#ifndef USE_FAST_PERCENTILE
    if (config->num_init_frames <= 0) return 0;
#endif

    size_t ring_rows = noise_estimator_ring_rows(config, shared_startup);

    size_t total = ALIGN16(sizeof(NoiseEstimator));
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* noise_psd  */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* S          */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* S_min      */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* spp        */
    total = ck_field_size(total, ck_mul_size(ring_rows, (size_t)n_freqs),
                          sizeof(float));                            /* min_buffer */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));   /* flatness_scratch */
#ifndef USE_FAST_PERCENTILE
    if (!shared_startup)
        total = ck_field_size(total, ck_mul_size((size_t)config->num_init_frames, (size_t)n_freqs),
                              sizeof(float));                        /* init_power_buffer  */
    total = ck_field_size(total, (size_t)config->num_init_frames, sizeof(float)); /* percentile_scratch */
#endif
    return MEM_SIZE_INVALID(total) ? 0 : total;
}

size_t noise_estimator_get_mem_size(int n_freqs, const AnrConfig* config) {
    return noise_estimator_mem_size_impl(n_freqs, config, false);
}

size_t noise_estimator_get_mem_size_shared_startup(int n_freqs, const AnrConfig* config) {
    return noise_estimator_mem_size_impl(n_freqs, config, true);
}

static NoiseEstimator* noise_estimator_init_impl(void* mem, size_t mem_size, int n_freqs,
                                                 const AnrConfig* config, bool shared_startup) {
    if (n_freqs <= 0 || !config || !mem) return NULL;
    /* Reject unaligned memory before writing. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    size_t need = noise_estimator_mem_size_impl(n_freqs, config, shared_startup);
    if (need == 0 || mem_size < need) return NULL;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;

    NoiseEstimator* self = (NoiseEstimator*)cursor;
    cursor += ALIGN16(sizeof(NoiseEstimator));

    noise_estimator_init_scalars(self, n_freqs, config);
    self->is_static = true;

    size_t ring_rows = noise_estimator_ring_rows(config, shared_startup);

    self->noise_psd  = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->S          = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->S_min      = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->spp        = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->min_buffer = (float*)cursor; cursor += ALIGN16(ring_rows * n_freqs * sizeof(float));
    self->flatness_scratch = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
#ifndef USE_FAST_PERCENTILE
    if (shared_startup) {
        self->init_power_buffer = self->min_buffer;
    } else {
        self->init_power_buffer = (float*)cursor;
        cursor += ALIGN16((size_t)self->num_init_frames * n_freqs * sizeof(float));
    }
    self->percentile_scratch = (float*)cursor;
    cursor += ALIGN16((size_t)self->num_init_frames * sizeof(float));
#endif

    /* Size query and carve must end at the same byte offset. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    return self;
}

NoiseEstimator* noise_estimator_init(void* mem, size_t mem_size,
                                     int n_freqs, const AnrConfig* config) {
    return noise_estimator_init_impl(mem, mem_size, n_freqs, config, false);
}

NoiseEstimator* noise_estimator_init_shared_startup(void* mem, size_t mem_size, int n_freqs,
                                                    const AnrConfig* config) {
    return noise_estimator_init_impl(mem, mem_size, n_freqs, config, true);
}

static NoiseEstimator* noise_estimator_create_impl(int n_freqs, const AnrConfig* config,
                                                   bool shared_startup) {
    if (n_freqs <= 0 || !config) return NULL;
    if (config->L <= 0) return NULL;
#ifndef USE_FAST_PERCENTILE
    if (config->num_init_frames <= 0) return NULL;
#endif

    NoiseEstimator* self = (NoiseEstimator*)calloc(1, sizeof(NoiseEstimator));
    if (!self) return NULL;

    noise_estimator_init_scalars(self, n_freqs, config);
    self->is_static = false;

    size_t ring_rows = noise_estimator_ring_rows(config, shared_startup);

    self->noise_psd = (float*)calloc(n_freqs, sizeof(float));
    self->S = (float*)calloc(n_freqs, sizeof(float));
    self->S_min = (float*)calloc(n_freqs, sizeof(float));
    self->spp = (float*)calloc(n_freqs, sizeof(float));

    self->min_buffer = (float*)calloc(ring_rows * n_freqs, sizeof(float));
    self->flatness_scratch = (float*)calloc(n_freqs, sizeof(float));

    if (!self->noise_psd || !self->S || !self->S_min ||
        !self->spp || !self->min_buffer || !self->flatness_scratch) {
        noise_estimator_destroy(self);
        return NULL;
    }

#ifndef USE_FAST_PERCENTILE
    self->init_power_buffer = shared_startup
        ? self->min_buffer
        : (float*)calloc(self->num_init_frames * n_freqs, sizeof(float));
    self->percentile_scratch = (float*)calloc(self->num_init_frames, sizeof(float));
    if (!self->init_power_buffer || !self->percentile_scratch) {
        noise_estimator_destroy(self);
        return NULL;
    }
#endif

    return self;
}

NoiseEstimator* noise_estimator_create(int n_freqs, const AnrConfig* config) {
    return noise_estimator_create_impl(n_freqs, config, false);
}

NoiseEstimator* noise_estimator_create_shared_startup(int n_freqs, const AnrConfig* config) {
    return noise_estimator_create_impl(n_freqs, config, true);
}

void noise_estimator_destroy(NoiseEstimator* self) {
    if (!self) return;
    if (self->is_static) return;  /* caller owns the block; nothing to free */

#ifndef USE_FAST_PERCENTILE
    /* Shared-startup instances alias the init rows onto min_buffer; free it once, below. */
    if (self->init_power_buffer && self->init_power_buffer != self->min_buffer)
        free(self->init_power_buffer);
    if (self->percentile_scratch) free(self->percentile_scratch);
#endif
    if (self->noise_psd) free(self->noise_psd);
    if (self->S) free(self->S);
    if (self->S_min) free(self->S_min);
    if (self->spp) free(self->spp);
    if (self->min_buffer) free(self->min_buffer);
    if (self->flatness_scratch) free(self->flatness_scratch);

    free(self);
}

#ifndef USE_FAST_PERCENTILE
/* Save initialization power for exact percentile selection. */
void noise_estimator_accumulate_init_power(NoiseEstimator* self, const float* power,
                                           int frame_idx) {
    if (!self || !power || !self->init_power_buffer) return;
    if (frame_idx < 0 || frame_idx >= self->num_init_frames) return;
    /* A shared region belongs to the ring once initialized. */
    if (self->is_initialized && self->init_power_buffer == self->min_buffer) return;

    int n_freqs = self->n_freqs;
    int offset = frame_idx * n_freqs;
    memcpy(self->init_power_buffer + offset, power, n_freqs * sizeof(float));
}

/* Partition around the midpoint pivot; returns its final index. */
static int quickselect_partition(float* arr, int left, int right) {
    int mid = left + (right - left) / 2;
    float pivot = arr[mid];

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

    int k = ((n - 1) * p) / 100;

    return quickselect(data, n, k);
}
#else
/* No accumulation needed for the fast-percentile path. */
void noise_estimator_accumulate_init_power(NoiseEstimator* self, const float* power,
                                           int frame_idx) {
    (void)self;
    (void)power;
    (void)frame_idx;
}
#endif

/* Seed bin k of every tracker array from its initial noise estimate. */
static void noise_estimator_seed_bin(NoiseEstimator* self, int k, float init_psd) {
    if (init_psd < 1e-10f) init_psd = 1e-10f;
    self->noise_psd[k] = init_psd;
    self->S[k] = init_psd;
    self->S_min[k] = init_psd;
    self->spp[k] = 0.0f;
}

/* Low-memory empirical stand-in for the configured 30th percentile. */
static void noise_estimator_seed_from_mean(NoiseEstimator* self, const float* power_sum,
                                           int n_frames) {
    for (int k = 0; k < self->n_freqs; k++) {
        float avg_power = power_sum[k] / (float)n_frames;
        noise_estimator_seed_bin(self, k, avg_power * 0.23f);
    }
}

void noise_estimator_init_noise(NoiseEstimator* self, const float* power_sum, int n_frames) {
    if (!self || !power_sum || n_frames <= 0) return;
#ifndef USE_FAST_PERCENTILE
    /* The init rows of a shared region were overwritten by the ring. */
    if (self->is_initialized && self->init_power_buffer == self->min_buffer) return;
#endif

    int n_freqs = self->n_freqs;

#ifdef USE_FAST_PERCENTILE
    noise_estimator_seed_from_mean(self, power_sum, n_frames);
#else
    // Exact 30th percentile per bin (quickselect over the stored init rows).

    float* freq_powers = self->percentile_scratch;
    if (!freq_powers) {
        // Fallback to approximation if the scratch is unavailable
        noise_estimator_seed_from_mean(self, power_sum, n_frames);
    } else {
        for (int k = 0; k < n_freqs; k++) {
            for (int f = 0; f < n_frames; f++) {
                freq_powers[f] = self->init_power_buffer[f * n_freqs + k];
            }

            // Exact 30th percentile
            noise_estimator_seed_bin(self, k, calculate_percentile(freq_powers, n_frames, 30));
        }
    }
#endif

    // Seed the minimum ring with the initial noise. Runs after the percentile pass: a shared
    // region holds the init rows until every bin has been read.
#ifdef USE_OPTIMIZED_MIN_BUFFER
    for (int k = 0; k < n_freqs; k++) {
        float* freq_buf = &self->min_buffer[k * self->L];
        for (int l = 0; l < self->L; l++) {
            freq_buf[l] = self->noise_psd[k];
        }
    }
#else
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
static inline void noise_estimator_ring_min(float* s_min, const float* s, float* ring,
                                            int L, int ring_pos, int n) {
#if ANR_VECTOR
    skr_ring_min_neon(s_min, s, ring, L, ring_pos, n);
#else
    skr_ring_min_scalar(s_min, s, ring, L, ring_pos, n);
#endif
}
#endif

static inline void noise_estimator_restart_inert(float* noise, const float* power,
                                                 float alpha_d, int n) {
#if ANR_VECTOR
    skr_restart_inert_neon(noise, power, alpha_d, n);
#else
    skr_restart_inert_scalar(noise, power, alpha_d, n);
#endif
}

void noise_estimator_update_ex(NoiseEstimator* self,
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

    // Time-smoothed power.
    sk_ema_f32(self->S, power, alpha_s, 1.0f - alpha_s, n_freqs);

    // Ring update and incremental minima.
    int ring_pos = self->ring_idx;
#if defined(USE_OPTIMIZED_MIN_BUFFER) && defined(USE_INCREMENTAL_MIN)
    noise_estimator_ring_min(self->S_min, self->S, self->min_buffer, L, ring_pos, n_freqs);
#else
    for (int k = 0; k < n_freqs; k++) {
        float new_S = self->S[k];

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
            self->S_min[k] = new_S;
        } else if (old_val <= self->S_min[k] * (1.0f + 1e-6f)) {
            // Evicted value was (approximately) the minimum — must rescan
            float min_val = FLT_MAX;
            for (int l = 0; l < L; l++) {
                float val = self->min_buffer[l * n_freqs + k];
                if (val < min_val) min_val = val;
            }
            self->S_min[k] = min_val;
        }
#else
#ifdef USE_OPTIMIZED_MIN_BUFFER
        {
            float* freq_buf = &self->min_buffer[k * L];
            float min_val = noise_estimator_min_ordered(freq_buf, L);
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

    self->ring_idx = (self->ring_idx + 1) % L;

    // Speech-indicator smoothing precedes scene resets and the noise update.
    for (int k = 0; k < n_freqs; k++) {
        float ratio = self->S[k] / (self->S_min[k] * delta + 1e-10f);
        float indicator = (ratio > 1.0f) ? 1.0f : 0.0f;

        self->spp[k] = alpha_p * self->spp[k] + (1.0f - alpha_p) * indicator;
    }

    // Scene detection uses the pre-update noise floor.
    {
        int hi_start = n_freqs / 2;  // upper half of the spectrum

        /* The cheap energy gate runs before the flatness calculation; the epsilon is applied to
         * the per-bin mean, not the raw sum. */
        float hi_power_sum = 0.0f;
        float hi_noise_sum = 0.0f;
        for (int k = hi_start; k < n_freqs; k++) {
            hi_power_sum += power[k];
            hi_noise_sum += self->noise_psd[k];
        }
        int n_hi = n_freqs - hi_start;
        float hi_power_mean = hi_power_sum / (float)n_hi;
        float hi_noise_mean = hi_noise_sum / (float)n_hi;
        float hi_gamma = hi_power_mean / (hi_noise_mean + 1e-10f);
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
                noise_estimator_reset_noise_floor(self, power);
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

    // alpha_tilde = alpha_d + (1 - alpha_d) * spp * bb_scale, applied after scene resets.
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
        sk_noise_update_f32(self->noise_psd + slow_end,
                             spp_for_update + slow_end,
                             power + slow_end,
                             alpha_d, bb_scale, n_freqs - slow_end);
    }

    noise_estimator_restart_inert(self->noise_psd, power, alpha_d, n_freqs);
}

const float* noise_estimator_get_noise_psd(const NoiseEstimator* self) {
    return self ? self->noise_psd : NULL;
}

void noise_estimator_reset(NoiseEstimator* self) {
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
