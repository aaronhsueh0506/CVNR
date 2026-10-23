"""NR content-preservation mode. The only accepted value is 'full' (removes noise and
noise-like content); it is recorded in benchmark records.

`apply_mode(params, mode)` validates the mode and returns a copy of `params`.
"""

from copy import deepcopy


def apply_mode(params: dict, mode: str) -> dict:
    """Return a copy of `params`. The only mode is 'full'; anything else is a ValueError."""
    if mode != 'full':
        raise ValueError(f"unknown NR mode {mode!r}; expected 'full'")
    return deepcopy(params)
