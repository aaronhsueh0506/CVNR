# 評估指標使用指南 (Metrics Usage Guide)

## 目錄

1. [概述](#概述)
2. [可用指標](#可用指標)
3. [使用方法](#使用方法)
4. [指標解釋](#指標解釋)
5. [完整範例](#完整範例)
6. [最佳實踐](#最佳實踐)
7. [參考文獻](#參考文獻)

## 概述

本項目提供基於 Loizou (2008) 推薦的客觀評估指標，用於評估語音降噪算法的效果。這些指標已被學術界廣泛採用，可以量化降噪算法的性能。

**可用指標**:
- **segSNR** - 分段信噪比（Segmental SNR）
- **fwSegSNR** - 頻率加權分段信噪比（Frequency-weighted Segmental SNR）
- **WSS** - 加權頻譜斜率距離（Weighted Spectral Slope）
- **global_SNR** - 全局信噪比（Global SNR）

所有指標均支持 **VAD（語音活動檢測）**，只評估語音段，忽略靜音段。

## 可用指標

### 2.1 segSNR (分段 SNR)

**用途**: 評估整體降噪效果

**計算方法**:
- 將信號分幀（默認 20ms 幀長，10ms 幀移）
- 計算每幀的 SNR
- 對所有幀的 SNR 取平均
- 裁剪異常值（默認 -15 到 35 dB）
- 可選 VAD 過濾靜音幀

**優點**:
- 簡單直觀
- 反映逐幀質量
- 對噪聲抑制敏感

**缺點**:
- 不考慮頻率重要性
- 不考慮人耳感知特性
- 可能對過度處理不敏感

**適用場景**:
- 快速評估降噪效果
- 初步算法對比
- 監控處理質量

### 2.2 fwSegSNR (頻率加權分段 SNR)

**用途**: 考慮人耳敏感度的評估

**計算方法**:
- 類似 segSNR，但對不同頻率加權
- **300-3000 Hz**: 權重 1.0（語音主要頻段）
- **< 300 Hz 或 > 3000 Hz**: 權重降低
- 更符合人耳對語音的敏感度

**優點**:
- 更符合感知質量
- 重視語音重要頻段
- 對語音失真更敏感

**缺點**:
- 計算稍複雜
- 需要頻率分析
- 對高頻失真不太敏感

**適用場景**:
- 語音質量評估
- 感知質量優化
- 語音通信系統評估

### 2.3 WSS (加權頻譜斜率距離)

**用途**: 評估頻譜失真

**計算方法**:
- 計算 25 個 Bark 頻帶的頻譜斜率
- 比較乾淨語音和處理後語音的斜率差異
- 使用感知加權
- 值越小表示失真越小

**優點**:
- 對頻譜失真敏感
- 能檢測過度處理
- 基於感知模型

**缺點**:
- 值越小越好（與 SNR 相反）
- 計算複雜度較高
- 解釋不如 SNR 直觀

**適用場景**:
- 檢測過度處理
- 頻譜保真度評估
- 配合 SNR 綜合評估

### 2.4 global_SNR (全局 SNR)

**用途**: 評估整體信噪比

**計算方法**:
- 計算整個信號的總能量比
- SNR = 10 * log10(signal_power / noise_power)

**優點**:
- 最簡單的指標
- 計算快速
- 容易理解

**缺點**:
- 不反映時域變化
- 對局部失真不敏感
- 可能被平均效應掩蓋

**適用場景**:
- 粗略評估
- 配合其他指標使用

## 使用方法

### 3.1 基本用法

```python
import numpy as np
from utils.metrics_loizou import composite_measure, print_metrics
from utils.audio_io import read_audio

# 讀取音頻
clean_signal, sr = read_audio('test_wav/clean.wav')
enhanced_signal, sr = read_audio('output/enhanced.wav')

# 計算所有指標
metrics = composite_measure(
    clean_signal=clean_signal,
    processed_signal=enhanced_signal,
    sample_rate=sr
)

# 打印結果
print_metrics(metrics)
```

**輸出示例**:
```
=== 音頻質量評估指標 ===
  分段SNR (segSNR):           12.45 dB
  頻率加權segSNR (fwSegSNR):  11.23 dB
  加權頻譜斜率 (WSS):          45.67
  全局SNR (global_SNR):       15.78 dB
```

### 3.2 單獨計算指標

```python
from utils.metrics_loizou import segmental_snr, frequency_weighted_segsnr, weighted_spectral_slope

# 只計算 segSNR
seg_snr = segmental_snr(clean_signal, enhanced_signal, sr)
print(f"segSNR: {seg_snr:.2f} dB")

# 計算頻率加權 segSNR
fw_seg_snr = frequency_weighted_segsnr(clean_signal, enhanced_signal, sr)
print(f"fwSegSNR: {fw_seg_snr:.2f} dB")

# 計算 WSS (值越小越好)
wss = weighted_spectral_slope(clean_signal, enhanced_signal, sr)
print(f"WSS: {wss:.2f}")
```

### 3.3 使用 VAD (Voice Activity Detection)

```python
# 啟用 VAD (默認已啟用)
seg_snr_with_vad = segmental_snr(
    clean_signal,
    enhanced_signal,
    sr,
    use_vad=True  # 只評估語音段
)

# 禁用 VAD (評估所有幀)
seg_snr_no_vad = segmental_snr(
    clean_signal,
    enhanced_signal,
    sr,
    use_vad=False
)

print(f"segSNR (with VAD): {seg_snr_with_vad:.2f} dB")
print(f"segSNR (no VAD):   {seg_snr_no_vad:.2f} dB")
```

**說明**: VAD 可以避免靜音段影響評估結果，通常應該啟用。

### 3.4 自定義參數

```python
# 調整幀長和幀移
seg_snr = segmental_snr(
    clean_signal,
    enhanced_signal,
    sr,
    frame_len_ms=30.0,    # 30ms 幀長 (默認 20ms)
    frame_shift_ms=15.0,  # 15ms 幀移 (默認 10ms)
    snr_clip_db=(-15.0, 40.0)  # SNR 裁剪範圍
)

# 調整 VAD 閾值
seg_snr = segmental_snr(
    clean_signal,
    enhanced_signal,
    sr,
    use_vad=True,
    vad_threshold_db=-35.0  # 更敏感的 VAD (默認 -40dB)
)
```

## 指標解釋

### 4.1 指標數值範圍

| 指標 | 典型範圍 | 優秀 | 良好 | 一般 | 差 |
|------|---------|------|------|------|-----|
| **segSNR** | -5 to 20 dB | >15 dB | 10-15 dB | 5-10 dB | <5 dB |
| **fwSegSNR** | -5 to 18 dB | >13 dB | 8-13 dB | 3-8 dB | <3 dB |
| **WSS** | 20 to 150 | <40 | 40-60 | 60-90 | >90 |
| **global_SNR** | 0 to 30 dB | >20 dB | 15-20 dB | 10-15 dB | <10 dB |

**注意**: WSS 值**越小越好**（與 SNR 相反）

### 4.2 指標含義

#### segSNR (Segmental SNR)

- **正值**: 增強信號比原始噪聲信號更好
- **改善 8-15 dB**: 顯著降噪效果
- **改善 <5 dB**: 降噪效果有限
- **負值**: 增強信號引入了更多失真

**示例**:
- 原始噪聲 segSNR: 2.5 dB
- 增強後 segSNR: 12.8 dB
- **改善**: 10.3 dB（顯著改善）

#### fwSegSNR (Frequency-weighted segSNR)

- 更貼近人耳感知
- 通常比 segSNR 低 1-3 dB（正常）
- 如果比 segSNR 低很多（>5 dB），可能在關鍵頻段（300-3000 Hz）失真嚴重

**示例**:
- segSNR: 12.8 dB
- fwSegSNR: 11.2 dB
- **差異**: 1.6 dB（正常）

#### WSS (Weighted Spectral Slope)

- **20-40**: 幾乎無頻譜失真（優秀）
- **40-60**: 輕微失真（良好）
- **60-90**: 中等失真（可接受）
- **>90**: 嚴重失真（差）

**警告信號**:
- WSS > 70 且 segSNR 很高 → 可能過度處理

#### global_SNR

- 整體能量比
- 通常高於 segSNR（因為不做裁剪）
- 主要用於參考

### 4.3 綜合評估建議

**良好的降噪結果應該**:
- ✅ segSNR 改善 ≥ 10 dB
- ✅ fwSegSNR 改善 ≥ 8 dB
- ✅ WSS < 60
- ✅ 沒有明顯的 Musical Noise（聽覺評估）

**警告信號**:
- ⚠️ segSNR 很高但 WSS 很大 → 過度處理
- ⚠️ fwSegSNR 遠低於 segSNR → 語音頻段失真
- ⚠️ global_SNR 高但 segSNR 低 → 不均勻處理

## 完整範例

### 5.1 評估單個版本

```python
#!/usr/bin/env python3
"""
評估 V3 降噪效果
"""
import numpy as np
from utils.audio_io import read_audio, write_audio
from utils.metrics_loizou import composite_measure, print_metrics
from denoisers import SppMmseDenoiser

# 1. 讀取音頻
clean_signal, sr = read_audio('test_wav/clean.wav')
noisy_signal, sr = read_audio('test_wav/test_noisy.wav')

# 2. 降噪處理
denoiser = SppMmseDenoiser(sample_rate=sr)
enhanced_signal = denoiser.denoise(noisy_signal)

# 3. 保存結果
write_audio('output/enhanced_v3.wav', enhanced_signal, sr)

# 4. 評估
print("\n=== V3 (MMSE-STSA) 降噪效果評估 ===")
metrics = composite_measure(clean_signal, enhanced_signal, sr)
print_metrics(metrics)

# 5. 與原始噪聲對比
print("\n=== 原始噪聲信號評估 ===")
noisy_metrics = composite_measure(clean_signal, noisy_signal, sr)
print_metrics(noisy_metrics)

# 6. 計算改善
print("\n=== 改善量 ===")
print(f"segSNR 改善:    {metrics['segSNR'] - noisy_metrics['segSNR']:.2f} dB")
print(f"fwSegSNR 改善:  {metrics['fwSegSNR'] - noisy_metrics['fwSegSNR']:.2f} dB")
print(f"WSS 改善:       {noisy_metrics['WSS'] - metrics['WSS']:.2f} (正值=變好)")
```

**預期輸出**:
```
=== V3 (MMSE-STSA) 降噪效果評估 ===
=== 音頻質量評估指標 ===
  分段SNR (segSNR):           12.34 dB
  頻率加權segSNR (fwSegSNR):  10.89 dB
  加權頻譜斜率 (WSS):          48.23
  全局SNR (global_SNR):       15.67 dB

=== 原始噪聲信號評估 ===
=== 音頻質量評估指標 ===
  分段SNR (segSNR):           2.15 dB
  頻率加權segSNR (fwSegSNR):  1.23 dB
  加權頻譜斜率 (WSS):          95.67
  全局SNR (global_SNR):       5.34 dB

=== 改善量 ===
segSNR 改善:    10.19 dB
fwSegSNR 改善:  9.66 dB
WSS 改善:       47.44 (正值=變好)
```

### 5.2 對比多個版本

```python
#!/usr/bin/env python3
"""
對比 V3, V3-2, V3-3, V3-4 降噪效果
"""
import numpy as np
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import (
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
    LaplacianMmseDenoiser
)

# 讀取音頻
clean, sr = read_audio('test_wav/clean.wav')
noisy, sr = read_audio('test_wav/test_noisy.wav')

# 定義版本
denoisers = {
    'V3 (MMSE-STSA)': SppMmseDenoiser(sample_rate=sr),
    'V3-2 (MMSE-LSA)': MmseLsaDenoiser(sample_rate=sr),
    'V3-3 (PMMSE)': PmmseDenoiser(sample_rate=sr),
    'V3-4 (Laplacian-MMSE)': LaplacianMmseDenoiser(sample_rate=sr)
}

# 評估每個版本
results = {}
for name, denoiser in denoisers.items():
    print(f"\n處理 {name}...")
    enhanced = denoiser.denoise(noisy)
    metrics = composite_measure(clean, enhanced, sr)
    results[name] = metrics

# 打印對比表格
print("\n" + "="*80)
print("MMSE 變體降噪效果對比")
print("="*80)
print(f"{'版本':<25} {'segSNR':>10} {'fwSegSNR':>10} {'WSS':>10} {'global_SNR':>12}")
print("-"*80)

for name, metrics in results.items():
    print(f"{name:<25} "
          f"{metrics['segSNR']:>9.2f}  "
          f"{metrics['fwSegSNR']:>9.2f}  "
          f"{metrics['WSS']:>9.2f}  "
          f"{metrics['global_SNR']:>11.2f}")

print("="*80)

# 找出最佳版本
best_segsnr = max(results.items(), key=lambda x: x[1]['segSNR'])
best_wss = min(results.items(), key=lambda x: x[1]['WSS'])

print(f"\n最佳 segSNR:  {best_segsnr[0]} ({best_segsnr[1]['segSNR']:.2f} dB)")
print(f"最佳 WSS:     {best_wss[0]} ({best_wss[1]['WSS']:.2f})")
```

**預期輸出**:
```
================================================================================
MMSE 變體降噪效果對比
================================================================================
版本                        segSNR   fwSegSNR        WSS   global_SNR
--------------------------------------------------------------------------------
V3 (MMSE-STSA)               12.34       10.89      48.23        15.67
V3-2 (MMSE-LSA)              13.12       11.45      42.56        16.23
V3-3 (PMMSE)                 11.89       10.34      51.78        14.89
V3-4 (Laplacian-MMSE)        13.56       11.78      39.12        16.78
================================================================================

最佳 segSNR:  V3-4 (Laplacian-MMSE) (13.56 dB)
最佳 WSS:     V3-4 (Laplacian-MMSE) (39.12)
```

### 5.3 批量評估

```python
#!/usr/bin/env python3
"""
批量評估多個測試文件
"""
import os
import numpy as np
import pandas as pd
from utils.audio_io import read_audio
from utils.metrics_loizou import composite_measure
from denoisers import SppMmseDenoiser

# 測試文件列表
test_files = [
    ('test_wav/babble_0dB.wav', 'test_wav/clean.wav'),
    ('test_wav/babble_10dB.wav', 'test_wav/clean.wav'),
    ('test_wav/car_0dB.wav', 'test_wav/clean.wav'),
    ('test_wav/car_10dB.wav', 'test_wav/clean.wav'),
]

# 降噪器
denoiser = SppMmseDenoiser(sample_rate=16000)

# 收集結果
results_list = []

for noisy_path, clean_path in test_files:
    print(f"\n處理: {os.path.basename(noisy_path)}")

    # 讀取
    clean, sr = read_audio(clean_path)
    noisy, sr = read_audio(noisy_path)

    # 降噪
    enhanced = denoiser.denoise(noisy)

    # 評估
    metrics = composite_measure(clean, enhanced, sr)

    # 記錄
    results_list.append({
        'file': os.path.basename(noisy_path),
        'segSNR': metrics['segSNR'],
        'fwSegSNR': metrics['fwSegSNR'],
        'WSS': metrics['WSS'],
        'global_SNR': metrics['global_SNR']
    })

# 創建 DataFrame
df = pd.DataFrame(results_list)

# 打印結果
print("\n" + "="*80)
print("批量評估結果")
print("="*80)
print(df.to_string(index=False))
print("="*80)

# 統計
print("\n平均值:")
print(df[['segSNR', 'fwSegSNR', 'WSS', 'global_SNR']].mean())

# 保存 CSV
df.to_csv('evaluation_results.csv', index=False)
print("\n結果已保存到 evaluation_results.csv")
```

## 最佳實踐

### 6.1 評估流程建議

1. **始終使用 clean signal** 作為參考
2. **同時評估 noisy 和 enhanced**，計算改善量
3. **使用多個指標**，不要只看 segSNR
4. **結合聽覺評估**，指標只是參考
5. **記錄實驗參數**，便於複現

### 6.2 常見錯誤

❌ **錯誤 1**: 只看 segSNR，忽略 WSS
- **問題**: 可能過度處理導致頻譜失真
- **解決**: 確保 WSS < 60

❌ **錯誤 2**: 使用 enhanced signal 當作 clean reference
- **問題**: 無法正確計算指標
- **解決**: 必須使用真實的 clean signal

❌ **錯誤 3**: 不同長度的音頻對比
- **問題**: `composite_measure` 會自動截斷，但結果不可靠
- **解決**: 確保 clean 和 processed 長度一致

❌ **錯誤 4**: 不考慮 VAD
- **問題**: 靜音段會影響平均值
- **解決**: 默認啟用 VAD，除非有特殊需求

### 6.3 調試技巧

```python
# 檢查音頻長度
print(f"Clean length: {len(clean)}")
print(f"Enhanced length: {len(enhanced)}")
assert len(clean) == len(enhanced), "Length mismatch!"

# 檢查數值範圍
print(f"Clean range: [{clean.min():.3f}, {clean.max():.3f}]")
print(f"Enhanced range: [{enhanced.min():.3f}, {enhanced.max():.3f}]")

# 檢查是否有 NaN 或 Inf
assert not np.isnan(enhanced).any(), "Enhanced contains NaN!"
assert not np.isinf(enhanced).any(), "Enhanced contains Inf!"

# VAD 測試
from utils.metrics_loizou import voice_activity_detection
vad_flags = voice_activity_detection(clean, sr)
print(f"VAD: {vad_flags.sum()} / {len(vad_flags)} frames are voice")
```

### 6.4 參數調整建議

**幀長和幀移**:
- 默認 20ms/10ms 適用於大多數情況
- 更短的幀（10ms）：更精細的時域分辨率
- 更長的幀（30ms）：更穩定的頻域分析

**VAD 閾值**:
- 默認 -40dB 適用於一般語音
- 降低閾值（-45dB）：包含更多弱音段
- 提高閾值（-35dB）：更嚴格的語音檢測

**SNR 裁剪範圍**:
- 默認 [-15, 35] dB 過濾極端值
- 可根據實際噪聲水平調整

## 參考文獻

**Loizou (2008)** - 指標推薦論文:
- Hu, Y., & Loizou, P. C. (2008). "Evaluation of objective quality measures for speech enhancement." *IEEE Transactions on Audio, Speech, and Language Processing*, 16(1), 229-238.
- DOI: 10.1109/TASL.2007.911054
- 說明: 本文評估了多種客觀指標與主觀聽覺測試的相關性，推薦 segSNR, fwSegSNR, WSS 等指標

**相關工具**:
- 完整實現見: [utils/metrics_loizou.py](../utils/metrics_loizou.py)
- 降噪器見: [denoisers/](../denoisers/) 目錄
- 音頻 I/O: [utils/audio_io.py](../utils/audio_io.py)

**在線資源**:
- Loizou's Speech Enhancement Book: http://www.utdallas.edu/~loizou/speech/software.htm
- IEEE Xplore: https://ieeexplore.ieee.org/
