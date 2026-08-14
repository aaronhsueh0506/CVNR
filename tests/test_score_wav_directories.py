import csv
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

score = importlib.import_module("tools.score_wav_directories")


def write_wav(path, signal, sample_rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(signal, dtype=np.float32), sample_rate, subtype="FLOAT")


def tone(sample_rate=16000, seconds=0.5):
    t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
    return 0.2 * np.sin(2.0 * np.pi * 440.0 * t)


def test_discover_cases_matches_relative_paths_recursively(tmp_path):
    clean = tmp_path / "clean"
    enhanced = tmp_path / "enhanced"
    noisy = tmp_path / "noisy"
    for root in (clean, enhanced, noisy):
        write_wav(root / "speaker" / "a.wav", tone())
        write_wav(root / "b.WAV", tone())
    cases = score.discover_cases(clean, enhanced, noisy)
    assert [case["relative_path"] for case in cases] == ["b.WAV", "speaker/a.wav"]


def test_discover_cases_rejects_missing_or_extra_files(tmp_path):
    clean = tmp_path / "clean"
    enhanced = tmp_path / "enhanced"
    write_wav(clean / "a.wav", tone())
    write_wav(enhanced / "b.wav", tone())
    with pytest.raises(ValueError, match="does not match clean WAV set"):
        score.discover_cases(clean, enhanced)


def test_load_case_rejects_sample_rate_channel_and_length_mismatch(tmp_path):
    clean = tmp_path / "clean.wav"
    enhanced = tmp_path / "enhanced.wav"
    write_wav(clean, tone())
    write_wav(enhanced, tone(48000), 48000)
    case = {"relative_path": "x.wav", "clean": clean, "enhanced": enhanced, "noisy": None}
    with pytest.raises(ValueError, match="sample rates differ"):
        score.load_case(case)

    write_wav(enhanced, np.column_stack((tone(), tone())))
    with pytest.raises(ValueError, match="mono WAV required"):
        score.load_case(case)

    write_wav(enhanced, tone()[:-2])
    with pytest.raises(ValueError, match="lengths differ"):
        score.load_case(case)
    signals, _ = score.load_case(case, length_tolerance_samples=2)
    assert len(signals["clean"]) == len(signals["enhanced"])


def test_identity_native_metrics_have_expected_direction():
    clean = tone()
    changed = clean + 0.01 * np.sin(np.arange(len(clean), dtype=np.float32))
    assert score.si_sdr(clean, clean) > score.si_sdr(changed, clean)
    assert score.segmental_snr(clean, clean, 16000) == pytest.approx(35.0)
    assert score.log_spectral_distance(clean, clean, 16000) == pytest.approx(0.0)
    assert score.log_spectral_distance(changed, clean, 16000) > 0.0


def test_score_signal_resamples_only_perceptual_branch(monkeypatch):
    calls = {}

    def fake_pesq(sample_rate, clean, candidate, mode):
        calls["pesq"] = (sample_rate, len(clean), len(candidate), mode)
        return 3.0

    def fake_stoi(clean, candidate, sample_rate, extended=False):
        calls["stoi"] = (sample_rate, len(clean), len(candidate), extended)
        return 0.9

    monkeypatch.setattr(score, "pesq_fn", fake_pesq)
    monkeypatch.setattr(score, "stoi_fn", fake_stoi)
    clean = tone(48000)
    result = score.score_signal(clean * 0.9, clean, 48000)
    assert calls["pesq"] == (16000, 8000, 8000, "wb")
    assert calls["stoi"] == (16000, 8000, 8000, False)
    assert set(result) == set(score.ABSOLUTE_METRICS)


def test_score_case_noisy_adds_positive_improvements(monkeypatch, tmp_path):
    monkeypatch.setattr(score, "pesq_fn", lambda sr, clean, candidate, mode: float(np.mean(candidate)))
    monkeypatch.setattr(
        score,
        "stoi_fn",
        lambda clean, candidate, sr, extended=False: float(np.mean(candidate)),
    )
    clean_signal = tone() + 0.05
    noisy_signal = clean_signal + 0.05 * np.sin(np.arange(len(clean_signal), dtype=np.float32))
    enhanced_signal = clean_signal + 0.01 * np.sin(np.arange(len(clean_signal), dtype=np.float32))
    paths = {}
    for role, signal in (("clean", clean_signal), ("noisy", noisy_signal), ("enhanced", enhanced_signal)):
        paths[role] = tmp_path / (role + ".wav")
        write_wav(paths[role], signal)
    record = score.score_case({"relative_path": "a.wav", **paths})
    assert record["improvement_si_sdr"] > 0
    assert record["improvement_seg_snr"] > 0
    assert record["improvement_lsd_db"] > 0


def test_main_writes_json_and_csv_without_noisy(monkeypatch, tmp_path):
    monkeypatch.setattr(score, "pesq_fn", lambda *args, **kwargs: 3.0)
    monkeypatch.setattr(score, "stoi_fn", lambda *args, **kwargs: 0.9)
    clean = tmp_path / "clean"
    enhanced = tmp_path / "enhanced"
    output = tmp_path / "scores"
    write_wav(clean / "a.wav", tone())
    write_wav(enhanced / "a.wav", tone() * 0.99)

    assert score.main([
        "--clean-dir", str(clean),
        "--enhanced-dir", str(enhanced),
        "--output-dir", str(output),
    ]) == 0

    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["run"]["n_cases"] == 1
    assert payload["run"]["noisy_dir"] is None
    assert "enhanced_pesq" in payload["summary"]
    assert not any(name.startswith("improvement_") for name in payload["summary"])
    with open(output / "per_file.csv", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["relative_path"] == "a.wav"


def test_main_fails_before_scoring_on_directory_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(score, "pesq_fn", lambda *args, **kwargs: 3.0)
    monkeypatch.setattr(score, "stoi_fn", lambda *args, **kwargs: 0.9)
    clean = tmp_path / "clean"
    enhanced = tmp_path / "enhanced"
    write_wav(clean / "a.wav", tone())
    write_wav(enhanced / "b.wav", tone())
    with pytest.raises(SystemExit, match="does not match clean WAV set"):
        score.main([
            "--clean-dir", str(clean),
            "--enhanced-dir", str(enhanced),
            "--output-dir", str(tmp_path / "out"),
        ])


def test_main_requires_perceptual_dependencies(monkeypatch, tmp_path):
    monkeypatch.setattr(score, "pesq_fn", None)
    monkeypatch.setattr(score, "stoi_fn", None)
    with pytest.raises(SystemExit, match="missing scoring dependencies"):
        score.main([
            "--clean-dir", str(tmp_path / "clean"),
            "--enhanced-dir", str(tmp_path / "enhanced"),
            "--output-dir", str(tmp_path / "out"),
        ])
