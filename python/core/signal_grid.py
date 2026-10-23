"""Project-wide no-padding STFT grid selection for traditional NR."""

from __future__ import annotations

import math
from typing import Optional, Tuple


# 8 kHz is supported here and by the mono pipeline; the 4-channel pipeline accepts only
# 16 kHz/256, 16 kHz/512 and 48 kHz/1024.
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

# The 16 ms anchor is a real duration, independent of the default grid. Constants tuned at a
# 16 ms hop pass authored_hop_seconds=_SIXTEEN_MS_HOP_SECONDS so that grid is their no-op point.
_SIXTEEN_MS_HOP_SECONDS = 0.016


def retime_ema_alpha(
    alpha_at_10ms: float,
    sample_rate: int,
    hop_size: int,
    authored_hop_seconds: float = _REFERENCE_HOP_SECONDS,
) -> float:
    """Preserves an EMA time constant on this grid: alpha ** (hop / sr / authored_hop_seconds)."""
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
    """Converts a frame count authored at authored_hop_seconds per frame to a no-shorter duration."""
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
    """Returns (frame_size, hop_size, fft_size) for an allowed grid.

    Frame equals FFT and hop is half a frame, so the transform input is never padded. Defaults:
    128 @ 8 kHz, 256 @ 16 kHz, 1024 @ 48 kHz; 256 @ 8 kHz and 512 @ 16 kHz are explicit alternates.
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
    """Raises ValueError unless all dimensions match the project grid."""

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
