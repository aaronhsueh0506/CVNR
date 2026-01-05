"""
Clean Audio Detector Module

檢測 clean 或 near-clean 音頻輸入，避免過度處理

Author: Phase 3 Optimization (2026-01-05)
Purpose: 當輸入為 clean 音頻時，自動檢測並減少降噪強度，保護語音質量
"""

import numpy as np


class CleanDetector:
    """
    Clean 音頻檢測器

    功能:
    1. 檢測輸入是否為 clean 或 near-clean 音頻
    2. 使用多重標準：SNR、噪聲 PSD、SPP
    3. 需要連續多幀確認才判定為 clean（避免誤判）

    檢測標準:
        - SNR > snr_threshold (默認 25dB)
        - 噪聲 PSD 極低 (< 1e-4)
        - SPP 平均值 > 0.8 (大部分是語音)
        - 持續 confirm_frames 幀 (默認 50 幀)

    用途:
        - 保護 clean.wav 作為輸入時的語音質量
        - 在高 SNR 場景自動切換到輕量降噪模式
    """

    def __init__(self, snr_threshold=25.0, confirm_frames=50):
        """
        初始化 Clean 檢測器

        Args:
            snr_threshold: SNR 閾值（dB），超過此值認為可能是 clean
            confirm_frames: 確認幀數，需要連續多少幀才判定為 clean
        """
        self.snr_threshold = snr_threshold
        self.confirm_frames = confirm_frames
        self.high_snr_count = 0  # 連續高 SNR 幀計數
        self.is_clean = False     # 當前是否判定為 clean

    def update(self, snr_db, noise_psd, spp=None):
        """
        更新 clean 檢測狀態

        Args:
            snr_db: 當前幀的 SNR (dB)
            noise_psd: 噪聲功率譜密度 (shape: [num_bins])
            spp: Speech Presence Probability (shape: [num_bins])，可選

        Returns:
            is_clean: 當前是否判定為 clean 音頻

        檢測邏輯:
            1. 檢查 SNR 是否超過閾值
            2. 檢查噪聲 PSD 是否極低
            3. (可選) 檢查 SPP 是否顯示高語音概率
            4. 連續滿足條件 confirm_frames 幀 → 判定為 clean
            5. 連續不滿足 10 幀 → 取消 clean 判定
        """
        # 計算噪聲 PSD 的平均能量
        avg_noise_psd = np.mean(noise_psd)

        # 檢查是否為 clean 幀的基本條件
        is_clean_frame = snr_db > self.snr_threshold and avg_noise_psd < 1e-4

        # 如果提供了 SPP，額外檢查語音存在概率
        if spp is not None:
            avg_spp = np.mean(spp)
            # 要求平均 SPP > 0.8（大部分是語音）
            is_clean_frame = is_clean_frame and avg_spp > 0.8

        # 更新連續高 SNR 幀計數
        if is_clean_frame:
            self.high_snr_count += 1
        else:
            # 快速衰減：不滿足條件時計數減 2（更快反應噪聲增加）
            self.high_snr_count = max(0, self.high_snr_count - 2)

        # 確認為 clean（需要連續多幀）
        if self.high_snr_count >= self.confirm_frames:
            self.is_clean = True
        elif self.high_snr_count < 10:
            # 連續不滿足 10 幀（相當於 5 次檢測失敗）→ 取消 clean 判定
            self.is_clean = False

        return self.is_clean

    def get_protection_factor(self):
        """
        獲取保護因子（用於調整降噪強度）

        Returns:
            protection_factor: 0.0-1.0
                - 0.0: 不是 clean，正常降噪
                - 0.5: 可能是 clean，輕量降噪
                - 1.0: 確定是 clean，最輕降噪

        用途:
            可以用於平滑地調整 g_min，而不是二元開關:
            g_min_final = g_min_adaptive * (1 - 0.5 * protection_factor) + 1.0 * (0.5 * protection_factor)
        """
        if not self.is_clean:
            return 0.0

        # 根據連續 clean 幀數計算保護強度
        # confirm_frames = 50 → 達到 50 幀時保護因子為 1.0
        # confirm_frames ~ 2*confirm_frames → 保護因子從 1.0 慢慢增加
        protection = min(1.0, self.high_snr_count / self.confirm_frames)

        return protection

    def reset(self):
        """重置檢測狀態（用於處理新音頻文件）"""
        self.high_snr_count = 0
        self.is_clean = False

    def get_status_string(self):
        """
        獲取當前狀態字符串（用於調試和日誌）

        Returns:
            status_str: 狀態描述字符串
        """
        if self.is_clean:
            return f"CLEAN (count={self.high_snr_count}, protection={self.get_protection_factor():.2f})"
        else:
            return f"NOISY (count={self.high_snr_count}/{self.confirm_frames})"


class AdaptiveCleanDetector(CleanDetector):
    """
    自適應 Clean 檢測器（進階版本）

    額外功能:
    - 動態調整 SNR 閾值
    - 根據音頻統計特性微調判定標準
    - 更精確的 clean 判定

    TODO: 未來擴展
    """

    def __init__(self, snr_threshold=25.0, confirm_frames=50, adaptive=True):
        super().__init__(snr_threshold, confirm_frames)
        self.adaptive = adaptive
        self.snr_stats = []  # 統計 SNR 歷史

    def update(self, snr_db, noise_psd, spp=None):
        """
        自適應更新（當前版本與基類相同，未來可擴展）

        未來可能的擴展:
        - 根據 SNR 方差判斷是否為 clean
        - 根據噪聲譜形狀判斷噪聲類型
        - 自適應調整 snr_threshold
        """
        # 保存 SNR 統計（最近 100 幀）
        self.snr_stats.append(snr_db)
        if len(self.snr_stats) > 100:
            self.snr_stats.pop(0)

        # 當前使用基類邏輯
        return super().update(snr_db, noise_psd, spp)

    def get_snr_stability(self):
        """
        獲取 SNR 穩定性（標準差）

        Returns:
            std: SNR 標準差，越小越穩定
        """
        if len(self.snr_stats) < 10:
            return None
        return np.std(self.snr_stats)


# 預設配置
DEFAULT_CONFIG = {
    "snr_threshold": 25.0,     # SNR 閾值 (dB)
    "confirm_frames": 50,      # 確認幀數
    "use_spp": True,           # 是否使用 SPP 檢測
}


if __name__ == "__main__":
    # 測試和驗證
    print("Clean Detector Module - Test\n")

    # 測試 Clean 檢測
    detector = CleanDetector(snr_threshold=25.0, confirm_frames=50)

    print("1. Simulating clean audio detection:")
    print("   (SNR > 25dB, low noise, high SPP for 60 frames)\n")

    # 模擬 clean 音頻場景
    for frame in range(60):
        # 模擬 clean 音頻：高 SNR，低噪聲，高 SPP
        snr_db = 30.0
        noise_psd = np.ones(256) * 1e-5
        spp = np.ones(256) * 0.9

        is_clean = detector.update(snr_db, noise_psd, spp)

        if frame % 10 == 0 or is_clean != detector.is_clean:
            print(f"   Frame {frame:3d}: {detector.get_status_string()}")

    print("\n2. Simulating noise increase:")
    print("   (SNR drops to 10dB, noise increases)\n")

    # 模擬噪聲增加
    for frame in range(60, 75):
        # 模擬噪聲增加
        snr_db = 10.0
        noise_psd = np.ones(256) * 0.01
        spp = np.ones(256) * 0.6

        is_clean = detector.update(snr_db, noise_psd, spp)

        if frame % 5 == 0 or is_clean != detector.is_clean:
            print(f"   Frame {frame:3d}: {detector.get_status_string()}")

    print("\n3. Testing protection factor:")
    detector_test = CleanDetector(snr_threshold=25.0, confirm_frames=50)

    for frame in range(0, 100, 10):
        # 模擬逐漸增加的 clean 確認
        snr_db = 30.0
        noise_psd = np.ones(256) * 1e-5
        spp = np.ones(256) * 0.9

        for _ in range(10):
            detector_test.update(snr_db, noise_psd, spp)

        protection = detector_test.get_protection_factor()
        print(f"   Frame {frame:3d}: protection_factor = {protection:.3f}, "
              f"status = {detector_test.get_status_string()}")

    print("\n✅ Clean Detector Module test completed!")
