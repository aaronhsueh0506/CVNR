# Static Memory API — NR (feature/static-memory)

## Overview

Added static memory (pre-allocated buffer) support to all NR modules.
Each module now provides `_get_mem_size()` and `_init()` in addition to the
existing `_create()` / `_destroy()` API.

When using `_init()`, no internal malloc is called. The caller provides a
pre-allocated buffer and the module places all internal state via pointer
arithmetic with 16-byte alignment (ALIGN16).

## Target

Novatek embedded platform (no heap / limited heap). Pipeline allocates a
single memory pool via PA/VA, then slices it to each module.

## Changed Files

### Headers
- `c_impl/include/fft_wrapper.h` — Added ALIGN16 macro, `fft_init()`, `fft_get_mem_size()`
- `c_impl/include/spp_estimator.h` — Added `spp_init()`, `spp_get_mem_size()`
- `c_impl/include/mcra_noise_estimator.h` — Added `mcra_init()`, `mcra_get_mem_size()`
- `c_impl/include/mmse_lsa_denoiser.h` — Added `mmse_lsa_init()`, `mmse_lsa_get_mem_size()`

### Sources
- `c_impl/src/fft_wrapper.c` — `is_static` flag, `fft_get_mem_size()` (queries kiss_fft_alloc), `fft_init()`, updated `fft_destroy()`
- `c_impl/src/spp_estimator.c` — `is_static`, `spp_get_mem_size()` (struct + 2 float arrays), `spp_init()`, updated `spp_destroy()`
- `c_impl/src/mcra_noise_estimator.c` — `is_static`, `mcra_get_mem_size()` (handles USE_FAST_PERCENTILE), `mcra_init()`, updated `mcra_destroy()`
- `c_impl/src/mmse_lsa_denoiser.c` — `is_static`, `mmse_lsa_get_mem_size()` (sums all sub-modules), `mmse_lsa_init()` (places all buffers + calls sub-module `_init()`), updated `mmse_lsa_destroy()`

## Memory Layout (16kHz, frame=320, hop=160, fft=512)

```
MmseLsaDenoiser struct
├── input_buffer[320]
├── window[320]
├── fft_in[512]
├── spectrum[257] (Complex)
├── power[257], magnitude[257], phase[257], enhanced_mag[257]
├── spp[257], xi[257], gamma[257], gain[257]
├── ola_buffer[320]
├── gain_prev[257], enhanced_psd_prev[257]
├── init_power_sum[257], log_gain_prev[257]
├── FftHandle (via fft_init)
│   ├── kiss_fft_cfg (forward)
│   ├── kiss_fft_cfg (inverse)
│   ├── work_in[512]
│   └── work_out[257] (Complex)
├── McraNoiseEstimator (via mcra_init)
│   ├── noise_psd[257], S[257], S_min[257], spp[257]
│   └── min_buffer[150 × 257]   ← largest single allocation (~150 KB)
└── SppEstimator (via spp_init)
    ├���─ xi_prev[257]
    └── gamma_prev[257]
```

Total: ~215 KB (MCRA min_buffer is ~70% of total)

## API Pattern

```c
// 1. Query size
size_t size = mmse_lsa_get_mem_size(&config);

// 2. Init in pre-allocated memory
MmseLsaDenoiser* nr = mmse_lsa_init(mem, size, &config);

// 3. Process (same as malloc version)
mmse_lsa_process(nr, in, out);

// 4. Destroy is no-op (is_static=1 → skip free)
mmse_lsa_destroy(nr);
```

## Notes

- `_create()` API is unchanged and still works (backward compatible)
- `is_static` flag in each struct prevents `_destroy()` from calling free
- All buffers are 16-byte aligned (ALIGN16 macro)
- kiss_fft supports pre-allocated memory natively: `kiss_fft_alloc(nfft, inv, mem, &lenmem)`
