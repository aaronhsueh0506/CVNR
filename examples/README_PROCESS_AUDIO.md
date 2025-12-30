# 🎵 音頻文件降噪處理工具

## ✨ 新功能！

現在您可以直接使用真實的音頻文件進行降噪處理了！

## 📁 文件說明

- **`process_audio.py`** - 主腳本，處理真實音頻文件
- **`PROCESS_AUDIO_USAGE.md`** - 詳細使用說明
- **`benchmark_all.py`** - 性能評估工具（用於測試和對比）
- **`compare_all_versions.py`** - 快速版本對比工具

## 🚀 快速開始

### 1. 安裝依賴

```bash
# 必需
pip install numpy pyyaml

# 音頻處理（擇一）
pip install soundfile  # 推薦
```

### 2. 處理您的音頻文件

```bash
# 最簡單的用法
python process_audio.py your_audio.wav

# 這會在 ./denoised/ 目錄生成：
# - your_audio_v1.wav
# - your_audio_v2.wav
# - your_audio_v3.wav
# - your_audio_v4.wav
```

### 3. 只使用推薦的版本

```bash
# 只使用 V3 和 V4（效果最好）
python process_audio.py your_audio.wav --versions V3 V4
```

## 📊 版本對比

| 版本 | 算法 | 速度 | 質量 | Musical Noise | 推薦用途 |
|------|------|------|------|---------|---------|
| V1 | 頻譜減法 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ✅ 已修復 | 快速測試 |
| V2 | Wiener 濾波 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ✅ 已修復 | 一般應用 |
| V3 | SPP-MMSE | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ✅ 已優化 | **推薦** |
| V4 | IMCRA-OMLSA | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ 已優化 | **最佳質量** |

**v1.1.0 更新**：所有版本的 Musical Noise 問題已修復/優化

## 🎯 使用場景

### 場景 1：錄音降噪

```bash
# 處理錄音文件，使用最佳質量
python process_audio.py recording.wav --versions V4 --output-dir ./clean
```

### 場景 2：對比不同版本效果

```bash
# 生成所有版本，比較效果
python process_audio.py noisy.wav

# 播放並選擇最好的版本
# open denoised/noisy_v1.wav
# open denoised/noisy_v2.wav
# open denoised/noisy_v3.wav
# open denoised/noisy_v4.wav
```

### 場景 3：批量處理

```bash
# 處理目錄下所有 WAV 文件
for file in *.wav; do
    python process_audio.py "$file" --versions V3 V4
done
```

## ⚙️ 調整參數

所有參數都在 `config/` 目錄的 YAML 文件中：

```bash
config/
├── v1_config.yaml  # 頻譜減法參數
├── v2_config.yaml  # Wiener 濾波參數
├── v3_config.yaml  # SPP-MMSE 參數
└── v4_config.yaml  # IMCRA-OMLSA 參數
```

### 常用調整

**增強降噪強度（可能增加失真）：**
```yaml
# 修改 v3_config.yaml 或 v4_config.yaml
gain_calculation:
  g_min_db: -25.0  # 改為 -30.0
```

**減少 Musical Noise（v1.1.0 已優化）：**
```yaml
# V1/V2: 修改 alpha_smooth
gain_calculation:
  alpha_smooth: 0.8  # 改為 0.85 或 0.9

# V3/V4: 修改 alpha_g
gain_calculation:
  alpha_g: 0.85  # 改為 0.9（v1.1.0 默認已從 0.7 提高到 0.85）
```

## 💡 Tips

1. **推薦首選 V3 或 V4**
   - V3：平衡效果和速度
   - V4：追求最佳質量

2. **輸入音頻建議**
   - 採樣率：16kHz（平衡質量和計算量）
   - 格式：WAV 16位 PCM
   - 聲道：單聲道（立體聲會自動轉換）

3. **效果不佳時**
   - 嘗試調整配置文件參數
   - 確認噪聲類型（穩態噪聲效果更好）
   - 檢查輸入音頻質量

4. **性能優化**
   - 降低採樣率到 8kHz 或 16kHz
   - 只處理需要的版本（如只用 V4）
   - 處理前可以先切分長音頻

## 🔍 與其他工具的區別

### process_audio.py（本工具）
- ✅ 處理真實音頻文件
- ✅ 從 config YAML 讀取參數
- ✅ 輸出多個版本供選擇
- ❌ 不進行性能評估
- 📌 **用途：日常音頻降噪**

### benchmark_all.py
- ✅ 性能和音質評估
- ✅ 生成對比表格和報告
- ✅ 支持多種噪聲類型測試
- ❌ 使用合成音頻測試
- 📌 **用途：算法評估和研究**

### compare_all_versions.py
- ✅ 快速對比四個版本
- ✅ 顯示詳細性能數據
- ❌ 使用合成音頻
- ❌ 參數寫死在代碼中
- 📌 **用途：學習和理解算法差異**

## 📝 完整示例

```bash
# 1. 確保安裝依賴
pip install numpy pyyaml soundfile

# 2. 準備音頻文件
# 假設有：my_recording.wav（含噪音頻）

# 3. 處理音頻（使用 V3 和 V4）
python process_audio.py my_recording.wav --versions V3 V4 --output-dir ./output

# 4. 查看結果
ls -lh ./output/
# 輸出：
# my_recording_v3.wav
# my_recording_v4.wav

# 5. 播放並選擇最佳版本
# (在 macOS)
open ./output/my_recording_v3.wav
open ./output/my_recording_v4.wav

# 6. 如果效果不滿意，調整參數
nano config/v4_config.yaml
# 修改 g_min_db 等參數

# 7. 重新處理
python process_audio.py my_recording.wav --versions V4 --output-dir ./output_v2
```

## 📚 更多資源

- [詳細使用說明](PROCESS_AUDIO_USAGE.md)
- [配置文件說明](../config/)
- [項目文檔](../README.md)
- [性能評估指南](../comparison_tables.md)

## ❓ 常見問題

**Q: 為什麼輸出聲音有點怪？**
A: 可能是降噪太強。調整 `g_min_db` 從 -20 改為 -15。

**Q: 降噪效果不明顯？**
A: 可能是降噪不足。調整 `g_min_db` 從 -20 改為 -25。

**Q: 有 Musical Noise（震動聲、金屬音）？**
A: v1.1.0 已修復。如仍有問題，提高平滑因子：
- V1/V2: `alpha_smooth: 0.8 → 0.85`
- V3/V4: `alpha_g: 0.85 → 0.9`

**Q: 可以處理 MP3 文件嗎？**
A: 需要先轉換為 WAV：
```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 output.wav
```

**Q: 處理速度慢？**
A: 
1. 只使用 V2（最快）
2. 降低採樣率
3. 分段處理長音頻

---

**祝您使用愉快！** 🎉

如有問題，請查看 [PROCESS_AUDIO_USAGE.md](PROCESS_AUDIO_USAGE.md) 或提交 issue。
