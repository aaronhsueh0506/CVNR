# NR

Single-channel traditional noise-reduction library. The release algorithm is
V3-2 MMSE-LSA/OMLSA with Bayesian speech-presence probability and MCRA noise
tracking. Python is the readable reference implementation; `c_impl/` is the
embedded C library, exposed through the functional ANR API (`anr.h`).

## Release contract

All processing grids are power-of-two, zero-padding-free, and use 50% overlap:

| Sample rate | Default frame/FFT | Default hop | Supported alternate |
|---:|---:|---:|---:|
| 8 kHz | 128 | 64 | 256/128 |
| 16 kHz | 256 | 128 | 512/256 |
| 48 kHz | 1024 | 512 | none |

`frame_size == fft_size` and `hop_size == frame_size / 2` are validated when
an instance is constructed. The Audio_ALG mono integration deliberately uses
the 8 kHz 256/128 alternate; the three main product grids are 16k/256/128,
16k/512/256, and 48k/1024/512.

The C library consumes and produces one complex spectrum per hop. Its caller
owns the rolling frame, periodic sqrt-Hann analysis/synthesis windows, rFFT,
iFFT, and overlap-add. `c_impl/example/main.c` is the complete time-domain
reference wrapper.

## Python usage

Python code, YAML configuration, dependencies and tests live in `python/`.
From the repository root, run the CLI below or set `PYTHONPATH=python` for
module imports. Audio fixtures are in `test_wav/`; benchmark tools write
outputs to `results/`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r python/requirements.txt

python python/process_audio.py input.wav --versions V3-2 \
  --nr-mode balanced --mode full --fft-size 256
```

`--nr-mode` selects suppression depth (`mild`, `moderate`, `balanced`, or
`aggressive`; the digits `0`-`3` select the same four in that order). All four
strengths share the same DD recursion, MCRA tracker, gain dynamics, and
low-frequency speech guard; a preset changes only `g_min`, the speech-presence
prior `q`, the a-priori-SNR floor, and noise over-subtraction, so the ladder is
monotonic and a stronger preset does not track speech as noise. Missing,
malformed, or unreadable YAML configuration is fatal; the CLI never falls back
to other defaults.

## C build and integration

The C API and archive are named ANR; [C API naming and Python layout](docs/anr_migration.md)
lists the source, header, type, function, and link names.
[NEON kernels and their bit-exact contract](docs/anr_optimization.md) covers the
kernels, three-grid cost measurements and reset behavior; what the checks cover
and their limits are in [docs/anr_validation.md](docs/anr_validation.md).
`make -C c_impl bench-anr` prints the per-hop cost of the current build.

```bash
# NE10/NEON build (embedded deliverable, the only FFT backend). SIMD=1 is the default.
make -C c_impl WERROR=1
make -C c_impl SIMD=0 test

# Scalar-kernel build.
make -C c_impl SIMD=0 WERROR=1
```

Use `anr_get_mem_size()` followed by `anr_init()` for the
caller-owned static-memory path. `anr_create()` is the heap convenience
wrapper. The pool path and heap path share the same processing core; see
[`c_impl/README.md`](c_impl/README.md) and the
[C integration manual](docs/c_user_manual_zh_TW.md) for API details.

The tuning scalars can be swapped on a running instance:
`anr_reconfigure()` takes a caller-composed `AnrConfig` verbatim, and
`anr_set_mode()` composes the canonical config for a strength mode. Nothing is
reallocated, so the grid and the pool-sizing fields (`L`, `num_init_frames`)
must match the instance; the noise floor, MCRA ring, SPP history and gain
smoothing history are preserved. An instance built from the unmodified canonical
preset for its grid (library-default `L`) can use `anr_set_mode()` directly. A
caller that layers its own overrides on top of a preset must rebuild its whole
composition and call `anr_reconfigure()`: the bare canonical preset passed to
`anr_set_mode()` reverts those overrides, or is refused when the overridden
fields are `L` or `num_init_frames`.
Details in [`c_impl/README.md`](c_impl/README.md).

HTML pages for integrators (self-contained, no external resources):
[`docs/html/nr.html`](docs/html/nr.html) (algorithm, sequence and flow diagrams,
latency), [`docs/html/nr_c_api.html`](docs/html/nr_c_api.html) (call order, error
semantics, reset), and [`docs/html/nr_c_api_params.html`](docs/html/nr_c_api_params.html)
(external versus internal parameters, public versus internal functions).

Build outputs are keyed by backend and configuration. `make -C c_impl
publish` creates the immutable release layout and provenance manifest; do not
copy an arbitrary file from a `bin/` directory.

## Validation

```bash
# Python tests, including Python/C effective-config parity.
python -m pytest

# C tests, Python/C configuration parity (five grids) and the numerical parity subset.
make -C c_impl WERROR=1 test
# Adds the other SIMD setting's bit-exact check, the standalone configuration dump
# and every numerical parity scenario (including the 8 kHz grids).
make -C c_impl WERROR=1 test-full

# Full VCTK+DEMAND benchmark and fail-closed comparison.
pip install -r python/requirements-dev.txt
python python/tools/run_vctk_benchmark.py --mode full --strength balanced \
  --output results/vctk_candidate.json
python python/tools/compare_vctk_benchmark.py \
  results/vctk_baseline.json results/vctk_candidate.json
```

The benchmark comparator refuses different grids, dropped/error cases, or
missing metrics before producing a verdict. PESQ/STOI are regression metrics,
not proof of subjective quality; release candidates still require the agreed
listening and target-device checks.

To score WAV files already produced by any enhancement model, without running
this NR implementation, use the directory scorer. Relative WAV paths must
match exactly; it never performs automatic delay alignment. The noisy input is
optional, but supplying it adds baseline and improvement metrics:

```bash
python python/tools/score_wav_directories.py \
  --clean-dir /path/to/clean \
  --enhanced-dir /path/to/enhanced \
  --noisy-dir /path/to/noisy \
  --output-dir results/model_name
```

The output directory contains `summary.json`, `summary.csv`, and
`per_file.csv`. Clean, enhanced, and optional noisy WAVs may have different
sample rates; each is resampled to the common 16 kHz scoring domain before
length validation, and all metrics use those same 16 kHz samples. Resampling
does not estimate or remove delay. This scorer requires the PESQ/STOI packages
from `python/requirements-dev.txt`.

## Limitations

- The first approximately 200 ms should contain noise or very little speech
  so MCRA can initialize reliably.
- This statistical single-microphone NR does not replace AEC, dereverberation,
  wind-noise handling, beamforming, or source separation.
- Impulsive noise and competing speech/music can violate its stationary-noise
  and binary speech-presence assumptions.
- Runtime grid changes require destroying/resetting and recreating state; do
  not switch FFT/hop size inside a stream.

## Repository layout

| Path | Purpose |
|---|---|
| `python/process_audio.py` | Python WAV CLI and canonical config composition |
| `python/core/`, `python/denoisers/` | Python reference implementation |
| `python/config/` | Versioned YAML configuration |
| `c_impl/include/`, `c_impl/src/` | Public C API and production source |
| `python/tests/`, `c_impl/test/` | Regression, parity, and negative-input tests |
| `python/tools/` | Benchmark, diagnosis, and conversion utilities |
| `docs/parameter_tuning.md` | Supported tuning workflow |
| `docs/html/` | Integrator pages: flow diagrams, API usage, parameter tables |
| `docs/archive/` | Historical plans and superseded research documents |

Source headers and the current READMEs take precedence over `docs/archive/`.
