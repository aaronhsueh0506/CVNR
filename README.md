# NR

Single-channel traditional noise-reduction library. The release algorithm is
V3-2 MMSE-LSA/OMLSA with Bayesian speech-presence probability and MCRA noise
tracking. Python is the readable reference implementation; `c_impl/` is the
embedded C library.

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

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python process_audio.py input.wav --versions V3-2 \
  --nr-mode balanced --mode full --fft-size 256
```

`--nr-mode` selects suppression depth (`mild`, `moderate`, `balanced`, or
`aggressive`). `--mode stationary` enables the content-preserving stationary
noise preset. Missing, malformed, or unreadable YAML configuration is fatal;
the CLI never silently falls back to unrelated defaults.

## C build and integration

```bash
# NE10/NEON build (embedded deliverable, default backend everywhere). SIMD=1 is the default.
make -C c_impl WERROR=1
make -C c_impl SIMD=0 test

# Portable, bit-reproducible reference build (explicit).
make -C c_impl BACKEND=kiss SIMD=0 WERROR=1
```

Use `mmse_lsa_get_mem_size()` followed by `mmse_lsa_init()` for the
caller-owned static-memory path. `mmse_lsa_create()` is the heap convenience
wrapper. The pool path and heap path share the same processing core; see
[`c_impl/README.md`](c_impl/README.md) and the
[C integration manual](docs/c_user_manual_zh_TW.md) for API details.

Build outputs are keyed by backend and configuration. `make -C c_impl
publish` creates the immutable release layout and provenance manifest; do not
copy an arbitrary file from a stale `bin/` directory.

## Validation

```bash
# Python tests, including Python/C effective-config parity.
python -m pytest tests

# C validation and configuration parity dump.
make -C c_impl SIMD=0 test
make -C c_impl test-config-parity

# Full VCTK+DEMAND benchmark and fail-closed comparison.
pip install -r requirements-dev.txt
python tools/run_vctk_benchmark.py --mode full --strength balanced \
  --output results/vctk_candidate.json
python tools/compare_vctk_benchmark.py \
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
python tools/score_wav_directories.py \
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
from `requirements-dev.txt`.

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
| `process_audio.py` | Python WAV CLI and canonical config composition |
| `core/`, `denoisers/` | Python reference implementation |
| `config/` | Versioned YAML configuration |
| `c_impl/include/`, `c_impl/src/` | Public C API and production source |
| `tests/`, `c_impl/test/` | Regression, parity, and negative-input tests |
| `tools/` | Benchmark, diagnosis, and conversion utilities |
| `docs/parameter_tuning.md` | Supported tuning workflow |
| `docs/archive/` | Historical plans and superseded research documents |

Historical result files under `results/` are evidence snapshots, not current
defaults. Source headers and the current READMEs take precedence if an archived
report disagrees.
