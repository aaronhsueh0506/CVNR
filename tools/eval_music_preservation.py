#!/usr/bin/env python3
"""
eval_music_preservation.py — instrument for the music-preservation / stationary-mode arc.

Measures, on COMPONENT-SEPARABLE mixtures, whether the NR denoiser preserves music while still
attenuating stationary noise — plus a speech-in-noise guard so speech quality is never silently
regressed. Bootstraps pseudo-music + synthetic noise so it runs with NO external dataset; drop
real clips into --music-dir / --speech-dir for perceptual-grade validation.

Method (gain-based stem decomposition — the honest way to separate retention from attenuation):
  1. mix = music + noise, noise scaled to a target music-to-noise ratio (MNR).
  2. run the denoiser on the mix -> per-frame gain G(t,f).
  3. apply the SAME G to the music STFT and the noise STFT (framed identically).
  4. music retention (dB)   = 10*log10( sum((G*|M|)^2) / sum(|M|^2) )   (~0 = preserved)
     noise attenuation (dB) = 10*log10( sum((G*|N|)^2) / sum(|N|^2) )   (very negative = removed)
  The GOAL of a music-friendly stationary suppressor: retention near 0 with attenuation strongly
  negative. A general suppressor sacrifices retention.

Speech guard: separate clean-speech + noise cases -> PESQ / STOI / segSNR (enhanced vs clean).
PESQ/STOI are speech models and are reported ONLY on speech cases, never on music.

Usage:
  python tools/eval_music_preservation.py                       # bootstrap, V3-2
  python tools/eval_music_preservation.py --versions V3-2 V3-2  # compare configs (later)
  python tools/eval_music_preservation.py --music-dir path/ --speech-dir path/
"""

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.audio_io import read_audio, write_audio, add_noise   # noqa: E402
from utils.test_data_generator import TestDataGenerator, generate_sample_speech  # noqa: E402
from utils import metrics as M                                # noqa: E402
from process_audio import create_denoiser_from_config         # noqa: E402

try:
    from utils.visualization import (
        plot_gain_spectrogram, plot_spp_spectrogram, plot_noise_psd_tracking,
    )
    _VIZ = True
except Exception:  # matplotlib missing etc.
    _VIZ = False

SR = 16000


# --------------------------------------------------------------------------- #
# Signal builders (bootstrap so the harness runs with no dataset)
# --------------------------------------------------------------------------- #
def generate_pseudo_music(duration, sample_rate=SR, seed=0):
    """Bootstrap 'music': a SUSTAINED chord (held tonal — the hard case that gets absorbed
    into the noise floor) + a vibrato lead + light percussion (broadband transients that
    exercise the scene-change detector). Not perceptually real; for mechanism inspection."""
    rng = np.random.RandomState(seed)
    n = int(duration * sample_rate)
    t = np.arange(n) / sample_rate
    x = np.zeros(n)
    # sustained major triad (root / major third / fifth), each with a few harmonics
    root = 220.0  # A3
    for f0 in (root, root * 5.0 / 4.0, root * 3.0 / 2.0):
        for h in range(1, 5):
            x += (1.0 / h) * np.sin(2 * np.pi * f0 * h * t + rng.uniform(0, 2 * np.pi))
    # vibrato lead an octave up
    lead = 2.0 * root
    inst_f = lead * (1 + 0.02 * np.sin(2 * np.pi * 5.0 * t))
    x += 0.8 * np.sin(2 * np.pi * np.cumsum(inst_f) / sample_rate)
    # light percussion: short broadband bursts every ~0.5 s
    step = int(0.5 * sample_rate)
    burst_len = int(0.03 * sample_rate)
    env = np.exp(-np.arange(burst_len) / (0.01 * sample_rate))
    for start in range(step, n, step):
        L = min(burst_len, n - start)
        if L <= 0:
            break
        x[start:start + L] += 0.6 * rng.randn(L) * env[:L]
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.8
    return x.astype(np.float32)


def generate_tonal_hum(duration, sample_rate=SR, base=60.0):
    """Mains-hum-like STATIONARY noise: narrowband tones at base + harmonics + faint broadband.
    Deliberately tonal — the case that is hardest to separate from sustained music."""
    n = int(duration * sample_rate)
    t = np.arange(n) / sample_rate
    x = np.zeros(n)
    for h in range(1, 6):
        x += (1.0 / h) * np.sin(2 * np.pi * base * h * t)
    x += 0.05 * np.random.RandomState(1).randn(n)
    x = x / (np.max(np.abs(x)) + 1e-9)
    return x.astype(np.float32)


def build_noise(noise_type, duration, gen):
    if noise_type == 'white':
        return gen.generate_white_noise(duration)
    if noise_type == 'pink':
        return gen.generate_pink_noise(duration)
    if noise_type == 'hum':
        return generate_tonal_hum(duration)
    raise ValueError(f"unknown noise type: {noise_type}")


# --------------------------------------------------------------------------- #
# Gain-based measurement
# --------------------------------------------------------------------------- #
def gain_energy_ratio_db(denoiser, gain, stem, frame_slice=None):
    """Apply the mix-derived per-frame gain to a stem's magnitude and return
    10*log10(output_energy / input_energy). `frame_slice=(s0,s1)` restricts to a frame range
    (e.g. music-portion for retention, noise-only lead-in for attenuation)."""
    mags, _phases, _spectra = denoiser.processor.process_signal(stem)
    nf = min(gain.shape[0], mags.shape[0])
    g = gain[:nf]
    m = mags[:nf]
    if frame_slice is not None:
        s0, s1 = frame_slice
        g = g[s0:s1]
        m = m[s0:s1]
    in_e = float(np.sum(m ** 2))
    out_e = float(np.sum((g * m) ** 2))
    return 10.0 * np.log10((out_e + 1e-20) / (in_e + 1e-20))


def mix_music_with_leadin(music, noise, ratio_db, leadin_s, sr):
    """Prepend a NOISE-ONLY lead-in so the denoiser learns the true stationary floor from noise
    (as in real use), then music enters over that floor. Returns (mix, music_stem_padded,
    noise_stem, n_lead_samples). Noise scaled so music/noise = ratio_db over the music portion.
    This makes music-retention (measured on the music portion) and noise-only-attenuation
    (measured on the pure-noise lead-in) genuinely separable — a fair test, unlike music-from-t0
    which the noise-init would absorb."""
    n_lead = int(leadin_s * sr)
    music_pad = np.concatenate([np.zeros(n_lead, dtype=np.float32), music]).astype(np.float32)
    total = len(music_pad)
    if len(noise) < total:
        noise = np.tile(noise, int(np.ceil(total / len(noise))))
    noise = noise[:total]
    m_pow = np.mean(music ** 2)
    n_pow = np.mean(noise[n_lead:] ** 2) + 1e-20
    noise_scaled = (np.sqrt(m_pow / (10 ** (ratio_db / 10)) / n_pow) * noise).astype(np.float32)
    mix = (music_pad + noise_scaled).astype(np.float32)
    return mix, music_pad, noise_scaled, n_lead


# --------------------------------------------------------------------------- #
# Case runners
# --------------------------------------------------------------------------- #
def run_music_case(denoiser, version, music_name, music, noise_name, noise, mnr_db,
                   leadin_s, out_dir, do_viz):
    mix, music_stem, noise_stem, n_lead = mix_music_with_leadin(music, noise, mnr_db, leadin_s, SR)
    enhanced, spp, gain, npsd = denoiser.denoise(
        mix, return_spp=True, return_gain=True, return_noise_psd=True,
    )
    hop = denoiser.processor.frame_shift
    init = getattr(denoiser.noise_estimator, 'num_init_frames', 20)
    lead_frames = n_lead // hop
    nfr = gain.shape[0]
    # music retention over the music portion; noise attenuation over the CONVERGED noise-only
    # lead-in (skip the num_init passthrough frames).
    retention = gain_energy_ratio_db(denoiser, gain, music_stem, frame_slice=(lead_frames, nfr))
    attenuation = gain_energy_ratio_db(denoiser, gain, noise_stem,
                                       frame_slice=(min(init, lead_frames), lead_frames))

    tag = f"{version}_{music_name}_{noise_name}_mnr{mnr_db:+.0f}"
    write_audio(os.path.join(out_dir, f"{tag}_mix.wav"), mix, SR)
    write_audio(os.path.join(out_dir, f"{tag}_enh.wav"), enhanced, SR)

    if do_viz and _VIZ:
        try:
            plot_gain_spectrogram(gain, os.path.join(out_dir, f"{tag}_gain.png"),
                                  SR, hop, f"{tag} gain")
            plot_spp_spectrogram(spp, os.path.join(out_dir, f"{tag}_spp.png"),
                                 SR, hop, f"{tag} SPP")
            mix_mag, _, _ = denoiser.processor.process_signal(mix)
            plot_noise_psd_tracking(npsd, os.path.join(out_dir, f"{tag}_noisepsd.png"),
                                    SR, hop, f"{tag} noise-PSD tracking",
                                    input_psd_matrix=mix_mag[:npsd.shape[0]] ** 2)
        except Exception as e:
            print(f"  (viz skipped for {tag}: {e})")

    return {
        'case': tag, 'kind': 'music', 'version': version,
        'music': music_name, 'noise': noise_name, 'mnr_db': mnr_db,
        'music_retention_db': round(retention, 3),
        'noise_attenuation_db': round(attenuation, 3),
    }


def run_speech_case(denoiser, version, speech, noise_name, noise, snr_db):
    mix = add_noise(speech, noise, snr_db)
    enhanced = denoiser.denoise(mix)
    n = min(len(enhanced), len(speech))
    clean, enh = speech[:n], enhanced[:n]
    pesq = M.calculate_pesq(clean, enh, fs=SR)
    stoi = M.calculate_stoi(clean, enh, fs=SR)
    segsnr = M.calculate_segmental_snr(clean, enh)
    return {
        'case': f"{version}_speech_{noise_name}_snr{snr_db:+.0f}", 'kind': 'speech',
        'version': version, 'noise': noise_name, 'snr_db': snr_db,
        'pesq': None if pesq is None else round(float(pesq), 3),
        'stoi': None if stoi is None else round(float(stoi), 3),
        'segsnr_db': round(float(segsnr), 3),
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def build_denoiser(version, config_dir):
    """Map a harness version name to a denoiser (all share the V3-2 base config so comparisons
    isolate one lever):
      V3-2        : current shipped baseline (mode=full).
      STATIONARY  : mode=stationary (Wiener lower-bound — the music-preserving mode).
    """
    v = version.upper()
    if v in ('STATIONARY', 'V3-2S', 'STAT'):
        return create_denoiser_from_config('V3-2', config_dir, SR, mode='stationary')
    return create_denoiser_from_config(version, config_dir, SR)


def load_clips(directory, duration, fallback_name, fallback_signal):
    if directory and os.path.isdir(directory):
        clips = []
        for p in sorted(glob.glob(os.path.join(directory, '*.wav'))):
            a, _sr = read_audio(p, target_sr=SR)
            clips.append((os.path.splitext(os.path.basename(p))[0], a.astype(np.float32)))
        if clips:
            return clips
    return [(fallback_name, fallback_signal)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--versions', nargs='+', default=['V3-2'],
                    help='denoiser config versions to compare (default: V3-2)')
    ap.add_argument('--config-dir', default=None, help='config dir (default: NR/config)')
    ap.add_argument('--music-dir', default=None, help='dir of real music .wav (else pseudo-music)')
    ap.add_argument('--speech-dir', default=None, help='dir of clean speech .wav (else synthetic)')
    ap.add_argument('--noise-types', nargs='+', default=['white', 'pink', 'hum'],
                    choices=['white', 'pink', 'hum'])
    ap.add_argument('--mnr-db', type=float, default=5.0, help='music-to-noise ratio (dB)')
    ap.add_argument('--noise-leadin-s', type=float, default=1.5,
                    help='noise-only lead-in before music so the floor is learned from noise (s)')
    ap.add_argument('--snr-db', type=float, default=5.0, help='speech-to-noise ratio (dB)')
    ap.add_argument('--duration', type=float, default=4.0, help='bootstrap clip length (s)')
    ap.add_argument('--output-dir', default='./results/music_eval')
    ap.add_argument('--no-viz', action='store_true')
    args = ap.parse_args()

    if args.config_dir is None:
        args.config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       'config')
    os.makedirs(args.output_dir, exist_ok=True)
    gen = TestDataGenerator(sample_rate=SR)

    music_clips = load_clips(args.music_dir, args.duration, 'pseudomusic',
                             generate_pseudo_music(args.duration))
    speech_clips = load_clips(args.speech_dir, args.duration, 'synthspeech',
                              generate_sample_speech(args.duration, SR))

    # Generate each noise ONCE (covering lead-in + longest clip). Reused across every version so
    # the A/B sees identical noise — and pink-noise generation isn't repeated per version.
    max_len = max(len(c[1]) for c in music_clips + speech_clips)
    noise_dur = max_len / SR + args.noise_leadin_s + 1.0
    noises = {nt: build_noise(nt, noise_dur, gen) for nt in args.noise_types}

    results = []
    for version in args.versions:
        denoiser = build_denoiser(version, args.config_dir)
        print(f"\n=== {version} ===")
        # music-preservation cases
        for m_name, music in music_clips:
            for nt in args.noise_types:
                r = run_music_case(denoiser, version, m_name, music, nt, noises[nt],
                                   args.mnr_db, args.noise_leadin_s, args.output_dir,
                                   not args.no_viz)
                results.append(r)
                print(f"  [music] {m_name:12s} + {nt:5s}: "
                      f"retention {r['music_retention_db']:+6.2f} dB | "
                      f"noise atten {r['noise_attenuation_db']:+6.2f} dB")
        # speech-guard cases
        for s_name, speech in speech_clips:
            for nt in args.noise_types:
                r = run_speech_case(denoiser, version, speech, nt, noises[nt], args.snr_db)
                results.append(r)
                print(f"  [speech] {s_name:12s} + {nt:5s}: "
                      f"PESQ {r['pesq']} | STOI {r['stoi']} | segSNR {r['segsnr_db']:+.2f} dB")

    out_json = os.path.join(args.output_dir, 'music_eval_results.json')
    with open(out_json, 'w') as f:
        json.dump({'args': vars(args), 'results': results}, f, indent=2)
    print(f"\nSaved: {out_json}")
    print(f"Plots/wavs in: {os.path.abspath(args.output_dir)}")

    # concise summary: mean retention vs attenuation per version (music cases)
    print("\n--- summary (music cases, mean over noise types) ---")
    for version in args.versions:
        mus = [r for r in results if r['kind'] == 'music' and r['version'] == version]
        if mus:
            ret = np.mean([r['music_retention_db'] for r in mus])
            att = np.mean([r['noise_attenuation_db'] for r in mus])
            print(f"  {version}: music retention {ret:+.2f} dB | noise attenuation {att:+.2f} dB "
                  f"(want retention→0, attenuation≪0)")


if __name__ == '__main__':
    main()
