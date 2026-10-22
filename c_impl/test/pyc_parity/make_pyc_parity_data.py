#!/usr/bin/env python3
"""Provenance for test/pyc_parity/data (run once; the files are then frozen and pinned by SHA256SUMS).

pyc_parity_nr.sh never regenerates the data: it only verifies SHA256SUMS. This script documents
where each file comes from. Every file is a byte-for-byte copy of, or a head-trim (first N seconds,
16-bit mono PCM, standard 44-byte WAV header) of, a file of the fixed NR regression inputs
(harness/data/nr). The source sha256 values below are the pinned digests of those inputs.
The output names carry a "test_" prefix because the repository's .gitignore excludes *.wav except
test_*.wav.

usage: make_pyc_parity_data.py <dir holding the source wavs> [<out dir, default ./data>]
"""
import hashlib
import os
import sys
import wave

# name -> (source sha256, seconds to keep or None for the whole file)
SOURCES = {
    "n8_babble_5dB.wav":       ("258db0cc69ef5191bd29876e6f78d1fcae8fdb5572969b1cf9cd61ee1fd43379", None),
    "n8_synth_gaps.wav":       ("43409a2c01e159d99c17f320c0f7674cc58a6bc45d4ce5e1ad59a46d60a97fc0", None),
    "n16_babble_5dB.wav":      ("c405a58e8c9bac3e31cf43c268b86bb6cdae1fd456f06f43cd4f4898ba8a1874", 14.0),
    "n16_music.wav":           ("3ff5fe3e1cd85d8a64618d63583f0d88779f0827b6f13a42bfe23794b9ea7931", None),
    "n16_scene_white_0dB.wav": ("5510f8b78ee6a56b3a0b1e4bd91fb746137514bc1c5efa1eeb228973f7e81159", None),
    "n16_synth_gaps.wav":      ("008f887f20ffc538120404e3d3213eec9402599b2c5337b88e7e71259cb92a06", None),
    "n16_vctk_p232_003.wav":   ("e49010f4972da88b514749b5172abd9cf4ad41e6be64b123b95ac044c5e61891", None),
    "n48_babble_5dB.wav":      ("4ed38712b95d9b2076607888c35d4a8b8ea5fd786dad2023bc50fb215694d9ef", 8.0),
    "n48_synth_gaps.wav":      ("51d2d526a208bae9ede860513f83515a441b2feeb917a52a746bf5042a6b8321", 14.0),
    "n48_vctk_p232_003.wav":   ("138fcd10a393ee3e5a0090948e3cb630d3f8a8cce1b0263407e5970084034d53", None),
}


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(out, exist_ok=True)
    lines = []
    for name in sorted(SOURCES):
        want, seconds = SOURCES[name]
        path = os.path.join(src, name)
        got = sha256(path)
        if got != want:
            sys.exit("source %s: sha256 %s != pinned %s" % (name, got, want))
        with wave.open(path) as w:
            assert w.getsampwidth() == 2 and w.getnchannels() == 1
            sr, n = w.getframerate(), w.getnframes()
            pcm = w.readframes(n)
        if seconds is not None:
            pcm = pcm[: 2 * int(round(seconds * sr))]
        with wave.open(os.path.join(out, "test_" + name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
        lines.append("%s  %s\n" % (sha256(os.path.join(out, "test_" + name)), "test_" + name))
    with open(os.path.join(out, "SHA256SUMS"), "w") as fh:
        fh.writelines(lines)
    sys.stdout.write("wrote %d files to %s\n" % (len(lines), out))


if __name__ == "__main__":
    main()
