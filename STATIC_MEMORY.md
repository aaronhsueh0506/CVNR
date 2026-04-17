# Static Memory API — NR (`feature/static-memory` branch)

> **Release**: v4.2.0 · Part A Review 修復已同步
> **對應檔案**: 所有 C 核心模組，詳見下方列表

## Overview

Added static memory (pre-allocated buffer) support to all NR modules.
Each module now provides `_get_mem_size()` and `_init()` in addition to the
existing `_create()` / `_destroy()` API.

When using `_init()`, no internal malloc is called. The caller provides a
pre-allocated buffer and the module places all internal state via pointer
arithmetic with 16-byte alignment (ALIGN16).

### v4.2 Part A 影響

- **Fix #3 (SPP `noise_psd_prev`)**: `spp_get_mem_size()` 新增 `ALIGN16(n_freqs * sizeof(float))` 區塊；`spp_init()` 從 pool 切出 `noise_psd_prev`
- **Fix #6 (flatness threshold)**: `mcra_init()` 從 `config->scene_change_flatness_threshold` 讀取，無記憶體影響
- **Fix #9 (q clip)**: `spp_init()` 同 `spp_create()` 對 `q` 套用 `(1e-6, 1-1e-6)` clip，無記憶體影響

靜態記憶體總量每實例增加約 **`n_freqs * 4` bytes**（16 kHz/257 bins ≈ 1 KB，48 kHz/513 bins ≈ 2 KB；相對於 MCRA `min_buffer` 的 ~33 KB / ~66 KB 而言很小）。

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

## Memory Layout (16 kHz, frame=320, hop=160, fft=512, L=32, n_freqs=257)

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
│   ├── min_buffer[L=32 × 257]      ← ~33 KB @ 16 kHz
│   └── init_power_buffer[20 × 257] (only if !USE_FAST_PERCENTILE)
└── SppEstimator (via spp_init) — v4.2 擴充 noise_psd_prev
    ├���─ xi_prev[257]
    ├── gamma_prev[257]
    └── noise_psd_prev[257]           ← v4.2 新增 (Fix #3)
```

Total (16 kHz, `USE_FAST_PERCENTILE`): **~50 KB**
Total (16 kHz, exact percentile): **~70 KB** (+20 KB for `init_power_buffer`)
Total (48 kHz, n_freqs=513, fft=1024): **~130 KB**

MCRA `min_buffer` 是主要佔比（≈65–70%）。v4.2 的 Fix #3 每實例增加 ~1 KB（16 kHz）或 ~2 KB（48 kHz）。

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
