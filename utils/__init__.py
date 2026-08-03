"""
Utility modules for audio I/O, metrics, and visualization.
"""

from .audio_io import read_audio, write_audio, normalize_audio

__all__ = [
    'read_audio', 'write_audio', 'normalize_audio',
    'plot_spp_spectrogram', 'plot_spp_comparison'
]

# plot_spp_spectrogram/plot_spp_comparison pull in matplotlib (visualization.py),
# which is not a hard dependency of the package -- pytest auto-collects
# utils/test_data_generator.py, so an eager `from .visualization import ...`
# here made matplotlib mandatory just to run algorithm unit tests that never
# touch plotting. Deferred via module __getattr__ (PEP 562): only imported
# the first time a caller actually accesses one of these two names.
def __getattr__(name):
    if name in ('plot_spp_spectrogram', 'plot_spp_comparison'):
        from . import visualization
        return getattr(visualization, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
