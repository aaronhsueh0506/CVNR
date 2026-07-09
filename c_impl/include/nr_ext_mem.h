/**
 * nr_ext_mem.h - Static / external-memory allocation helpers (USE_EXT_MEM)
 *
 * When the library is compiled with -DUSE_EXT_MEM, the denoiser and every
 * sub-module (MCRA, SPP, FFT) place ALL of their internal state into a single
 * caller-provided memory block instead of calling malloc(). Each module exposes:
 *
 *     size_t <mod>_query_memsize(...);                       // size the block
 *     <Handle>* <mod>_create(..., void* mem, size_t size);  // no internal malloc
 *
 * The caller pre-allocates one block (a static array, or a Novatek hd_common_mem
 * block for DMA), and the create() functions bump-allocate every buffer out of
 * it. This header defines the single alignment used consistently by every
 * module's query_memsize()/create() pair, so the size reported always matches
 * the layout produced.
 *
 * Contract: the memory block passed to create() MUST be NR_MEM_ALIGN-aligned;
 * every internal sub-allocation is then also NR_MEM_ALIGN-aligned. create() also
 * zero-initialises the whole block so behaviour is byte-identical to the malloc
 * (calloc) build. mmse_lsa_destroy()/fft_destroy()/... free nothing under
 * USE_EXT_MEM — the caller owns and releases the block.
 */
#ifndef NR_EXT_MEM_H
#define NR_EXT_MEM_H

#ifdef USE_EXT_MEM
#include <stddef.h>
#include <stdint.h>

/* Bump-allocation alignment. 16 bytes covers float/Complex (4/8) and keeps
 * NE10 SIMD loads aligned. */
#define NR_MEM_ALIGN 16u

static inline size_t nr_aligned_size(size_t s) {
    return (s + (NR_MEM_ALIGN - 1u)) & ~(size_t)(NR_MEM_ALIGN - 1u);
}
#endif /* USE_EXT_MEM */

#endif /* NR_EXT_MEM_H */
