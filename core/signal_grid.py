"""Project-wide no-padding STFT grid selection for traditional NR."""

from __future__ import annotations

import math
from typing import Optional, Tuple


# 8000 is fully supported by this standalone library and by the Audio_ALG
# MONO pipeline (audio_pipeline.c accepts/tests it as a 4th grid -- see
# Audio_ALG/pipelines/README.md "Parameter Alignment"). It is NOT supported
# by the Audio_ALG 4-CHANNEL pipeline, whose public API contracts to
# exactly three grids: 16 kHz/256, 16 kHz/512, 48 kHz/1024 (see
# Audio_ALG/pipelines/4ch_aec_bf_nr_res/README.md and 4aec_nr_res.c's explicit
# sample_rate check). Callers targeting the 4-channel pipeline specifically
# should not construct an NR instance at 8 kHz even though this table
# allows it.
_ALLOWED_FFTS = {
    8000: (128, 256),
    16000: (256, 512),
    48000: (1024,),
}

_DEFAULT_FFT = {
    8000: 128,
    16000: 256,
    48000: 1024,
}

_REFERENCE_HOP_SECONDS = 0.010

# The 16ms-hop grid (512 frame @ 16 kHz / 256 frame @ 8 kHz) was the project
# default from 2026-03-09 (commit 04edc42) through 2026-08-02, when the
# low-latency 8ms-hop grid (256 frame @ 16 kHz / 128 frame @ 8 kHz) became
# the default instead (16ms grids remain supported, explicit alternates).
# This flip does NOT change which grid is the "16ms anchor" for retiming
# purposes -- that anchor is a real-world duration (16ms), independent of
# whichever grid `_DEFAULT_FFT` currently points at. Several V3-2 preset
# values were added or last-tuned against a genuine 16ms hop (e.g. alpha_xi
# 0.88->0.92, commit 6822129, 2026-07-10, a musical-noise fix validated with
# a 12-file PESQ guard at the live 16ms grid; L=32, config/v3_2_config.yaml's
# "32 幀 x 16ms/hop = 512ms" comment) -- retiming those from the 10ms
# reference instead would silently undo the tuning (e.g. alpha_xi 0.92 ->
# ~0.875 at a 16ms-hop grid). Callers pass this as `authored_hop_seconds`
# for any constant proven (by commit date + message, or an explicit YAML
# comment) to be 16ms-native; the retime functions then treat WHICHEVER
# grid actually has a 16ms hop as the no-op point for that constant, and
# rescale every other grid (now including the 8ms-hop default) relative to
# that 16ms anchor.
_SIXTEEN_MS_HOP_SECONDS = 0.016


def retime_ema_alpha(
    alpha_at_10ms: float,
    sample_rate: int,
    hop_size: int,
    authored_hop_seconds: float = _REFERENCE_HOP_SECONDS,
) -> float:
    """Preserve an EMA's wall-clock time constant on a non-authored-rate grid.

    Existing NR presets were tuned with one update every ``authored_hop_seconds``
    (10 ms unless the caller states otherwise -- see ``_SIXTEEN_MS_HOP_SECONDS``
    for constants proven 16ms-native by git history). With a hop of ``H``
    samples, ``alpha_new = alpha_ref ** (H / sr / authored_hop_seconds)`` gives
    the same decay after any fixed amount of real time.
    """
    alpha = float(alpha_at_10ms)
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"EMA alpha must be in [0, 1], got {alpha}")
    if sample_rate <= 0 or hop_size <= 0:
        raise ValueError("sample_rate and hop_size must be positive")
    exponent = (hop_size / sample_rate) / authored_hop_seconds
    return float(alpha ** exponent)


def retime_frame_count(
    frames_at_10ms: int,
    sample_rate: int,
    hop_size: int,
    authored_hop_seconds: float = _REFERENCE_HOP_SECONDS,
) -> int:
    """Convert a legacy frame count (authored at ``authored_hop_seconds`` per
    frame) to a no-shorter real duration at the actual grid."""
    if frames_at_10ms <= 0:
        raise ValueError("reference frame count must be positive")
    if sample_rate <= 0 or hop_size <= 0:
        raise ValueError("sample_rate and hop_size must be positive")
    seconds = int(frames_at_10ms) * authored_hop_seconds
    return max(1, int(math.ceil(seconds * sample_rate / hop_size - 1e-12)))


def resolve_signal_grid(
    sample_rate: int,
    fft_size: Optional[int] = None,
) -> Tuple[int, int, int]:
    """Return ``(frame_size, hop_size, fft_size)`` for an allowed grid.

    The project contract is intentionally stricter than a generic STFT:
    frame equals FFT, hop is exactly half a frame, and the transform input is
    therefore never padded. 8/16 kHz each default to their low-latency
    8ms-hop grid (128/256); their 16ms-hop grid (256/512) remains a
    supported, explicit alternate.
    """

    if sample_rate not in _ALLOWED_FFTS:
        raise ValueError(
            f"unsupported sample_rate={sample_rate}; expected 8000, 16000, or 48000"
        )

    chosen = _DEFAULT_FFT[sample_rate] if fft_size is None else int(fft_size)
    if chosen not in _ALLOWED_FFTS[sample_rate]:
        allowed = "/".join(str(value) for value in _ALLOWED_FFTS[sample_rate])
        raise ValueError(
            f"unsupported fft_size={chosen} at {sample_rate} Hz; expected {allowed}"
        )

    return chosen, chosen // 2, chosen


def validate_signal_grid(
    sample_rate: int,
    frame_size: int,
    frame_shift: int,
    fft_size: int,
) -> None:
    """Raise ``ValueError`` unless all dimensions match the project grid."""

    expected_frame, expected_hop, expected_fft = resolve_signal_grid(
        sample_rate, fft_size
    )
    if (
        frame_size != expected_frame
        or frame_shift != expected_hop
        or fft_size != expected_fft
    ):
        raise ValueError(
            "no-padding grid required: frame_size == fft_size and "
            "frame_shift == frame_size/2; got "
            f"sr={sample_rate}, frame={frame_size}, hop={frame_shift}, fft={fft_size}"
        )
