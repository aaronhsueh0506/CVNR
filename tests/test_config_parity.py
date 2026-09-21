"""Python<->C effective-config parity test (2026-08-03).

Certifies that Python's canonical NR config composition --
``process_audio.build_v3_2_base_params()`` -> ``core.nr_strength.apply_strength()``
-> the ``MmseLsaDenoiser`` constructor -- resolves to the SAME effective,
already-retimed config as the C library's ``mmse_lsa_config_for_mode_grid()``,
across every (grid, strength) combination this project ships. Compares actual
resolved numeric fields, not just "both sides produce finite output" --
that weaker check would have missed the exact class of bug this project just
spent a round fixing (Audio_ALG's C pipelines silently overriding the
canonical alpha_d/alpha_attack back to a stale, worse-measured legacy
tuning -- see NR/CHANGELOG.md and audio_pipeline.c's matching comment).

The C side is `c_impl/test/test_config_parity.c`, built and run via
`make -C c_impl test-config-parity`, which prints one CSV row per
(sample_rate, fft_size, strength) for mmse_lsa_config_for_mode_grid()'s
resolved MmseLsaConfig.
"""
import csv
import io
import math
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import process_audio
from core.nr_strength import apply_strength
from denoisers.v3_2_mmse_lsa import MmseLsaDenoiser

CONFIG_FILE = os.path.join(_ROOT, "config", "v3_2_config.yaml")

# Grid-independent (not retimed) fields: MmseLsaDenoiser stores these
# converted to a linear domain, so the comparison converts the C dB field to
# the same linear domain rather than trying to invert the float32 log/exp
# round trip back to dB.
_DB_TO_LINEAR_FIELDS = {
    "delta_db": "delta",
    "scene_change_threshold_db": "scene_change_threshold",
}

# Tolerance: C computes in float32, Python in float64: 1e-4 relative +
# 1e-5 absolute comfortably clears that gap while still catching a genuine
# provenance/composition mismatch (which is off by 10-40%, not ULPs -- see
# alpha_d 0.75 vs 0.96 and alpha_attack 0.55 vs 0.38 in this round's A/B).
def _close(a, b):
    return math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-5)


def _dump_c_config():
    c_impl_dir = os.path.join(_ROOT, "c_impl")
    # Pin DEBUG=0 explicitly rather than inheriting the caller's shell
    # environment -- the Makefile hard-rejects any DEBUG value other than
    # "0"/"1" (including a stray exported DEBUG from an unrelated tool), and
    # this test has no reason to depend on ambient environment cleanliness.
    env = dict(os.environ, DEBUG="0")
    result = subprocess.run(
        ["make", "test-config-parity"],
        cwd=c_impl_dir, capture_output=True, text=True, timeout=120, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`make test-config-parity` failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    lines = result.stdout.splitlines()
    header_idx = next(
        i for i, line in enumerate(lines) if line.startswith("sample_rate,")
    )
    csv_text = "\n".join(lines[header_idx:])
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows:
        raise RuntimeError(
            f"no CSV rows parsed from test-config-parity output:\n{result.stdout}"
        )
    return rows


def _python_effective_config(sample_rate, fft_size, strength):
    config = process_audio.load_config(CONFIG_FILE)
    frame_size, frame_shift, resolved_fft = process_audio.resolve_signal_grid(
        sample_rate, fft_size)
    params = process_audio.build_v3_2_base_params(
        config, sample_rate, frame_size, frame_shift, resolved_fft)
    params = apply_strength(params, strength)
    params["strength"] = strength
    denoiser = MmseLsaDenoiser(**params)
    p = denoiser.get_params()
    ne = denoiser.noise_estimator
    return {
        "hop_size": frame_shift,
        "alpha_xi": p["alpha_xi"],
        "q": p["q"],
        "xi_min_db": p["xi_min_db"],
        "g_min_db": p["g_min_db"],
        "alpha_g": p["alpha_g"],
        "alpha_attack": p["alpha_attack"],
        "alpha_decay": p["alpha_decay"],
        "num_init_frames": p["num_init_frames"],
        "alpha_s": p["alpha_s"],
        "alpha_d": p["alpha_d"],
        "alpha_p": p["alpha_p"],
        "L": p["L"],
        "broadband_threshold": ne.broadband_threshold,
        "delta": ne.delta,
        "scene_change_threshold": ne.scene_change_threshold,
        "scene_change_min_frames": ne.scene_change_min_frames,
        "scene_change_blend": ne.scene_change_blend,
        "scene_change_flatness_threshold": ne.scene_change_flatness_threshold,
    }


@pytest.fixture(scope="module")
def c_rows():
    return _dump_c_config()


def test_c_dump_covers_three_grids_and_four_strengths(c_rows):
    grids = {(int(r["sample_rate"]), int(r["fft_size"])) for r in c_rows}
    strengths = {r["strength"] for r in c_rows}
    assert grids == {(16000, 256), (16000, 512), (48000, 1024)}
    assert strengths == {"mild", "moderate", "balanced", "aggressive"}


@pytest.mark.parametrize("sample_rate,fft_size", [
    (16000, 256), (16000, 512), (48000, 1024),
])
@pytest.mark.parametrize("strength", ["mild", "moderate", "balanced", "aggressive"])
def test_python_c_effective_config_matches(c_rows, sample_rate, fft_size, strength):
    c_row = next(
        r for r in c_rows
        if int(r["sample_rate"]) == sample_rate
        and int(r["fft_size"]) == fft_size
        and r["strength"] == strength
    )
    py = _python_effective_config(sample_rate, fft_size, strength)

    assert int(c_row["hop_size"]) == py["hop_size"], "hop_size"
    for field in (
        "alpha_xi", "q", "xi_min_db", "g_min_db", "alpha_g", "alpha_attack",
        "alpha_decay", "alpha_s", "alpha_d", "alpha_p",
        "broadband_threshold", "scene_change_blend",
        "scene_change_flatness_threshold",
    ):
        c_val = float(c_row[field])
        py_val = py[field]
        assert _close(c_val, py_val), (
            f"{field} mismatch at {sample_rate}Hz/fft={fft_size}/{strength}: "
            f"C={c_val!r} Python={py_val!r}"
        )

    for field in ("num_init_frames", "L", "scene_change_min_frames"):
        c_val = int(c_row[field])
        py_val = py[field]
        assert c_val == py_val, (
            f"{field} mismatch at {sample_rate}Hz/fft={fft_size}/{strength}: "
            f"C={c_val!r} Python={py_val!r}"
        )

    for db_field, linear_attr in _DB_TO_LINEAR_FIELDS.items():
        c_linear = 10 ** (float(c_row[db_field]) / 10)
        py_linear = py[linear_attr]
        assert _close(c_linear, py_linear), (
            f"{db_field} mismatch at {sample_rate}Hz/fft={fft_size}/{strength}: "
            f"C={c_row[db_field]!r} ({c_linear!r} linear) "
            f"Python={py_linear!r} linear"
        )
