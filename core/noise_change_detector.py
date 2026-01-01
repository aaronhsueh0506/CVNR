"""
Noise Change Detector - 噪聲場景變化檢測器

使用已計算的 posterior SNR (gamma) 檢測噪聲場景突變
- 輕量級實現，利用現有計算
- 適用於 V2/V3/V4（都有 gamma）
"""

import numpy as np
from typing import Optional


class NoiseChangeDetector:
    """
    基於 Posterior SNR 統計特性的噪聲場景變化檢測器

    原理：
        在非語音段，posterior SNR (γ = |Y|²/λ_d) 主要反映噪聲特性。
        當噪聲場景切換時（如從辦公室噪聲切換到街道噪聲），
        γ 的統計分布會出現系統性變化。

    檢測策略：
        1. 維護最近 N 幀的 γ 歷史（只在非語音段）
        2. 比較當前 γ 與歷史平均值
        3. 如果能量比 > 2.0 或 < 0.5，判定為場景變化

    參數:
        history_length: γ 歷史緩衝區長度（幀數）(default: 20)
        energy_ratio_high: 能量增加閾值 (default: 2.0)
        energy_ratio_low: 能量減少閾值 (default: 0.5)
        spp_threshold: SPP 閾值，低於此值才檢測 (default: 0.3)
        confirmation_frames: 連續確認幀數 (default: 3)
        cooldown_frames: 冷卻期幀數 (default: 50)
    """

    def __init__(
        self,
        history_length: int = 20,
        energy_ratio_high: float = 2.0,
        energy_ratio_low: float = 0.5,
        spp_threshold: float = 0.3,
        confirmation_frames: int = 3,
        cooldown_frames: int = 50
    ):
        self.history_length = history_length
        self.energy_ratio_high = energy_ratio_high
        self.energy_ratio_low = energy_ratio_low
        self.spp_threshold = spp_threshold
        self.confirmation_frames = confirmation_frames
        self.cooldown_frames = cooldown_frames

        # 狀態
        self.gamma_history = []  # 保存最近 N 幀的 gamma
        self.confirmation_counter = 0
        self.cooldown_counter = 0
        self.is_in_cooldown = False

    def detect(
        self,
        gamma: np.ndarray,
        spp: Optional[np.ndarray] = None
    ) -> bool:
        """
        檢測噪聲場景是否變化

        參數:
            gamma: 當前幀的 posterior SNR (n_freqs,)
            spp: 語音存在機率 (可選，用於 V3/V4) (n_freqs,)

        返回:
            是否檢測到噪聲變化
        """
        # 冷卻期檢查
        if self.is_in_cooldown:
            self.cooldown_counter += 1
            if self.cooldown_counter >= self.cooldown_frames:
                self.is_in_cooldown = False
                self.cooldown_counter = 0
            return False

        # SPP 檢查（只在非語音段檢測）
        if spp is not None:
            mean_spp = np.mean(spp)
            if mean_spp > self.spp_threshold:
                return False  # 語音段，不檢測

        # 積累歷史（只在非語音段）
        self.gamma_history.append(gamma.copy())

        # 保持固定長度
        if len(self.gamma_history) > self.history_length:
            self.gamma_history.pop(0)

        # 需要足夠的歷史數據
        if len(self.gamma_history) < self.history_length:
            return False

        # 計算參考值（歷史平均，排除當前幀）
        gamma_ref = np.mean(self.gamma_history[:-1], axis=0)

        # 計算當前幀與歷史平均的能量比
        energy_current = np.sum(gamma)
        energy_ref = np.sum(gamma_ref)
        energy_ratio = energy_current / (energy_ref + 1e-10)

        # 判斷是否超過閾值
        if (energy_ratio > self.energy_ratio_high or
            energy_ratio < self.energy_ratio_low):
            self.confirmation_counter += 1
        else:
            self.confirmation_counter = 0

        # 連續確認
        if self.confirmation_counter >= self.confirmation_frames:
            # 檢測到變化
            self.confirmation_counter = 0
            self.is_in_cooldown = True
            self.cooldown_counter = 0
            # 重置歷史（開始適應新場景）
            self.gamma_history = [gamma.copy()]
            return True

        return False

    def reset(self):
        """重置檢測器狀態"""
        self.gamma_history = []
        self.confirmation_counter = 0
        self.cooldown_counter = 0
        self.is_in_cooldown = False

    def get_status(self) -> dict:
        """獲取檢測器狀態（用於調試）"""
        return {
            'history_frames': len(self.gamma_history),
            'confirmation_counter': self.confirmation_counter,
            'is_in_cooldown': self.is_in_cooldown,
            'cooldown_counter': self.cooldown_counter
        }

    def __repr__(self):
        return (
            f"NoiseChangeDetector("
            f"history={self.history_length}, "
            f"energy_ratio=[{self.energy_ratio_low:.1f}, {self.energy_ratio_high:.1f}])"
        )
