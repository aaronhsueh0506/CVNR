"""
Evaluation Metrics - 評估指標

Provides comprehensive metrics for speech enhancement evaluation:
- segSNR (Segmental SNR) - PRIMARY metric for traditional algorithms
- SNR (Signal-to-Noise Ratio)
- PESQ (Perceptual Evaluation of Speech Quality) - Reference only
- STOI (Short-Time Objective Intelligibility) - Reference only
- LSD (Log Spectral Distance)
- Musical Noise Detection

Note:
    For traditional denoising algorithms (spectral subtraction, Wiener, etc.),
    segSNR is the primary metric because it's more forgiving of spectral
    modifications. PESQ/STOI are designed for codecs and penalize the kind
    of spectral changes that traditional algorithms inherently make.
"""

import numpy as np
from typing import Tuple, Optional

# Optional dependencies
try:
    from pesq import pesq as pesq_score
    PESQ_AVAILABLE = True
except ImportError:
    PESQ_AVAILABLE = False

try:
    from pystoi import stoi as stoi_score
    STOI_AVAILABLE = True
except ImportError:
    STOI_AVAILABLE = False


def calculate_snr(signal: np.ndarray, noise: np.ndarray) -> float:
    """
    Calculate Signal-to-Noise Ratio in dB.

    Args:
        signal: Clean signal
        noise: Noise signal

    Returns:
        SNR in dB
    """
    signal_power = np.mean(signal ** 2)
    noise_power = np.mean(noise ** 2)

    if noise_power < 1e-10:
        return 100.0  # Very high SNR

    snr_db = 10 * np.log10(signal_power / noise_power)
    return float(snr_db)


def calculate_snr_improvement(
    noisy: np.ndarray,
    clean: np.ndarray,
    enhanced: np.ndarray
) -> Tuple[float, float, float]:
    """
    Calculate input SNR, output SNR, and SNR improvement.

    Args:
        noisy: Noisy signal
        clean: Clean reference signal
        enhanced: Enhanced signal

    Returns:
        (input_snr_db, output_snr_db, snr_improvement_db)
    """
    # Ensure same length
    min_len = min(len(noisy), len(clean), len(enhanced))
    noisy = noisy[:min_len]
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # Calculate input SNR
    input_noise = noisy - clean
    input_snr = calculate_snr(clean, input_noise)

    # Calculate output SNR
    output_noise = enhanced - clean
    output_snr = calculate_snr(clean, output_noise)

    # SNR improvement
    snr_improvement = output_snr - input_snr

    return input_snr, output_snr, snr_improvement


def calculate_pesq(
    clean: np.ndarray,
    enhanced: np.ndarray,
    fs: int = 16000,
    mode: str = 'wb'
) -> Optional[float]:
    """
    Calculate PESQ (Perceptual Evaluation of Speech Quality).

    Args:
        clean: Clean reference signal
        enhanced: Enhanced signal
        fs: Sampling rate (8000 or 16000)
        mode: 'wb' (wideband) or 'nb' (narrowband)

    Returns:
        PESQ score (1.0-4.5) or None if PESQ not available

    Note:
        Requires: pip install pesq
        Score range: 1.0-4.5 (higher is better)
        - > 4.0: Excellent
        - 3.5-4.0: Good
        - 3.0-3.5: Fair
        - < 3.0: Poor
    """
    if not PESQ_AVAILABLE:
        print("Warning: PESQ not available. Install with: pip install pesq")
        return None

    # Ensure same length
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # PESQ requires specific sample rates
    if fs not in [8000, 16000]:
        print(f"Warning: PESQ requires fs=8000 or 16000, got {fs}")
        return None

    try:
        score = pesq_score(fs, clean, enhanced, mode)
        return float(score)
    except Exception as e:
        print(f"PESQ calculation failed: {e}")
        return None


def calculate_stoi(
    clean: np.ndarray,
    enhanced: np.ndarray,
    fs: int = 16000,
    extended: bool = False
) -> Optional[float]:
    """
    Calculate STOI (Short-Time Objective Intelligibility).

    Args:
        clean: Clean reference signal
        enhanced: Enhanced signal
        fs: Sampling rate
        extended: Use extended STOI (ESTOI)

    Returns:
        STOI score (0-1) or None if STOI not available

    Note:
        Requires: pip install pystoi
        Score range: 0-1 (higher is better)
        - > 0.9: Excellent
        - 0.8-0.9: Good
        - 0.7-0.8: Fair
        - < 0.7: Poor
    """
    if not STOI_AVAILABLE:
        print("Warning: STOI not available. Install with: pip install pystoi")
        return None

    # Ensure same length
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    try:
        score = stoi_score(clean, enhanced, fs, extended=extended)
        return float(score)
    except Exception as e:
        print(f"STOI calculation failed: {e}")
        return None


def calculate_segmental_snr(
    clean: np.ndarray,
    enhanced: np.ndarray,
    frame_size: int = 256,
    hop_size: int = 128
) -> float:
    """
    Calculate Segmental Signal-to-Noise Ratio (segSNR).

    This metric is more suitable for traditional denoising algorithms than PESQ/STOI
    because it measures SNR frame-by-frame, avoiding the harsh penalties that
    perceptual metrics impose on spectral modifications.

    Args:
        clean: Clean reference signal
        enhanced: Enhanced signal
        frame_size: Frame size in samples (default 256 = 16ms @ 16kHz)
        hop_size: Hop size in samples (default 128 = 50% overlap)

    Returns:
        Segmental SNR in dB (higher is better)

    Note:
        - Frame-by-frame SNR calculation with outlier clipping
        - Silent frames (power < 1e-10) are skipped
        - Frame SNRs are clipped to [-10, 35] dB to avoid outliers
        - Typical range: 5-20 dB for good denoising
    """
    # Ensure same length
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # Calculate number of frames
    num_frames = (len(clean) - frame_size) // hop_size + 1

    if num_frames < 1:
        # Signal too short, fall back to global SNR
        noise = enhanced - clean
        return calculate_snr(clean, noise)

    # Calculate frame-by-frame SNR
    frame_snrs = []

    for i in range(num_frames):
        start = i * hop_size
        end = start + frame_size

        if end > len(clean):
            break

        clean_frame = clean[start:end]
        enhanced_frame = enhanced[start:end]

        # Calculate frame power
        signal_power = np.mean(clean_frame ** 2)

        # Skip silent frames
        if signal_power < 1e-10:
            continue

        # Calculate noise for this frame
        noise_frame = enhanced_frame - clean_frame
        noise_power = np.mean(noise_frame ** 2)

        # Calculate frame SNR
        if noise_power < 1e-10:
            frame_snr = 35.0  # Very high SNR (clipped)
        else:
            frame_snr = 10 * np.log10(signal_power / noise_power)

        # Clip to avoid outliers
        frame_snr = np.clip(frame_snr, -10.0, 35.0)

        frame_snrs.append(frame_snr)

    # Return mean of all frame SNRs
    if len(frame_snrs) == 0:
        return 0.0  # No valid frames

    segmental_snr = np.mean(frame_snrs)
    return float(segmental_snr)


def calculate_segmental_snr_improvement(
    noisy: np.ndarray,
    clean: np.ndarray,
    enhanced: np.ndarray,
    frame_size: int = 256,
    hop_size: int = 128
) -> Tuple[float, float, float]:
    """
    Calculate input segSNR, output segSNR, and segSNR improvement.

    This is the PRIMARY metric for evaluating traditional denoising algorithms,
    as it's more forgiving of spectral modifications than PESQ/STOI.

    Args:
        noisy: Noisy signal
        clean: Clean reference signal
        enhanced: Enhanced signal
        frame_size: Frame size in samples
        hop_size: Hop size in samples

    Returns:
        (input_segsnr_db, output_segsnr_db, segsnr_improvement_db)
    """
    # Calculate input segSNR (noisy vs clean)
    input_segsnr = calculate_segmental_snr(clean, noisy, frame_size, hop_size)

    # Calculate output segSNR (enhanced vs clean)
    output_segsnr = calculate_segmental_snr(clean, enhanced, frame_size, hop_size)

    # Calculate improvement
    segsnr_improvement = output_segsnr - input_segsnr

    return input_segsnr, output_segsnr, segsnr_improvement


def calculate_lsd(
    clean: np.ndarray,
    enhanced: np.ndarray,
    frame_size: int = 512,
    hop_size: int = 256
) -> float:
    """
    Calculate Log Spectral Distance (LSD).

    Args:
        clean: Clean reference signal
        enhanced: Enhanced signal
        frame_size: Frame size for STFT
        hop_size: Hop size for STFT

    Returns:
        LSD in dB (lower is better)

    Note:
        - < 1 dB: Excellent
        - 1-2 dB: Good
        - 2-3 dB: Fair
        - > 3 dB: Poor
    """
    # Ensure same length
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # Calculate spectrograms
    clean_spec = _stft(clean, frame_size, hop_size)
    enhanced_spec = _stft(enhanced, frame_size, hop_size)

    # Ensure same number of frames
    min_frames = min(clean_spec.shape[1], enhanced_spec.shape[1])
    clean_spec = clean_spec[:, :min_frames]
    enhanced_spec = enhanced_spec[:, :min_frames]

    # Calculate LSD
    # LSD = sqrt(mean((20*log10(|Enhanced|/|Clean|))^2))
    ratio = enhanced_spec / (clean_spec + 1e-10)
    log_ratio = 20 * np.log10(ratio + 1e-10)
    lsd = np.sqrt(np.mean(log_ratio ** 2))

    return float(lsd)


def detect_musical_noise(
    enhanced: np.ndarray,
    frame_size: int = 512,
    hop_size: int = 256
) -> float:
    """
    Detect musical noise using spectral variance method.

    Args:
        enhanced: Enhanced signal
        frame_size: Frame size for STFT
        hop_size: Hop size for STFT

    Returns:
        Musical noise score (higher means more musical noise)

    Note:
        This measures the variance of spectral changes between frames.
        Higher values indicate more "tonal" artifacts (musical noise).
    """
    # Calculate spectrogram
    spec = _stft(enhanced, frame_size, hop_size)

    # Calculate frame-to-frame spectral difference
    diff = np.diff(spec, axis=1)

    # Calculate variance across frequency bins
    variance = np.var(diff, axis=0)

    # Average variance
    musical_noise_score = np.mean(variance)

    return float(musical_noise_score)


def _stft(signal: np.ndarray, frame_size: int, hop_size: int) -> np.ndarray:
    """
    Short-Time Fourier Transform.

    Args:
        signal: Input signal
        frame_size: Frame size
        hop_size: Hop size

    Returns:
        Magnitude spectrogram (freq_bins x num_frames)
    """
    # Create Hanning window
    window = np.hanning(frame_size)

    # Calculate number of frames
    num_frames = (len(signal) - frame_size) // hop_size + 1

    # Initialize spectrogram
    num_freq_bins = frame_size // 2 + 1
    spectrogram = np.zeros((num_freq_bins, num_frames))

    # Process each frame
    for i in range(num_frames):
        start = i * hop_size
        end = start + frame_size

        if end > len(signal):
            break

        frame = signal[start:end] * window
        spectrum = np.fft.rfft(frame)
        spectrogram[:, i] = np.abs(spectrum)

    return spectrogram


def evaluate_all_metrics(
    noisy: np.ndarray,
    clean: np.ndarray,
    enhanced: np.ndarray,
    fs: int = 16000
) -> dict:
    """
    Calculate all available metrics for comprehensive evaluation.

    Args:
        noisy: Noisy input signal
        clean: Clean reference signal
        enhanced: Enhanced output signal
        fs: Sampling rate

    Returns:
        Dictionary with all metric results

    Note:
        For traditional denoising algorithms, segSNR is the primary metric.
        PESQ/STOI are provided for reference only.
    """
    results = {}

    # Segmental SNR metrics (PRIMARY for traditional algorithms)
    input_segsnr, output_segsnr, segsnr_improvement = calculate_segmental_snr_improvement(
        noisy, clean, enhanced
    )
    results['input_segsnr_db'] = input_segsnr
    results['output_segsnr_db'] = output_segsnr
    results['segsnr_improvement_db'] = segsnr_improvement

    # Global SNR metrics
    input_snr, output_snr, snr_improvement = calculate_snr_improvement(
        noisy, clean, enhanced
    )
    results['input_snr_db'] = input_snr
    results['output_snr_db'] = output_snr
    results['snr_improvement_db'] = snr_improvement

    # PESQ (reference only for traditional algorithms)
    pesq_result = calculate_pesq(clean, enhanced, fs)
    results['pesq'] = pesq_result

    # STOI (reference only for traditional algorithms)
    stoi_result = calculate_stoi(clean, enhanced, fs)
    results['stoi'] = stoi_result

    # LSD
    lsd_result = calculate_lsd(clean, enhanced)
    results['lsd_db'] = lsd_result

    # Musical noise
    musical_noise = detect_musical_noise(enhanced)
    results['musical_noise'] = musical_noise

    return results


def print_metrics(metrics: dict, algorithm_name: str = ""):
    """
    Pretty print metrics results.

    Args:
        metrics: Dictionary from evaluate_all_metrics()
        algorithm_name: Name of the algorithm
    """
    if algorithm_name:
        print(f"\n{'='*70}")
        print(f"Metrics for: {algorithm_name}")
        print(f"{'='*70}")

    # PRIMARY METRICS (Segmental SNR)
    print("\n[PRIMARY METRICS - Segmental SNR]")
    print(f"  Input segSNR:         {metrics['input_segsnr_db']:7.2f} dB")
    print(f"  Output segSNR:        {metrics['output_segsnr_db']:7.2f} dB")
    print(f"  segSNR Improvement:   {metrics['segsnr_improvement_db']:7.2f} dB  ★")

    # SECONDARY METRICS (Global SNR)
    print("\n[Global SNR Metrics]")
    print(f"  Input SNR:            {metrics['input_snr_db']:7.2f} dB")
    print(f"  Output SNR:           {metrics['output_snr_db']:7.2f} dB")
    print(f"  SNR Improvement:      {metrics['snr_improvement_db']:7.2f} dB")

    # REFERENCE METRICS (PESQ/STOI - not primary for traditional algorithms)
    print("\n[Reference Metrics - For comparison only]")
    if metrics['pesq'] is not None:
        print(f"  PESQ:                 {metrics['pesq']:7.2f} (1.0-4.5)")
    else:
        print(f"  PESQ:                 N/A (install: pip install pesq)")

    if metrics['stoi'] is not None:
        print(f"  STOI:                 {metrics['stoi']:7.3f} (0-1)")
    else:
        print(f"  STOI:                 N/A (install: pip install pystoi)")

    # QUALITY METRICS
    print("\n[Quality Metrics]")
    print(f"  LSD:                  {metrics['lsd_db']:7.2f} dB")
    print(f"  Musical Noise:        {metrics['musical_noise']:7.2e}")

    print(f"\n{'='*70}")
    print("Note: For traditional denoising, focus on segSNR improvement (★)")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    # Example usage
    print("Speech Enhancement Metrics Module")
    print(f"PESQ available: {PESQ_AVAILABLE}")
    print(f"STOI available: {STOI_AVAILABLE}")

    # Generate test signals
    fs = 16000
    duration = 2.0
    t = np.linspace(0, duration, int(fs * duration))

    # Clean signal (sine wave)
    clean = np.sin(2 * np.pi * 440 * t)

    # Noisy signal
    noise = np.random.randn(len(clean)) * 0.1
    noisy = clean + noise

    # "Enhanced" signal (just apply simple gain)
    enhanced = noisy * 0.8

    # Calculate all metrics
    metrics = evaluate_all_metrics(noisy, clean, enhanced, fs)
    print_metrics(metrics, "Test Example")
