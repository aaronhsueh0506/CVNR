"""Abstract base class for denoisers."""

import numpy as np
from abc import ABC, abstractmethod
from typing import Tuple


class BaseDenoiser(ABC):
    """Common interface of all denoisers."""

    def __init__(self, sample_rate: int = 16000, n_fft: int = 512):
        self.sample_rate = sample_rate
        self.is_initialized = False
        self.n_fft = n_fft

    @abstractmethod
    def denoise(self, noisy_signal: np.ndarray) -> np.ndarray:
        """Denoise noisy_signal (n_samples,) and return the enhanced signal (n_samples,)."""
        pass

    @abstractmethod
    def denoise_spectrum(
        self,
        noisy_magnitude: np.ndarray,
        noisy_phase: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Denoise magnitude/phase spectra (n_frames, n_freqs); returns (magnitude, phase)."""
        pass

    @abstractmethod
    def reset(self):
        """Reset the denoiser state."""
        pass

    def __repr__(self):
        return f"{self.__class__.__name__}(sample_rate={self.sample_rate})"
