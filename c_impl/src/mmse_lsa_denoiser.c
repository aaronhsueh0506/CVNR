/**
 * mmse_lsa_denoiser.c - MMSE-LSA Denoiser (Frequency-Domain I/O)
 *
 * Implements the same public API as the time-domain variant but operates
 * entirely in the frequency domain. Caller owns FFT/IFFT/windowing/OLA.
 *
 * Internal pipeline per frame:
 *   spectrum_in -> power -> MCRA noise est -> SPP -> MMSE-LSA gain
 *   -> apply gain to spectrum -> spectrum_out
 */

#include "mmse_lsa_denoiser.h"
#include "mmse_lsa_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"
#include "fft_wrapper.h"   /* Complex, fft_power, fft_apply_gain, ALIGN16 */
#include "fast_math.h"
#include "simd_kernels.h"  /* sk_exp1_approx_f32 (kernel 27), sk_fast_exp_f32
                             * (kernel 23), sk_fast_log_f32 (kernel 25) --
                             * provably scalar-reference-bit-exact by
                             * construction (verbatim op-sequence match --
                             * see that header's top-of-file contract), gated
                             * by this TU's mandatory -ffp-contract=off same
                             * as every other caller. */

#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "mmse_lsa_internal.h"

/* -------------------------------------------------------------------------
 * Internal structure
 * ---------------------------------------------------------------------- */

struct MmseLsaDenoiser {
    MmseLsaConfig config;

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

    /* calculate_gain() per-call scratch [n_freqs] -- transient (fully
     * overwritten every call, nothing persisted across hops), pre-allocated
     * here so the exp1_approx/fast_exp/fast_log calls can batch over the
     * whole bin range via sk_exp1_approx_f32/sk_fast_exp_f32/sk_fast_log_f32
     * instead of per-bin scalar calls, with zero malloc on the hot path
     * either way. Distinct from `v` above (that one is SPP's shared
     * v=ξ/(1+ξ)·γ output, reused here as an INPUT when USE_SHARED_XI_RATIO
     * is on; gain_v_scratch is calculate_gain()'s own post-clamp copy).
     *
     * gain_v_scratch does quadruple duty across passes 2-6: once pass 2's
     * sk_exp1_approx_f32 consumes the
     * clamped v[k] this array holds, nothing later in the function ever
     * reads that ORIGINAL value again (confirmed by inspection of the whole
     * function below), so exp1_approx's own output, pass 4's fast_exp
     * output, and pass 6's fast_log output are all written back into this
     * SAME buffer in place (sk_<name>(gain_v_scratch, gain_v_scratch,
     * n_freqs)) instead of three separate [n_freqs] scratch arrays -- safe
     * because sk_exp1_approx_f32/sk_fast_exp_f32/sk_fast_log_f32 each fully
     * load a 4-lane block into registers before storing that same block
     * back (no cross-lane/cross-block dependency), a contract now recorded
     * next to each kernel in simd_kernels.h (mirrors sk_capply_gain_f32's
     * pre-existing out==z contract) and exercised by simd_selftest.c's
     * test_exp_log_family_inplace(). gain_xi_ratio_scratch MUST stay a
     * separate buffer: it is written at pass 1, consumed as xi_ratio at
     * pass 5, then overwritten with the speech-present gain G_H1 and read
     * again by the DD-state update in pass 7. Passes 2-4 overwrite
     * gain_v_scratch in between. */
    float* gain_v_scratch;         /* v[k] -> exp1_approx(v[k]) -> 0.5x -> fast_exp(...) -> (+1e-10f) -> fast_log(...), all in place */
    float* gain_xi_ratio_scratch;  /* xi_ratio[k] -> G_H1[k], consumed again at pass 7 */

    float* gain_prev;
    float* enhanced_psd_prev;

    /* Frame-level speech evidence: scalar state only, no additional
     * spectral array. */
    float  cross_band_prior_state;
    float  cross_band_prior_lift;
    int    speech_bin_start;
    int    speech_bin_end;
    float  speech_band_inv_count;
    int    noise_gate_lf_bin;
    float  noise_gate_xi;
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

    /* Stationary-mode Wiener gain lower-bound (default off → full behaviour). */
    bool   stationary_floor;
    float  stationary_floor_exponent;   /* p */
    float  stationary_floor_beta;       /* β */

    bool   is_static;   /* 1 == placed via mmse_lsa_init() (caller-owned memory);
                         * 0 == heap instance from mmse_lsa_create() (owns its mallocs) */
};

/* -------------------------------------------------------------------------
 * Gain calculation
 * ---------------------------------------------------------------------- */

/* Parameters ONLY. Split out from the state clearing below so a runtime
 * reconfiguration can swap the gain coefficients without discarding the
 * smoothing history they smooth -- a strength change is not a restart. */
static void apply_gain_config_scalars(MmseLsaDenoiser* self,
                                       const MmseLsaConfig* config) {
    /* Amplitude-dB (/20): the gain is applied directly to the magnitude spectrum
     * (fft_apply_gain multiplies each bin, no sqrt), so g_min is an AMPLITUDE floor.
     * g_min_db=-15 → 10^(-15/20)=0.178 (a true -15 dB amplitude floor). Mirrors Python
     * mmse_lsa.py. (SNR/power dB — xi_min, delta, scene_change — correctly stay /10.) */
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

    self->stationary_floor          = config->stationary_floor;
    self->stationary_floor_exponent = config->stationary_floor_exponent;
    self->stationary_floor_beta     = config->stationary_floor_beta;
}

/* First bin at or above hz, and the bin count covering [0, hz] inclusive. */
static int hz_to_bin_ceil(float hz, const MmseLsaConfig* config) {
    return (int)ceilf(hz * (float)config->fft_size /
                      (float)config->sample_rate);
}

static int hz_to_bin_floor_inclusive(float hz, const MmseLsaConfig* config) {
    return (int)floorf(hz * (float)config->fft_size /
                       (float)config->sample_rate) + 1;
}

static void update_noise_gate_geometry(MmseLsaDenoiser* self,
                                       const MmseLsaConfig* config) {
    self->noise_gate_lf_bin = hz_to_bin_ceil(config->noise_gate_lf_hz, config);
    if (self->noise_gate_lf_bin < 1) self->noise_gate_lf_bin = 1;
    if (self->noise_gate_lf_bin > self->n_freqs)
        self->noise_gate_lf_bin = self->n_freqs;
}

static void reset_gain_state(MmseLsaDenoiser* self) {
    if (self->log_gain_prev)
        memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    self->gain_initialized = false;
}

static void reset_frame_evidence_state(MmseLsaDenoiser* self) {
    self->cross_band_prior_state = 0.0f;
    self->cross_band_prior_lift = 0.0f;
    self->speech_protect_frame_active = false;
    self->slow_lf_rise = false;
    self->makeup_prior_state = 0.5f;
}

/* First-order logit lift of a posterior by the frame prior (research switch). */
static inline float lift_spp(float spp_k, float lift) {
    return spp_k + lift * spp_k * (1.0f - spp_k);
}

/* DD state feeding the next frame's spp_estimate: the emitted gain, its log
 * for the attack/decay smoothing, and the enhanced PSD built from dd_gain
 * (the emitted gain, or G_H1 under dd_from_gmmse). */
static inline void store_gain_state(MmseLsaDenoiser* self, int k, float gain,
                                    float log_gain, float dd_gain) {
    self->log_gain_prev[k]     = log_gain;
    self->gain_prev[k]         = gain;
    self->enhanced_psd_prev[k] = dd_gain * dd_gain * self->power[k];
}

/* Reduce fixed-prior evidence to shared frame decisions. The product path
 * uses the SPP mean for the LF gain floor and the xi fraction for the LF
 * tracker guard. Optional research q lifting/make-up reuse the same scan.
 * With every consumer off the scan is skipped and the frame flags keep
 * their reset values, which those consumers then never read. */
static void update_frame_speech_evidence(MmseLsaDenoiser* self) {
    const MmseLsaConfig* cfg = &self->config;
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
        evidence >= cfg->speech_protect_frame_threshold;
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
    /* First-order logit lift about balanced q=0.5. The experiment helper
     * caps the lift at +0.04, keeping this close to exact Bayesian
     * re-prioring without another divide per bin. */
    self->cross_band_prior_lift = 4.0f * (prior - base_q);
}

/* Apply the broadband scalar after calculate_gain() has saved the unscaled
 * OM-LSA/DD state. The returned/applied gain includes this scalar, while the
 * next frame's DD recursion does not feed it back. The production config
 * disables this experiment, so its extra spectrum passes stay off the hot
 * path. */
static void apply_frame_makeup(MmseLsaDenoiser* self) {
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

/* The product speech floor affects only a handful of bins below 300 Hz.
 * Keeping it out of the full gain loop avoids a per-bin condition over the
 * whole spectrum.  Repair the DD state only for bins whose final gain moves. */
static void apply_low_band_speech_floor(MmseLsaDenoiser* self,
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

static void update_noise_estimator(MmseLsaDenoiser* self) {
    mcra_update_ex(self->noise_est, self->power, self->spp,
                   self->slow_lf_rise, self->noise_gate_lf_bin,
                   self->config.alpha_d_speech);
}

static const float* prepare_noise_for_spp(MmseLsaDenoiser* self,
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

static void calculate_gain(MmseLsaDenoiser* self,
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
    /* Stationary-mode Wiener lower-bound (default off): gain >= (ξ/(β+ξ))^p. */
    bool  stat_floor   = self->stationary_floor;
    float stat_p       = self->stationary_floor_exponent;
    float stat_beta    = self->stationary_floor_beta;
    bool  stat_p2      = (stat_p == 2.0f);  /* preset p; skip powf on the common path */

    float* v_scratch        = self->gain_v_scratch;
    float* xi_ratio_scratch = self->gain_xi_ratio_scratch;

    /* Pass 1 (scalar): per-bin v/xi_ratio -- the USE_SHARED_XI_RATIO block
     * below (and its #else fallback) is byte-for-byte untouched from the
     * pre-split code: xi_ratio/v are treated as opaque, already-correct
     * scalar inputs produced by logic this split must not alter. The domain
     * clamp that follows it is likewise unmodified, just scratched afterward
     * instead of feeding straight into a per-bin exp1_approx() call. */
    for (int k = 0; k < n_freqs; k++) {
        float xi_k    = xi[k];
        float gamma_k = gamma[k];

        float v, xi_ratio;
#ifdef USE_SHARED_XI_RATIO
        if (v_in != NULL) {
            v        = v_in[k];
            xi_ratio = v / (gamma_k + 1e-10f);
        } else {
            xi_ratio = xi_k / (1.0f + xi_k);
            v        = xi_ratio * gamma_k;
        }
#else
        (void)v_in;
        xi_ratio = xi_k / (1.0f + xi_k);
        v        = xi_ratio * gamma_k;
#endif

        if (v < 1e-10f) v = 1e-10f;
        if (v > 700.0f) v = 700.0f;

        v_scratch[k]        = v;
        xi_ratio_scratch[k] = xi_ratio;
    }

    /* Pass 2 (vectorized, in place): exp1_v[k] = exp1_approx(v[k]) via
     * sk_exp1_approx_f32 (simd_kernels.h kernel 27) -- bit-exact by
     * construction (see that header's contract). Written back into
     * gain_v_scratch itself: nothing downstream reads the original clamped
     * v[k] again (see the struct field comment above), and
     * sk_exp1_approx_f32 documents out==x as safe (per-4-lane-block
     * load-then-store, no cross-block state). */
    sk_exp1_approx_f32(v_scratch, v_scratch, n_freqs);

    /* Pass 3 (scalar, branch-free): scale in place to 0.5f*exp1_v[k], the
     * exact argument the original `fast_exp(0.5f * exp1_v)` call took. */
    for (int k = 0; k < n_freqs; k++) {
        v_scratch[k] = 0.5f * v_scratch[k];
    }

    /* Pass 4 (vectorized, in place): fast_exp(0.5f*exp1_v[k]) via
     * sk_fast_exp_f32 (simd_kernels.h kernel 23) -- bit-exact by
     * construction, out==x safe per that kernel's documented contract.
     * gain_v_scratch now holds fast_exp's result. */
    sk_fast_exp_f32(v_scratch, v_scratch, n_freqs);

    /* Pass 5 (scalar, branch-free): gain_mmse[k] = xi_ratio*fast_exp(...),
     * clamped to [g_min,1.0] -- unmodified formula/clamp, written in place
     * (+1e-10f folded in here too: the exact argument fast_log() takes
     * next). The scratch slot is then repurposed to retain this G_H1 value
     * for the pass-7 DD recursion. */
    for (int k = 0; k < n_freqs; k++) {
        float gain_mmse = xi_ratio_scratch[k] * v_scratch[k];
        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f)  gain_mmse = 1.0f;
        xi_ratio_scratch[k] = gain_mmse;
        v_scratch[k] = gain_mmse + 1e-10f;
    }

    /* Pass 6 (vectorized, in place): log_gain_mmse[k] =
     * fast_log(gain_mmse[k]+1e-10f) via sk_fast_log_f32 (simd_kernels.h
     * kernel 25) -- bit-exact by construction, out==x safe per that
     * kernel's documented contract. gain_v_scratch now holds
     * log_gain_mmse. */
    sk_fast_log_f32(v_scratch, v_scratch, n_freqs);

    /* Pass 7 (scalar): attack/decay smoothing (reads self->log_gain_prev[k],
     * PREVIOUS hop's state for this same bin k -- not a same-call cross-bin
     * dependency, since this same loop only WRITES log_gain_prev[k] for bin
     * k after this read, same as before the split), the
     * USE_FAST_GAIN_SMOOTHING/USE_SINGLE_CLAMP clamp variants, the
     * stationary-floor branch, and the DD-state fold -- all unmodified from
     * the pre-split code, just reading log_gain_mmse from the vectorized
     * scratch instead of a same-iteration local. */
    for (int k = 0; k < n_freqs; k++) {
        float xi_k    = xi[k];
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
        /* Stationary Wiener lower-bound: gain = max(gain, (ξ/(β+ξ))^p), then re-derive
         * the saved log gain from the floored value (Python mmse_lsa.py:199-206). */
        if (stat_floor) {
            float ratio   = xi_k / (stat_beta + xi_k);
            float g_floor = stat_p2 ? ratio * ratio : powf(ratio, stat_p);
            if (g_floor > gain) { gain = g_floor; log_gain_save = fast_log(gain + 1e-10f); }
        }
        gain_out[k] = gain;
#else
        float gain = fast_exp(log_gain);
#ifndef USE_SINGLE_CLAMP
        if (gain < g_min) gain = g_min;
        if (gain > 1.0f)  gain = 1.0f;
#endif
        if (stat_floor) {
            float ratio   = xi_k / (stat_beta + xi_k);
            float g_floor = stat_p2 ? ratio * ratio : powf(ratio, stat_p);
            if (g_floor > gain) gain = g_floor;
        }
        gain_out[k] = gain;
        float log_gain_save = fast_log(gain + 1e-10f);
#endif

        /* DD-state fold: gain_prev/enhanced_psd_prev feed next frame's
         * spp_estimate_ex DD term. Folded in from the separate post-loop
         * pass that used to run in mmse_lsa_process/mmse_lsa_process_gain —
         * self->power[k] is already final here (fft_power ran before this
         * call and is untouched since) and `gain` above is the exact value
         * just written to gain_out[k], so this is bit-identical, just fused
         * into this loop instead of a second one over the same range. */
        store_gain_state(self, k, gain, log_gain_save,
                         dd_from_gmmse ? xi_ratio_scratch[k] : gain);
    }

    apply_low_band_speech_floor(self, gain_out);

    self->gain_initialized = true;
}

/* Everything between the noise floor handed to the SPP estimator and this
 * frame's gain, shared by mmse_lsa_process and mmse_lsa_process_gain:
 * SPP/DD, the frame speech evidence, the OM-LSA gain, the optional make-up,
 * then the tracker update from the clean power and SPP (the augmented floor
 * never reaches the tracker). The tracker update and calculate_gain touch
 * disjoint state, so it runs last on every configuration. */
static void run_frame_gain_stage(MmseLsaDenoiser* self,
                                 const float* noise_for_spp) {
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
    update_noise_estimator(self);
}

/* -------------------------------------------------------------------------
 * Shared post-alloc setup
 * ---------------------------------------------------------------------- */

static void _setup(MmseLsaDenoiser* self, const MmseLsaConfig* config) {
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

/* -------------------------------------------------------------------------
 * Create / Destroy
 * ---------------------------------------------------------------------- */

/* ---- Static-memory (no malloc) variant ------------------------------------ *
 * The whole instance — struct, all spectral state arrays, and the MCRA + SPP
 * sub-modules — is bump-allocated from a single caller-provided block. */

size_t mmse_lsa_get_mem_size(const MmseLsaConfig* config) {
    /* F05: reject an invalid/adversarial config up front (bad sample_rate,
     * negative or huge fft_size/L/num_init_frames, inconsistent framing)
     * before any size arithmetic runs on its fields. */
    if (!mmse_lsa_validate_config(config)) return 0;
    int nf = config->fft_size / 2 + 1;

    size_t total = ALIGN16(sizeof(MmseLsaDenoiser));
    /* Checked arithmetic (F05): ck_field_size saturates to SIZE_MAX on
     * overflow instead of silently wrapping; MEM_SIZE_INVALID() below turns
     * that into a `return 0` failure rather than a small wrapped byte count
     * that mmse_lsa_init() would then carve past. Numerically identical to
     * the old `total += ALIGN16(nf*sizeof(float))` chain for any config that
     * passes validate_config() above. */
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

MmseLsaDenoiser* mmse_lsa_init(void* mem, size_t mem_size,
                                const MmseLsaConfig* config) {
    if (!config || !mem) return NULL;
    /* F07: reject a misaligned pool base before any write into it. */
    if (!MEM_IS_ALIGNED16(mem)) return NULL;
    /* F05: reject an invalid config (see mmse_lsa_get_mem_size) before
     * deriving nf from it. */
    if (!mmse_lsa_validate_config(config)) return NULL;
    size_t need = mmse_lsa_get_mem_size(config);
    if (need == 0 || mem_size < need) return NULL;
    int nf = config->fft_size / 2 + 1;

    memset(mem, 0, need);   /* calloc-equivalent */
    uint8_t* cursor = (uint8_t*)mem;
    size_t arr = ALIGN16((size_t)nf * sizeof(float));

    MmseLsaDenoiser* self = (MmseLsaDenoiser*)cursor;
    cursor += ALIGN16(sizeof(MmseLsaDenoiser));

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

    /* Lockstep guard: mmse_lsa_get_mem_size() and the carve sequence above
     * (own arrays + the two sub-module carves) are independently-maintained
     * additions that must total identically -- a field added/removed from
     * one but not the other would otherwise only surface as a silent
     * over/under-carve, not a build or test failure. cursor is expected to
     * land exactly at mem + need. */
    if ((size_t)(cursor - (uint8_t*)mem) != need) return NULL;

    _setup(self, config);
    self->is_static = true;
    return self;
}

/* ---- Heap (malloc) version ----------------------------------------------- */

MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config) {
    /* F05: reject an invalid/adversarial config before deriving nf from it
     * (see mmse_lsa_get_mem_size for the full rationale). */
    if (!mmse_lsa_validate_config(config)) return NULL;
    int nf = config->fft_size / 2 + 1;

    MmseLsaDenoiser* self =
        (MmseLsaDenoiser*)calloc(1, sizeof(MmseLsaDenoiser));
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
        mmse_lsa_destroy(self);
        return NULL;
    }

    _setup(self, config);
    self->is_static = false;
    return self;
}

void mmse_lsa_destroy(MmseLsaDenoiser* self) {
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

/* -------------------------------------------------------------------------
 * Core processing
 * ---------------------------------------------------------------------- */

int mmse_lsa_process(MmseLsaDenoiser* self,
                     const Complex*   spectrum_in,
                     Complex*         spectrum_out) {
    if (!self || !spectrum_in || !spectrum_out) return -1;

    int nf = self->n_freqs;

    /* 1. Power from input spectrum */
    fft_power(spectrum_in, self->power, nf);

    /* 2. Noise init or normal processing */
    if (!self->is_initialized) {
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

        /* Pass through during init. DD state folded in here (g=1.0, so
         * gain_prev=1.0 and enhanced_psd_prev=1*1*power=power exactly —
         * same values the old post-loop pass wrote for this branch, just
         * fused into this loop instead of a second one over the same range). */
        for (int k = 0; k < nf; k++) {
            self->gain[k]              = 1.0f;
            self->gain_prev[k]         = 1.0f;
            self->enhanced_psd_prev[k] = self->power[k];
        }
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);
        run_frame_gain_stage(self, prepare_noise_for_spp(self, noise_psd, NULL));
    }

    /* 4+5. Copy-with-gain-applied (out-of-place) or apply gain in-place.
     * Fused: avoids writing spectrum_out twice (memcpy then *=). Same
     * per-bin arithmetic as fft_apply_gain (audio_common/src/fft_wrapper.c:
     * spectrum[k].{r,i} *= gain[k]) — out[k] = in[k]*gain[k] is bit-identical
     * to memcpy(out,in) followed by fft_apply_gain(out,gain) since the
     * multiply operands and rounding are the same either way. */
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

int mmse_lsa_process_gain(MmseLsaDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out) {
    if (!self || !spectrum_in) return -1;

    int nf = self->n_freqs;

    /* 1. Power from input spectrum */
    fft_power(spectrum_in, self->power, nf);

    /* 2. Noise init or normal processing (identical to mmse_lsa_process; the
     *    MCRA tracker and the init pass-through are unaffected by extra noise). */
    if (!self->is_initialized) {
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

        /* Pass through during init; DD state folded in (see mmse_lsa_process). */
        for (int k = 0; k < nf; k++) {
            self->gain[k]              = 1.0f;
            self->gain_prev[k]         = 1.0f;
            self->enhanced_psd_prev[k] = self->power[k];
        }
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);

        /* Unified gain: fold R² into the noise floor for the SPP / a-priori-SNR
         * estimate (ξ = S²/(N²+R²)) WITHOUT polluting the MCRA tracker — exactly
         * the Python denoise_spectrum copy `noise_psd = noise_psd + extra[i]`.
         * With extra==NULL this is the plain noise. */
        run_frame_gain_stage(self,
                             prepare_noise_for_spp(self, noise_psd, extra_noise_psd));
    }

    /* Return the gain WITHOUT applying it (caller combines with res_gain).
     * gain_out is optional: a caller that only needs the gain transiently
     * can read it via mmse_lsa_get_gain() instead of paying for this copy. */
    if (gain_out) memcpy(gain_out, self->gain, nf * sizeof(float));

    return 0;
}

/* -------------------------------------------------------------------------
 * Reset
 * ---------------------------------------------------------------------- */

int mmse_lsa_reconfigure(MmseLsaDenoiser* self, const MmseLsaConfig* target) {
    bool reset_cross_band_prior;
    bool reset_shared_frame_state;
    if (!self || !target) return -1;
    /* Full validation first, exactly as the construction paths do: only
     * comparing the geometry below would let a target through whose tuning
     * scalars are outside the ranges init would have refused. */
    if (!mmse_lsa_validate_config(target)) return -1;
    /* Grid and the two pool-sizing fields must match the instance: everything
     * downstream is carved from them, and this entry point reallocates
     * nothing. Checked before any write so a refusal leaves the instance
     * bit-identical. */
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

    /* Parameters only. Deliberately NO mcra_reset / spp_reset /
     * reset_gain_state: a strength change is not a restart, and discarding the
     * tracked noise floor mid-stream would be a worse artefact than the one
     * being tuned away. The experimental cross-band EMA is reset only when
     * its own configuration changes; carrying that scalar between different
     * priors would make runtime A/B order-dependent. */
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

int mmse_lsa_set_mode(MmseLsaDenoiser* self, MmseLsaNrMode mode) {
    MmseLsaConfig target;
    if (!self) return -1;
    if (!mmse_lsa_nr_mode_is_valid(mode)) return -1;
    target = mmse_lsa_config_for_mode_grid(self->config.sample_rate,
                                           self->config.fft_size, mode);
    /* The content axis is ORTHOGONAL to strength: an instance built through
     * mmse_lsa_apply_stationary() must stay stationary after a strength
     * change, or the switch silently produces a hybrid that is neither mode. */
    if (self->config.stationary_floor) mmse_lsa_apply_stationary(&target);
    return mmse_lsa_reconfigure(self, &target);
}

void mmse_lsa_reset(MmseLsaDenoiser* self) {
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

/* -------------------------------------------------------------------------
 * Query
 * ---------------------------------------------------------------------- */

int mmse_lsa_get_hop_size(const MmseLsaDenoiser* self) {
    return self ? self->config.hop_size : 0;
}

int mmse_lsa_get_frame_size(const MmseLsaDenoiser* self) {
    return self ? self->config.frame_size : 0;
}

int mmse_lsa_get_n_freqs(const MmseLsaDenoiser* self) {
    return self ? self->n_freqs : 0;
}

int mmse_lsa_get_latency(const MmseLsaDenoiser* self) {
    /* Freq-domain NR itself has zero latency.
     * Caller's IFFT+OLA adds frame_size — caller accounts for that. */
    (void)self;
    return 0;
}

bool mmse_lsa_is_initialized(const MmseLsaDenoiser* self) {
    return self ? self->is_initialized : false;
}

const float* mmse_lsa_get_spp(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->spp;
}

const float* mmse_lsa_get_noise_psd(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self || !self->noise_est) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return mcra_get_noise_psd(self->noise_est);
}

const float* mmse_lsa_get_gain(const MmseLsaDenoiser* self, int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->gain;
}

/* Aggregate debug/status snapshot (see MmseLsaDebugStatus). Read-only:
 * reduces the existing gain/SPP/noise-PSD arrays of the last frame; runs
 * only when the caller actually invokes this, so it costs nothing on the
 * hot path otherwise. Standard math (logf/log10f), not fast_math — this is
 * a diagnostics path, not the DSP gain loop. */
void mmse_lsa_debug_status(const MmseLsaDenoiser* self, MmseLsaDebugStatus* out) {
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
