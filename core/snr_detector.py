"""
SNR Detector Module

實時 SNR 檢測和自適應 g_min 計算

Author: Phase 3 Optimization (2026-01-05)
Purpose: 根據實時 SNR 動態調整降噪強度，解決固定 g_min 導致的 STOI 下降問題
"""

import numpy as np


class SnrDetector:
    """
    實時 SNR 檢測器

    功能:
    1. 估算當前幀的 SNR (基於後驗 SNR gamma)
    2. 根據 SNR 動態計算自適應 g_min
    3. 平滑 SNR 估計以避免劇烈波動
    """

    def __init__(self, smoothing_factor=0.9):
        """
        初始化 SNR 檢測器

        Args:
            smoothing_factor: SNR 平滑因子 (0-1)，越接近 1 越平滑
        """
        self.smoothing_factor = smoothing_factor
        self.snr_history = []

    def estimate_frame_snr(self, Y_psd, noise_psd):
        """
        估算當前幀的 SNR

        Args:
            Y_psd: 當前幀的功率譜密度 (shape: [num_bins])
            noise_psd: 噪聲功率譜密度估計 (shape: [num_bins])

        Returns:
            snr_db: SNR 估計值（dB）

        原理:
            - 使用後驗 SNR (gamma = Y_psd / noise_psd)
            - 只計算語音頻段 (300Hz - 4000Hz)
            - SNR = mean(gamma) - 1.0 (減去噪聲本身的貢獻)
        """
        # 計算後驗 SNR (gamma)
        gamma = Y_psd / (noise_psd + 1e-10)

        # 只使用語音頻段 (300Hz - 4000Hz for 16kHz sampling)
        # 假設 512 FFT, 16kHz → bin 10~128 (約 310Hz ~ 4000Hz)
        # bin_freq = k * sr / fft_size
        # 300Hz: k = 300 * 512 / 16000 ≈ 9.6 → 10
        # 4000Hz: k = 4000 * 512 / 16000 = 128
        num_bins = len(gamma)
        if num_bins >= 128:
            speech_gamma = gamma[10:128]
        else:
            # 如果 FFT 尺寸較小，使用全部頻段（除去最低和最高頻段）
            low_idx = max(1, int(num_bins * 0.05))
            high_idx = int(num_bins * 0.85)
            speech_gamma = gamma[low_idx:high_idx]

        # SNR = mean(gamma) - 1 (減去噪聲本身)
        snr_linear = np.mean(speech_gamma) - 1.0
        snr_linear = max(snr_linear, 1e-10)  # 避免 log(0)

        snr_db = 10 * np.log10(snr_linear)

        # 平滑處理（指數移動平均）
        if len(self.snr_history) > 0:
            snr_db = self.smoothing_factor * self.snr_history[-1] + \
                     (1 - self.smoothing_factor) * snr_db

        self.snr_history.append(snr_db)

        # 保留最近 100 幀歷史（避免內存無限增長）
        if len(self.snr_history) > 100:
            self.snr_history.pop(0)

        return snr_db

    @staticmethod
    def get_adaptive_g_min(snr_db, base_g_min_db=-15.0):
        """
        根據 SNR 動態調整 g_min (Phase 4: 7 級細化分級)

        Args:
            snr_db: 當前 SNR (dB)
            base_g_min_db: 基準 g_min (dB)，默認 -10dB (Phase 4 優化)

        Returns:
            g_min: 線性域的最小增益

        設計原理:
            SNR 越高 → 語音越清晰 → g_min 應該越大（降噪越輕）
            SNR 越低 → 噪聲越強 → g_min 應該越小（降噪越強）

        Phase 4 細化分級策略 (7 級):
            - 極低 SNR (< -5dB): base - 3dB → 最強降噪
            - 很低 SNR (-5~0dB): base → 強降噪
            - 低 SNR (0~5dB): base + 2dB → 中強降噪
            - 中低 SNR (5~10dB): base + 4dB → 中等降噪
            - 中高 SNR (10~15dB): base + 6dB → 輕降噪
            - 高 SNR (15~20dB): base + 8dB → 輕量降噪
            - 極高 SNR (> 20dB): base + 10dB → 最輕降噪（接近 clean）

        示例（base_g_min_db = -10, Phase 4）:
            SNR = -10dB → g_min_db = -13dB → g_min = 0.0501 (95% 抑制)
            SNR = 0dB   → g_min_db = -10dB → g_min = 0.1000 (90% 抑制)
            SNR = 5dB   → g_min_db = -8dB  → g_min = 0.1585 (84% 抑制)
            SNR = 10dB  → g_min_db = -6dB  → g_min = 0.2512 (75% 抑制) ⭐
            SNR = 15dB  → g_min_db = -4dB  → g_min = 0.3981 (60% 抑制) ⭐
            SNR = 20dB  → g_min_db = -2dB  → g_min = 0.6310 (37% 抑制)
            SNR = 30dB  → g_min_db = 0dB   → g_min = 1.0000 (無抑制)
        """
        if snr_db < -5:
            # 極低 SNR: 額外降低 3dB（最強抑制）
            g_min_db = base_g_min_db - 3
        elif snr_db < 0:
            # 很低 SNR: 使用基準值（強抑制）
            g_min_db = base_g_min_db
        elif snr_db < 5:
            # 低 SNR: 提高 2dB（中強降噪）
            g_min_db = base_g_min_db + 2
        elif snr_db < 10:
            # 中低 SNR: 提高 4dB（中等降噪）
            g_min_db = base_g_min_db + 4
        elif snr_db < 15:
            # 中高 SNR: 提高 6dB（輕降噪）⭐ 關鍵優化
            g_min_db = base_g_min_db + 6
        elif snr_db < 20:
            # 高 SNR: 提高 8dB（輕量降噪）⭐ 關鍵優化
            g_min_db = base_g_min_db + 8
        else:
            # 極高 SNR/Clean: 提高 10dB（最小抑制）
            g_min_db = base_g_min_db + 10

        # 轉換為線性域
        g_min = 10 ** (g_min_db / 10)

        return g_min

    def get_average_snr(self):
        """
        獲取最近幀的平均 SNR

        Returns:
            avg_snr_db: 平均 SNR (dB)，如果沒有歷史則返回 None
        """
        if len(self.snr_history) == 0:
            return None
        return np.mean(self.snr_history)

    def reset(self):
        """重置 SNR 歷史（用於處理新音頻文件）"""
        self.snr_history = []


# SNR 分級參考表（用於文檔和調試）
SNR_LEVELS = {
    "extreme_low": {"range": "< -5dB", "delta": -3, "description": "極低 SNR，最強降噪"},
    "low": {"range": "-5 ~ 5dB", "delta": 0, "description": "低 SNR，強降噪"},
    "medium": {"range": "5 ~ 15dB", "delta": +3, "description": "中等 SNR，中等降噪"},
    "high": {"range": "15 ~ 25dB", "delta": +6, "description": "高 SNR，輕降噪"},
    "extreme_high": {"range": "> 25dB", "delta": +9, "description": "極高 SNR/Clean，最輕降噪"},
}


def print_snr_table(base_g_min_db=-15.0):
    """
    打印 SNR 分級表（用於調試和驗證）

    Args:
        base_g_min_db: 基準 g_min (dB)
    """
    print("\n" + "="*80)
    print(f"SNR Adaptive g_min Table (base_g_min_db = {base_g_min_db} dB)")
    print("="*80)
    print(f"{'SNR Range':<15} {'g_min_db':>10} {'g_min (linear)':>15} {'Description':<25}")
    print("-"*80)

    test_snrs = [-10, 0, 10, 20, 30]
    for snr in test_snrs:
        g_min = SnrDetector.get_adaptive_g_min(snr, base_g_min_db)
        g_min_db = 10 * np.log10(g_min)

        if snr < -5:
            range_desc = "< -5dB"
            desc = "極低 SNR，最強降噪"
        elif snr < 5:
            range_desc = "-5 ~ 5dB"
            desc = "低 SNR，強降噪"
        elif snr < 15:
            range_desc = "5 ~ 15dB"
            desc = "中等 SNR，中等降噪"
        elif snr < 25:
            range_desc = "15 ~ 25dB"
            desc = "高 SNR，輕降噪"
        else:
            range_desc = "> 25dB"
            desc = "極高 SNR/Clean，最輕降噪"

        print(f"{range_desc:<15} {g_min_db:>10.1f} {g_min:>15.4f} {desc:<25}")

    print("="*80 + "\n")


if __name__ == "__main__":
    # 測試和驗證
    print("SNR Detector Module - Test")

    # 測試 SNR 檢測
    detector = SnrDetector(smoothing_factor=0.9)

    # 模擬不同 SNR 場景
    print("\n1. Testing SNR estimation:")
    test_cases = [
        (1.0, 0.1, "High SNR (10dB)"),
        (1.0, 1.0, "Low SNR (0dB)"),
        (0.1, 1.0, "Very Low SNR (-10dB)"),
    ]

    for Y_psd_val, noise_psd_val, desc in test_cases:
        Y_psd = np.ones(256) * Y_psd_val
        noise_psd = np.ones(256) * noise_psd_val
        snr_db = detector.estimate_frame_snr(Y_psd, noise_psd)
        print(f"  {desc}: SNR = {snr_db:.2f} dB")

    # 測試自適應 g_min
    print("\n2. Testing adaptive g_min:")
    print_snr_table(base_g_min_db=-15.0)

    print("Testing with V3-2 base (-12dB):")
    print_snr_table(base_g_min_db=-12.0)
