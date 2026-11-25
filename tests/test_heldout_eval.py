from __future__ import annotations

import csv
import io

from bench.heldout.eval_heldout import (
    build_report,
    compute_group_metrics,
    compute_text_hash,
    evaluate_csv,
    evaluate_rows,
    is_risky_level,
)


class FakePipeline:
    def __init__(self, mapping):
        self.mapping = dict(mapping)

    def __call__(self, text):
        label, level, risk, latency = self.mapping[text]
        return {
            "evidence": {"label": label, "level": level, "risk": risk},
            "timings_ms": {"total_ms": latency},
        }


def _tiny_rows_and_mapping():
    rows = [
        {"text": "t-ham-tn", "truth": "ham", "source": "srcA", "language": "English", "synthetic": "mixed"},
        {"text": "t-ham-fp", "truth": "ham", "source": "srcA", "language": "English", "synthetic": "mixed"},
        {"text": "t-risky-tp", "truth": "risky", "source": "srcA", "language": "English", "synthetic": "mixed"},
        {"text": "t-risky-tp2", "truth": "risky", "source": "srcA", "language": "English", "synthetic": "mixed"},
        {"text": "t-risky-fn", "truth": "risky", "source": "srcA", "language": "English", "synthetic": "mixed"},
    ]
    mapping = {
        "t-ham-tn": ("ham", "low", 0.05, 10.0),
        "t-ham-fp": ("unwanted", "medium", 0.45, 20.0),
        "t-risky-tp": ("scam", "high", 0.90, 30.0),
        "t-risky-tp2": ("unwanted", "medium", 0.50, 40.0),
        "t-risky-fn": ("ham", "low", 0.10, 50.0),
    }
    return rows, mapping


def test_is_risky_level_matches_alert_policy():
    assert is_risky_level("medium") is True
    assert is_risky_level("high") is True
    assert is_risky_level("low") is False
    assert is_risky_level("LOW") is False and is_risky_level("low") is False


def test_text_hash_consistent_with_corpus():
    from data.build_corpus import compute_text_hash as corpus_hash

    assert compute_text_hash("Hello  WORLD") == corpus_hash("Hello  WORLD")
    assert compute_text_hash("") == corpus_hash("")
    assert compute_text_hash("  \t ") == corpus_hash("  \t ")
    assert "hello" not in compute_text_hash("Hello world")


def test_metric_arithmetic_overall_and_groups():
    rows, mapping = _tiny_rows_and_mapping()
    fake = FakePipeline(mapping)
    records, report = evaluate_rows(rows, fake)
    assert len(records) == 5
    for rec in records:
        assert "text" not in rec
        assert rec["text_hash"] == compute_text_hash(rec["text_hash"] if False else _reverse_lookup(rows, mapping, rec))
    overall = report["overall"]
    assert overall["n"] == 5
    assert overall["confusion_level"] == {
        "ham": {"low": 1, "medium": 1, "high": 0},
        "risky": {"low": 1, "medium": 1, "high": 1},
    }
    assert overall["confusion_label"] == {
        "ham": {"ham": 1, "unwanted": 1, "scam": 0},
        "risky": {"ham": 1, "unwanted": 1, "scam": 1},
    }
    assert abs(overall["risky_recall"] - (2.0 / 3.0)) < 1e-9
    assert abs(overall["false_positive_rate"] - 0.5) < 1e-9
    assert abs(overall["precision"] - (2.0 / 3.0)) < 1e-9
    assert abs(overall["f1"] - (2.0 / 3.0)) < 1e-9
    assert overall["latency_median_ms"] == 30.0
    assert overall["latency_p95_ms"] == 50.0
    src = report["per_source"]["srcA"]
    assert src["n"] == 5
    lang = report["per_language"]["English"]
    assert lang["n"] == 5
    assert src == overall
    assert lang == overall


def _reverse_lookup(rows, mapping, rec):
    for row in rows:
        if compute_text_hash(row["text"]) == rec["text_hash"]:
            return row["text"]
    raise AssertionError("hash not found")


def test_in_memory_csv_and_fake_pipeline(tmp_path):
    rows, mapping = _tiny_rows_and_mapping()
    csv_path = tmp_path / "tiny.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["text", "truth", "source", "language", "synthetic"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    fake = FakePipeline(mapping)
    records, report = evaluate_csv(str(csv_path), fake)
    assert len(records) == 5
    assert report["overall"]["n"] == 5
    assert report["overall"]["confusion_level"]["risky"] == {"low": 1, "medium": 1, "high": 1}
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["text", "truth", "source", "language", "synthetic"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    text_csv = buffer.getvalue()
    reader = csv.DictReader(io.StringIO(text_csv))
    records2, report2 = evaluate_rows(reader, FakePipeline(mapping))
    assert records2 == records
    assert report2 == report


def test_per_source_language_split():
    rows = [
        {"text": "a1", "truth": "ham", "source": "srcA", "language": "English", "synthetic": "mixed"},
        {"text": "b1", "truth": "risky", "source": "srcB", "language": "Hindi", "synthetic": "true"},
    ]
    mapping = {
        "a1": ("ham", "low", 0.05, 10.0),
        "b1": ("scam", "high", 0.9, 20.0),
    }
    _records, report = evaluate_rows(rows, FakePipeline(mapping))
    assert report["overall"]["n"] == 2
    assert report["per_source"]["srcA"]["n"] == 1
    assert report["per_source"]["srcB"]["n"] == 1
    assert report["per_language"]["English"]["n"] == 1
    assert report["per_language"]["Hindi"]["n"] == 1
    assert report["per_source"]["srcA"]["confusion_level"]["ham"] == {"low": 1, "medium": 0, "high": 0}
    assert report["per_source"]["srcB"]["confusion_level"]["risky"] == {"low": 0, "medium": 0, "high": 1}


def test_zero_division_safe():
    empty = build_report([])
    overall = empty["overall"]
    assert overall["n"] == 0
    assert overall["risky_recall"] == 0.0
    assert overall["false_positive_rate"] == 0.0
    assert overall["precision"] == 0.0
    assert overall["f1"] == 0.0
    assert overall["latency_median_ms"] == 0.0
    assert overall["latency_p95_ms"] == 0.0
    assert empty["per_source"] == {}
    assert empty["per_language"] == {}
    only_ham = [
        {"truth": "ham", "pred_label": "ham", "pred_level": "low", "latency_ms": 5.0, "source": "s", "language": "l"},
    ]
    metrics = compute_group_metrics(only_ham)
    assert metrics["risky_recall"] == 0.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["precision"] == 0.0
    assert metrics["f1"] == 0.0
    only_risky_no_risky_pred = [
        {"truth": "risky", "pred_label": "ham", "pred_level": "low", "latency_ms": 7.0, "source": "s", "language": "l"},
    ]
    m2 = compute_group_metrics(only_risky_no_risky_pred)
    assert m2["risky_recall"] == 0.0
    assert m2["false_positive_rate"] == 0.0
    assert m2["precision"] == 0.0
    assert m2["f1"] == 0.0
    only_risky = [
        {"truth": "risky", "pred_label": "scam", "pred_level": "high", "latency_ms": 9.0, "source": "s", "language": "l"},
    ]
    m3 = compute_group_metrics(only_risky)
    assert m3["risky_recall"] == 1.0
    assert m3["false_positive_rate"] == 0.0
    assert m3["precision"] == 1.0
    assert m3["f1"] == 1.0


def test_unknown_truth_rejected():
    import pytest as _pytest
    from bench.heldout.eval_heldout import compute_group_metrics as _cgm

    with _pytest.raises(ValueError):
        _cgm([{"truth": "maybe", "pred_label": "ham", "pred_level": "low", "latency_ms": 1.0, "source": "s", "language": "l"}])
    with _pytest.raises(ValueError):
        _cgm([{"truth": "", "pred_label": "ham", "pred_level": "low", "latency_ms": 1.0, "source": "s", "language": "l"}])
    with _pytest.raises(ValueError):
        evaluate_rows([{"text": "x", "truth": "typo", "source": "s", "language": "l"}], FakePipeline({"x": ("ham", "low", 0.0, 1.0)}))


def test_unknown_predictions_rejected():
    import pytest as _pytest
    from bench.heldout.eval_heldout import compute_group_metrics as _cgm

    with _pytest.raises(ValueError):
        _cgm([{"truth": "ham", "pred_label": "unknown_label", "pred_level": "low", "latency_ms": 1.0, "source": "s", "language": "l"}])
    with _pytest.raises(ValueError):
        _cgm([{"truth": "ham", "pred_label": "ham", "pred_level": "weird", "latency_ms": 1.0, "source": "s", "language": "l"}])
    with _pytest.raises(ValueError):
        evaluate_rows([{"text": "y", "truth": "ham", "source": "s", "language": "l"}], FakePipeline({"y": ("evil", "low", 0.0, 1.0)}))
    with _pytest.raises(ValueError):
        evaluate_rows([{"text": "z", "truth": "ham", "source": "s", "language": "l"}], FakePipeline({"z": ("ham", "sideways", 0.0, 1.0)}))
