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
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>

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

    bool is_initialized;
    int frame_count;

    // v4.1: Eta scene change detection removed

#ifndef USE_FAST_PERCENTILE
    // Buffer for exact percentile calculation during initialization
    // Layout: init_power_buffer[frame_idx * n_freqs + freq_idx]
    float* init_power_buffer;
    int num_init_frames;    // Max number of init frames (from config)
#endif
};

McraNoiseEstimator* mcra_create(int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    McraNoiseEstimator* self = (McraNoiseEstimator*)calloc(1, sizeof(McraNoiseEstimator));
    if (!self) return NULL;

    self->n_freqs = n_freqs;
    self->L = config->L;
    self->alpha_s = config->alpha_s;
    self->alpha_d = config->alpha_d;
    self->alpha_p = config->alpha_p;
    self->delta = powf(10.0f, config->delta_db / 10.0f);

    // Allocate state arrays
    self->noise_psd = (float*)calloc(n_freqs, sizeof(float));
    self->S = (float*)calloc(n_freqs, sizeof(float));
    self->S_min = (float*)calloc(n_freqs, sizeof(float));
    self->spp = (float*)calloc(n_freqs, sizeof(float));

    // Allocate min tracking buffer
    self->min_buffer = (float*)calloc(self->L * n_freqs, sizeof(float));

    if (!self->noise_psd || !self->S || !self->S_min ||
        !self->spp || !self->min_buffer) {
        mcra_destroy(self);
        return NULL;
    }

    self->ring_idx = 0;
    self->is_initialized = false;
    self->frame_count = 0;

    // v4.1: Eta scene change detection removed

#ifndef USE_FAST_PERCENTILE
    // Allocate buffer for exact percentile calculation
    self->num_init_frames = config->num_init_frames;
    self->init_power_buffer = (float*)calloc(self->num_init_frames * n_freqs, sizeof(float));
    if (!self->init_power_buffer) {
        mcra_destroy(self);
        return NULL;
    }
#endif

    return self;
}

void mcra_destroy(McraNoiseEstimator* self) {
    if (!self) return;

    if (self->noise_psd) free(self->noise_psd);
    if (self->S) free(self->S);
    if (self->S_min) free(self->S_min);
    if (self->spp) free(self->spp);
    if (self->min_buffer) free(self->min_buffer);
#ifndef USE_FAST_PERCENTILE
    if (self->init_power_buffer) free(self->init_power_buffer);
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
 * Calculate p-th percentile using quickselect
 * @param data Input data (will be copied, not modified)
 * @param n Number of elements
 * @param p Percentile (0-100)
 * @return The p-th percentile value
 */
static float calculate_percentile(const float* data, int n, int p) {
    if (n <= 0) return 0.0f;
    if (n == 1) return data[0];

    // Copy data since quickselect modifies the array
    float* temp = (float*)malloc(n * sizeof(float));
    if (!temp) return data[0];  // Fallback
    memcpy(temp, data, n * sizeof(float));

    // Calculate index for p-th percentile
    // k = floor((n-1) * p / 100)
    int k = ((n - 1) * p) / 100;

    float result = quickselect(temp, n, k);
    free(temp);

    return result;
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
        self->S[k] = avg_power;
        self->S_min[k] = init_psd;
        self->spp[k] = 0.0f;
    }
#else
    // Exact 30th percentile using quickselect (v4.0 optimized)
    // Requires init_power_buffer to be filled via mcra_accumulate_init_power()

    // Temporary buffer to hold power values for one frequency bin
    float* freq_powers = (float*)malloc(n_frames * sizeof(float));
    if (!freq_powers) {
        // Fallback to approximation if allocation fails
        for (int k = 0; k < n_freqs; k++) {
            float avg_power = power_sum[k] / (float)n_frames;
            self->noise_psd[k] = avg_power * 0.23f;  // v4.0: 30th percentile
            self->S[k] = avg_power;
            self->S_min[k] = self->noise_psd[k];
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

            float avg_power = power_sum[k] / (float)n_frames;

            self->noise_psd[k] = init_psd;
            self->S[k] = avg_power;
            self->S_min[k] = init_psd;
            self->spp[k] = 0.0f;
        }
        free(freq_powers);
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
    self->frame_count = n_frames;
}

void mcra_update(McraNoiseEstimator* self, const float* power, const float* spp_ext) {
    if (!self || !power || !self->is_initialized) return;

    int n_freqs = self->n_freqs;
    int L = self->L;
    float alpha_s = self->alpha_s;
    float alpha_d = self->alpha_d;
    float alpha_p = self->alpha_p;
    float delta = self->delta;

    // Loop A+B: Time smoothing + min buffer write + incremental min tracking
    // v4.1: Eta energy accumulation removed
    int ring_pos = self->ring_idx;
    for (int k = 0; k < n_freqs; k++) {
        // S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
        float new_S = alpha_s * self->S[k] + (1.0f - alpha_s) * power[k];
        self->S[k] = new_S;

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

    // v4.1: Eta scene change detection removed (L=5 optimization replaces it)

    // Loop C: Speech indicator + SPP smoothing + noise update
    const float* spp_for_update = spp_ext ? spp_ext : self->spp;
    for (int k = 0; k < n_freqs; k++) {
        // Speech indicator: I(k,l) = 1 if S(k,l)/(S_min(k,l)·δ) > 1
        float ratio = self->S[k] / (self->S_min[k] * delta + 1e-10f);
        float indicator = (ratio > 1.0f) ? 1.0f : 0.0f;

        // SPP smoothing: p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self->spp[k] = alpha_p * self->spp[k] + (1.0f - alpha_p) * indicator;

        // Noise update with SPP gating (uses external SPP if provided, else internal)
        // v4.1: Eta multiplication removed
        float tilde_alpha_d = alpha_d + (1.0f - alpha_d) * spp_for_update[k];
        self->noise_psd[k] = tilde_alpha_d * self->noise_psd[k] +
                            (1.0f - tilde_alpha_d) * power[k];
    }

    self->frame_count++;
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
    self->frame_count = 0;
    // v4.1: Eta state removed
}
