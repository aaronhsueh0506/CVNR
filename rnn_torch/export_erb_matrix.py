"""
匯出 ERB 轉換矩陣

用法:
    python export_erb_matrix.py --format npy      # 輸出 .npy
    python export_erb_matrix.py --format c        # 輸出 C header
    python export_erb_matrix.py --format all      # 全部格式
"""

import argparse
import numpy as np

# ERB 參數 (與 train.py 一致)
SR = 8000
N_FFT = 256
N_BANDS = 18


def erb_rate(f):
    """頻率 (Hz) → ERB-rate (Glasberg & Moore 1990)"""
    return 21.4 * np.log10(0.00437 * f + 1)


def erb_inv(e):
    """ERB-rate → 頻率 (Hz)"""
    return (10 ** (e / 21.4) - 1) / 0.00437


def compute_erb_bands(n_fft=N_FFT, sr=SR, n_bands=N_BANDS):
    """計算 ERB band 的 FFT bin 邊界"""
    n_bins = n_fft // 2 + 1
    e_low = erb_rate(0)
    e_high = erb_rate(sr / 2)
    erb_edges = np.linspace(e_low, e_high, n_bands + 1)
    freq_edges = erb_inv(erb_edges)
    bin_edges = np.round(freq_edges / (sr / n_fft)).astype(int)
    bin_edges = np.clip(bin_edges, 0, n_bins - 1)
    for i in range(1, len(bin_edges)):
        if bin_edges[i] <= bin_edges[i - 1]:
            bin_edges[i] = bin_edges[i - 1] + 1
    bin_edges[-1] = min(bin_edges[-1], n_bins)
    return bin_edges


def compute_erb_matrix(n_fft=N_FFT, n_bands=N_BANDS):
    """
    建構 ERB 轉換矩陣 W, shape = (n_bins, n_bands)

    Forward:  band_energy = power_spec @ W
    Backward: bin_gains = W @ band_gains
    """
    bin_edges = compute_erb_bands(n_fft=n_fft, n_bands=n_bands)
    n_bins = n_fft // 2 + 1
    W = np.zeros((n_bins, n_bands), dtype=np.float32)

    for b in range(n_bands):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        W[lo:hi, b] = 1.0

    return W, bin_edges


def export_npy(W, output_path):
    """儲存為 .npy"""
    np.save(output_path, W)
    print(f"已儲存: {output_path}")


def export_c_header(W, bin_edges, output_path):
    """儲存為 C header"""
    n_bins, n_bands = W.shape

    with open(output_path, 'w') as f:
        f.write("/* ERB 轉換矩陣 - 自動產生 */\n")
        f.write(f"/* N_BINS={n_bins}, N_BANDS={n_bands}, N_FFT={N_FFT}, SR={SR} */\n\n")
        f.write("#ifndef ERB_MATRIX_H\n")
        f.write("#define ERB_MATRIX_H\n\n")

        f.write(f"#define ERB_N_BINS {n_bins}\n")
        f.write(f"#define ERB_N_BANDS {n_bands}\n\n")

        # bin edges
        f.write(f"static const int ERB_BIN_EDGES[{n_bands + 1}] = {{\n    ")
        f.write(", ".join(str(int(e)) for e in bin_edges))
        f.write("\n};\n\n")

        # 完整矩陣 (row-major: W[bin][band])
        f.write(f"/* W[n_bins][n_bands] - row major */\n")
        f.write(f"static const float ERB_MATRIX[{n_bins}][{n_bands}] = {{\n")
        for i in range(n_bins):
            row = ", ".join(f"{v:.1f}f" for v in W[i])
            f.write(f"    {{{row}}}")
            if i < n_bins - 1:
                f.write(",")
            f.write(f"  /* bin {i} */\n")
        f.write("};\n\n")

        # 轉置矩陣 (方便 backward: W_T[band][bin])
        f.write(f"/* W_T[n_bands][n_bins] - for backward expansion */\n")
        f.write(f"static const float ERB_MATRIX_T[{n_bands}][{n_bins}] = {{\n")
        W_T = W.T
        for b in range(n_bands):
            row = ", ".join(f"{v:.1f}f" for v in W_T[b])
            f.write(f"    {{{row}}}")
            if b < n_bands - 1:
                f.write(",")
            f.write(f"  /* band {b} */\n")
        f.write("};\n\n")

        f.write("#endif /* ERB_MATRIX_H */\n")

    print(f"已儲存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='匯出 ERB 轉換矩陣')
    parser.add_argument('--format', choices=['npy', 'c', 'all'], default='all',
                        help='輸出格式')
    parser.add_argument('--output-dir', default='output', help='輸出目錄')
    args = parser.parse_args()

    import os
    os.makedirs(args.output_dir, exist_ok=True)

    W, bin_edges = compute_erb_matrix()
    n_bins, n_bands = W.shape

    print(f"ERB Matrix: ({n_bins}, {n_bands})")
    print(f"Bin edges: {bin_edges.tolist()}")
    print(f"Non-zero entries: {int(W.sum())} (每個 bin 只屬於一個 band)")
    print()

    if args.format in ('npy', 'all'):
        export_npy(W, os.path.join(args.output_dir, 'erb_matrix.npy'))

    if args.format in ('c', 'all'):
        export_c_header(W, bin_edges, os.path.join(args.output_dir, 'erb_matrix.h'))

    # 驗證
    print("\n=== 驗證 ===")
    # 模擬 power spectrum
    power = np.random.rand(n_bins).astype(np.float32)

    # Forward: band_energy = power @ W
    band_energy = power @ W
    print(f"Forward: power ({n_bins},) @ W ({n_bins},{n_bands}) → band_energy ({n_bands},)")

    # Backward: bin_gains = W @ band_gains
    band_gains = np.random.rand(n_bands).astype(np.float32)
    bin_gains = W @ band_gains
    print(f"Backward: W ({n_bins},{n_bands}) @ band_gains ({n_bands},) → bin_gains ({n_bins},)")

    # 驗證與 for-loop 版本一致
    band_energy_loop = np.zeros(n_bands)
    for b in range(n_bands):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        band_energy_loop[b] = power[lo:hi].sum()

    bin_gains_loop = np.zeros(n_bins)
    for b in range(n_bands):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        bin_gains_loop[lo:hi] = band_gains[b]

    print(f"Forward  max diff: {np.abs(band_energy - band_energy_loop).max():.2e}")
    print(f"Backward max diff: {np.abs(bin_gains - bin_gains_loop).max():.2e}")


if __name__ == '__main__':
    main()
