"""
Utility modules for audio I/O, metrics, and visualization.
"""

from .audio_io import read_audio, write_audio, normalize_audio

__all__ = [
    'read_audio', 'write_audio', 'normalize_audio',
    'plot_spp_spectrogram', 'plot_spp_comparison'
]

# matplotlib is optional: the two plotting functions are imported on first access (PEP 562).
def __getattr__(name):
    if name in ('plot_spp_spectrogram', 'plot_spp_comparison'):
        from . import visualization
        return getattr(visualization, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
