# Python reference

The readable NR implementation, WAV CLI, tools, tests and YAML configuration
are grouped here. Python retains its MMSE-LSA/OMLSA algorithm names; the C API
is ANR. See [repository usage](../README.md) and the
[migration guide](../docs/anr_migration.md).

Run from the repository root:

```bash
python3 -m pip install -r python/requirements-dev.txt
python3 python/process_audio.py input.wav --versions V3-2 --nr-mode balanced
PYTHONPATH=python python3 -c "from denoisers import MmseLsaDenoiser"
python3 -m pytest
```

`config/` holds Python-only YAML. C presets are in
`../c_impl/include/anr_types.h`. Datasets and generated research outputs are
kept in `../test_wav/` and `../results/`; repository-aware tools resolve those
paths independently of this directory.

## Stationary mode

`python/core/nr_modes.py` keeps the `stationary` content-preservation mode
(Wiener gain lower bound plus a tonal scene-reset veto). The C library has no
stationary mode: `anr_apply_stationary()`, the `stationary_floor*` and
`scene_change_tonal_veto` configuration fields and the `--stationary` command
line flags are not part of the C API. Python/C parity checks therefore cover
the `full` mode only, and `tools/parity_nr.py dump` accepts only `--mode full`.
