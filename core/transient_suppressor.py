"""
Transient Suppressor - 時域 buffeting 抑制器

在時域偵測風聲在 micˊ 上造成的短時能量激增 (buffeting)，以 attack/release
envelope 平滑抑制，避免對語音爆破音 (/p/, /t/, /k/) 造成過度影響。

流程：
1. pre-filter 80Hz 高通（選配）去除 DC + rumble，避免被視為 transient
2. 短窗能量 E_short / 長窗能量 E_long，比值 > threshold 判定為 transient
3. 用 attack/release envelope 平滑 gain，避免產生 click

參考：V4 規格書 §3.3
"""

import numpy as np
from typing import Optional


class TransientSuppressor:
    """時域 transient 抑制器。

    參數:
        sample_rate: 採樣率 (Hz)
        short_window_ms: 短窗 (ms)，抓 buffeting 瞬間
        long_window_ms: 長窗 (ms)，背景能量
        threshold_db: E_short/E_long 超過此 dB 視為 transient
        suppression_db: transient 段 gain (dB)，負數
        attack_ms: gain 下降時常數（快速進入壓制）
        release_ms: gain 上升時常數（慢速退出）
        enable_highpass_prefilter: 是否啟用 80Hz 高通 pre-filter
        highpass_cutoff_hz: 高通截止頻率 (Hz)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        short_window_ms: float = 10.0,
        long_window_ms: float = 500.0,
        threshold_db: float = 15.0,
        suppression_db: float = -12.0,
        attack_ms: float = 2.0,
        release_ms: float = 20.0,
        enable_highpass_prefilter: bool = True,
        highpass_cutoff_hz: float = 80.0,
    ):
        self.sample_rate = sample_rate
        self.short_window = max(1, int(short_window_ms * sample_rate / 1000))
        self.long_window = max(1, int(long_window_ms * sample_rate / 1000))

        self.threshold_linear = 10 ** (threshold_db / 10)  # E 是功率 → 10*log10
        self.suppression_gain = 10 ** (suppression_db / 20)  # gain 是振幅 → 20*log10

        # 一階 IIR attack/release 係數：y[n] = alpha * y[n-1] + (1-alpha) * x[n]
        # time constant τ ↔ alpha = exp(-1 / (τ * fs))
        self.alpha_attack = float(np.exp(-1.0 / (attack_ms * 1e-3 * sample_rate)))
        self.alpha_release = float(np.exp(-1.0 / (release_ms * 1e-3 * sample_rate)))

        self.enable_highpass = enable_highpass_prefilter
        self.highpass_cutoff_hz = highpass_cutoff_hz
        if enable_highpass_prefilter:
            self._hp_coeffs = self._design_highpass(highpass_cutoff_hz, sample_rate)
        else:
            self._hp_coeffs = None

        # 狀態
        self.gain_prev = 1.0
        self.short_rms_prev = 0.0
        self.long_rms_prev = 0.0

    def _design_highpass(self, fc: float, fs: float):
        """簡易一階 butterworth 高通係數（y[n] = b0*x[n] + b1*x[n-1] - a1*y[n-1]）。"""
        # bilinear 一階 HP
        w0 = 2 * np.pi * fc / fs
        alpha = np.tan(w0 / 2)
        # 一階 HP: H(s) = s / (s + w0) → bilinear
        b0 = 1.0 / (1.0 + alpha)
        b1 = -b0
        a1 = (alpha - 1.0) / (alpha + 1.0)
        return (b0, b1, a1)

    def _apply_highpass(self, x: np.ndarray) -> np.ndarray:
        b0, b1, a1 = self._hp_coeffs
        y = np.zeros_like(x)
        x_prev = 0.0
        y_prev = 0.0
        for n in range(len(x)):
            y[n] = b0 * x[n] + b1 * x_prev - a1 * y_prev
            x_prev = x[n]
            y_prev = y[n]
        return y

    def process(self, signal: np.ndarray) -> np.ndarray:
        """處理整段 time-domain 信號，返回 buffeting 抑制後版本。"""
        if self.enable_highpass:
            x_for_detect = self._apply_highpass(signal)
        else:
            x_for_detect = signal

        # 短/長窗 RMS（用遞迴 IIR 平均近似滑動窗，避免 O(N*W)）
        n = len(signal)
        alpha_short = 1.0 - 1.0 / self.short_window
        alpha_long = 1.0 - 1.0 / self.long_window

        out = np.empty_like(signal)
        short_power = self.short_rms_prev
        long_power = self.long_rms_prev
        gain = self.gain_prev

        for i in range(n):
            x2 = x_for_detect[i] ** 2
            short_power = alpha_short * short_power + (1 - alpha_short) * x2
            long_power = alpha_long * long_power + (1 - alpha_long) * x2

            ratio = short_power / (long_power + 1e-12)
            target_gain = self.suppression_gain if ratio > self.threshold_linear else 1.0

            # attack（gain 下降）快、release（gain 上升）慢
            if target_gain < gain:
                gain = self.alpha_attack * gain + (1 - self.alpha_attack) * target_gain
            else:
                gain = self.alpha_release * gain + (1 - self.alpha_release) * target_gain

            out[i] = signal[i] * gain

        self.short_rms_prev = short_power
        self.long_rms_prev = long_power
        self.gain_prev = gain

        return out

    def reset(self):
        self.gain_prev = 1.0
        self.short_rms_prev = 0.0
        self.long_rms_prev = 0.0


if __name__ == "__main__":
    sr = 16000
    ts = TransientSuppressor(sample_rate=sr)
    t = np.linspace(0, 1, sr)
    # 背景白噪 + 一個 20ms transient burst
    signal = 0.05 * np.random.randn(sr)
    burst_start = sr // 2
    burst_len = int(0.02 * sr)
    signal[burst_start:burst_start + burst_len] += 1.0 * np.random.randn(burst_len)
    out = ts.process(signal)
    rms_sig = np.sqrt(np.mean(signal[burst_start:burst_start + burst_len] ** 2))
    rms_out = np.sqrt(np.mean(out[burst_start:burst_start + burst_len] ** 2))
    suppression_db = 20 * np.log10(rms_out / (rms_sig + 1e-12))
    print(f"burst RMS in={rms_sig:.3f}  out={rms_out:.3f}  suppression={suppression_db:+.1f} dB")
