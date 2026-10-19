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
