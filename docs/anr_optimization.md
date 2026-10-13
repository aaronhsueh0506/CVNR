# ANR bit-exact optimization

This release keeps the processing and presets of the preceding release. It renames the C
API and source/archive files to ANR, moves Python reference code into `python/`,
and accelerates existing C operations without changing any output bit, except the
payload bits of a NaN result (see [Bit-exact scope](#bit-exact-scope)). See
[migration](anr_migration.md).

## NEON kernels

Each kernel is a pair of static functions in the library sources. The scalar twin
defines the arithmetic and also processes the tail of an array; the NEON twin processes
four bins at a time. Both keep the operation order of the original loop: separate rounded
multiply and add (no fused multiply-add), the original divides, ordered compares with a
bit select (so a NaN behaves as in the scalar branch), and no reciprocal or square-root
estimates. The NEON twin returns the same bits as the scalar twin except the payload bits
of a NaN result. No additional state, allocation or delay is introduced.
Building with `-DANR_REFERENCE_KERNELS` selects the scalar twins instead (the final-gain
passes use the per-bin reference loop), which is how one source tree is compared with
itself.

| Stage | Kernel |
|---|---|
| MCRA minimum ring, rescan | Lane-wise running minima over the row. The result is the ordered minimum whenever the seed vectors hold no NaN and the minimum is not a zero; any other row takes the scalar first-on-tie rule, so NaN, signed zero and ties behave exactly as before. |
| MCRA minimum ring, update | Compare and select of the incremental minimum on four bins. Bins whose evicted value was the minimum are collected through a lane table without a data-dependent branch and rescanned after each block of 128 bins. |
| MCRA inert-bin restart | Select between the restart update and the unchanged value. |
| SPP decision-directed pass | Posterior SNR, a-priori SNR and the exponent argument, with the original three divides. |
| Gain input preparation | Clamp and divide that produce v and xi/(1+xi). |
| Final gain | Blend and smoothing of the log gain before the batched exponential, and select and store of the next-hop state after it. |

Loops that stay scalar: the speech-evidence sum and the high-band power and noise sums
(serial float reductions whose order is part of the result), the integer counters, the
speech-indicator smoothing, the gain application and the loops that clang already
vectorizes with the same result. The exponential, logarithm and E1 kernels come from
`audio_common` and are unchanged.

## Bit-exact scope

For every input that holds no NaN, scalar twin, NEON twin and the loops they replace return
identical bits; the same holds for infinities, signed zeros and subnormals. A NaN stays a NaN
in the same place. Only the payload bits of a NaN result can differ: the NEON final-gain
blend and store (`final_blend`, `final_store`) did so in about 0.9 % of the calls of a
random-bit-pattern differential test against the original loops, and no other kernel did.
Every statement below that says "identical" or "bit-exact" carries this exception.

## Cost

`make bench-anr` (from `c_impl/`) times `anr_process()` and `anr_process_gain()` with an
extra noise PSD on three grids and two strengths. It uses frozen synthetic spectra, a
fresh instance per pass, five untimed warm-up passes and 30 timed passes of 600 hops, and
prints median, quartiles and minimum. The figures below are medians in microseconds per
hop on Apple M4 with the NE10 backend and clang -O2 with the strict FP flags, 12
alternating runs of the two binaries compared in each table. They describe the host and
compiler that built the binaries; they are not target-platform figures.

The two tables answer different questions and have different baselines; do not mix them.

**Scalar-twin build to NEON build (36.6 % to 42.7 % less).** The baseline is the same
source compiled with `EXTRA_CFLAGS=-DANR_REFERENCE_KERNELS` (every kernel runs its scalar
twin), the comparison the NEON kernels are designed for.

| Grid | Strength | `anr_process` | `anr_process_gain` + extra PSD |
|---|---|---|---|
| 16 kHz, FFT 256 | balanced | 1.455 → 0.853 (−41.6 %) | 1.391 → 0.827 (−40.8 %) |
| 16 kHz, FFT 256 | aggressive | 1.459 → 0.852 (−41.7 %) | 1.390 → 0.828 (−40.5 %) |
| 16 kHz, FFT 512 | balanced | 2.678 → 1.648 (−38.4 %) | 2.507 → 1.588 (−36.6 %) |
| 16 kHz, FFT 512 | aggressive | 2.717 → 1.655 (−39.2 %) | 2.518 → 1.590 (−36.9 %) |
| 48 kHz, FFT 1024 | balanced | 5.461 → 3.142 (−42.5 %) | 5.395 → 3.103 (−42.4 %) |
| 48 kHz, FFT 1024 | aggressive | 5.470 → 3.135 (−42.7 %) | 5.410 → 3.102 (−42.6 %) |

**Before to after this change, same build (39.7 % to 48.6 % less).** The baseline is the
code before the NEON kernels, both binaries built with the NEON path on. That code already
had a NEON ordered minimum, which on this host was slower than a plain scalar loop, so
this reduction is larger than the one above. An independent repetition of the comparison
gave 38.9 % to 46.6 %.

| Grid | Strength | `anr_process` | `anr_process_gain` + extra PSD |
|---|---|---|---|
| 16 kHz, FFT 256 | balanced | 1.607 → 0.831 (−48.3 %) | 1.537 → 0.805 (−47.6 %) |
| 16 kHz, FFT 256 | aggressive | 1.614 → 0.830 (−48.6 %) | 1.539 → 0.805 (−47.7 %) |
| 16 kHz, FFT 512 | balanced | 2.768 → 1.647 (−40.5 %) | 2.628 → 1.584 (−39.7 %) |
| 16 kHz, FFT 512 | aggressive | 2.815 → 1.648 (−41.4 %) | 2.632 → 1.585 (−39.8 %) |
| 48 kHz, FFT 1024 | balanced | 5.880 → 3.135 (−46.7 %) | 5.806 → 3.099 (−46.6 %) |
| 48 kHz, FFT 1024 | aggressive | 5.837 → 3.131 (−46.4 %) | 5.796 → 3.096 (−46.6 %) |

The scalar twins are compiled by the host compiler, which vectorizes some of them; on a
compiler or core that does not, the gap to the scalar twins is expected to be larger.
Validation scope and its limits are in [anr_validation.md](anr_validation.md).

## Verification

From `c_impl/`, run:

```sh
make BACKEND=ne10 SIMD=1 WERROR=1 all lib mem parity test-config test-reconfigure test-noise-restart test-scene-change test-config-parity test-api-cpp test-bit-exact
make BACKEND=kiss SIMD=0 WERROR=1 test-bit-exact
```

`make test-bit-exact` builds the library twice from the same sources, once with
`-DANR_REFERENCE_KERNELS`, and runs three checks:

- a synthetic per-hop stream (three grids; four strengths, DD-from-G_H1, cross-band
  prior with make-up, a fast-decay case that reaches the inert-bin restart, and a static
  pool; 256 hops each, including digital-silence hops; the feature cases add runtime
  resets and reconfiguration) whose state and output bytes must be identical between the two builds
  (its inputs are finite, so the payload exception does not arise);
- the ordered-minimum test, which compares the minimum with an independent scalar rule on
  random bit patterns, NaN payloads, signed zeros, infinities, subnormals, ties and
  unaligned starts;
- the kernel differential test (`test/test_anr_kernels.c`), which compares the scalar and
  NEON twin of every kernel on random values, NaN, signed zero, infinity, subnormals and
  values at each comparison boundary. A NaN result that differs from its twin only in the
  payload is counted separately; every other difference fails.

The kernel-level tests (`test/test_anr_kernels.c` and `test/test_min_ordered_special.c`)
run inside `make test-bit-exact`; there is no separate target. `test_anr_kernels.c` is the
only gate for the growth constant `1.0f + 1e-6f` of the minimum ring and for the
`1 - alpha_d` weight of the inert-bin restart: a change of either leaves the per-hop stream, which compares two
builds of the same sources, unchanged.

Under `SIMD=0` no NEON twin is compiled. `test_anr_kernels.c` then reports that it has
nothing to compare, and the stream comparison sets scalar against scalar, so `test-bit-exact`
cannot fail on a change of a scalar twin (only the ordered-minimum test still checks scalar
code against an independent rule). The scalar twins are covered by comparing the
per-hop stream hash of the preceding sources with that of the changed sources on the same
build configuration; run that comparison whenever a scalar twin changes.

Repeat the bit-exact target for both backends and SIMD settings when modifying these
kernels. Keep `-ffp-contract=off`; reassociation and fast-math are outside this contract.
The test script uses the production optimization definitions and does not forward
arbitrary DEBUG or EXTRA_CFLAGS into the reference build. C++ API, configuration,
reconfiguration, silence restart and scene-change regressions are separate make targets.
Python/C gain comparisons are numerical parity checks, not Python/C bit-exactness.

Digital silence. A frame whose bins are all exactly zero carries no noise
statistics: it does not count toward noise initialization and does not advance
the noise tracker. A stream that starts with silence therefore initializes on
the signal that follows, and a converged noise floor is kept across a silent
stretch. `make test-noise-restart` covers both, and a stationary tone whose
first frame is a reduced-power waveform onset after five seconds of silence.
Streaming reset remains caller-controlled at a new stream or discontinuity.
Existing scene-change adaptation is retained.

The initialization window (`num_init_frames`, about 200 ms at unity gain)
therefore follows the leading silence instead of being consumed by it: the first
non-zero frames of such a stream pass unprocessed until the floor is
initialized, exactly as the first frames of a stream that starts with signal do,
and the first tracked frame shows the usual cold-start dip. Streams without an
all-zero frame are unchanged bit for bit.
