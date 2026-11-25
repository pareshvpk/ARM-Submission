from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import sim_script_gate  # noqa: E402


CASES = [
    (
        "English",
        "Your parcel will arrive tomorrow morning.",
        "Latin",
        1.0,
        False,
    ),
    (
        "Hinglish in Latin letters",
        "Aapka OTP turant share karo warna account band ho jayega.",
        "Latin",
        1.0,
        False,
    ),
    (
        "Tamil",
        "உங்கள் கணக்கு முடக்கப்பட்டது. உடனே இணைப்பை திறக்கவும்.",
        "Tamil",
        1.0,
        True,
    ),
    (
        "Hindi",
        "आपका खाता बंद कर दिया जाएगा। तुरंत केवाईसी करें।",
        "Devanagari",
        1.0,
        True,
    ),
    (
        "Mixed mostly Latin with two Tamil words",
        "Please pay the bill today வணக்கம் நன்றி tomorrow morning.",
        "Latin",
        None,
        False,
    ),
    (
        "Digits and emoji only",
        "12345 67890 😀🚀🔥 !!!",
        "Other",
        0.0,
        False,
    ),
]


@pytest.mark.parametrize("label,text,expected_script,expected_share,expected_gated", CASES)
def test_dominant_script(
    label: str,
    text: str,
    expected_script: str,
    expected_share: float | None,
    expected_gated: bool,
) -> None:
    script, share = sim_script_gate.dominant_script(text)
    assert script == expected_script, label
    if expected_share is None:
        assert 0.5 <= share < 1.0, label
    else:
        assert share == pytest.approx(expected_share), label
    assert sim_script_gate.is_gated(text) is expected_gated, label


@pytest.mark.skipif(
    not (sim_script_gate.DUMP_CSV.is_file() and sim_script_gate.HELDOUT_CSV.is_file()),
    reason="held-out CSV or calibration dump not present",
)
def test_shipped_run_leaves_non_gated_rows_at_plain_fuse() -> None:
    rows, _missing = sim_script_gate._load_rows()
    assert rows
    params = sim_script_gate.shipped_params()
    plain = sim_script_gate._fuse_levels(rows, params)
    for variant in ("V1", "V2", "V3", "V4"):
        records = sim_script_gate._shipped_records(rows, plain, variant, params)
        for row, record, base in zip(rows, records, plain):
            if row["gated"]:
                continue
            assert record["level"] == base["level"]
            assert record["risk"] == pytest.approx(base["risk"])
