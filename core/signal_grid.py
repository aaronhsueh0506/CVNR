"""Project-wide no-padding STFT grid selection for traditional NR."""

from __future__ import annotations

import math
from typing import Optional, Tuple


_ALLOWED_FFTS = {
    8000: (256,),
    16000: (256, 512),
    48000: (1024,),
}

_DEFAULT_FFT = {
    8000: 256,
    16000: 512,
    48000: 1024,
}

_REFERENCE_HOP_SECONDS = 0.010


def retime_ema_alpha(
    alpha_at_10ms: float,
    sample_rate: int,
    hop_size: int,
) -> float:
    """Preserve an EMA's wall-clock time constant on a non-10-ms grid.

    Existing NR presets were tuned with one update every 10 ms.  With a hop of
    ``H`` samples, ``alpha_new = alpha_10ms ** (H / sr / 10ms)`` gives the same
    decay after any fixed amount of real time.
    """
    alpha = float(alpha_at_10ms)
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"EMA alpha must be in [0, 1], got {alpha}")
    if sample_rate <= 0 or hop_size <= 0:
        raise ValueError("sample_rate and hop_size must be positive")
    exponent = (hop_size / sample_rate) / _REFERENCE_HOP_SECONDS
    return float(alpha ** exponent)


def retime_frame_count(
    frames_at_10ms: int,
    sample_rate: int,
    hop_size: int,
) -> int:
    """Convert a legacy 10-ms frame count to a no-shorter real duration."""
    if frames_at_10ms <= 0:
        raise ValueError("reference frame count must be positive")
    if sample_rate <= 0 or hop_size <= 0:
        raise ValueError("sample_rate and hop_size must be positive")
    seconds = int(frames_at_10ms) * _REFERENCE_HOP_SECONDS
    return max(1, int(math.ceil(seconds * sample_rate / hop_size - 1e-12)))


def resolve_signal_grid(
    sample_rate: int,
    fft_size: Optional[int] = None,
) -> Tuple[int, int, int]:
    """Return ``(frame_size, hop_size, fft_size)`` for an allowed grid.

    The project contract is intentionally stricter than a generic STFT:
    frame equals FFT, hop is exactly half a frame, and the transform input is
    therefore never padded. 16 kHz offers the low-latency 256 grid as an
    explicit option; 512 remains its default.
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
