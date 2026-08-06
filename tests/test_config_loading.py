"""Fail-closed tests for the public Python configuration loader."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import process_audio


def test_missing_yaml_dependency_is_fatal(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("name: test\n", encoding="utf-8")
    monkeypatch.setattr(process_audio, "YAML_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="PyYAML is required"):
        process_audio.load_config(str(config))


def test_missing_config_is_fatal(tmp_path):
    with pytest.raises(FileNotFoundError, match="config file not found"):
        process_audio.load_config(str(tmp_path / "missing.yaml"))


def test_non_mapping_config_is_fatal(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config root must be a mapping"):
        process_audio.load_config(str(config))


def test_valid_mapping_loads(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("audio:\n  sample_rate: 16000\n", encoding="utf-8")
    assert process_audio.load_config(str(config)) == {
        "audio": {"sample_rate": 16000}
    }
