from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
RULES_FILE = ROOT_DIR / "sentinel" / "data" / "rules.json"
SEED = 20261108

BASELINE_PARAMS: dict[str, float] = {
    "temperature": 1.0,
    "scam_weight": 1.0,
    "unwanted_weight": 0.5,
    "medium_threshold": 0.4,
    "high_threshold": 0.7,
}

TEMPERATURES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
SCAM_WEIGHTS = (0.8, 0.9, 1.0, 1.1, 1.2)
UNWANTED_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
MEDIUM_THRESHOLDS = (0.35, 0.4, 0.45, 0.5)
HIGH_THRESHOLDS = (0.6, 0.7, 0.8, 0.9)

ACCEPTANCE = {
    "max_risky_recall_drop_pp": 1.0,
    "max_ham_fpr_increase": 0.0,
    "shoe_store_promotion_must_not_be_high": True,
}


def load_fusion_rules() -> dict[str, float]:
    data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    root = data.get("root", data)
    fusion = root["fusion"]
    keys = [
        "sms_unwanted_weight",
        "url_weight",
        "cue_weight",
        "cue_cap",
        "combo_score",
        "app_install_score",
        "collect_pin_score",
        "high_level_threshold",
        "medium_level_threshold",
        "sms_ham_confidence_threshold",
        "risk_round_decimals",
    ]
    return {k: fusion[k] for k in keys}


def parse_cue_types(value: str) -> set[str]:
    return {part.strip() for part in (value or "").split(";") if part.strip()}


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes")


def read_dump(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    skipped = 0
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            p_ham = _parse_prob(row.get("p_ham"))
            p_unwanted = _parse_prob(row.get("p_unwanted"))
            p_scam = _parse_prob(row.get("p_scam"))
            if p_ham is None or p_unwanted is None or p_scam is None:
                skipped += 1
                continue
            rows.append(
                {
                    "text_hash": str(row.get("text_hash", "") or ""),
                    "source": str(row.get("source", "") or ""),
                    "language": str(row.get("language", "") or ""),
                    "truth": str(row.get("truth", "") or "").strip().lower(),
                    "p_ham": p_ham,
                    "p_unwanted": p_unwanted,
                    "p_scam": p_scam,
                    "fused_label": str(row.get("fused_label", "") or ""),
                    "fused_level": str(row.get("fused_level", "") or "").strip().lower(),
                    "fused_risk": float(row.get("fused_risk") or 0.0),
                    "cue_types": parse_cue_types(str(row.get("cue_types", "") or "")),
                    "num_urls": int(float(row.get("num_urls") or 0)),
                    "max_untrusted_url_prob": float(row.get("max_untrusted_url_prob") or 0.0),
                    "indicators": str(row.get("indicators", "") or ""),
                    "collect_pin": parse_bool(row.get("collect_pin")),
                    "shoe_store_promotion": parse_bool(row.get("shoe_store_promotion")),
                }
            )
    if skipped:
        print(
            f"read_dump: skipped {skipped} row(s) with missing or non-finite probabilities",
            file=sys.stderr,
        )
    return rows


def _parse_prob(value: object) -> float | None:
    """Return a finite float for *value*, or None if missing/non-finite."""
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def split_rows(rows: list[dict], seed: int = SEED):
    labelled = [r for r in rows if r["truth"] in ("ham", "risky")]
    extra = [r for r in rows if r["truth"] not in ("ham", "risky")]
    strata: dict[tuple[str, str], list[dict]] = {}
    for row in labelled:
        strata.setdefault((row["source"], row["language"]), []).append(row)
    rng = random.Random(seed)
    calibration: list[dict] = []
    test: list[dict] = []
    for key in sorted(strata):
        group = list(strata[key])
        rng.shuffle(group)
        half = len(group) // 2
        calibration.extend(group[:half])
        test.extend(group[half:])
    return calibration, test, extra


def apply_temperature(probs: tuple[float, float, float], temperature: float) -> tuple[float, float, float]:
    if temperature == 1.0:
        return probs
    logs = [math.log(p) if p > 0.0 else -math.inf for p in probs]
    # All-zero probs carry no information; returning them as-is avoids nan
    # (log(0) = -inf, exp(-inf - -inf) = nan, and nan <= 0.0 is False).
    if all(lg == -math.inf for lg in logs):
        return probs
    top = max(logs) / temperature
    weights = [math.exp((lg / temperature) - top) if math.isfinite(lg) else 0.0 for lg in logs]
    total = sum(weights)
    if total <= 0.0:
        return probs
    n = tuple(w / total for w in weights)
    return (n[0], n[1], n[2])

def risk_and_level(row: dict, params: dict[str, float], rules: dict[str, float]) -> tuple[float, str]:
    p_ham, p_unwanted, p_scam = apply_temperature(
        (row["p_ham"], row["p_unwanted"], row["p_scam"]), float(params["temperature"])
    )
    sms_score = float(params["scam_weight"]) * p_scam + float(params["unwanted_weight"]) * p_unwanted
    url_score = row["max_untrusted_url_prob"] * float(rules["url_weight"])
    cues_score = min(float(rules["cue_cap"]), float(rules["cue_weight"]) * len(row["cue_types"]))
    combos = "urgency" in row["cue_types"] and bool(
        row["cue_types"] & {"threat", "credential_request", "payment_request"}
    )
    confident_ham = p_ham >= float(rules["sms_ham_confidence_threshold"])
    combo_score = float(rules["combo_score"]) if (combos and not confident_ham) else 0.0
    app_install_score = float(rules["app_install_score"]) if "app_install" in row["cue_types"] else 0.0
    collect_pin_score = float(rules["collect_pin_score"]) if row["collect_pin"] else 0.0
    risk = max(sms_score, url_score, cues_score, combo_score, app_install_score, collect_pin_score)
    risk = round(min(1.0, max(0.0, risk)), int(rules["risk_round_decimals"]))
    high_thr = float(params["high_threshold"])
    medium_thr = float(params["medium_threshold"])
    if risk >= high_thr:
        level = "high"
    elif risk >= medium_thr:
        level = "medium"
    else:
        level = "low"
    return risk, level


def prepare_rows(rows: list[dict], rules: dict[str, float]) -> list[dict]:
    """Precompute per-row parts that do not depend on the fitted candidate."""
    prepared: list[dict] = []
    for row in rows:
        probs = (row["p_ham"], row["p_unwanted"], row["p_scam"])
        temp_probs = {t: apply_temperature(probs, t) for t in TEMPERATURES}
        cues = row["cue_types"]
        combos = "urgency" in cues and bool(cues & {"threat", "credential_request", "payment_request"})
        prepared.append(
            {
                "truth": row["truth"],
                "language": row["language"],
                "shoe": row["shoe_store_promotion"],
                "temp_probs": temp_probs,
                "combos": combos,
                "static_max": max(
                    row["max_untrusted_url_prob"] * float(rules["url_weight"]),
                    min(float(rules["cue_cap"]), float(rules["cue_weight"]) * len(cues)),
                    float(rules["app_install_score"]) if "app_install" in cues else 0.0,
                    float(rules["collect_pin_score"]) if row["collect_pin"] else 0.0,
                ),
            }
        )
    return prepared


def risk_and_level_prepared(prep: dict, params: dict[str, float], rules: dict[str, float]) -> tuple[float, str]:
    p_ham, p_unwanted, p_scam = prep["temp_probs"][float(params["temperature"])]
    sms_score = float(params["scam_weight"]) * p_scam + float(params["unwanted_weight"]) * p_unwanted
    confident_ham = p_ham >= float(rules["sms_ham_confidence_threshold"])
    combo_score = float(rules["combo_score"]) if (prep["combos"] and not confident_ham) else 0.0
    risk = max(sms_score, prep["static_max"], combo_score)
    risk = round(min(1.0, max(0.0, risk)), int(rules["risk_round_decimals"]))
    if risk >= float(params["high_threshold"]):
        return risk, "high"
    if risk >= float(params["medium_threshold"]):
        return risk, "medium"
    return risk, "low"


def metrics_prepared(preprepared: list[dict], params: dict[str, float], rules: dict[str, float]) -> dict:
    tp = fn = fp = tn = 0
    for prep in preprepared:
        _risk, level = risk_and_level_prepared(prep, params, rules)
        risky = level in ("medium", "high")
        if prep["truth"] == "risky" and risky:
            tp += 1
        elif prep["truth"] == "risky":
            fn += 1
        elif prep["truth"] == "ham" and risky:
            fp += 1
        elif prep["truth"] == "ham":
            tn += 1
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"n": len(preprepared), "risky_recall": recall, "ham_fpr": fpr, "tp": tp, "fn": fn, "fp": fp, "tn": tn}


def assert_baseline_reproduced(rows: list[dict], rules: dict[str, float]) -> None:
    params = dict(BASELINE_PARAMS)
    params["unwanted_weight"] = float(rules["sms_unwanted_weight"])
    params["medium_threshold"] = float(rules["medium_level_threshold"])
    params["high_threshold"] = float(rules["high_level_threshold"])
    mismatches: list[dict] = []
    for index, row in enumerate(rows):
        _risk, level = risk_and_level(row, params, rules)
        if level != row["fused_level"]:
            mismatches.append(
                {"row": index, "text_hash": row["text_hash"], "dumped": row["fused_level"], "reproduced": level}
            )
    if mismatches:
        shown = mismatches[:10]
        raise SystemExit(f"FAIL: baseline fusion not reproduced on {len(mismatches)} row(s); first: {shown}")


def metrics(rows: list[dict], params: dict[str, float], rules: dict[str, float]) -> dict:
    tp = fn = fp = tn = 0
    for row in rows:
        _risk, level = risk_and_level(row, params, rules)
        risky = level in ("medium", "high")
        if row["truth"] == "risky" and risky:
            tp += 1
        elif row["truth"] == "risky":
            fn += 1
        elif row["truth"] == "ham" and risky:
            fp += 1
        elif row["truth"] == "ham":
            tn += 1
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"n": len(rows), "risky_recall": recall, "ham_fpr": fpr, "tp": tp, "fn": fn, "fp": fp, "tn": tn}


def per_language_metrics(rows: list[dict], params: dict[str, float], rules: dict[str, float]) -> dict:
    by_lang: dict[str, list[dict]] = {}
    for row in rows:
        by_lang.setdefault(row["language"], []).append(row)
    return {lang: metrics(group, params, rules) for lang, group in sorted(by_lang.items())}


def per_language_metrics_prepared(preprepared: list[dict], params: dict[str, float], rules: dict[str, float]) -> dict:
    by_lang: dict[str, list[dict]] = {}
    for prep in preprepared:
        by_lang.setdefault(prep["language"], []).append(prep)
    return {lang: metrics_prepared(group, params, rules) for lang, group in sorted(by_lang.items())}


def extra_levels(extra: list[dict], params: dict[str, float], rules: dict[str, float]) -> list[dict]:
    out = []
    for row in extra:
        out.append({"text_hash": row["text_hash"], "level": risk_and_level(row, params, rules)[1]})
    return out


def acceptance_passes(
    baseline: dict, candidate: dict, shoe_levels: list[str]
) -> tuple[bool, dict]:
    recall_drop_pp = (baseline["risky_recall"] - candidate["risky_recall"]) * 100.0
    fpr_ok = candidate["ham_fpr"] <= baseline["ham_fpr"] + ACCEPTANCE["max_ham_fpr_increase"]
    recall_ok = recall_drop_pp <= ACCEPTANCE["max_risky_recall_drop_pp"]
    shoe_ok = all(level != "high" for level in shoe_levels) if shoe_levels else True
    checks = {
        "risky_recall_drop_pp": recall_drop_pp,
        "recall_ok": recall_ok,
        "ham_fpr_delta": candidate["ham_fpr"] - baseline["ham_fpr"],
        "fpr_ok": fpr_ok,
        "shoe_store_not_high": shoe_ok,
    }
    return bool(recall_ok and fpr_ok and shoe_ok), checks


def candidate_grid() -> list[dict[str, float]]:
    grid: list[dict[str, float]] = []
    for temperature in TEMPERATURES:
        for scam_weight in SCAM_WEIGHTS:
            for unwanted_weight in UNWANTED_WEIGHTS:
                for medium in MEDIUM_THRESHOLDS:
                    for high in HIGH_THRESHOLDS:
                        if high <= medium:
                            continue
                        grid.append(
                            {
                                "temperature": temperature,
                                "scam_weight": scam_weight,
                                "unwanted_weight": unwanted_weight,
                                "medium_threshold": medium,
                                "high_threshold": high,
                            }
                        )
    return grid


def choose_candidate(calibration: list[dict], extra: list[dict], rules: dict[str, float]):
    baseline_params = dict(BASELINE_PARAMS)
    baseline_params["unwanted_weight"] = float(rules["sms_unwanted_weight"])
    baseline_params["medium_threshold"] = float(rules["medium_level_threshold"])
    baseline_params["high_threshold"] = float(rules["high_level_threshold"])
    cal_prep = prepare_rows(calibration, rules)
    extra_prep = prepare_rows(extra, rules)
    base_cal = metrics_prepared(cal_prep, baseline_params, rules)
    shoe_prep = [p for p in extra_prep if p["shoe"]]
    best: dict | None = None
    best_key: tuple | None = None
    for params in candidate_grid():
        cand = metrics_prepared(cal_prep, params, rules)
        shoe_levels = [risk_and_level_prepared(p, params, rules)[1] for p in shoe_prep]
        passes, _checks = acceptance_passes(base_cal, cand, shoe_levels)
        if not passes:
            continue
        key = (
            cand["ham_fpr"],
            -cand["risky_recall"],
            abs(params["temperature"] - 1.0),
            abs(params["scam_weight"] - 1.0),
            abs(params["unwanted_weight"] - float(rules["sms_unwanted_weight"])),
            abs(params["medium_threshold"] - float(rules["medium_level_threshold"])),
            abs(params["high_threshold"] - float(rules["high_level_threshold"])),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = {"params": params, "calibration_metrics": cand}
    return baseline_params, base_cal, best


def run(dump_path: str | Path) -> dict:
    rows = read_dump(dump_path)
    rules = load_fusion_rules()
    assert_baseline_reproduced(rows, rules)
    calibration, test, extra = split_rows(rows)
    baseline_params, _base_cal, chosen = choose_candidate(calibration, extra, rules)
    result: dict = {
        "seed": SEED,
        "n_dump_rows": len(rows),
        "n_calibration": len(calibration),
        "n_test": len(test),
        "n_extra": len(extra),
        "acceptance": ACCEPTANCE,
        "baseline_params": baseline_params,
        "chosen": None,
        "chosen_params": None,
        "accepted_test": False,
    }
    test_prep = prepare_rows(test, rules)
    extra_prep = prepare_rows(extra, rules)
    base_test = metrics_prepared(test_prep, baseline_params, rules)
    result["baseline_test"] = base_test
    result["baseline_test_per_language"] = per_language_metrics_prepared(test_prep, baseline_params, rules)
    if chosen is not None:
        params = chosen["params"]
        cand_test = metrics_prepared(test_prep, params, rules)
        shoe_levels_test = [risk_and_level_prepared(p, params, rules)[1] for p in extra_prep if p["shoe"]]
        passes, checks = acceptance_passes(base_test, cand_test, shoe_levels_test)
        result["chosen"] = chosen
        result["chosen_params"] = params
        result["accepted_test"] = passes
        result["test_checks"] = checks
        result["chosen_test"] = cand_test
        result["chosen_test_per_language"] = per_language_metrics_prepared(test_prep, params, rules)
    result["extra_baseline_levels"] = extra_levels(extra, baseline_params, rules)
    result["extra_chosen_levels"] = (
        extra_levels(extra, chosen["params"], rules) if chosen is not None else []
    )
    result["verdict"] = (
        "chosen candidate passes pre-registered acceptance on the test half"
        if chosen is not None and result["accepted_test"]
        else "no candidate passes pre-registered acceptance"
    )
    return result


def write_outputs(result: dict, out_path: str | Path) -> tuple[Path, Path]:
    out = Path(out_path)
    if out.suffix == ".json":
        json_path = out
        md_path = out.with_suffix(".md")
    elif out.suffix == ".md":
        md_path = out
        json_path = out.with_suffix(".json")
    else:
        json_path = out.with_suffix(".json") if out.suffix else Path(str(out) + ".json")
        md_path = out.with_suffix(".md") if out.suffix else Path(str(out) + ".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Calibration result (DT-2)",
        "",
        "Pre-registered acceptance (evaluated on the test half only): risky recall drop <= 1.0 pp vs baseline,",
        "ham FPR not higher than baseline, shoe-store promotion extra not high.",
        "",
        f"- Dump rows: {result['n_dump_rows']} (calibration {result['n_calibration']}, test {result['n_test']}, extra {result['n_extra']})",
        f"- Verdict: {result['verdict']}",
        "",
        "## Baseline (test half)",
        "",
        _metric_line(result["baseline_test"]),
        "",
        "## Chosen candidate (test half)",
        "",
    ]
    if result.get("chosen_params"):
        lines.append(f"Params: {result['chosen_params']}")
        lines.append("")
        lines.append(_metric_line(result["chosen_test"]))
    else:
        lines.append("No candidate passed the acceptance gate on the calibration half.")
    lines += ["", "## Per-language (test half)", "", "Baseline:"]
    for lang, m in result["baseline_test_per_language"].items():
        lines.append(f"- {lang}: recall {m['risky_recall']:.3f}, ham FPR {m['ham_fpr']:.3f} (n={m['n']})")
    if result.get("chosen_params"):
        lines.append("")
        lines.append("Chosen:")
        for lang, m in result["chosen_test_per_language"].items():
            lines.append(f"- {lang}: recall {m['risky_recall']:.3f}, ham FPR {m['ham_fpr']:.3f} (n={m['n']})")
    lines += ["", "## Extra texts (levels before -> after)", ""]
    for before, after in zip(result["extra_baseline_levels"], result["extra_chosen_levels"]):
        lines.append(f"- {before['text_hash'][:12]}: {before['level']} -> {after['level']}")
    if result.get("chosen_params") is None:
        for before in result["extra_baseline_levels"]:
            lines.append(f"- {before['text_hash'][:12]}: {before['level']} (unchanged)")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _metric_line(m: dict) -> str:
    return (
        f"n={m['n']}, risky recall {m['risky_recall']:.4f}, ham FPR {m['ham_fpr']:.4f} "
        f"(tp={m['tp']} fn={m['fn']} fp={m['fp']} tn={m['tn']})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate SMS fusion on a dump_probs CSV (stdlib only)")
    parser.add_argument("dump_csv")
    parser.add_argument("--out", required=True, help="Output path (writes <out>.json and <out>.md)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args.dump_csv)
    json_path, md_path = write_outputs(result, args.out)
    print(json.dumps(result, indent=2))
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
