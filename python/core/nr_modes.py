"""
NR content-preservation MODE presets.

Orthogonal to the C `config_for_mode` STRENGTH axis (MILD/BALANCED/AGGRESSIVE) — this is the
CONTENT-preservation axis, currently a single preset:

  full  current behaviour: removes noise AND noise-like content (incl. sustained music).
        Empty overlay → byte-identical to the shipped V3-2.

`apply_mode(params, mode)` overlays a preset onto the constructor-param dict built by
`process_audio.create_denoiser_from_config` (V3-2 branch).
"""

from copy import deepcopy

NR_MODE_PRESETS = {
    # current behaviour — nothing overlaid → byte-identical shipped V3-2
    'full': {},
}


def apply_mode(params: dict, mode: str) -> dict:
    """Return a copy of `params` with the NR mode preset overlaid.

    'full' → unchanged (empty overlay → byte-identical). Unknown mode → ValueError.
    """
    if mode not in NR_MODE_PRESETS:
        raise ValueError(
            f"unknown NR mode {mode!r}; expected one of {sorted(NR_MODE_PRESETS)}"
        )
    out = deepcopy(params)
    out.update(NR_MODE_PRESETS[mode])
    return out
