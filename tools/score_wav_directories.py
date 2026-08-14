#!/usr/bin/env python3
"""Score already-enhanced WAV files against clean references.

This tool does not run the NR algorithm.  It compares WAV files in directories
with identical relative paths.  ``--clean-dir`` and ``--enhanced-dir`` are
required; ``--noisy-dir`` is optional and enables input-baseline and
improvement metrics.

PESQ-WB and STOI are evaluated at 16 kHz.  SI-SDR, segmental SNR, and LSD are
evaluated at the WAVs' native sample rate.  The three signals are never shifted
or independently resampled, so an algorithmic delay remains visible in the
scores.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

try:
    from pesq import pesq as pesq_fn
except ImportError:  # pragma: no cover - exercised by dependency preflight
    pesq_fn = None

try:
    from pystoi import stoi as stoi_fn
except ImportError:  # pragma: no cover - exercised by dependency preflight
    stoi_fn = None


PESQ_STOI_SR = 16000
ABSOLUTE_METRICS = ("pesq", "stoi", "si_sdr", "seg_snr", "lsd_db")
HIGHER_IS_BETTER = {
    "pesq": True,
    "stoi": True,
    "si_sdr": True,
    "seg_snr": True,
    "lsd_db": False,
}


def _wav_inventory(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("directory does not exist: {}".format(root))
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".wav":
            continue
        relative = path.relative_to(root).as_posix()
        if relative in files:
            raise ValueError("duplicate WAV relative path: {}".format(relative))
        files[relative] = path
    if not files:
        raise ValueError("no WAV files found under {}".format(root))
    return root, files


def discover_cases(clean_dir, enhanced_dir, noisy_dir=None):
    """Return strict relative-path matches for the requested directories."""
    _, clean = _wav_inventory(clean_dir)
    enhanced_root, enhanced = _wav_inventory(enhanced_dir)
    noisy_root, noisy = (None, None)
    if noisy_dir is not None:
        noisy_root, noisy = _wav_inventory(noisy_dir)

    expected = set(clean)
    for label, root, inventory in (
        ("enhanced", enhanced_root, enhanced),
        ("noisy", noisy_root, noisy),
    ):
        if inventory is None:
            continue
        actual = set(inventory)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ValueError(
                "{} WAV set does not match clean WAV set under {}: "
                "missing={} extra={}\n  first missing={}\n  first extra={}".format(
                    label, root, len(missing), len(extra), missing[:10], extra[:10]
                )
            )

    return [
        {
            "relative_path": relative,
            "clean": clean[relative],
            "enhanced": enhanced[relative],
            "noisy": noisy[relative] if noisy is not None else None,
        }
        for relative in sorted(expected)
    ]


def _read_mono(path):
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if audio.shape[1] != 1:
        raise ValueError("{} has {} channels; mono WAV required".format(path, audio.shape[1]))
    audio = audio[:, 0]
    if audio.size == 0:
        raise ValueError("{} is empty".format(path))
    if not np.all(np.isfinite(audio)):
        raise ValueError("{} contains NaN or Inf".format(path))
    return audio, int(sample_rate)


def load_case(case, length_tolerance_samples=0):
    signals = {}
    sample_rates = {}
    for role in ("clean", "enhanced", "noisy"):
        path = case.get(role)
        if path is None:
            continue
        signals[role], sample_rates[role] = _read_mono(path)

    if len(set(sample_rates.values())) != 1:
        raise ValueError(
            "sample rates differ for {}: {}".format(case["relative_path"], sample_rates)
        )

    lengths = {role: len(signal) for role, signal in signals.items()}
    spread = max(lengths.values()) - min(lengths.values())
    if spread > length_tolerance_samples:
        raise ValueError(
            "lengths differ for {}: {} (tolerance={} samples); no automatic "
            "alignment is performed".format(
                case["relative_path"], lengths, length_tolerance_samples
            )
        )
    if spread:
        n = min(lengths.values())
        signals = {role: signal[:n] for role, signal in signals.items()}

    return signals, next(iter(sample_rates.values()))


def _resample(signal, source_rate, target_rate=PESQ_STOI_SR):
    if source_rate == target_rate:
        return signal
    divisor = math.gcd(source_rate, target_rate)
    return np.asarray(
        resample_poly(signal, target_rate // divisor, source_rate // divisor),
        dtype=np.float32,
    )


def si_sdr(estimate, reference):
    ref = np.asarray(reference, dtype=np.float64)
    est = np.asarray(estimate, dtype=np.float64)
    ref = ref - np.mean(ref)
    est = est - np.mean(est)
    ref_energy = float(np.dot(ref, ref))
    if ref_energy <= 1e-12:
        raise ValueError("clean reference has insufficient non-DC energy for SI-SDR")
    scale = float(np.dot(est, ref)) / ref_energy
    target = scale * ref
    residual = est - target
    return float(
        10.0
        * np.log10(
            (float(np.dot(target, target)) + 1e-12)
            / (float(np.dot(residual, residual)) + 1e-12)
        )
    )


def segmental_snr(estimate, reference, sample_rate, frame_ms=20.0):
    frame = int(round(sample_rate * frame_ms / 1000.0))
    if frame <= 0 or len(reference) < frame:
        raise ValueError("signal is shorter than one 20 ms segSNR frame")
    n_frames = len(reference) // frame
    ref = np.asarray(reference[: n_frames * frame], dtype=np.float64)
    est = np.asarray(estimate[: n_frames * frame], dtype=np.float64)
    error = (est - ref).reshape(n_frames, frame)
    ref = ref.reshape(n_frames, frame)
    numerator = np.sum(ref * ref, axis=1) + 1e-10
    denominator = np.sum(error * error, axis=1) + 1e-10
    values = np.clip(10.0 * np.log10(numerator / denominator), -10.0, 35.0)
    return float(np.mean(values))


def log_spectral_distance(estimate, reference, sample_rate, frame_ms=32.0):
    frame = max(2, int(round(sample_rate * frame_ms / 1000.0)))
    hop = frame // 2
    if len(reference) < frame:
        raise ValueError("signal is shorter than one LSD frame")
    window = np.hanning(frame).astype(np.float64)
    squared_distances = []
    for start in range(0, len(reference) - frame + 1, hop):
        ref_spec = np.abs(np.fft.rfft(reference[start:start + frame] * window))
        est_spec = np.abs(np.fft.rfft(estimate[start:start + frame] * window))
        ref_db = 20.0 * np.log10(np.maximum(ref_spec, 1e-8))
        est_db = 20.0 * np.log10(np.maximum(est_spec, 1e-8))
        squared_distances.append(float(np.mean((est_db - ref_db) ** 2)))
    return float(np.sqrt(np.mean(squared_distances)))


def score_signal(candidate, clean, sample_rate):
    clean_16k = _resample(clean, sample_rate)
    candidate_16k = _resample(candidate, sample_rate)
    n_16k = min(len(clean_16k), len(candidate_16k))
    clean_16k = clean_16k[:n_16k]
    candidate_16k = candidate_16k[:n_16k]

    metrics = {
        "pesq": float(pesq_fn(PESQ_STOI_SR, clean_16k, candidate_16k, "wb")),
        "stoi": float(stoi_fn(clean_16k, candidate_16k, PESQ_STOI_SR, extended=False)),
        "si_sdr": si_sdr(candidate, clean),
        "seg_snr": segmental_snr(candidate, clean, sample_rate),
        "lsd_db": log_spectral_distance(candidate, clean, sample_rate),
    }
    for name, value in metrics.items():
        if not np.isfinite(value):
            raise ValueError("{} returned a non-finite value".format(name))
    return metrics


def score_case(case, length_tolerance_samples=0):
    signals, sample_rate = load_case(case, length_tolerance_samples)
    enhanced = score_signal(signals["enhanced"], signals["clean"], sample_rate)
    record = {
        "relative_path": case["relative_path"],
        "sample_rate": sample_rate,
        "n_samples": len(signals["clean"]),
    }
    record.update({"enhanced_{}".format(k): v for k, v in enhanced.items()})

    if "noisy" in signals:
        noisy = score_signal(signals["noisy"], signals["clean"], sample_rate)
        record.update({"noisy_{}".format(k): v for k, v in noisy.items()})
        for metric in ABSOLUTE_METRICS:
            if metric == "lsd_db":
                improvement = noisy[metric] - enhanced[metric]
            else:
                improvement = enhanced[metric] - noisy[metric]
            record["improvement_{}".format(metric)] = improvement
    return record


def _summary(values, higher_is_better, records, worst_n):
    array = np.asarray(values, dtype=np.float64)
    order = np.argsort(array if higher_is_better else -array)
    worst = [
        {"relative_path": records[int(i)]["relative_path"], "value": float(array[int(i)])}
        for i in order[:worst_n]
    ]
    return {
        "direction": "higher_is_better" if higher_is_better else "lower_is_better",
        "count": int(len(array)),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "p10": float(np.percentile(array, 10)),
        "p90": float(np.percentile(array, 90)),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "worst": worst,
    }


def summarize(records, worst_n):
    fields = [name for name in records[0] if name not in {
        "relative_path", "sample_rate", "n_samples"
    }]
    output = {}
    for field in fields:
        metric = field.split("_", 1)[1]
        higher_is_better = True if field.startswith("improvement_") else HIGHER_IS_BETTER[metric]
        output[field] = _summary(
            [record[field] for record in records], higher_is_better, records, worst_n
        )
    return output


def _atomic_text_write(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(".{}.{}.tmp".format(path.name, os.getpid()))
    try:
        with open(temp, "w", encoding="utf-8", newline="") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp), str(path))
    finally:
        if temp.exists():
            temp.unlink()


def write_outputs(output_dir, run, records, summaries):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {"run": run, "summary": summaries, "records": records}
    _atomic_text_write(
        output_dir / "summary.json",
        lambda stream: json.dump(payload, stream, indent=2, sort_keys=True),
    )

    record_fields = list(records[0])
    _atomic_text_write(
        output_dir / "per_file.csv",
        lambda stream: _write_csv(stream, record_fields, records),
    )

    summary_rows = []
    for metric, stats in summaries.items():
        summary_rows.append({
            "metric": metric,
            "direction": stats["direction"],
            "count": stats["count"],
            "mean": stats["mean"],
            "median": stats["median"],
            "p10": stats["p10"],
            "p90": stats["p90"],
            "min": stats["min"],
            "max": stats["max"],
            "worst": ";".join(
                "{}={:.6g}".format(item["relative_path"], item["value"])
                for item in stats["worst"]
            ),
        })
    summary_fields = [
        "metric", "direction", "count", "mean", "median", "p10", "p90",
        "min", "max", "worst",
    ]
    _atomic_text_write(
        output_dir / "summary.csv",
        lambda stream: _write_csv(stream, summary_fields, summary_rows),
    )


def _write_csv(stream, fieldnames, rows):
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)


def build_arg_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-dir", required=True)
    parser.add_argument("--enhanced-dir", required=True)
    parser.add_argument(
        "--noisy-dir",
        help="Optional noisy-input directory. Enables baseline and improvement metrics.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--length-tolerance-samples",
        type=int,
        default=0,
        help="Permit and trim only this many tail samples (default: 0). Does not align signals.",
    )
    parser.add_argument("--worst-n", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=10)
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.length_tolerance_samples < 0:
        raise SystemExit("FATAL: --length-tolerance-samples must be >= 0")
    if args.worst_n < 1 or args.progress_every < 1:
        raise SystemExit("FATAL: --worst-n and --progress-every must be >= 1")
    if pesq_fn is None or stoi_fn is None:
        missing = []
        if pesq_fn is None:
            missing.append("pesq")
        if stoi_fn is None:
            missing.append("pystoi")
        raise SystemExit(
            "FATAL: missing scoring dependencies: {}. Install with "
            "'python3 -m pip install -r requirements-dev.txt'.".format(", ".join(missing))
        )

    try:
        cases = discover_cases(args.clean_dir, args.enhanced_dir, args.noisy_dir)
    except ValueError as exc:
        raise SystemExit("FATAL: {}".format(exc))

    start = time.time()
    records = []
    for index, case in enumerate(cases, 1):
        try:
            records.append(score_case(case, args.length_tolerance_samples))
        except Exception as exc:
            raise SystemExit(
                "FATAL: scoring {} failed: {}".format(case["relative_path"], exc)
            )
        if index % args.progress_every == 0 or index == len(cases):
            print("[{}/{}] scored".format(index, len(cases)))

    script_path = Path(__file__).resolve()
    run = {
        "tool": script_path.name,
        "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "clean_dir": str(Path(args.clean_dir).resolve()),
        "enhanced_dir": str(Path(args.enhanced_dir).resolve()),
        "noisy_dir": str(Path(args.noisy_dir).resolve()) if args.noisy_dir else None,
        "n_cases": len(records),
        "length_tolerance_samples": args.length_tolerance_samples,
        "pesq_stoi_sample_rate": PESQ_STOI_SR,
        "native_metrics": ["si_sdr", "seg_snr", "lsd_db"],
        "automatic_alignment": False,
        "elapsed_sec": time.time() - start,
    }
    summaries = summarize(records, min(args.worst_n, len(records)))
    write_outputs(args.output_dir, run, records, summaries)

    print("Results written to {}".format(Path(args.output_dir).resolve()))
    for name in (
        "enhanced_pesq",
        "enhanced_stoi",
        "enhanced_si_sdr",
        "enhanced_seg_snr",
        "enhanced_lsd_db",
    ):
        stats = summaries[name]
        print("  {:24s} mean={:.4f} median={:.4f}".format(name, stats["mean"], stats["median"]))
    if args.noisy_dir:
        print("Improvement (positive is better):")
        for name in (
            "improvement_pesq", "improvement_stoi", "improvement_si_sdr",
            "improvement_seg_snr", "improvement_lsd_db",
        ):
            stats = summaries[name]
            print("  {:24s} mean={:+.4f} median={:+.4f}".format(name, stats["mean"], stats["median"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
