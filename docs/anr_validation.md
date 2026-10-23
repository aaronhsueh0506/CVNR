# ANR validation scope

What the repository checks for the C ANR library, and what those checks do not
cover. The bit-exact claims are reproduced by the make targets named below
([ANR bit-exact optimization](anr_optimization.md)); the digital-silence
figures are recorded measurements whose raw files are not stored in the
repository.

## Bit-exact gate

`make test-bit-exact`, for `SIMD=0` and `SIMD=1` (FFT backend NE10), compares an
optimized build with an independent scalar reference build
(`-DANR_REFERENCE_KERNELS`): identical state and gain traces (164,236,480 trace
bytes in 111,301 records over 6,144 hops), 616,800 minimum arrays containing NaN,
signed zero, infinity, subnormal and random bit patterns, and the scalar-versus-NEON
differential test of every kernel. The gate compares two builds of the same source
tree. "Identical" means identical bits except the payload bits of a NaN result; the
streams hold no NaN input, and the kernel differential test counts a NaN result that
differs only in its payload separately. With `SIMD=0` both builds of the stream test run
the scalar twins and the differential test has no vector twin, so those configurations do
not test the scalar twins against anything; a scalar-twin change needs the before/after
stream-hash comparison described in the optimization page.

## Regression suites

Configuration, reconfiguration, noise restart, scene change, C++ header compilation and
Python/C configuration parity are separate make targets. The Python/C gain comparison
is a numerical parity check on float32 gains (absolute error statistics), not
Python/C bit-exactness.

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

- Cost figures ([anr_optimization.md](anr_optimization.md)) are host measurements on
  Apple M4 with NE10; they are not embedded-board, whole-pipeline or other-compiler
  results. Embedded cycle counts are not covered.
- Bit-exactness (except the payload bits of a NaN result) is established between builds of
  the same source tree with the NE10 FFT backend.
- The Python reference and the C library agree numerically, not bitwise.
- The digital-silence stimuli are synthetic (speech-like harmonic bursts, coloured noise,
  a weak tone); they do not cover recorded material.
- The unity-gain initialization window is not suppressed: a click inside it passes
  unprocessed.
