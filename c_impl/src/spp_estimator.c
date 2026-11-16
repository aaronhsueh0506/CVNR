/* Decision-directed per-bin speech-presence probability (Cohen and Berdugo). */

#include "spp_estimator.h"
#include "utility/mem_align.h"
#include "utility/simd_kernels.h"  /* Requires -ffp-contract=off. */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "anr_internal.h"

struct SppEstimator {
    int n_freqs;

    float alpha;        // A priori SNR smoothing factor
    float xi_min;       // Minimum a priori SNR (linear)
    float prior_ratio;  // (1-q)/q precomputed

    // State arrays [n_freqs]
    float* noise_psd_prev;  // Previous frame noise PSD (for DD xi_dd_term1)

    // Per-call scratch [n_freqs]; v is replaced in place by exp(-v).
    float* v_scratch;         // v[k] = ξ/(1+ξ)·γ -> exp(-v[k]), in place
    float* term_xi_scratch;   // term_xi[k] = 1+ξ[k]

    bool is_initialized;

    bool is_static;      // true: caller-owned memory; false: heap
};

/* Update tuning scalars without clearing SNR history. */
void spp_apply_config_scalars(SppEstimator* self,
                              const AnrConfig* config) {
    self->alpha = config->alpha_xi;
    // Clip q to (eps, 1-eps) so prior_ratio is well defined
    {
        const float _eps = 1e-6f;
        float q_clipped = config->q;
        if (q_clipped < _eps) q_clipped = _eps;
        if (q_clipped > 1.0f - _eps) q_clipped = 1.0f - _eps;
        self->prior_ratio = (1.0f - q_clipped) / q_clipped;
    }
    self->xi_min = powf(10.0f, config->xi_min_db / 10.0f);
}

static void spp_init_scalars(SppEstimator* self, int n_freqs,
                             const AnrConfig* config) {
    self->n_freqs = n_freqs;
    spp_apply_config_scalars(self, config);
    self->is_initialized = false;
}

size_t spp_get_mem_size(int n_freqs) {
    /* Checked dimensions and saturating size arithmetic; invalid totals return 0. */
    if (n_freqs <= 0) return 0;
    size_t total = ALIGN16(sizeof(SppEstimator));
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* noise_psd_prev    */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* v_scratch         */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* term_xi_scratch   */
    return MEM_SIZE_INVALID(total) ? 0 : total;
}

SppEstimator* spp_init(void* mem, size_t mem_size,
                       int n_freqs, const AnrConfig* config) {
    if (n_freqs <= 0 || !config || !mem) return NULL;
    /* Reject unaligned memory before writing. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    size_t need = spp_get_mem_size(n_freqs);
    if (need == 0 || mem_size < need) return NULL;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;

    SppEstimator* self = (SppEstimator*)cursor;
    cursor += ALIGN16(sizeof(SppEstimator));

    spp_init_scalars(self, n_freqs, config);
    self->is_static = true;

    self->noise_psd_prev = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));

    self->v_scratch         = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->term_xi_scratch   = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));

    /* Size query and carve must end at the same byte offset. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    return self;
}

SppEstimator* spp_create(int n_freqs, const AnrConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    SppEstimator* self = (SppEstimator*)calloc(1, sizeof(SppEstimator));
    if (!self) return NULL;

    spp_init_scalars(self, n_freqs, config);
    self->is_static = false;

    self->noise_psd_prev = (float*)calloc(n_freqs, sizeof(float));

    self->v_scratch         = (float*)calloc(n_freqs, sizeof(float));
    self->term_xi_scratch   = (float*)calloc(n_freqs, sizeof(float));

    if (!self->noise_psd_prev ||
        !self->v_scratch || !self->term_xi_scratch) {
        spp_destroy(self);
        return NULL;
    }

    return self;
}

void spp_destroy(SppEstimator* self) {
    if (!self) return;
    if (self->is_static) return;  /* caller owns the block; nothing to free */

    if (self->noise_psd_prev) free(self->noise_psd_prev);
    if (self->v_scratch) free(self->v_scratch);
    if (self->term_xi_scratch) free(self->term_xi_scratch);

    free(self);
}

/* v for the gain stage: clamped to [1e-10, 700]; NaN passes through. */
static inline float spp_gain_v(float v) {
    if (v < 1e-10f) v = 1e-10f;
    if (v > 700.0f) v = 700.0f;
    return v;
}

/* One bin of the decision-directed update: xi = max(alpha * enhanced_prev / noise_prev +
 * (1 - alpha) * max(gamma - 1, 0), xi_min), xi / (1 + xi), v = xi / (1 + xi) * gamma and 1 + xi;
 * v_out gets the clamped v. */
static inline void spp_dd_elem(const SppEstimator* self, float power, float noise,
                               float enhanced_prev, float noise_prev, float* xi_out,
                               float* v_out, float* ratio_out, float* v_scratch,
                               float* term_xi_scratch) {
    float gamma = power / (noise + 1e-10f);
    float term1 = enhanced_prev / (noise_prev + 1e-10f);
    float max_gamma_m1 = gamma > 1.0f ? gamma - 1.0f : 0.0f;
    float xi_dd = self->alpha * term1 + (1.0f - self->alpha) * max_gamma_m1;
    float xi = xi_dd > self->xi_min ? xi_dd : self->xi_min;
    *xi_out = xi;
    float term_xi = 1.0f + xi;
    float ratio = xi / term_xi;
    float v = ratio * gamma;
    *v_out = spp_gain_v(v);
    *ratio_out = ratio;
    *term_xi_scratch = term_xi;
    *v_scratch = v;
}

ANR_TWIN void spp_dd_scalar(SppEstimator* self, const float* power,
                            const float* noise, const float* noise_prev,
                            const float* enhanced_prev,
                            float* xi_out, float* v_out, float* ratio_out, int n) {
    for (int k = 0; k < n; k++)
        spp_dd_elem(self, power[k], noise[k], enhanced_prev[k], noise_prev[k],
                    xi_out + k, v_out + k, ratio_out + k, self->v_scratch + k,
                    self->term_xi_scratch + k);
}

#if SK_HAVE_NEON
ANR_TWIN void spp_dd_neon(SppEstimator* self, const float* power, const float* noise,
                          const float* noise_prev, const float* enhanced_prev,
                          float* xi_out, float* v_out, float* ratio_out, int n) {
    const float32x4_t eps = vdupq_n_f32(1e-10f);
    const float32x4_t v_max = vdupq_n_f32(700.0f);
    const float32x4_t one = vdupq_n_f32(1.0f);
    const float32x4_t zero = vdupq_n_f32(0.0f);
    const float32x4_t alpha = vdupq_n_f32(self->alpha);
    const float32x4_t one_minus_alpha = vdupq_n_f32(1.0f - self->alpha);
    const float32x4_t xi_min = vdupq_n_f32(self->xi_min);
    int k = 0;
    for (; k + 4 <= n; k += 4) {
        float32x4_t gamma = vdivq_f32(vld1q_f32(power + k), vaddq_f32(vld1q_f32(noise + k), eps));
        float32x4_t term1 = vdivq_f32(vld1q_f32(enhanced_prev + k),
                                      vaddq_f32(vld1q_f32(noise_prev + k), eps));
        float32x4_t max_gamma_m1 = vbslq_f32(vcgtq_f32(gamma, one), vsubq_f32(gamma, one), zero);
        float32x4_t xi_dd = vaddq_f32(vmulq_f32(alpha, term1),
                                      vmulq_f32(one_minus_alpha, max_gamma_m1));
        float32x4_t xi = vbslq_f32(vcgtq_f32(xi_dd, xi_min), xi_dd, xi_min);
        vst1q_f32(xi_out + k, xi);
        float32x4_t term_xi = vaddq_f32(one, xi);
        float32x4_t ratio = vdivq_f32(xi, term_xi);
        float32x4_t v = vmulq_f32(ratio, gamma);
        float32x4_t vc = vbslq_f32(vcltq_f32(v, eps), eps, v);
        vst1q_f32(v_out + k, vbslq_f32(vcgtq_f32(vc, v_max), v_max, vc));
        vst1q_f32(ratio_out + k, ratio);
        vst1q_f32(self->term_xi_scratch + k, term_xi);
        vst1q_f32(self->v_scratch + k, v);
    }
    for (; k < n; k++)
        spp_dd_elem(self, power[k], noise[k], enhanced_prev[k], noise_prev[k],
                    xi_out + k, v_out + k, ratio_out + k, self->v_scratch + k,
                    self->term_xi_scratch + k);
}
#endif

static inline void spp_dd(SppEstimator* self, const float* power, const float* noise,
                          const float* noise_prev, const float* enhanced_prev,
                          float* xi_out, float* v_out, float* ratio_out, int n) {
#if ANR_VECTOR
    spp_dd_neon(self, power, noise, noise_prev, enhanced_prev, xi_out, v_out, ratio_out, n);
#else
    spp_dd_scalar(self, power, noise, noise_prev, enhanced_prev, xi_out, v_out, ratio_out, n);
#endif
}

/* Pass 1 of the SPP estimate: xi, the staged v and 1 + xi for the exponential pass, and the gain
 * stage's clamped v and xi / (1 + xi). */
static void spp_prepare(SppEstimator* self, const float* Y_psd, const float* noise_psd,
                        const float* enhanced_psd_prev, float* xi_out,
                        float* v_out, float* ratio_out) {
    const int n_freqs = self->n_freqs;
    const float xi_min = self->xi_min;
    float* v_scratch = self->v_scratch;
    float* term_xi_scratch = self->term_xi_scratch;

    // DD uses previous-hop noise; before initialization, use current noise.
    const float* noise_for_dd = self->is_initialized ? self->noise_psd_prev : noise_psd;

    if (self->is_initialized && enhanced_psd_prev != NULL) {
        spp_dd(self, Y_psd, noise_psd, noise_for_dd, enhanced_psd_prev, xi_out, v_out, ratio_out,
               n_freqs);
        return;
    }
    for (int k = 0; k < n_freqs; k++) {
        float gamma = Y_psd[k] / (noise_psd[k] + 1e-10f);

        /* No DD history: direct estimate with the same floor as the DD path. */
        float xi = gamma - 1.0f > xi_min ? gamma - 1.0f : xi_min;
        xi_out[k] = xi;

        float term_xi = 1.0f + xi;
        float ratio = xi / term_xi;
        float v = ratio * gamma;
        v_out[k] = spp_gain_v(v);
        ratio_out[k] = ratio;
        term_xi_scratch[k] = term_xi;
        v_scratch[k] = v;
    }
}

void spp_estimate(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* v_out,
    float* ratio_out
) {
    if (!self || !Y_psd || !noise_psd || !spp_out || !xi_out || !v_out || !ratio_out)
        return;

    int n_freqs = self->n_freqs;
    float prior_ratio = self->prior_ratio;
    float* v_scratch = self->v_scratch;
    float* term_xi_scratch = self->term_xi_scratch;

    spp_prepare(self, Y_psd, noise_psd, enhanced_psd_prev, xi_out, v_out, ratio_out);

    // exp(-v) in place.
    sk_fast_exp_neg_f32(v_scratch, v_scratch, n_freqs);

    // spp = 1 / (1 + prior_ratio * (1 + xi) * exp(-v))
    for (int k = 0; k < n_freqs; k++) {
        spp_out[k] = 1.0f / (1.0f + prior_ratio * term_xi_scratch[k] * v_scratch[k]);
    }

    // Save current noise for next-hop DD.
    memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));

    self->is_initialized = true;
}

void spp_reset(SppEstimator* self) {
    if (!self) return;

    memset(self->noise_psd_prev, 0, self->n_freqs * sizeof(float));

    self->is_initialized = false;
}
