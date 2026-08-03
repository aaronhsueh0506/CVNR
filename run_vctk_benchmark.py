#!/usr/bin/env python3
"""VCTK+DEMAND regression benchmark runner (V3-2 MMSE-LSA).

Replaces the dead regenerate_all_vctk.py / compute_improvement_vctk.py pair:
both imported deleted modules (regenerate_all / compute_improvement) and both
hardcoded a "noisy"/"clean" subdirectory layout that does not match the
actual downloaded dataset at test_wav/vctk_demand/ (which uses
noisy_testset_wav/ and clean_testset_wav/). Neither exposed --mode/--strength.

This is ONE self-contained, checked-in tool: for every (clean, noisy) pair in
the dataset it resamples both to the target sample rate, runs the V3-2
denoiser via create_denoiser_from_config() with an explicit mode/strength/
fft_size, scores PESQ (wideband, 16 kHz)/STOI/SI-SDR/segSNR against the clean
reference, and writes one JSON record per file plus run-identifying metadata
(including the repo's git commit / dirty state) to --output. Compare two such
JSON files with compare_vctk_benchmark.py.

Config-directory resolution note: process_audio.create_denoiser_from_config()
resolves its config directory relative to the caller-supplied string with a
plain os.path.join + os.path.exists check, and process_audio.load_config()
silently returns {} (all-defaults) with only a printed warning if the file is
missing -- i.e. a caller with the wrong CWD gets a silently-wrong denoiser,
not a loud error. This script never hands it a bare relative path: --config-dir
defaults to <nr-root>/config (nr-root defaults to this script's own directory,
not CWD), and the resolved config file's existence is checked up front with a
hard SystemExit if it is missing, before any case is processed.

Usage:
    python3 run_vctk_benchmark.py --mode full --strength balanced \\
        --output results/vctk_full_balanced.json

    python3 run_vctk_benchmark.py --mode stationary --strength balanced \\
        --sample-rate 16000 --fft-size 512 \\
        --output results/vctk_stationary_balanced_fft512.json

    python3 run_vctk_benchmark.py --mode full --strength aggressive \\
        --cases results/vctk_clean_50.txt --output /tmp/smoke.json --limit 10

Then:
    python3 compare_vctk_benchmark.py baseline.json candidate.json
"""
import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import librosa

try:
    from pesq import pesq as pesq_fn
except ImportError:
    pesq_fn = None

try:
    from pystoi import stoi as stoi_fn
except ImportError:
    stoi_fn = None

SCRIPT_DIR = Path(__file__).resolve().parent

DENOISER_VERSION = "V3-2"
PESQ_SR = 16000  # pesq only supports 8000 (nb) / 16000 (wb); spec wants wb.
VALID_MODES = ("full", "stationary")
VALID_STRENGTHS = ("mild", "moderate", "balanced", "aggressive")
DEFAULT_CLEAN_SUBDIR = "clean_testset_wav"
DEFAULT_NOISY_SUBDIR = "noisy_testset_wav"

# Regression gates live in compare_vctk_benchmark.py's GATES dict (the only
# place that actually enforces them) -- not duplicated here to avoid the two
# copies drifting apart.


# --------------------------------------------------------------------------
# Repo wiring: resolve config dir + import create_denoiser_from_config from
# an explicit nr_root, never from ambient CWD / sys.path state.
# --------------------------------------------------------------------------

def resolve_config_dir(nr_root: Path, config_dir_arg: str, version: str):
    config_dir = Path(config_dir_arg).resolve() if config_dir_arg else (nr_root / "config")
    config_filename = version.lower().replace("-", "_") + "_config.yaml"
    config_file = config_dir / config_filename
    if not config_file.is_file():
        raise SystemExit(
            f"FATAL: resolved config file does not exist: {config_file}\n"
            f"  nr_root     = {nr_root}\n"
            f"  config_dir  = {config_dir}\n"
            f"  config_arg  = {config_dir_arg!r}\n"
            "process_audio.create_denoiser_from_config() would silently fall back\n"
            "to hardcoded defaults here (load_config() only prints a warning and\n"
            "returns {}) -- refusing to run rather than produce silently-wrong\n"
            "numbers. Pass --config-dir explicitly if the config lives elsewhere,\n"
            "or --nr-root if you meant to point at a different checkout."
        )
    return config_dir, config_file


# --------------------------------------------------------------------------
# Content-hash provenance: SHA256 of actual file BYTES (never a path or
# mtime), so a candidate run made with a modified runner script / config /
# case manifest is distinguishable from one made with byte-identical inputs,
# even when the *path* string is unchanged (e.g. a bug fix landed in-place).
# --------------------------------------------------------------------------

def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def import_process_audio_module(nr_root: Path):
    """Import process_audio from nr_root specifically, regardless of what else
    is already on sys.path or cached in sys.modules (guards against a nested
    worktree / scratch dir shadowing the real module, the exact failure mode
    that bit the throwaway scratchpad worker). Returns the module itself (not
    just create_denoiser_from_config) so callers can also reach
    load_config/build_v3_2_base_params/apply_strength/apply_mode/
    resolve_signal_grid/MmseLsaDenoiser -- resolving config+params once per
    run instead of re-loading the YAML from disk on every case."""
    nr_root_str = str(nr_root)
    sys.path = [p for p in sys.path if p not in ("", nr_root_str)]
    sys.path.insert(0, nr_root_str)
    sys.modules.pop("process_audio", None)
    try:
        return importlib.import_module("process_audio")
    except ImportError as exc:
        raise SystemExit(
            f"FATAL: could not import process_audio from nr_root={nr_root}: {exc}\n"
            "Pass --nr-root pointing at a checkout that contains process_audio.py."
        )


# --------------------------------------------------------------------------
# Git identity: commit + dirty-working-tree fingerprint, so two runs against
# an uncommitted working tree are distinguishable from a truly identical commit.
# --------------------------------------------------------------------------

def _git(nr_root: Path, args):
    return subprocess.run(
        ["git", "-C", str(nr_root)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
    ).stdout


def get_git_identity(nr_root: Path) -> dict:
    try:
        commit = _git(nr_root, ["rev-parse", "--short", "HEAD"]).strip()
    except Exception as exc:
        return {"git_commit": None, "git_dirty": None, "git_diff_hash": None,
                "git_error": str(exc)}

    try:
        status = _git(nr_root, ["status", "--porcelain"])
    except Exception:
        status = ""
    dirty = bool(status.strip())

    diff_hash = None
    if dirty:
        h = hashlib.sha256()
        try:
            h.update(_git(nr_root, ["diff", "HEAD"]).encode("utf-8", errors="replace"))
        except Exception:
            pass
        # Untracked entries: hash their *paths*, not their bytes. This repo's
        # untracked entries are large downloaded dataset directories (e.g.
        # test_wav/vctk_demand/), not code -- hashing file content there would
        # be slow and behaviourally meaningless. Path names are still enough
        # to tell apart two dirty states that differ only in what's untracked.
        untracked = sorted(line[3:] for line in status.splitlines() if line.startswith("??"))
        h.update("\n".join(untracked).encode("utf-8"))
        diff_hash = h.hexdigest()[:16]

    return {"git_commit": commit, "git_dirty": dirty, "git_diff_hash": diff_hash}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def si_sdr(estimate: np.ndarray, reference: np.ndarray) -> float:
    """Scale-invariant SDR (Le Roux et al. 2018), dB."""
    ref = reference.astype(np.float64)
    est = estimate.astype(np.float64)
    ref = ref - ref.mean()
    est = est - est.mean()
    n = min(len(ref), len(est))
    ref, est = ref[:n], est[:n]
    alpha = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    proj = alpha * ref
    noise = est - proj
    return float(10.0 * np.log10((np.sum(proj ** 2) + 1e-12) / (np.sum(noise ** 2) + 1e-12)))


def seg_snr(estimate: np.ndarray, reference: np.ndarray, sr: int,
            frame_ms: float = 20.0, floor_db: float = -10.0, ceil_db: float = 35.0) -> float:
    """Hand-rolled segmental SNR: mean of per-frame 10*log10(||ref||^2/||est-ref||^2),
    each frame clipped to [floor_db, ceil_db] before averaging (standard segSNR
    convention -- keeps near-silent / all-noise frames from dominating the mean)."""
    n = min(len(reference), len(estimate))
    ref = reference[:n].astype(np.float64)
    est = estimate[:n].astype(np.float64)
    frame = int(round(sr * frame_ms / 1000.0))
    if frame <= 0 or n < frame:
        return float("nan")
    n_frames = n // frame
    vals = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        s, e = i * frame, (i + 1) * frame
        r = ref[s:e]
        noise = est[s:e] - r
        num = np.sum(r ** 2) + 1e-10
        den = np.sum(noise ** 2) + 1e-10
        vals[i] = np.clip(10.0 * np.log10(num / den), floor_db, ceil_db)
    return float(vals.mean())


# --------------------------------------------------------------------------
# Case discovery
# --------------------------------------------------------------------------

def discover_cases(clean_dir: Path, noisy_dir: Path, cases_file):
    if cases_file:
        stems = []
        with open(cases_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                stems.append(line[:-4] if line.lower().endswith(".wav") else line)
        return stems

    clean_stems = {p.stem for p in clean_dir.glob("*.wav")}
    noisy_stems = {p.stem for p in noisy_dir.glob("*.wav")}
    matched = sorted(clean_stems & noisy_stems)
    only_clean = clean_stems - noisy_stems
    only_noisy = noisy_stems - clean_stems
    if only_clean or only_noisy:
        print(f"WARNING: {len(only_clean)} clean-only files, {len(only_noisy)} "
              f"noisy-only files excluded (no matching pair)", file=sys.stderr)
    return matched


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run the V3-2 NR denoiser over VCTK+DEMAND and score PESQ/STOI/SI-SDR/segSNR.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mode", required=True, choices=VALID_MODES,
                   help="NR content-preservation mode.")
    p.add_argument("--strength", required=True, choices=VALID_STRENGTHS,
                   help="NR depth preset.")
    p.add_argument("--sample-rate", type=int, default=16000,
                   help="Pipeline sample rate the denoiser runs at (default: 16000).")
    p.add_argument("--fft-size", type=int, default=None,
                   help="FFT size override. Default: None (library default grid for --sample-rate).")
    p.add_argument("--cases", default=None,
                   help="Optional path to a text file of case stems/filenames, one per line "
                        "(# comments and blank lines ignored). Default: every matched "
                        "clean/noisy pair found under --dataset-dir.")
    p.add_argument("--output", required=True, help="Output JSON path.")
    p.add_argument("--dataset-dir", default=None,
                   help="Dataset root (default: <nr-root>/test_wav/vctk_demand).")
    p.add_argument("--clean-subdir", default=DEFAULT_CLEAN_SUBDIR)
    p.add_argument("--noisy-subdir", default=DEFAULT_NOISY_SUBDIR)
    p.add_argument("--nr-root", default=str(SCRIPT_DIR),
                   help="NR repo checkout to import process_audio/denoisers from and to "
                        "read git identity from (default: this script's own directory). "
                        "Set this to compare a different worktree/commit.")
    p.add_argument("--config-dir", default=None,
                   help="Override config directory (default: <nr-root>/config).")
    p.add_argument("--limit", type=int, default=None,
                   help="Only process the first N discovered cases (smoke testing).")
    p.add_argument("--progress-every", type=int, default=50)
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    nr_root = Path(args.nr_root).resolve()
    dataset_dir = Path(args.dataset_dir).resolve() if args.dataset_dir else (nr_root / "test_wav" / "vctk_demand")
    clean_dir = dataset_dir / args.clean_subdir
    noisy_dir = dataset_dir / args.noisy_subdir

    if not clean_dir.is_dir():
        raise SystemExit(f"FATAL: clean subdir not found: {clean_dir}")
    if not noisy_dir.is_dir():
        raise SystemExit(f"FATAL: noisy subdir not found: {noisy_dir}")

    config_dir, config_file = resolve_config_dir(nr_root, args.config_dir, DENOISER_VERSION)
    process_audio = import_process_audio_module(nr_root)

    # Resolve config -> params ONCE per run (mirrors process_audio.
    # create_denoiser_from_config()'s V3-2 branch exactly), instead of the
    # previous per-case call that re-opened and re-parsed the YAML from disk
    # on every one of up to 824 cases while mode/strength/grid never change
    # within a run. Each case below still gets its own fresh MmseLsaDenoiser
    # instance (clean streaming state per file), just built directly from
    # this cached params dict instead of via a full config reload.
    _config = process_audio.load_config(str(config_file))
    _frame_size, _frame_shift, _fft_size = process_audio.resolve_signal_grid(
        args.sample_rate, args.fft_size)
    _params = process_audio.build_v3_2_base_params(
        _config, args.sample_rate, _frame_size, _frame_shift, _fft_size)
    _strength = args.strength or _config.get('strength', 'balanced')
    _params = process_audio.apply_strength(_params, _strength)
    _params['strength'] = _strength
    _mode = args.mode or _config.get('mode', 'full')
    _params = process_audio.apply_mode(_params, _mode)
    _params['mode'] = _mode

    script_path = Path(__file__).resolve()
    script_sha256 = sha256_file(script_path)
    config_sha256 = sha256_file(config_file)

    if pesq_fn is None:
        raise SystemExit("FATAL: the 'pesq' package is not importable in this environment.")
    if stoi_fn is None:
        raise SystemExit("FATAL: the 'pystoi' package is not importable in this environment.")

    stems = discover_cases(clean_dir, noisy_dir, args.cases)
    if args.limit is not None:
        stems = stems[: args.limit]
    if not stems:
        raise SystemExit("FATAL: no cases to run (empty case list / no matched pairs found).")

    # Case-manifest provenance: if an explicit --cases file was given, hash
    # its actual bytes (the manifest artifact itself). Otherwise there is no
    # on-disk manifest -- synthesize one from the final (post --limit) stem
    # list actually iterated, so two "discovered" runs are still comparable.
    if args.cases:
        cases_manifest_path = Path(args.cases).resolve()
        cases_manifest_sha256 = sha256_file(cases_manifest_path)
        cases_manifest_source = "file"
    else:
        cases_manifest_path = None
        cases_manifest_sha256 = sha256_bytes("\n".join(stems).encode("utf-8"))
        cases_manifest_source = "discovered"

    git_identity = get_git_identity(nr_root)

    print("=" * 100)
    print("VCTK/DEMAND benchmark (V3-2 MMSE-LSA)")
    print(f"  nr_root      : {nr_root}")
    print(f"  dataset_dir  : {dataset_dir}")
    print(f"  clean_subdir : {args.clean_subdir}")
    print(f"  noisy_subdir : {args.noisy_subdir}")
    print(f"  config_dir   : {config_dir}")
    print(f"  mode         : {args.mode}")
    print(f"  strength     : {args.strength}")
    print(f"  sample_rate  : {args.sample_rate}")
    print(f"  fft_size arg : {args.fft_size} (None = library default)")
    print(f"  cases        : {len(stems)}"
          + (f" (from {args.cases})" if args.cases else " (all matched pairs)"))
    print(f"  script_sha256 : {script_sha256}")
    print(f"  config_sha256 : {config_sha256}  ({config_file})")
    print(f"  manifest_sha256: {cases_manifest_sha256}  ({cases_manifest_source}"
          + (f", {cases_manifest_path}" if cases_manifest_path else "") + ")")
    print(f"  git_commit   : {git_identity.get('git_commit')}"
          + (f"  [DIRTY diff_hash={git_identity.get('git_diff_hash')}]"
             if git_identity.get("git_dirty") else "  [clean]"))
    print("=" * 100)

    records = []
    fft_size_used = _fft_size
    hop_size_used = _frame_shift
    t_start = time.time()
    n_ok = 0
    n_err = 0

    for i, stem in enumerate(stems, 1):
        clean_path = clean_dir / f"{stem}.wav"
        noisy_path = noisy_dir / f"{stem}.wav"
        record = {
            "filename": f"{stem}.wav",
            "mode": args.mode,
            "strength": args.strength,
            "sample_rate": args.sample_rate,
            **git_identity,
        }
        try:
            if not clean_path.is_file():
                raise FileNotFoundError(f"missing clean file: {clean_path}")
            if not noisy_path.is_file():
                raise FileNotFoundError(f"missing noisy file: {noisy_path}")

            clean, sr_c = librosa.load(str(clean_path), sr=None)
            noisy, sr_n = librosa.load(str(noisy_path), sr=None)

            clean_rs = clean if sr_c == args.sample_rate else librosa.resample(
                clean, orig_sr=sr_c, target_sr=args.sample_rate)
            noisy_rs = noisy if sr_n == args.sample_rate else librosa.resample(
                noisy, orig_sr=sr_n, target_sr=args.sample_rate)

            n = min(len(clean_rs), len(noisy_rs))
            clean_rs = clean_rs[:n].astype(np.float32)
            noisy_rs = noisy_rs[:n].astype(np.float32)

            denoiser = process_audio.MmseLsaDenoiser(**_params)

            enhanced = denoiser.denoise(noisy_rs)
            m = min(len(enhanced), len(clean_rs))
            enh = np.asarray(enhanced[:m], dtype=np.float32)
            cln = clean_rs[:m]

            record["fft_size"] = fft_size_used
            record["hop_size"] = hop_size_used
            record["n_samples"] = int(m)
            record["si_sdr"] = si_sdr(enh, cln)
            record["seg_snr"] = seg_snr(enh, cln, args.sample_rate)

            # PESQ is spec'd as wideband @ 16 kHz regardless of pipeline sample_rate.
            if args.sample_rate == PESQ_SR:
                pesq_enh, pesq_cln = enh, cln
            else:
                pesq_enh = librosa.resample(enh, orig_sr=args.sample_rate, target_sr=PESQ_SR)
                pesq_cln = librosa.resample(cln, orig_sr=args.sample_rate, target_sr=PESQ_SR)
            try:
                record["pesq"] = float(pesq_fn(PESQ_SR, pesq_cln, pesq_enh, "wb"))
            except Exception as exc:
                record["pesq"] = None
                record["pesq_error"] = str(exc)

            try:
                record["stoi"] = float(stoi_fn(cln, enh, args.sample_rate, extended=False))
            except Exception as exc:
                record["stoi"] = None
                record["stoi_error"] = str(exc)

            n_ok += 1
        except Exception as exc:
            record["error"] = str(exc)
            n_err += 1

        records.append(record)
        if i % args.progress_every == 0 or i == len(stems):
            elapsed = time.time() - t_start
            print(f"  [{i}/{len(stems)}] ok={n_ok} err={n_err} elapsed={elapsed:.1f}s")

    elapsed = time.time() - t_start

    output = {
        "run": {
            "tool": "run_vctk_benchmark.py",
            "nr_root": str(nr_root),
            "dataset_dir": str(dataset_dir),
            "clean_subdir": args.clean_subdir,
            "noisy_subdir": args.noisy_subdir,
            "mode": args.mode,
            "strength": args.strength,
            "sample_rate": args.sample_rate,
            "fft_size_arg": args.fft_size,
            "fft_size": fft_size_used,
            "hop_size": hop_size_used,
            "n_cases": len(stems),
            "n_ok": n_ok,
            "n_err": n_err,
            "elapsed_sec": elapsed,
            "script_path": str(script_path),
            "script_sha256": script_sha256,
            "config_file": str(config_file),
            "config_sha256": config_sha256,
            "cases_manifest_source": cases_manifest_source,
            "cases_manifest_path": str(cases_manifest_path) if cases_manifest_path else None,
            "cases_manifest_sha256": cases_manifest_sha256,
            **git_identity,
        },
        "records": records,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print("=" * 100)
    print(f"Done: {n_ok} ok, {n_err} errors, {elapsed:.1f}s total -> {out_path}")

    if n_ok:

        def summarize(key):
            vals = np.array([r[key] for r in records if r.get(key) is not None], dtype=float)
            if len(vals) == 0:
                return "n=0"
            return (f"n={len(vals)} mean={vals.mean():.4f} "
                    f"median={np.median(vals):.4f} p10={np.percentile(vals, 10):.4f} "
                    f"p90={np.percentile(vals, 90):.4f}")

        for key in ("pesq", "stoi", "si_sdr", "seg_snr"):
            print(f"  {key:8s}: {summarize(key)}")
    print("=" * 100)


if __name__ == "__main__":
    main()
