"""
Noise Estimators - 噪聲估計器
"""

from .simple_average import SimpleAverageNoiseEstimator
from .recursive_average import RecursiveAverageNoiseEstimator
from .mcra import McraNoiseEstimator

# IMCRA (accept_external_spp=True) is the default mode; alias for clarity.
ImcraNoiseEstimator = McraNoiseEstimator

__all__ = [
    'SimpleAverageNoiseEstimator',
    'RecursiveAverageNoiseEstimator',
    'McraNoiseEstimator',
    'ImcraNoiseEstimator',
]
