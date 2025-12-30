#!/usr/bin/env python3
"""Debug script to check audio processing levels"""

import numpy as np
from scipy.io import wavfile
from denoisers.v1_spectral_subtraction import SpectralSubtractionDenoiser

# Read input
sr, audio = wavfile.read('../babble_10dB.wav')
if audio.dtype == np.int16:
    audio = audio.astype(np.float32) / 32768.0

print(f'\n{"="*60}')
print(f'Input Audio Analysis')
print(f'{"="*60}')
print(f'Shape: {audio.shape}')
print(f'RMS: {np.sqrt(np.mean(audio**2)):.6f}')
print(f'Peak: {np.max(np.abs(audio)):.6f}')
print(f'dB: {20*np.log10(np.sqrt(np.mean(audio**2)) + 1e-10):.1f}')

# Create V1 denoiser
denoiser = SpectralSubtractionDenoiser(
    sample_rate=16000,
    frame_size_ms=20,
    frame_shift_ms=10,
    fft_size=512,
    num_init_frames=20,
    alpha=1.0,
    beta=0.1
)

print(f'\n{"="*60}')
print(f'Denoiser Configuration')
print(f'{"="*60}')
print(f'alpha: {denoiser.gain_calculator.alpha}')
print(f'beta: {denoiser.gain_calculator.beta}')
print(f'num_init_frames: {denoiser.noise_estimator.num_init_frames}')

# Process
enhanced = denoiser.denoise(audio)

print(f'\n{"="*60}')
print(f'Enhanced Audio Analysis')
print(f'{"="*60}')
print(f'Shape: {enhanced.shape}')
print(f'RMS: {np.sqrt(np.mean(enhanced**2)):.6f}')
print(f'Peak: {np.max(np.abs(audio)):.6f}')
print(f'dB: {20*np.log10(np.sqrt(np.mean(enhanced**2)) + 1e-10):.1f}')
print(f'Attenuation: {20*np.log10((np.sqrt(np.mean(enhanced**2)) + 1e-10) / (np.sqrt(np.mean(audio**2)) + 1e-10)):.1f} dB')

# Check noise estimation
noise_est = denoiser.noise_estimator
if hasattr(noise_est, 'noise_psd') and noise_est.noise_psd is not None:
    print(f'\n{"="*60}')
    print(f'Noise Estimation')
    print(f'{"="*60}')
    print(f'Noise PSD mean: {np.mean(noise_est.noise_psd):.6f}')
    print(f'Noise PSD max: {np.max(noise_est.noise_psd):.6f}')
    print(f'Noise PSD min: {np.min(noise_est.noise_psd):.6f}')
