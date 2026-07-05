"""
NR content-preservation MODE presets (`full` | `stationary`).

Orthogonal to the C `config_for_mode` STRENGTH axis (MILD/BALANCED/AGGRESSIVE) — this is a
CONTENT-preservation axis:

  full        current aggressive behaviour: removes noise AND noise-like content (incl.
              sustained music). Empty overlay → byte-identical to the shipped V3-2.
  stationary  ReSpeaker-like: remove ONLY the stationary noise floor, preserve all
              non-stationary content (speech / music / transients). Realised by the Wiener
              gain lower-bound (see MmseLsaGainCalculator.stationary_floor) plus a slower
              noise update (so music isn't absorbed into the floor) and a music-aware
              scene-change (tonal veto).

`apply_mode(params, mode)` overlays a preset onto the constructor-param dict built by
`process_audio.create_denoiser_from_config` (V3-2 branch). It is also the seam for a future
AUTO content detector: the detector picks `mode` per-utterance and calls `apply_mode`; nothing
else needs to change.

The keys below are MmseLsaDenoiser constructor kwargs. `alpha_noise` is the mcra noise-update
rate (`alpha_d`); `stationary_floor*` and `scene_change_tonal_veto`/`scene_change_lo_flatness_max`
are the new mode levers (all default-off so `full` is untouched).
"""

from copy import deepcopy

NR_MODE_PRESETS = {
    # current behaviour — nothing overlaid → byte-identical shipped V3-2
    'full': {},
    # ReSpeaker-like stationary-only suppressor
    'stationary': {
        # the mechanism: Wiener gain lower-bound (ξ/(β+ξ))^p — removes exactly the stationary floor
        'stationary_floor': True,
        # p=2.0: pure Wiener (p=1) leaves the noise's own SNR fluctuations under-suppressed
        # (measured atten only ~−7 dB); p=2 deepens noise removal to ~−10..−14 dB while music
        # retention stays ~0 (harness sweep). Tunable.
        'stationary_floor_exponent': 2.0,
        'stationary_floor_beta': 1.0,        # remove exactly N
        # residual-noise depth is set by xi_min (NOT g_min); leave natural comfort noise
        'xi_min_db': -22.0,
        'alpha_xi': 0.92,                    # steadier ξ → steadier bound
        'g_min_db': -30.0,                   # amplitude dB (/20); = old -15 @ /10, mostly inert under the bound
        # keep N an honest STATIONARY floor: slow the posterior-gated recursive average so
        # music phrases aren't absorbed (which would collapse ξ and defeat the bound)
        'alpha_noise': 0.95,
        # music-aware scene-change: percussion can't confirm; tonal (music) low band is vetoed
        'scene_change_min_frames': 30,
        'scene_change_flatness_threshold': 0.6,
        'scene_change_tonal_veto': True,
        'scene_change_lo_flatness_max': 0.4,
    },
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
