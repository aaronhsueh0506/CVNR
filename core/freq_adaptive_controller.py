"""
Frequency-Adaptive Parameter Controller

根據 WindDetector 輸出的 wind_probability 與 severity，為每個頻率 bin 產生
時變的 g_min / alpha_xi / alpha_g 參數。

設計要點：
- 依 freq_band_edges 劃分頻段，每段有 [normal, mild, severe] profile
- 依 wind_probability 在相鄰 severity 之間線性插值，避免硬切造成突跳
- wind_probability=0 時輸出完全等同 normal profile（保 backward compat）

參考：V4 規格書 §3.2
"""

import numpy as np
from typing import Optional


class FreqAdaptiveController:
    """頻段自適應參數控制器

    參數:
        sample_rate: 採樣率 (Hz)
        fft_size: FFT 點數
        freq_band_edges: 頻段邊界 (Hz)，N+1 個值構成 N 段
        g_min_profile_db: 每段 [normal, mild, severe] 最小增益 (dB)
        alpha_xi_profile: 每段 [normal, mild, severe] SPP DD 平滑
        alpha_g_profile: 每段 [normal, mild, severe] 增益時間平滑
        mild_threshold / severe_threshold: 與 WindDetector 一致，用於線性插值
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        fft_size: int = 512,
        freq_band_edges: Optional[list] = None,
        g_min_profile_db: Optional[dict] = None,
        alpha_xi_profile: Optional[dict] = None,
        alpha_g_profile: Optional[dict] = None,
        mild_threshold: float = 0.4,
        severe_threshold: float = 0.75,
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.n_freqs = fft_size // 2 + 1

        # 預設頻段：[0, 200, 800, 4000, 8000] Hz → 4 段
        if freq_band_edges is None:
            freq_band_edges = [0, 200, 800, 4000, 8000]
        self.freq_band_edges = freq_band_edges
        self.n_bands = len(freq_band_edges) - 1

        # 預設 profile
        if g_min_profile_db is None:
            g_min_profile_db = {
                'band_0': [-15, -25, -35],  # 0-200 Hz：風聲重災區，severe 時壓到 -35dB
                'band_1': [-15, -20, -25],  # 200-800 Hz
                'band_2': [-15, -15, -18],  # 800-4000 Hz
                'band_3': [-15, -15, -15],  # >4000 Hz
            }
        if alpha_xi_profile is None:
            alpha_xi_profile = {
                'band_0': [0.88, 0.80, 0.70],  # 風聲時減少平滑，讓 DD 更快反應
                'band_1': [0.88, 0.85, 0.80],
                'band_2': [0.88, 0.88, 0.88],
                'band_3': [0.88, 0.88, 0.90],
            }
        if alpha_g_profile is None:
            alpha_g_profile = {
                'band_0': [0.88, 0.80, 0.70],
                'band_1': [0.88, 0.85, 0.80],
                'band_2': [0.88, 0.88, 0.88],
                'band_3': [0.88, 0.88, 0.90],
            }

        self.g_min_profile_db = g_min_profile_db
        self.alpha_xi_profile = alpha_xi_profile
        self.alpha_g_profile = alpha_g_profile

        self.mild_threshold = mild_threshold
        self.severe_threshold = severe_threshold

        # 預計算每個 freq bin 屬於哪個 band
        freq_per_bin = sample_rate / fft_size
        self._bin_band_idx = np.zeros(self.n_freqs, dtype=np.int32)
        for k in range(self.n_freqs):
            f = k * freq_per_bin
            for b in range(self.n_bands):
                if freq_band_edges[b] <= f < freq_band_edges[b + 1]:
                    self._bin_band_idx[k] = b
                    break
            else:
                # 超出最後邊界 → 併入最後一段
                self._bin_band_idx[k] = self.n_bands - 1

        # 預建 per-band 的 (normal, mild, severe) 陣列
        self._g_min_db_bands = np.array(
            [g_min_profile_db[f'band_{b}'] for b in range(self.n_bands)]
        )  # shape (n_bands, 3)
        self._alpha_xi_bands = np.array(
            [alpha_xi_profile[f'band_{b}'] for b in range(self.n_bands)]
        )
        self._alpha_g_bands = np.array(
            [alpha_g_profile[f'band_{b}'] for b in range(self.n_bands)]
        )

    def get_params(
        self,
        wind_probability: float,
        wind_severity: str = 'none',
    ) -> dict:
        """根據 wind_probability 線性插值出每個 bin 的參數陣列。

        返回:
            dict {g_min: (n_freqs,) linear scale, alpha_xi: (n_freqs,), alpha_g: (n_freqs,)}
        """
        p = float(wind_probability)

        # 在 [normal(0), mild(mild_th), severe(severe_th)] 之間插值
        if p <= 0.0:
            # 完全 normal：索引 0
            g_min_db_bands = self._g_min_db_bands[:, 0]
            alpha_xi_bands = self._alpha_xi_bands[:, 0]
            alpha_g_bands = self._alpha_g_bands[:, 0]
        elif p < self.mild_threshold:
            # normal → mild
            alpha = p / self.mild_threshold
            g_min_db_bands = (
                (1 - alpha) * self._g_min_db_bands[:, 0]
                + alpha * self._g_min_db_bands[:, 1]
            )
            alpha_xi_bands = (
                (1 - alpha) * self._alpha_xi_bands[:, 0]
                + alpha * self._alpha_xi_bands[:, 1]
            )
            alpha_g_bands = (
                (1 - alpha) * self._alpha_g_bands[:, 0]
                + alpha * self._alpha_g_bands[:, 1]
            )
        elif p < self.severe_threshold:
            # mild → severe
            alpha = (p - self.mild_threshold) / (self.severe_threshold - self.mild_threshold)
            g_min_db_bands = (
                (1 - alpha) * self._g_min_db_bands[:, 1]
                + alpha * self._g_min_db_bands[:, 2]
            )
            alpha_xi_bands = (
                (1 - alpha) * self._alpha_xi_bands[:, 1]
                + alpha * self._alpha_xi_bands[:, 2]
            )
            alpha_g_bands = (
                (1 - alpha) * self._alpha_g_bands[:, 1]
                + alpha * self._alpha_g_bands[:, 2]
            )
        else:
            # 完全 severe
            g_min_db_bands = self._g_min_db_bands[:, 2]
            alpha_xi_bands = self._alpha_xi_bands[:, 2]
            alpha_g_bands = self._alpha_g_bands[:, 2]

        # 展開到每個 freq bin
        g_min_db_per_bin = g_min_db_bands[self._bin_band_idx]
        g_min_per_bin = 10 ** (g_min_db_per_bin / 10.0)
        alpha_xi_per_bin = alpha_xi_bands[self._bin_band_idx]
        alpha_g_per_bin = alpha_g_bands[self._bin_band_idx]

        return {
            'g_min': g_min_per_bin,
            'alpha_xi': alpha_xi_per_bin,
            'alpha_g': alpha_g_per_bin,
        }

    def __repr__(self):
        return (f"FreqAdaptiveController(n_bands={self.n_bands}, "
                f"edges={self.freq_band_edges})")


if __name__ == "__main__":
    ctrl = FreqAdaptiveController()
    print("Test at wind_prob = 0.0 (normal):")
    p0 = ctrl.get_params(0.0)
    print(f"  g_min range: {10*np.log10(p0['g_min'].min()):.1f} ~ {10*np.log10(p0['g_min'].max()):.1f} dB")

    print("\nTest at wind_prob = 0.5 (mild~severe):")
    p5 = ctrl.get_params(0.5)
    print(f"  g_min range: {10*np.log10(p5['g_min'].min()):.1f} ~ {10*np.log10(p5['g_min'].max()):.1f} dB")

    print("\nTest at wind_prob = 1.0 (severe):")
    p1 = ctrl.get_params(1.0)
    print(f"  g_min at DC: {10*np.log10(p1['g_min'][0]):.1f} dB (應 ~-35)")
    print(f"  g_min at 6kHz: {10*np.log10(p1['g_min'][192]):.1f} dB (應 ~-15)")
