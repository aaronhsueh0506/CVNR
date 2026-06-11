"""
Audio I/O utilities - 音頻文件讀寫
"""

import numpy as np
from typing import Tuple, Optional
import warnings

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False
    warnings.warn("soundfile not available, trying scipy.io.wavfile")
    try:
        from scipy.io import wavfile
        SCIPY_AVAILABLE = True
    except ImportError:
        SCIPY_AVAILABLE = False
        warnings.warn("Neither soundfile nor scipy available for audio I/O")


def read_audio(
    file_path: str,
    target_sr: Optional[int] = None,
    mono: bool = True
) -> Tuple[np.ndarray, int]:
    """
    讀取音頻文件

    參數:
        file_path: 音頻文件路徑
        target_sr: 目標採樣率（如果與原始不同會重採樣）
        mono: 是否轉換為單聲道

    返回:
        audio: 音頻數據 (n_samples,) 或 (n_samples, n_channels)
        sample_rate: 採樣率
    """
    if SOUNDFILE_AVAILABLE:
        audio, sample_rate = sf.read(file_path, dtype='float32')
    elif SCIPY_AVAILABLE:
        sample_rate, audio = wavfile.read(file_path)
        # 轉換為 float32 並歸一化
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0
        elif audio.dtype == np.uint8:
            audio = (audio.astype(np.float32) - 128.0) / 128.0
    else:
        raise RuntimeError("No audio I/O library available. Install soundfile or scipy.")

    # 轉換為單聲道
    if mono and len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # 重採樣（簡單實現，生產環境建議使用 librosa.resample）
    if target_sr is not None and target_sr != sample_rate:
        warnings.warn(
            f"Resampling from {sample_rate} to {target_sr} Hz. "
            "Install librosa for better quality resampling."
        )
        audio = simple_resample(audio, sample_rate, target_sr)
        sample_rate = target_sr

    return audio, sample_rate


def write_audio(
    file_path: str,
    audio: np.ndarray,
    sample_rate: int,
    normalize: bool = False
) -> None:
    """
    寫入音頻文件

    參數:
        file_path: 輸出文件路徑
        audio: 音頻數據 (n_samples,) 或 (n_samples, n_channels)
        sample_rate: 採樣率
        normalize: 是否歸一化到 [-1, 1]
    """
    if normalize:
        audio = normalize_audio(audio)

    if SOUNDFILE_AVAILABLE:
        sf.write(file_path, audio, sample_rate)
    elif SCIPY_AVAILABLE:
        # 轉換為 int16（先 clip 避免 overflow）
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        wavfile.write(file_path, sample_rate, audio_int16)
    else:
        raise RuntimeError("No audio I/O library available. Install soundfile or scipy.")


def normalize_audio(audio: np.ndarray, target_level: float = 0.95) -> np.ndarray:
    """
    歸一化音頻到指定峰值

    參數:
        audio: 音頻數據
        target_level: 目標峰值電平 (0-1)

    返回:
        normalized_audio: 歸一化後的音頻
    """
    max_val = np.abs(audio).max()
    if max_val > 0:
        return audio * (target_level / max_val)
    return audio


def simple_resample(
    audio: np.ndarray,
    orig_sr: int,
    target_sr: int
) -> np.ndarray:
    """
    簡單的重採樣（線性插值）

    注意：這是一個簡單實現，生產環境請使用 librosa.resample

    參數:
        audio: 原始音頻
        orig_sr: 原始採樣率
        target_sr: 目標採樣率

    返回:
        resampled: 重採樣後的音頻
    """
    duration = len(audio) / orig_sr
    target_length = int(duration * target_sr)

    # 線性插值
    orig_indices = np.arange(len(audio))
    target_indices = np.linspace(0, len(audio) - 1, target_length)
    resampled = np.interp(target_indices, orig_indices, audio)

    return resampled


def calculate_snr(
    clean: np.ndarray,
    noisy: np.ndarray
) -> float:
    """
    計算信噪比 (SNR)

    參數:
        clean: 乾淨信號
        noisy: 帶噪信號

    返回:
        snr_db: SNR (dB)
    """
    noise = noisy - clean
    signal_power = np.mean(clean ** 2)
    noise_power = np.mean(noise ** 2)

    if noise_power < 1e-10:
        return 100.0  # 無噪聲

    snr = 10 * np.log10(signal_power / noise_power)
    return snr


def add_noise(
    clean: np.ndarray,
    noise: np.ndarray,
    target_snr_db: float
) -> np.ndarray:
    """
    將噪聲添加到乾淨信號以達到目標 SNR

    參數:
        clean: 乾淨信號
        noise: 噪聲信號
        target_snr_db: 目標 SNR (dB)

    返回:
        noisy: 帶噪信號
    """
    # 確保噪聲長度足夠
    if len(noise) < len(clean):
        # 重複噪聲
        n_repeats = int(np.ceil(len(clean) / len(noise)))
        noise = np.tile(noise, n_repeats)

    noise = noise[:len(clean)]

    # 計算當前功率
    signal_power = np.mean(clean ** 2)
    noise_power = np.mean(noise ** 2)

    # 計算所需的噪聲縮放因子
    target_noise_power = signal_power / (10 ** (target_snr_db / 10))
    noise_scale = np.sqrt(target_noise_power / noise_power)

    # 添加噪聲
    noisy = clean + noise_scale * noise

    return noisy


def split_audio(
    audio: np.ndarray,
    chunk_size: int,
    overlap: int = 0
) -> list:
    """
    將音頻分割成塊

    參數:
        audio: 音頻信號
        chunk_size: 塊大小（樣本數）
        overlap: 重疊樣本數

    返回:
        chunks: 音頻塊列表
    """
    chunks = []
    step = chunk_size - overlap

    for i in range(0, len(audio), step):
        chunk = audio[i:i + chunk_size]
        if len(chunk) == chunk_size:
            chunks.append(chunk)

    return chunks
