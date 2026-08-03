#!/usr/bin/env python3
"""Compare two run_vctk_benchmark.py JSON outputs (baseline vs candidate).

FAIL-CLOSED by default: this tool refuses to produce a PASS/FAIL verdict
unless the comparison is actually apples-to-apples. Specifically, before any
metric is compared it hard-errors (non-zero exit, no verdict printed) if:

  * baseline and candidate were run with different grid settings (mode,
    strength, sample_rate, fft_size, hop_size) -- unless --allow-mismatch is
    passed explicitly, in which case a loud warning banner is printed and the
    comparison proceeds anyway (for deliberate exploratory A/B-across-grids
    use). This is the ONLY thing --allow-mismatch bypasses.
  * baseline and candidate do not have the IDENTICAL set of filenames (not
    just the same count) -- this catches a run that silently dropped cases
    (e.g. a crash partway through) that would otherwise still produce a
    healthy-looking mean delta over whatever subset happened to survive.
    NOT bypassable by --allow-mismatch: this is a data-integrity check, not a
    grid-settings choice.
  * either run has n_err > 0 (any per-case processing error). NOT bypassable.
  * for any metric, the number of cases with a valid (non-null, non-NaN)
    value in BOTH runs is less than the full matched case count -- catches a
    metric that silently came back null/missing for some or all cases
    (including the n=0 case, which used to report a vacuous PASS). NOT
    bypassable.

Only after all of the above hold does it match records by filename and print
mean/median/p10/p90 for each side plus mean/median/p10/p90/worst-N of the
per-file candidate-minus-baseline delta, and a PASS/FAIL against this repo's
established regression gates:

    PESQ mean delta >= -0.005
    STOI mean delta >= -0.002

No file in the matched dataset is excluded from the metric stats themselves
(including known PESQ-brittleness outliers such as p257_065) -- median/p10/
p90 are reported alongside the mean specifically so a single metric-
discontinuity outlier cannot misrepresent the aggregate; if you want to
sanity-check whether one file is doing that, look at the worst-N list.

Usage:
    python3 compare_vctk_benchmark.py baseline.json candidate.json
    python3 compare_vctk_benchmark.py baseline.json candidate.json --worst-n 10
    python3 compare_vctk_benchmark.py baseline.json candidate.json --json-out delta.json
    python3 compare_vctk_benchmark.py baseline.json candidate.json --allow-mismatch
"""
import argparse
import json
import sys

import numpy as np

METRICS = ("pesq", "stoi", "si_sdr", "seg_snr")
GATES = {"pesq": -0.005, "stoi": -0.002}
# Known, accepted exception (2026-08-03, see CHANGELOG.md "Audio_ALG C
# pipeline NR tuning A/B" entry): dropping the legacy alpha_d/alpha_attack
# override in favour of mmse_lsa_config_for_mode_grid()'s canonical (B)
# defaults regresses standalone VCTK+DEMAND STOI by ~-0.026, ~13x past this
# gate. That comparison was deliberately run and the regression accepted
# because this NR component is never used standalone in this project (it is
# always AEC-chained; the AEC-chained 90-case leg favoured B). If a
# baseline/candidate comparison here is re-litigating exactly that A-vs-B
# change, a STOI FAIL is expected and already decided -- it is not a new
# regression. Do NOT loosen this gate to silence it; it must stay strict for
# any other, still-undecided change.
# Grid-settings fields that must match between baseline and candidate unless
# --allow-mismatch is passed. fft_size/hop_size here are the *resolved*
# values the denoiser actually ran at (run['fft_size'] / run['hop_size']),
# not the raw --fft-size CLI arg (which may be None = "library default").
GRID_KEYS = ("mode", "strength", "sample_rate", "fft_size", "hop_size")


def load(path):
    """Load a run_vctk_benchmark.py JSON output.

    Returns (run_meta, all_by_filename) where all_by_filename includes EVERY
    record that has a "filename" key -- including ones with an "error" key --
    so that filename-set / n_err checks see the true shape of the run rather
    than a pre-filtered subset.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("records", data if isinstance(data, list) else [])
    all_by_name = {r["filename"]: r for r in records if "filename" in r}
    return data.get("run", {}), all_by_name


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def _is_valid(value):
    """True for a real, usable metric value: not None, not NaN."""
    if value is None:
        return False
    if isinstance(value, float) and np.isnan(value):
        return False
    return True


def describe_run(tag, run_meta):
    if not run_meta:
        print(f"  {tag}: (no 'run' metadata block in this JSON)")
        return
    print(f"  {tag}: mode={run_meta.get('mode')} strength={run_meta.get('strength')} "
          f"sample_rate={run_meta.get('sample_rate')} fft_size={run_meta.get('fft_size')} "
          f"hop_size={run_meta.get('hop_size')}")
    dirty_note = ""
    if run_meta.get("git_dirty"):
        dirty_note = f"  [DIRTY diff_hash={run_meta.get('git_diff_hash')}]"
    print(f"          git_commit={run_meta.get('git_commit')}{dirty_note}  "
          f"n_cases={run_meta.get('n_cases')} n_ok={run_meta.get('n_ok')} "
          f"n_err={run_meta.get('n_err')}")
    script_sha = run_meta.get("script_sha256")
    config_sha = run_meta.get("config_sha256")
    manifest_sha = run_meta.get("cases_manifest_sha256")
    if script_sha or config_sha or manifest_sha:
        print(f"          script_sha256={_short(script_sha)}  "
              f"config_sha256={_short(config_sha)}  "
              f"manifest_sha256={_short(manifest_sha)}")


def _short(h, n=12):
    return h[:n] + "..." if isinstance(h, str) and len(h) > n else h


# --------------------------------------------------------------------------
# Fail-closed gates. Each raises SystemExit(message) -- printed to stderr by
# the default excepthook and exits non-zero -- rather than returning a
# boolean, so a caller can never accidentally ignore the return value and
# fall through to a verdict anyway.
# --------------------------------------------------------------------------

def check_grid_match(base_run, cand_run, allow_mismatch):
    """Returns the list of (key, baseline_value, candidate_value) mismatches.
    Raises SystemExit if there are any and allow_mismatch is False."""
    mismatches = [
        (key, base_run.get(key), cand_run.get(key))
        for key in GRID_KEYS
        if base_run.get(key) != cand_run.get(key)
    ]
    if mismatches and not allow_mismatch:
        lines = "\n".join(f"    {k}: baseline={bv!r} candidate={cv!r}" for k, bv, cv in mismatches)
        raise SystemExit(
            "FATAL: baseline/candidate grid settings differ -- refusing an "
            f"apples-to-oranges comparison:\n{lines}\n"
            "  Pass --allow-mismatch to compare anyway (only for deliberate "
            "exploratory A/B-across-grids use); the output will loudly flag "
            "that the bypass was used."
        )
    return mismatches


def check_filename_sets(base_all, cand_all):
    """Hard requirement, NOT bypassable by --allow-mismatch: baseline and
    candidate must have attempted the exact same set of cases. A silently
    dropped subset (crash, partial run, wrong --cases file) must never be
    excluded quietly -- it must fail the comparison outright."""
    base_names, cand_names = set(base_all), set(cand_all)
    if base_names != cand_names:
        only_base = sorted(base_names - cand_names)
        only_cand = sorted(cand_names - base_names)
        raise SystemExit(
            "FATAL: baseline and candidate do not have identical filename sets -- "
            f"{len(only_base)} case(s) present only in baseline, {len(only_cand)} "
            "case(s) present only in candidate. This usually means one run "
            "silently dropped cases (crash / partial run / mismatched --cases) "
            "rather than a legitimate difference; refusing to compare a subset.\n"
            f"  baseline-only (first 10): {only_base[:10]}\n"
            f"  candidate-only (first 10): {only_cand[:10]}"
        )


def check_no_errors(base_run, cand_run, base_all, cand_all):
    """Hard requirement, NOT bypassable: n_err must be exactly 0 on both
    sides. Falls back to counting records with an "error" key if the run
    metadata block is missing/old and doesn't carry n_err."""
    base_n_err = base_run.get("n_err")
    if base_n_err is None:
        base_n_err = sum(1 for r in base_all.values() if "error" in r)
    cand_n_err = cand_run.get("n_err")
    if cand_n_err is None:
        cand_n_err = sum(1 for r in cand_all.values() if "error" in r)
    if base_n_err or cand_n_err:
        raise SystemExit(
            "FATAL: per-case processing errors present -- refusing to compare a "
            f"partially-failed run:\n"
            f"    baseline n_err={base_n_err}   candidate n_err={cand_n_err}\n"
            "  Fix the underlying failure and rerun until n_err == 0 on both "
            "sides before comparing."
        )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline", help="Baseline run_vctk_benchmark.py JSON output.")
    ap.add_argument("candidate", help="Candidate run_vctk_benchmark.py JSON output.")
    ap.add_argument("--worst-n", type=int, default=20)
    ap.add_argument("--json-out", default=None, help="Optional path to also dump the delta summary as JSON.")
    ap.add_argument("--allow-mismatch", action="store_true",
                     help="Allow comparing baseline/candidate runs made with different grid "
                          "settings (mode/strength/sample_rate/fft_size/hop_size). Off by "
                          "default -- a settings mismatch is a hard error. Does NOT bypass the "
                          "filename-set, n_err, or metric-completeness checks, which are "
                          "always mandatory regardless of this flag.")
    args = ap.parse_args(argv)

    base_run, base_all = load(args.baseline)
    cand_run, cand_all = load(args.candidate)

    print("=" * 100)
    print("VCTK/DEMAND benchmark comparison")
    describe_run("baseline ", base_run)
    describe_run("candidate", cand_run)
    print("=" * 100)

    mismatches = check_grid_match(base_run, cand_run, args.allow_mismatch)
    if mismatches:
        print("!" * 100)
        print("! WARNING: --allow-mismatch is in effect -- comparing runs with DIFFERENT")
        print("! grid settings. This is NOT a like-for-like regression check.")
        for k, bv, cv in mismatches:
            print(f"!   {k}: baseline={bv!r}  candidate={cv!r}")
        print("!" * 100)

    check_filename_sets(base_all, cand_all)
    check_no_errors(base_run, cand_run, base_all, cand_all)

    common = sorted(set(base_all) & set(cand_all))
    if not common:
        raise SystemExit(
            "FATAL: no common cases between baseline and candidate -- nothing to compare."
        )

    print(f"  matched filenames: {len(common)} (identical sets, verified; n_err=0 both sides)")
    print("=" * 100)

    json_out = {
        "baseline_run": base_run,
        "candidate_run": cand_run,
        "allow_mismatch": bool(args.allow_mismatch),
        "grid_mismatches": [{"key": k, "baseline": bv, "candidate": cv} for k, bv, cv in mismatches],
        "metrics": {},
    }
    overall_pass = True
    expected_n = len(common)

    for metric in METRICS:
        names = [n for n in common
                 if _is_valid(base_all[n].get(metric)) and _is_valid(cand_all[n].get(metric))]

        if len(names) != expected_n:
            missing = sorted(set(common) - set(names))
            raise SystemExit(
                f"FATAL: metric '{metric}' has only {len(names)}/{expected_n} case(s) with a "
                "valid (non-null, non-NaN) value in BOTH baseline and candidate -- refusing to "
                "compare a metric with silently missing/under-counted values (this includes "
                "the n=0 case, which must FAIL, not vacuously PASS).\n"
                f"  missing/null (first 10): {missing[:10]}"
            )

        b = np.array([base_all[n][metric] for n in names], dtype=float)
        c = np.array([cand_all[n][metric] for n in names], dtype=float)
        delta = c - b

        print(f"\n-- {metric} (n={len(delta)}) --")
        print(f"   baseline : mean={b.mean():+.4f} median={np.median(b):+.4f} "
              f"p10={pct(b,10):+.4f} p90={pct(b,90):+.4f}")
        print(f"   candidate: mean={c.mean():+.4f} median={np.median(c):+.4f} "
              f"p10={pct(c,10):+.4f} p90={pct(c,90):+.4f}")
        print(f"   delta    : mean={delta.mean():+.4f} median={np.median(delta):+.4f} "
              f"p10={pct(delta,10):+.4f} p90={pct(delta,90):+.4f}")

        order = np.argsort(delta)  # ascending -> most negative (worst) first
        worst = [(names[i], float(delta[i])) for i in order[: args.worst_n]]
        worst_mean = float(np.mean([d for _, d in worst])) if worst else float("nan")
        print(f"   worst-{args.worst_n} mean delta: {worst_mean:+.4f}")
        for name, dv in worst:
            print(f"      {name}: {dv:+.4f}")

        metric_out = {
            "n": len(delta),
            "baseline": {"mean": float(b.mean()), "median": float(np.median(b)),
                         "p10": pct(b, 10), "p90": pct(b, 90)},
            "candidate": {"mean": float(c.mean()), "median": float(np.median(c)),
                          "p10": pct(c, 10), "p90": pct(c, 90)},
            "delta": {"mean": float(delta.mean()), "median": float(np.median(delta)),
                      "p10": pct(delta, 10), "p90": pct(delta, 90)},
            "worst": [{"filename": n, "delta": d} for n, d in worst],
        }

        if metric in GATES:
            thr = GATES[metric]
            verdict = "PASS" if delta.mean() >= thr else "FAIL"
            if verdict == "FAIL":
                overall_pass = False
            print(f"   GATE ({metric} mean delta >= {thr}): {verdict}")
            metric_out["gate"] = {"threshold": thr, "verdict": verdict}

        json_out["metrics"][metric] = metric_out

    print("\n" + "=" * 100)
    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    if mismatches:
        print("  (compared under --allow-mismatch -- settings differed; see WARNING above)")
    print("=" * 100)
    json_out["overall_verdict"] = "PASS" if overall_pass else "FAIL"

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(json_out, f, indent=2)
        print(f"delta summary written to {args.json_out}")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
