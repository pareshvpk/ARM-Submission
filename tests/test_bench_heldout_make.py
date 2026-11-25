"""make_heldout counts empty texts separately from duplicates."""
from __future__ import annotations

import csv
from pathlib import Path

from bench.heldout.make_heldout import _label_to_truth, process_source
from data.build_corpus import compute_text_hash


def test_empty_counted_separately(tmp_path: Path):
    csv_path = tmp_path / "src.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label", "language"])
        w.writeheader()
        w.writerow({"text": "hello world", "label": "ham", "language": "English"})
        w.writerow({"text": "   ", "label": "ham", "language": "English"})
        w.writerow({"text": "", "label": "scam", "language": "English"})
        w.writerow({"text": "hello world", "label": "ham", "language": "English"})
    out_rows: list[dict[str, str]] = []
    stats = process_source(csv_path, "src", "mixed", False, set(), set(), out_rows)
    assert stats["dropped_empty"] == 2
    assert stats["dropped_duplicate"] == 1
    assert stats["kept"] == 1
    assert len(out_rows) == 1


def test_unknown_labels_dropped_not_risky(tmp_path: Path):
    csv_path = tmp_path / "src.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label", "language"])
        w.writeheader()
        w.writerow({"text": "hello ham", "label": "ham", "language": "English"})
        w.writerow({"text": "hello scam", "label": "scam", "language": "English"})
        w.writerow({"text": "hello spam", "label": "spam", "language": "English"})
        w.writerow({"text": "hello empty", "label": "", "language": "English"})
        w.writerow({"text": "hello typo", "label": "scamm", "language": "English"})
        w.writerow({"text": "hello unknown", "label": "unknown", "language": "English"})
    out_rows: list[dict[str, str]] = []
    stats = process_source(csv_path, "src", "mixed", False, set(), set(), out_rows)
    assert stats["kept"] == 3
    assert stats["dropped_unmapped"] == 3
    assert stats["kept_per_truth"] == {"ham": 1, "risky": 2}
    truths = {r["truth"] for r in out_rows}
    assert truths == {"ham", "risky"}
    assert len(out_rows) == 3


def test_label_to_truth_unit():
    assert _label_to_truth("ham") == "ham"
    assert _label_to_truth(" HAM ") == "ham"
    assert _label_to_truth("spam") == "risky"
    assert _label_to_truth("Scam") == "risky"
    assert _label_to_truth("") is None
    assert _label_to_truth("   ") is None
    assert _label_to_truth(None) is None
    assert _label_to_truth(float("nan")) is None
    assert _label_to_truth("scamm") is None
    assert _label_to_truth("unknown") is None


def test_normalised_duplicate(tmp_path: Path):
    csv_path = tmp_path / "src.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label", "language"])
        w.writeheader()
        w.writerow({"text": "OTP 482910", "label": "scam", "language": "English"})
        w.writerow({"text": "otp  482910", "label": "scam", "language": "English"})
    out_rows: list[dict[str, str]] = []
    stats = process_source(csv_path, "src", "mixed", False, set(), set(), out_rows)
    assert stats["kept"] == 1
    assert stats["dropped_duplicate"] == 1
    assert len(out_rows) == 1


def test_normalised_corpus_overlap(tmp_path: Path):
    csv_path = tmp_path / "src.csv"
    corpus_hash = compute_text_hash("OTP 482910")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label", "language"])
        w.writeheader()
        w.writerow({"text": "otp  482910", "label": "scam", "language": "English"})
        w.writerow({"text": "fresh message", "label": "ham", "language": "English"})
    out_rows: list[dict[str, str]] = []
    stats = process_source(csv_path, "src", "mixed", False, {corpus_hash}, set(), out_rows)
    assert stats["dropped_seen_in_corpus"] == 1
    assert stats["kept"] == 1
