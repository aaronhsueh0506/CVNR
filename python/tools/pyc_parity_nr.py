#!/usr/bin/env python3
"""
pyc_parity_nr.py -- Python<->C numeric parity tool for the V3-2 MMSE-LSA noise reduction.

Driven by c_impl/test/pyc_parity_nr.sh, which builds the C side and passes the binaries in.
Run the script, not this file.

What it compares
  Layer 1 (L1)  std-math C (SIMD=0, -DUSE_STANDARD_MATH, none of the six USE_* optimizations)
                against the Python reference.  A deviation here is a Python<->C sync bug.
  Layer 2 (L2)  shipping C (Makefile default: SIMD=1, fast math, the six USE_* flags) against the
                std-math C.  This measures the accepted fast-math/optimization approximation.
  Python is not compared with the shipping build directly: that number would mix the two layers.

Scenario kinds
  gain  Identical float32 spectra go to Python (denoise_spectrum on |X32| and angle(X32)) and to the
        C gain drivers (anr_process_gain); the per-bin gains are compared.  Only the gain, SPP and
        noise-tracker arithmetic is measured; FFT differences are excluded.
  e2e   Identical float32 samples go through the whole chain (Python float64 STFT/denoise/OLA vs
        c_impl/example/main.c steps 4-7 in float32); the waveforms are compared.  This includes the
        C FFT/OLA path, so in L2 it also includes the SIMD=1 build of audiolib's FFT.

Inputs are fixed: the pinned wav files in test/pyc_parity/data (sha256 in SHA256SUMS) plus
deterministic transforms of them (zeroed spans, scaling, int16 rounding, spectral bin zeroing, level
steps).  Nothing is random, so repeated runs give a byte-identical JSON.

Verdicts per scenario and layer
  GREEN                    within the tolerance
  RED_EXPECTED(S-xx)       over the tolerance and listed in expected_red.json under that finding
  RED_UNEXPECTED           over the tolerance and not listed                    -> failure
  GREEN_UNEXPECTED(S-xx)   listed as expected red but within the tolerance      -> failure: the
                           finding was fixed, delete its entry from expected_red.json
  ERROR                    a driver failed or produced a non-finite value        -> failure
Exit code 0 = no failure, 1 = failure, 2 = infrastructure error (inputs, build flags, drivers).

The tolerances below are FROZEN (2026-10-20, after S-10/S-11/S-12): chosen from a full measurement
against the post-fix real trees (428 scenarios, grids 8k128/8k256/16k256/16k512/48k1024,
PYTHONHASHSEED=0 two-run byte-identical).  See NR/CHANGELOG.md's tolerance-freeze entry for the
measured worst-GREEN value and margin behind each constant, and for the one constant (gain L2
max_abs) whose real margin is already thin (0.5-2.0x band) and was left unchanged rather than
loosened or tightened on no evidence -- that cell mixes the fast-math approximation budget with all
six USE_* optimization flags (S-10's NEON twin among them) in one tolerance, a known gate blind spot
this freeze does not close.  The measured numbers are always printed next to the tolerances.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

try:
    import numpy as np                                       # noqa: E402
    from core import FrameProcessor                          # noqa: E402
    from core.signal_grid import resolve_signal_grid         # noqa: E402
    from process_audio import create_denoiser_from_config    # noqa: E402
except ImportError as _exc:  # missing numpy/scipy/pyyaml: infrastructure, not a parity failure
    print('pyc_parity_nr: infrastructure error: cannot import the Python reference (%s)' % _exc,
          file=sys.stderr)
    sys.exit(2)

FORMAT = 1
MAGIC = 0x4E525032  # 'NRP2'
STRENGTHS = ('mild', 'moderate', 'balanced', 'aggressive')
GRIDS = ((8000, 128), (8000, 256), (16000, 256), (16000, 512), (48000, 1024))
LAYERS = ('L1', 'L2')

# ---- FROZEN tolerances (2026-10-20; supersedes the Wave-S-prep provisional cut) ------------------
# gain: max|dG| and the 99.9th percentile of |dG| over all frames x bins.
# e2e : rms of the waveform difference relative to the rms of the reference (dB) and max|dy| / peak.
# Measured on the post-S-10/S-11/S-12 real tree (428 scenarios): L1 worst-GREEN max_abs/p999 =
# 3.809e-4 / 5.190e-6 (frozen with ~5x/~4x margin); L2 worst-GREEN max_abs/p999 = 9.693e-2 / 3.186e-3
# (max_abs frozen UNCHANGED at 1.5e-1 -- 2x the measured value already exceeds the old number, so
# this is the loosest defensible freeze, not a tightened one; two real scenarios already sit in the
# harness's own 0.5-2.0x marginal band at this tolerance, see CHANGELOG.md). e2e worst-GREEN
# rms_err_db/max_over_peak: L1 -106.48 dB / 8.439e-6, L2 -61.15 dB / 2.620e-3.
TOLERANCES = {
    'gain': {'L1': {'max_abs': 2.0e-3, 'p999': 2.0e-5},
             'L2': {'max_abs': 1.5e-1, 'p999': 7.0e-3}},
    'e2e': {'L1': {'rms_err_db': -100.0, 'max_over_peak': 2.0e-5},
            'L2': {'rms_err_db': -55.0, 'max_over_peak': 6.0e-3}},
}
# A verdict whose measured/limit ratio lies in (MARGIN_LOW, MARGIN_HIGH) is flagged MARGINAL.
MARGIN_LOW, MARGIN_HIGH = 0.5, 2.0

USE_FLAGS_SHIP = ('-DUSE_FAST_GAIN_SMOOTHING', '-DUSE_SHARED_XI_RATIO', '-DUSE_OPTIMIZED_MIN_BUFFER',
                  '-DUSE_OPTIMIZED_E1', '-DUSE_SINGLE_CLAMP', '-DUSE_INCREMENTAL_MIN')
DEFINES_REQUIRED = {
    'L1': {'-DUSE_STANDARD_MATH', '-DSIMD_KERNELS_FORCE_SCALAR'},
    'L2': set(USE_FLAGS_SHIP),
}
KNOWN_TAGS = ('S-10', 'S-11/S-12', 'S-13')

DATA_FILES = {
    8000: {'babble': 'test_n8_babble_5dB.wav', 'synth': 'test_n8_synth_gaps.wav'},
    16000: {'vctk': 'test_n16_vctk_p232_003.wav', 'babble': 'test_n16_babble_5dB.wav', 'music': 'test_n16_music.wav',
            'scene': 'test_n16_scene_white_0dB.wav', 'synth': 'test_n16_synth_gaps.wav'},
    48000: {'vctk': 'test_n48_vctk_p232_003.wav', 'babble': 'test_n48_babble_5dB.wav', 'synth': 'test_n48_synth_gaps.wav'},
}


# ---- deterministic input transforms -------------------------------------------------------------
def _ident(x, sr):
    return x


def _zero_spans(spans):
    def f(x, sr):
        y = x.copy()
        for t0, dur in spans:
            a = int(round(t0 * sr))
            y[a:a + int(round(dur * sr))] = 0.0
        return y
    return f


def _scale(s):
    return lambda x, sr: x * s


def _step(second_half_gain):
    def f(x, sr):
        y = x.copy()
        y[len(y) // 2:] *= second_half_gain
        return y
    return f


def _int16_peak(lsb):
    """Scale to a peak of `lsb` int16 LSB and round to the int16 grid (no dither)."""
    def f(x, sr):
        y = x / np.max(np.abs(x)) * (lsb / 32768.0)
        return np.round(y * 32768.0) / 32768.0
    return f


def _zero_band_edit(t0, t1, f0_hz, f1_hz):
    """Spectral edit: exact zero in bins f0..f1 (Hz) for the frames covering [t0, t1) seconds."""
    def f(re_, im_, sr, fft, hop):
        a, b = int(t0 * sr / hop), int(t1 * sr / hop)
        k0, k1 = int(round(f0_hz * fft / sr)), int(round(f1_hz * fft / sr))
        re_[a:b, k0:k1 + 1] = 0.0
        im_[a:b, k0:k1 + 1] = 0.0
    return f


# One entry per input family.
#   role      which data file ('speech' = VCTK clip where one exists, else the babble clip)
#   tf        audio transform;  edit  spectral edit on the float32 spectra (gain scenarios only)
#   makeup    make-up gain on in both implementations;  py_prior  Python makeup_prior (None = default)
#   srs       sample rates the family exists for (default: all);  kinds  'gain' and/or 'e2e'
#   exercises {layer: finding} the family can expose.  It documents the mechanism, validates
#             expected_red.json (an entry must name a finding its family exercises on that layer) and
#             labels --emit-expected-red.  Findings (PY_C_SYNC_AUDIT.md): S-10 USE_SHARED_XI_RATIO at
#             zero-power bins; S-11/S-12 C-only 1e-10 initial-PSD floor and hi_gamma epsilon placement;
#             S-13 makeup_prior default.  S-10 and S-11/S-12 were fixed 2026-10-20 (see
#             NR/CHANGELOG.md and c_impl/CHANGELOG.md) and no longer have expected_red.json entries;
#             these families stay here to document/validate the mechanism and because some of them
#             (e.g. int16_pk5/12/18, babble_1e-4) exercise more than one finding.  S-13 remains open.
FAMILIES = (
    dict(name='speech', role='speech', tf=_ident, kinds=('gain', 'e2e'), exercises={}),
    dict(name='babble', role='babble', tf=_ident, kinds=('gain',), srs=(16000, 48000), exercises={}),
    dict(name='music', role='music', tf=_ident, kinds=('gain', 'e2e'), srs=(16000,), exercises={}),
    dict(name='scene_real', role='scene', tf=_ident, kinds=('gain',), srs=(16000,), exercises={}),
    dict(name='scene_up', role='babble', tf=_step(4.0), kinds=('gain',), exercises={}),
    dict(name='scene_down', role='babble', tf=_step(0.125), kinds=('gain',), exercises={}),
    dict(name='synth_gaps', role='synth', tf=_ident, kinds=('gain', 'e2e'),
         exercises={'L2': 'S-10', 'L1': 'S-11/S-12'}),
    dict(name='gap64_500', role='babble', tf=_zero_spans(((4.0, 0.064), (6.0, 0.5))),
         kinds=('gain', 'e2e'), exercises={'L2': 'S-10'}),
    dict(name='zerobins', role='babble', tf=_ident, edit=_zero_band_edit(3.0, 4.0, 1250.0, 1875.0),
         kinds=('gain',), exercises={'L2': 'S-10'}),
    dict(name='scale_1e-3', role='speech', tf=_scale(1e-3), kinds=('gain',),
         exercises={'L1': 'S-11/S-12'}),
    dict(name='scale_1e-4', role='speech', tf=_scale(1e-4), kinds=('gain', 'e2e'),
         exercises={'L1': 'S-11/S-12'}),
    dict(name='scale_1e-5', role='speech', tf=_scale(1e-5), kinds=('gain',),
         exercises={'L1': 'S-11/S-12'}),
    dict(name='scale_1e-6', role='speech', tf=_scale(1e-6), kinds=('gain',),
         exercises={'L1': 'S-11/S-12'}),
    dict(name='int16_pk5', role='speech', tf=_int16_peak(5), kinds=('gain',),
         exercises={'L1': 'S-11/S-12', 'L2': 'S-10'}),
    dict(name='int16_pk12', role='speech', tf=_int16_peak(12), kinds=('gain',),
         exercises={'L1': 'S-11/S-12', 'L2': 'S-10'}),
    dict(name='int16_pk55', role='speech', tf=_int16_peak(55), kinds=('gain',),
         exercises={'L1': 'S-11/S-12', 'L2': 'S-10'}),
    dict(name='babble_1e-4', role='babble', tf=_scale(1e-4), kinds=('gain',), srs=(16000, 48000),
         exercises={'L1': 'S-11/S-12'}),
    dict(name='makeup', role='speech', tf=_ident, makeup=True, py_prior=None, kinds=('gain',),
         exercises={'L1': 'S-13'}),
    dict(name='makeup_xi_ctrl', role='speech', tf=_ident, makeup=True, py_prior='xi', kinds=('gain',),
         exercises={}),
)


def role_file(sr, role):
    """Data file behind a family role ('speech' = the VCTK clip where one exists, else babble)."""
    if role == 'speech':
        role = 'vctk' if 'vctk' in DATA_FILES[sr] else 'babble'
    return DATA_FILES[sr][role]


def _audio_key(fam):
    """Families that share (role, transform, edit) share their spectra."""
    if fam['name'] in ('makeup', 'makeup_xi_ctrl'):
        return 'speech'
    return fam['name']


# ---- small helpers ------------------------------------------------------------------------------
class InfraError(Exception):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def file_sha256(path):
    with open(path, 'rb') as fh:
        return sha256_bytes(fh.read())


def read_wav(path):
    with wave.open(path) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise InfraError('%s: expected 16-bit mono' % path)
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float64) / 32768.0
    return x, sr


def load_inputs(data_dir):
    """Returns ({sr: {role: float64 audio}}, {file: sha256}); verifies the pinned digests."""
    sums = {}
    with open(os.path.join(data_dir, 'SHA256SUMS')) as fh:
        for line in fh:
            if line.strip():
                digest, name = line.split()
                sums[name] = digest
    bases, shas = {}, {}
    for sr, roles in DATA_FILES.items():
        bases[sr] = {}
        for role, name in roles.items():
            path = os.path.join(data_dir, name)
            got = file_sha256(path)
            if sums.get(name) != got:
                raise InfraError('%s: sha256 %s does not match SHA256SUMS' % (name, got))
            x, file_sr = read_wav(path)
            if file_sr != sr:
                raise InfraError('%s: sample rate %d, expected %d' % (name, file_sr, sr))
            bases[sr][role] = x
            shas[name] = got
        bases[sr]['speech'] = bases[sr].get('vctk', bases[sr]['babble'])
    return bases, shas


def enumerate_scenarios():
    """All scenarios in a stable order: list of dicts."""
    out = []
    for sr, fft in GRIDS:
        for fam in FAMILIES:
            if fam.get('srs') and sr not in fam['srs']:
                continue
            for strength in STRENGTHS:
                for kind in fam['kinds']:
                    out.append(dict(
                        id='%s/%dk_%d/%s/%s' % (kind, sr // 1000, fft, strength, fam['name']),
                        kind=kind, sr=sr, fft=fft, strength=strength, fam=fam))
    out.sort(key=lambda s: s['id'])
    return out


def load_registry(path, scenarios):
    """expected_red.json -> {(scenario id, layer): finding label}; validated against the scenarios."""
    with open(path) as fh:
        doc = json.load(fh)
    if doc.get('format') != FORMAT:
        raise InfraError('%s: unsupported format' % path)
    by_id = {s['id']: s for s in scenarios}
    reg = {}
    for tag, layers in doc.get('expected_red', {}).items():
        if tag not in KNOWN_TAGS:
            raise InfraError('%s: unknown finding label %r' % (path, tag))
        for layer, ids in layers.items():
            if layer not in LAYERS:
                raise InfraError('%s: unknown layer %r' % (path, layer))
            for sid in ids:
                if sid not in by_id:
                    raise InfraError('%s: stale scenario id %s' % (path, sid))
                if by_id[sid]['fam']['exercises'].get(layer) != tag:
                    raise InfraError('%s: %s is listed under %s/%s but its family does not exercise '
                                     'that finding on that layer' % (path, sid, tag, layer))
                if (sid, layer) in reg:
                    raise InfraError('%s: duplicate entry %s/%s' % (path, sid, layer))
                reg[(sid, layer)] = tag
    return reg


# ---- Python reference ---------------------------------------------------------------------------
class PyRef:
    def __init__(self, work):
        self.config_dir = os.path.join(os.path.dirname(HERE), 'config')
        self.work = work
        self._variants = {}

    def _variant_dir(self, prior):
        """Copy of the config directory with makeup_gain on (prior None keeps the YAML default)."""
        key = prior or 'default'
        if key not in self._variants:
            d = os.path.join(self.work, 'cfg_makeup_' + key)
            shutil.copytree(self.config_dir, d)
            p = os.path.join(d, 'v3_2_config.yaml')
            with open(p) as fh:
                text = fh.read()
            anchor = 'gain_calculation:\n'
            if text.count(anchor) != 1:
                raise InfraError('v3_2_config.yaml: expected exactly one gain_calculation section')
            add = '  makeup_gain: true\n' + ('  makeup_prior: %s\n' % prior if prior else '')
            with open(p, 'w') as fh:
                fh.write(text.replace(anchor, anchor + add))
            self._variants[key] = d
        return self._variants[key]

    def denoiser(self, sr, fft, strength, makeup=False, prior=None):
        cfg = self._variant_dir(prior) if makeup else self.config_dir
        den = create_denoiser_from_config('V3-2', cfg, sr, mode='full', strength=strength, fft_size=fft)
        if bool(den.makeup_gain) != bool(makeup):
            raise InfraError('Python makeup_gain=%r, expected %r' % (den.makeup_gain, makeup))
        if makeup and den.makeup_prior != (prior or 'spp'):
            raise InfraError('Python makeup_prior=%r, expected %r' % (den.makeup_prior, prior or 'spp'))
        return den

    def gains(self, den, re32, im32):
        X = re32.astype(np.float64) + 1j * im32.astype(np.float64)
        out = den.denoise_spectrum(np.abs(X), np.angle(X), return_gain=True)
        return np.asarray(out[2], dtype=np.float32)


def stft32(audio, sr, fft):
    frame, hop, fft_size = resolve_signal_grid(sr, fft)
    proc = FrameProcessor(sample_rate=sr, frame_size=frame, frame_shift=hop, fft_size=fft_size,
                          window_type='hanning')
    _, _, spec = proc.process_signal(audio)
    return (np.ascontiguousarray(np.real(spec).astype(np.float32)),
            np.ascontiguousarray(np.imag(spec).astype(np.float32)), hop)


# ---- C drivers ----------------------------------------------------------------------------------
ENV = dict(os.environ, OMP_NUM_THREADS='1', LC_ALL='C')


def run_cmd(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=600)
    if r.returncode != 0:
        raise InfraError('%s failed (rc=%d): %s' % (os.path.basename(cmd[0]), r.returncode,
                                                    (r.stderr or r.stdout).strip()))


def write_nrp2(path, re32, im32, G32, sr):
    nf, nb = re32.shape
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<iiii', MAGIC, nf, nb, sr))
        fh.write(np.stack([re32, im32], axis=1).astype('<f4').tobytes())
        fh.write(G32.astype('<f4').tobytes())


def read_gains(path):
    with open(path, 'rb') as fh:
        nf, nb = struct.unpack('<ii', fh.read(8))
        return np.frombuffer(fh.read(nf * nb * 4), dtype='<f4').reshape(nf, nb).copy()


def run_gain_driver(binary, nrp2, strength, makeup, tag):
    out = nrp2 + '.' + tag
    cmd = [binary, nrp2, out, strength] + (['makeup_gain=1'] if makeup else [])
    run_cmd(cmd)
    g = read_gains(out)
    os.remove(out)
    return g


def run_e2e_driver(binary, x32, sr, fft, strength, work, tag):
    inp = os.path.join(work, 'e2e_in.f32')
    out = os.path.join(work, 'e2e_out_%s.f32' % tag)
    x32.astype('<f4').tofile(inp)
    run_cmd([binary, inp, str(len(x32)), str(sr), str(fft), strength, out])
    y = np.fromfile(out, dtype='<f4')
    os.remove(out)
    return y


# ---- metrics and verdicts -----------------------------------------------------------------------
def gain_stats(a32, b32, zero_mask):
    d = np.abs(a32.astype(np.float64) - b32.astype(np.float64))
    finite = bool(np.isfinite(a32).all() and np.isfinite(b32).all())
    fi, ki = np.unravel_index(int(np.argmax(d)), d.shape)
    return dict(
        max_abs=float(d.max()) if finite else None,
        p999=float(np.percentile(d, 99.9)) if finite else None, finite=finite,
        n_gt_1e3=int((d > 1e-3).sum()), n_cells=int(d.size),
        bit_identical=bool(np.array_equal(a32.view(np.uint32), b32.view(np.uint32))),
        worst_frame_bin=[int(fi), int(ki)],
        zero_cells=int(zero_mask.sum()),
        max_zero_cells=float(d[zero_mask].max()) if finite and zero_mask.any() else None,
        max_other_cells=float(d[~zero_mask].max()) if finite and (~zero_mask).any() else None)


def e2e_stats(ref, c32):
    if ref.shape != c32.shape:
        raise InfraError('waveform length mismatch %s vs %s' % (ref.shape, c32.shape))
    r = ref.astype(np.float64)
    c = c32.astype(np.float64)
    d = np.abs(r - c)
    peak = float(np.max(np.abs(r)))
    rms_ref = float(np.sqrt(np.mean(r ** 2)))
    rms_err = float(np.sqrt(np.mean(d ** 2)))
    if rms_ref <= 0.0:
        rms_err_db = None
    elif rms_err <= 0.0:
        rms_err_db = -300.0  # exact
    else:
        rms_err_db = max(20.0 * float(np.log10(rms_err / rms_ref)), -300.0)
    finite = bool(np.isfinite(c32).all() and np.isfinite(ref).all())
    return dict(
        max_abs=float(d.max()) if finite else None,
        max_over_peak=float(d.max() / peak) if finite and peak > 0 else None,
        rms_err_db=rms_err_db if finite else None,
        finite=finite,
        n_samples=int(len(r)),
        bit_identical=bool(np.array_equal(ref.astype(np.float32).view(np.uint32), c32.view(np.uint32))),
        peak_ref=peak)


def judge(kind, layer, st):
    """-> (red, limit_ratio).  Ratio = worst measured/limit over the gated metrics."""
    tol = TOLERANCES[kind][layer]
    if kind == 'gain':
        ratios = [st['max_abs'] / tol['max_abs'], st['p999'] / tol['p999']]
    else:
        # rms_err_db: ratio of linear amplitudes (10^((x - limit)/20))
        ratios = [10.0 ** ((st['rms_err_db'] - tol['rms_err_db']) / 20.0) if st['rms_err_db'] is not None else 0.0,
                  (st['max_over_peak'] or 0.0) / tol['max_over_peak']]
    ratio = max(ratios)
    return ratio > 1.0, ratio


def finish_layer(rec, kind, layer, st, registry):
    sid = rec['id']
    if not st['finite']:
        st.update(red=True, limit_ratio=None, marginal=False, verdict='ERROR', tag=None)
        return
    red, ratio = judge(kind, layer, st)
    tag = registry.get((sid, layer))
    if red:
        verdict = 'RED_EXPECTED(%s)' % tag if tag else 'RED_UNEXPECTED'
    else:
        verdict = 'GREEN_UNEXPECTED(%s)' % tag if tag else 'GREEN'
    st.update(red=red, limit_ratio=ratio, marginal=bool(MARGIN_LOW < ratio < MARGIN_HIGH),
              verdict=verdict, tag=tag)


# ---- run ----------------------------------------------------------------------------------------
def selfcheck(args, bases, work):
    """The gain driver with no override must write the same bytes as example/parity_runner, and must
    reject unknown strengths and overrides.  One scenario per grid, both layers."""
    rows = []
    for sr, fft in GRIDS:
        audio = bases[sr]['speech'][: int(6.0 * sr)]
        re32, im32, _ = stft32(audio, sr, fft)
        path = os.path.join(work, 'selfcheck.nrp2')
        write_nrp2(path, re32, im32, np.zeros_like(re32), sr)
        for layer, drv, runner in (('L1', args.gain_l1, args.runner_l1), ('L2', args.gain_l2, args.runner_l2)):
            a = os.path.join(work, 'sc_driver.bin')
            b = os.path.join(work, 'sc_runner.bin')
            run_cmd([drv, path, a, 'balanced'])
            run_cmd([runner, path, b, 'full', 'balanced'])
            with open(a, 'rb') as fa, open(b, 'rb') as fb:
                same = fa.read() == fb.read()
            rows.append(dict(grid='%dk_%d' % (sr // 1000, fft), layer=layer, byte_identical=same))
            os.remove(a)
            os.remove(b)
        os.remove(path)
    strict = True
    audio = bases[16000]['speech'][: int(1.0 * 16000)]
    re32, im32, _ = stft32(audio, 16000, 256)
    path = os.path.join(work, 'selfcheck.nrp2')
    write_nrp2(path, re32, im32, np.zeros_like(re32), 16000)
    for drv in (args.gain_l1, args.gain_l2):
        for extra in (['bogus'], ['balanced', 'nonexistent=1'], ['balanced', 'makeup_gain=2']):
            r = subprocess.run([drv, path, os.path.join(work, 'none.out')] + extra,
                               capture_output=True, text=True, env=ENV)
            strict = strict and r.returncode != 0
    os.remove(path)
    ok = all(r['byte_identical'] for r in rows) and strict
    return dict(ok=ok, gain_driver_vs_parity_runner=rows, strict_arguments=strict)


def check_defines(layer, text):
    got = {t for t in text.split() if t.startswith('-D')}
    if got != DEFINES_REQUIRED[layer]:
        raise InfraError('%s build defines %s != required %s' % (
            layer, sorted(got), sorted(DEFINES_REQUIRED[layer])))
    return sorted(got)


def run_all(args):
    scenarios = enumerate_scenarios()
    registry = load_registry(args.expected_red, scenarios)
    sel = [s for s in scenarios
           if (not args.only or re.search(args.only, s['id']))
           and not (args.no_e2e and s['kind'] == 'e2e')]
    if args.list:
        for s in sel:
            print(s['id'])
        return 0
    define_info = {'L1': check_defines('L1', args.defines_l1), 'L2': check_defines('L2', args.defines_l2)}
    for flag in ('gain_l1', 'gain_l2', 'e2e_l1', 'e2e_l2', 'runner_l1', 'runner_l2'):
        if not (getattr(args, flag) and os.access(getattr(args, flag), os.X_OK)):
            raise InfraError('--%s is not an executable file' % flag.replace('_', '-'))
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)
    bases, shas = load_inputs(args.data)
    pyref = PyRef(work)
    sc = selfcheck(args, bases, work)
    if not sc['ok']:
        raise InfraError('driver self-check failed: %s' % json.dumps(sc, sort_keys=True))

    records = []
    cache_key, cache = None, {}
    for s in sel:
        fam, sr, fft, strength, kind = s['fam'], s['sr'], s['fft'], s['strength'], s['kind']
        rec = dict(id=s['id'], kind=kind, family=fam['name'], sr=sr, fft=fft, strength=strength,
                   input=role_file(sr, fam['role']),
                   exercises=dict(fam['exercises']))
        akey = (kind, _audio_key(fam), sr, fft)
        if cache_key != (sr, fft):
            cache, cache_key = {}, (sr, fft)
        if akey not in cache:
            audio = fam['tf'](bases[sr][fam['role']], sr)
            if kind == 'gain':
                re32, im32, hop = stft32(audio, sr, fft)
                if fam.get('edit'):
                    fam['edit'](re32, im32, sr, fft, hop)
                cache[akey] = (re32, im32)
            else:
                cache[akey] = (np.ascontiguousarray(audio.astype('<f4')),)
        if kind == 'gain':
            re32, im32 = cache[akey]
            makeup = bool(fam.get('makeup'))
            den = pyref.denoiser(sr, fft, strength, makeup=makeup, prior=fam.get('py_prior'))
            g_py = pyref.gains(den, re32, im32)
            path = os.path.join(work, 'case.nrp2')
            write_nrp2(path, re32, im32, g_py, sr)
            g1 = run_gain_driver(args.gain_l1, path, strength, makeup, 'l1')
            g2 = run_gain_driver(args.gain_l2, path, strength, makeup, 'l2')
            os.remove(path)
            zero = (re32 == 0.0) & (im32 == 0.0)
            rec.update(n_frames=int(re32.shape[0]), n_bins=int(re32.shape[1]),
                       spectra_sha16=sha256_bytes(re32.tobytes() + im32.tobytes())[:16])
            rec['L1'] = gain_stats(g_py, g1, zero)
            rec['L2'] = gain_stats(g1, g2, zero)
        else:
            (x32,) = cache[akey]
            den = pyref.denoiser(sr, fft, strength)
            y_py = np.asarray(den.denoise(x32.astype(np.float64)))
            y1 = run_e2e_driver(args.e2e_l1, x32, sr, fft, strength, work, 'l1')
            y2 = run_e2e_driver(args.e2e_l2, x32, sr, fft, strength, work, 'l2')
            rec.update(n_samples=int(len(x32)), input_sha16=sha256_bytes(x32.tobytes())[:16])
            rec['L1'] = e2e_stats(y_py, y1)
            rec['L2'] = e2e_stats(y1, y2)
        for layer in LAYERS:
            finish_layer(rec, kind, layer, rec[layer], registry)
        records.append(rec)
        if args.progress:
            print('  [%d/%d] %s' % (len(records), len(sel), s['id']), file=sys.stderr, flush=True)
    if args.clean_work:
        shutil.rmtree(work, ignore_errors=True)

    failures = [(r['id'], layer, r[layer]['verdict']) for r in records for layer in LAYERS
                if r[layer]['verdict'] in ('RED_UNEXPECTED', 'ERROR') or
                r[layer]['verdict'].startswith('GREEN_UNEXPECTED')]
    counts = {}
    for r in records:
        for layer in LAYERS:
            key = '%s_%s' % (layer, re.sub(r'\(.*\)', '', r[layer]['verdict']))
            counts[key] = counts.get(key, 0) + 1
    marginal = [(r['id'], layer) for r in records for layer in LAYERS if r[layer].get('marginal')]
    doc = dict(
        tool='pyc_parity_nr', format=FORMAT,
        layers=dict(
            L1=dict(desc='std-math C (SIMD=0, -DUSE_STANDARD_MATH, no USE_* optimizations) vs Python',
                    defines=define_info['L1']),
            L2=dict(desc='shipping C (SIMD=1, Makefile default, six USE_* flags) vs std-math C',
                    defines=define_info['L2'])),
        tolerances=dict(FROZEN=True, margin_flag=[MARGIN_LOW, MARGIN_HIGH], values=TOLERANCES),
        inputs=shas,
        registry_sha256=file_sha256(args.expected_red),
        selfcheck=sc,
        scenarios=records,
        summary=dict(n_scenarios=len(records), verdict_counts=counts,
                     marginal=[list(m) for m in marginal],
                     failures=[list(f) for f in failures],
                     result='FAIL' if failures else 'PASS'))
    with open(args.json, 'w') as fh:
        json.dump(doc, fh, sort_keys=True, indent=1)
        fh.write('\n')
    if args.emit_expected_red:
        emit_registry(args.emit_expected_red, records)
    print_report(doc, args.brief)
    return 1 if failures else 0


def emit_registry(path, records):
    """Write the current red set as a registry candidate, labelled by the family's documented
    finding.  Reds of families without a documented finding for that layer are left out (they stay
    RED_UNEXPECTED); the labelling is a starting point to be confirmed by ablation, not evidence.
    Use it on a full run (a --only subset would write a partial registry)."""
    fams = {f['name']: f for f in FAMILIES}
    reg = {}
    for r in records:
        for layer in LAYERS:
            if r[layer]['red'] and r[layer]['verdict'] != 'ERROR':
                tag = fams[r['family']]['exercises'].get(layer)
                if tag:
                    reg.setdefault(tag, {}).setdefault(layer, []).append(r['id'])
    for tag in reg:
        for layer in reg[tag]:
            reg[tag][layer].sort()
    with open(path, 'w') as fh:
        json.dump(dict(format=FORMAT, expected_red=reg), fh, sort_keys=True, indent=1)
        fh.write('\n')


def _fmt(v, spec):
    return '-' if v is None else format(v, spec)


def print_report(doc, brief):
    print('pyc_parity_nr  (tolerances FROZEN 2026-10-20: %s)' % json.dumps(TOLERANCES, sort_keys=True))
    print('L1 = %s' % doc['layers']['L1']['desc'])
    print('L2 = %s' % doc['layers']['L2']['desc'])
    for kind in ('gain', 'e2e'):
        rows = [r for r in doc['scenarios'] if r['kind'] == kind]
        if not rows:
            continue
        print()
        if kind == 'gain':
            print('%-44s | %-9s %-9s %-3s %-22s | %-9s %-9s %-3s %-22s' % (
                'gain scenario', 'L1 max', 'L1 p99.9', 'bit', 'L1 verdict', 'L2 max', 'L2 p99.9', 'bit', 'L2 verdict'))
        else:
            print('%-44s | %-9s %-9s %-3s %-22s | %-9s %-9s %-3s %-22s' % (
                'e2e scenario', 'L1 max', 'L1 rmsdB', 'bit', 'L1 verdict', 'L2 max', 'L2 rmsdB', 'bit', 'L2 verdict'))
        for r in rows:
            if brief and all(r[l]['verdict'] in ('GREEN',) or r[l]['verdict'].startswith('RED_EXPECTED')
                             for l in LAYERS):
                continue
            cells = []
            for layer in LAYERS:
                st = r[layer]
                second = st['p999'] if kind == 'gain' else st['rms_err_db']
                cells.append('%-9s %-9s %-3s %-22s' % (
                    _fmt(st['max_abs'], '.3e'), _fmt(second, '.3e' if kind == 'gain' else '.1f'),
                    'Y' if st['bit_identical'] else 'n',
                    st['verdict'] + ('~' if st.get('marginal') else '')))
            print('%-44s | %s | %s' % (r['id'], cells[0], cells[1]))
    s = doc['summary']
    print()
    print('summary: %d scenarios; %s' % (s['n_scenarios'], json.dumps(s['verdict_counts'], sort_keys=True)))
    if s['marginal']:
        print('marginal (limit ratio between %.1f and %.1f, "~" above): %d' % (
            MARGIN_LOW, MARGIN_HIGH, len(s['marginal'])))
    for f in s['failures']:
        print('FAILURE: %s %s %s' % tuple(f))
    print('RESULT: %s' % s['result'])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', help='test/pyc_parity/data (pinned wavs + SHA256SUMS)')
    ap.add_argument('--expected-red', help='test/pyc_parity/expected_red.json')
    ap.add_argument('--json', required=False, help='machine-readable result')
    ap.add_argument('--work', required=False, help='scratch directory (must be outside the repo)')
    ap.add_argument('--gain-l1'), ap.add_argument('--gain-l2')
    ap.add_argument('--e2e-l1'), ap.add_argument('--e2e-l2')
    ap.add_argument('--runner-l1', help='example/parity_runner of the L1 build (driver self-check)')
    ap.add_argument('--runner-l2', help='example/parity_runner of the L2 build (driver self-check)')
    ap.add_argument('--defines-l1', default='', help='-D flags the L1 build was compiled with')
    ap.add_argument('--defines-l2', default='', help='-D flags the L2 build was compiled with')
    ap.add_argument('--only', help='regex on the scenario id')
    ap.add_argument('--no-e2e', action='store_true')
    ap.add_argument('--list', action='store_true', help='print the selected scenario ids and exit')
    ap.add_argument('--brief', action='store_true', help='table: only rows that are not GREEN/RED_EXPECTED')
    ap.add_argument('--progress', action='store_true')
    ap.add_argument('--clean-work', action='store_true')
    ap.add_argument('--emit-expected-red', help='write the current red set as a registry candidate')
    args = ap.parse_args()
    try:
        for need in ('data', 'expected_red'):
            if not getattr(args, need):
                ap.error('--%s is required' % need.replace('_', '-'))
        if not args.list:
            for need in ('json', 'work', 'gain_l1', 'gain_l2', 'e2e_l1', 'e2e_l2', 'runner_l1', 'runner_l2'):
                if not getattr(args, need):
                    ap.error('--%s is required' % need.replace('_', '-'))
        return run_all(args)
    except InfraError as exc:
        print('pyc_parity_nr: infrastructure error: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
