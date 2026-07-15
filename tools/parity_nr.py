#!/usr/bin/env python3
"""
parity_nr.py — Python<->C numeric parity harness for the V3-2 MMSE-LSA NR port.

Goal: certify that the C-ported gain / SPP / MCRA arithmetic matches the Python
V3-2 reference, ISOLATED from any FFT-backend difference. We do that by feeding
the *identical* per-frame complex input spectra to both sides:

  Python side (this script):
    1. Load a test wav, run the Python FrameProcessor (window + rFFT) to get the
       per-frame complex spectra X[f, k]  (the production v3_2 framing).
    2. Run the production V3-2 MmseLsaDenoiser (standalone YAML config) and dump
       the per-frame Python gain G_py[f, k] (denoise(..., return_gain=True)).
    3. Dump the input spectra (real/imag) + Python gains to a raw float32 file.

  C side (c_impl/example/parity_runner):
    Reads the SAME input spectra, drives mmse_lsa_process_gain() frame-by-frame,
    dumps the C gains G_c[f, k].

  Diff (this script, --compare):
    worst |G_py - G_c| and median |G_py - G_c| over all frames x bins.

Because both sides see byte-identical input spectra, any residual delta is purely
the gain/SPP/MCRA computation — exactly what we want to certify. Run the C side
once with `make` (fast-math) and once with `make debug` (-DUSE_STANDARD_MATH).

Binary file layout (little-endian float32, header is int32):
  [magic=0x4e525031 'NRP1'][n_frames][n_freqs]
  then per frame f:  X_re[n_freqs], X_im[n_freqs]
  then per frame f:  G_py[n_freqs]
  (C runner appends nothing; it writes a separate gains-only file.)

C gains file layout:
  [n_frames][n_freqs]  then per frame: G_c[n_freqs]

Usage:
  # 1. dump Python reference spectra + gains
  python3 tools/parity_nr.py dump --wav test_wav/wav/babble_10dB.wav \
        --out /tmp/parity_in.bin

  # 2. (build + run C side -- see c_impl/example/parity_runner.c)
  #    bin/ is now keyed bin/<backend>-<config-hash>/ (round-3 review B01);
  #    resolve the exact path with `make -C c_impl print-bin-dir` (same
  #    BACKEND/EXTRA_CFLAGS as the `make parity` build below):
  "$(make -s -C c_impl print-bin-dir)"/parity_runner /tmp/parity_in.bin /tmp/parity_c_gains.bin

  # 3. compare
  python3 tools/parity_nr.py compare --ref /tmp/parity_in.bin \
        --c-gains /tmp/parity_c_gains.bin
"""

import argparse
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import FrameProcessor                       # noqa: E402
from utils.audio_io import read_audio                 # noqa: E402

MAGIC = 0x4E525031  # 'NRP1'


def _build_reference_denoiser(sample_rate, config_dir, mode='full', strength='balanced'):
    """Build the production V3-2 MmseLsaDenoiser exactly like process_audio.py.

    strength = the depth preset (mild|moderate|balanced|aggressive), mirrored by C
    mmse_lsa_config_for_mode(). mode = content axis (full|stationary), mirrored by C
    mmse_lsa_apply_stationary(). Pass the SAME two args to parity_runner.
    """
    # Reuse process_audio's loader so config/v3_2_config.yaml drives the params.
    from process_audio import create_denoiser_from_config
    return create_denoiser_from_config('V3-2', config_dir, sample_rate,
                                        mode=mode, strength=strength)


def cmd_dump(args):
    audio, sr = read_audio(args.wav)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = audio.astype(np.float64)

    config_dir = args.config_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')

    denoiser = _build_reference_denoiser(sr, config_dir, mode=args.mode, strength=args.strength)
    params = denoiser.get_params()
    frame_size = params['frame_size']
    frame_shift = params['frame_shift']
    fft_size = params['fft_size']

    # 1. Per-frame complex spectra from the SAME framing as the denoiser uses.
    proc = FrameProcessor(sample_rate=sr, frame_size=frame_size,
                          frame_shift=frame_shift, fft_size=fft_size,
                          window_type='hanning')
    _, _, spectra = proc.process_signal(audio)          # (n_frames, n_freqs) complex
    n_frames, n_freqs = spectra.shape

    # 2. Production Python gains (includes init-passthrough frames at gain=1).
    _, gain_hist = denoiser.denoise(audio, return_gain=True)
    assert gain_hist.shape == (n_frames, n_freqs), (
        f"gain shape {gain_hist.shape} != spectra {spectra.shape}")

    # 3. Dump: header + spectra(re,im) + python gains.
    X_re = np.real(spectra).astype(np.float32)
    X_im = np.imag(spectra).astype(np.float32)
    G_py = gain_hist.astype(np.float32)

    with open(args.out, 'wb') as fh:
        fh.write(struct.pack('<iii', MAGIC, n_frames, n_freqs))
        for f in range(n_frames):
            fh.write(X_re[f].tobytes())
            fh.write(X_im[f].tobytes())
        for f in range(n_frames):
            fh.write(G_py[f].tobytes())

    print(f"[dump] wav={args.wav} sr={sr}")
    print(f"[dump] frame={frame_size} hop={frame_shift} fft={fft_size} "
          f"n_freqs={n_freqs} n_frames={n_frames}")
    print(f"[dump] wrote {args.out} ({os.path.getsize(args.out)} bytes)")


def _read_ref(path):
    with open(path, 'rb') as fh:
        magic, n_frames, n_freqs = struct.unpack('<iii', fh.read(12))
        assert magic == MAGIC, f"bad magic {magic:#x}"
        spec = np.frombuffer(
            fh.read(n_frames * n_freqs * 2 * 4), dtype='<f4'
        ).reshape(n_frames, 2, n_freqs)
        G_py = np.frombuffer(
            fh.read(n_frames * n_freqs * 4), dtype='<f4'
        ).reshape(n_frames, n_freqs)
    return n_frames, n_freqs, G_py


def _read_c_gains(path):
    with open(path, 'rb') as fh:
        n_frames, n_freqs = struct.unpack('<ii', fh.read(8))
        G_c = np.frombuffer(
            fh.read(n_frames * n_freqs * 4), dtype='<f4'
        ).reshape(n_frames, n_freqs)
    return n_frames, n_freqs, G_c


def cmd_compare(args):
    nf_ref, nfreq_ref, G_py = _read_ref(args.ref)
    nf_c, nfreq_c, G_c = _read_c_gains(args.c_gains)
    assert (nf_ref, nfreq_ref) == (nf_c, nfreq_c), (
        f"shape mismatch ref={nf_ref}x{nfreq_ref} c={nf_c}x{nfreq_c}")

    diff = np.abs(G_py.astype(np.float64) - G_c.astype(np.float64))
    worst = float(diff.max())
    median = float(np.median(diff))
    mean = float(diff.mean())
    # locate worst
    fi, ki = np.unravel_index(np.argmax(diff), diff.shape)

    print(f"[compare] frames={nf_ref} bins={nfreq_ref} "
          f"(total {diff.size} gain values)")
    print(f"[compare] worst |Δgain| = {worst:.3e}  (frame {fi}, bin {ki}: "
          f"py={G_py[fi, ki]:.6f} c={G_c[fi, ki]:.6f})")
    print(f"[compare] median |Δgain| = {median:.3e}")
    print(f"[compare] mean  |Δgain| = {mean:.3e}")
    return worst, median


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('dump', help='dump Python reference spectra + gains')
    d.add_argument('--wav', required=True)
    d.add_argument('--out', required=True)
    d.add_argument('--config-dir', default=None)
    d.add_argument('--mode', choices=('full', 'stationary'), default='full',
                   help="NR content mode (must match parity_runner's mode arg)")
    d.add_argument('--strength', choices=('mild', 'moderate', 'balanced', 'aggressive'),
                   default='balanced',
                   help="NR strength preset (must match parity_runner's strength arg)")
    d.set_defaults(func=cmd_dump)

    c = sub.add_parser('compare', help='compare Python vs C gains')
    c.add_argument('--ref', required=True, help='Python dump file')
    c.add_argument('--c-gains', required=True, help='C gains file')
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
