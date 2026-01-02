"""
Loizou 評估指標模塊

基於 Loizou (2008) "Evaluation of Objective Quality Measures for Speech Enhancement"
實現改進的語音增強評估指標

參考文獻:
    Hu, Y., & Loizou, P. C. (2008).
    "Evaluation of objective quality measures for speech enhancement."
    IEEE Transactions on Audio, Speech, and Language Processing, 16(1), 229-238.

主要指標:
    - segSNR: 帶 VAD 的分段 SNR
    - fwSegSNR: 頻率加權分段 SNR
    - WSS: 加權頻譜斜率距離
    - LLR: 對數似然比
    - Composite: 復合指標

實現參考: https://github.com/schmiph2/pysepm
"""

import numpy as np
from typing import Tuple, Optional


def frame_signal(signal: np.ndarray, frame_len: int, frame_shift: int) -> np.ndarray:
    """
    分幀函數

    參數:
        signal: 輸入信號 (n_samples,)
        frame_len: 幀長 (samples)
        frame_shift: 幀移 (samples)

    返回:
        frames: 分幀後的信號 (n_frames, frame_len)
    """
    n_samples = len(signal)
    n_frames = 1 + (n_samples - frame_len) // frame_shift

    frames = np.zeros((n_frames, frame_len))
    for i in range(n_frames):
        start = i * frame_shift
        frames[i] = signal[start:start + frame_len]

    return frames


def voice_activity_detection(
    signal: np.ndarray,
    frame_len: int,
    frame_shift: int,
    energy_threshold_db: float = -40.0
) -> np.ndarray:
    """
    簡單的語音活動檢測 (VAD)

    基於能量閾值的 VAD,用於排除靜音幀

    參數:
        signal: 輸入信號 (n_samples,)
        frame_len: 幀長 (samples)
        frame_shift: 幀移 (samples)
        energy_threshold_db: 能量閾值 (dB),低於此值視為靜音

    返回:
        vad_flags: 語音幀標記 (n_frames,), True=語音, False=靜音
    """
    frames = frame_signal(signal, frame_len, frame_shift)
    n_frames = frames.shape[0]

    # 計算每幀能量 (dB)
    frame_energy = np.sum(frames ** 2, axis=1) + 1e-10
    frame_energy_db = 10 * np.log10(frame_energy)

    # 應用閾值
    vad_flags = frame_energy_db > energy_threshold_db

    return vad_flags


def segmental_snr(
    clean: np.ndarray,
    enhanced: np.ndarray,
    sample_rate: int = 16000,
    frame_len_ms: float = 20.0,
    frame_shift_ms: float = 10.0,
    use_vad: bool = True,
    vad_threshold_db: float = -40.0,
    snr_clip_db: Tuple[float, float] = (-10.0, 35.0)
) -> float:
    """
    分段信噪比 (Segmental SNR)

    根據 Loizou 2008 的建議實現:
    1. 使用 VAD 排除靜音幀
    2. 限制 SNR 範圍在 [-10, 35] dB
    3. 只計算有語音的幀

    參數:
        clean: 乾淨語音信號 (n_samples,)
        enhanced: 增強後的語音信號 (n_samples,)
        sample_rate: 採樣率 (Hz)
        frame_len_ms: 幀長 (毫秒)
        frame_shift_ms: 幀移 (毫秒)
        use_vad: 是否使用 VAD 排除靜音幀
        vad_threshold_db: VAD 能量閾值 (dB)
        snr_clip_db: SNR 限制範圍 (min_db, max_db)

    返回:
        seg_snr: 分段 SNR (dB)

    注意:
        - 傳統 segSNR (不用 VAD) 相關性只有 0.40-0.46
        - 使用 VAD 可以顯著提高評估準確性
        - Global SNR 通常比 segSNR 高約 7 dB
    """
    # 確保長度一致
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # 計算幀參數
    frame_len = int(sample_rate * frame_len_ms / 1000)
    frame_shift = int(sample_rate * frame_shift_ms / 1000)

    # 分幀
    frames_clean = frame_signal(clean, frame_len, frame_shift)
    frames_enhanced = frame_signal(enhanced, frame_len, frame_shift)
    n_frames = frames_clean.shape[0]

    # VAD
    if use_vad:
        vad_flags = voice_activity_detection(
            clean,
            frame_len,
            frame_shift,
            vad_threshold_db
        )
    else:
        vad_flags = np.ones(n_frames, dtype=bool)

    # 計算每幀的 SNR
    snr_frames = []
    for i in range(n_frames):
        if not vad_flags[i]:
            continue

        signal_power = np.sum(frames_clean[i] ** 2) + 1e-10
        noise_power = np.sum((frames_clean[i] - frames_enhanced[i]) ** 2) + 1e-10

        snr_db = 10 * np.log10(signal_power / noise_power)

        # 限制 SNR 範圍
        snr_db = np.clip(snr_db, snr_clip_db[0], snr_clip_db[1])
        snr_frames.append(snr_db)

    if len(snr_frames) == 0:
        return 0.0

    return np.mean(snr_frames)


def frequency_weighted_segsnr(
    clean: np.ndarray,
    enhanced: np.ndarray,
    sample_rate: int = 16000,
    frame_len_ms: float = 20.0,
    frame_shift_ms: float = 10.0,
    use_vad: bool = True,
    vad_threshold_db: float = -40.0
) -> float:
    """
    頻率加權分段 SNR (Frequency-weighted Segmental SNR)

    對不同頻率賦予不同權重,更符合人耳感知特性

    參數:
        clean: 乾淨語音信號
        enhanced: 增強後的語音信號
        sample_rate: 採樣率
        frame_len_ms: 幀長 (毫秒)
        frame_shift_ms: 幀移 (毫秒)
        use_vad: 是否使用 VAD
        vad_threshold_db: VAD 閾值

    返回:
        fwseg_snr: 頻率加權 segSNR (dB)
    """
    # 計算幀參數
    frame_len = int(sample_rate * frame_len_ms / 1000)
    frame_shift = int(sample_rate * frame_shift_ms / 1000)

    # 確保長度一致
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # 分幀
    frames_clean = frame_signal(clean, frame_len, frame_shift)
    frames_enhanced = frame_signal(enhanced, frame_len, frame_shift)
    n_frames = frames_clean.shape[0]

    # VAD
    if use_vad:
        vad_flags = voice_activity_detection(
            clean,
            frame_len,
            frame_shift,
            vad_threshold_db
        )
    else:
        vad_flags = np.ones(n_frames, dtype=bool)

    # FFT
    n_fft = 512

    # 頻率權重 (基於聽覺感知)
    # 語音能量主要集中在 300-3000 Hz,給予更高權重
    freqs = np.fft.rfftfreq(n_fft, 1/sample_rate)
    weights = np.ones_like(freqs)

    # 300-3000 Hz 權重為 1.0, 其他頻率權重遞減
    for i, f in enumerate(freqs):
        if f < 300:
            weights[i] = 0.5
        elif f > 3000:
            weights[i] = max(0.3, 1.0 - (f - 3000) / 5000)

    weights = weights / np.sum(weights)  # 歸一化

    # 計算頻率加權 SNR
    fwsnr_frames = []
    for i in range(n_frames):
        if not vad_flags[i]:
            continue

        # FFT
        clean_fft = np.fft.rfft(frames_clean[i], n=n_fft)
        enhanced_fft = np.fft.rfft(frames_enhanced[i], n=n_fft)

        # 頻譜能量
        clean_psd = np.abs(clean_fft) ** 2 + 1e-10
        noise_psd = np.abs(clean_fft - enhanced_fft) ** 2 + 1e-10

        # 頻率加權 SNR
        snr_freq = clean_psd / noise_psd
        fwsnr = 10 * np.log10(np.sum(weights * snr_freq))

        fwsnr = np.clip(fwsnr, -10, 35)
        fwsnr_frames.append(fwsnr)

    if len(fwsnr_frames) == 0:
        return 0.0

    return np.mean(fwsnr_frames)


def weighted_spectral_slope(
    clean: np.ndarray,
    enhanced: np.ndarray,
    sample_rate: int = 16000,
    frame_len_ms: float = 20.0,
    frame_shift_ms: float = 10.0,
    use_vad: bool = True,
    vad_threshold_db: float = -40.0
) -> float:
    """
    加權頻譜斜率距離 (Weighted-slope Spectral distance, WSS)

    測量頻譜失真的經典指標

    參數:
        clean: 乾淨語音信號
        enhanced: 增強後的語音信號
        sample_rate: 採樣率
        frame_len_ms: 幀長
        frame_shift_ms: 幀移
        use_vad: 是否使用 VAD
        vad_threshold_db: VAD 閾值

    返回:
        wss: WSS 距離 (值越小越好)
    """
    # 計算幀參數
    frame_len = int(sample_rate * frame_len_ms / 1000)
    frame_shift = int(sample_rate * frame_shift_ms / 1000)

    # 確保長度一致
    min_len = min(len(clean), len(enhanced))
    clean = clean[:min_len]
    enhanced = enhanced[:min_len]

    # 分幀
    frames_clean = frame_signal(clean, frame_len, frame_shift)
    frames_enhanced = frame_signal(enhanced, frame_len, frame_shift)
    n_frames = frames_clean.shape[0]

    # VAD
    if use_vad:
        vad_flags = voice_activity_detection(
            clean,
            frame_len,
            frame_shift,
            vad_threshold_db
        )
    else:
        vad_flags = np.ones(n_frames, dtype=bool)

    # FFT
    n_fft = 512
    n_bands = 25  # 將頻譜分為 25 個頻帶

    # Bark 頻率權重 (模擬人耳臨界頻帶)
    weights = np.array([0.003, 0.003, 0.003, 0.007, 0.010, 0.016, 0.016, 0.017,
                        0.017, 0.022, 0.027, 0.028, 0.030, 0.032, 0.034, 0.035,
                        0.037, 0.036, 0.036, 0.033, 0.030, 0.029, 0.027, 0.026,
                        0.024])

    # 計算 WSS
    wss_frames = []
    for i in range(n_frames):
        if not vad_flags[i]:
            continue

        # FFT
        clean_fft = np.fft.rfft(frames_clean[i], n=n_fft)
        enhanced_fft = np.fft.rfft(frames_enhanced[i], n=n_fft)

        # 對數頻譜
        clean_log_spec = np.log10(np.abs(clean_fft) + 1e-10)
        enhanced_log_spec = np.log10(np.abs(enhanced_fft) + 1e-10)

        # 計算頻譜斜率
        clean_slope = np.diff(clean_log_spec)
        enhanced_slope = np.diff(enhanced_log_spec)

        # 分頻帶計算
        n_bins_per_band = len(clean_slope) // n_bands
        wss_band = []

        for j in range(n_bands):
            start = j * n_bins_per_band
            end = (j + 1) * n_bins_per_band
            if end > len(clean_slope):
                end = len(clean_slope)

            if end <= start:
                continue

            slope_diff = clean_slope[start:end] - enhanced_slope[start:end]
            wss_band.append(np.sum(slope_diff ** 2))

        # 加權平均
        if len(wss_band) == len(weights):
            wss_frame = np.sum(np.array(wss_band) * weights)
            wss_frames.append(wss_frame)

    if len(wss_frames) == 0:
        return 0.0

    return np.mean(wss_frames)


def composite_measure(
    clean: np.ndarray,
    enhanced: np.ndarray,
    sample_rate: int = 16000
) -> dict:
    """
    Loizou 復合評估指標

    綜合多個指標提供全面評估

    參數:
        clean: 乾淨語音信號
        enhanced: 增強後的語音信號
        sample_rate: 採樣率

    返回:
        metrics: 包含各種指標的字典
            - segSNR: 帶 VAD 的分段 SNR
            - fwSegSNR: 頻率加權 segSNR
            - WSS: 加權頻譜斜率距離
            - global_SNR: 全局 SNR
    """
    metrics = {}

    # 1. Segmental SNR with VAD
    metrics['segSNR'] = segmental_snr(
        clean, enhanced, sample_rate,
        use_vad=True
    )

    # 2. Frequency-weighted Segmental SNR
    metrics['fwSegSNR'] = frequency_weighted_segsnr(
        clean, enhanced, sample_rate,
        use_vad=True
    )

    # 3. Weighted Spectral Slope
    metrics['WSS'] = weighted_spectral_slope(
        clean, enhanced, sample_rate,
        use_vad=True
    )

    # 4. Global SNR (參考)
    signal_power = np.sum(clean ** 2) + 1e-10
    noise_power = np.sum((clean - enhanced) ** 2) + 1e-10
    metrics['global_SNR'] = 10 * np.log10(signal_power / noise_power)

    return metrics


def print_metrics(metrics: dict, title: str = "評估結果"):
    """
    格式化打印評估指標

    參數:
        metrics: 指標字典
        title: 標題
    """
    print(f"\n{'='*50}")
    print(f"{title}")
    print(f"{'='*50}")

    # 排序並打印
    for key in ['segSNR', 'fwSegSNR', 'WSS', 'global_SNR']:
        if key in metrics:
            value = metrics[key]
            if key == 'WSS':
                print(f"{key:15s}: {value:7.3f} (越小越好)")
            else:
                print(f"{key:15s}: {value:7.3f} dB")

    print(f"{'='*50}\n")


if __name__ == "__main__":
    # 測試示例
    print("Loizou 評估指標模塊")
    print("\n使用方法:")
    print("  from utils.metrics_loizou import segmental_snr, composite_measure")
    print("  snr = segmental_snr(clean, enhanced, sample_rate=16000)")
    print("  metrics = composite_measure(clean, enhanced, sample_rate=16000)")
    print("\n注意:")
    print("  - segSNR 使用 VAD 排除靜音幀")
    print("  - SNR 限制在 [-10, 35] dB 範圍")
    print("  - Global SNR 通常比 segSNR 高約 7 dB")
