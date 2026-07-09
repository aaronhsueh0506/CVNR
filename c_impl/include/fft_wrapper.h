/**
 * fft_wrapper.h - FFT wrapper interface
 *
 * Abstracts FFT implementation (KISS FFT by default)
 * Provides real-to-complex FFT for audio processing
 */

#ifndef FFT_WRAPPER_H
#define FFT_WRAPPER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Complex number structure
typedef struct {
    float r;  // Real part
    float i;  // Imaginary part
} Complex;

// Opaque FFT handle
typedef struct FftHandle FftHandle;

#ifdef USE_EXT_MEM
/**
 * Query the memory size needed for an FFT handle (for external allocation).
 * Includes the handle, the KISS forward/inverse configs, and the work buffers.
 *
 * @param fft_size FFT size (must be power of 2)
 * @return Bytes required, or 0 on invalid fft_size
 */
size_t fft_query_memsize(int fft_size);

/**
 * Create FFT handle in caller-provided memory (no internal malloc).
 *
 * @param fft_size FFT size (must be power of 2)
 * @param mem      Pre-allocated buffer (NR_MEM_ALIGN-aligned)
 * @param mem_size Size of buffer (>= fft_query_memsize(fft_size))
 * @return FFT handle (points into mem), or NULL on error
 */
FftHandle* fft_create(int fft_size, void* mem, size_t mem_size);
#else
/**
 * Create FFT handle for given size (malloc version)
 *
 * @param fft_size FFT size (must be power of 2)
 * @return FFT handle, or NULL on error
 */
FftHandle* fft_create(int fft_size);
#endif

/**
 * Destroy FFT handle. Under USE_EXT_MEM this is a no-op (caller owns the buffer).
 */
void fft_destroy(FftHandle* handle);

/**
 * Get number of frequency bins (fft_size/2 + 1)
 */
int fft_get_n_freqs(const FftHandle* handle);

/**
 * Forward FFT: real input -> complex output
 *
 * @param handle FFT handle
 * @param time_in Real input [fft_size]
 * @param freq_out Complex output [n_freqs]
 */
void fft_forward(FftHandle* handle, const float* time_in, Complex* freq_out);

/**
 * Inverse FFT: complex input -> real output
 *
 * @param handle FFT handle
 * @param freq_in Complex input [n_freqs]
 * @param time_out Real output [fft_size]
 */
void fft_inverse(FftHandle* handle, const Complex* freq_in, float* time_out);

/**
 * Compute magnitude spectrum from complex spectrum
 *
 * @param freq Complex spectrum [n_freqs]
 * @param magnitude Output magnitude [n_freqs]
 * @param n_freqs Number of frequency bins
 */
void fft_magnitude(const Complex* freq, float* magnitude, int n_freqs);

/**
 * Compute power spectrum from complex spectrum
 *
 * @param freq Complex spectrum [n_freqs]
 * @param power Output power (magnitude^2) [n_freqs]
 * @param n_freqs Number of frequency bins
 */
void fft_power(const Complex* freq, float* power, int n_freqs);

/**
 * Apply gain to complex spectrum (in-place)
 *
 * @param freq Complex spectrum [n_freqs]
 * @param gain Gain array [n_freqs]
 * @param n_freqs Number of frequency bins
 */
void fft_apply_gain(Complex* freq, const float* gain, int n_freqs);

#ifdef __cplusplus
}
#endif

#endif // FFT_WRAPPER_H
