"""
MCRA - Minima Controlled Recursive Averaging
Cohen & Berdugo (2002)

用於 V3 系列降噪器

v3.0: 升級為雙視窗最小值追蹤 (Dual-Window Minima Tracking)
- 整合場景轉換偵測功能
- 移除外部 NoiseChangeDetector 依賴
- 自動適應噪聲場景變化

特點：
- 時間平滑：減少功率譜波動
- 雙視窗最小值追蹤：快速適應噪聲變化（預設）
- 單視窗最小值追蹤：傳統 FIFO 緩衝區方法（可選）
- SPP 門控：語音段自動減少噪聲更新

============================================================================
雙視窗最小值追蹤 (Dual-Window Minima Tracking) 原理
============================================================================

問題：傳統單視窗最小值追蹤的局限性
--------------------------------------
- 使用 FIFO 緩衝區存儲過去 L 幀的最小值
- 當噪聲突然增加時，需要等待整個 L 幀窗口更新完畢
- 適應時間 = L × 幀移 (例如 96 × 10ms = 960ms)

解決方案：雙視窗結構
--------------------------------------
Cohen & Berdugo 2002 提出使用兩個重疊的子視窗：

┌─────────────────────────────────────────────┐
│               全局最小值 S_min               │
├─────────────────────┬───────────────────────┤
│   stored_min        │      S_min_sw         │
│   (上一輪最小值)     │    (當前子視窗最小值)   │
├─────────────────────┴───────────────────────┤
│          ← counter 計數 (0 到 L-1) →         │
└─────────────────────────────────────────────┘

運作流程 (每幀執行)：
1. S_min = min(S_min, S)         # 持續追蹤全局最小值
2. S_min_sw = min(S_min_sw, S)   # 持續追蹤子視窗最小值
3. counter++

當 counter >= L 時 (每 L 幀觸發一次)：
4. S_min = min(stored_min, S_min_sw)  # 合併兩個子視窗
5. stored_min = S_min_sw              # 保存當前子視窗最小值
6. S_min_sw = S                       # 重置子視窗
7. counter = 0

優點：
- 自動適應噪聲場景變化（最多 L 幀延遲）
- 無需外部檢測器判斷場景變化
- 記憶體效率高（只需 3 個陣列，不需要 FIFO 緩衝區）
- 計算效率高（只有 min 運算）

實例（L=96, 幀移=10ms）：
- 正常運作：每 960ms 自動刷新最小值
- 噪聲突增：最多 960ms 後 S_min 會追上新噪聲水平
- 噪聲突降：S_min 立即跟隨（因為 min 運算）

============================================================================

參考文獻：
    Cohen, I. & Berdugo, B. (2002). "Noise estimation by minima controlled
    recursive averaging for robust speech enhancement." IEEE Signal Processing
    Letters, 9(1), 12-15.
"""

import numpy as np
from typing import Optional
from collections import deque


class McraNoiseEstimator:
    """
    MCRA 噪聲估計器 (整合 Dual-Window Minima Tracking)

    演算法步驟：
    1. 時間平滑：S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
    2. 雙視窗最小值追蹤：
       - S_min = min(S_min, S)
       - S_min_sw = min(S_min_sw, S)
       - 每 L 幀更新：S_min = min(stored_min, S_min_sw)
    3. 語音指示器：I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
    4. SPP 平滑：p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
    5. 噪聲更新：α̃_d = α_d + (1-α_d)·p(k,l)
                 N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²

    參數:
        alpha_s: 時間平滑因子 (0.85-0.95)，越大越平滑
        alpha_d: 噪聲更新基礎速率 (0.80-0.90)，越大更新越慢
        alpha_p: SPP 平滑因子 (0.1-0.3)，越大 SPP 變化越平緩
        L: 最小值窗口長度（幀），約 1 秒 @ 10ms 幀移
        delta_db: 偏差補償（dB），語音檢測閾值
        num_init_frames: 初始化使用的幀數
        use_dual_window: 使用雙視窗模式 (True) 或單視窗模式 (False)
            - True（預設）：記憶體效率高 O(3×n_freqs)，計算效率高 O(1)
            - False：傳統 FIFO 緩衝區，記憶體用量 O(L×n_freqs)，計算 O(L)
    """

    def __init__(
        self,
        alpha_s: float = 0.9,
        alpha_d: float = 0.85,
        alpha_p: float = 0.2,
        L: int = 96,
        delta_db: float = 5.0,
        num_init_frames: int = 20,
        use_dual_window: bool = True,  # True=雙視窗, False=單視窗(FIFO)
        spp_hard_threshold: float = 0.8  # 保留向後兼容（未使用）
    ):
        self.alpha_s = alpha_s
        self.alpha_d = alpha_d
        self.alpha_p = alpha_p
        self.L = L
        self.delta = 10 ** (delta_db / 10)  # 線性域的 delta
        self.num_init_frames = num_init_frames
        self.use_dual_window = use_dual_window

        # 狀態變量
        self.noise_psd = None       # 噪聲功率譜密度
        self.S = None               # 時間平滑後的功率譜
        self.S_min = None           # 全局最小值
        self.S_min_sw = None        # 子視窗最小值 (雙視窗專用)
        self.stored_min = None      # 存儲的最小值 (雙視窗專用)
        self.min_buffer = None      # FIFO 緩衝區 (單視窗專用)
        self.spp = None             # Speech Presence Probability

        self.counter = 0            # 視窗計數器 (雙視窗專用)
        self.is_initialized = False
        self.frame_count = 0

        # 場景轉換偵測
        self.prev_frame_energy = 1.0  # 前一幀能量（初始化為 1 避免除零）

    def estimate(self, magnitude_spectrum: np.ndarray) -> np.ndarray:
        """
        初始化噪聲估計

        v2.1: 改用 20th 百分位數作為噪聲估計，避免語音幀導致過高估計。

        參數:
            magnitude_spectrum: 幅度譜 (n_frames, n_freqs) 或 (n_freqs,)

        返回:
            noise_psd: 初始噪聲功率譜密度 (n_freqs,)
        """
        if magnitude_spectrum.ndim == 1:
            magnitude_spectrum = magnitude_spectrum.reshape(1, -1)

        n_freqs = magnitude_spectrum.shape[1]

        # 使用前 N 幀初始化
        init_frames = magnitude_spectrum[:self.num_init_frames]
        power_spectrum = init_frames ** 2

        # v2.1: 使用 20th 百分位數而非平均值
        # 這樣即使初始幀包含語音，也能得到較低的噪聲估計
        init_psd = np.percentile(power_spectrum, 20, axis=0)

        # 初始化狀態
        self.noise_psd = init_psd.copy()
        self.S = init_psd.copy()
        self.S_min = init_psd.copy()
        self.spp = np.zeros(n_freqs)

        if self.use_dual_window:
            # 雙視窗模式：使用 S_min_sw 和 stored_min
            self.S_min_sw = init_psd.copy()
            self.stored_min = init_psd.copy()
            self.min_buffer = None
        else:
            # 單視窗模式：使用 FIFO 緩衝區
            self.min_buffer = deque(maxlen=self.L)
            # 填充初始值
            for _ in range(self.L):
                self.min_buffer.append(init_psd.copy())
            self.S_min_sw = None
            self.stored_min = None

        self.counter = 0
        self.is_initialized = True
        self.frame_count = self.num_init_frames

        # 初始化前一幀能量
        self.prev_frame_energy = np.sum(init_psd)

        return self.noise_psd

    def update(
        self,
        magnitude: np.ndarray,
        is_speech: Optional[bool] = None,  # 保持接口兼容（MCRA 內部判斷，忽略此參數）
        spp: Optional[np.ndarray] = None   # v2.0: 支持外部 SPP（軟判決）
    ) -> np.ndarray:
        """
        MCRA 噪聲估計更新

        v3.0: 支持雙視窗和單視窗最小值追蹤
        - 雙視窗模式 (預設)：記憶體效率高，自動適應噪聲變化
        - 單視窗模式：傳統 FIFO 緩衝區方法

        參數:
            magnitude: 當前幀的幅度譜 (n_freqs,)
            is_speech: 忽略，MCRA 使用 SPP 判斷
            spp: 外部 SPP 值 (n_freqs,)，可選。若提供則用於噪聲更新門控

        返回:
            noise_psd: 更新後的噪聲功率譜密度 (n_freqs,)
        """
        if not self.is_initialized:
            raise RuntimeError("Noise estimator not initialized. Call estimate() first.")

        # 1. 計算當前幀的功率譜
        power = magnitude ** 2

        # === 場景轉換偵測 ===
        E_curr = np.sum(power)
        beta = E_curr / (self.prev_frame_energy + 1e-10)

        # 計算自適應係數 η
        # β > 50: 突發尖峰（脈衝噪聲），忽略
        # β ≈ 1: 能量穩定，η ≈ 0.95（正常更新）
        # β > 10: 能量突增，η → 0（加速噪聲更新）
        if beta > 50:
            eta = 0.0  # 突發尖峰（脈衝噪聲），強制快速更新噪聲
        else:
            eta = 0.95 / (1.0 + np.exp(20 * (beta - 10)))

        # 更新前一幀能量
        self.prev_frame_energy = E_curr
        # === 場景轉換偵測結束 ===

        # 2. 時間平滑
        # S(k,l) = α_s·S(k,l-1) + (1-α_s)·|Y(k,l)|²
        self.S = self.alpha_s * self.S + (1 - self.alpha_s) * power

        # ================================================================
        # 3. 最小值追蹤（根據模式選擇）
        # ================================================================
        if self.use_dual_window:
            # ----------------------------------------------------------
            # 雙視窗最小值追蹤 (Dual-Window Minima Tracking)
            # ----------------------------------------------------------
            # 每幀持續追蹤：
            #   - S_min: 全局最小值（用於語音檢測）
            #   - S_min_sw: 當前子視窗最小值（用於下一輪更新）
            self.S_min = np.minimum(self.S_min, self.S)      # 步驟 1
            self.S_min_sw = np.minimum(self.S_min_sw, self.S)  # 步驟 2

            self.counter += 1  # 步驟 3

            # 每 L 幀觸發視窗切換（關鍵：自動適應噪聲場景變化）
            # 這是雙視窗的核心邏輯：
            #   - stored_min 保存上一輪的子視窗最小值
            #   - S_min_sw 保存當前輪的子視窗最小值
            #   - 兩者取最小值作為新的 S_min
            #   - 這樣即使噪聲突增，最多 L 幀後 S_min 會追上
            if self.counter >= self.L:
                # 步驟 4: 合併兩個子視窗的最小值
                self.S_min = np.minimum(self.stored_min, self.S_min_sw)
                # 步驟 5: 保存當前子視窗最小值供下一輪使用
                self.stored_min = self.S_min_sw.copy()
                # 步驟 6: 重置當前子視窗（從當前幀開始新一輪追蹤）
                self.S_min_sw = self.S.copy()
                # 步驟 7: 重置計數器
                self.counter = 0
        else:
            # ----------------------------------------------------------
            # 單視窗最小值追蹤 (Single-Window FIFO Buffer)
            # ----------------------------------------------------------
            # 將當前平滑功率譜加入緩衝區（自動丟棄最舊的幀）
            self.min_buffer.append(self.S.copy())
            # 計算緩衝區中所有幀的逐元素最小值
            self.S_min = np.min(np.array(self.min_buffer), axis=0)

        # 4. 語音指示器（基於最小值比）
        # I(k,l) = 1 if S(k,l)/S_min(k,l) > δ else 0
        ratio = self.S / (self.S_min * self.delta + 1e-10)
        indicator = (ratio > 1.0).astype(float)

        # 5. SPP 平滑
        # p(k,l) = α_p·p(k,l-1) + (1-α_p)·I(k,l)
        self.spp = self.alpha_p * self.spp + (1 - self.alpha_p) * indicator

        # 6. 噪聲更新
        # 若提供外部 SPP，使用外部 SPP；否則使用內部 SPP
        used_spp = spp if spp is not None else self.spp
        # 原始: alpha_d_tilde = α_d + (1 - α_d) × SPP
        # 修改: alpha_d_tilde = (α_d + (1 - α_d) × SPP) × η
        # η 由場景轉換偵測計算，當噪聲突增時 η 變小，加速噪聲更新
        alpha_d_tilde = (self.alpha_d + (1 - self.alpha_d) * used_spp) * eta

        # N(k,l) = α̃_d·N(k,l-1) + (1-α̃_d)·|Y(k,l)|²
        self.noise_psd = alpha_d_tilde * self.noise_psd + (1 - alpha_d_tilde) * power

        self.frame_count += 1

        return self.noise_psd

    def reset(self):
        """重置估計器狀態"""
        self.noise_psd = None
        self.S = None
        self.S_min = None
        self.S_min_sw = None
        self.stored_min = None
        self.min_buffer = None
        self.spp = None
        self.is_initialized = False
        self.frame_count = 0
        self.counter = 0
        self.prev_frame_energy = 1.0

    def __repr__(self):
        mode = "dual-window" if self.use_dual_window else "single-window"
        return (f"McraNoiseEstimator(alpha_s={self.alpha_s}, alpha_d={self.alpha_d}, "
                f"alpha_p={self.alpha_p}, L={self.L}, mode={mode})")
