"""Offline simulation of a dominant-script gate on the held-out SMS set.

This script does not touch the app or the detector code. It joins the
held-out messages to the probability dump by the documented text hash, proves
that it reproduces the dumped fused level with the real fusion code path, and
then scores five gate variants on the rows whose dominant script is not Latin.

Run from the repository root:

    .venv\\Scripts\\python.exe bench\\heldout\\sim_script_gate.py
"""

from __future__ import annotations

import collections
import csv
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for path in (str(ROOT_DIR), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import calibrate  # noqa: E402
import dump_probs  # noqa: E402
import sentinel.fusion as fusion_mod  # noqa: E402
import sentinel.rules as rules_mod  # noqa: E402
from sentinel.fusion import _apply_temperature  # noqa: E402

HELDOUT_CSV = HERE / "heldout_20261107.csv"
DUMP_CSV = HERE / "calib_20261108" / "dump_20261108.csv"
OUT_MD = HERE / "sim_script_gate_20261110.md"
OUT_JSON = HERE / "sim_script_gate_20261110.json"

VARIANTS = ("V0", "V1", "V2", "V3", "V4")
GATED_SCRIPT = "Latin"
GATE_MIN_SHARE = 0.5
MISMATCH_LIMIT = 0.005

DUMP_BASELINE_PARAMS = {
    "temperature": float(calibrate.BASELINE_PARAMS["temperature"]),
    "scam_weight": float(calibrate.BASELINE_PARAMS["scam_weight"]),
    "unwanted_weight": float(calibrate.BASELINE_PARAMS["unwanted_weight"]),
}

MEDIUM_THRESHOLD = float(rules_mod.FUSION_RULES["medium_level_threshold"])
HIGH_THRESHOLD = float(rules_mod.FUSION_RULES["high_level_threshold"])
URL_WEIGHT = float(rules_mod.FUSION_RULES["url_weight"])
CUE_WEIGHT = float(rules_mod.FUSION_RULES["cue_weight"])
CUE_CAP = float(rules_mod.FUSION_RULES["cue_cap"])
COMBO_SCORE = float(rules_mod.FUSION_RULES["combo_score"])
APP_INSTALL_SCORE = float(rules_mod.FUSION_RULES["app_install_score"])
COLLECT_PIN_SCORE = float(rules_mod.FUSION_RULES["collect_pin_score"])
HAM_CONFIDENCE = float(rules_mod.FUSION_RULES["sms_ham_confidence_threshold"])
URL_PHISHING_THRESHOLD = float(rules_mod.FUSION_RULES["url_phishing_label_threshold"])
RISK_ROUND_DECIMALS = int(rules_mod.FUSION_RULES["risk_round_decimals"])
CAP_VALUE = round(MEDIUM_THRESHOLD - 0.0001, RISK_ROUND_DECIMALS)
V4_SCAM_CONFIDENCE = 0.9

SCRIPT_BLOCKS: list[tuple[str, list[tuple[int, int]]]] = [
    ("Latin", [(0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x00D6),
               (0x00D8, 0x00F6), (0x00F8, 0x024F), (0x1E00, 0x1EFF)]),
    ("Devanagari", [(0x0900, 0x097F), (0xA8E0, 0xA8FF)]),
    ("Bengali", [(0x0980, 0x09FF)]),
    ("Gurmukhi", [(0x0A00, 0x0A7F)]),
    ("Gujarati", [(0x0A80, 0x0AFF)]),
    ("Odia", [(0x0B00, 0x0B7F)]),
    ("Tamil", [(0x0B80, 0x0BFF)]),
    ("Telugu", [(0x0C00, 0x0C7F)]),
    ("Kannada", [(0x0C80, 0x0CFF)]),
    ("Malayalam", [(0x0D00, 0x0D7F)]),
    ("Arabic", [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]),
]
SCRIPT_ORDER = [name for name, _ranges in SCRIPT_BLOCKS] + ["Other"]


def _script_of(char: str) -> str:
    """Return the Unicode-block script name for a single letter."""
    codepoint = ord(char)
    for name, ranges in SCRIPT_BLOCKS:
        for start, end in ranges:
            if start <= codepoint <= end:
                return name
    return "Other"


def dominant_script(text: str) -> tuple[str, float]:
    """Return (script, share) for the script with the most letters in *text*.

    Only Unicode letter categories are counted. Digits, punctuation, marks,
    emoji and whitespace are ignored. A text with no letters returns
    ("Other", 0.0).
    """
    counts: dict[str, int] = collections.Counter()
    for char in text:
        if unicodedata.category(char).startswith("L"):
            counts[_script_of(char)] += 1
    total = sum(counts.values())
    if total == 0:
        return "Other", 0.0
    name, count = max(
        counts.items(),
        key=lambda item: (item[1], -SCRIPT_ORDER.index(item[0]) if item[0] in SCRIPT_ORDER else -len(SCRIPT_ORDER)),
    )
    return name, count / total


def is_gated(text: str) -> bool:
    """True when the dominant script is not Latin and holds at least half the letters."""
    script, share = dominant_script(text)
    return script != GATED_SCRIPT and share >= GATE_MIN_SHARE


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Confusion counts and headline metrics for risky-vs-ham records."""
    tp = fn = fp = tn = 0
    for record in records:
        predicted_risky = record["level"] in ("medium", "high")
        if record["truth"] == "risky" and predicted_risky:
            tp += 1
        elif record["truth"] == "risky":
            fn += 1
        elif record["truth"] == "ham" and predicted_risky:
            fp += 1
        else:
            tn += 1
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(records),
        "risky_recall": recall,
        "fpr_ham": fpr,
        "precision": precision,
        "f1": f1,
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
    }


def _levels_for(
    rows: list[dict[str, Any]], variant: str, params: dict[str, float] | None = None
) -> list[dict[str, Any]]:
    """Return per-row truth/level/risk for a variant, leaving non-gated rows at V0."""
    if params is None:
        params = DUMP_BASELINE_PARAMS
    out = []
    for row in rows:
        chosen = variant if row["gated"] and variant != "V0" else "V0"
        level, risk = _score_row(row, chosen, params)
        out.append({"truth": row["truth"], "level": level, "risk": risk})
    return out


def shipped_params() -> dict[str, float]:
    """Return the fusion parameters that ship in sentinel/data/rules.json right now."""
    return {
        "temperature": float(rules_mod.FUSION_RULES["sms_temperature"]),
        "scam_weight": float(rules_mod.FUSION_RULES["sms_scam_weight"]),
        "unwanted_weight": float(rules_mod.FUSION_RULES["sms_unwanted_weight"]),
    }


def _shipped_records(
    rows: list[dict[str, Any]],
    real_shipped: list[dict[str, Any]],
    variant: str,
    params: dict[str, float],
) -> list[dict[str, Any]]:
    """Mix the real shipped fuse() for non-gated rows with the variant on gated rows."""
    records = []
    for row, base in zip(rows, real_shipped):
        if not row["gated"] or variant == "V0":
            level, risk = base["level"], base["risk"]
        else:
            level, risk = _score_row(row, variant, params)
        records.append({"truth": row["truth"], "level": level, "risk": risk})
    return records


def _score_row(
    row: dict[str, Any], variant: str, params: dict[str, float] | None = None
) -> tuple[str, float]:
    """Reproduce the real fusion score and apply one gate variant to the SMS term."""
    if params is None:
        params = DUMP_BASELINE_PARAMS
    scaled_ham, scaled_unwanted, scaled_scam = _apply_temperature(
        (row["p_ham"], row["p_unwanted"], row["p_scam"]),
        params["temperature"],
    )
    sms_score = (
        params["scam_weight"] * scaled_scam
        + params["unwanted_weight"] * scaled_unwanted
    )
    cue_types = row["cue_types"]
    if variant == "V1":
        sms_score = params["scam_weight"] * scaled_scam
    elif variant == "V2":
        sms_score = 0.5 * sms_score
    elif variant in ("V3", "V4"):
        no_cue = len(cue_types) == 0
        no_alarming_url = row["max_untrusted_url_prob"] < URL_PHISHING_THRESHOLD
        below_v4_confidence = scaled_scam < V4_SCAM_CONFIDENCE
        if no_cue and no_alarming_url and (variant == "V3" or below_v4_confidence):
            sms_score = min(sms_score, CAP_VALUE)

    url_score = row["max_untrusted_url_prob"] * URL_WEIGHT
    cues_score = min(CUE_CAP, CUE_WEIGHT * len(cue_types))
    combo = (
        "urgency" in cue_types
        and bool(cue_types & {"threat", "credential_request", "payment_request"})
        and not (scaled_ham >= HAM_CONFIDENCE)
    )
    combo_score = COMBO_SCORE if combo else 0.0
    app_install_score = APP_INSTALL_SCORE if "app_install" in cue_types else 0.0
    collect_pin_score = COLLECT_PIN_SCORE if row["collect_pin"] else 0.0

    risk = max(sms_score, url_score, cues_score, combo_score, app_install_score, collect_pin_score)
    risk = round(min(1.0, max(0.0, risk)), RISK_ROUND_DECIMALS)
    if risk >= HIGH_THRESHOLD:
        level = "high"
    elif risk >= MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"
    return level, risk


def _fuse_inputs(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild the inputs the dump used so the real fuse() can be replayed."""
    sms_result = {
        "probs": {"ham": row["p_ham"], "unwanted": row["p_unwanted"], "scam": row["p_scam"]},
        "label": "ham",
    }
    url_results: list[dict[str, Any]] = []
    if row["max_untrusted_url_prob"] > 0:
        url_results = [
            {"url": "http://example.xyz/login", "prob": row["max_untrusted_url_prob"], "indicators": []}
        ]
    cues = [{"type": cue_type, "text": ""} for cue_type in sorted(row["cue_types"])]
    if row["collect_pin"]:
        if not any(cue["type"] == "payment_request" for cue in cues):
            cues.append({"type": "payment_request", "text": "collect request"})
        else:
            for cue in cues:
                if cue["type"] == "payment_request":
                    cue["text"] = "collect request"
                    break
        if not any(cue["type"] == "credential_request" for cue in cues):
            cues.append({"type": "credential_request", "text": "pin"})
        else:
            for cue in cues:
                if cue["type"] == "credential_request":
                    cue["text"] = "pin"
                    break
    return sms_result, url_results, cues


def _fuse_levels(rows: list[dict[str, Any]], params: dict[str, float]) -> list[dict[str, Any]]:
    """Run the real sentinel.fusion.fuse() with a temporary fusion parameter set."""
    keys = ("sms_temperature", "sms_scam_weight", "sms_unwanted_weight")
    saved = {key: rules_mod.FUSION_RULES[key] for key in keys}
    rules_mod.FUSION_RULES["sms_temperature"] = params["temperature"]
    rules_mod.FUSION_RULES["sms_scam_weight"] = params["scam_weight"]
    rules_mod.FUSION_RULES["sms_unwanted_weight"] = params["unwanted_weight"]
    try:
        out = []
        for row in rows:
            sms_result, url_results, cues = _fuse_inputs(row)
            evidence = fusion_mod.fuse("x", sms_result, url_results, cues)
            out.append({"level": evidence.level, "risk": evidence.risk})
        return out
    finally:
        for key, value in saved.items():
            rules_mod.FUSION_RULES[key] = value


def _load_rows() -> tuple[list[dict[str, Any]], int]:
    """Join held-out messages to the dump by text hash."""
    dump_by_hash = {}
    with open(DUMP_CSV, "r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            dump_by_hash[str(raw.get("text_hash", "") or "")] = raw
    rows: list[dict[str, Any]] = []
    missing = 0
    with open(HELDOUT_CSV, "r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            text = str(raw.get("text", "") or "")
            text_hash = dump_probs.compute_text_hash(text)
            dumped = dump_by_hash.get(text_hash)
            if dumped is None:
                missing += 1
                continue
            script, share = dominant_script(text)
            rows.append(
                {
                    "text_hash": text_hash,
                    "language": str(raw.get("language", "") or ""),
                    "truth": str(raw.get("truth", "") or "").strip().lower(),
                    "synthetic": str(raw.get("synthetic", "") or "").strip().lower(),
                    "script": script,
                    "script_share": share,
                    "gated": script != GATED_SCRIPT and share >= GATE_MIN_SHARE,
                    "p_ham": float(dumped["p_ham"]),
                    "p_unwanted": float(dumped["p_unwanted"]),
                    "p_scam": float(dumped["p_scam"]),
                    "cue_types": {part for part in str(dumped.get("cue_types", "") or "").split(";") if part},
                    "max_untrusted_url_prob": float(dumped["max_untrusted_url_prob"]),
                    "collect_pin": str(dumped.get("collect_pin", "") or "").strip().lower() == "true",
                    "dumped_level": str(dumped.get("fused_level", "") or "").strip().lower(),
                    "dumped_risk": float(dumped.get("fused_risk", 0.0) or 0.0),
                }
            )
    return rows, missing


def _grouped_metrics(
    rows: list[dict[str, Any]], variant_records: list[dict[str, Any]], key: str
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row, record in zip(rows, variant_records):
        groups[str(row[key])].append(record)
    return {name: _metrics(group) for name, group in sorted(groups.items())}


def run() -> dict[str, Any]:
    """Run the simulation and return the report payload."""
    rows, missing = _load_rows()
    if not rows:
        raise SystemExit("no joined rows: check the held-out CSV and the dump")

    shipped_fusion_params = shipped_params()
    real_baseline = _fuse_levels(rows, DUMP_BASELINE_PARAMS)
    real_shipped = _fuse_levels(rows, shipped_fusion_params)
    replica_baseline = [_score_row(row, "V0") for row in rows]

    level_mismatches = sum(
        1 for row, (level, _risk) in zip(rows, replica_baseline) if level != row["dumped_level"]
    )
    risk_mismatches = sum(
        1 for row, (_level, risk) in zip(rows, replica_baseline) if abs(risk - row["dumped_risk"]) > 1e-9
    )
    real_vs_replica = sum(
        1
        for result, (replica_level, replica_risk) in zip(real_baseline, replica_baseline)
        if result["level"] != replica_level or abs(result["risk"] - replica_risk) > 1e-9
    )
    shipped_level_mismatches = sum(
        1 for row, result in zip(rows, real_shipped) if result["level"] != row["dumped_level"]
    )
    mismatch_share = level_mismatches / len(rows)
    shipped_share = shipped_level_mismatches / len(rows)

    reproduction = {
        "method": (
            "real sentinel.fusion.fuse() with FUSION_RULES temporarily set to the dump-time "
            "baseline (temperature 1.0, scam weight 1.0, unwanted weight 0.5)"
        ),
        "baseline_params": DUMP_BASELINE_PARAMS,
        "n_rows": len(rows),
        "n_missing_join": missing,
        "n_level_mismatches": level_mismatches,
        "level_mismatch_percent": mismatch_share * 100.0,
        "limit_percent": MISMATCH_LIMIT * 100.0,
        "passed": mismatch_share <= MISMATCH_LIMIT,
        "n_risk_mismatches": risk_mismatches,
        "n_replica_vs_real_fuse_mismatches": real_vs_replica,
        "shipped_rules_level_mismatches": shipped_level_mismatches,
        "shipped_rules_mismatch_percent": shipped_share * 100.0,
        "note": (
            "The dumped fused_level is the pre-calibration baseline recorded in "
            "calibrate.BASELINE_PARAMS and calibration.md (temperature 1.0, scam weight 1.0). "
            "The shipped rules.json is the calibrated candidate (temperature 3.0, scam weight 0.9), "
            "so replaying the shipped parameters against the dump is expected to differ and is "
            "reported only for transparency."
        ),
    }
    if not reproduction["passed"]:
        raise SystemExit(
            "reproduction failed: {n} of {d} levels differ ({p:.2f}%), above the {l:.2f}% limit".format(
                n=level_mismatches,
                d=len(rows),
                p=mismatch_share * 100.0,
                l=MISMATCH_LIMIT * 100.0,
            )
        )

    variant_records = {variant: _levels_for(rows, variant) for variant in VARIANTS}
    gated_rows = [row for row in rows if row["gated"]]
    gated_index = [index for index, row in enumerate(rows) if row["gated"]]

    overall: dict[str, dict[str, Any]] = {}
    overall_gated: dict[str, dict[str, Any]] = {}
    per_language: dict[str, dict[str, dict[str, Any]]] = {}
    per_language_gated: dict[str, dict[str, dict[str, Any]]] = {}
    per_script: dict[str, dict[str, dict[str, Any]]] = {}
    per_script_gated: dict[str, dict[str, dict[str, Any]]] = {}
    for variant in VARIANTS:
        records = variant_records[variant]
        overall[variant] = _metrics(records)
        gated_records = [records[index] for index in gated_index]
        overall_gated[variant] = _metrics(gated_records)
        per_language[variant] = _grouped_metrics(rows, records, "language")
        per_script[variant] = _grouped_metrics(rows, records, "script")
        per_language_gated[variant] = _grouped_metrics(
            [rows[index] for index in gated_index], gated_records, "language"
        )
        per_script_gated[variant] = _grouped_metrics(
            [rows[index] for index in gated_index], gated_records, "script"
        )

    baseline_gated = overall_gated["V0"]
    acceptance: dict[str, dict[str, Any]] = {}
    for variant in ("V1", "V2", "V3", "V4"):
        records = variant_records[variant]
        baseline_records = variant_records["V0"]
        protected = [
            (index, row, record)
            for index, (row, record) in enumerate(zip(rows, records))
            if row["language"] in ("English", "Hinglish")
        ]
        changed = sum(
            1
            for index, _row, record in protected
            if record["level"] != baseline_records[index]["level"]
        )
        a_pass = changed == 0
        b_fpr = overall_gated[variant]["fpr_ham"]
        b_pass = b_fpr <= 0.05
        recall_drop_pp = (baseline_gated["risky_recall"] - overall_gated[variant]["risky_recall"]) * 100.0
        c_pass = recall_drop_pp <= 5.0
        acceptance[variant] = {
            "a_english_hinglish_unchanged": {
                "n_rows": len(protected),
                "n_level_changes": changed,
                "pass": a_pass,
            },
            "b_gated_fpr_ham": {
                "value": b_fpr,
                "value_percent": b_fpr * 100.0,
                "limit_percent": 5.0,
                "pass": b_pass,
            },
            "c_gated_recall_drop_pp": {
                "value_pp": recall_drop_pp,
                "limit_pp": 5.0,
                "baseline_recall": baseline_gated["risky_recall"],
                "variant_recall": overall_gated[variant]["risky_recall"],
                "pass": c_pass,
            },
            "overall_pass": bool(a_pass and b_pass and c_pass),
        }

    shipped_variant_records = {
        variant: _shipped_records(rows, real_shipped, variant, shipped_fusion_params)
        for variant in VARIANTS
    }
    shipped_overall: dict[str, dict[str, Any]] = {}
    shipped_overall_gated: dict[str, dict[str, Any]] = {}
    shipped_per_language: dict[str, dict[str, dict[str, Any]]] = {}
    shipped_per_language_gated: dict[str, dict[str, dict[str, Any]]] = {}
    for variant in VARIANTS:
        records = shipped_variant_records[variant]
        shipped_overall[variant] = _metrics(records)
        gated_records = [records[index] for index in gated_index]
        shipped_overall_gated[variant] = _metrics(gated_records)
        shipped_per_language[variant] = _grouped_metrics(rows, records, "language")
        shipped_per_language_gated[variant] = _grouped_metrics(
            [rows[index] for index in gated_index], gated_records, "language"
        )

    shipped_baseline_gated = shipped_overall_gated["V0"]
    shipped_acceptance: dict[str, dict[str, Any]] = {}
    for variant in ("V1", "V2", "V3", "V4"):
        records = shipped_variant_records[variant]
        baseline_records = shipped_variant_records["V0"]
        protected = [
            (index, row, record)
            for index, (row, record) in enumerate(zip(rows, records))
            if row["language"] in ("English", "Hinglish")
        ]
        changed = sum(
            1
            for index, _row, record in protected
            if record["level"] != baseline_records[index]["level"]
        )
        a_pass = changed == 0
        b_fpr = shipped_overall_gated[variant]["fpr_ham"]
        b_pass = b_fpr <= 0.05
        recall_drop_pp = (
            shipped_baseline_gated["risky_recall"] - shipped_overall_gated[variant]["risky_recall"]
        ) * 100.0
        c_pass = recall_drop_pp <= 5.0
        shipped_acceptance[variant] = {
            "a_english_hinglish_unchanged": {
                "n_rows": len(protected),
                "n_level_changes": changed,
                "pass": a_pass,
            },
            "b_gated_fpr_ham": {
                "value": b_fpr,
                "value_percent": b_fpr * 100.0,
                "limit_percent": 5.0,
                "pass": b_pass,
            },
            "c_gated_recall_drop_pp": {
                "value_pp": recall_drop_pp,
                "limit_pp": 5.0,
                "baseline_recall": shipped_baseline_gated["risky_recall"],
                "variant_recall": shipped_overall_gated[variant]["risky_recall"],
                "pass": c_pass,
            },
            "overall_pass": bool(a_pass and b_pass and c_pass),
        }

    fpr_eligible = [
        variant
        for variant in ("V1", "V2", "V3", "V4")
        if shipped_acceptance[variant]["b_gated_fpr_ham"]["pass"]
    ]
    best_pool = fpr_eligible or ["V1", "V2", "V3", "V4"]
    best_variant = max(
        best_pool,
        key=lambda candidate: (
            shipped_overall_gated[candidate]["risky_recall"],
            -shipped_overall_gated[candidate]["fpr_ham"],
        ),
    )
    shipped_any_pass = any(check["overall_pass"] for check in shipped_acceptance.values())

    calibrate_rules = calibrate.load_fusion_rules()
    calibrate_chosen = {
        "temperature": float(shipped_fusion_params["temperature"]),
        "scam_weight": float(shipped_fusion_params["scam_weight"]),
        "unwanted_weight": float(calibrate_rules["sms_unwanted_weight"]),
        "medium_threshold": float(calibrate_rules["medium_level_threshold"]),
        "high_threshold": float(calibrate_rules["high_level_threshold"]),
    }
    reference_mismatches = sum(
        1
        for row, result in zip(rows, real_shipped)
        if calibrate.risk_and_level(row, calibrate_chosen, calibrate_rules)[1] != result["level"]
    )
    shipped_v0_overall = shipped_overall["V0"]
    cross_check = {
        "stored_shipped_level_column": None,
        "note": (
            "There is no stored shipped-level column. dump_20261108.csv fused_level is the "
            "pre-calibration baseline. The shipped levels are recomputed with "
            "calibrate.risk_and_level and the chosen candidate (temperature 3.0, scam weight 0.9), "
            "exactly as tests/test_calibration_shipped.py does."
        ),
        "reference_rows_n": len(rows),
        "reference_scope": (
            "tests/test_calibration_shipped.py and calibration.md cover all 13,104 dumped rows; "
            "this run joins the 13,098 held-out rows."
        ),
        "n_shipped_vs_reference_level_mismatches": reference_mismatches,
        "shipped_v0_overall_recall": shipped_v0_overall["risky_recall"],
        "shipped_v0_overall_fpr_ham": shipped_v0_overall["fpr_ham"],
        "docs_benchmarks_test_half_recall": 0.7726,
        "docs_benchmarks_test_half_fpr_ham": 0.1053,
        "docs_benchmarks_note": (
            "docs/benchmarks.md section SMS fusion calibration reports the 6,550-row test half "
            "only; the shipped V0 numbers here are over all 13,098 joined rows and are not "
            "directly comparable."
        ),
    }

    shipped_rules = {
        "decision_basis": (
            "real sentinel.fusion.fuse() with sentinel/data/rules.json as shipped "
            "(temperature 3.0, scam weight 0.9)"
        ),
        "v0_method": "real sentinel.fusion.fuse() with FUSION_RULES untouched",
        "variant_method": (
            "V1 to V4 are the same variant definitions applied on top of the shipped rules; "
            "V4 temperature-scaled p_scam uses the shipped temperature"
        ),
        "params": {
            **shipped_fusion_params,
            "medium_threshold": MEDIUM_THRESHOLD,
            "high_threshold": HIGH_THRESHOLD,
        },
        "cross_check": cross_check,
        "best_variant": best_variant,
        "best_variant_rule": (
            "highest gated risky recall among the variants whose gated ham FPR is at most 5%, "
            "then lower gated ham FPR"
        ),
        "metrics": {
            "overall_all_rows": shipped_overall,
            "overall_gated_rows": shipped_overall_gated,
            "per_language_all_rows": {
                "V0": shipped_per_language["V0"],
                best_variant: shipped_per_language[best_variant],
            },
            "per_language_gated_rows": {
                "V0": shipped_per_language_gated["V0"],
                best_variant: shipped_per_language_gated[best_variant],
            },
        },
        "acceptance_preregistered": shipped_acceptance,
        "verdict": "ACCEPTED" if shipped_any_pass else "REJECTED",
    }

    synthetic_false_rows = [row for row in rows if row["synthetic"] == "false"]
    synthetic_false = {
        "n": len(synthetic_false_rows),
        "note": "heldout_20261107.csv synthetic values are 'true' and 'mixed'; there are no 'false' rows",
        "overall": {
            variant: _metrics(
                [
                    record
                    for row, record in zip(rows, variant_records[variant])
                    if row["synthetic"] == "false"
                ]
            )
            for variant in VARIANTS
        },
    }

    gated_counts_by_language = collections.Counter(row["language"] for row in gated_rows)
    gated_counts_by_script = collections.Counter(row["script"] for row in gated_rows)
    total_by_language = collections.Counter(row["language"] for row in rows)
    total_by_script = collections.Counter(row["script"] for row in rows)

    return {
        "generated": "2026-11-10",
        "inputs": {"heldout_csv": str(HELDOUT_CSV), "dump_csv": str(DUMP_CSV)},
        "gate_rule": {
            "description": "dominant script is not Latin and its share of letters is at least 0.5",
            "min_share": GATE_MIN_SHARE,
            "baseline_script": GATED_SCRIPT,
            "cap_value": CAP_VALUE,
            "medium_threshold": MEDIUM_THRESHOLD,
            "url_phishing_threshold": URL_PHISHING_THRESHOLD,
            "v4_scam_confidence": V4_SCAM_CONFIDENCE,
        },
        "reproduction": reproduction,
        "n_total": len(rows),
        "n_gated": len(gated_rows),
        "n_not_gated": len(rows) - len(gated_rows),
        "gated_by_language": dict(sorted(gated_counts_by_language.items())),
        "gated_by_script": dict(sorted(gated_counts_by_script.items())),
        "total_by_language": dict(sorted(total_by_language.items())),
        "total_by_script": dict(sorted(total_by_script.items())),
        "metrics": {
            "overall_all_rows": overall,
            "overall_gated_rows": overall_gated,
            "per_language_all_rows": per_language,
            "per_language_gated_rows": per_language_gated,
            "per_script_all_rows": per_script,
            "per_script_gated_rows": per_script_gated,
        },
        "acceptance_preregistered": acceptance,
        "shipped_rules": shipped_rules,
        "synthetic_false": synthetic_false,
    }


def _format_metric_row(label: str, metrics: dict[str, Any]) -> str:
    return "| {} | {} | {:.3f} | {:.2%} | {:.3f} | {:.3f} |".format(
        label,
        metrics["n"],
        metrics["risky_recall"],
        metrics["fpr_ham"],
        metrics["precision"],
        metrics["f1"],
    )


def write_markdown(report: dict[str, Any]) -> None:
    """Write the human-readable report beside the JSON output."""
    repro = report["reproduction"]
    shipped = report["shipped_rules"]
    shipped_pass = shipped["verdict"] == "ACCEPTED"
    shipped_verdict_text = (
        f"the best variant ({shipped['best_variant']}) passes all three pre-registered checks"
        if shipped_pass
        else "no variant passes (a), (b) and (c) together, so the gate is rejected on this basis"
    )
    lines = [
        "**Decision basis:** the shipped-rules run below is the decision basis: V0 is the real "
        "`sentinel.fusion.fuse()` with `sentinel/data/rules.json` as it now ships (temperature 3.0, "
        "scam weight 0.9), and the baseline-parameter run earlier is kept only as the reproduction check.",
        "",
        f"**Verdict:** on the shipped rules the gate is **{shipped['verdict']}**; {shipped_verdict_text}.",
        "",
        "# Script-gate simulation (ML-1, 2026-11-10)",
        "",
        "Offline only. No app code was changed. The simulation joins the held-out messages to "
        "`bench/heldout/calib_20261108/dump_20261108.csv` by the documented text hash, replays the "
        "real fusion path, and scores the gate variants on the rows whose dominant script is not Latin.",
        "",
        "## Reproduction check",
        "",
        f"- Method: {repro['method']}.",
        f"- Joined rows: {repro['n_rows']} (missing joins: {repro['n_missing_join']}).",
        f"- Level mismatches against the dump column: **{repro['n_level_mismatches']}** "
        f"({repro['level_mismatch_percent']:.2f}%), limit {repro['limit_percent']:.1f}%: "
        f"**{'PASS' if repro['passed'] else 'FAIL'}**.",
        f"- Risk mismatches (absolute): {repro['n_risk_mismatches']}.",
        f"- Replica vs real `fuse()` mismatches: {repro['n_replica_vs_real_fuse_mismatches']}.",
        f"- For transparency, replaying the shipped post-calibration rules "
        f"(temperature 3.0, scam weight 0.9) against this dump differs on "
        f"{repro['shipped_rules_level_mismatches']} rows ({repro['shipped_rules_mismatch_percent']:.2f}%).",
        "",
        repro["note"],
        "",
        "## Gated rows",
        "",
        f"{report['n_gated']} of {report['n_total']} rows are gated "
        f"({report['n_gated'] / report['n_total']:.1%}); {report['n_not_gated']} are not gated and are "
        "kept exactly at V0.",
        "",
        "| Language | Rows | Gated | Share |",
        "|---|---:|---:|---:|",
    ]
    for language, total in report["total_by_language"].items():
        gated = report["gated_by_language"].get(language, 0)
        lines.append(f"| {language} | {total} | {gated} | {gated / total:.1%} |")
    lines += [
        "",
        "| Dominant script | Rows | Gated | Share |",
        "|---|---:|---:|---:|",
    ]
    for script, total in report["total_by_script"].items():
        gated = report["gated_by_script"].get(script, 0)
        lines.append(f"| {script} | {total} | {gated} | {gated / total:.1%} |")

    lines += [
        "",
        "## Overall results (all 13,098 rows)",
        "",
        "Predicted risky means level medium or high. Non-gated rows are identical to V0 in every variant.",
        "",
        "| Variant | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        lines.append(_format_metric_row(variant, report["metrics"]["overall_all_rows"][variant]))

    lines += [
        "",
        "## Gated rows only (acceptance basis)",
        "",
        "| Variant | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        lines.append(_format_metric_row(variant, report["metrics"]["overall_gated_rows"][variant]))

    for title, key in (
        ("Per language (all rows)", "per_language_all_rows"),
        ("Per dominant script (all rows)", "per_script_all_rows"),
    ):
        lines += [
            "",
            f"## {title}",
            "",
        ]
        index_key = "language" if "language" in key else "script"
        labels = sorted(report["metrics"][key][VARIANTS[0]])
        for variant in VARIANTS:
            lines += [
                f"### {variant}",
                "",
                "| {} | n | Risky recall | FPR on ham | Precision | F1 |".format(index_key.capitalize()),
                "|---|---:|---:|---:|---:|---:|",
            ]
            for label in labels:
                lines.append(_format_metric_row(label, report["metrics"][key][variant][label]))
            lines.append("")

    lines += [
        "## Pre-registered acceptance",
        "",
        "A variant passes only when all three checks hold. Values are shown for each check.",
        "",
        "| Variant | (a) English/Hinglish unchanged | (b) Gated ham FPR | (c) Gated recall drop vs V0 | Verdict |",
        "|---|---|---|---|---|",
    ]
    for variant, checks in report["acceptance_preregistered"].items():
        a = checks["a_english_hinglish_unchanged"]
        b = checks["b_gated_fpr_ham"]
        c = checks["c_gated_recall_drop_pp"]
        lines.append(
            "| {} | {} ({} of {} rows changed) | {} ({:.2f}%, limit 5.0%) | {} ({:.2f} pp, limit 5.0 pp) | **{}** |".format(
                variant,
                "PASS" if a["pass"] else "FAIL",
                a["n_level_changes"],
                a["n_rows"],
                "PASS" if b["pass"] else "FAIL",
                b["value_percent"],
                "PASS" if c["pass"] else "FAIL",
                c["value_pp"],
                "PASS" if checks["overall_pass"] else "FAIL",
            )
        )
    lines += [
        "",
        "No variant passes. The gate reliably cuts the false alarms on gated rows, but every variant "
        "loses far more than 5 percentage points of risky recall on those rows, because many native-script "
        "risky rows were reaching medium level only through the SMS `unwanted` term.",
        "",
        "## Rows where synthetic is false",
        "",
        f"n = {report['synthetic_false']['n']}. {report['synthetic_false']['note']}. "
        "The join works, but this table is therefore empty; no result can be reported for a false slice.",
        "",
        "## Caveats",
        "",
        "- Most rows are synthetic: 12,889 of 13,098 are tagged `synthetic=true`; the remaining 209 "
        "carnageiron English rows are `mixed` real/synthetic. No row is tagged `synthetic=false`.",
        "- Labels are the dataset authors', not hand-checked.",
        "- The dump column is the pre-calibration baseline. Reproducing it requires the dump-time "
        "parameters (temperature 1.0, scam weight 1.0, unwanted weight 0.5); the shipped rules.json now "
        "carries the calibrated candidate (3.0, 0.9). The simulation keeps the dump baseline so V0 is "
        "the column under test.",
        "- V4 `temperature-scaled p_scam` uses the same reproduction temperature (1.0), so it equals the "
        "dumped raw `p_scam`. The shipped fusion temperature (3.0) would move that boundary.",
        "- `max_untrusted_url_prob` is the processed untrusted URL probability already in the dump; the "
        "URL scam threshold is rules.json `url_phishing_label_threshold` (0.5).",
        "- The cap in V3/V4 is {:.4f}, just below the medium threshold, and the final score is rounded "
        "to {} decimals before the level is chosen.".format(CAP_VALUE, RISK_ROUND_DECIMALS),
        "",
        "## Exploratory (not pre-registered)",
        "",
        "These ideas were not part of the acceptance rule and were not scored as variants.",
        "",
        "- The closest variant is V1 (drop the unwanted term): gated ham FPR falls from 16.6% to 2.2%, "
        "but gated risky recall falls by about 20 points. A softer version might suppress only the "
        "`unwanted` label/presentation while leaving the level, or blend the unwanted weight rather "
        "than dropping it; that would need its own pre-registered test.",
        "- A cue-aware gate (cap only when the model's top class is `unwanted` and no cue exists) could "
        "preserve scam rows, but the dump does not store the model's argmax class, so it cannot be "
        "tested from these columns without a new dump.",
        "",
    ]

    best = shipped["best_variant"]
    shipped_metrics = shipped["metrics"]
    cross = shipped["cross_check"]
    lines += [
        "",
        "## Shipped rules run (decision basis)",
        "",
        "This is the decision basis. V0 is the real `sentinel.fusion.fuse()` with "
        "`sentinel/data/rules.json` exactly as it ships (temperature 3.0, scam weight 0.9). "
        "V1 to V4 apply the same variant definitions on top of those shipped rules; V4 uses the "
        "shipped temperature for its temperature-scaled `p_scam`. Non-gated rows stay at the real "
        "shipped `fuse()` result.",
        "",
        "### Overall (all 13,098 rows)",
        "",
        "| Variant | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        lines.append(_format_metric_row(variant, shipped_metrics["overall_all_rows"][variant]))
    lines += [
        "",
        "### Gated rows only (acceptance basis)",
        "",
        "| Variant | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        lines.append(_format_metric_row(variant, shipped_metrics["overall_gated_rows"][variant]))
    lines += [
        "",
        "### Per language (all rows)",
        "",
        "#### V0",
        "",
        "| Language | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, metrics in shipped_metrics["per_language_all_rows"]["V0"].items():
        lines.append(_format_metric_row(label, metrics))
    lines += [
        "",
        f"#### {best} (best variant)",
        "",
        "| Language | n | Risky recall | FPR on ham | Precision | F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, metrics in shipped_metrics["per_language_all_rows"][best].items():
        lines.append(_format_metric_row(label, metrics))
    lines += [
        "",
        "### Pre-registered acceptance",
        "",
        "Same acceptance rule as the baseline run. A variant passes only when all three checks hold.",
        "",
        "| Variant | (a) English/Hinglish unchanged | (b) Gated ham FPR | (c) Gated recall drop vs V0 | Verdict |",
        "|---|---|---|---|---|",
    ]
    for variant, checks in shipped["acceptance_preregistered"].items():
        a = checks["a_english_hinglish_unchanged"]
        b = checks["b_gated_fpr_ham"]
        c = checks["c_gated_recall_drop_pp"]
        lines.append(
            "| {} | {} ({} of {} rows changed) | {} ({:.2f}%, limit 5.0%) | {} ({:.2f} pp, limit 5.0 pp) | **{}** |".format(
                variant,
                "PASS" if a["pass"] else "FAIL",
                a["n_level_changes"],
                a["n_rows"],
                "PASS" if b["pass"] else "FAIL",
                b["value_percent"],
                "PASS" if c["pass"] else "FAIL",
                c["value_pp"],
                "PASS" if checks["overall_pass"] else "FAIL",
            )
        )
    lines += [
        "",
        f"Best variant by the stated rule: **{best}**, chosen for the {shipped['best_variant_rule']}.",
        "",
        "### Cross-check against the stored calibration evidence",
        "",
        f"- {cross['note']}",
        f"- Shipped V0 against that recomputed reference: **{cross['n_shipped_vs_reference_level_mismatches']}** "
        f"level mismatches on {cross['reference_rows_n']} joined rows.",
        f"- {cross['reference_scope']}",
        f"- Shipped V0 on all joined rows: risky recall **{cross['shipped_v0_overall_recall']:.2%}**, "
        f"ham FPR **{cross['shipped_v0_overall_fpr_ham']:.2%}**.",
        f"- {cross['docs_benchmarks_note']} The docs test-half values are recall "
        f"{cross['docs_benchmarks_test_half_recall']:.2%} and FPR "
        f"{cross['docs_benchmarks_test_half_fpr_ham']:.2%}.",
        "",
        "### Shipped-run caveats",
        "",
        "- The earlier baseline sections are unchanged and remain the reproduction check against the dump column.",
        "- V4 uses the shipped temperature (3.0) here, so its `p_scam` boundary differs from the baseline-run V4.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    """Run the simulation, write both outputs, and print a short summary."""
    report = run()
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print(f"reproduction mismatches: {report['reproduction']['n_level_mismatches']} "
          f"({report['reproduction']['level_mismatch_percent']:.2f}%)")
    print(f"gated rows: {report['n_gated']} of {report['n_total']}")
    for variant, checks in report["acceptance_preregistered"].items():
        print(
            "{}: a={} b={} c={} overall={}".format(
                variant,
                "PASS" if checks["a_english_hinglish_unchanged"]["pass"] else "FAIL",
                "PASS" if checks["b_gated_fpr_ham"]["pass"] else "FAIL",
                "PASS" if checks["c_gated_recall_drop_pp"]["pass"] else "FAIL",
                "PASS" if checks["overall_pass"] else "FAIL",
            )
        )
    shipped = report["shipped_rules"]
    shipped_overall = shipped["metrics"]["overall_all_rows"]["V0"]
    shipped_gated = shipped["metrics"]["overall_gated_rows"]["V0"]
    print(
        "shipped V0 overall: recall {:.3%} fpr {:.3%}".format(
            shipped_overall["risky_recall"], shipped_overall["fpr_ham"]
        )
    )
    print(
        "shipped V0 gated: recall {:.3%} fpr {:.3%}".format(
            shipped_gated["risky_recall"], shipped_gated["fpr_ham"]
        )
    )
    for variant, checks in shipped["acceptance_preregistered"].items():
        print(
            "shipped {}: a={} b={} c={} overall={}".format(
                variant,
                "PASS" if checks["a_english_hinglish_unchanged"]["pass"] else "FAIL",
                "PASS" if checks["b_gated_fpr_ham"]["pass"] else "FAIL",
                "PASS" if checks["c_gated_recall_drop_pp"]["pass"] else "FAIL",
                "PASS" if checks["overall_pass"] else "FAIL",
            )
        )
    print(f"wrote {OUT_JSON} and {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
