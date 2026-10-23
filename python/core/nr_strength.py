"""NR strength presets (suppression depth only); values equal the C `anr_config_for_mode`.

'balanced' is the base config (empty overlay). Presets share the DD, noise-tracker and gain
dynamics and differ only in g_min_db, q, xi_min_db and noise_over_subtraction.
`apply_strength(params, strength)` overlays a preset on the constructor parameters.
"""

from copy import deepcopy

NR_STRENGTH_PRESETS = {
    'mild': {
        'g_min_db': -20.0,
        'q': 0.58,
        'xi_min_db': -10.0,
        'noise_over_subtraction': 1.2,
    },
    'moderate': {
        'g_min_db': -23.0,
        'q': 0.54,
        'xi_min_db': -10.0,
        'noise_over_subtraction': 1.3,
    },
    'balanced': {},
    'aggressive': {
        'g_min_db': -28.0,
        'q': 0.45,
        'xi_min_db': -12.0,
        'noise_over_subtraction': 1.3,
    },
}


# CLI index -> preset name, in AnrMode order (mild=0 ... aggressive=3).
_STRENGTH_BY_INDEX = {str(i): name for i, name in enumerate(NR_STRENGTH_PRESETS)}


def nr_strength_name(value: str) -> str:
    """argparse `type=`: map a strength index "0".."3" to its preset name; return any other value
    unchanged so the parser's `choices` check reports it."""
    return _STRENGTH_BY_INDEX.get(value, value)


def apply_strength(params: dict, strength: str) -> dict:
    """Return a copy of `params` with the preset overlaid; ValueError for an unknown strength."""
    if strength not in NR_STRENGTH_PRESETS:
        raise ValueError(
            f"unknown NR strength {strength!r}; expected one of {sorted(NR_STRENGTH_PRESETS)}"
        )
    out = deepcopy(params)
    out.update(NR_STRENGTH_PRESETS[strength])
    return out
