"""
RNNoise v0.2 風格噪音抑制模型 — 訓練腳本
基於官方 xiph/rnnoise torch 版本架構，適配 8kHz / ERB bands / 無 pitch

用法:
    python train.py --librispeech /path/to/LibriSpeech --noise-dir ./noise
"""

import argparse
import glob
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from torch.utils.data import Dataset, DataLoader, random_split
import tqdm

# ============================================================
# 常數
# ============================================================
SR = 8000
N_FFT = 256
WIN_LEN = 160       # 20ms
HOP_LEN = 80        # 10ms
N_BANDS = 18
SEGMENT_SEC = 3.0
SEGMENT_SAMPLES = int(SEGMENT_SEC * SR)     # 24000
SNR_LEVELS = [0, 5, 10, 15, 20]

# ============================================================
# ERB Band 工具
# ============================================================

def erb_rate(f):
    """頻率 (Hz) → ERB-rate (Glasberg & Moore 1990)"""
    return 21.4 * np.log10(0.00437 * f + 1)

def erb_inv(e):
    """ERB-rate → 頻率 (Hz)"""
    return (10 ** (e / 21.4) - 1) / 0.00437

def compute_erb_bands(n_fft=N_FFT, sr=SR, n_bands=N_BANDS):
    """計算 ERB band 的 FFT bin 邊界，回傳 shape=(n_bands+1,) 的整數陣列"""
    n_bins = n_fft // 2 + 1
    e_low = erb_rate(0)
    e_high = erb_rate(sr / 2)
    erb_edges = np.linspace(e_low, e_high, n_bands + 1)
    freq_edges = erb_inv(erb_edges)
    bin_edges = np.round(freq_edges / (sr / n_fft)).astype(int)
    bin_edges = np.clip(bin_edges, 0, n_bins - 1)
    # 確保單調遞增，沒有空 band
    for i in range(1, len(bin_edges)):
        if bin_edges[i] <= bin_edges[i - 1]:
            bin_edges[i] = bin_edges[i - 1] + 1
    bin_edges[-1] = min(bin_edges[-1], n_bins)
    return bin_edges

# 預先計算全域 bin edges
BIN_EDGES = compute_erb_bands()

def band_energy(power_spec, bin_edges=BIN_EDGES):
    """
    從 power spectrum 計算各 ERB band 能量
    power_spec: (..., n_bins)
    回傳: (..., n_bands)
    """
    bands = []
    for b in range(len(bin_edges) - 1):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        bands.append(power_spec[..., lo:hi].sum(dim=-1))
    return torch.stack(bands, dim=-1)

def extract_features(power_spec, bin_edges=BIN_EDGES):
    """power spectrum → log ERB band energy (正規化)"""
    energy = band_energy(power_spec, bin_edges)
    log_energy = torch.log(energy + 1e-10)
    # per-utterance 正規化
    mean = log_energy.mean(dim=-2, keepdim=True)
    std = log_energy.std(dim=-2, keepdim=True) + 1e-8
    return (log_energy - mean) / std

def compute_gain_target(clean_power, noisy_power, bin_edges=BIN_EDGES):
    """
    計算 per-band ideal ratio mask (amplitude domain)
    clean_power, noisy_power: (n_frames, n_bins)
    回傳: (n_frames, n_bands), 值域 [0, 1]
    """
    clean_energy = band_energy(clean_power, bin_edges)
    noisy_energy = band_energy(noisy_power, bin_edges)
    ratio = clean_energy / (noisy_energy + 1e-10)
    gain = torch.sqrt(torch.clamp(ratio, 0.0, 1.0))
    return gain

# ============================================================
# STFT 工具
# ============================================================

def stft(audio, n_fft=N_FFT, hop=HOP_LEN, win_len=WIN_LEN):
    """回傳 complex spectrum, shape=(n_frames, n_bins)"""
    window = torch.hann_window(win_len, device=audio.device)
    spec = torch.stft(audio, n_fft, hop_length=hop, win_length=win_len,
                      window=window, return_complex=True, center=True)
    return spec.T  # (n_bins, n_frames) → (n_frames, n_bins)

# ============================================================
# 模型 (基於 RNNoise v0.2 官方 PyTorch 架構)
# ============================================================

class RNNoiseModel(nn.Module):
    """
    架構沿用官方 v0.2: Conv1d 前處理 + 3 層 GRU + concat 全層輸出
    差異: 輸入改為 ERB band log energy, 無 VAD, 無 sparsification
    """
    def __init__(self, n_bands=N_BANDS, cond_size=64, gru_size=128):
        super().__init__()
        self.n_bands = n_bands
        self.gru_size = gru_size

        # Conv1d 前處理 (k=3 + k=1, 減少 latency)
        self.conv1 = nn.Conv1d(n_bands, cond_size, kernel_size=3, padding=0)
        self.conv2 = nn.Conv1d(cond_size, gru_size, kernel_size=1)

        # 3 層 GRU
        self.gru1 = nn.GRU(gru_size, gru_size, batch_first=True)
        self.gru2 = nn.GRU(gru_size, gru_size, batch_first=True)
        self.gru3 = nn.GRU(gru_size, gru_size, batch_first=True)

        # 輸出: concat(conv_out, gru1, gru2, gru3) → gains
        self.dense_out = nn.Linear(4 * gru_size, n_bands)

        # 初始化 GRU hidden weights 為 orthogonal
        for gru in [self.gru1, self.gru2, self.gru3]:
            for name, param in gru.named_parameters():
                if 'weight_hh' in name:
                    nn.init.orthogonal_(param)

        n_params = sum(p.numel() for p in self.parameters())
        print(f"Model: {n_params:,} parameters")

    def forward(self, x, states=None):
        """
        x: (batch, seq_len, n_bands)
        states: [h1, h2, h3] 或 None
        回傳: gains (batch, seq_len', n_bands), new_states
              seq_len' = seq_len - 2 (conv1 kernel=3 valid 減 2 frame)
        """
        device = x.device
        batch = x.size(0)

        if states is None:
            h1 = torch.zeros(1, batch, self.gru_size, device=device)
            h2 = torch.zeros(1, batch, self.gru_size, device=device)
            h3 = torch.zeros(1, batch, self.gru_size, device=device)
        else:
            h1, h2, h3 = states

        # Conv1d 前處理: (B, T, C) → (B, C, T) → conv → (B, C, T') → (B, T', C)
        tmp = x.permute(0, 2, 1)
        tmp = torch.tanh(self.conv1(tmp))
        tmp = torch.tanh(self.conv2(tmp))
        conv_out = tmp.permute(0, 2, 1)  # (B, T-2, gru_size)

        # 3 層 GRU
        gru1_out, h1 = self.gru1(conv_out, h1)
        gru2_out, h2 = self.gru2(gru1_out, h2)
        gru3_out, h3 = self.gru3(gru2_out, h3)

        # Concat 全層輸出 (同官方 v0.2)
        cat = torch.cat([conv_out, gru1_out, gru2_out, gru3_out], dim=-1)
        gains = torch.sigmoid(self.dense_out(cat))

        return gains, [h1, h2, h3]

# ============================================================
# Dataset
# ============================================================

class NoisySpeechDataset(Dataset):
    """
    LibriSpeech (clean) + 噪音資料夾 (noise)，on-the-fly 混合
    每個 sample 回傳: (features, target_gains)，shape 都是 (n_frames, n_bands)
    """
    def __init__(self, librispeech_root, noise_dir, sr=SR,
                 segment_sec=SEGMENT_SEC, snr_levels=SNR_LEVELS):
        self.sr = sr
        self.segment_samples = int(segment_sec * sr)
        self.snr_levels = snr_levels

        # 掃描所有語音檔 (.flac)
        self.speech_files = sorted(
            glob.glob(os.path.join(librispeech_root, '**', '*.flac'), recursive=True)
        )
        if not self.speech_files:
            raise FileNotFoundError(f"在 {librispeech_root} 找不到 .flac 檔案")

        # 掃描所有噪音檔 (.wav)
        self.noise_files = sorted(glob.glob(os.path.join(noise_dir, '*.wav')))
        if not self.noise_files:
            raise FileNotFoundError(f"在 {noise_dir} 找不到 .wav 檔案")

        print(f"Dataset: {len(self.speech_files)} speech files, "
              f"{len(self.noise_files)} noise files")

    def __len__(self):
        return len(self.speech_files)

    def _load_and_crop(self, path, target_len):
        """載入音檔、resample 到目標取樣率、隨機裁切到指定長度"""
        audio, orig_sr = torchaudio.load(path)
        audio = audio[0]  # mono
        if orig_sr != self.sr:
            audio = torchaudio.functional.resample(audio, orig_sr, self.sr)
        # 隨機裁切或 zero-pad
        if len(audio) >= target_len:
            start = random.randint(0, len(audio) - target_len)
            audio = audio[start:start + target_len]
        else:
            audio = F.pad(audio, (0, target_len - len(audio)))
        return audio

    def _load_noise(self, target_len):
        """載入噪音、若不夠長則 loop"""
        path = random.choice(self.noise_files)
        audio, orig_sr = torchaudio.load(path)
        audio = audio[0]
        if orig_sr != self.sr:
            audio = torchaudio.functional.resample(audio, orig_sr, self.sr)
        # Loop 到足夠長度
        if len(audio) < target_len:
            repeats = (target_len // len(audio)) + 1
            audio = audio.repeat(repeats)
        start = random.randint(0, len(audio) - target_len)
        return audio[start:start + target_len]

    def __getitem__(self, idx):
        # 載入語音
        speech = self._load_and_crop(self.speech_files[idx], self.segment_samples)

        # 載入噪音
        noise = self._load_noise(self.segment_samples)

        # 隨機選擇 SNR 並混合
        snr_db = random.choice(self.snr_levels)
        speech_rms = speech.pow(2).mean().sqrt() + 1e-10
        noise_rms = noise.pow(2).mean().sqrt() + 1e-10
        noise_scaled = noise * (speech_rms / noise_rms) * (10 ** (-snr_db / 20))
        noisy = speech + noise_scaled

        # STFT
        clean_spec = stft(speech)      # (n_frames, n_bins)
        noisy_spec = stft(noisy)

        clean_power = clean_spec.abs().pow(2)
        noisy_power = noisy_spec.abs().pow(2)

        # 特徵與目標
        features = extract_features(noisy_power)            # (n_frames, n_bands)
        target_gains = compute_gain_target(clean_power, noisy_power)  # (n_frames, n_bands)

        return features, target_gains

# ============================================================
# 訓練
# ============================================================

def train(args):
    device = torch.device(args.device)

    # Dataset
    dataset = NoisySpeechDataset(args.librispeech, args.noise_dir)
    n_val = max(1, int(len(dataset) * 0.1))
    n_train = len(dataset) - n_val
    train_set, val_set = random_split(dataset, [n_train, n_val])

    train_loader = DataLoader(train_set, batch_size=args.batch_size,
                              shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, num_workers=2)

    # 模型
    model = RNNoiseModel(n_bands=N_BANDS, cond_size=64, gru_size=128).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, betas=(0.8, 0.98))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lr_lambda=lambda step: 1.0 / (1.0 + 5e-5 * step)
    )

    gamma = 0.5  # perceptual exponent

    os.makedirs(args.output_dir, exist_ok=True)
    best_val_loss = float('inf')

    for epoch in range(1, args.epochs + 1):
        # --- Train ---
        model.train()
        train_loss_sum = 0
        with tqdm.tqdm(train_loader, desc=f"Epoch {epoch}/{args.epochs}") as pbar:
            for features, targets in pbar:
                features = features.to(device)
                targets = targets.to(device)

                pred_gains, _ = model(features)
                # Conv1d valid padding 會減少 2 個 frame
                targets = targets[:, 1:-1, :]

                loss = F.mse_loss(pred_gains ** gamma, targets ** gamma)

                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()

                train_loss_sum += loss.item()
                pbar.set_postfix(loss=f"{loss.item():.5f}")

        avg_train = train_loss_sum / len(train_loader)

        # --- Validation ---
        model.eval()
        val_loss_sum = 0
        with torch.no_grad():
            for features, targets in val_loader:
                features = features.to(device)
                targets = targets.to(device)
                pred_gains, _ = model(features)
                targets = targets[:, 1:-1, :]
                val_loss_sum += F.mse_loss(pred_gains ** gamma, targets ** gamma).item()

        avg_val = val_loss_sum / max(len(val_loader), 1)
        print(f"  train_loss={avg_train:.5f}  val_loss={avg_val:.5f}")

        # 儲存 checkpoint
        ckpt = {
            'epoch': epoch,
            'state_dict': model.state_dict(),
            'loss': avg_val,
            'bin_edges': BIN_EDGES.tolist(),
        }
        torch.save(ckpt, os.path.join(args.output_dir, f'rnnoise_epoch{epoch}.pth'))

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save(ckpt, os.path.join(args.output_dir, 'rnnoise_best.pth'))
            print(f"  ✓ best model saved (val_loss={avg_val:.5f})")

# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RNNoise v0.2 訓練 (8kHz, ERB bands)')
    parser.add_argument('--librispeech', required=True, help='LibriSpeech 根目錄')
    parser.add_argument('--noise-dir', default='./noise', help='噪音 wav 資料夾')
    parser.add_argument('--output-dir', default='./output', help='模型輸出資料夾')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    train(parser.parse_args())
