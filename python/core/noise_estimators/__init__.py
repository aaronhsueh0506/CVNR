"""Noise estimators."""

from .simple_average import SimpleAverageNoiseEstimator
from .recursive_average import RecursiveAverageNoiseEstimator
from .mcra import McraNoiseEstimator

# IMCRA is McraNoiseEstimator with accept_external_spp=True (the default).
ImcraNoiseEstimator = McraNoiseEstimator

__all__ = [
    'SimpleAverageNoiseEstimator',
    'RecursiveAverageNoiseEstimator',
    'McraNoiseEstimator',
    'ImcraNoiseEstimator',
]
