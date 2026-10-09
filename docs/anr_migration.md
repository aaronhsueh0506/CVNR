# C ANR API migration

The C noise-reduction library now uses its function name, **ANR** (adaptive
noise reduction), rather than its gain-estimation algorithm in public names.
This is a complete source/API rename: the previous names and forwarding
wrappers are not provided. The Python reference retains its algorithm names.

| Previous C name | Current C name |
|---|---|
| `mmse_lsa_denoiser.h` | `anr.h` |
| `mmse_lsa_types.h` | `anr_types.h` |
| `src/mmse_lsa_denoiser.c` | `src/anr.c` |
| `src/mmse_lsa_internal.h` | `src/anr_internal.h` |
| `libmmse_lsa.a` | `libanr.a` |
| `mmse_lsa_*` functions | `anr_*` functions |
| `MmseLsaDenoiser` | `AnrDenoiser` |
| `MmseLsaConfig` | `AnrConfig` |
| `MmseLsaNrMode` | `AnrMode` |
| `MmseLsaDebugStatus` | `AnrDebugStatus` |
| `MMSE_LSA_NR_*` strength constants | `ANR_MODE_*` |
| Other `MMSE_LSA_*` constants | `ANR_*` |

Update includes, types, function calls, constants, source lists, and archive
link inputs together, then rebuild every consumer. Link `libanr.a` with the
matching `libaudio_common.a` as before. The frequency-domain API, struct
fields, supported grids, presets, memory ownership, and streaming semantics
are unchanged by this rename. Algorithm descriptions still identify the
MMSE-LSA/OMLSA gain and MCRA/SPP components for technical accuracy.

```c
#include "anr.h"

AnrConfig cfg = anr_config_for_mode_grid(16000, 256, ANR_MODE_BALANCED);
AnrDenoiser *nr = anr_create(&cfg);
/* Check nr before processing; spectrum contains cfg.fft_size / 2 + 1 bins. */
anr_process(nr, spectrum, spectrum);
anr_destroy(nr);
```

Both current C runners, C regression tests, and Python/C parity tooling use
the new API. Existing research results and archived documentation remain
historical records, so their old names describe the versions originally
measured. Select fresh artifacts through the Makefile query targets or a new
release manifest; an older build directory can still contain older artifacts.

## Removed stationary mode

The C library no longer provides the stationary content mode: `anr_apply_stationary()`,
the `AnrConfig` fields `stationary_floor`, `stationary_floor_exponent`,
`stationary_floor_beta`, `scene_change_tonal_veto` and `scene_change_lo_flatness_max`,
and the `--stationary` option of the example programs are gone. `AnrConfig` shrinks
from 180 to 160 bytes and `anr_get_mem_size()` by 48 bytes, so callers that build
`AnrConfig` field by field or size static pools from a fixed constant must be
rebuilt. The Python reference keeps its stationary mode.

## Python directory layout

Python implementation, tools, tests, YAML configuration and requirements now
live under `python/`, matching the adjacent AEC repository layout. Module and
class names remain unchanged. No Python algorithm is renamed. The repository
root retains `c_impl/`, `docs/`, `test_wav/` and `results/`.

| Previous path | Current path |
|---|---|
| `process_audio.py` | `python/process_audio.py` |
| `core/`, `denoisers/`, `utils/` | `python/core/`, `python/denoisers/`, `python/utils/` |
| `tools/`, `tests/` | `python/tools/`, `python/tests/` |
| `config/` | `python/config/` |
| `requirements*.txt` | `python/requirements*.txt` |

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
