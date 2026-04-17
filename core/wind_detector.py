"""
Wind Detector - 風聲偵測器

基於頻域特徵偵測風聲存在，輸出機率與嚴重度分級。

核心特徵：
- Low-frequency energy ratio：風聲能量主要集中在 <500Hz
- Spectral tilt (dB)：風聲低頻/高頻能量比 > 12dB，語音 6-10dB
- ZCR（可選）：風聲過零率較低

機率融合後做時間平滑 + hangover，避免幀級抖動。
嚴重度分級 (none / mild / severe) 供下游 FreqAdaptiveController 使用。

參考：V4 規格書 §3.1
"""

import numpy as np
from typing import Optional


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class WindDetector:
    """風聲偵測器

    參數:
        sample_rate: 採樣率 (Hz)
        fft_size: FFT 點數（決定 n_freqs = fft_size // 2 + 1）
        low_freq_cutoff: 低頻段上限 (Hz)，用於 low_energy_ratio
        high_freq_cutoff: 高頻段下限 (Hz)，用於 spectral tilt
        low_energy_ratio_threshold: low_energy_ratio 轉機率時的中心點
        low_energy_ratio_slope: sigmoid 斜率
        spectral_tilt_threshold_db: tilt 轉機率時的中心點 (dB)
        spectral_tilt_slope: sigmoid 斜率
        zcr_threshold: ZCR 中心點（風聲 ZCR 較低，ZCR 低 → 機率高）
        zcr_slope: sigmoid 斜率
        feature_weights: dict，各特徵權重；預設等權重
        alpha_prob: 機率時間平滑因子
        hangover_frames: 風聲偵測到後持續 N 幀最低 mild 級
        mild_threshold: 機率 ≥ 此值為 mild
        severe_threshold: 機率 ≥ 此值為 severe
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        fft_size: int = 512,
        low_freq_cutoff: float = 300.0,
        high_freq_cutoff: float = 2000.0,
        low_energy_ratio_threshold: float = 0.6,
        low_energy_ratio_slope: float = 15.0,
        spectral_tilt_threshold_db: float = 12.0,
        spectral_tilt_slope: float = 0.3,
        zcr_threshold: float = 0.05,
        zcr_slope: float = 80.0,
        feature_weights: Optional[dict] = None,
        alpha_prob: float = 0.7,
        hangover_frames: int = 15,
        mild_threshold: float = 0.4,
        severe_threshold: float = 0.75,
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.n_freqs = fft_size // 2 + 1

        self.low_freq_cutoff = low_freq_cutoff
        self.high_freq_cutoff = high_freq_cutoff

        # sigmoid 參數
        self.low_energy_ratio_threshold = low_energy_ratio_threshold
        self.low_energy_ratio_slope = low_energy_ratio_slope
        self.spectral_tilt_threshold_db = spectral_tilt_threshold_db
        self.spectral_tilt_slope = spectral_tilt_slope
        self.zcr_threshold = zcr_threshold
        self.zcr_slope = zcr_slope

        # 特徵權重（等權重；ZCR 不提供時會動態重分配）
        default_weights = {'low_energy_ratio': 1.0, 'spectral_tilt': 1.0, 'zcr': 1.0}
        self.feature_weights = dict(default_weights)
        if feature_weights:
            self.feature_weights.update(feature_weights)

        # 時間平滑與 hangover
        self.alpha_prob = alpha_prob
        self.hangover_frames = hangover_frames

        # 閾值
        self.mild_threshold = mild_threshold
        self.severe_threshold = severe_threshold

        # 預計算頻率 bin（使用整數 floor）
        freq_per_bin = sample_rate / fft_size
        self.low_bin_end = max(1, int(low_freq_cutoff / freq_per_bin))
        # tilt 用：low band 80-300Hz，high band (high_freq_cutoff ~ 6000)
        self.tilt_low_bin_start = max(1, int(80.0 / freq_per_bin))
        self.tilt_low_bin_end = self.low_bin_end
        self.tilt_high_bin_start = int(high_freq_cutoff / freq_per_bin)
        self.tilt_high_bin_end = min(self.n_freqs, int(6000.0 / freq_per_bin))

        # 狀態
        self.wind_prob_prev = 0.0
        self.hangover_counter = 0
        self.frame_count = 0

    def detect(
        self,
        magnitude: np.ndarray,
        time_domain_frame: Optional[np.ndarray] = None,
    ) -> dict:
        """偵測當前幀風聲存在機率與嚴重度。

        參數:
            magnitude: (n_freqs,) 當前幀幅度譜
            time_domain_frame: (frame_size,) 時域幀（可選，用於 ZCR）

        返回:
            dict 包含 wind_probability, wind_severity, features, hangover_active
        """
        power = magnitude ** 2

        # Feature 1: low energy ratio
        p_low = np.sum(power[:self.low_bin_end])
        p_full = np.sum(power) + 1e-10
        low_energy_ratio = float(p_low / p_full)
        score_1 = float(_sigmoid(
            self.low_energy_ratio_slope *
            (low_energy_ratio - self.low_energy_ratio_threshold)
        ))

        # Feature 2: spectral tilt (dB)
        p_tilt_low = np.mean(power[self.tilt_low_bin_start:self.tilt_low_bin_end]) + 1e-10
        p_tilt_high = np.mean(power[self.tilt_high_bin_start:self.tilt_high_bin_end]) + 1e-10
        tilt_db = float(10.0 * np.log10(p_tilt_low / p_tilt_high))
        score_2 = float(_sigmoid(
            self.spectral_tilt_slope * (tilt_db - self.spectral_tilt_threshold_db)
        ))

        # Feature 3: ZCR（可選）
        zcr_value = None
        score_3 = None
        if time_domain_frame is not None and len(time_domain_frame) > 1:
            signs = np.sign(time_domain_frame)
            zcr_value = float(np.sum(np.abs(np.diff(signs))) / (2 * len(time_domain_frame)))
            # ZCR 低 → 風聲機率高（負斜率）
            score_3 = float(_sigmoid(
                -self.zcr_slope * (zcr_value - self.zcr_threshold)
            ))

        # 加權融合
        w_ler = self.feature_weights['low_energy_ratio']
        w_tilt = self.feature_weights['spectral_tilt']
        w_zcr = self.feature_weights['zcr'] if score_3 is not None else 0.0
        total_w = w_ler + w_tilt + w_zcr
        score_sum = w_ler * score_1 + w_tilt * score_2
        if score_3 is not None:
            score_sum += w_zcr * score_3
        wind_prob_raw = float(score_sum / total_w)

        # 時間平滑
        wind_prob = self.alpha_prob * self.wind_prob_prev + (1 - self.alpha_prob) * wind_prob_raw

        # Hangover
        if wind_prob > self.severe_threshold:
            self.hangover_counter = self.hangover_frames
        elif self.hangover_counter > 0:
            self.hangover_counter -= 1
            # hangover 期間強制至少 mild
            wind_prob = max(wind_prob, self.mild_threshold + 0.01)

        # 嚴重度
        if wind_prob < self.mild_threshold:
            severity = 'none'
        elif wind_prob < self.severe_threshold:
            severity = 'mild'
        else:
            severity = 'severe'

        self.wind_prob_prev = wind_prob
        self.frame_count += 1

        return {
            'wind_probability': wind_prob,
            'wind_severity': severity,
            'features': {
                'low_energy_ratio': low_energy_ratio,
                'spectral_tilt_db': tilt_db,
                'zcr': zcr_value,
            },
            'hangover_active': self.hangover_counter > 0,
        }

    def reset(self):
        self.wind_prob_prev = 0.0
        self.hangover_counter = 0
        self.frame_count = 0

    def __repr__(self):
        return (f"WindDetector(mild={self.mild_threshold}, "
                f"severe={self.severe_threshold}, hangover={self.hangover_frames})")


if __name__ == "__main__":
    sr = 16000
    fft = 512
    n = fft // 2 + 1
    wd = WindDetector(sample_rate=sr, fft_size=fft)

    # 純語音 like：能量集中在 200-2000Hz
    mag_speech = np.zeros(n)
    mag_speech[6:60] = 1.0  # ~200Hz–2kHz
    # 純風 like：能量集中在 <500Hz，高頻極弱
    mag_wind = np.zeros(n)
    mag_wind[1:15] = 2.0
    mag_wind[15:] = 0.05
    # 純雜訊：平坦
    mag_noise = np.ones(n)

    for label, mag in [('speech', mag_speech), ('wind', mag_wind), ('noise', mag_noise)]:
        wd.reset()
        r = wd.detect(mag)
        print(f"{label:6s}  prob={r['wind_probability']:.3f}  sev={r['wind_severity']:6s}  "
              f"LER={r['features']['low_energy_ratio']:.2f}  "
              f"tilt={r['features']['spectral_tilt_db']:+6.2f}dB")
