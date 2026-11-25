from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import calibrate  # noqa: E402
import pytest  # noqa: E402

RULES = calibrate.load_fusion_rules()


def make_row(text_hash, truth, p_ham, p_unw, p_scam, cues=(), max_url=0.0, collect_pin=False, shoe=False, source="s", language="en"):
    row = {
        "text_hash": text_hash,
        "source": source,
        "language": language,
        "truth": truth,
        "p_ham": p_ham,
        "p_unwanted": p_unw,
        "p_scam": p_scam,
        "cue_types": set(cues),
        "num_urls": 1 if max_url else 0,
        "max_untrusted_url_prob": max_url,
        "indicators": "",
        "collect_pin": collect_pin,
        "shoe_store_promotion": shoe,
    }
    risk, level = calibrate.risk_and_level(row, calibrate.BASELINE_PARAMS | {"medium_threshold": RULES["medium_level_threshold"], "high_threshold": RULES["high_level_threshold"]}, RULES)
    row["fused_level"] = level
    row["fused_risk"] = risk
    row["fused_label"] = "scam" if level == "high" else "ham"
    return row


def make_dump(tmp_path):
    rows = [
        make_row("h1", "ham", 0.9, 0.05, 0.05),
        make_row("h2", "ham", 0.6, 0.1, 0.3, cues=("urgency",)),
        make_row("r1", "risky", 0.05, 0.05, 0.9, cues=("urgency", "threat")),
        make_row("r2", "risky", 0.2, 0.3, 0.5, max_url=0.9),
        make_row("h3", "ham", 0.8, 0.1, 0.1, source="s2"),
        make_row("r3", "risky", 0.1, 0.1, 0.8, source="s2"),
        make_row("x1", "unknown", 0.1, 0.1, 0.8, cues=("pay",), shoe=True, source="extra", language="unknown"),
    ]
    path = tmp_path / "dump.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "text_hash", "source", "language", "truth", "p_ham", "p_unwanted", "p_scam",
                "fused_label", "fused_level", "fused_risk", "cue_types", "num_urls",
                "max_untrusted_url_prob", "indicators", "collect_pin", "shoe_store_promotion",
            ],
        )
        writer.writeheader()
        for r in rows:
            out = dict(r)
            out["cue_types"] = ";".join(sorted(r["cue_types"]))
            out["collect_pin"] = "true" if r["collect_pin"] else "false"
            out["shoe_store_promotion"] = "true" if r["shoe_store_promotion"] else "false"
            writer.writerow(out)
    return path, rows


def make_row_dicts():
    return [
        {"text_hash": "h1", "source": "s", "language": "en", "truth": "ham",
         "p_ham": 0.9, "p_unwanted": 0.05, "p_scam": 0.05},
        {"text_hash": "h2", "source": "s", "language": "en", "truth": "ham",
         "p_ham": "", "p_unwanted": 0.1, "p_scam": 0.3},  # missing p_ham -> skip
        {"text_hash": "r1", "source": "s", "language": "en", "truth": "risky",
         "p_ham": 0.05, "p_unwanted": 0.05, "p_scam": 0.9},
        {"text_hash": "r2", "source": "s", "language": "en", "truth": "risky",
         "p_ham": 0.2, "p_unwanted": 0.3, "p_scam": "nan"},  # non-finite -> skip
    ]


def _write_dump(path, rows):
    import csv
    fieldnames = [
        "text_hash", "source", "language", "truth", "p_ham", "p_unwanted",
        "p_scam", "fused_label", "fused_level", "fused_risk", "cue_types",
        "num_urls", "max_untrusted_url_prob", "indicators", "collect_pin",
        "shoe_store_promotion",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            out = dict(r)
            out["cue_types"] = ";".join(sorted(out.get("cue_types", set()) or set()))
            out["collect_pin"] = "true" if out.get("collect_pin") else "false"
            out["shoe_store_promotion"] = "true" if out.get("shoe_store_promotion") else "false"
            for k in fieldnames:
                out.setdefault(k, "")
            writer.writerow({k: out[k] for k in fieldnames})


def test_baseline_reproduction_passes(tmp_path):
    path, rows = make_dump(tmp_path)
    loaded = calibrate.read_dump(path)
    calibrate.assert_baseline_reproduced(loaded, RULES)
    assert len(loaded) == len(rows)


def test_baseline_reproduction_fails_loudly(tmp_path):
    path, _rows = make_dump(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace("low", "high").replace("medium", "high")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    loaded = calibrate.read_dump(path)
    with pytest.raises(SystemExit):
        calibrate.assert_baseline_reproduced(loaded, RULES)


def test_split_determinism(tmp_path):
    _path, rows = make_dump(tmp_path)
    a = calibrate.split_rows(rows)
    b = calibrate.split_rows(rows)
    assert [r["text_hash"] for r in a[0]] == [r["text_hash"] for r in b[0]]
    assert [r["text_hash"] for r in a[1]] == [r["text_hash"] for r in b[1]]
    assert len(a[0]) + len(a[1]) == 6
    assert len(a[2]) == 1


def test_acceptance_logic():
    baseline = {"risky_recall": 0.90, "ham_fpr": 0.10}
    ok_cand = {"risky_recall": 0.895, "ham_fpr": 0.08}
    passes, _ = calibrate.acceptance_passes(baseline, ok_cand, ["low"])
    assert passes
    bad_recall = {"risky_recall": 0.80, "ham_fpr": 0.05}
    passes, _ = calibrate.acceptance_passes(baseline, bad_recall, ["low"])
    assert not passes
    bad_fpr = {"risky_recall": 0.90, "ham_fpr": 0.11}
    passes, _ = calibrate.acceptance_passes(baseline, bad_fpr, ["low"])
    assert not passes
    shoe_high = {"risky_recall": 0.90, "ham_fpr": 0.05}
    passes, _ = calibrate.acceptance_passes(baseline, shoe_high, ["high"])
    assert not passes


def test_run_and_outputs(tmp_path):
    path, _rows = make_dump(tmp_path)
    result = calibrate.run(path)
    assert "baseline_test" in result
    assert "extra_baseline_levels" in result
    json_path, md_path = calibrate.write_outputs(result, tmp_path / "cal")

    path = tmp_path / "dump_missing.csv"
    _write_dump(path, make_row_dicts())
    loaded = calibrate.read_dump(path)
    assert len(loaded) == 2
    kept = {r["text_hash"] for r in loaded}
    assert kept == {"h1", "r1"}


def test_read_dump_reports_skipped_count(tmp_path, capsys):
    path = tmp_path / "dump_bad.csv"
    _write_dump(path, make_row_dicts())
    calibrate.read_dump(path)
    captured = capsys.readouterr()
    assert "skipped 2 row(s) with missing or non-finite probabilities" in captured.err


def test_apply_temperature_all_zero_returns_probs():
    # All-zero probs must not produce nan risk; apply_temperature returns probs.
    out = calibrate.apply_temperature((0.0, 0.0, 0.0), 0.5)
    assert out == (0.0, 0.0, 0.0)
    row = {
        "p_ham": 0.0, "p_unwanted": 0.0, "p_scam": 0.0,
        "max_untrusted_url_prob": 0.0, "cue_types": set(), "collect_pin": False,
    }
    risk, level = calibrate.risk_and_level(
        row, calibrate.BASELINE_PARAMS,
        {"medium_level_threshold": 0.35, "high_level_threshold": 0.6,
         "url_weight": 1.0, "cue_cap": 1.0, "cue_weight": 0.1,
         "sms_ham_confidence_threshold": 0.9, "combo_score": 0.0,
         "app_install_score": 0.0, "collect_pin_score": 0.0,
         "risk_round_decimals": 2},
    )
    assert risk == 0.0
    assert level == "low"
    assert not (risk != risk)  # not nan
