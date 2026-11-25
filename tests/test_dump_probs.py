from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import dump_probs  # noqa: E402


def fake_evidence(label="ham", risk=0.1, level="low"):
    return SimpleNamespace(
        label=label,
        risk=risk,
        level=level,
        indicators=["impersonation"],
        cue_spans=[{"type": "impersonation", "start": 0, "end": 3, "text": "sbi"}],
        urls=[{"url": "http://x.top", "prob": 0.9, "trusted": False}],
    )


def test_text_hash_matches_eval_heldout():
    sys.path.insert(0, str(ROOT / "bench" / "heldout"))
    import eval_heldout

    text = "  Hello   WORLD  "
    assert dump_probs.compute_text_hash(text) == eval_heldout.compute_text_hash(text)


def test_build_dump_row_no_text_and_columns():
    text = "Big shoe-store sale! Flat 70 percent off today only."
    row = dump_probs.build_dump_row(
        text, "extra", "unknown", "unknown", {"ham": 0.1, "unwanted": 0.1, "scam": 0.8}, fake_evidence(level="high", risk=0.84, label="scam")
    )
    for field in dump_probs.FIELDNAMES:
        assert field in row
    assert "shoe-store" not in json.dumps(row).lower() or row["shoe_store_promotion"] == "true"
    assert text not in json.dumps(row)
    assert row["shoe_store_promotion"] == "true"
    assert row["p_scam"] == 0.8
    assert row["max_untrusted_url_prob"] == 0.9
    assert row["num_urls"] == 1
    assert row["cue_types"] == "impersonation"


def test_dump_tokens_for_texts(tmp_path):
    out = tmp_path / "tokens.jsonl"
    dump_probs.dump_tokens_for_texts(["hello world", "second"], lambda t: [1, 2, 3], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["input_ids"] == [1, 2, 3]
    assert first["line"] == 0


def test_extra_texts_scoring_writes_no_text(tmp_path, monkeypatch):
    extra_file = tmp_path / "extra.txt"
    extra_file.write_text("Your order has been delivered.\nBig shoe-store sale! Flat 70 percent off today only.\n", encoding="utf-8")
    out_csv = tmp_path / "dump.csv"
    monkeypatch.setattr(dump_probs, "load_detectors_for_dump", lambda args: (None, SimpleNamespace(predict=lambda t: {"probs": {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}, "label": "ham"})))
    from sentinel.pipeline import analyse as _analyse  # noqa: F401

    def fake_analyse(text, url_det=None, sms_det=None, advisor=None):
        from sentinel.fusion import Evidence

        return {"evidence": fake_evidence()}

    import sentinel.pipeline

    monkeypatch.setattr(sentinel.pipeline, "analyse", fake_analyse)
    rc = dump_probs.main(["--extra-texts", str(extra_file), "--out", str(out_csv)])
    assert rc == 0
    with open(out_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert all(r["source"] == "extra" and r["truth"] == "unknown" for r in rows)
    assert "delivered" not in out_csv.read_text(encoding="utf-8").lower()
