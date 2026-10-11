# ANR validation summary

This page records what was verified for the C API rename to ANR and the bit-exact
kernel changes (batched final-gain exponential and NEON kernels for the MCRA
minimum ring, inert-bin restart, SPP decision-directed pass and gain stages), what
the verification does not cover, and which evidence files were kept out of the
repository.

## What was verified

Numbers in this section were recorded by the evidence files listed below; the
repository tests reproduce the bit-exact claims on demand (see
[ANR bit-exact optimization](anr_optimization.md)).

- **Four-way bit-exact stream.** For FFT backend kiss and NE10, each with
  `SIMD=0` and `SIMD=1`, the optimized build and an independent scalar
  reference build (`-DANR_REFERENCE_KERNELS`) produce identical state and
  gain traces: 164,236,480 trace bytes (111,301 records) over 6,144 hops, plus
  616,800 minimum arrays containing NaN, signed zero, infinity, subnormal and
  random bit patterns, plus the scalar-versus-NEON differential test of every
  kernel. `make test-bit-exact` runs this gate; it compares two builds of the
  same source tree, per backend. The two FFT backends are not claimed to be
  bit-exact with each other.
- **WAV byte equality.** 384 end-to-end configurations (12 input files, four
  strengths, the stationary overlay on/off, four backend/SIMD builds) give
  output WAV files byte-equal to the release before the rename, and heap and
  static allocation give byte-equal output, always within the same backend. The
  stationary overlay was recorded in this matrix and is not part of the C
  library any more; the 192 configurations without it remain applicable.
- **Regression suites.** Configuration, reconfiguration, noise restart,
  scene change, C++ header compilation and Python/C configuration parity pass.
- **Python/C gain comparison** is a numerical parity check on float32 gains
  (absolute error statistics), not Python/C bit-exactness.

## Digital-silence frames

Frames whose bins are all exactly zero do not count toward noise initialization
and do not advance the noise tracker.

- A 1 kHz tone (10 s) that follows 5 s of exact zeros converges to the same gain
  as the same tone without leading silence, within 0.07 dB, at 16 kHz/FFT 256,
  16 kHz/FFT 512 and 48 kHz/FFT 1024 in the balanced and aggressive modes, and
  reaches -6 dB 0.192 s after the tone starts, within one 64 ms block of the
  control (0.192 s). Without the change the converged gain stays at
  -1.9 / -0.2 / -0.02 dB against -18.1 dB for the control.
- Noise that follows 5 s of digital silence starts like a cold start after the
  change. The output stays below -6 dB from 0.192 s after the noise starts
  (control without silence: 0.19-0.26 s) and is within 3 dB of its converged
  level from 0.26-0.58 s (control: 0.26-0.45 s). Before the change it stayed
  below -6 dB from 0.064-0.128 s, so the first -6 dB is reached later with the
  change, while the output was within 3 dB of the converged level only from
  0.58-1.73 s.
- Streams without any all-zero frame produce byte-identical WAV output: 48 of
  48 configurations for each of three such stimuli (speech-like noise with a
  weak tone, and two stimuli whose digital silence is replaced by +-1 LSB
  noise). Per-hop state streams match bit for bit when the all-zero stretch of
  the stream is replaced by a very low level signal.
- Streams that do contain all-zero frames change by design. In a speech-like
  noise stream with isolated zero stretches of 20, 60 and 150 ms, the output
  in the 100 ms blocks that follow the longest stretch is up to 4.4 dB quieter
  than before the change (deeper noise suppression; worst case 16 kHz/FFT 512,
  aggressive mode). The last two seconds differ by less than 0.01 dB.
  Compared with the output of the same stream without any stretch (probe at
  16 kHz/FFT 512, aggressive mode; the longest stretch ends at 7.65 s):
  - The first 100 ms block after the stretch (7.6-7.7 s) is 4.1 dB below it
    with the change (-70.7 against -66.6 dBFS) and 0.4 dB above it before the
    change. This block holds the 4.4 dB worst case. About 3 dB of that gap comes
    from the last 50 ms of the stretch inside the block, whose output is
    below -100 dBFS; over the 50 ms after the stretch the output with the change
    is 1.1 dB below.
    The balanced mode shows the same block about 4 dB low both before (-3.7 dB)
    and after (-4.1 dB) the change.
  - From the second block on (7.7-8.0 s) the output with the change matches it
    within 0.3 dB; before the change it was up to 3.7 dB higher.
- `make test-noise-restart` fails without the change (initialization on
  silence, the noise floor moving across silence, and a tone whose first frame
  is a reduced-power onset) and passes with it.

## Stationary mode removal

The C library has no stationary content mode. With the default configuration
the output is unchanged by the removal: the per-hop state and output stream
of all configurations that do not use the stationary mode is bit-identical
before and after on both FFT backends and both SIMD settings (97,354 records
of 97,354 for the unmodified stream, 97,375 of 97,375 with the zero stretch
replaced), and 144 end-to-end WAV configurations (six stimuli, three grids,
balanced and aggressive, four builds) give byte-identical files. A deliberate
1-ulp change in one gain bin is detected by the stream comparison in all eight
runs (two streams, four builds) and by the WAV comparison in 45 of 48 runs
(two stimuli, three grids, two modes, four builds); the other three outputs are
equal after 16-bit quantisation, so the WAV comparison is the weaker of the
two. The instance size shrinks by 48 bytes per instance (`anr_get_mem_size` 58,304 to
58,256 bytes at 16 kHz/FFT 256, 69,856 to 69,808 at 16 kHz/FFT 512, 183,616 to
183,568 at 48 kHz/FFT 1024) and `AnrConfig` from 180 to 160 bytes. Per-hop cost
shows no consistent change: over six grid/mode cells (Apple M4, NE10, frozen
spectra of a speech-like stimulus, 12 alternating pairs) the median pair ratio
ranges from -1.4 % to +6.2 % with no consistent sign and the best-of-run ratio
from -3.1 % to +3.0 %. The measurement cannot resolve differences below about
3 %; the removed code was a branch that is false in every default run.

## Cost

Apple M4, NE10 backend, clang -O2 with the strict FP flags; `make bench-anr`
measures the frequency-domain C core (`anr_process()` and `anr_process_gain()`),
excluding the caller's FFT, window, overlap-add, initialization and I/O. Twelve
alternating runs of the scalar-twin build and the NEON build, each run the median
of 30 passes of 600 hops, give a median reduction of 36.6 % to 42.7 % per hop over
the three grids and two strengths; the per-cell figures are in
[anr_optimization.md](anr_optimization.md).

## Scope limits

- Cost figures are host measurements on Apple M4 with NE10; they are not
  embedded-board, whole-pipeline or other-compiler results. Embedded cycle
  counts are not covered.
- Bit-exactness is established between builds of one backend. The kiss and
  NE10 outputs are separate references.
- The WAV matrix uses 12 development input files and covers only the listed
  strengths and options; it does not prove equality for other inputs.
- The Python reference and the C library agree numerically, not bitwise.
- The stimuli used for the digital-silence and stationary-removal comparisons are
  synthetic (speech-like harmonic bursts, coloured noise, a weak tone); they do
  not cover recorded material.
- Algorithms, presets, state geometry, memory size and latency are unchanged by
  the rename and the kernels.

## Evidence files kept outside the repository

The following 33 files (345,696 bytes in total) hold the raw measurements,
manifests and decision records behind this page. They are not part of the
repository because they contain local paths and bulky traces. The sha256 below
identifies each file so that a copy held elsewhere can be matched.

| File | Bytes | sha256 |
|---|---:|---|
| `BOARD_LEVEL_AND_SPECTRUM.json` | 16730 | `f173d872d80f23d303e98275ceaa3bfb52232999660f5cc4eb237373eacb8a6e` |
| `LEVEL_MATCH_MANIFEST.json` | 3303 | `ec13339a8a388b2ae46ed0222391db88cbff7673070d030d6aab8bcfd5c03464` |
| `LOCAL_ARTIFACTS.json` | 1060 | `5c2a8ae3016586e8bc824733e99f30ae1c9f818b1e37dc0e0068bba48e00faba` |
| `NR_CONDITIONED_ROUND_SUMMARY.json` | 52986 | `c95ef458b024be0605ea97a155ee70da3c814bb2dad0037609a95b636d43c0d0` |
| `NR_COST_ASSESSMENT.txt` | 1999 | `e6fd0b522c21e8044a2ca22c7145e69a2aafa31227a1b563d45f408397f34716` |
| `NR_C_COST_ASSESSMENT.json` | 2470 | `235f67c8f4fac970bf9d70cd8eaae52e4dbda1f566898246fb45eb4034f3465c` |
| `NR_C_KERNEL_COST.json` | 8244 | `a8883470b15f5d9067e27f141038ff09dc92ce7a8d6f39d604d366d074d45fc4` |
| `NR_C_KERNEL_NE10.csv` | 1245 | `be34a95060b9f4d17f3956b058b4f896ab1458ad1b9900148d6c9fd93fe2bd93` |
| `NR_C_PROFILE_INPUTS.json` | 2504 | `7ec309630da27a39d0e30037e67b3fa07c16d88db8530189568c2112f898e268` |
| `NR_C_PROFILE_NE10.csv` | 412 | `5efa2b583f04e0adac33d83a8bd9a5ba49fb81b39b849e3fd17fe6a4ba7e40c4` |
| `NR_RETAIN_BASE_DECISION.json` | 1097 | `be8d2ea511309225fcb38e8b02ba42fc6998abef03fe34b79be09d4a85e2a6c2` |
| `README.md` | 5209 | `7dfd2d862f762a6f651c2e70fe06b88c47235598a23b75ef01c425213c2500e2` |
| `REVISION_58.txt` | 1879 | `55670289f11ec0998d1a05509ef2eba9d76ab61c7d874c91538e8a1d87be657a` |
| `REVISION_59.txt` | 1244 | `39b115d9038e4a11e67f727fffee8781b0dce19fb1aeba5d0ec7b1680602befd` |
| `SOURCE_MANIFEST.json` | 4462 | `f17af9e6e9384f0ec7756a8495b9de4f75a73706ffdeaf3420d7749777060a6f` |
| `SPECTROGRAM_MANIFEST.json` | 20649 | `dfd42db5034e883390d5cbf98d50e59cb7052182c305fc5be78037bcd869ac21` |
| `WEBRTC_MANIFEST.json` | 8617 | `14ce9eb4276909908f8dda6b4377d8c6957539a0a625f5ed1913ce702efe5783` |
| `WEBRTC_NS_GAIN_ATTRIBUTION.json` | 1390 | `633c9d8d8f367ca3bcae55c3b9244b0e4bc4fee83f9f4b012b5e4f58cdb06ca3` |
| `anr_release/COMMENT_TOKENS.json` | 1614 | `3660743ab1a678b465a88d1a006d8cdb77979348ea3ddca2c672e69334025689` |
| `anr_release/CPP_HEADER_FIX.json` | 7440 | `119b2bc9ecd62cf1489f98701cbfa401241de7cc1b91d9fcf72c1f8afa6a586c` |
| `anr_release/FORMAL_PREVIOUS_LAYOUT.json` | 4643 | `8c888fc8324aa9e9ab1fe0ac577d9c561d297fbb65b8d9238bba554073a27d5b` |
| `anr_release/INLINE_TOKEN_EQUIVALENCE.json` | 151 | `f1f98fe7ecdbfc7780c761090361459bb4caf15daab443f0c52a3b44d625910c` |
| `anr_release/LIB_COST.json` | 10013 | `cb15404ff4f08ada7e0a90967d7dc515464a30ad16ee0c4491224e746450a16b` |
| `anr_release/LIB_FINAL_BITEXACT.json` | 5151 | `6be7874850108fb43202b824fe469992be618d6f874aa6a4c9041b8bc84c2840` |
| `anr_release/LIB_OBJECT_ASSOCIATION.json` | 739 | `5ee3eef1ee0959531c9f4e4fb76b6fc229edfded70d8118db132d279f57633b2` |
| `anr_release/MAIN_BUILD_METADATA.json` | 2855 | `5ac7b376d96f64e3c4820a7441899304f047c4c02701f9207433d14af2abeddd` |
| `anr_release/MAIN_COST.json` | 8991 | `2c4e5daa91cbf681c87e8f0655289e6482affb092da76cbea2467460d267bd29` |
| `anr_release/MAIN_SELECTED_LAYOUT.json` | 5919 | `74c1d3ddff0ebf3f87a1edbef56c4389d3abd846509fc90be896c823bcfdf9a1` |
| `anr_release/MAIN_VARIANT_BITEXACT.json` | 710 | `d95ebcacee137fa638681c5670b5d22621eadcadbb8c4c4b3bea73252f1b4d4a` |
| `anr_release/PYTHON_ALGORITHM_AST.json` | 8339 | `d8965e22f4755963bd83f4fe7a3d00769f8c5c3dbb0910720c72f6f42bd4beef` |
| `anr_release/PYTHON_C_PARITY.json` | 17828 | `c29917827e73a2d7d88bbcbd937c2831a6479b6ebed3a0abe33deff955c69ae5` |
| `anr_release/RELEASE_VALIDATION.json` | 15062 | `031516ca64fe7cfc018c745a81742f3d0d40b3fc44404bc1c3c65b8253500c18` |
| `anr_release/WAV_BITEXACT.json` | 120741 | `c71a6bf54adbf35581df03bf4c13157cfd0c56f70c2684149f33349ebc9f5bf6` |
