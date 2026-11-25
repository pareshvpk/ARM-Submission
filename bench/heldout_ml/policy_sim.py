"""Round 3: score alert policy and warning-clause filter for one or more model arms.

    python bench/heldout_ml/policy_sim.py NAME=MODEL_DIR[,ID_MAP] [NAME=...] --out docs/multilang/round3_sim

Variants per arm:
  base    shipped behaviour: alert when level is medium or high
  policy  new alert policy on the same verdict
  both    warning-clause cue filter applied before fusion, then the new alert policy
Sets: S (real SMS, development and test halves by sender header), H (held-out), G (golden),
R (RBI advisories), phone test messages. Output holds counts only, never message text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))

import dump_probs  # noqa: E402
import sim_script_gate as sim  # noqa: E402
from score_arms import TorchSmsDetector, phone_messages  # noqa: E402
from sentinel import pipeline  # noqa: E402
from alert_policy_round3 import filter_warning_cues, should_alert  # noqa: E402  (round-3 experiment policy, kept beside this script)
from sentinel.detectors import sms_cues  # noqa: E402
from sentinel.fusion import fuse  # noqa: E402

VARIANTS = ("base", "policy", "both", "policy2")
ML = ROOT / "bench" / "heldout_ml"


def split_of(header: str) -> str:
    return "test" if int(hashlib.sha1(header.encode("utf-8")).hexdigest(), 16) % 2 else "dev"


def sender_class(header: str) -> str:
    suffix = header.rsplit("-", 1)[-1] if "-" in header else ""
    return {"S": "genuine", "T": "genuine", "G": "genuine", "P": "promotional"}.get(suffix, "unknown")


def verdicts(text: str, probs: tuple[float, float, float], url_results: list[dict] | None = None) -> dict:
    """Level and alert for the three variants of one message."""
    sms_result = {"probs": {"ham": probs[0], "unwanted": probs[1], "scam": probs[2]},
                  "label": ("ham", "unwanted", "scam")[max(range(3), key=lambda i: probs[i])]}
    if url_results is None:
        url_results = [pipeline._score_url_with_detector(u, None) for u in pipeline._extract_urls_safe(text)]
    has_url = bool(url_results) or bool(pipeline._extract_urls_safe(text))
    raw = sms_cues(text)
    kept = filter_warning_cues(text, raw)
    out = {}
    for name, cues in (("base", raw), ("policy", raw), ("both", kept), ("policy2", raw)):
        evidence = fuse(text, sms_result, url_results, cues)
        untrusted = max((float(u["prob"]) for u in evidence.urls if not u.get("trusted")), default=0.0)
        types = {c["type"] for c in cues}
        if name == "base":
            alert = evidence.level != "low"
        else:
            alert = should_alert(evidence.level, types, has_url, untrusted,
                                 sms_label=sms_result["label"] if name == "policy2" else None)
        out[name] = (evidence.level, alert)
    return out


def rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def score_real(det) -> dict:
    rows = list(csv.DictReader(open(ML / "real_sms.csv", encoding="utf-8", newline="")))
    probs = det.probs_batch([r["text"] for r in rows])
    counts = defaultdict(lambda: defaultdict(lambda: {"n": 0, "alert": 0, "high": 0, "medium": 0}))
    for row, p in zip(rows, probs):
        result = verdicts(row["text"], p)
        keys = [f"{split_of(row['header'])}|all", f"{split_of(row['header'])}|{sender_class(row['header'])}",
                f"{split_of(row['header'])}|{sender_class(row['header'])}|{row['language']}"]
        for variant, (level, alert) in result.items():
            for key in keys:
                cell = counts[variant][key]
                cell["n"] += 1
                cell["alert"] += alert
                cell["high"] += level == "high"
                cell["medium"] += level == "medium"
    return {v: {k: dict(c, alert_rate=rate(c["alert"], c["n"]), high_rate=rate(c["high"], c["n"]))
                for k, c in sorted(cells.items())} for v, cells in counts.items()}


def score_heldout(det) -> dict:
    rows, _missing = sim._load_rows()
    text_by_hash = {dump_probs.compute_text_hash(r["text"]): r["text"]
                    for r in csv.DictReader(open(sim.HELDOUT_CSV, encoding="utf-8", newline=""))}
    texts = [text_by_hash[r["text_hash"]] for r in rows]
    probs = det.probs_batch(texts)
    counts = defaultdict(lambda: defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0}))
    for row, text, p in zip(rows, texts, probs):
        url_results = []
        if row["max_untrusted_url_prob"] > 0:
            url_results = [{"url": "http://example.xyz/login", "prob": row["max_untrusted_url_prob"], "indicators": []}]
        for variant, (_level, alert) in verdicts(text, p, url_results).items():
            for key in ("Overall", row["language"]):
                cell = counts[variant][key]
                cell[("tp" if alert else "fn") if row["truth"] == "risky" else ("fp" if alert else "tn")] += 1
    wanted = ("Overall", "English", "Hinglish", "Tamil", "Hindi")
    return {v: {k: dict(c, recall=rate(c["tp"], c["tp"] + c["fn"]), false_alarms=rate(c["fp"], c["fp"] + c["tn"]))
                for k, c in cells.items() if k in wanted} for v, cells in counts.items()}


def score_small(det) -> dict:
    out = {v: {"golden": {"Tamil": 0, "Hindi": 0}, "R_alerts": 0, "R_n": 0, "phone_ok": 0, "phone_n": 0} for v in VARIANTS}
    golden = list(csv.DictReader(open(ML / "golden_ta_hi.csv", encoding="utf-8", newline="")))
    for row, p in zip(golden, det.probs_batch([r["text"] for r in golden])):
        for variant, (_level, alert) in verdicts(row["text"], p).items():
            out[variant]["golden"][row["language"]] += alert == (row["truth"] == "risky")
    real_path = ML / "real_owner.csv"
    if real_path.exists():
        advisories = list(csv.DictReader(open(real_path, encoding="utf-8", newline="")))
        for row, p in zip(advisories, det.probs_batch([r["text"] for r in advisories])):
            for variant, (_level, alert) in verdicts(row["text"], p).items():
                out[variant]["R_alerts"] += alert
                out[variant]["R_n"] += 1
    phone = phone_messages()
    for (_label, text, expected), p in zip(phone, det.probs_batch([t for _l, t, _e in phone])):
        for variant, (_level, alert) in verdicts(text, p).items():
            out[variant]["phone_ok"] += alert == (expected == "high")
            out[variant]["phone_n"] += 1
    return out


def write_markdown(report: dict, path: Path) -> None:
    lines = ["# Round 3 simulation: alert policy and warning-clause filter", "",
             "Counts only. base = alert on medium or high; policy = new alert policy; both = policy + warning-clause filter.",
             "PC scoring: PyTorch fp32, URL-indicator fallback (no URL model).", ""]
    for arm, data in report["arms"].items():
        lines += [f"## {arm}", "", "| Real SMS slice | n | base: alert / HIGH | policy | both | policy2 |", "|---|---|---|---|---|---|"]
        for key in ("test|genuine", "test|all", "test|promotional", "test|unknown", "test|genuine|Tamil", "dev|genuine", "dev|all"):
            cells = [data["real"][v].get(key) for v in VARIANTS]
            if cells[0]:
                lines.append(f"| {key} | {cells[0]['n']} | " + " | ".join(
                    f"{100 * c['alert_rate']:.1f} % / {100 * c['high_rate']:.1f} %" for c in cells) + " |")
        lines += ["", "| Held-out slice | base: recall / false alarms | policy | both | policy2 |", "|---|---|---|---|---|"]
        for key in ("English", "Hinglish", "Tamil", "Hindi", "Overall"):
            lines.append(f"| {key} | " + " | ".join(
                f"{data['heldout'][v][key]['recall']:.3f} / {100 * data['heldout'][v][key]['false_alarms']:.1f} %" for v in VARIANTS) + " |")
        small = data["small"]
        lines += ["", "| Check | base | policy | both | policy2 |", "|---|---|---|---|---|",
                  "| Golden Tamil / Hindi correct of 60 | " + " | ".join(f"{small[v]['golden']['Tamil']} / {small[v]['golden']['Hindi']}" for v in VARIANTS) + " |",
                  "| RBI advisories alerted | " + " | ".join(f"{small[v]['R_alerts']} of {small[v]['R_n']}" for v in VARIANTS) + " |",
                  "| Phone test messages right | " + " | ".join(f"{small[v]['phone_ok']} of {small[v]['phone_n']}" for v in VARIANTS) + " |", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("arms", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(open(ML / "real_sms.csv", encoding="utf-8", newline="")))
    headers = sorted({r["header"] for r in rows})
    (ML / "real_sms_split.json").write_text(json.dumps({h: split_of(h) for h in headers}, indent=0), encoding="utf-8")
    report: dict = {"real_rows": len(rows), "headers": len(headers), "arms": {}}
    for spec in args.arms:
        name, _, rest = spec.partition("=")
        model_dir, _, id_map = rest.partition(",")
        det = TorchSmsDetector(model_dir, id_map or None, "cuda")
        report["arms"][name] = {"real": score_real(det), "heldout": score_heldout(det), "small": score_small(det)}
        print(name, "done", flush=True)
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    write_markdown(report, out.with_suffix(".md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

