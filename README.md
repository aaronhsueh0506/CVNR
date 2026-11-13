# NR · 單聲道降噪

C 函式庫實作 V3-2 MMSE-LSA／OMLSA 與 MCRA 噪音追蹤。每 hop 接收一幀複數頻譜，可取回增強頻譜或逐頻帶增益。呼叫端負責 STFT、合成及 overlap-add。

## 先處理一段 WAV

將 `audiolib/` 和 `NR/` 放在同一層。在 NR 根目錄執行下列命令。

```sh
make -C c_impl
bin="$(make -s -C c_impl print-bin-dir)"
"$bin/denoise_wav" input.wav output.wav --nr-level 2
```

預設 grid 是 8 kHz 128/64、16 kHz 256/128、48 kHz 1024/512（FFT／hop）。8 kHz 另支援 256/128，16 kHz 另支援 512/256。Python 的 `--nr-mode` 接受 `mild`、`moderate`、`balanced`、`aggressive`；C 的 `--nr-level` 只接受數字 `0`..`3`（`0` mild、`1` moderate、`2` balanced（預設）、`3` aggressive），其他值以結束碼 2 拒絕。

<a id="limitations"></a>
約 200 ms 的初始非靜音資料供噪音估計使用，建議使用背景噪音或弱語音。改變取樣率或 FFT 長度時請重新建立 instance。音樂、競爭語音、風切與突發聲都可能偏離穩態噪音假設。

**[開啟 NR 文件](docs/html/index.html)** · 可在本機離線閱讀。
