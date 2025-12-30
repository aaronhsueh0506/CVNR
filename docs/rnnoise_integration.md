# RNNoise 集成與性能分析指南

## 概述

RNNoise 是由 Xiph.Org 開發的基於深度學習的實時降噪算法，使用 GRU（Gated Recurrent Unit）網絡架構。本文檔提供 RNNoise 的集成方法、性能分析和與傳統方法的對比。

## RNNoise 架構分析

### 模型結構

```
輸入音頻 (48kHz)
    ↓
幀分割 (10ms, 480 samples)
    ↓
特徵提取 (42 Bark-scale features)
    ↓
GRU 層 (24 hidden units)
    ↓
全連接層 (22 outputs)
    ↓
增益掩碼 (22 頻帶)
    ↓
應用增益 → 輸出音頻
```

### 關鍵參數

| 參數 | 值 | 說明 |
|-----|---|------|
| 採樣率 | 48 kHz | 原始 RNNoise 設計（可降采樣） |
| 幀長 | 10 ms | 480 samples @ 48kHz |
| 輸入特徵 | 42 維 | Bark-scale 頻譜特徵 |
| GRU 隱藏單元 | 24 | 遞歸層神經元數量 |
| 輸出維度 | 22 | 頻帶增益掩碼 |
| 模型參數量 | ~87K | 總參數數（權重+偏置）|

## 理論複雜度分析

### 浮點運算量（FLOPs）

#### 1. 特徵提取階段

```python
# Bark-scale FFT + 特徵計算
feature_extraction_flops = ~5,000 FLOPs/幀
```

#### 2. GRU 層計算

GRU 有 3 個門控機制（reset gate, update gate, new gate）：

```python
# GRU 公式:
# r_t = sigmoid(W_r · [x_t, h_{t-1}])
# z_t = sigmoid(W_z · [x_t, h_{t-1}])
# h_tilde = tanh(W_h · [x_t, r_t ⊙ h_{t-1}])
# h_t = z_t ⊙ h_{t-1} + (1 - z_t) ⊙ h_tilde

# 每個門的計算:
# - 矩陣乘法: (input_size + hidden_size) × hidden_size
# - 激活函數: hidden_size

input_size = 42  # Bark-scale features
hidden_size = 24
num_gates = 3

# 矩陣乘法 FLOPs
matmul_per_gate = (input_size + hidden_size) * hidden_size * 2  # 乘法+加法
# = (42 + 24) * 24 * 2 = 3,168 FLOPs

# 總 GRU FLOPs
gru_flops = num_gates * matmul_per_gate + hidden_size * 10  # ~10K FLOPs/幀
```

#### 3. 全連接層

```python
fc_input = 24   # GRU output
fc_output = 22  # Frequency bands

fc_flops = fc_input * fc_output * 2  # = 1,056 FLOPs/幀
```

#### 總計（10ms 幀）

```python
total_flops_10ms = feature_extraction_flops + gru_flops + fc_flops
                 ≈ 5,000 + 10,000 + 1,000
                 ≈ 16,000 FLOPs/幀

# 對齊到 20ms（與傳統方法比較）
total_flops_20ms ≈ 33,000 FLOPs/幀
```

### 內存佔用

```python
# 模型權重
gru_weights = (42 + 24) * 24 * 3 * 4 bytes  # float32
            ≈ 19 KB

fc_weights = 24 * 22 * 4 bytes
           ≈ 2 KB

total_model_size ≈ 85 KB

# 運行時內存（緩存、中間變量）
runtime_memory ≈ 5-10 MB
```

## 安裝方法

### 選項 A：Python Binding（推薦用於測試）

#### 方法 1：使用 rnnoise-python

```bash
pip install rnnoise-python
```

**示例代碼：**

```python
import numpy as np
from rnnoise import RNNoise

# 初始化降噪器
denoiser = RNNoise()

# 讀取音頻（16-bit PCM）
audio = load_audio('noisy.wav', sr=48000)

# 處理（10ms 幀，480 samples @ 48kHz）
frame_size = 480
enhanced = []

for i in range(0, len(audio), frame_size):
    frame = audio[i:i+frame_size]
    if len(frame) < frame_size:
        frame = np.pad(frame, (0, frame_size - len(frame)))

    # RNNoise 需要 int16 輸入
    frame_int16 = (frame * 32767).astype(np.int16)
    enhanced_frame = denoiser.process_frame(frame_int16)
    enhanced.append(enhanced_frame / 32767.0)

enhanced_audio = np.concatenate(enhanced)
```

#### 方法 2：使用 noisereduce（包含 RNNoise）

```bash
pip install noisereduce
```

**示例代碼：**

```python
import noisereduce as nr

# 使用 RNNoise 後端
reduced = nr.reduce_noise(
    y=audio,
    sr=sample_rate,
    stationary=False,  # RNNoise 適合非穩態噪聲
    use_rnnoise=True   # 使用 RNNoise
)
```

### 選項 B：編譯原始 C 代碼（推薦用於生產）

```bash
# 克隆倉庫
git clone https://github.com/xiph/rnnoise.git
cd rnnoise

# 編譯
./autogen.sh
./configure
make

# 安裝
sudo make install
```

**C API 示例：**

```c
#include <rnnoise.h>

// 創建降噪狀態
DenoiseState *st = rnnoise_create(NULL);

// 處理音頻幀（10ms, 480 samples @ 48kHz）
float frame[480];
rnnoise_process_frame(st, frame, frame);

// 釋放資源
rnnoise_destroy(st);
```

### 選項 C：使用命令行工具

```bash
# 編譯後使用
./examples/rnnoise_demo input.pcm output.pcm

# 輸入格式：48kHz, 16-bit, mono PCM
```

## 性能測試腳本

### 測試處理時間和資源使用

創建 `test_rnnoise_performance.py`：

```python
#!/usr/bin/env python3
"""
RNNoise 性能測試腳本

測量：
- 處理時間
- CPU 使用率
- 內存佔用
- 實時率（RTF）
"""

import time
import numpy as np

try:
    from rnnoise import RNNoise
    RNNOISE_AVAILABLE = True
except ImportError:
    RNNOISE_AVAILABLE = False
    print("Error: rnnoise-python not installed")
    print("Install with: pip install rnnoise-python")
    exit(1)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not available, CPU/memory monitoring disabled")


def test_rnnoise_performance(duration_sec=2.0, sample_rate=48000):
    """
    測試 RNNoise 性能

    Args:
        duration_sec: 測試音頻時長（秒）
        sample_rate: 採樣率（必須是 48kHz for RNNoise）
    """
    if sample_rate != 48000:
        print("Warning: RNNoise designed for 48kHz, resampling may be needed")

    # 生成測試音頻（白噪聲）
    num_samples = int(duration_sec * sample_rate)
    audio = np.random.randn(num_samples).astype(np.float32) * 0.1

    # 初始化 RNNoise
    denoiser = RNNoise()

    # 幀參數
    frame_size = 480  # 10ms @ 48kHz
    num_frames = num_samples // frame_size

    # 開始監控
    if PSUTIL_AVAILABLE:
        process = psutil.Process()
        process.cpu_percent()  # 初始化
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

    # 處理音頻
    start_time = time.perf_counter()
    enhanced = []

    for i in range(num_frames):
        start_idx = i * frame_size
        frame = audio[start_idx:start_idx + frame_size]

        # 轉換為 int16
        frame_int16 = (frame * 32767).astype(np.int16)

        # 處理
        enhanced_frame = denoiser.process_frame(frame_int16)
        enhanced.append(enhanced_frame / 32767.0)

    processing_time = time.perf_counter() - start_time

    # 計算性能指標
    audio_duration = num_samples / sample_rate
    rtf = processing_time / audio_duration

    # CPU 和內存
    if PSUTIL_AVAILABLE:
        cpu_percent = process.cpu_percent()
        mem_after = process.memory_info().rss / 1024 / 1024
        mem_used = mem_after - mem_before
    else:
        cpu_percent = None
        mem_used = None

    # 打印結果
    print("="*60)
    print("RNNoise Performance Test")
    print("="*60)
    print(f"Audio duration:     {audio_duration:.2f} s")
    print(f"Processing time:    {processing_time*1000:.2f} ms")
    print(f"Real-time factor:   {rtf:.4f}")
    print(f"Frames processed:   {num_frames}")
    print(f"Time per frame:     {processing_time/num_frames*1000:.3f} ms")

    if PSUTIL_AVAILABLE:
        print(f"CPU usage:          {cpu_percent:.1f}%")
        print(f"Memory used:        {mem_used:.2f} MB")

    # 評估實時性
    if rtf < 0.3:
        realtime_status = "優秀（可在低功耗設備運行）"
    elif rtf < 0.5:
        realtime_status = "良好（可在移動設備運行）"
    elif rtf < 1.0:
        realtime_status = "合格（實時處理）"
    else:
        realtime_status = "不合格（無法實時）"

    print(f"Real-time status:   {realtime_status}")
    print("="*60)

    # 返回結果
    return {
        'processing_time_ms': processing_time * 1000,
        'rtf': rtf,
        'cpu_percent': cpu_percent,
        'memory_mb': mem_used,
        'frames_processed': num_frames,
        'time_per_frame_ms': processing_time / num_frames * 1000
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test RNNoise performance')
    parser.add_argument('--duration', type=float, default=2.0,
                       help='Test audio duration in seconds (default: 2.0)')

    args = parser.parse_args()

    results = test_rnnoise_performance(duration_sec=args.duration)

    # 與理論對比
    print("\nTheoretical Analysis:")
    print(f"Expected FLOPs/frame: ~16,000 (10ms)")
    print(f"Expected FLOPs/frame: ~33,000 (20ms, for comparison with V1-V4)")
```

### 運行測試

```bash
# 安裝依賴
pip install rnnoise-python psutil

# 運行測試（2 秒音頻）
python test_rnnoise_performance.py

# 運行測試（5 秒音頻）
python test_rnnoise_performance.py --duration 5.0
```

## 與傳統方法對比

### 計算複雜度對比（20ms 幀）

| 方法 | FLOPs/幀 | 相對複雜度 |
|-----|----------|-----------|
| V1 頻譜減法 | ~47K | 1.0x |
| V2 Wiener | ~47K | 1.0x |
| V3 SPP-MMSE | ~50K | 1.06x |
| V4 IMCRA-OMLSA | ~53K | 1.13x |
| **RNNoise** | **~33K** | **0.70x** |

**結論：** RNNoise 的理論計算量實際上比 V3-V4 **更低**，但實際運行時間可能更長，因為：
1. GRU 的矩陣運算難以向量化
2. 需要序列依賴（無法並行處理所有幀）
3. Python/C 接口開銷

### 降噪效果對比（理論分析）

| 維度 | V1 | V2 | V3 | V4 | RNNoise |
|------|----|----|----|----|---------|
| 穩態噪聲 | 良好 | 良好 | 優秀 | 優秀 | 優秀 |
| 非穩態噪聲 | 較差 | 較差 | 良好 | 優秀 | **最優** |
| 音樂噪聲 | 嚴重 | 中等 | 輕微 | 極少 | **極少** |
| 語音保真度 | 一般 | 良好 | 優秀 | 優秀 | 良好 |
| 實時性 | 優秀 | 優秀 | 優秀 | 良好 | 一般 |

### 部署難度對比

| 方法 | 依賴複雜度 | 模型大小 | 跨平台性 | 調參難度 |
|-----|----------|---------|---------|---------|
| V1-V4 | 低（僅 NumPy） | 無模型 | 優秀 | 中等 |
| RNNoise | 高（需編譯/Python binding） | 85KB | 良好 | 低（無需調參） |

## 使用建議

### 何時使用 RNNoise

✅ **適合的場景：**
- 非穩態噪聲（說話聲、音樂、環境噪聲）
- 對音質要求高，可接受略高延遲
- 有 GPU 或多核 CPU 資源
- 不需要頻繁調整參數

❌ **不適合的場景：**
- 極低延遲要求（< 20ms）
- 嵌入式設備（資源受限）
- 需要精確控制降噪強度
- 只有穩態白噪聲

### 何時使用傳統方法（V1-V4）

✅ **適合的場景：**
- 實時性要求極高
- 嵌入式或低功耗設備
- 需要完全控制和可解釋性
- 穩態噪聲為主
- 需要快速原型開發

### 混合策略

考慮根據場景動態選擇：

```python
def select_denoiser(noise_type, device_capability):
    if noise_type == 'stationary' and device_capability == 'low':
        return 'V2_Wiener'  # 簡單高效
    elif noise_type == 'non_stationary' and device_capability == 'high':
        return 'RNNoise'  # 效果最佳
    else:
        return 'V4_IMCRA_OMLSA'  # 平衡選擇
```

## 進一步優化

### RNNoise 加速方法

1. **使用 ONNX Runtime**
   ```bash
   # 將 RNNoise 轉換為 ONNX 格式
   # 使用 ONNX Runtime 加速推理
   pip install onnxruntime
   ```

2. **量化模型**
   - INT8 量化可減少 4x 模型大小
   - 輕微精度損失，顯著加速

3. **批處理**
   - 一次處理多幀（如果延遲允許）
   - 提高 GPU 利用率

## 參考資源

### 論文
- Valin, J. M. (2018). "A Hybrid DSP/Deep Learning Approach to Real-Time Full-Band Speech Enhancement"
- GitHub: https://github.com/xiph/rnnoise

### 相關項目
- RNNoise Python: https://github.com/jnr0790/rnnoise-python
- DeepFilterNet: https://github.com/Rikorose/DeepFilterNet（更先進的深度學習方法）

### 數據集
- DNS Challenge: https://github.com/microsoft/DNS-Challenge（用於訓練和評估）

---

**最後更新：** 2025-12-30
**作者：** Speech Denoising Project
