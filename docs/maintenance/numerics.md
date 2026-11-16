# ANR bit-exact optimization

NEON kernels accelerate the C core without changing any output bit, except the
payload bits of a NaN result (see [Bit-exact scope](#bit-exact-scope)). C API
naming is in [anr_migration.md](../anr_migration.md).

## NEON kernels

Each kernel is a pair of static functions, either in the library sources or in
audiolib `utility/simd_nr.h` (`skr_*`). The scalar twin
defines the arithmetic and also processes the tail of an array; the NEON twin processes
four bins at a time. Both keep the scalar loop's operation order: separate rounded
multiply and add (no fused multiply-add), exact divides, ordered compares with a
bit select (so a NaN behaves as in the scalar branch), and no reciprocal or square-root
estimates. The NEON twin returns the same bits as the scalar twin except the payload bits
of a NaN result. No additional state, allocation or delay is introduced.
Building with `-DANR_REFERENCE_KERNELS` selects the scalar twins instead (the final-gain
passes use the per-bin reference loop), so one source tree can be compared with itself.

| Stage | Kernel |
|---|---|
| MCRA minimum ring, rescan | Lane-wise running minima over the row. The result is the ordered minimum whenever the seed vectors hold no NaN and the minimum is not a zero; any other row takes the scalar first-on-tie rule, so NaN, signed zero and ties behave as in the scalar rule. |
| MCRA minimum ring, update | Compare and select of the incremental minimum on four bins. Bins whose evicted value was the minimum are collected through a lane table without a data-dependent branch and rescanned after each block of 128 bins. |
| MCRA inert-bin restart | Select between the restart update and the unchanged value. |
| SPP decision-directed pass | Posterior SNR, a-priori SNR and the exponent argument, with three exact divides. |
| Gain input preparation | Clamp and divide that produce v and xi/(1+xi). |
| Final gain | Blend and smoothing of the log gain before the batched exponential, and select and store of the next-hop state after it. |

Loops that stay scalar: the speech-evidence sum and the high-band power and noise sums
(serial float reductions whose order is part of the result), the integer counters, the
speech-indicator smoothing, the gain application and the loops that clang already
vectorizes with the same result. The exponential, logarithm and E1 kernels come from
`audiolib`.

## Bit-exact scope

For every input that holds no NaN, scalar twin, NEON twin and the plain per-bin loops return
identical bits; the same holds for infinities, signed zeros and subnormals. A NaN stays a NaN
in the same place. Only the payload bits of a NaN result can differ, and only in the NEON
final-gain blend and store (`final_blend`, `final_store`); no other kernel does.
Every statement below that says "identical" or "bit-exact" carries this exception.

## Cost

`make bench-anr` (from `c_impl/`) times `anr_process()` and `anr_process_gain_with_residual_psd()` with a
residual-echo PSD on three grids and two levels. It uses frozen synthetic spectra, a
fresh instance per pass, five untimed warm-up passes and 30 timed passes of 600 hops, and
prints median, quartiles and minimum. The figures below are medians in microseconds per
hop on an Arm64 development host with the NE10 backend and clang -O2 with the strict FP flags, 12
alternating runs of the two binaries. They describe the host and compiler that built the
binaries; they are not target-platform figures.

**Scalar-twin build to NEON build (38.9 % to 45.0 % less).** The baseline is the same
source compiled with `EXTRA_CFLAGS=-DANR_REFERENCE_KERNELS` (every kernel runs its scalar
twin).

| Grid | Level | `anr_process` | `anr_process_gain_with_residual_psd` |
|---|---|---|---|
| 16 kHz, FFT 256 | balanced | 1.435 → 0.794 (−44.7 %) | 1.337 → 0.740 (−44.7 %) |
| 16 kHz, FFT 256 | aggressive | 1.434 → 0.788 (−45.0 %) | 1.337 → 0.740 (−44.7 %) |
| 16 kHz, FFT 512 | balanced | 2.601 → 1.573 (−39.5 %) | 2.392 → 1.462 (−38.9 %) |
| 16 kHz, FFT 512 | aggressive | 2.640 → 1.570 (−40.5 %) | 2.402 → 1.460 (−39.2 %) |
| 48 kHz, FFT 1024 | balanced | 5.297 → 2.952 (−44.3 %) | 5.177 → 2.863 (−44.7 %) |
| 48 kHz, FFT 1024 | aggressive | 5.314 → 2.936 (−44.8 %) | 5.185 → 2.865 (−44.7 %) |

The scalar twins are compiled by the host compiler, which vectorizes some of them; on a
compiler or core that does not, the gap to the scalar twins is expected to be larger.
The following sections specify the validation scope and its limits.

## Verification

From `c_impl/`, run:

```sh
make BACKEND=ne10 SIMD=1 WERROR=1 test
make BACKEND=ne10 SIMD=1 WERROR=1 test-full
```

`test` builds `all lib mem parity`, runs the C test targets (`test-config`, `test-reconfigure`,
`test-noise-restart`, `test-gain-api`, `test-scene-change`, `test-shared-startup`, `test-api-cpp`, `test-cli-args`, `test-parity-runner`, `test-nrp2-io`, `test-bit-exact`),
the pytest suite, and the Python/C parity gate (220 of the 428 scenarios: four levels on the
16 kHz and 48 kHz grids, without the 8 kHz grids, the `scale_1e-3`/`scale_1e-5`/`scale_1e-6`/`int16_pk55`
rungs and the make-up rows of the 16k/512 and 48k/1024 grids). The Python/C configuration comparison
(`python/tests/test_config_parity.py`, five grids x four levels) runs the `test-config-parity`
dump from inside pytest. `test-full` adds the standalone `test-config-parity`, `test-bit-exact` at the
other `SIMD` setting, and all 428 parity scenarios.

`make test-bit-exact` builds the library twice from the same sources, once with
`-DANR_REFERENCE_KERNELS`, and runs three checks:

- a synthetic per-hop stream (three grids; four levels, DD-from-G_H1, cross-band
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
code against an independent rule). When a scalar twin changes, compare the per-hop stream
hash of the sources before and after the edit, built in the same configuration.

Repeat the bit-exact target for both SIMD settings with the NE10 backend when modifying these
kernels. Keep `-ffp-contract=off`; reassociation and fast-math are outside this contract.
The test script uses the production optimization definitions and does not forward
arbitrary DEBUG or EXTRA_CFLAGS into the reference build. C++ API, configuration,
reconfiguration, silence restart and scene-change regressions are separate make targets.
Python/C gain comparisons are numerical parity checks, not Python/C bit-exactness.

## Regression suites

Configuration, reconfiguration, noise restart, scene change, C++ header compilation and
Python/C configuration parity are separate make targets. The Python/C gain comparison
is a numerical parity check on float32 gains (absolute error statistics), not
Python/C bit-exactness.

`make test` runs the C targets at the current `SIMD` setting, the pytest suite (which includes
the Python/C configuration comparison for the five grids 8k/128, 8k/256, 16k/256, 16k/512 and
48k/1024) and a 220-scenario subset of the numerical parity check. `make test-full` also runs
`test-bit-exact` at the other `SIMD` setting and all 428 parity scenarios, including the 8 kHz
grids; the 8 kHz grids are covered in `make test` by the configuration comparison only.

## Digital-silence frames

Frames whose bins are all exactly zero do not count toward noise initialization and
do not advance the noise tracker; `make test-noise-restart` covers the behavior.

- A 1 kHz tone (10 s) that follows 5 s of exact zeros converges to the same gain as the
  same tone without leading silence, within 0.07 dB, at 16 kHz/FFT 256, 16 kHz/FFT 512
  and 48 kHz/FFT 1024 in the balanced and aggressive modes, and reaches -6 dB 0.192 s
  after the tone starts, within one 64 ms block of the control.
- Noise that follows 5 s of digital silence starts like a cold start: the output stays
  below -6 dB from 0.192 s after the noise starts (control without silence: 0.19-0.26 s)
  and is within 3 dB of its converged level from 0.26-0.58 s (control: 0.26-0.45 s).
- Streams without any all-zero frame are unaffected by the rule.
- Streams that contain all-zero frames differ by design: in a speech-like noise stream with
  isolated zero stretches of 20, 60 and 150 ms, the output in the 100 ms blocks after the
  longest stretch is up to 4.4 dB quieter than the same stream without a stretch (deeper
  noise suppression; worst case 16 kHz/FFT 512, aggressive mode), and the last two seconds
  differ by less than 0.01 dB.
- Leading digital silence moves the unity-gain initialization window onto the first
  non-zero frames (19 frames, 0.2 s at 48 kHz/FFT 1024).

## First tracked frame after initialization

Mean over bins of the gain in dB, first tracked frame against the settled value of the
same stream: 0.0 to 1.7 dB below it on six pipeline streams (echo canceller residual PSD
added to the noise floor), and at most 0.9 dB on noise-only input (white, babble and car
noise, three grids, with and without leading zeros). `make test-noise-restart` and
`python/tests/test_first_frame_gain.py` fail when the `xi_min` floor of the first estimate
is removed.

## Scope limits

- The cost figures above are host measurements on
  an Arm64 development host with NE10; they are not embedded-board, whole-pipeline or other-compiler
  results. Embedded cycle counts are not covered.
- Bit-exactness (except the payload bits of a NaN result) is established between builds of
  the same source tree with the NE10 FFT backend.
- The Python reference and the C library agree numerically, not bitwise.
- The digital-silence stimuli are synthetic (speech-like harmonic bursts, coloured noise,
  a weak tone); they do not cover recorded material.
- The unity-gain initialization window is not suppressed: a click inside it passes
  unprocessed.
