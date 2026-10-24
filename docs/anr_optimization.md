# ANR bit-exact optimization

NEON kernels accelerate the C core without changing any output bit, except the
payload bits of a NaN result (see [Bit-exact scope](#bit-exact-scope)). C API
naming is in [anr_migration.md](anr_migration.md).

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

`make bench-anr` (from `c_impl/`) times `anr_process()` and `anr_process_gain()` with an
extra noise PSD on three grids and two strengths. It uses frozen synthetic spectra, a
fresh instance per pass, five untimed warm-up passes and 30 timed passes of 600 hops, and
prints median, quartiles and minimum. The figures below are medians in microseconds per
hop on an Arm64 development host with the NE10 backend and clang -O2 with the strict FP flags, 12
alternating runs of the two binaries. They describe the host and compiler that built the
binaries; they are not target-platform figures.

**Scalar-twin build to NEON build (38.9 % to 45.0 % less).** The baseline is the same
source compiled with `EXTRA_CFLAGS=-DANR_REFERENCE_KERNELS` (every kernel runs its scalar
twin).

| Grid | Strength | `anr_process` | `anr_process_gain` + extra PSD |
|---|---|---|---|
| 16 kHz, FFT 256 | balanced | 1.435 → 0.794 (−44.7 %) | 1.337 → 0.740 (−44.7 %) |
| 16 kHz, FFT 256 | aggressive | 1.434 → 0.788 (−45.0 %) | 1.337 → 0.740 (−44.7 %) |
| 16 kHz, FFT 512 | balanced | 2.601 → 1.573 (−39.5 %) | 2.392 → 1.462 (−38.9 %) |
| 16 kHz, FFT 512 | aggressive | 2.640 → 1.570 (−40.5 %) | 2.402 → 1.460 (−39.2 %) |
| 48 kHz, FFT 1024 | balanced | 5.297 → 2.952 (−44.3 %) | 5.177 → 2.863 (−44.7 %) |
| 48 kHz, FFT 1024 | aggressive | 5.314 → 2.936 (−44.8 %) | 5.185 → 2.865 (−44.7 %) |

The scalar twins are compiled by the host compiler, which vectorizes some of them; on a
compiler or core that does not, the gap to the scalar twins is expected to be larger.
Validation scope and its limits are in [anr_validation.md](anr_validation.md).

## Verification

From `c_impl/`, run:

```sh
make BACKEND=ne10 SIMD=1 WERROR=1 test
make BACKEND=ne10 SIMD=1 WERROR=1 test-full
```

`test` builds `all lib mem parity`, runs the C test targets (`test-config`, `test-reconfigure`,
`test-noise-restart`, `test-scene-change`, `test-shared-startup`, `test-api-cpp`, `test-bit-exact`),
the pytest suite, and the Python/C parity gate (220 of the 428 scenarios: four strengths on the
16 kHz and 48 kHz grids, without the 8 kHz grids, the `scale_1e-3`/`scale_1e-5`/`scale_1e-6`/`int16_pk55`
rungs and the make-up rows of the 16k/512 and 48k/1024 grids). The Python/C configuration comparison
(`python/tests/test_config_parity.py`, five grids x four strengths) runs the `test-config-parity`
dump from inside pytest. `test-full` adds the standalone `test-config-parity`, `test-bit-exact` at the
other `SIMD` setting, and all 428 parity scenarios.

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
code against an independent rule). When a scalar twin changes, compare the per-hop stream
hash of the sources before and after the edit, built in the same configuration.

Repeat the bit-exact target for both SIMD settings with the NE10 backend when modifying these
kernels. Keep `-ffp-contract=off`; reassociation and fast-math are outside this contract.
The test script uses the production optimization definitions and does not forward
arbitrary DEBUG or EXTRA_CFLAGS into the reference build. C++ API, configuration,
reconfiguration, silence restart and scene-change regressions are separate make targets.
Python/C gain comparisons are numerical parity checks, not Python/C bit-exactness.

## Digital silence

A frame whose bins are all exactly zero carries no noise statistics: it does not count
toward noise initialization and does not advance the noise tracker. A stream that starts
with silence therefore initializes on the signal that follows, and a converged noise floor
is kept across a silent stretch. `make test-noise-restart` covers both, and a tone whose
first frame is a reduced-power waveform onset after five seconds of silence. Streaming
reset stays caller-controlled at a new stream or discontinuity.

The initialization window (`num_init_frames`, about 200 ms at unity gain) follows the
leading silence instead of being consumed by it: the first non-zero frames of such a stream
pass unprocessed until the floor is initialized, exactly as the first frames of a stream
that starts with signal do. A click inside that window is not suppressed.

## First tracked frame

The first SPP estimate after initialization has no a-priori SNR history and uses the direct
estimate `max(gamma - 1, xi_min)`, with the same floor `xi_min` as the decision-directed
estimate of later frames. Without the floor, a bin whose posterior SNR is at most 1 gets
xi = 0, the MMSE-LSA gain is then `g_min` for any SPP, and the first tracked frame sits at
the gain floor while the following frames settle higher; the log-gain smoothing carries the
notch into the next two frames. The bypass state left by the initialization window
(`gain_prev`, `enhanced_psd_prev`) is not read by this estimate. The direct branch is taken
by the first estimate and by any call without gain history (`gain_prev` NULL), always with
the same floor. The recursive decision-directed, noise-tracker and gain-smoothing state
carries the effect into later frames; it is not guaranteed to decay monotonically.
`make test-noise-restart` and `python/tests/test_first_frame_gain.py` cover it.

The Python `SppEstimator` is shared by the V3, V3-2 and V3-3 denoisers and
`compute_spp_batch`; the C library mirrors V3-2 only.
