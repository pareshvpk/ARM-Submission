from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import calibrate  # noqa: E402

from sentinel.fusion import fuse  # noqa: E402

DUMP_PATH = ROOT / "bench" / "heldout" / "calib_20261108" / "dump_20261108.csv"


def _fuse_inputs(row: dict):
    sms_result = {
        "probs": {"ham": row["p_ham"], "unwanted": row["p_unwanted"], "scam": row["p_scam"]},
        "label": "ham",
    }
    url_results = []
    if row["max_untrusted_url_prob"] > 0:
        url_results = [{"url": "http://example.xyz/login", "prob": row["max_untrusted_url_prob"], "indicators": []}]
    cues = [{"type": cue_type, "text": ""} for cue_type in sorted(row["cue_types"])]
    if row["collect_pin"]:
        has_payment = any(cue["type"] == "payment_request" for cue in cues)
        if has_payment:
            for cue in cues:
                if cue["type"] == "payment_request":
                    cue["text"] = "collect request"
                    break
        else:
            cues.append({"type": "payment_request", "text": "collect request"})
        has_pin = any(cue["type"] == "credential_request" for cue in cues)
        if has_pin:
            for cue in cues:
                if cue["type"] == "credential_request":
                    cue["text"] = "pin"
                    break
        else:
            cues.append({"type": "credential_request", "text": "pin"})
    return sms_result, url_results, cues


@pytest.mark.skipif(not DUMP_PATH.is_file(), reason="calibration dump bench/heldout/calib_20261108/dump_20261108.csv not present")
def test_shipped_fusion_matches_chosen_candidate_levels():
    rows = calibrate.read_dump(DUMP_PATH)
    assert rows, f"no rows in {DUMP_PATH}"
    rules = calibrate.load_fusion_rules()
    chosen = {
        "temperature": 3.0,
        "scam_weight": 0.9,
        "unwanted_weight": float(rules["sms_unwanted_weight"]),
        "medium_threshold": float(rules["medium_level_threshold"]),
        "high_threshold": float(rules["high_level_threshold"]),
    }
    mismatches = []
    for index, row in enumerate(rows):
        _expected_risk, expected_level = calibrate.risk_and_level(row, chosen, rules)
        sms_result, url_results, cues = _fuse_inputs(row)
        evidence = fuse("x", sms_result, url_results, cues)
        if evidence.level != expected_level:
            mismatches.append(
                {"row": index, "text_hash": row["text_hash"], "expected": expected_level, "actual": evidence.level}
            )
    assert not mismatches, f"{len(mismatches)} levels differ from calibrate.py chosen candidate; first: {mismatches[:10]}"
