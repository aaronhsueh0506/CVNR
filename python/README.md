# Python reference

The readable NR implementation, WAV CLI, tools, tests and YAML configuration
are grouped here. Python retains its MMSE-LSA/OMLSA algorithm names; the C API
is ANR. See [repository usage](../README.md) and
[C API naming and Python layout](../docs/anr_migration.md).

Run from the repository root:

```bash
python3 -m pip install -r python/requirements-dev.txt
python3 python/process_audio.py input.wav --versions V3-2 --nr-mode balanced
PYTHONPATH=python python3 -c "from denoisers import MmseLsaDenoiser"
python3 -m pytest
```

`config/` holds Python-only YAML. C presets are in
`../c_impl/include/anr_types.h`. Audio fixtures are in `../test_wav/` and
benchmark outputs go to `../results/`; repository-aware tools resolve those
paths independently of this directory.


## Evaluate WAV output

The VCTK runner renders audio from the NR reference. To score audio already rendered by another model, keep the same relative WAV names under each input directory and supply aligned signals.

```sh
python3 python/tools/run_vctk_benchmark.py --mode full --strength balanced --output results/vctk_candidate.json
python3 python/tools/score_wav_directories.py --clean-dir clean --enhanced-dir enhanced --noisy-dir noisy --output-dir results/model
```

The scorer resamples each signal to 16 kHz before checking lengths and writes aggregate and per-file metrics. See the [metrics reference](../docs/reference/metrics.md) and [Python variant comparison](../docs/reference/python_variants.md).
