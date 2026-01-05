"""
Transition Detector - 語音過渡檢測器
Phase 6 新增功能

用於檢測噪音→語音的過渡點，觸發快速適應模式
"""

import numpy as np
from typing import Tuple


class TransitionDetector:
    """
    檢測 SPP 跳變以識別噪音→語音過渡

    設計理念:
    - 檢測 SPP 平均值的突然上升
    - 需要連續確認以避免誤觸發
    - 觸發後進入加速模式一定時間
    - 冷卻期避免頻繁切換

    參數:
        spp_jump_threshold: SPP 跳變閾值（預設 0.2）
        confirm_frames: 確認幀數（預設 2）
        boost_duration: 加速持續幀數（預設 20）
        cooldown_frames: 冷卻幀數（預設 30）
        avg_window: SPP 平均窗口大小（預設 5，取低頻部分）

    狀態機:
        IDLE → CONFIRMING → BOOSTING → COOLDOWN → IDLE
    """

    # 狀態定義
    STATE_IDLE = 0
    STATE_CONFIRMING = 1
    STATE_BOOSTING = 2
    STATE_COOLDOWN = 3

    def __init__(
        self,
        spp_jump_threshold: float = 0.2,
        confirm_frames: int = 2,
        boost_duration: int = 20,
        cooldown_frames: int = 30,
        avg_window: int = 5
    ):
        self.spp_jump_threshold = spp_jump_threshold
        self.confirm_frames = confirm_frames
        self.boost_duration = boost_duration
        self.cooldown_frames = cooldown_frames
        self.avg_window = avg_window

        # 狀態變量
        self.state = self.STATE_IDLE
        self.spp_prev = None
        self.confirm_count = 0
        self.boost_count = 0
        self.cooldown_count = 0

    def detect(self, spp: np.ndarray) -> Tuple[bool, str]:
        """
        檢測當前幀是否需要加速

        參數:
            spp: 當前幀的 SPP (n_freqs,)

        返回:
            (in_boost_mode, state_name): (是否處於加速模式, 當前狀態名稱)
        """
        # 計算 SPP 平均值（使用低頻部分，更穩定）
        spp_avg = np.mean(spp[:min(len(spp), self.avg_window)])

        # 初始化
        if self.spp_prev is None:
            self.spp_prev = spp_avg
            return False, "IDLE"

        # 計算 SPP 變化
        spp_delta = spp_avg - self.spp_prev

        # 狀態機
        if self.state == self.STATE_IDLE:
            # 檢測跳變
            if spp_delta > self.spp_jump_threshold:
                self.state = self.STATE_CONFIRMING
                self.confirm_count = 1
                state_name = "CONFIRMING"
                in_boost = False
            else:
                state_name = "IDLE"
                in_boost = False

        elif self.state == self.STATE_CONFIRMING:
            # 確認跳變
            if spp_delta > self.spp_jump_threshold:
                self.confirm_count += 1
                if self.confirm_count >= self.confirm_frames:
                    # 確認完成，進入加速模式
                    self.state = self.STATE_BOOSTING
                    self.boost_count = 0
                    state_name = "BOOSTING"
                    in_boost = True
                else:
                    state_name = "CONFIRMING"
                    in_boost = False
            else:
                # 跳變消失，回到 IDLE
                self.state = self.STATE_IDLE
                self.confirm_count = 0
                state_name = "IDLE"
                in_boost = False

        elif self.state == self.STATE_BOOSTING:
            # 加速模式計時
            self.boost_count += 1
            if self.boost_count >= self.boost_duration:
                # 加速結束，進入冷卻
                self.state = self.STATE_COOLDOWN
                self.cooldown_count = 0
                state_name = "COOLDOWN"
                in_boost = False
            else:
                state_name = "BOOSTING"
                in_boost = True

        elif self.state == self.STATE_COOLDOWN:
            # 冷卻期計時
            self.cooldown_count += 1
            if self.cooldown_count >= self.cooldown_frames:
                # 冷卻結束，回到 IDLE
                self.state = self.STATE_IDLE
                state_name = "IDLE"
                in_boost = False
            else:
                state_name = "COOLDOWN"
                in_boost = False

        else:
            # 未知狀態（不應發生）
            self.state = self.STATE_IDLE
            state_name = "IDLE"
            in_boost = False

        # 更新歷史
        self.spp_prev = spp_avg

        return in_boost, state_name

    def reset(self):
        """重置檢測器"""
        self.state = self.STATE_IDLE
        self.spp_prev = None
        self.confirm_count = 0
        self.boost_count = 0
        self.cooldown_count = 0

    def get_state_name(self) -> str:
        """獲取當前狀態名稱"""
        state_names = {
            self.STATE_IDLE: "IDLE",
            self.STATE_CONFIRMING: "CONFIRMING",
            self.STATE_BOOSTING: "BOOSTING",
            self.STATE_COOLDOWN: "COOLDOWN"
        }
        return state_names.get(self.state, "UNKNOWN")

    def __repr__(self):
        return (f"TransitionDetector("
                f"threshold={self.spp_jump_threshold}, "
                f"confirm={self.confirm_frames}, "
                f"boost={self.boost_duration}, "
                f"cooldown={self.cooldown_frames})")


if __name__ == "__main__":
    # 測試示例
    print("Transition Detector 測試\n")

    detector = TransitionDetector(
        spp_jump_threshold=0.2,
        confirm_frames=2,
        boost_duration=5,
        cooldown_frames=10
    )

    print(f"檢測器配置: {detector}\n")

    # 模擬 SPP 序列
    # 前 10 幀: 低 SPP (噪音)
    # 11-12 幀: 跳變 (確認)
    # 13-17 幀: 高 SPP (加速)
    # 18-27 幀: 冷卻
    # 28+ 幀: 正常

    spp_sequence = []
    for i in range(30):
        if i < 10:
            spp_avg = 0.2  # 噪音段
        elif i < 20:
            spp_avg = 0.7  # 語音段（觸發跳變）
        else:
            spp_avg = 0.6  # 持續語音

        # 模擬頻譜（簡化為常數）
        spp = np.full(10, spp_avg)
        spp_sequence.append(spp)

    # 逐幀檢測
    print("幀號 | SPP_avg | 狀態        | Boost")
    print("-" * 45)

    for i, spp in enumerate(spp_sequence):
        in_boost, state_name = detector.detect(spp)
        spp_avg = np.mean(spp)
        boost_str = "YES" if in_boost else "NO"
        print(f"{i:3d}  | {spp_avg:.2f}    | {state_name:11s} | {boost_str}")

    print("\n測試完成!")
    print("\n預期行為:")
    print("- 幀 0-9: IDLE (噪音段)")
    print("- 幀 10: CONFIRMING (檢測到跳變)")
    print("- 幀 11: CONFIRMING 或 BOOSTING (達到確認幀數)")
    print("- 幀 12-16: BOOSTING (加速 5 幀)")
    print("- 幀 17-26: COOLDOWN (冷卻 10 幀)")
    print("- 幀 27+: IDLE (恢復正常)")
