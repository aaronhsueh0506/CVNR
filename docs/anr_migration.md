# C ANR API naming and Python layout

The C noise-reduction library is named by its function, **ANR** (adaptive
noise reduction), not by its gain-estimation algorithm. The Python reference
keeps its algorithm names (`MmseLsaDenoiser`, `McraNoiseEstimator`,
`MmseLsaGainCalculator`, `SppEstimator`). Algorithm descriptions name the
MMSE-LSA/OMLSA gain and MCRA/SPP components for technical accuracy.

| Item | C name |
|---|---|
| Public headers | `include/anr.h`, `include/anr_types.h` |
| Sources | `src/anr.c`, `src/anr_internal.h` |
| Archive | `libanr.a`, linked with the matching `libaudio_common.a` |
| Types | `AnrDenoiser`, `AnrConfig`, `AnrMode`, `AnrDebugStatus` |
| Functions | `anr_*` |
| Strength constants | `ANR_MODE_*` |
| Other constants | `ANR_*` |

```c
#include "anr.h"

AnrConfig cfg = anr_config_for_mode_grid(16000, 256, ANR_MODE_BALANCED);
AnrDenoiser *nr = anr_create(&cfg);
/* Check nr before processing; spectrum contains cfg.fft_size / 2 + 1 bins. */
anr_process(nr, spectrum, spectrum);
anr_destroy(nr);
```

Both C runners, the C regression tests and the Python/C parity tooling use
this API. Select build artifacts through the Makefile query targets
(`print-lib-path`, `print-bin-dir`) or a release manifest, not by guessing a
`bin/` path.

## Python directory layout

Python implementation, tools, tests, YAML configuration and requirements live
under `python/`, matching the adjacent AEC repository layout. The repository
root holds `c_impl/`, `docs/` and `test_wav/`; benchmark tools write generated
outputs to `results/`.

| Path | Content |
|---|---|
| `python/process_audio.py` | WAV CLI |
| `python/core/`, `python/denoisers/`, `python/utils/` | reference implementation |
| `python/tools/`, `python/tests/` | tools and tests |
| `python/config/` | YAML configuration |
| `python/requirements*.txt` | dependencies |

From the repository root:

```bash
python3 -m pip install -r python/requirements-dev.txt
python3 python/process_audio.py input.wav --versions V3-2 --nr-mode balanced
PYTHONPATH=python python3 -c "from denoisers import MmseLsaDenoiser"
python3 -m pytest
python3 python/tools/parity_nr.py --help
```

The WAV CLI and parity tool resolve default configuration beside the Python
tree independently of the working directory. Benchmark tools distinguish the
repository root (Git identity, datasets and results) from its Python directory
(module imports and YAML). `pytest.ini` resolves imports and test discovery
when invoked at the repository root.
