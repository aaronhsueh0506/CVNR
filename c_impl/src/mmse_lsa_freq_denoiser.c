/**
 * mmse_lsa_freq_denoiser.c - MMSE-LSA Denoiser (Frequency-Domain I/O)
 *
 * All time-domain framing, FFT, IFFT, windowing, and OLA are removed.
 * Caller passes in a Complex spectrum [n_freqs] each hop and receives back
 * the NR-enhanced spectrum.
 *
 * Internal processing: MCRA noise estimation -> SPP -> MMSE-LSA gain ->
 *   apply gain to spectrum.
 */

#include "mmse_lsa_freq_denoiser.h"
#include "mmse_lsa_types.h"
#include "mcra_noise_estimator.h"
#include "spp_estimator.h"
#include "fft_wrapper.h"
#include "fast_math.h"

#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

/* -------------------------------------------------------------------------
 * Internal structure
 * ---------------------------------------------------------------------- */

struct MmseLsaFreqDenoiser {
    MmseLsaConfig config;
    int is_static;

    int n_freqs;               /* fft_size/2 + 1 = 257 @ 512-pt FFT */

    /* Temp per-frame buffer */
    float* power;              /* |X[k]|^2  [n_freqs] */

    /* Sub-modules */
    McraNoiseEstimator* noise_est;
    SppEstimator*       spp_est;

    /* Algorithm buffers [n_freqs] */
    float* spp;
    float* xi;
    float* gamma;
    float* gain;

#ifdef USE_SHARED_XI_RATIO
    float* v;
#endif

    /* DD-smoothing state [n_freqs] */
    float* gain_prev;
    float* enhanced_psd_prev;

    /* Noise init accumulator */
    int    init_frame_count;
    float* init_power_sum;     /* [n_freqs] */
    bool   is_initialized;

    /* Gain calculation parameters */
    float  g_min;
    float  log_g_min;
    float  alpha_g;
    float  alpha_attack;
    float  alpha_decay;
    float* log_gain_prev;      /* [n_freqs] */
    bool   gain_initialized;
};

/* -------------------------------------------------------------------------
 * Gain calculation (identical logic to mmse_lsa_denoiser.c)
 * ---------------------------------------------------------------------- */

static void init_gain_params(MmseLsaFreqDenoiser* self,
                              const MmseLsaConfig* config) {
    self->g_min        = powf(10.0f, config->g_min_db / 10.0f);
    self->log_g_min    = logf(self->g_min + 1e-10f);
    self->alpha_g      = config->alpha_g;
    self->alpha_attack = config->alpha_attack;
    self->alpha_decay  = config->alpha_decay;
    self->gain_initialized = false;
}

static void reset_gain_state(MmseLsaFreqDenoiser* self) {
    if (self->log_gain_prev)
        memset(self->log_gain_prev, 0, self->n_freqs * sizeof(float));
    self->gain_initialized = false;
}

static void calculate_gain(MmseLsaFreqDenoiser* self,
                            const float* spp,
                            const float* xi,
                            const float* gamma,
                            const float* v_in,
                            float* gain_out) {
    int   n_freqs    = self->n_freqs;
    float g_min      = self->g_min;
    float log_g_min  = self->log_g_min;
    float alpha_attack = self->alpha_attack;
    float alpha_decay  = self->alpha_decay;

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

        float exp1_v     = exp1_approx(v);
        float gain_mmse  = xi_ratio * fast_exp(0.5f * exp1_v);

        if (gain_mmse < g_min) gain_mmse = g_min;
        if (gain_mmse > 1.0f)  gain_mmse = 1.0f;

        float log_gain_mmse = fast_log(gain_mmse + 1e-10f);
        float log_gain      = spp_k * log_gain_mmse +
                              (1.0f - spp_k) * log_g_min;

        if (self->gain_initialized) {
            float prev = self->log_gain_prev[k];
            float alpha = (log_gain > prev) ? alpha_attack : alpha_decay;
            log_gain = alpha * prev + (1.0f - alpha) * log_gain;
        }

#ifdef USE_FAST_GAIN_SMOOTHING
        float gain;
        float log_gain_save;
        if (log_gain < log_g_min) {
            gain = g_min;
            log_gain_save = log_g_min;
        } else if (log_gain > 0.0f) {
            gain = 1.0f;
            log_gain_save = 0.0f;
        } else {
            gain = fast_exp(log_gain);
            log_gain_save = log_gain;
        }
        gain_out[k] = gain;
        self->log_gain_prev[k] = log_gain_save;
#else
        float gain = fast_exp(log_gain);
#ifndef USE_SINGLE_CLAMP
        if (gain < g_min) gain = g_min;
        if (gain > 1.0f)  gain = 1.0f;
#endif
        gain_out[k] = gain;
        self->log_gain_prev[k] = fast_log(gain + 1e-10f);
#endif
    }

    self->gain_initialized = true;
}

/* -------------------------------------------------------------------------
 * Memory layout helper (shared by create and init)
 * ---------------------------------------------------------------------- */

size_t mmse_lsa_freq_get_mem_size(const MmseLsaConfig* config) {
    if (!config) return 0;
    int nf = config->fft_size / 2 + 1;
    size_t total = 0;

    total += ALIGN16(sizeof(MmseLsaFreqDenoiser));
    total += ALIGN16(nf * sizeof(float));          /* power */
    total += mcra_get_mem_size(nf, config);        /* noise_est */
    total += spp_get_mem_size(nf);                 /* spp_est */
    total += ALIGN16(nf * sizeof(float)) * 4;      /* spp, xi, gamma, gain */
#ifdef USE_SHARED_XI_RATIO
    total += ALIGN16(nf * sizeof(float));          /* v */
#endif
    total += ALIGN16(nf * sizeof(float)) * 2;      /* gain_prev, enhanced_psd_prev */
    total += ALIGN16(nf * sizeof(float));          /* init_power_sum */
    total += ALIGN16(nf * sizeof(float));          /* log_gain_prev */

    return total;
}

/* -------------------------------------------------------------------------
 * Shared post-alloc initialisation (sets params, zeros buffers)
 * ---------------------------------------------------------------------- */

static void _freq_setup(MmseLsaFreqDenoiser* self,
                         const MmseLsaConfig* config) {
    self->config = *config;
    self->n_freqs = config->fft_size / 2 + 1;
    self->init_frame_count = 0;
    self->is_initialized   = false;
    init_gain_params(self, config);
}

/* -------------------------------------------------------------------------
 * Heap (malloc) version
 * ---------------------------------------------------------------------- */

MmseLsaFreqDenoiser* mmse_lsa_freq_create(const MmseLsaConfig* config) {
    if (!config) return NULL;
    int nf = config->fft_size / 2 + 1;

    MmseLsaFreqDenoiser* self =
        (MmseLsaFreqDenoiser*)calloc(1, sizeof(MmseLsaFreqDenoiser));
    if (!self) return NULL;

    self->power            = (float*)calloc(nf, sizeof(float));
    self->noise_est        = mcra_create(nf, config);
    self->spp_est          = spp_create(nf, config);
    self->spp              = (float*)calloc(nf, sizeof(float));
    self->xi               = (float*)calloc(nf, sizeof(float));
    self->gamma            = (float*)calloc(nf, sizeof(float));
    self->gain             = (float*)calloc(nf, sizeof(float));
#ifdef USE_SHARED_XI_RATIO
    self->v                = (float*)calloc(nf, sizeof(float));
#endif
    self->gain_prev        = (float*)calloc(nf, sizeof(float));
    self->enhanced_psd_prev= (float*)calloc(nf, sizeof(float));
    self->init_power_sum   = (float*)calloc(nf, sizeof(float));
    self->log_gain_prev    = (float*)calloc(nf, sizeof(float));

    if (!self->power || !self->noise_est || !self->spp_est ||
        !self->spp || !self->xi || !self->gamma || !self->gain ||
        !self->gain_prev || !self->enhanced_psd_prev ||
        !self->init_power_sum || !self->log_gain_prev
#ifdef USE_SHARED_XI_RATIO
        || !self->v
#endif
        ) {
        mmse_lsa_freq_destroy(self);
        return NULL;
    }

    _freq_setup(self, config);
    return self;
}

/* -------------------------------------------------------------------------
 * Static (pre-allocated) version
 * ---------------------------------------------------------------------- */

MmseLsaFreqDenoiser* mmse_lsa_freq_init(void* mem, size_t mem_size,
                                          const MmseLsaConfig* config) {
    if (!mem || !config) return NULL;
    if (mem_size < mmse_lsa_freq_get_mem_size(config)) return NULL;

    int nf = config->fft_size / 2 + 1;
    uint8_t* ptr = (uint8_t*)mem;

    MmseLsaFreqDenoiser* self = (MmseLsaFreqDenoiser*)ptr;
    ptr += ALIGN16(sizeof(MmseLsaFreqDenoiser));
    memset(self, 0, sizeof(MmseLsaFreqDenoiser));
    self->is_static = 1;

    self->power = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    memset(self->power, 0, nf * sizeof(float));

    size_t mcra_mem = mcra_get_mem_size(nf, config);
    self->noise_est = mcra_init(ptr, mcra_mem, nf, config);
    ptr += mcra_mem;
    if (!self->noise_est) return NULL;

    size_t spp_mem = spp_get_mem_size(nf);
    self->spp_est = spp_init(ptr, spp_mem, nf, config);
    ptr += spp_mem;
    if (!self->spp_est) return NULL;

    self->spp   = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    self->xi    = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    self->gamma = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    self->gain  = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    memset(self->spp,   0, nf * sizeof(float));
    memset(self->xi,    0, nf * sizeof(float));
    memset(self->gamma, 0, nf * sizeof(float));
    memset(self->gain,  0, nf * sizeof(float));

#ifdef USE_SHARED_XI_RATIO
    self->v = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    memset(self->v, 0, nf * sizeof(float));
#endif

    self->gain_prev         = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    self->enhanced_psd_prev = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    memset(self->gain_prev,         0, nf * sizeof(float));
    memset(self->enhanced_psd_prev, 0, nf * sizeof(float));

    self->init_power_sum = (float*)ptr;  ptr += ALIGN16(nf * sizeof(float));
    memset(self->init_power_sum, 0, nf * sizeof(float));

    self->log_gain_prev = (float*)ptr;
    /* ptr += ALIGN16(nf * sizeof(float)); */  /* last field — no advance needed */
    memset(self->log_gain_prev, 0, nf * sizeof(float));

    _freq_setup(self, config);
    return self;
}

/* -------------------------------------------------------------------------
 * Destroy
 * ---------------------------------------------------------------------- */

void mmse_lsa_freq_destroy(MmseLsaFreqDenoiser* self) {
    if (!self) return;
    if (self->is_static) return;

    free(self->power);
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

int mmse_lsa_freq_process(MmseLsaFreqDenoiser* self,
                           const Complex* spectrum_in,
                           Complex* spectrum_out) {
    if (!self || !spectrum_in || !spectrum_out) return -1;

    int nf = self->n_freqs;

    /* 1. Power spectrum from input */
    fft_power(spectrum_in, self->power, nf);

    /* 2. Noise initialization or normal processing */
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

    /* 3. Update DD state for next frame */
    for (int k = 0; k < nf; k++) {
        float g = self->gain[k];
        self->gain_prev[k]         = g;
        self->enhanced_psd_prev[k] = g * g * self->power[k];
    }

    /* 4. Copy spectrum_in -> spectrum_out (handles aliased in-place calls) */
    if (spectrum_out != spectrum_in)
        memcpy(spectrum_out, spectrum_in, nf * sizeof(Complex));

    /* 5. Apply NR gain to output spectrum */
    fft_apply_gain(spectrum_out, self->gain, nf);

    return 0;
}

/* -------------------------------------------------------------------------
 * Reset
 * ---------------------------------------------------------------------- */

void mmse_lsa_freq_reset(MmseLsaFreqDenoiser* self) {
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

int mmse_lsa_freq_get_n_freqs(const MmseLsaFreqDenoiser* self) {
    return self ? self->n_freqs : 0;
}

bool mmse_lsa_freq_is_initialized(const MmseLsaFreqDenoiser* self) {
    return self ? self->is_initialized : false;
}

const float* mmse_lsa_freq_get_gain(const MmseLsaFreqDenoiser* self,
                                     int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->gain;
}

const float* mmse_lsa_freq_get_noise_psd(const MmseLsaFreqDenoiser* self,
                                          int* n_freqs) {
    if (!self || !self->noise_est) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return mcra_get_noise_psd(self->noise_est);
}

const float* mmse_lsa_freq_get_spp(const MmseLsaFreqDenoiser* self,
                                    int* n_freqs) {
    if (!self) { if (n_freqs) *n_freqs = 0; return NULL; }
    if (n_freqs) *n_freqs = self->n_freqs;
    return self->spp;
}
