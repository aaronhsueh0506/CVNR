"""
NR STRENGTH presets — suppression depth only.

Orthogonal to the CONTENT axis in `core/nr_modes.py` (`full` | `stationary`). This mirrors the C
`mmse_lsa_config_for_mode` (c_impl/include/mmse_lsa_types.h): `balanced` == the base
`config/v3_2_config.yaml` (empty overlay). Every preset shares the same DD,
noise tracker and gain dynamics; only the four depth controls below differ.

`apply_strength(params, strength)` overlays a preset onto the constructor-param dict built by
`process_audio.create_denoiser_from_config` (V3-2 branch). It is applied BEFORE `nr_modes.apply_mode`
so the content mode composes on top of the strength base — mirroring C's
`config_for_mode(strength)` then `apply_stationary()`.

The depth controls are `g_min_db`, fixed speech prior `q`, DD SNR floor
`xi_min_db`, and `noise_over_subtraction`. Time constants are deliberately not
allowed here: otherwise a stronger preset can leave more noise merely because
it changed the tracker/attack path.
"""

from copy import deepcopy

NR_STRENGTH_PRESETS = {
    # Gentler depth: preserve more detail and leave more background noise.
    'mild': {
        'g_min_db': -20.0,
        'q': 0.58,
        'xi_min_db': -10.0,
        'noise_over_subtraction': 1.2,
    },
    # Intermediate depth between mild and balanced.
    'moderate': {
        'g_min_db': -23.0,
        'q': 0.54,
        'xi_min_db': -10.0,
        'noise_over_subtraction': 1.3,
    },
    # Base YAML is the balanced anchor.
    'balanced': {},
    'aggressive': {
        'g_min_db': -28.0,
        'q': 0.45,
        'xi_min_db': -12.0,
        'noise_over_subtraction': 1.3,
    },
}


def apply_strength(params: dict, strength: str) -> dict:
    """Return a copy of `params` with the NR strength preset overlaid.

    'balanced' → unchanged (empty overlay == base config). Unknown strength → ValueError.
    """
    if strength not in NR_STRENGTH_PRESETS:
        raise ValueError(
            f"unknown NR strength {strength!r}; expected one of {sorted(NR_STRENGTH_PRESETS)}"
        )
    out = deepcopy(params)
    out.update(NR_STRENGTH_PRESETS[strength])
    return out
