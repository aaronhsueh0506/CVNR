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

#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

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

    float* gain_prev;
    float* enhanced_psd_prev;

    int    init_frame_count;
    float* init_power_sum;
    bool   is_initialized;

    float  g_min;
    float  log_g_min;
    float  alpha_g;
    float  alpha_attack;
    float  alpha_decay;
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

static void init_gain_params(MmseLsaDenoiser* self,
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
    self->gain_initialized = false;

    self->stationary_floor          = config->stationary_floor;
    self->stationary_floor_exponent = config->stationary_floor_exponent;
    self->stationary_floor_beta     = config->stationary_floor_beta;
}

static void reset_gain_state(MmseLsaDenoiser* self) {
    if (self->log_gain_prev)
        memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    self->gain_initialized = false;
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
    /* Stationary-mode Wiener lower-bound (default off): gain >= (ξ/(β+ξ))^p. */
    bool  stat_floor   = self->stationary_floor;
    float stat_p       = self->stationary_floor_exponent;
    float stat_beta    = self->stationary_floor_beta;
    bool  stat_p2      = (stat_p == 2.0f);  /* preset p; skip powf on the common path */

    for (int k = 0; k < n_freqs; k++) {
        float xi_k    = xi[k];
        float gamma_k = gamma[k];
        float spp_k   = spp[k];

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

        float exp1_v    = exp1_approx(v);
        float gain_mmse = xi_ratio * fast_exp(0.5f * exp1_v);

        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f)  gain_mmse = 1.0f;

        float log_gain_mmse = fast_log(gain_mmse + 1e-10f);
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
        self->log_gain_prev[k] = log_gain_save;
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
        self->log_gain_prev[k] = fast_log(gain + 1e-10f);
#endif
    }

    self->gain_initialized = true;
}

/* -------------------------------------------------------------------------
 * Shared post-alloc setup
 * ---------------------------------------------------------------------- */

static void _setup(MmseLsaDenoiser* self, const MmseLsaConfig* config) {
    self->config           = *config;
    self->n_freqs          = config->fft_size / 2 + 1;
    self->init_frame_count = 0;
    self->is_initialized   = false;
    init_gain_params(self, config);
}

/* -------------------------------------------------------------------------
 * Create / Destroy
 * ---------------------------------------------------------------------- */

/* ---- Static-memory (no malloc) variant ------------------------------------ *
 * The whole instance — struct, all spectral state arrays, and the MCRA + SPP
 * sub-modules — is bump-allocated from a single caller-provided block. */

size_t mmse_lsa_get_mem_size(const MmseLsaConfig* config) {
    if (!config) return 0;
    int nf = config->fft_size / 2 + 1;
    size_t arr = ALIGN16((size_t)nf * sizeof(float));

    size_t total = ALIGN16(sizeof(MmseLsaDenoiser));
    total += arr;   /* power             */
    total += arr;   /* noise_aug         */
    total += arr;   /* spp               */
    total += arr;   /* xi                */
    total += arr;   /* gamma             */
    total += arr;   /* gain              */
#ifdef USE_SHARED_XI_RATIO
    total += arr;   /* v                 */
#endif
    total += arr;   /* gain_prev         */
    total += arr;   /* enhanced_psd_prev */
    total += arr;   /* init_power_sum    */
    total += arr;   /* log_gain_prev     */
    total += mcra_get_mem_size(nf, config);
    total += spp_get_mem_size(nf);
    return total;
}

MmseLsaDenoiser* mmse_lsa_init(void* mem, size_t mem_size,
                                const MmseLsaConfig* config) {
    if (!config || !mem) return NULL;
    if (mem_size < mmse_lsa_get_mem_size(config)) return NULL;
    int nf = config->fft_size / 2 + 1;

    memset(mem, 0, mmse_lsa_get_mem_size(config));   /* calloc-equivalent */
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

    _setup(self, config);
    self->is_static = true;
    return self;
}

/* ---- Heap (malloc) version ----------------------------------------------- */

MmseLsaDenoiser* mmse_lsa_create(const MmseLsaConfig* config) {
    if (!config) return NULL;
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
    self->gain_prev         = (float*)calloc(nf, sizeof(float));
    self->enhanced_psd_prev = (float*)calloc(nf, sizeof(float));
    self->init_power_sum    = (float*)calloc(nf, sizeof(float));
    self->log_gain_prev     = (float*)calloc(nf, sizeof(float));

    if (!self->power || !self->noise_aug || !self->noise_est || !self->spp_est ||
        !self->spp || !self->xi || !self->gamma || !self->gain ||
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

        /* Pass through during init */
        for (int k = 0; k < nf; k++)
            self->gain[k] = 1.0f;
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);

#ifdef USE_SHARED_XI_RATIO
        spp_estimate_ex(self->spp_est, self->power, noise_psd,
                        self->gain_prev, self->enhanced_psd_prev,
                        self->spp, self->xi, self->gamma, self->v);
        calculate_gain(self, self->spp, self->xi, self->gamma,
                       self->v, self->gain);
#else
        spp_estimate(self->spp_est, self->power, noise_psd,
                     self->gain_prev, self->enhanced_psd_prev,
                     self->spp, self->xi, self->gamma);
        calculate_gain(self, self->spp, self->xi, self->gamma,
                       NULL, self->gain);
#endif

        mcra_update(self->noise_est, self->power, self->spp);
    }

    /* 3. Update DD state */
    for (int k = 0; k < nf; k++) {
        float g = self->gain[k];
        self->gain_prev[k]         = g;
        self->enhanced_psd_prev[k] = g * g * self->power[k];
    }

    /* 4. Copy to output (supports in-place) */
    if (spectrum_out != spectrum_in)
        memcpy(spectrum_out, spectrum_in, nf * sizeof(Complex));

    /* 5. Apply NR gain */
    fft_apply_gain(spectrum_out, self->gain, nf);

    return 0;
}

int mmse_lsa_process_gain(MmseLsaDenoiser* self,
                          const Complex*   spectrum_in,
                          const float*     extra_noise_psd,
                          float*           gain_out) {
    if (!self || !spectrum_in || !gain_out) return -1;

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

        for (int k = 0; k < nf; k++)
            self->gain[k] = 1.0f;
    } else {
        const float* noise_psd = mcra_get_noise_psd(self->noise_est);

        /* Unified gain: fold R² into the noise floor for the SPP / a-priori-SNR
         * estimate (ξ = S²/(N²+R²)) WITHOUT polluting the MCRA tracker — exactly
         * the Python denoise_spectrum copy `noise_psd = noise_psd + extra[i]`
         * (v3_2_mmse_lsa.py:268-269). With extra==NULL this is the plain noise. */
        const float* noise_for_spp = noise_psd;
        if (extra_noise_psd) {
            for (int k = 0; k < nf; k++)
                self->noise_aug[k] = noise_psd[k] + extra_noise_psd[k];
            noise_for_spp = self->noise_aug;
        }

#ifdef USE_SHARED_XI_RATIO
        spp_estimate_ex(self->spp_est, self->power, noise_for_spp,
                        self->gain_prev, self->enhanced_psd_prev,
                        self->spp, self->xi, self->gamma, self->v);
        calculate_gain(self, self->spp, self->xi, self->gamma,
                       self->v, self->gain);
#else
        spp_estimate(self->spp_est, self->power, noise_for_spp,
                     self->gain_prev, self->enhanced_psd_prev,
                     self->spp, self->xi, self->gamma);
        calculate_gain(self, self->spp, self->xi, self->gamma,
                       NULL, self->gain);
#endif

        /* MCRA updates from the clean power + SPP only (R² excluded). */
        mcra_update(self->noise_est, self->power, self->spp);
    }

    /* 3. Update DD state (same recursion as the apply path). */
    for (int k = 0; k < nf; k++) {
        float g = self->gain[k];
        self->gain_prev[k]         = g;
        self->enhanced_psd_prev[k] = g * g * self->power[k];
    }

    /* 4. Return the gain WITHOUT applying it (caller combines with res_gain). */
    memcpy(gain_out, self->gain, nf * sizeof(float));

    return 0;
}

/* -------------------------------------------------------------------------
 * Reset
 * ---------------------------------------------------------------------- */

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

    double gain_sum = 0.0, spp_sum = 0.0, noise_sum = 0.0;
    float  gain_min = gain[0];
    for (int k = 0; k < n; ++k) {
        float g = gain[k];
        gain_sum += (double)g;
        if (g < gain_min) gain_min = g;
        if (spp)       spp_sum   += (double)spp[k];
        if (noise_psd) noise_sum += (double)noise_psd[k];
    }

    float mean_gain = (float)(gain_sum / n);
    out->mean_gain_db   = 20.0f * log10f(mean_gain + 1e-10f);
    out->min_gain_db    = 20.0f * log10f(gain_min + 1e-10f);
    out->mean_spp       = spp ? (float)(spp_sum / n) : 0.0f;
    out->noise_floor_db = 10.0f * log10f((float)(noise_sum / n) + 1e-10f);
}
