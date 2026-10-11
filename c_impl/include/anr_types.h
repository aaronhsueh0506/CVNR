/* ANR configuration and strength presets. Gain estimator: Ephraim-Malah MMSE-LSA/OMLSA. */

#ifndef ANR_TYPES_H
#define ANR_TYPES_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <limits.h>
#include <math.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Suppression strength. */
typedef enum {
    ANR_MODE_MILD       = 0,   // Gentlest, preserve speech detail (g_min -20)
    ANR_MODE_MODERATE   = 1,   // Between mild and balanced (g_min -23)
    ANR_MODE_BALANCED   = 2,   // Default (g_min -25)
    ANR_MODE_AGGRESSIVE = 3    // Deepest noise removal (g_min -28)
} AnrMode;

/* Runtime mode whitelist; reject invalid enum values before preset lookup. */
static inline bool anr_nr_mode_is_valid(AnrMode mode) {
    return mode == ANR_MODE_MILD || mode == ANR_MODE_MODERATE ||
           mode == ANR_MODE_BALANCED || mode == ANR_MODE_AGGRESSIVE;
}

/* CLI name/enum conversion. Unknown names return -1. */
static inline int anr_nr_mode_from_name(const char *name) {
    if (!name) return -1;
    if (strcmp(name, "mild") == 0)       return ANR_MODE_MILD;
    if (strcmp(name, "moderate") == 0)   return ANR_MODE_MODERATE;
    if (strcmp(name, "balanced") == 0)   return ANR_MODE_BALANCED;
    if (strcmp(name, "aggressive") == 0) return ANR_MODE_AGGRESSIVE;
    return -1;
}

static inline const char *anr_nr_mode_name(AnrMode mode) {
    switch (mode) {
        case ANR_MODE_MILD:       return "mild";
        case ANR_MODE_MODERATE:   return "moderate";
        case ANR_MODE_BALANCED:   return "balanced";
        case ANR_MODE_AGGRESSIVE: return "aggressive";
        default:                     return "invalid";
    }
}

/* Frame speech gate = configured threshold + (q - ANR_SPEECH_PROTECT_ANCHOR_Q). This keeps the
 * margin above the noise-only SPP prior consistent across strengths; the anchor leaves the
 * configured value bit-exact.
 */
#define ANR_SPEECH_PROTECT_ANCHOR_Q 0.52f

/* ANR configuration. Grid and pool dimensions are fixed for an instance. */
typedef struct {
    int sample_rate;        // Sample rate (8000, 16000, 48000)
    int frame_size;         // Frame length in samples; equal to fft_size
    int hop_size;           // 50% overlap; equal to frame_size / 2
    int fft_size;           // Whitelisted power-of-two transform size

    // SPP parameters
    float alpha_xi;         // A priori SNR smoothing; 0.92 at the 16 ms tuning anchor
    float q;                // Speech prior probability (0.52 in balanced)
    float xi_min_db;        // A priori SNR floor in dB (-10 in balanced)

    // Suppression and LF speech floor; cross-band prior is optional and off by default.
    bool  cross_band_speech_prior;
    float cross_band_speech_prior_max_q;
    float cross_band_speech_prior_alpha;
    float noise_over_subtraction;
    bool  speech_protect_floor;
    float speech_protect_floor_db;
    float speech_protect_threshold;
    float speech_protect_frame_threshold;   // Frame gate authored at ANR_SPEECH_PROTECT_ANCHOR_Q

    // Speech preservation; DD-from-G_H1 and make-up are optional and off by default.
    bool  dd_from_gmmse;              // DD power from G_H1 (Cohen eq. 18)
    bool  speech_aware_noise_tracking;
    float alpha_d_speech;             // Slow rising LF noise update
    float noise_gate_xi_db;            // Frame speech-evidence threshold
    float noise_gate_lf_hz;            // Protected low-frequency range
    float noise_gate_frame_frac;       // Required fraction of speech bins
    bool  makeup_gain;                 // Post-OM-LSA frame scalar
    float makeup_prior_xi_db;         // C make-up uses noise_gate_xi_db; field mirrors Python.
    float makeup_blim;
    float makeup_up_slope;
    float makeup_down_slope;

    // MCRA parameters
    float alpha_s;          // Time smoothing (0.95)
    float alpha_d;          // Noise update (0.85 at the 16-ms tuning anchor)
    float alpha_p;          // SPP smoothing (0.2)
    int L;                  // Minimum tracking window: 32 frames at the 16-ms
                            // anchor (~512 ms), grid-retimed
    float delta_db;         // Bias compensation in dB (10.0)
    int num_init_frames;    // Noise initialization (~200 ms, grid-retimed)

    // MCRA scene change detection
    float scene_change_threshold_db;     // Hi-freq gamma threshold in dB (10.0)
    int scene_change_min_frames;         // Consecutive duration (~50 ms by default)
    float scene_change_blend;            // Noise reset blend factor (0.5)
    float scene_change_flatness_threshold; // Hi-freq spectral flatness threshold (0.4)
    float broadband_threshold;           // Broadband scene-reset gate; 1.0 disables it

    // Gain parameters
    float g_min_db;         // Minimum gain in amplitude dB, /20 (-25.0)
    float alpha_g;          // Python config parity only; C gain path uses alpha_attack/decay.
    float alpha_attack;     // Asymmetric attack (0.15 at the 16-ms anchor)
    float alpha_decay;      // Asymmetric decay (0.88 = alpha_g)
} AnrConfig;

/* Default FFT: 8k/128, 16k/256, 48k/1024. Alternate 8k/256 and 16k/512 grids are supported;
 * hop = FFT/2.
 */
static inline int anr_default_fft_size(int sample_rate) {
    return (sample_rate == 48000) ? 1024
         : (sample_rate == 16000) ? 256
         : (sample_rate == 8000) ? 128 : 0;
}

/* Retime an EMA coefficient from ref_hop_seconds to this hop. Keep the reference duration in
 * double precision: float rounding can change frame-count ceil() at an integer boundary.
 */
static inline float anr_retime_alpha_ref(float alpha_ref,
                                               int sample_rate, int hop_size,
                                               double ref_hop_seconds) {
    if (!(alpha_ref >= 0.0f && alpha_ref <= 1.0f) ||
        sample_rate <= 0 || hop_size <= 0 || ref_hop_seconds <= 0.0) {
        return alpha_ref;
    }
    double exponent = ((double)hop_size / (double)sample_rate) / ref_hop_seconds;
    return powf(alpha_ref, (float)exponent);
}

/** Convert a coefficient tuned at 10-ms updates to this grid's hop. */
static inline float anr_retime_alpha(float alpha_10ms,
                                           int sample_rate, int hop_size) {
    return anr_retime_alpha_ref(alpha_10ms, sample_rate, hop_size, 0.010);
}

/* Retime a frame count without shortening duration. Reference seconds must remain double,
 * matching anr_retime_alpha_ref().
 */
static inline int anr_retime_frames_ref(int frames_ref,
                                             int sample_rate, int hop_size,
                                             double ref_hop_seconds) {
    double seconds, frames_d;
    if (frames_ref <= 0 || sample_rate <= 0 || hop_size <= 0 ||
        ref_hop_seconds <= 0.0) {
        return 0;
    }
    seconds = (double)frames_ref * ref_hop_seconds;
    frames_d = ceil(seconds * (double)sample_rate / (double)hop_size - 1e-12);
    if (frames_d < 1.0) frames_d = 1.0;
    return frames_d > (double)INT_MAX ? 0 : (int)frames_d;
}

/** Convert a frame count authored at 10 ms without shortening real duration. */
static inline int anr_retime_frames(int frames_10ms,
                                         int sample_rate, int hop_size) {
    if (frames_10ms <= 0 || sample_rate <= 0 || hop_size <= 0) return 0;
    int64_t numerator = (int64_t)frames_10ms * (int64_t)sample_rate;
    int64_t denominator = (int64_t)100 * (int64_t)hop_size;
    int64_t frames = (numerator + denominator - 1) / denominator;
    return frames > INT_MAX ? 0 : (int)frames;
}

/** Build the default preset directly on one whitelisted no-padding grid. */
static inline AnrConfig anr_default_config_for_grid(
        int sample_rate, int fft_size) {
    /* Zero padding bytes so config copies and same-mode reconfiguration are deterministic. */
#ifdef __cplusplus
    AnrConfig config = {};
#else
    AnrConfig config = {0};
#endif

    config.sample_rate = sample_rate;

    // No padding, 50% overlap; validation rejects unsupported rate/grid pairs.
    config.frame_size = fft_size;
    config.hop_size = fft_size / 2;
    config.fft_size = fft_size;

    // SPP anchors: alpha_xi and LF tracking use 16 ms.
    config.alpha_xi = anr_retime_alpha_ref(0.92f, sample_rate, config.hop_size, 0.016);
                                 // DD ξ smoothing shared by all strengths.
    config.q = 0.52f;
    config.xi_min_db = -10.0f;
    config.cross_band_speech_prior = false;
    config.cross_band_speech_prior_max_q = 0.54f;
    config.cross_band_speech_prior_alpha = 0.90f;
    config.noise_over_subtraction = 1.4f;
    config.speech_protect_floor = true;
    config.speech_protect_floor_db = -15.0f;
    config.speech_protect_threshold = 0.0f;
    config.speech_protect_frame_threshold = 0.55f;
    config.dd_from_gmmse = false;
    config.speech_aware_noise_tracking = true;
    config.alpha_d_speech = anr_retime_alpha_ref(
        0.95f, sample_rate, config.hop_size, 0.016);
    config.noise_gate_xi_db = 3.0f;
    config.noise_gate_lf_hz = 300.0f;
    config.noise_gate_frame_frac = 0.50f;
    config.makeup_gain = false;
    config.makeup_prior_xi_db = 3.0f;
    config.makeup_blim = 0.5f;
    config.makeup_up_slope = 1.3f;
    config.makeup_down_slope = 0.3f;

    // MCRA parameters (sync with Python v3_2_config.yaml)
    config.alpha_s = anr_retime_alpha(0.95f, sample_rate, config.hop_size);
    /* 10-ms alpha_d anchor 0.903414 corresponds to 0.85 at a 16-ms hop. */
    config.alpha_d = anr_retime_alpha(0.903414f, sample_rate, config.hop_size);
    config.alpha_p = anr_retime_alpha(0.2f, sample_rate, config.hop_size);
    // L is authored at 16 ms (32 frames = 512 ms); other MCRA anchors use 10 ms.
    config.L = anr_retime_frames_ref(32, sample_rate, config.hop_size, 0.016);
    config.delta_db = 10.0f;
    config.num_init_frames = anr_retime_frames(20, sample_rate, config.hop_size);

    // MCRA scene change detection
    config.scene_change_threshold_db = 10.0f;
    config.scene_change_min_frames = anr_retime_frames(5, sample_rate, config.hop_size);
    config.scene_change_blend = 0.5f;
    config.scene_change_flatness_threshold = 0.4f;
    config.broadband_threshold = 1.0f;   // <1.0 enables broadband scene reset; 1.0 == disabled.

    // Gain parameters (sync with Python v3_2_config.yaml)
    config.g_min_db = -25.0f;
    config.alpha_g = anr_retime_alpha(0.88f, sample_rate, config.hop_size);
    // alpha_attack uses the 16-ms anchor; alpha_g/alpha_decay use 10 ms.
    config.alpha_attack = anr_retime_alpha_ref(0.15f, sample_rate, config.hop_size, 0.016);
    config.alpha_decay = anr_retime_alpha(0.88f, sample_rate, config.hop_size);

    return config;
}

static inline AnrConfig anr_default_config(int sample_rate) {
    return anr_default_config_for_grid(
        sample_rate, anr_default_fft_size(sample_rate));
}

/* Strength presets share tracker/DD/gain dynamics and change only q, xi_min_db, g_min_db and
 * over-subtraction. g_min_db is amplitude dB (/20).
 */
static inline AnrConfig anr_config_for_mode_grid(
        int sample_rate, int fft_size, AnrMode mode) {
    AnrConfig config = anr_default_config_for_grid(sample_rate, fft_size);

    switch (mode) {
    case ANR_MODE_MILD:
        config.g_min_db = -20.0f;
        config.q = 0.58f;
        config.xi_min_db = -10.0f;
        config.noise_over_subtraction = 1.2f;
        break;

    case ANR_MODE_MODERATE:
        config.g_min_db = -23.0f;
        config.q = 0.54f;
        config.xi_min_db = -10.0f;
        config.noise_over_subtraction = 1.3f;
        break;

    case ANR_MODE_AGGRESSIVE:
        config.g_min_db = -28.0f;
        config.q = 0.45f;
        config.xi_min_db = -12.0f;
        /* Aggressive over-subtraction factor. */
        config.noise_over_subtraction = 1.3f;
        break;

    case ANR_MODE_BALANCED:
    default:
        break;
    }

    return config;
}

static inline AnrConfig anr_config_for_mode(
        int sample_rate, AnrMode mode) {
    return anr_config_for_mode_grid(
        sample_rate, anr_default_fft_size(sample_rate), mode);
}

/* Optional speech-protection overlay; not a strength preset. */
static inline void anr_apply_speech_protection_experiment(
        AnrConfig* config) {
    if (!config) return;
    config->noise_over_subtraction = 1.0f;
    config->speech_protect_floor = true;
    config->speech_protect_floor_db = -20.0f;
    config->speech_protect_threshold = 0.50f;
    config->speech_protect_frame_threshold = 0.55f;
}

/* Optional cross-band-prior overlay; disabled by default. */
static inline void anr_apply_cross_band_speech_experiment(
        AnrConfig* config) {
    if (!config) return;
    anr_apply_speech_protection_experiment(config);
    config->cross_band_speech_prior = true;
    config->cross_band_speech_prior_max_q =
        config->q < 0.95f ? config->q + 0.04f : 0.99f;
    config->cross_band_speech_prior_alpha = 0.90f;
}

/* Construction/reconfiguration validation: supported grid, bounded dimensions, and finite
 * tunables in valid ranges. Query/create/init use this gate before size arithmetic. Returns
 * true only for a usable configuration.
 */
static inline bool anr_finite_in_range(float v, float lo, float hi) {
    return isfinite(v) && v >= lo && v <= hi;
}

static inline bool anr_validate_config(const AnrConfig* config) {
    if (!config) return false;

    // Supported sample rates.
    if (config->sample_rate != 8000 &&
        config->sample_rate != 16000 &&
        config->sample_rate != 48000) {
        return false;
    }

    // Reject negative dimensions before unsigned size conversion.
    if (config->frame_size < 0 || config->hop_size < 0 || config->fft_size < 0 ||
        config->L < 0 || config->num_init_frames < 0 ||
        config->scene_change_min_frames < 0) {
        return false;
    }

    // Positive power-of-two FFT within the size bound.
    if (config->fft_size <= 0 || config->fft_size > 8192 ||
        (config->fft_size & (config->fft_size - 1)) != 0) {
        return false;
    }

    // frame = FFT and hop = frame/2; only the five supported grids are valid.
    if (config->frame_size <= 0 || config->frame_size != config->fft_size) {
        return false;
    }
    if (config->hop_size <= 0 || config->frame_size != 2 * config->hop_size) {
        return false;
    }
    if (!((config->sample_rate == 8000 &&
           (config->fft_size == 128 || config->fft_size == 256)) ||
          (config->sample_rate == 16000 &&
           (config->fft_size == 256 || config->fft_size == 512)) ||
          (config->sample_rate == 48000 && config->fft_size == 1024))) {
        return false;
    }

    // Bound tracker and initialization storage.
    if (config->L <= 0 || config->L > 320) {
        return false;
    }
    if (config->num_init_frames <= 0 || config->num_init_frames > 200) {
        return false;
    }

    // Tunables must be finite and remain in their valid ranges.

    // SPP: alpha in [0,1], q strictly in (0,1), xi floor in power dB.
    if (!isfinite(config->alpha_xi) || config->alpha_xi < 0.0f || config->alpha_xi > 1.0f) {
        return false;
    }
    if (!isfinite(config->q) || config->q <= 0.0f || config->q >= 1.0f) {
        return false;
    }
    if (!isfinite(config->xi_min_db) ||
        config->xi_min_db < -80.0f || config->xi_min_db > 80.0f) {
        return false;
    }
    if (!isfinite(config->cross_band_speech_prior_max_q) ||
        config->cross_band_speech_prior_max_q <= 0.0f ||
        config->cross_band_speech_prior_max_q >= 1.0f ||
        (config->cross_band_speech_prior &&
         config->cross_band_speech_prior_max_q < config->q)) {
        return false;
    }
    if (!isfinite(config->cross_band_speech_prior_alpha) ||
        config->cross_band_speech_prior_alpha < 0.0f ||
        config->cross_band_speech_prior_alpha >= 1.0f) {
        return false;
    }
    if (!anr_finite_in_range(config->noise_over_subtraction, 1.0f, 4.0f)) {
        return false;
    }
    if (!isfinite(config->speech_protect_floor_db) ||
        config->speech_protect_floor_db < -80.0f ||
        config->speech_protect_floor_db > 0.0f ||
        (config->speech_protect_floor &&
         config->speech_protect_floor_db < config->g_min_db)) {
        return false;
    }
    if (!anr_finite_in_range(config->speech_protect_threshold, 0.0f, 1.0f) ||
        !anr_finite_in_range(config->speech_protect_frame_threshold,
                                  0.0f, 1.0f)) {
        return false;
    }
    if (!isfinite(config->alpha_d_speech) ||
        config->alpha_d_speech < 0.0f || config->alpha_d_speech >= 1.0f) {
        return false;
    }
    if (!anr_finite_in_range(config->noise_gate_xi_db, -80.0f, 80.0f)) {
        return false;
    }
    if (!isfinite(config->noise_gate_lf_hz) ||
        config->noise_gate_lf_hz <= 0.0f ||
        config->noise_gate_lf_hz > 0.5f * (float)config->sample_rate) {
        return false;
    }
    if (!anr_finite_in_range(config->noise_gate_frame_frac, 0.0f, 1.0f) ||
        !anr_finite_in_range(config->makeup_prior_xi_db, -80.0f, 80.0f)) {
        return false;
    }
    if (!isfinite(config->makeup_blim) ||
        config->makeup_blim <= 0.0f || config->makeup_blim >= 1.0f ||
        !isfinite(config->makeup_up_slope) || config->makeup_up_slope < 0.0f ||
        !isfinite(config->makeup_down_slope) ||
        config->makeup_down_slope < 0.0f || config->makeup_down_slope > 1.0f) {
        return false;
    }

    // MCRA smoothing coefficients in [0,1]; delta in power dB.
    if (!isfinite(config->alpha_s) || config->alpha_s < 0.0f || config->alpha_s > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_d) || config->alpha_d < 0.0f || config->alpha_d > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_p) || config->alpha_p < 0.0f || config->alpha_p > 1.0f) {
        return false;
    }
    if (!isfinite(config->delta_db) ||
        config->delta_db < -80.0f || config->delta_db > 80.0f) {
        return false;
    }

    // Scene threshold in power dB; blend/flatness/broadband ratios in [0,1].
    if (!isfinite(config->scene_change_threshold_db) ||
        config->scene_change_threshold_db < -80.0f ||
        config->scene_change_threshold_db > 80.0f) {
        return false;
    }
    if (!isfinite(config->scene_change_blend) ||
        config->scene_change_blend < 0.0f || config->scene_change_blend > 1.0f) {
        return false;
    }
    if (!isfinite(config->scene_change_flatness_threshold) ||
        config->scene_change_flatness_threshold < 0.0f ||
        config->scene_change_flatness_threshold > 1.0f) {
        return false;
    }
    if (!isfinite(config->broadband_threshold) ||
        config->broadband_threshold < 0.0f || config->broadband_threshold > 1.0f) {
        return false;
    }

    // Gain floor in amplitude dB; smoothing coefficients in [0,1].
    if (!isfinite(config->g_min_db) ||
        config->g_min_db < -80.0f || config->g_min_db > 80.0f) {
        return false;
    }
    if (!isfinite(config->alpha_g) || config->alpha_g < 0.0f || config->alpha_g > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_attack) ||
        config->alpha_attack < 0.0f || config->alpha_attack > 1.0f) {
        return false;
    }
    if (!isfinite(config->alpha_decay) ||
        config->alpha_decay < 0.0f || config->alpha_decay > 1.0f) {
        return false;
    }

    return true;
}

#ifdef __cplusplus
}
#endif

#endif // ANR_TYPES_H
