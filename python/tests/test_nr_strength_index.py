"""NR strength index <-> name: the CLI digit "0".."3" must equal the C `AnrMode` value of the same preset."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.nr_strength import NR_STRENGTH_PRESETS, nr_strength_name  # noqa: E402

ANR_TYPES_H = ROOT.parent / "c_impl" / "include" / "anr_types.h"


def test_index_matches_c_anr_mode_values():
    text = ANR_TYPES_H.read_text(encoding="utf-8")
    c_modes = {name.lower(): int(value)
               for name, value in re.findall(r"ANR_MODE_([A-Z]+)\s*=\s*(\d+)", text)}
    assert set(c_modes) == set(NR_STRENGTH_PRESETS)
    for name, value in c_modes.items():
        assert nr_strength_name(str(value)) == name


def test_names_and_other_values_pass_through_unchanged():
    for name in NR_STRENGTH_PRESETS:
        assert nr_strength_name(name) == name
    for other in ("4", "-1", "02", " 2", "", "loud"):
        assert nr_strength_name(other) == other
