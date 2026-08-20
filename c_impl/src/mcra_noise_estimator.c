/**
 * mcra_noise_estimator.c - MCRA Noise Estimator Implementation
 *
 * Cohen & Berdugo (2002) - Minima Controlled Recursive Averaging
 *
 * Algorithm:
 * 1. Time smoothing: S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
 * 2. Min tracking: S_min(k,l) = min{S(k,τ): l-L+1 ≤ τ ≤ l}
 * 3. Speech indicator: I(k,l) = 1 if S(k,l)/(S_min(k,l)·δ) > 1 else 0
 * 4. SPP smoothing: p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
 * 5. Noise update: α̃_d = α_d + (1-α_d)·p(k,l)
 *                  N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²
 */

#include "mcra_noise_estimator.h"
#include "fast_math.h"
#include "fft_wrapper.h"   /* ALIGN16 */
#include "simd_kernels.h"  /* sk_ema_f32 (kernel 4), sk_mcra_noise_update_f32 (kernel 28) --
                             * both are provably scalar-reference-bit-exact by construction
                             * (non-fused, verbatim op-sequence match -- see that header's
                             * top-of-file contract), gated by this TU's mandatory
                             * -ffp-contract=off same as every other caller. */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include "mmse_lsa_internal.h"

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
    // Optimized layout: min_buffer[freq_idx * L + frame_idx]
    // All L values for the same frequency are contiguous (better cache locality)
#else
    // Original layout: min_buffer[frame_idx * n_freqs + freq_idx]
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
    bool scene_change_tonal_veto;           // Skip reset when LOW band is tonal (music-safe)
    float scene_change_lo_flatness_max;     // Lo-band flatness below this => tonal => veto

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

/* Geometric-mean / arithmetic-mean spectral flatness of power[start:end] (∈ (0,1]).
 * ~0.1-0.2 for tonal/voiced content, ~0.5-0.7 for white noise. Mirrors Python
 * core/noise_estimators/mcra.py _spectral_flatness (same +1e-20 eps).
 *
 * `scratch` must hold >= (end-start) floats (the caller's flatness_scratch,
 * sized n_freqs -- always enough). Split into three passes so the expensive
 * fast_log() call is a single vectorized sk_fast_log_f32() over the whole
 * range instead of one scalar call per bin (kernel 25, the same kernel
 * calculate_gain() already uses -- see mmse_lsa_denoiser.c): (1) scalar
 * arith_sum accumulation while staging power+eps into scratch, in the
 * ORIGINAL k=start..end-1 order; (2) one vectorized log over scratch,
 * in-place (sk_fast_log_f32 is documented out==x safe and bit-exact to the
 * scalar fast_log() per-element); (3) scalar log_sum reduction over scratch
 * in the same 0..n-1 order. Every individual addend is bit-identical to the
 * original single-pass loop, so log_sum/arith_sum are bit-identical too. */
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
    return fast_exp(log_sum * inv_n) / (arith_sum * inv_n);
}

/* Partial noise-floor reset on a confirmed scene change: blend the tracked noise
 * toward the observed power and re-seed the min tracker to the current S. */
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

/* Shared scalar/config initialisation — identical for both malloc and ext-mem
 * builds (arrays are zeroed separately: calloc in the malloc path, memset of the
 * whole block in the ext-mem path). */
/* Tuning scalars ONLY -- no geometry, no state. Split out from
 * mcra_init_scalars so a runtime reconfiguration can swap the coefficients
 * without discarding the tracked noise floor, the min-tracking ring position
 * or the scene-change run length. `L` and `num_init_frames` size caller-owned
 * buffers, so a reconfiguration path must have already established that they
 * are unchanged before calling this; they are re-applied here anyway so the
 * function is a complete statement of what the config controls. */
void mcra_apply_config_scalars(McraNoiseEstimator* self,
                               const MmseLsaConfig* config) {
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
    self->scene_change_tonal_veto = config->scene_change_tonal_veto;
    self->scene_change_lo_flatness_max = config->scene_change_lo_flatness_max;

#ifndef USE_FAST_PERCENTILE
    self->num_init_frames = config->num_init_frames;
#endif
}

static void mcra_init_scalars(McraNoiseEstimator* self, int n_freqs,
                              const MmseLsaConfig* config) {
    self->n_freqs = n_freqs;
    mcra_apply_config_scalars(self, config);

    self->ring_idx = 0;
    self->is_initialized = false;
    self->scene_change_count = 0;
}

/* ---- Static-memory (no malloc) variant ------------------------------------ */

size_t mcra_get_mem_size(int n_freqs, const MmseLsaConfig* config) {
    /* F05: explicit sign/bound guards — n_freqs/L/num_init_frames are plain
     * `int`s from the caller; a negative value cast to size_t below would
     * become a huge allocation request instead of an error, and an extreme
     * positive value could overflow the size_t multiplication silently. The
     * ck_* helpers additionally saturate any overflow that slips past these
     * guards (e.g. n_freqs itself still huge-but-positive) to SIZE_MAX, which
     * MEM_SIZE_INVALID() below turns into a `return 0` failure. */
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
                              int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config || !mem) return NULL;
    /* F07: reject a misaligned pool base before any write into it. mcra_init
     * is a public entry point (declared in mcra_noise_estimator.h) — it is
     * normally only reached via mmse_lsa_init()'s own aligned sub-carve, but
     * guard it directly too in case it is ever called standalone. */
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

    /* Lockstep guard: mcra_get_mem_size() and the carve sequence above are
     * two independently-maintained additions that must total identically --
     * a field added/removed from one but not the other would otherwise only
     * surface as a silent over/under-carve, not a build or test failure.
     * cursor is expected to land exactly at mem + need. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    return self;
}

/* ---- Heap (malloc) variant ------------------------------------------------ */

McraNoiseEstimator* mcra_create(int n_freqs, const MmseLsaConfig* config) {
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
/**
 * Accumulate power spectrum for exact percentile calculation
 * Call this for each frame during initialization phase
 */
void mcra_accumulate_init_power(McraNoiseEstimator* self, const float* power, int frame_idx) {
    if (!self || !power || !self->init_power_buffer) return;
    if (frame_idx < 0 || frame_idx >= self->num_init_frames) return;

    int n_freqs = self->n_freqs;
    int offset = frame_idx * n_freqs;
    memcpy(self->init_power_buffer + offset, power, n_freqs * sizeof(float));
}

/**
 * Quickselect partition function
 * Returns the index of the pivot after partitioning
 */
static int quickselect_partition(float* arr, int left, int right) {
    // Use middle element as pivot (median-of-three would be better for large arrays)
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

/**
 * Quickselect algorithm - finds k-th smallest element in O(n) average
 * Note: This modifies the input array!
 */
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

/**
 * Calculate p-th percentile using quickselect, IN PLACE.
 * @param data Scratch data — REORDERED by quickselect (caller passes a disposable
 *             buffer, so no temporary allocation is needed). Result is unchanged
 *             vs the previous copy-then-select version (same k-th smallest value).
 * @param n Number of elements
 * @param p Percentile (0-100)
 * @return The p-th percentile value
 */
static float calculate_percentile(float* data, int n, int p) {
    if (n <= 0) return 0.0f;
    if (n == 1) return data[0];

    // k = floor((n-1) * p / 100)
    int k = ((n - 1) * p) / 100;

    return quickselect(data, n, k);
}
#else
/**
 * Stub function when USE_FAST_PERCENTILE is defined
 */
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
    // Fast approximation: 20th percentile ≈ mean × 0.17
    // This is an empirical approximation for power spectrum distribution
    for (int k = 0; k < n_freqs; k++) {
        float avg_power = power_sum[k] / (float)n_frames;
        float init_psd = avg_power * 0.23f;  // v4.0: 30th percentile (more accurate)

        if (init_psd < 1e-10f) init_psd = 1e-10f;

        self->noise_psd[k] = init_psd;
        self->S[k] = init_psd;
        self->S_min[k] = init_psd;
        self->spp[k] = 0.0f;
    }
#else
    // Exact 30th percentile using quickselect (v4.0 optimized)
    // Requires init_power_buffer to be filled via mcra_accumulate_init_power()

    // Per-bin gather + quickselect scratch — pre-allocated, no malloc.
    float* freq_powers = self->percentile_scratch;
    if (!freq_powers) {
        // Fallback to approximation if the scratch is unavailable
        for (int k = 0; k < n_freqs; k++) {
            float avg_power = power_sum[k] / (float)n_frames;
            float init_psd = avg_power * 0.23f;  // v4.0: 30th percentile
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

            // Calculate exact 30th percentile (v4.0 optimized)
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
    // Optimized layout: [freq_idx * L + frame_idx]
    for (int k = 0; k < n_freqs; k++) {
        float* freq_buf = &self->min_buffer[k * self->L];
        for (int l = 0; l < self->L; l++) {
            freq_buf[l] = self->noise_psd[k];
        }
    }
#else
    // Original layout: [frame_idx * n_freqs + freq_idx]
    for (int l = 0; l < self->L; l++) {
        for (int k = 0; k < n_freqs; k++) {
            self->min_buffer[l * n_freqs + k] = self->noise_psd[k];
        }
    }
#endif

    self->ring_idx = 0;
    self->is_initialized = true;
}

void mcra_update(McraNoiseEstimator* self, const float* power, const float* spp_ext) {
    if (!self || !power || !self->is_initialized) return;

    int n_freqs = self->n_freqs;
    int L = self->L;
    float alpha_s = self->alpha_s;
    float alpha_d = self->alpha_d;
    float alpha_p = self->alpha_p;
    float delta = self->delta;

    // Loop A0: S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|² -- hoisted into its
    // own pass via sk_ema_f32 (simd_kernels.h kernel 4), a verbatim
    // non-fused match for this exact expression shape (bit-identical by
    // construction: same op sequence/order as the plain scalar loop it
    // replaces, see that kernel's header comment). Loop B below reads back
    // self->S[k] (already updated here) wherever it used to read the local
    // `new_S`.
    sk_ema_f32(self->S, power, alpha_s, 1.0f - alpha_s, n_freqs);

    // Loop B: min buffer write + incremental min tracking
    // v4.1: Eta energy accumulation removed
    int ring_pos = self->ring_idx;
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
            float min_val = freq_buf[0];
            for (int l = 1; l < L; l++) {
                if (freq_buf[l] < min_val) min_val = freq_buf[l];
            }
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
            float min_val = freq_buf[0];
            for (int l = 1; l < L; l++) {
                if (freq_buf[l] < min_val) min_val = freq_buf[l];
            }
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

    // Advance ring index
    self->ring_idx = (self->ring_idx + 1) % L;

    // Loop C1: speech indicator + SPP smoothing only (Python mcra.py step 5).
    // The noise update is deferred to AFTER the scene-change reset + broadband
    // gate, matching the Python ordering exactly (steps 7-8 run before step 8b's
    // SPP-gated update).
    for (int k = 0; k < n_freqs; k++) {
        // Speech indicator: I(k,l) = 1 if S(k,l)/(S_min(k,l)·δ) > 1
        float ratio = self->S[k] / (self->S_min[k] * delta + 1e-10f);
        float indicator = (ratio > 1.0f) ? 1.0f : 0.0f;

        // SPP smoothing: p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self->spp[k] = alpha_p * self->spp[k] + (1.0f - alpha_p) * indicator;
    }

    // Scene change detection (Python step 7, on the PRE-update noise_psd):
    // hi-freq gamma + spectral flatness
    {
        int hi_start = n_freqs / 2;  // Upper half (~4kHz for 16kHz/512FFT)
        int hi_count = n_freqs - hi_start;

        // Merged hi-freq loop: power sum + noise sum + arith-sum-for-flatness,
        // staging power+eps into flatness_scratch; the log itself is a single
        // vectorized sk_fast_log_f32() call below (kernel 25) instead of one
        // scalar fast_log() per bin -- see spectral_flatness()'s comment for
        // why this three-pass split is bit-identical to the original.
        float hi_power_sum = 0.0f;
        float hi_noise_sum = 0.0f;
        float arith_sum = 0.0f;
        for (int k = hi_start; k < n_freqs; k++) {
            hi_power_sum += power[k];
            hi_noise_sum += self->noise_psd[k];
            float p = power[k] + 1e-20f;
            self->flatness_scratch[k - hi_start] = p;
            arith_sum += p;
        }
        sk_fast_log_f32(self->flatness_scratch, self->flatness_scratch, hi_count);
        float log_sum = 0.0f;
        for (int k = 0; k < hi_count; k++) log_sum += self->flatness_scratch[k];
        float hi_gamma = hi_power_sum / (hi_noise_sum + 1e-10f);
        float inv_hi_count = 1.0f / (float)hi_count;
        float geo_mean = fast_exp(log_sum * inv_hi_count);
        float arith_mean = arith_sum * inv_hi_count;
        float hi_flatness = geo_mean / arith_mean;

        if (hi_gamma > self->scene_change_threshold &&
            hi_flatness > self->scene_change_flatness_threshold) {
            // Ceilinged at scene_change_min_frames (UBSan-probed).
            // scene_change_min_frames is
            // user-configurable with NO upper bound in validate_config
            // (unlike num_init_frames's <=200 cap), so a caller can legally
            // set it arbitrarily high. The ONLY consumer of this field is
            // the `>= scene_change_min_frames` check immediately below,
            // which -- on every reachable call sequence -- resets the
            // counter back to 0 in the SAME call that first satisfies it,
            // so on paper the bare `++` never actually walks past
            // scene_change_min_frames <= INT_MAX (an ad hoc UBSan probe
            // confirms: seeding the field one step from the boundary at a
            // reachable state produces a clean same-call reset, no trap --
            // this repo's `delay_aec3.c consistent_estimate_counter` has the
            // identical increment-then-immediate-check-and-reset shape and
            // was correspondingly left unguarded). This guard hardens the
            // bare statement itself against that invariant ever being
            // broken by a future edit to the reset logic below (the same
            // probe shows the UNGUARDED `++` alone traps immediately if the
            // field is ever left sitting at INT_MAX by such a future bug) --
            // observationally identical for every state real execution can
            // reach, so behaviour-preserving.
            if (self->scene_change_count < self->scene_change_min_frames)
                self->scene_change_count++;
            if (self->scene_change_count >= self->scene_change_min_frames) {
                // Music-safe tonal veto (stationary mode): if the LOW band is tonal
                // (peaky, low flatness) treat it as music and skip the noise-floor reset;
                // only a genuine noise-scene change (flat low band) is let through.
                // Matches Python mcra.py:230-236 (lo_flatness via _spectral_flatness).
                bool blocked = self->scene_change_tonal_veto &&
                               spectral_flatness(power, 0, hi_start,
                                                  self->flatness_scratch) <
                                   self->scene_change_lo_flatness_max;
                if (!blocked) mcra_reset_noise_floor(self, power);
                self->scene_change_count = 0;
            }
        } else {
            self->scene_change_count = 0;
        }
    }

    // Broadband scene-reset gate (Python step 8a, mcra.py:229-235): when most
    // bins are active (fraction with internal spp>0.5 exceeds broadband_threshold),
    // scale the noise-update SPP toward 0 so the floor catches a broadband onset
    // fast. Uses the INTERNAL smoothed spp for the ratio; the per-bin update uses
    // the external SPP if the denoiser supplied one. Disabled when >= 1.0.
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

    // Noise update with SPP gating (Python step 8b), AFTER the scene resets:
    // α̃_d = α_d + (1-α_d)·(spp·bb_scale);  N = α̃_d·N + (1-α̃_d)·|Y|²
    // sk_mcra_noise_update_f32 (simd_kernels.h kernel 28) is a verbatim,
    // non-fused match for this exact loop shape -- bit-identical by
    // construction (see that kernel's header comment).
    sk_mcra_noise_update_f32(self->noise_psd, spp_for_update, power,
                              alpha_d, bb_scale, n_freqs);
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
