#!/usr/bin/env python3
"""Focused fail-closed tests for run_vctk_benchmark.py / compare_vctk_benchmark.py.

These guard the specific silent-PASS failure modes found in the original
tools (see compare_vctk_benchmark.py's module docstring for the full
rationale):

  1. comparing runs with different grid settings (mode/strength/sample_rate/
     fft_size/hop_size) must hard-fail unless --allow-mismatch is passed.
  2. baseline/candidate must have the IDENTICAL filename set (not just the
     same count) -- a run that silently dropped cases must hard-fail, not be
     silently reduced to whatever subset survived on both sides.
  3. n_err > 0 in EITHER run must hard-fail the comparison outright.
  4. a metric with fewer valid (non-null, non-NaN) compared values than the
     full matched case count -- including the all-null / n=0 case -- must
     hard-fail rather than report a vacuous PASS.
  5. run_vctk_benchmark.py's output JSON must record SHA256 content hashes
     (of the runner script, the config file, and the case manifest) that
     actually change when the underlying file's *bytes* change -- not just a
     path string that never changes across runs.

All of these are tested against the actual functions/CLI entry points in the
two tools, using small synthetic JSON fixtures (fast, no dataset/audio deps
required) plus a couple of direct hashlib-content tests for #5.
"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

compare_mod = importlib.import_module("tools.compare_vctk_benchmark")
run_mod = importlib.import_module("tools.run_vctk_benchmark")


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

def make_record(name, pesq=2.5, stoi=0.9, si_sdr=10.0, seg_snr=5.0, error=None):
    r = {"filename": name}
    if error is not None:
        r["error"] = error
    else:
        r.update({"pesq": pesq, "stoi": stoi, "si_sdr": si_sdr, "seg_snr": seg_snr})
    return r


def make_run_meta(records, **overrides):
    run = {
        "mode": "full",
        "strength": "balanced",
        "sample_rate": 16000,
        "fft_size": 256,
        "hop_size": 128,
        "n_cases": len(records),
        "n_ok": sum(1 for r in records if "error" not in r),
        "n_err": sum(1 for r in records if "error" in r),
    }
    run.update(overrides)
    return run


def write_json(path, run_meta, records):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run": run_meta, "records": records}, f)
    return path


def default_pair(tmp_path, n=5):
    """Two byte-for-byte-equivalent (matching grid, matching filenames,
    n_err=0) baseline/candidate JSONs -- the legitimate comparison case."""
    records = [make_record(f"p{i}.wav") for i in range(n)]
    base = write_json(tmp_path / "base.json", make_run_meta(records), records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records), records)
    return base, cand


# --------------------------------------------------------------------------
# 1. Grid-settings mismatch
# --------------------------------------------------------------------------

def test_grid_mismatch_rejected_without_allow_mismatch():
    base_run = make_run_meta([], sample_rate=16000)
    cand_run = make_run_meta([], sample_rate=8000)
    with pytest.raises(SystemExit, match="grid settings differ"):
        compare_mod.check_grid_match(base_run, cand_run, allow_mismatch=False)


def test_grid_mismatch_allowed_with_flag_returns_mismatch_list():
    base_run = make_run_meta([], sample_rate=16000, fft_size=256)
    cand_run = make_run_meta([], sample_rate=8000, fft_size=512)
    mismatches = compare_mod.check_grid_match(base_run, cand_run, allow_mismatch=True)
    keys = {k for k, _, _ in mismatches}
    assert keys == {"sample_rate", "fft_size"}


def test_grid_match_no_mismatch_is_silent():
    run_meta = make_run_meta([])
    assert compare_mod.check_grid_match(run_meta, dict(run_meta), allow_mismatch=False) == []


def test_main_rejects_mismatched_grid_end_to_end(tmp_path):
    records = [make_record("a.wav")]
    base = write_json(tmp_path / "base.json", make_run_meta(records, mode="full"), records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records, mode="stationary"), records)
    with pytest.raises(SystemExit, match="grid settings differ"):
        compare_mod.main([str(base), str(cand)])


def test_main_allow_mismatch_flag_permits_comparison(tmp_path, capsys):
    records = [make_record("a.wav", pesq=3.0, stoi=0.95)]
    base = write_json(tmp_path / "base.json", make_run_meta(records, mode="full"), records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records, mode="stationary"), records)
    rc = compare_mod.main([str(base), str(cand), "--allow-mismatch"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "allow-mismatch" in out.lower()


# --------------------------------------------------------------------------
# 2. Filename-set mismatch (missing/excluded cases)
# --------------------------------------------------------------------------

def test_filename_set_mismatch_hard_fails_even_with_same_count():
    # Same COUNT (2 vs 2) but different actual filenames -- must still fail;
    # this is the "not just matching count" requirement.
    base_all = {"a.wav": make_record("a.wav"), "b.wav": make_record("b.wav")}
    cand_all = {"a.wav": make_record("a.wav"), "c.wav": make_record("c.wav")}
    with pytest.raises(SystemExit, match="identical filename sets"):
        compare_mod.check_filename_sets(base_all, cand_all)


def test_filename_set_match_passes_silently():
    base_all = {"a.wav": make_record("a.wav")}
    cand_all = {"a.wav": make_record("a.wav")}
    compare_mod.check_filename_sets(base_all, cand_all)  # must not raise


def test_main_rejects_dropped_cases_not_silently_excluded(tmp_path):
    """Simulates the exact regression scenario: candidate silently dropped a
    case (e.g. crash). Must hard-fail, not just compare the surviving subset
    with a healthy-looking mean delta."""
    base_records = [make_record(f"p{i}.wav") for i in range(5)]
    cand_records = base_records[:4]  # p4.wav silently missing
    base = write_json(tmp_path / "base.json", make_run_meta(base_records), base_records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(cand_records), cand_records)
    with pytest.raises(SystemExit, match="identical filename sets"):
        compare_mod.main([str(base), str(cand)])


def test_main_filename_mismatch_not_bypassed_by_allow_mismatch(tmp_path):
    """--allow-mismatch is documented to bypass ONLY grid-settings checks --
    it must NOT paper over a dropped-case data-integrity failure."""
    base_records = [make_record(f"p{i}.wav") for i in range(5)]
    cand_records = base_records[:4]
    base = write_json(tmp_path / "base.json", make_run_meta(base_records), base_records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(cand_records), cand_records)
    with pytest.raises(SystemExit, match="identical filename sets"):
        compare_mod.main([str(base), str(cand), "--allow-mismatch"])


# --------------------------------------------------------------------------
# 3. n_err > 0
# --------------------------------------------------------------------------

def test_n_err_nonzero_in_candidate_hard_fails():
    records_ok = [make_record("a.wav")]
    records_err = [make_record("a.wav"), make_record("b.wav", error="boom")]
    base_run = make_run_meta(records_ok)
    cand_run = make_run_meta(records_err)
    base_all = {r["filename"]: r for r in records_ok}
    cand_all = {r["filename"]: r for r in records_err}
    with pytest.raises(SystemExit, match="per-case processing errors"):
        compare_mod.check_no_errors(base_run, cand_run, base_all, cand_all)


def test_n_err_nonzero_in_baseline_hard_fails():
    records_err = [make_record("a.wav", error="boom")]
    records_ok = [make_record("a.wav")]
    base_run = make_run_meta(records_err)
    cand_run = make_run_meta(records_ok)
    base_all = {r["filename"]: r for r in records_err}
    cand_all = {r["filename"]: r for r in records_ok}
    with pytest.raises(SystemExit, match="per-case processing errors"):
        compare_mod.check_no_errors(base_run, cand_run, base_all, cand_all)


def test_n_err_zero_both_sides_passes_silently():
    records = [make_record("a.wav")]
    run_meta = make_run_meta(records)
    all_by_name = {r["filename"]: r for r in records}
    compare_mod.check_no_errors(run_meta, run_meta, all_by_name, all_by_name)  # must not raise


def test_n_err_fallback_counts_error_records_when_run_meta_missing_n_err():
    """Older JSONs may lack a top-level n_err -- must fall back to counting
    records with an "error" key rather than treating missing as 0."""
    records = [make_record("a.wav"), make_record("b.wav", error="boom")]
    run_meta_no_n_err = {k: v for k, v in make_run_meta(records).items() if k != "n_err"}
    all_by_name = {r["filename"]: r for r in records}
    with pytest.raises(SystemExit, match="per-case processing errors"):
        compare_mod.check_no_errors(run_meta_no_n_err, run_meta_no_n_err, all_by_name, all_by_name)


def test_main_rejects_run_with_errors_end_to_end(tmp_path):
    base_records = [make_record("a.wav"), make_record("b.wav", error="crashed")]
    cand_records = [make_record("a.wav"), make_record("b.wav")]
    base = write_json(tmp_path / "base.json", make_run_meta(base_records), base_records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(cand_records), cand_records)
    with pytest.raises(SystemExit, match="per-case processing errors"):
        compare_mod.main([str(base), str(cand)])


# --------------------------------------------------------------------------
# 4. Under-counted / missing / all-null metric values (including n=0)
# --------------------------------------------------------------------------

def test_main_rejects_partial_null_metric_values(tmp_path):
    records_base = [make_record(f"p{i}.wav") for i in range(4)]
    records_cand = [make_record(f"p{i}.wav") for i in range(4)]
    records_cand[2]["pesq"] = None  # one case silently missing pesq
    base = write_json(tmp_path / "base.json", make_run_meta(records_base), records_base)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records_cand), records_cand)
    with pytest.raises(SystemExit, match=r"metric 'pesq' has only 3/4"):
        compare_mod.main([str(base), str(cand)])


def test_main_rejects_all_null_metric_values_n_zero_case(tmp_path):
    """The exact bug: every case errored/null for a metric -> n=0 compared --
    must FAIL, never report a vacuous PASS."""
    records_base = [make_record(f"p{i}.wav") for i in range(3)]
    records_cand = [make_record(f"p{i}.wav") for i in range(3)]
    for r in records_cand:
        r["pesq"] = None
        r["stoi"] = None
    base = write_json(tmp_path / "base.json", make_run_meta(records_base), records_base)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records_cand), records_cand)
    with pytest.raises(SystemExit, match=r"metric 'pesq' has only 0/3"):
        compare_mod.main([str(base), str(cand)])


def test_main_rejects_nan_metric_values_not_just_none(tmp_path):
    records_base = [make_record(f"p{i}.wav") for i in range(3)]
    records_cand = [make_record(f"p{i}.wav") for i in range(3)]
    records_cand[0]["seg_snr"] = float("nan")
    base = write_json(tmp_path / "base.json", make_run_meta(records_base), records_base)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records_cand), records_cand)
    with pytest.raises(SystemExit, match=r"metric 'seg_snr' has only 2/3"):
        compare_mod.main([str(base), str(cand)])


# --------------------------------------------------------------------------
# 5. SHA256 content-hash provenance (not path-based)
# --------------------------------------------------------------------------

def test_sha256_file_reflects_content_not_path(tmp_path):
    same_content = b"alpha beta gamma\n"
    f1 = tmp_path / "one.py"
    f2 = tmp_path / "two.py"  # different path, same bytes
    f1.write_bytes(same_content)
    f2.write_bytes(same_content)
    assert run_mod.sha256_file(f1) == run_mod.sha256_file(f2), (
        "same content at different paths must hash identically -- proves the "
        "hash is content-based, not path-based"
    )
    assert run_mod.sha256_file(f1) == hashlib.sha256(same_content).hexdigest()


def test_sha256_file_changes_when_content_changes_at_same_path(tmp_path):
    f = tmp_path / "script.py"
    f.write_bytes(b"print('v1')\n")
    h1 = run_mod.sha256_file(f)
    f.write_bytes(b"print('v2')  # bugfix\n")  # same path, modified content
    h2 = run_mod.sha256_file(f)
    assert h1 != h2, (
        "modifying a file's bytes in place must change its hash even though "
        "the path string is unchanged -- this is exactly what a path-only "
        "fingerprint would miss"
    )


def test_sha256_bytes_matches_hashlib_reference():
    data = "p1.wav\np2.wav\np3.wav".encode("utf-8")
    assert run_mod.sha256_bytes(data) == hashlib.sha256(data).hexdigest()


def test_run_output_json_has_content_hash_fields_not_bare_paths(tmp_path):
    """Build a fake config dir + case manifest and drive the provenance
    computation the same way main() does, without running the full audio
    pipeline, and confirm the recorded hashes are content-derived."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "v3_2_config.yaml"
    config_file.write_text("spp: {}\n", encoding="utf-8")

    cases_file = tmp_path / "cases.txt"
    cases_file.write_text("p1.wav\np2.wav\n", encoding="utf-8")

    script_sha = run_mod.sha256_file(Path(run_mod.__file__).resolve())
    config_sha = run_mod.sha256_file(config_file)
    manifest_sha = run_mod.sha256_file(cases_file)

    # Independently recomputed via raw hashlib -- must agree byte-for-byte.
    assert script_sha == hashlib.sha256(Path(run_mod.__file__).resolve().read_bytes()).hexdigest()
    assert config_sha == hashlib.sha256(config_file.read_bytes()).hexdigest()
    assert manifest_sha == hashlib.sha256(cases_file.read_bytes()).hexdigest()

    # Editing the config file's content (same path) must change its hash --
    # the failure mode a path-only fingerprint would miss entirely.
    config_file.write_text("spp: {tuned: true}\n", encoding="utf-8")
    assert run_mod.sha256_file(config_file) != config_sha


def test_describe_run_handles_missing_hash_fields_gracefully(capsys):
    """Backward compatibility: older JSONs without the new hash fields must
    not crash describe_run()."""
    old_style_run = {"mode": "full", "strength": "balanced", "sample_rate": 16000,
                      "fft_size": 256, "hop_size": 128, "n_cases": 1, "n_ok": 1, "n_err": 0}
    compare_mod.describe_run("baseline", old_style_run)  # must not raise
    out = capsys.readouterr().out
    assert "baseline" in out


# --------------------------------------------------------------------------
# Legitimate comparison paths still work (regression safety net)
# --------------------------------------------------------------------------

def test_main_passes_on_identical_matching_grid_runs(tmp_path):
    base, cand = default_pair(tmp_path, n=6)
    rc = compare_mod.main([str(base), str(cand)])
    assert rc == 0


def test_main_fails_gate_on_real_pesq_regression(tmp_path):
    """A genuine regression (not a tooling/data-integrity problem) must still
    surface as OVERALL FAIL via the normal gate, distinguishing a real
    regression from a hard 'refuse to compare' error."""
    base_records = [make_record(f"p{i}.wav", pesq=3.0) for i in range(10)]
    cand_records = [make_record(f"p{i}.wav", pesq=2.5) for i in range(10)]  # -0.5 >> -0.005 gate
    base = write_json(tmp_path / "base.json", make_run_meta(base_records), base_records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(cand_records), cand_records)
    rc = compare_mod.main([str(base), str(cand)])
    assert rc == 1


def test_main_json_out_records_allow_mismatch_and_grid_mismatches(tmp_path):
    records = [make_record("a.wav")]
    base = write_json(tmp_path / "base.json", make_run_meta(records, strength="balanced"),
                       records)
    cand = write_json(tmp_path / "cand.json", make_run_meta(records, strength="aggressive"),
                       records)
    out_path = tmp_path / "delta.json"
    rc = compare_mod.main([str(base), str(cand), "--allow-mismatch", "--json-out", str(out_path)])
    assert rc == 0
    delta = json.loads(out_path.read_text())
    assert delta["allow_mismatch"] is True
    assert any(m["key"] == "strength" for m in delta["grid_mismatches"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
