"""
NR content-preservation MODE.

Orthogonal to the C `config_for_mode` STRENGTH axis (MILD/BALANCED/AGGRESSIVE). This was
the CONTENT-preservation axis; the only mode that ever shipped is 'full' (removes noise
AND noise-like content, incl. sustained music) — the 'stationary' alternative was removed.
`mode` stays a recorded constant rather than being deleted outright because
`run_vctk_benchmark.py`'s `GRID_KEYS` writes it into every benchmark JSON record on disk,
and dropping the field would break comparability with existing baselines that recorded
`mode: stationary`.

`apply_mode(params, mode)` is called from `process_audio.create_denoiser_from_config`
(V3-2 branch); it validates the single accepted value and returns a copy of `params`.
"""

from copy import deepcopy


def apply_mode(params: dict, mode: str) -> dict:
    """Return a copy of `params`. The only mode is 'full'; anything else is a ValueError."""
    if mode != 'full':
        raise ValueError(f"unknown NR mode {mode!r}; expected 'full'")
    return deepcopy(params)
