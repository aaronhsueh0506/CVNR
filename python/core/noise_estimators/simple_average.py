"""Simple-average noise estimator (V1 spectral subtraction)."""

import numpy as np
from typing import Optional


class SimpleAverageNoiseEstimator:
    """Noise PSD from the mean power of the num_init_frames lowest-energy frames (default 20),
    with an optional re-estimate from non-speech frames after a noise-scene change.
    """

    def __init__(self, num_init_frames: int = 20):
        self.num_init_frames = num_init_frames
        self.noise_psd = None
        self.is_initialized = False

        self.is_reestimating = False
        self.noise_buffer = []
        self.reestimate_frames = num_init_frames

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """Estimates the noise PSD (n_freqs,) from a magnitude spectrogram (n_frames, n_freqs) or one frame."""
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_frames = magnitude_spectrum.shape[0]

        # With enough frames, use the lowest-energy ones rather than assuming the start is noise.
        if n_frames > self.num_init_frames * 2:
            frame_energy = np.sum(magnitude_spectrum ** 2, axis=1)

            min_energy_indices = np.argsort(frame_energy)[:self.num_init_frames]
            init_frames = magnitude_spectrum[min_energy_indices]
        else:
            # Too few frames: use the first num_init_frames.
            init_frames = magnitude_spectrum[:self.num_init_frames]

        power_spectrum = init_frames ** 2

        self.noise_psd = np.mean(power_spectrum, axis=0)
        self.is_initialized = True

        return self.noise_psd

    def update(self, magnitude: np.ndarray, is_speech: bool = True) -> np.ndarray:
        """Returns the noise PSD (n_freqs,); it is fixed unless a re-estimate is running, which
        averages `reestimate_frames` non-speech frames (is_speech=False).
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        if self.is_reestimating:
            if not is_speech:
                self.noise_buffer.append(magnitude ** 2)

                if len(self.noise_buffer) >= self.reestimate_frames:
                    self.noise_psd = np.mean(self.noise_buffer, axis=0)
                    self.is_reestimating = False
                    self.noise_buffer = []

        return self.noise_psd

    def start_reestimate(self):
        """Starts a re-estimate from the next non-speech frames (call after a noise-scene change)."""
        self.is_reestimating = True
        self.noise_buffer = []

    def reset(self):
        """Clears all state."""
        self.noise_psd = None
        self.is_initialized = False
        self.is_reestimating = False
        self.noise_buffer = []

    def __repr__(self):
        return f"SimpleAverageNoiseEstimator(num_init_frames={self.num_init_frames})"
