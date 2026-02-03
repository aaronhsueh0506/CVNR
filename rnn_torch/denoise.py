"""
RNNoise v0.2 風格噪音抑制 — 推論腳本

用法:
    python denoise.py --model output/rnnoise_best.pth --input noisy.wav --output clean.wav

量化校正資料:
    python denoise.py --model output/rnnoise_best.pth --input noisy.wav --output clean.wav \
                      --dump-calib calib/ --max-frames 200
"""

import argparse
import os
import numpy as np
import torch
import torchaudio

from train import (
    SR, N_FFT, WIN_LEN, HOP_LEN, N_BANDS,
    BIN_EDGES, RNNoiseModel, band_energy, extract_features,
)


def streaming_forward_with_dump(model, features, dump_dir, max_frames):
    """
    Streaming 逐幀推論，同時存下每幀的 ONNX 輸入供量化校正。

    features: (n_frames, n_bands)
    存檔: dump_dir/frame_XXXX.npy，每個檔案包含 {input, h1_in, h2_in, h3_in}
    """
    os.makedirs(dump_dir, exist_ok=True)
    n_frames = features.size(0)
    gru_size = model.gru_size

    h1 = torch.zeros(1, 1, gru_size)
    h2 = torch.zeros(1, 1, gru_size)
    h3 = torch.zeros(1, 1, gru_size)

    saved = 0
    with torch.no_grad():
        for t in range(2, n_frames):
            x = features[t-2:t+1, :].unsqueeze(0)  # (1, 3, N_BANDS)

            # 存校正資料
            if saved < max_frames:
                np.save(os.path.join(dump_dir, f'frame_{saved:04d}.npy'), {
                    'input': x.numpy(),
                    'h1_in': h1.numpy(),
                    'h2_in': h2.numpy(),
                    'h3_in': h3.numpy(),
                })
                saved += 1

            # streaming forward
            tmp = x.permute(0, 2, 1)
            tmp = torch.tanh(model.conv1(tmp))
            tmp = torch.tanh(model.conv2(tmp))
            conv_out = tmp.permute(0, 2, 1)

            g1, h1 = model.gru1(conv_out, h1)
            g2, h2 = model.gru2(g1, h2)
            g3, h3 = model.gru3(g2, h3)

    print(f"校正資料已存: {dump_dir}/ ({saved} frames)")


def denoise(args):
    device = torch.device('cpu')

    # 載入模型
    ckpt = torch.load(args.model, map_location=device, weights_only=False)
    model = RNNoiseModel(n_bands=N_BANDS, cond_size=64, gru_size=128)
    model.load_state_dict(ckpt['state_dict'])
    model.eval()

    bin_edges = np.array(ckpt.get('bin_edges', BIN_EDGES.tolist()))

    # 載入音檔
    audio, orig_sr = torchaudio.load(args.input)
    audio = audio[0]  # mono
    if orig_sr != SR:
        audio = torchaudio.functional.resample(audio, orig_sr, SR)

    # STFT
    window = torch.hann_window(WIN_LEN)
    spec = torch.stft(audio, N_FFT, hop_length=HOP_LEN, win_length=WIN_LEN,
                      window=window, return_complex=True, center=True)
    # spec: (n_bins, n_frames)

    power = spec.abs().pow(2).T  # (n_frames, n_bins)
    features = extract_features(power, bin_edges)  # (n_frames, n_bands)

    # 存量化校正資料
    if args.dump_calib:
        streaming_forward_with_dump(model, features, args.dump_calib, args.max_frames)

    # 推論 (batch)
    with torch.no_grad():
        gains, _ = model(features.unsqueeze(0))  # (1, n_frames-2, n_bands)
    gains = gains.squeeze(0)  # (n_frames-2, n_bands)

    # 將 band gains 展開到每個 FFT bin
    n_bins = spec.size(0)
    n_frames_out = gains.size(0)
    bin_gains = torch.ones(n_bins, spec.size(1))  # 預設 gain=1

    for b in range(N_BANDS):
        lo, hi = int(bin_edges[b]), int(bin_edges[b + 1])
        bin_gains[lo:hi, 1:1 + n_frames_out] = gains[:, b].unsqueeze(0)

    # 套用 gain 到 complex spectrum
    filtered = spec * bin_gains

    # ISTFT
    output = torch.istft(filtered, N_FFT, hop_length=HOP_LEN, win_length=WIN_LEN,
                         window=window, length=len(audio))

    torchaudio.save(args.output, output.unsqueeze(0), SR)
    print(f"降噪完成: {args.output}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RNNoise v0.2 推論 (8kHz, ERB bands)')
    parser.add_argument('--model', required=True, help='模型 .pth 檔案路徑')
    parser.add_argument('--input', required=True, help='輸入含噪音的 wav')
    parser.add_argument('--output', required=True, help='輸出降噪後的 wav')
    parser.add_argument('--dump-calib', default=None, help='存量化校正資料的目錄')
    parser.add_argument('--max-frames', type=int, default=200, help='最多存幾幀校正資料')
    args = parser.parse_args()
    denoise(args)
