# ANR bit-exact optimization

This release keeps the processing and presets of the preceding release. It renames the C
API and source/archive files to ANR, moves Python reference code into `python/`,
and accelerates two existing C operations. See [migration](anr_migration.md).

MCRA retains the frequency-major minimum ring. Its NEON rescan preserves scalar
NaN and first-on-tie behavior, including signed zero. Full-mode final gain uses
the existing batch exponential kernel and scratch storage with the same clamps
and non-fused floating-point order. No additional state, allocation or delay is
introduced. The main source uses an inline gain block; the separately maintained
Audio_ALG copy uses a private helper selected against its own original source.

| Grid | Main full C core time reduction | Main stationary time increase |
|---|---:|---:|
| 16k, FFT256, hop128 | 6.687% | 0.204% |
| 16k, FFT512, hop256 | 7.729% | 0.799% |
| 48k, FFT1024, hop512 | 6.983% | 0.341% |

Full remains the default; stationary is opt-in. Measurements use Apple M4,
NE10, clang O2 and strict FP flags. Four alternating pairs each repeat the same
frozen development spectra pool 150 times. They cover the frequency-domain C
core and spectrum power, excluding caller FFT/window/OLA, initialization and
I/O. These are host measurements, not embedded-board or whole-pipeline results.
Validation scope and the list of evidence files kept outside the repository
are in [anr_validation.md](anr_validation.md).

The selected implementation matches the preceding release for all 523,882,912 trace bytes over
38,456 hops. End-to-end WAV checks cover 384 configurations, comparing preceding/new
and heap/static output bytes within the same backend. The formal test also
checks deep intermediate state and 514,000 minimum arrays containing NaNs,
signed zero, infinities, subnormals and random bit patterns. C++ API, configuration,
reconfiguration, silence restart and scene-change regressions pass. Python/C
gain comparisons are numerical parity checks, not Python/C bit-exactness.

From `c_impl/`, run:

```sh
make BACKEND=ne10 SIMD=1 WERROR=1 all lib mem parity test-config test-reconfigure test-noise-restart test-scene-change test-config-parity test-api-cpp test-bit-exact
make BACKEND=kiss SIMD=0 WERROR=1 test-bit-exact
```

Repeat the bit-exact target for both backends and SIMD settings when modifying
these kernels. Keep `-ffp-contract=off`; reassociation/fast-math is outside this
contract. The test script uses the production optimization definitions and an
independent scalar final-gain/minimum reference. Its current target does not
forward arbitrary DEBUG or EXTRA_CFLAGS into the reference test build.

The historical silence-restart defect was already fixed by BASE ancestor
`8086ae5`. Current C regression reports identical steady tone gain (0.1246)
with and without five seconds of leading digital silence at 16k/48k. Streaming
reset remains caller-controlled at a new stream or discontinuity. Existing
scene-change adaptation is retained; no current evidence connects the recent
naturalness observations to a reset defect. A recorded counterexample is needed
before changing that behavior.
