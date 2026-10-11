/* ANR frequency-domain core: power -> MCRA/SPP -> OM-LSA gain -> output spectrum. Caller owns
 * windowing, FFT/IFFT and overlap-add.
 */

#include "anr.h"
#include "anr_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"
#include "fft_wrapper.h"   /* Complex, fft_power, fft_apply_gain, ALIGN16 */
#include "fast_math.h"
#include "simd_kernels.h"  /* Bit-exact SIMD math kernels; requires -ffp-contract=off. */

#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "anr_internal.h"

/* Instance state. */

struct AnrDenoiser {
    AnrConfig config;

    int n_freqs;               /* fft_size/2 + 1 */

    float* power;              /* |X[k]|^2  [n_freqs] */
    float* noise_aug;          /* N²+R² scratch for the unified-gain path */

    McraNoiseEstimator* noise_est;
    SppEstimator*       spp_est;

    float* spp;
    float* xi;
    float* gamma;
    float* gain;

#ifdef USE_SHARED_XI_RATIO
    float* v;
#endif

    /* Preallocated gain scratch[n_freqs]. gain_v_scratch is reused in-place after each SIMD
     * pass consumes its prior value. gain_xi_ratio_scratch must stay separate: ratio is
     * consumed after v is overwritten, then G_H1 is retained for DD. The SPP v array remains
     * an input under USE_SHARED_XI_RATIO.
     */
    float* gain_v_scratch;         /* v -> E1 -> 0.5*E1 -> exp -> log(G_H1 + eps). */
    float* gain_xi_ratio_scratch;  /* xi/(1+xi) -> G_H1 for DD. */

    float* gain_prev;
    float* enhanced_psd_prev;

    /* Frame speech evidence; scalar state only. */
    float  cross_band_prior_state;
    float  cross_band_prior_lift;
    int    speech_bin_start;
    int    speech_bin_end;
    float  speech_band_inv_count;
    int    noise_gate_lf_bin;
    float  noise_gate_xi;
    float  speech_protect_frame_threshold;   /* config value + (q - anchor q) */
    bool   slow_lf_rise;
    float  makeup_prior_state;

    int    init_frame_count;
    float* init_power_sum;
    bool   is_initialized;

    float  g_min;
    float  log_g_min;
    float  alpha_g;
    float  alpha_attack;
    float  alpha_decay;
    float  speech_protect_floor_gain;
    float  log_speech_protect_floor_gain;
    bool   speech_protect_frame_active;
    float* log_gain_prev;
    bool   gain_initialized;

    bool   is_static;   /* true: caller-owned pool; false: heap-owned allocations. */
};

/* Gain and speech controls. */

/* Update coefficients without clearing gain history. */
static void apply_gain_config_scalars(AnrDenoiser* self,
                                       const AnrConfig* config) {
    /* g_min is an amplitude floor: 10^(g_min_db/20). SNR and power dB use /10. */
    self->g_min        = powf(10.0f, config->g_min_db / 20.0f);
    self->log_g_min    = logf(self->g_min + 1e-10f);
    self->alpha_g      = config->alpha_g;
    self->alpha_attack = config->alpha_attack;
    self->alpha_decay  = config->alpha_decay;
    self->speech_protect_floor_gain =
        powf(10.0f, config->speech_protect_floor_db / 20.0f);
    self->log_speech_protect_floor_gain =
        fast_log(self->speech_protect_floor_gain + 1e-10f);
    self->noise_gate_xi = powf(10.0f, config->noise_gate_xi_db / 10.0f);
    /* See ANR_SPEECH_PROTECT_ANCHOR_Q (anr_types.h). */
    self->speech_protect_frame_threshold =
        config->speech_protect_frame_threshold +
        (config->q - ANR_SPEECH_PROTECT_ANCHOR_Q);
}

/* First bin at or above hz, and the bin count covering [0, hz] inclusive. */
static int hz_to_bin_ceil(float hz, const AnrConfig* config) {
    return (int)ceilf(hz * (float)config->fft_size /
                      (float)config->sample_rate);
}

static int hz_to_bin_floor_inclusive(float hz, const AnrConfig* config) {
    return (int)floorf(hz * (float)config->fft_size /
                       (float)config->sample_rate) + 1;
}

static void update_noise_gate_geometry(AnrDenoiser* self,
                                       const AnrConfig* config) {
    self->noise_gate_lf_bin = hz_to_bin_ceil(config->noise_gate_lf_hz, config);
    if (self->noise_gate_lf_bin < 1) self->noise_gate_lf_bin = 1;
    if (self->noise_gate_lf_bin > self->n_freqs)
        self->noise_gate_lf_bin = self->n_freqs;
}

static void reset_gain_state(AnrDenoiser* self) {
    if (self->log_gain_prev)
        memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    self->gain_initialized = false;
}

static void reset_frame_evidence_state(AnrDenoiser* self) {
    self->cross_band_prior_state = 0.0f;
    self->cross_band_prior_lift = 0.0f;
    self->speech_protect_frame_active = false;
    self->slow_lf_rise = false;
    self->makeup_prior_state = 0.5f;
}

/* First-order logit lift of a posterior by the frame prior (optional; off by default). */
static inline float lift_spp(float spp_k, float lift) {
    return spp_k + lift * spp_k * (1.0f - spp_k);
}

/* Next-hop DD state: emitted gain/log gain and enhanced power formed from dd_gain (emitted
 * gain, or G_H1 when enabled).
 */
static inline void store_gain_state(AnrDenoiser* self, int k, float gain,
                                    float log_gain, float dd_gain) {
    self->log_gain_prev[k]     = log_gain;
    self->gain_prev[k]         = gain;
    self->enhanced_psd_prev[k] = dd_gain * dd_gain * self->power[k];
}

/* Reduce SPP mean and xi fraction for LF gain/tracker guards. Optional prior/make-up controls
 * reuse this scan; skip when all consumers are disabled.
 */
static void update_frame_speech_evidence(AnrDenoiser* self) {
    const AnrConfig* cfg = &self->config;
    if (!cfg->cross_band_speech_prior && !cfg->speech_protect_floor &&
        !cfg->speech_aware_noise_tracking && !cfg->makeup_gain)
        return;
    float evidence_sum = 0.0f;
    int xi_high = 0;
    for (int k = self->speech_bin_start; k < self->speech_bin_end; k++) {
        evidence_sum += self->spp[k];
        if (self->xi[k] > self->noise_gate_xi) xi_high++;
    }
    float evidence = evidence_sum * self->speech_band_inv_count;
    float xi_fraction = (float)xi_high * self->speech_band_inv_count;
    self->speech_protect_frame_active =
        evidence >= self->speech_protect_frame_threshold;
    self->slow_lf_rise = self->config.speech_aware_noise_tracking &&
                         xi_fraction > self->config.noise_gate_frame_frac;
    if (self->config.makeup_gain) {
        float target = xi_fraction / 0.15f;
        if (target > 1.0f) target = 1.0f;
        self->makeup_prior_state +=
            0.1f * (target - self->makeup_prior_state);
        if (self->makeup_prior_state < 0.01f)
            self->makeup_prior_state = 0.01f;
    }

    if (!self->config.cross_band_speech_prior) return;

    float target = (evidence - 0.50f) / (0.70f - 0.50f);
    if (target < 0.0f) target = 0.0f;
    if (target > 1.0f) target = 1.0f;
    float a = self->config.cross_band_speech_prior_alpha;
    self->cross_band_prior_state =
        a * self->cross_band_prior_state + (1.0f - a) * target;

    const float base_q = self->config.q;
    const float max_q = self->config.cross_band_speech_prior_max_q;
    float prior = base_q + self->cross_band_prior_state * (max_q - base_q);
    /* First-order logit lift about q=0.5; the overlay caps the prior lift at +0.04. */
    self->cross_band_prior_lift = 4.0f * (prior - base_q);
}

/* Optional output make-up follows the unscaled OM-LSA/DD update; its scalar is not fed into
 * next-hop DD. Disabled by default.
 */
static void apply_frame_makeup(AnrDenoiser* self) {
    if (!self->config.makeup_gain) return;
    float e_in = 0.0f;
    float e_out = 0.0f;
    for (int k = 0; k < self->n_freqs; k++) {
        float g = self->gain[k];
        e_in += self->power[k];
        e_out += g * g * self->power[k];
    }
    float g_frame = sqrtf(e_out / (e_in + 1e-20f));
    float scale_up = 1.0f;
    if (g_frame > self->config.makeup_blim) {
        scale_up = 1.0f + self->config.makeup_up_slope
                             * (g_frame - self->config.makeup_blim);
        if (g_frame * scale_up > 1.0f) scale_up = 1.0f / g_frame;
    }
    float scale_down = 1.0f;
    if (g_frame < self->config.makeup_blim) {
        float floored = g_frame > self->g_min ? g_frame : self->g_min;
        scale_down = 1.0f - self->config.makeup_down_slope
                              * (self->config.makeup_blim - floored);
    }
    float p = self->makeup_prior_state;
    float scale = p * scale_up + (1.0f - p) * scale_down;
    for (int k = 0; k < self->n_freqs; k++) self->gain[k] *= scale;
}

/* Apply the LF speech floor only in protected bins; repair DD state where final gain changes. */
static void apply_low_band_speech_floor(AnrDenoiser* self,
                                        float* gain_out) {
    if (!self->config.speech_protect_floor ||
        !self->speech_protect_frame_active) return;

    const bool  cross_band_prior = self->config.cross_band_speech_prior;
    const bool  dd_from_gmmse    = self->config.dd_from_gmmse;
    const float threshold        = self->config.speech_protect_threshold;
    const float floor_gain       = self->speech_protect_floor_gain;
    const int   end              = self->noise_gate_lf_bin;
    for (int k = 1; k < end; k++) {
        float spp_k = self->spp[k];
        if (cross_band_prior)
            spp_k = lift_spp(spp_k, self->cross_band_prior_lift);
        if (spp_k <= threshold || gain_out[k] >= floor_gain) continue;

        gain_out[k] = floor_gain;
        /* gain_xi_ratio_scratch still holds this frame's G_H1 from pass 5. */
        store_gain_state(self, k, floor_gain,
                         self->log_speech_protect_floor_gain,
                         dd_from_gmmse ? self->gain_xi_ratio_scratch[k]
                                       : floor_gain);
    }
}

static void update_noise_estimator(AnrDenoiser* self) {
    mcra_update_ex(self->noise_est, self->power, self->spp,
                   self->slow_lf_rise, self->noise_gate_lf_bin,
                   self->config.alpha_d_speech);
}

static const float* prepare_noise_for_spp(AnrDenoiser* self,
                                           const float* noise_psd,
                                           const float* extra_noise_psd) {
    const float scale = self->config.noise_over_subtraction;
    const int   nf    = self->n_freqs;
    if (!extra_noise_psd && scale == 1.0f) return noise_psd;
    if (extra_noise_psd) {
        for (int k = 0; k < nf; k++)
            self->noise_aug[k] = scale * (noise_psd[k] + extra_noise_psd[k]);
    } else {
        for (int k = 0; k < nf; k++)
            self->noise_aug[k] = scale * noise_psd[k];
    }
    return self->noise_aug;
}

/* Gain inputs from the SPP stage: v clamped to [1e-10, 700] (NaN passes through) and the
 * a-priori ratio xi/(1+xi) recovered as v/(gamma + 1e-10). The output arrays must not overlap
 * the inputs.
 */
#ifdef USE_SHARED_XI_RATIO
static inline void gain_prepare_elem(float v_in, float gamma, float* v_out,
                                     float* ratio_out) {
    float v = v_in;
    if (v < 1e-10f) v = 1e-10f;
    if (v > 700.0f) v = 700.0f;
    *v_out = v;
    *ratio_out = v_in / (gamma + 1e-10f);
}

static inline ANR_MAYBE_UNUSED void gain_prepare_scalar(const float* v_in, const float* gamma,
                                                        float* v_out, float* ratio_out, int n) {
    for (int k = 0; k < n; k++)
        gain_prepare_elem(v_in[k], gamma[k], v_out + k, ratio_out + k);
}

#if SK_HAVE_NEON
static inline void gain_prepare_neon(const float* v_in, const float* gamma,
                                     float* v_out, float* ratio_out, int n) {
    const float32x4_t eps = vdupq_n_f32(1e-10f);
    const float32x4_t v_max = vdupq_n_f32(700.0f);
    int k = 0;
    for (; k + 4 <= n; k += 4) {
        float32x4_t v_raw = vld1q_f32(v_in + k);
        float32x4_t ratio = vdivq_f32(v_raw, vaddq_f32(vld1q_f32(gamma + k), eps));
        float32x4_t v = vbslq_f32(vcltq_f32(v_raw, eps), eps, v_raw);
        v = vbslq_f32(vcgtq_f32(v, v_max), v_max, v);
        vst1q_f32(v_out + k, v);
        vst1q_f32(ratio_out + k, ratio);
    }
    for (; k < n; k++)
        gain_prepare_elem(v_in[k], gamma[k], v_out + k, ratio_out + k);
}
#endif

static inline void gain_prepare(const float* v_in, const float* gamma,
                                float* v_out, float* ratio_out, int n) {
#if ANR_VECTOR
    gain_prepare_neon(v_in, gamma, v_out, ratio_out, n);
#else
    gain_prepare_scalar(v_in, gamma, v_out, ratio_out, n);
#endif
}
#endif

#ifdef USE_FAST_GAIN_SMOOTHING
/* Batched final-gain passes: blend and smooth the log gain, then (after the caller's exp over
 * the clamped log gain) select, store the next-hop state and form the DD power.
 */
typedef struct {
    float log_g_min;
    float g_min;
    float alpha_attack;
    float alpha_decay;
    float prior_lift;
    bool  cross_band_prior;
    bool  smooth;          /* smooth against the previous log gain */
    bool  dd_from_gmmse;
} FinalGainParams;

/* log_mmse: log(G_H1 + eps) in, blended and smoothed log gain out. emitted: that log gain clamped
 * to [log_g_min, 0], ready for exp(). prev_log is read only when smooth is set.
 */
static inline void final_blend_elem(const FinalGainParams* g, float posterior, float prev_log,
                                    float* log_mmse, float* emitted) {
    float p = posterior;
    if (g->cross_band_prior) p = lift_spp(p, g->prior_lift);
    float log_gain = p * *log_mmse + (1.0f - p) * g->log_g_min;
    if (g->smooth) {
        float alpha = (log_gain > prev_log) ? g->alpha_attack : g->alpha_decay;
        log_gain = alpha * prev_log + (1.0f - alpha) * log_gain;
    }
    *log_mmse = log_gain;
    *emitted = (log_gain < g->log_g_min) ? g->log_g_min
               : (log_gain > 0.0f) ? 0.0f : log_gain;
}

static inline ANR_MAYBE_UNUSED void final_blend_scalar(const FinalGainParams* g,
                                                       const float* posterior, float* log_mmse,
                                                       const float* saved_logs, float* emitted,
                                                       int n) {
    for (int k = 0; k < n; k++)
        final_blend_elem(g, posterior[k], g->smooth ? saved_logs[k] : 0.0f, log_mmse + k,
                         emitted + k);
}

/* exp_gain: exp() of the clamped log gain in, final gain out. The log gain outside
 * [log_g_min, 0] takes g_min / 1 and the matching saved log gain.
 */
static inline void final_store_elem(const FinalGainParams* g, float log_gain, float conditional,
                                    float power, float* exp_gain, float* saved_log,
                                    float* previous_gain, float* previous_psd) {
    float gain = *exp_gain;
    float log_save = log_gain;
    if (log_gain < g->log_g_min) {
        gain = g->g_min;
        log_save = g->log_g_min;
    } else if (log_gain > 0.0f) {
        gain = 1.0f;
        log_save = 0.0f;
    }
    *exp_gain = gain;
    *saved_log = log_save;
    *previous_gain = gain;
    float dd_gain = g->dd_from_gmmse ? conditional : gain;
    *previous_psd = dd_gain * dd_gain * power;
}

static inline ANR_MAYBE_UNUSED void final_store_scalar(const FinalGainParams* g,
                                                       const float* log_gain, float* exp_gain,
                                                       float* saved_logs, float* previous_gain,
                                                       float* previous_psd,
                                                       const float* conditional_gain,
                                                       const float* power, int n) {
    for (int k = 0; k < n; k++)
        final_store_elem(g, log_gain[k], conditional_gain[k], power[k], exp_gain + k,
                         saved_logs + k, previous_gain + k, previous_psd + k);
}

#if SK_HAVE_NEON
static inline void final_blend_neon(const FinalGainParams* g, const float* posterior,
                                    float* log_mmse, const float* saved_logs, float* emitted,
                                    int n) {
    const float32x4_t one = vdupq_n_f32(1.0f);
    const float32x4_t zero = vdupq_n_f32(0.0f);
    const float32x4_t log_min = vdupq_n_f32(g->log_g_min);
    const float32x4_t lift = vdupq_n_f32(g->prior_lift);
    const float32x4_t attack = vdupq_n_f32(g->alpha_attack);
    const float32x4_t decay = vdupq_n_f32(g->alpha_decay);
    int k = 0;
    for (; k + 4 <= n; k += 4) {
        float32x4_t p = vld1q_f32(posterior + k);
        if (g->cross_band_prior)
            p = vaddq_f32(p, vmulq_f32(vmulq_f32(lift, p), vsubq_f32(one, p)));
        float32x4_t log_gain = vaddq_f32(vmulq_f32(p, vld1q_f32(log_mmse + k)),
                                         vmulq_f32(vsubq_f32(one, p), log_min));
        if (g->smooth) {
            float32x4_t prev = vld1q_f32(saved_logs + k);
            float32x4_t alpha = vbslq_f32(vcgtq_f32(log_gain, prev), attack, decay);
            log_gain = vaddq_f32(vmulq_f32(alpha, prev),
                                 vmulq_f32(vsubq_f32(one, alpha), log_gain));
        }
        vst1q_f32(log_mmse + k, log_gain);
        float32x4_t clamped = vbslq_f32(vcgtq_f32(log_gain, zero), zero, log_gain);
        vst1q_f32(emitted + k, vbslq_f32(vcltq_f32(log_gain, log_min), log_min, clamped));
    }
    for (; k < n; k++)
        final_blend_elem(g, posterior[k], g->smooth ? saved_logs[k] : 0.0f, log_mmse + k,
                         emitted + k);
}

static inline void final_store_neon(const FinalGainParams* g, const float* log_gain,
                                    float* exp_gain, float* saved_logs, float* previous_gain,
                                    float* previous_psd, const float* conditional_gain,
                                    const float* power, int n) {
    const float32x4_t one = vdupq_n_f32(1.0f);
    const float32x4_t zero = vdupq_n_f32(0.0f);
    const float32x4_t log_min = vdupq_n_f32(g->log_g_min);
    const float32x4_t gain_min = vdupq_n_f32(g->g_min);
    int k = 0;
    for (; k + 4 <= n; k += 4) {
        float32x4_t lg = vld1q_f32(log_gain + k);
        uint32x4_t below = vcltq_f32(lg, log_min);
        uint32x4_t above = vcgtq_f32(lg, zero);
        float32x4_t gain = vbslq_f32(below, gain_min,
                                     vbslq_f32(above, one, vld1q_f32(exp_gain + k)));
        float32x4_t log_save = vbslq_f32(below, log_min, vbslq_f32(above, zero, lg));
        vst1q_f32(exp_gain + k, gain);
        vst1q_f32(saved_logs + k, log_save);
        vst1q_f32(previous_gain + k, gain);
        float32x4_t dd = g->dd_from_gmmse ? vld1q_f32(conditional_gain + k) : gain;
        vst1q_f32(previous_psd + k, vmulq_f32(vmulq_f32(dd, dd), vld1q_f32(power + k)));
    }
    for (; k < n; k++)
        final_store_elem(g, log_gain[k], conditional_gain[k], power[k], exp_gain + k,
                         saved_logs + k, previous_gain + k, previous_psd + k);
}
#endif
#endif

static void calculate_gain(AnrDenoiser* self,
                            const float* spp,
                            const float* xi,
                            const float* gamma,
                            const float* v_in,
                            float* gain_out) {
    int   n_freqs      = self->n_freqs;
    float g_min        = self->g_min;
    float log_g_min    = self->log_g_min;
    float alpha_attack = self->alpha_attack;
    float alpha_decay  = self->alpha_decay;
    bool  cross_band_prior = self->config.cross_band_speech_prior;
    float prior_lift = self->cross_band_prior_lift;
    bool  dd_from_gmmse = self->config.dd_from_gmmse;

    float* v_scratch        = self->gain_v_scratch;
    float* xi_ratio_scratch = self->gain_xi_ratio_scratch;

    /* Prepare clamped v and xi/(1+xi), preserving scalar operation order. */
#ifdef USE_SHARED_XI_RATIO
    if (v_in != NULL) {
        gain_prepare(v_in, gamma, v_scratch, xi_ratio_scratch, n_freqs);
    } else
#else
    (void)v_in;
#endif
    {
        for (int k = 0; k < n_freqs; k++) {
            float xi_ratio = xi[k] / (1.0f + xi[k]);
            float v        = xi_ratio * gamma[k];

            if (v < 1e-10f) v = 1e-10f;
            if (v > 700.0f) v = 700.0f;

            v_scratch[k]        = v;
            xi_ratio_scratch[k] = xi_ratio;
        }
    }

    /* E1(v) in-place; USE_STANDARD_MATH selects exp1_approx(). */
    sk_exp1_approx_f32(v_scratch, v_scratch, n_freqs);

    /* Scale E1 by 0.5 before exponentiation. */
    for (int k = 0; k < n_freqs; k++) {
        v_scratch[k] = 0.5f * v_scratch[k];
    }

    /* Exponentiate in-place; SIMD kernel supports exact input/output aliasing. */
    sk_fast_exp_f32(v_scratch, v_scratch, n_freqs);

    /* G_H1 = clamp(xi_ratio * exp(0.5*E1), g_min, 1). Retain G_H1 for DD; add eps only to the
     * following log input.
     */
    for (int k = 0; k < n_freqs; k++) {
        float gain_mmse = xi_ratio_scratch[k] * v_scratch[k];
        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f)  gain_mmse = 1.0f;
        xi_ratio_scratch[k] = gain_mmse;
        v_scratch[k] = gain_mmse + 1e-10f;
    }

    /* log(G_H1 + eps) in-place; SIMD kernel supports exact aliasing. */
    sk_fast_log_f32(v_scratch, v_scratch, n_freqs);

#if defined(USE_FAST_GAIN_SMOOTHING) && ANR_VECTOR
    {
        FinalGainParams params = {log_g_min, g_min, alpha_attack, alpha_decay, prior_lift,
                                  cross_band_prior, self->gain_initialized, dd_from_gmmse};
        final_blend_neon(&params, spp, v_scratch, self->log_gain_prev, gain_out, n_freqs);
        sk_fast_exp_f32(gain_out, gain_out, n_freqs);
        final_store_neon(&params, v_scratch, gain_out, self->log_gain_prev, self->gain_prev,
                         self->enhanced_psd_prev, xi_ratio_scratch, self->power, n_freqs);
    }
    apply_low_band_speech_floor(self, gain_out);
    self->gain_initialized = true;
    return;
#endif

    /* Blend OM-LSA log gain, smooth against the previous hop and store DD state. Each bin reads
     * its own prior-hop history before overwriting it.
     */
    for (int k = 0; k < n_freqs; k++) {
        float spp_k   = spp[k];

        if (cross_band_prior) spp_k = lift_spp(spp_k, prior_lift);

        float log_gain_mmse = v_scratch[k];
        float log_gain      = spp_k * log_gain_mmse +
                              (1.0f - spp_k) * log_g_min;

        if (self->gain_initialized) {
            float prev  = self->log_gain_prev[k];
            float alpha = (log_gain > prev) ? alpha_attack : alpha_decay;
            log_gain    = alpha * prev + (1.0f - alpha) * log_gain;
        }

#ifdef USE_FAST_GAIN_SMOOTHING
        float gain, log_gain_save;
        if (log_gain < log_g_min) {
            gain = g_min;  log_gain_save = log_g_min;
        } else if (log_gain > 0.0f) {
            gain = 1.0f;   log_gain_save = 0.0f;
        } else {
            gain = fast_exp(log_gain);  log_gain_save = log_gain;
        }
        gain_out[k] = gain;
#else
        float gain = fast_exp(log_gain);
#ifndef USE_SINGLE_CLAMP
        if (gain < g_min) gain = g_min;
        if (gain > 1.0f)  gain = 1.0f;
#endif
        gain_out[k] = gain;
        float log_gain_save = fast_log(gain + 1e-10f);
#endif

        /* Store emitted gain and selected DD power for the next SPP estimate. */
        store_gain_state(self, k, gain, log_gain_save,
                         dd_from_gmmse ? xi_ratio_scratch[k] : gain);
    }

    apply_low_band_speech_floor(self, gain_out);

    self->gain_initialized = true;
}

/* Shared frame stage: SPP/DD -> speech evidence -> gain/floors -> optional make-up -> noise
 * update. Tracker receives clean input power, never the augmented extra-noise floor, and is
 * not advanced on digital-silence frames.
 */
static void run_frame_gain_stage(AnrDenoiser* self,
                                 const float* noise_for_spp,
                                 bool track_noise) {
#ifdef USE_SHARED_XI_RATIO
    spp_estimate_ex(self->spp_est, self->power, noise_for_spp,
                    self->gain_prev, self->enhanced_psd_prev,
                    self->spp, self->xi, self->gamma, self->v);
    update_frame_speech_evidence(self);
    calculate_gain(self, self->spp, self->xi, self->gamma,
                   self->v, self->gain);
#else
    spp_estimate(self->spp_est, self->power, noise_for_spp,
                 self->gain_prev, self->enhanced_psd_prev,
                 self->spp, self->xi, self->gamma);
    update_frame_speech_evidence(self);
    calculate_gain(self, self->spp, self->xi, self->gamma,
                   NULL, self->gain);
#endif
    apply_frame_makeup(self);
    if (track_noise) update_noise_estimator(self);
}

/* Shared initialization. */

static void _setup(AnrDenoiser* self, const AnrConfig* config) {
    self->config           = *config;
    self->n_freqs          = config->fft_size / 2 + 1;
    self->init_frame_count = 0;
    self->is_initialized   = false;
    self->speech_bin_start = hz_to_bin_ceil(80.0f, config);
    self->speech_bin_end = hz_to_bin_floor_inclusive(4000.0f, config);
    if (self->speech_bin_start < 1) self->speech_bin_start = 1;
    if (self->speech_bin_end > self->n_freqs)
        self->speech_bin_end = self->n_freqs;
    if (self->speech_bin_end <= self->speech_bin_start) {
        self->speech_bin_start = 0;
        self->speech_bin_end = self->n_freqs;
    }
    self->speech_band_inv_count =
        1.0f / (float)(self->speech_bin_end - self->speech_bin_start);
    update_noise_gate_geometry(self, config);
    apply_gain_config_scalars(self, config);
    reset_gain_state(self);
    reset_frame_evidence_state(self);
}

/* Lifecycle. */

/* Single-block static allocation. */

size_t anr_get_mem_size(const AnrConfig* config) {
    /* Validate dimensions before size arithmetic. */
    if (!anr_validate_config(config)) return 0;
    int nf = config->fft_size / 2 + 1;

    size_t total = ALIGN16(sizeof(AnrDenoiser));
    /* Checked aligned sizes saturate on overflow; invalid totals return 0. */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* power             */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* noise_aug         */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* spp               */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* xi                */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* gamma             */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* gain              */
#ifdef USE_SHARED_XI_RATIO
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* v                     */
#endif
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* gain_v_scratch        */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* gain_xi_ratio_scratch */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* gain_prev         */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* enhanced_psd_prev */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* init_power_sum    */
    total = ck_field_size(total, (size_t)nf, sizeof(float));   /* log_gain_prev     */

    size_t mcra_sz = mcra_get_mem_size(nf, config);
    size_t spp_sz  = spp_get_mem_size(nf);
    if (mcra_sz == 0 || spp_sz == 0) return 0;   /* sub-module rejected the config */

    total = ck_add_size(total, mcra_sz);
    total = ck_add_size(total, spp_sz);

    return MEM_SIZE_INVALID(total) ? 0 : total;
}

AnrDenoiser* anr_init(void* mem, size_t mem_size,
                                const AnrConfig* config) {
    if (!config || !mem) return NULL;
    /* Reject unaligned memory before writing. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    /* Validate before deriving dimensions. */
    if (!anr_validate_config(config)) return NULL;
    size_t need = anr_get_mem_size(config);
    if (need == 0 || mem_size < need) return NULL;
    int nf = config->fft_size / 2 + 1;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;
    size_t arr = ALIGN16((size_t)nf * sizeof(float));

    AnrDenoiser* self = (AnrDenoiser*)cursor;
    cursor += ALIGN16(sizeof(AnrDenoiser));

    self->power             = (float*)cursor; cursor += arr;
    self->noise_aug         = (float*)cursor; cursor += arr;
    self->spp               = (float*)cursor; cursor += arr;
    self->xi                = (float*)cursor; cursor += arr;
    self->gamma             = (float*)cursor; cursor += arr;
    self->gain              = (float*)cursor; cursor += arr;
#ifdef USE_SHARED_XI_RATIO
    self->v                 = (float*)cursor; cursor += arr;
#endif
    self->gain_v_scratch        = (float*)cursor; cursor += arr;
    self->gain_xi_ratio_scratch = (float*)cursor; cursor += arr;
    self->gain_prev         = (float*)cursor; cursor += arr;
    self->enhanced_psd_prev = (float*)cursor; cursor += arr;
    self->init_power_sum    = (float*)cursor; cursor += arr;
    self->log_gain_prev     = (float*)cursor; cursor += arr;

    /* Sub-modules carved from the same block (no malloc). */
    size_t mcra_sz = mcra_get_mem_size(nf, config);
    self->noise_est = mcra_init(cursor, mcra_sz, nf, config);
    cursor += mcra_sz;

    size_t spp_sz = spp_get_mem_size(nf);
    self->spp_est = spp_init(cursor, spp_sz, nf, config);
    cursor += spp_sz;

    if (!self->noise_est || !self->spp_est) return NULL;

    /* Size query and carve must end at the same byte offset. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    _setup(self, config);
    self->is_static = true;
    return self;
}

/* Heap allocation. */

AnrDenoiser* anr_create(const AnrConfig* config) {
    /* Validate before deriving dimensions. */
    if (!anr_validate_config(config)) return NULL;
    int nf = config->fft_size / 2 + 1;

    AnrDenoiser* self =
        (AnrDenoiser*)calloc(1, sizeof(AnrDenoiser));
    if (!self) return NULL;

    self->power             = (float*)calloc(nf, sizeof(float));
    self->noise_aug         = (float*)calloc(nf, sizeof(float));
    self->noise_est         = mcra_create(nf, config);
    self->spp_est           = spp_create(nf, config);
    self->spp               = (float*)calloc(nf, sizeof(float));
    self->xi                = (float*)calloc(nf, sizeof(float));
    self->gamma             = (float*)calloc(nf, sizeof(float));
    self->gain              = (float*)calloc(nf, sizeof(float));
#ifdef USE_SHARED_XI_RATIO
    self->v                 = (float*)calloc(nf, sizeof(float));
#endif
    self->gain_v_scratch        = (float*)calloc(nf, sizeof(float));
    self->gain_xi_ratio_scratch = (float*)calloc(nf, sizeof(float));
    self->gain_prev         = (float*)calloc(nf, sizeof(float));
    self->enhanced_psd_prev = (float*)calloc(nf, sizeof(float));
    self->init_power_sum    = (float*)calloc(nf, sizeof(float));
    self->log_gain_prev     = (float*)calloc(nf, sizeof(float));

    if (!self->power || !self->noise_aug || !self->noise_est || !self->spp_est ||
        !self->spp || !self->xi || !self->gamma || !self->gain ||
        !self->gain_v_scratch || !self->gain_xi_ratio_scratch ||
        !self->gain_prev || !self->enhanced_psd_prev ||
        !self->init_power_sum || !self->log_gain_prev
#ifdef USE_SHARED_XI_RATIO
        || !self->v
#endif
        ) {
        anr_destroy(self);
        return NULL;
    }

    _setup(self, config);
    self->is_static = false;
    return self;
}

void anr_destroy(AnrDenoiser* self) {
    if (!self) return;
    if (self->is_static) return;  /* caller owns the block; nothing to free */

    free(self->power);
    free(self->noise_aug);
    if (self->noise_est) mcra_destroy(self->noise_est);
    if (self->spp_est)   spp_destroy(self->spp_est);
    free(self->spp);
    free(self->xi);
    free(self->gamma);
    free(self->gain);
#ifdef USE_SHARED_XI_RATIO
    free(self->v);
#endif
    free(self->gain_v_scratch);
    free(self->gain_xi_ratio_scratch);
    free(self->gain_prev);
    free(self->enhanced_psd_prev);
    free(self->init_power_sum);
    free(self->log_gain_prev);
    free(self);
}

/* Spectrum processing. */

/* Digital silence: every bin power is exactly zero. Such a frame carries no noise statistics, so
 * it neither counts toward initialization nor advances the tracker (a floor seeded from zeros
 * would leave a returning stationary tone unsuppressed).
 */
static bool frame_is_silent(const float* power, int n_freqs) {
    for (int k = 0; k < n_freqs; k++)
        if (power[k] != 0.0f) return false;
    return true;
}

int anr_process(AnrDenoiser* self,
                     const Complex*   spectrum_in,
                     Complex*         spectrum_out) {
    if (!self || !spectrum_in || !spectrum_out) return -1;

    int nf = self->n_freqs;

    /* 1. Power from input spectrum */
    fft_power(spectrum_in, self->power, nf);
    const bool silent = frame_is_silent(self->power, nf);

    /* 2. Noise init or normal processing */
    if (!self->is_initialized) {
        if (!silent) {
            for (int k = 0; k < nf; k++)
                self->init_power_sum[k] += self->power[k];

            mcra_accumulate_init_power(self->noise_est, self->power,
                                       self->init_frame_count);
            self->init_frame_count++;

            if (self->init_frame_count >= self->config.num_init_frames) {
                mcra_init_noise(self->noise_est, self->init_power_sum,
                                self->init_frame_count);
                self->is_initialized = true;
            }
        }

        /* Initialization bypass: gain = 1 and next-hop enhanced power = input power. */
        for (int k = 0; k < nf; k++) {
            self->gain[k]              = 1.0f;
            self->gain_prev[k]         = 1.0f;
            self->enhanced_psd_prev[k] = self->power[k];
        }
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);
        run_frame_gain_stage(self, prepare_noise_for_spp(self, noise_psd, NULL), !silent);
    }

    /* Apply gain once for exact in-place or disjoint spectra; partial overlap is unsupported.
     * Multiply operands and rounding match fft_apply_gain().
     */
    if (spectrum_out != spectrum_in) {
        for (int k = 0; k < nf; k++) {
            float g = self->gain[k];
            spectrum_out[k].r = spectrum_in[k].r * g;
            spectrum_out[k].i = spectrum_in[k].i * g;
        }
    } else {
        fft_apply_gain(spectrum_out, self->gain, nf);
    }

    return 0;
}

int anr_process_gain(AnrDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out) {
    if (!self || !spectrum_in) return -1;
    int nf = self->n_freqs;

    /* 1. Power from input spectrum */
    fft_power(spectrum_in, self->power, nf);
    const bool silent = frame_is_silent(self->power, nf);

    /* Noise initialization is independent of extra noise. */
    if (!self->is_initialized) {
        if (!silent) {
            for (int k = 0; k < nf; k++)
                self->init_power_sum[k] += self->power[k];

            mcra_accumulate_init_power(self->noise_est, self->power,
                                       self->init_frame_count);
            self->init_frame_count++;

            if (self->init_frame_count >= self->config.num_init_frames) {
                mcra_init_noise(self->noise_est, self->init_power_sum,
                                self->init_frame_count);
                self->is_initialized = true;
            }
        }

        /* Initialization bypass and DD state update. */
        for (int k = 0; k < nf; k++) {
            self->gain[k]              = 1.0f;
            self->gain_prev[k]         = 1.0f;
            self->enhanced_psd_prev[k] = self->power[k];
        }
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);

        /* Extra PSD augments SPP/SNR noise; MCRA observes raw power, with SPP-gated updates. */
        run_frame_gain_stage(self,
                             prepare_noise_for_spp(self, noise_psd, extra_noise_psd),
                             !silent);
    }

    /* Optional gain copy; borrowed state is available through anr_get_gain(). */
    if (gain_out) memcpy(gain_out, self->gain, nf * sizeof(float));

    return 0;
}

/* Runtime reconfiguration and reset. */

int anr_reconfigure(AnrDenoiser* self, const AnrConfig* target) {
    bool reset_cross_band_prior;
    bool reset_shared_frame_state;
    if (!self || !target) return -1;
    /* Validate all target tunables before writing. */
    if (!anr_validate_config(target)) return -1;
    /* Grid and pool dimensions cannot change; reject before any state write. */
    if (target->sample_rate != self->config.sample_rate ||
        target->frame_size  != self->config.frame_size  ||
        target->hop_size    != self->config.hop_size    ||
        target->fft_size    != self->config.fft_size    ||
        target->L           != self->config.L           ||
        target->num_init_frames != self->config.num_init_frames) {
        return -1;
    }

    reset_cross_band_prior =
        target->cross_band_speech_prior != self->config.cross_band_speech_prior ||
        target->cross_band_speech_prior_max_q !=
            self->config.cross_band_speech_prior_max_q ||
        target->cross_band_speech_prior_alpha !=
            self->config.cross_band_speech_prior_alpha;
    reset_shared_frame_state =
        target->speech_aware_noise_tracking !=
            self->config.speech_aware_noise_tracking ||
        target->noise_gate_xi_db != self->config.noise_gate_xi_db ||
        target->noise_gate_lf_hz != self->config.noise_gate_lf_hz ||
        target->noise_gate_frame_frac != self->config.noise_gate_frame_frac ||
        target->makeup_gain != self->config.makeup_gain ||
        target->makeup_prior_xi_db != self->config.makeup_prior_xi_db;

    /* Preserve DSP histories. Reset only the optional cross-band EMA when its own prior
     * configuration changes.
     */
    apply_gain_config_scalars(self, target);
    mcra_apply_config_scalars(self->noise_est, target);
    spp_apply_config_scalars(self->spp_est, target);
    self->config = *target;
    update_noise_gate_geometry(self, target);
    if (reset_cross_band_prior) {
        self->cross_band_prior_state = 0.0f;
        self->cross_band_prior_lift = 0.0f;
        self->speech_protect_frame_active = false;
    }
    if (reset_shared_frame_state) {
        self->slow_lf_rise = false;
        self->makeup_prior_state = 0.5f;
    }
    return 0;
}

int anr_set_mode(AnrDenoiser* self, AnrMode mode) {
    AnrConfig target;
    if (!self) return -1;
    if (!anr_nr_mode_is_valid(mode)) return -1;
    target = anr_config_for_mode_grid(self->config.sample_rate,
                                           self->config.fft_size, mode);
    return anr_reconfigure(self, &target);
}

void anr_reset(AnrDenoiser* self) {
    if (!self) return;

    mcra_reset(self->noise_est);
    spp_reset(self->spp_est);
    reset_gain_state(self);

    memset(self->power,             0, self->n_freqs * sizeof(float));
    memset(self->gain_prev,         0, self->n_freqs * sizeof(float));
    memset(self->enhanced_psd_prev, 0, self->n_freqs * sizeof(float));
    memset(self->init_power_sum,    0, self->n_freqs * sizeof(float));
    self->init_frame_count = 0;
    self->is_initialized   = false;
    reset_frame_evidence_state(self);
}

/* Queries. */

int anr_get_hop_size(const AnrDenoiser* self) {
    return self ? self->config.hop_size : 0;
}

int anr_get_frame_size(const AnrDenoiser* self) {
    return self ? self->config.frame_size : 0;
}

int anr_get_n_freqs(const AnrDenoiser* self) {
    return self ? self->n_freqs : 0;
}

int anr_get_latency(const AnrDenoiser* self) {
    /* Frequency-domain core has no added latency. */
    (void)self;
    return 0;
}

bool anr_is_initialized(const AnrDenoiser* self) {
    return self ? self->is_initialized : false;
}

const float* anr_get_spp(const AnrDenoiser* self, int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->spp;
}

const float* anr_get_noise_psd(const AnrDenoiser* self, int* n_freqs) {
    if (!self || !self->noise_est) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return mcra_get_noise_psd(self->noise_est);
}

float anr_get_speech_protect_frame_threshold(const AnrDenoiser* self) {
    return self ? self->speech_protect_frame_threshold : 0.0f;
}

const float* anr_get_gain(const AnrDenoiser* self, int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->gain;
}

/* Read-only on-demand reductions over last-frame state. Standard log math; no per-hop cost
 * when unused.
 */
void anr_debug_status(const AnrDenoiser* self, AnrDebugStatus* out) {
    if (!out) return;
    memset(out, 0, sizeof(*out));
    if (!self) return;

    out->initialized = self->is_initialized ? 1 : 0;

    const int n = self->n_freqs;
    const float* gain = self->gain;
    const float* spp  = self->spp;
    const float* noise_psd = self->noise_est ? mcra_get_noise_psd(self->noise_est) : NULL;
    if (n <= 0 || !gain) return;

    float gain_sum = 0.0f, spp_sum = 0.0f, noise_sum = 0.0f;
    float gain_min = gain[0];
    for (int k = 0; k < n; ++k) {
        float g = gain[k];
        gain_sum += g;
        if (g < gain_min) gain_min = g;
        if (spp)       spp_sum   += spp[k];
        if (noise_psd) noise_sum += noise_psd[k];
    }

    float mean_gain = gain_sum / n;
    out->mean_gain_db   = 20.0f * log10f(mean_gain + 1e-10f);
    out->min_gain_db    = 20.0f * log10f(gain_min + 1e-10f);
    out->mean_spp       = spp ? (spp_sum / n) : 0.0f;
    out->noise_floor_db = 10.0f * log10f((noise_sum / n) + 1e-10f);
}
