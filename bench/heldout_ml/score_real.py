"""Score model arms on a CSV of messages through the full pipeline (no URL model, no Llama).

    python bench/heldout_ml/score_real.py CSV NAME=MODEL_DIR[,ID_MAP] [NAME=...] --out PATH_NO_EXT

The CSV needs id, language, truth (ham or risky), text. Output: per-arm level for every row and
counts by language. Message text is never written to the output, only ids.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))
from score_arms import TorchSmsDetector  # noqa: E402
from sentinel.pipeline import analyse  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("arms", nargs="+")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8", newline="")))
    report = {"csv": args.csv, "rows": len(rows), "arms": {}, "per_row": [{"id": r["id"], "language": r["language"], "truth": r["truth"]} for r in rows]}
    for spec in args.arms:
        name, _, rest = spec.partition("=")
        model_dir, _, id_map = rest.partition(",")
        det = TorchSmsDetector(model_dir, id_map or None, "cuda")
        summary = {}
        for row, slot in zip(rows, report["per_row"]):
            result = analyse(row["text"], sms_det=det)
            evidence = result["evidence"]
            probs = det.predict(row["text"])["probs"]
            slot[name] = {"level": evidence["level"], "risk": evidence["risk"], "label": evidence["label"],
                          "p_scam": round(probs["scam"], 3), "p_unwanted": round(probs["unwanted"], 3),
                          "cues": sorted({c["type"] for c in evidence.get("cue_spans", [])}),
                          "urls": [(u.get("trusted"), round(float(u.get("prob", 0)), 2)) for u in evidence.get("urls", [])]}
            lang = summary.setdefault(row["language"], {"n": 0, "correct": 0})
            lang["n"] += 1
            lang["correct"] += (evidence["level"] != "low") == (row["truth"] == "risky")
        report["arms"][name] = summary
        print(name, summary, flush=True)
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    names = list(report["arms"])
    lines = [f"# Scores on {Path(args.csv).name} ({len(rows)} messages)", "",
             "Full pipeline with the shipped rules, URL-indicator fallback, no Llama. Correct = genuine stays low, risky is medium or high.", "",
             "| Language | n | " + " | ".join(f"{n} correct" for n in names) + " |", "|---|---|" + "---|" * len(names)]
    for lang in sorted({r["language"] for r in rows}):
        lines.append(f"| {lang} | {report['arms'][names[0]][lang]['n']} | " + " | ".join(str(report["arms"][n][lang]["correct"]) for n in names) + " |")
    lines += ["", "| id | language | truth | " + " | ".join(names) + " |", "|---|---|---|" + "---|" * len(names)]
    for slot in report["per_row"]:
        lines.append(f"| {slot['id']} | {slot['language']} | {slot['truth']} | " + " | ".join(
            f"{slot[n]['level']} {slot[n]['risk']:.2f} ({slot[n]['label']}; cues {','.join(slot[n]['cues']) or '-'})" for n in names) + " |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
