"""
NR STRENGTH presets (`mild` | `balanced` | `aggressive`) — the suppression-DEPTH axis.

Orthogonal to the CONTENT axis in `core/nr_modes.py` (`full` | `stationary`). This mirrors the C
`mmse_lsa_config_for_mode` (c_impl/include/mmse_lsa_types.h): `balanced` == the base
`config/v3_2_config.yaml` (empty overlay); `mild` / `aggressive` overlay depth + smoothing deltas.

`apply_strength(params, strength)` overlays a preset onto the constructor-param dict built by
`process_audio.create_denoiser_from_config` (V3-2 branch). It is applied BEFORE `nr_modes.apply_mode`
so the content mode composes on top of the strength base — mirroring C's
`config_for_mode(strength)` then `apply_stationary()`.

Musical-noise fix (2026-07): the shared DD ξ-smoothing lever `alpha_xi=0.92` lives in the base YAML
(and the C `mmse_lsa_default_config`), so ALL three presets inherit it. Higher alpha_xi damps ξ
jitter → SPP jitter → the isolated per-bin gain peaks that are musical noise (root cause: SPP is the
exponent in G = G_H1^spp · g_min^(1-spp), and its only temporal memory is ξ). Deeper presets also
carry more downstream gain-smoothing (alpha_g / alpha_decay), because audible peak height scales as
|log g_min| · Δspp — a deeper floor re-exposes any residual jitter.

Keys below are MmseLsaDenoiser constructor kwargs (`alpha_noise` == the MCRA noise-update rate
`alpha_d`). Values mirror C config_for_mode; alpha_xi is intentionally NOT set here (inherited from
the base, shared across presets). Depth of `mild` / `aggressive` is tuned empirically via
`tools/ablate_nr_music.py`; `balanced` is the ear-locked anchor.
"""

from copy import deepcopy

NR_STRENGTH_PRESETS = {
    # gentler: preserve speech detail, less noise removed (user note: currently under-denoises;
    # deepen via the ablation harness if desired)
    'mild': {
        'g_min_db': -20.0,       # amplitude dB (/20) → 0.10 floor (gentler than balanced 0.032)
        'q': 0.6,
        'xi_min_db': -15.0,
        'alpha_noise': 0.85,     # slower noise tracking
        'alpha_g': 0.92,         # more downstream gain smoothing
        'alpha_attack': 0.4,
        'alpha_decay': 0.92,
    },
    # between mild and balanced (user request 2026-07): mild's gentle smoothing, depth midway
    # (g_min −25, q 0.55, xi_min −18). For when mild under-denoises but balanced is too strong.
    'moderate': {
        'g_min_db': -25.0,       # amplitude dB (/20) → 0.056 floor (mild −20 ↔ balanced −30)
        'q': 0.55,
        'xi_min_db': -18.0,
        'alpha_noise': 0.85,
        'alpha_g': 0.92,
        'alpha_attack': 0.4,
        'alpha_decay': 0.92,
    },
    # ear-locked anchor (user-confirmed 2026-07): == base YAML (alpha_xi=0.92), EMPTY overlay.
    # This is the `only_alpha_xi` set. The alpha_xi 0.88→0.92 fix is the whole musical-noise win
    # (MN 0.067→0.061, −9%) and is essentially free on speech (PESQ −0.001 on the 12-file guard).
    # The extra attack/decay smoothing (`only_alpha_xi_and_smoothing`) was DROPPED: it bought only
    # −4% more MN but cost the speech regression (PESQ −0.021 / segSNR −0.38) and sounded the same
    # by ear — a bad trade on the default preset. Bonus: stationary mode (which overrides alpha_xi
    # to 0.92 already) is now completely undisturbed.
    'balanced': {},
    # deepest suppression; carries the most downstream smoothing to hold musical noise down at depth
    # (= the ablation's `aggressive_smooth`: alpha_g 0.75→0.85 / decay 0.85→0.88 vs the C-mirror,
    # trading ~0.2 dB depth for less speckle at the −40 dB floor).
    'aggressive': {
        'g_min_db': -40.0,       # amplitude dB (/20) → 0.01 floor
        'q': 0.35,
        'xi_min_db': -25.0,
        'alpha_noise': 0.5,      # faster noise tracking
        'alpha_g': 0.85,         # more downstream smoothing than the C-mirror 0.75 (musical-noise)
        'alpha_attack': 0.15,
        'alpha_decay': 0.88,
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
