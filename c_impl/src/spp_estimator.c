/**
 * spp_estimator.c - Speech Presence Probability Estimator
 *
 * Decision Directed method for SPP estimation
 * Based on Cohen & Berdugo (2001)
 *
 * SPP is a soft decision measure indicating the probability of
 * speech presence at each time-frequency bin.
 */

#include "spp_estimator.h"
#include "fft_wrapper.h"   /* ALIGN16 */
#include "simd_kernels.h"  /* sk_fast_exp_neg_f32 (kernel 24) -- provably
                             * scalar-reference-bit-exact by construction
                             * (verbatim op-sequence match -- see that
                             * header's top-of-file contract), gated by this
                             * TU's mandatory -ffp-contract=off same as every
                             * other caller. */
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

// Internal structure
struct SppEstimator {
    int n_freqs;

    float alpha;        // A priori SNR smoothing factor
    float q;            // Prior speech probability
    float xi_min;       // Minimum a priori SNR (linear)
    float prior_ratio;  // (1-q)/q precomputed

    // State arrays [n_freqs]
    float* gamma_prev;  // Previous frame a posteriori SNR
    float* noise_psd_prev;  // Previous frame noise PSD (for DD xi_dd_term1)

    // Per-call scratch [n_freqs] -- transient (fully overwritten every call,
    // nothing persisted across hops), pre-allocated here so the vectorized
    // exp_neg_v pass in spp_estimate()/spp_estimate_ex() can batch over the
    // whole bin range via sk_fast_exp_neg_f32 instead of a per-bin scalar
    // fast_exp_neg() call, with zero malloc on the hot path either way.
    // Shared by both functions (only one of the two runs per hop).
    //
    // v_scratch does DOUBLE duty (review-round buffer-reuse hardening):
    // nothing downstream reads the original v[k] this array holds once
    // pass 2 (sk_fast_exp_neg_f32) consumes it (confirmed by inspection of
    // both spp_estimate() and spp_estimate_ex() below -- pass 3 only reads
    // term_xi_scratch and the exp_neg_v result), so fast_exp_neg's own
    // output is written back into this SAME buffer in place
    // (sk_fast_exp_neg_f32(v_scratch, v_scratch, n_freqs)) instead of a
    // separate exp_neg_v_scratch array -- safe because sk_fast_exp_neg_f32
    // fully loads each 4-lane block into registers before storing that same
    // block back (no cross-lane/cross-block dependency), a contract now
    // recorded next to the kernel in simd_kernels.h (mirrors
    // sk_capply_gain_f32's pre-existing out==z contract) and exercised by
    // simd_selftest.c's test_exp_log_family_inplace(). term_xi_scratch MUST
    // stay separate: it is read at pass 3, after v_scratch has already been
    // overwritten in place by pass 2.
    float* v_scratch;         // v[k] = ξ/(1+ξ)·γ -> fast_exp_neg(v[k]), in place
    float* term_xi_scratch;   // term_xi[k] = 1+ξ[k]

    bool is_initialized;

    bool is_static;      // 1 == placed via spp_init() (caller-owned memory);
                         // 0 == heap instance from spp_create() (owns its mallocs)
};

/* Shared scalar/config initialisation — identical for both malloc and ext-mem
 * builds (state arrays are zeroed separately: calloc / block memset). */
static void spp_init_scalars(SppEstimator* self, int n_freqs,
                             const MmseLsaConfig* config) {
    self->n_freqs = n_freqs;
    self->alpha = config->alpha_xi;
    // Fix #9: clip q to (eps, 1-eps) so prior_ratio is well defined
    {
        const float _eps = 1e-6f;
        float q_clipped = config->q;
        if (q_clipped < _eps) q_clipped = _eps;
        if (q_clipped > 1.0f - _eps) q_clipped = 1.0f - _eps;
        self->q = q_clipped;
        self->prior_ratio = (1.0f - q_clipped) / q_clipped;
    }
    self->xi_min = powf(10.0f, config->xi_min_db / 10.0f);
    self->is_initialized = false;
}

/* ---- Static-memory (no malloc) variant ------------------------------------ */

size_t spp_get_mem_size(int n_freqs) {
    /* F05: explicit sign guard (see mcra_get_mem_size for the rationale) plus
     * checked arithmetic — MEM_SIZE_INVALID() below turns any overflow into
     * a `return 0` failure instead of a wrapped byte count. */
    if (n_freqs <= 0) return 0;
    size_t total = ALIGN16(sizeof(SppEstimator));
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* gamma_prev        */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* noise_psd_prev    */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* v_scratch         */
    total = ck_field_size(total, (size_t)n_freqs, sizeof(float));  /* term_xi_scratch   */
    return MEM_SIZE_INVALID(total) ? 0 : total;
}

SppEstimator* spp_init(void* mem, size_t mem_size,
                       int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config || !mem) return NULL;
    /* F07: reject a misaligned pool base before any write into it. spp_init
     * is a public entry point (declared in spp_estimator.h) — normally only
     * reached via mmse_lsa_init()'s own aligned sub-carve, but guard it
     * directly too in case it is ever called standalone. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    size_t need = spp_get_mem_size(n_freqs);
    if (need == 0 || mem_size < need) return NULL;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;

    SppEstimator* self = (SppEstimator*)cursor;
    cursor += ALIGN16(sizeof(SppEstimator));

    spp_init_scalars(self, n_freqs, config);
    self->is_static = true;

    self->gamma_prev     = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->noise_psd_prev = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));

    self->v_scratch         = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));
    self->term_xi_scratch   = (float*)cursor; cursor += ALIGN16((size_t)n_freqs * sizeof(float));

    return self;
}

/* ---- Heap (malloc) variant ------------------------------------------------ */

SppEstimator* spp_create(int n_freqs, const MmseLsaConfig* config) {
    if (n_freqs <= 0 || !config) return NULL;

    SppEstimator* self = (SppEstimator*)calloc(1, sizeof(SppEstimator));
    if (!self) return NULL;

    spp_init_scalars(self, n_freqs, config);
    self->is_static = false;

    // Allocate state arrays
    self->gamma_prev = (float*)calloc(n_freqs, sizeof(float));
    self->noise_psd_prev = (float*)calloc(n_freqs, sizeof(float));

    // Allocate per-call scratch (see struct SppEstimator comment)
    self->v_scratch         = (float*)calloc(n_freqs, sizeof(float));
    self->term_xi_scratch   = (float*)calloc(n_freqs, sizeof(float));

    if (!self->gamma_prev || !self->noise_psd_prev ||
        !self->v_scratch || !self->term_xi_scratch) {
        spp_destroy(self);
        return NULL;
    }

    return self;
}

void spp_destroy(SppEstimator* self) {
    if (!self) return;
    if (self->is_static) return;  /* caller owns the block; nothing to free */

    if (self->gamma_prev) free(self->gamma_prev);
    if (self->noise_psd_prev) free(self->noise_psd_prev);
    if (self->v_scratch) free(self->v_scratch);
    if (self->term_xi_scratch) free(self->term_xi_scratch);

    free(self);
}

void spp_estimate(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* gain_prev,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out
) {
    if (!self || !Y_psd || !noise_psd || !spp_out || !xi_out || !gamma_out) return;

    int n_freqs = self->n_freqs;
    float alpha = self->alpha;
    float xi_min = self->xi_min;
    float prior_ratio = self->prior_ratio;
    float* v_scratch = self->v_scratch;
    float* term_xi_scratch = self->term_xi_scratch;

    // Fix #3: DD xi_dd_term1 should use previous frame's noise_psd.
    // On the first DD call (after one estimate()), noise_psd_prev already holds
    // the prior frame's noise; if not yet populated, fall back to current noise.
    const float* noise_for_dd = self->is_initialized ? self->noise_psd_prev : noise_psd;

    // Pass 1 (scalar): gamma/xi (Decision Directed method, unmodified) +
    // v/term_xi scratch writes. exp_neg_v/spp_out are deferred to the
    // vectorized passes below so fast_exp_neg can batch over the whole bin
    // range via sk_fast_exp_neg_f32 instead of a per-bin scalar call.
    for (int k = 0; k < n_freqs; k++) {
        // 1. Calculate a posteriori SNR
        // γ = |Y|² / λ_n
        float gamma = Y_psd[k] / (noise_psd[k] + 1e-10f);
        gamma_out[k] = gamma;

        // 2. Estimate a priori SNR using Decision Directed method
        float xi;
        if (!self->is_initialized || gain_prev == NULL) {
            // First frame: direct estimate
            xi = gamma > 1.0f ? gamma - 1.0f : 0.0f;
        } else {
            // DD method: ξ = α·|X̂_{n-1}|²/λ_n_prev + (1-α)·max(γ-1, 0)
            float xi_dd_term1;
            if (enhanced_psd_prev != NULL) {
                // Use provided enhanced PSD (recommended)
                xi_dd_term1 = enhanced_psd_prev[k] / (noise_for_dd[k] + 1e-10f);
            } else {
                // Fallback: use gain²·γ_prev approximation
                float g2 = gain_prev[k] * gain_prev[k];
                xi_dd_term1 = g2 * self->gamma_prev[k];
            }

            float max_gamma_m1 = gamma > 1.0f ? gamma - 1.0f : 0.0f;
            float xi_dd = alpha * xi_dd_term1 + (1.0f - alpha) * max_gamma_m1;

            // Apply minimum constraint
            xi = xi_dd > xi_min ? xi_dd : xi_min;
        }
        xi_out[k] = xi;

        // 3. Calculate log-likelihood ratio: v = ξ/(1+ξ)·γ -- scratched for
        // the vectorized exp_neg pass below (term_xi scratched too since the
        // final SPP formula in pass 3 needs both alongside exp_neg_v).
        float term_xi = 1.0f + xi;
        float v = xi / term_xi * gamma;
        term_xi_scratch[k] = term_xi;
        v_scratch[k] = v;

        // Save for next frame
        self->gamma_prev[k] = gamma;
    }

    // Pass 2 (vectorized, in place): exp_neg_v[k] = fast_exp_neg(v[k]) over
    // the whole bin range via sk_fast_exp_neg_f32 (simd_kernels.h kernel 24)
    // -- bit-exact by construction (see that header's contract). Written
    // back into v_scratch itself: nothing downstream reads the original
    // v[k] again (see the struct field comment above), and
    // sk_fast_exp_neg_f32 documents out==x as safe (per-4-lane-block
    // load-then-store, no cross-block state).
    sk_fast_exp_neg_f32(v_scratch, v_scratch, n_freqs);

    // Pass 3 (scalar): SPP = 1 / (1 + prior_ratio × (1+ξ) × exp(-v)).
    for (int k = 0; k < n_freqs; k++) {
        spp_out[k] = 1.0f / (1.0f + prior_ratio * term_xi_scratch[k] * v_scratch[k]);
    }

    // Fix #3: save current noise_psd for next frame's DD term
    memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));

    self->is_initialized = true;
}

void spp_reset(SppEstimator* self) {
    if (!self) return;

    memset(self->gamma_prev, 0, self->n_freqs * sizeof(float));
    memset(self->noise_psd_prev, 0, self->n_freqs * sizeof(float));

    self->is_initialized = false;
}

bool spp_is_initialized(const SppEstimator* self) {
    return self ? self->is_initialized : false;
}

#ifdef USE_SHARED_XI_RATIO
void spp_estimate_ex(
    SppEstimator* self,
    const float* Y_psd,
    const float* noise_psd,
    const float* gain_prev,
    const float* enhanced_psd_prev,
    float* spp_out,
    float* xi_out,
    float* gamma_out,
    float* v_out
) {
    if (!self || !Y_psd || !noise_psd || !spp_out || !xi_out || !gamma_out) return;

    int n_freqs = self->n_freqs;
    float alpha = self->alpha;
    float xi_min = self->xi_min;
    float prior_ratio = self->prior_ratio;
    float* v_scratch = self->v_scratch;
    float* term_xi_scratch = self->term_xi_scratch;

    // Fix #3: DD xi_dd_term1 uses previous frame's noise_psd
    const float* noise_for_dd = self->is_initialized ? self->noise_psd_prev : noise_psd;

    // Pass 1 (scalar): gamma/xi/v/term_xi (unmodified) + v/term_xi scratch
    // writes. exp_neg_v/spp_out are deferred to the vectorized passes below
    // so fast_exp_neg can batch over the whole bin range via
    // sk_fast_exp_neg_f32 instead of a per-bin scalar call.
    for (int k = 0; k < n_freqs; k++) {
        // 1. Calculate a posteriori SNR
        float gamma = Y_psd[k] / (noise_psd[k] + 1e-10f);
        gamma_out[k] = gamma;

        // 2. Estimate a priori SNR using Decision Directed method
        float xi;
        if (!self->is_initialized || gain_prev == NULL) {
            xi = gamma > 1.0f ? gamma - 1.0f : 0.0f;
        } else {
            float xi_dd_term1;
            if (enhanced_psd_prev != NULL) {
                xi_dd_term1 = enhanced_psd_prev[k] / (noise_for_dd[k] + 1e-10f);
            } else {
                float g2 = gain_prev[k] * gain_prev[k];
                xi_dd_term1 = g2 * self->gamma_prev[k];
            }

            float max_gamma_m1 = gamma > 1.0f ? gamma - 1.0f : 0.0f;
            float xi_dd = alpha * xi_dd_term1 + (1.0f - alpha) * max_gamma_m1;
            xi = xi_dd > xi_min ? xi_dd : xi_min;
        }
        xi_out[k] = xi;

        // 3. Calculate v = ξ/(1+ξ)·γ (compute term_xi once)
        float term_xi = 1.0f + xi;
        float v = (xi / term_xi) * gamma;

        // Output v for gain calculator to reuse
        if (v_out) {
            v_out[k] = v;
        }

        // Scratch v/term_xi for the vectorized exp_neg pass below (pass 3
        // needs both alongside exp_neg_v to finish the SPP formula).
        term_xi_scratch[k] = term_xi;
        v_scratch[k] = v;

        // Save for next frame
        self->gamma_prev[k] = gamma;
    }

    // Pass 2 (vectorized, in place): exp_neg_v[k] = fast_exp_neg(v[k]) over
    // the whole bin range via sk_fast_exp_neg_f32 (simd_kernels.h kernel 24)
    // -- bit-exact by construction (see that header's contract). Written
    // back into v_scratch itself: nothing downstream reads the original
    // v[k] again (see the struct field comment above), and
    // sk_fast_exp_neg_f32 documents out==x as safe (per-4-lane-block
    // load-then-store, no cross-block state).
    sk_fast_exp_neg_f32(v_scratch, v_scratch, n_freqs);

    // Pass 3 (scalar): SPP = 1 / (1 + prior_ratio × term_xi × exp_neg_v).
    for (int k = 0; k < n_freqs; k++) {
        spp_out[k] = 1.0f / (1.0f + prior_ratio * term_xi_scratch[k] * v_scratch[k]);
    }

    // Fix #3: save current noise_psd for next frame's DD term
    memcpy(self->noise_psd_prev, noise_psd, n_freqs * sizeof(float));

    self->is_initialized = true;
}
#endif
