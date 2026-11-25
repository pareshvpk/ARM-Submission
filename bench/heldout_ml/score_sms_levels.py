"""Level distribution of model arms on the real SMS file (registered business senders).

    python bench/heldout_ml/score_sms_levels.py NAME=MODEL_DIR[,ID_MAP] [NAME=...]

Sender class comes from the DLT header suffix when present: -S service, -T transactional,
-G government count as genuine; -P as promotional; no suffix as unknown. Messages from
registered headers are almost never scams, so HIGH on any of them, and MEDIUM on a genuine one,
is counted as a false alarm. Summary json has counts only; per-row levels go to a git-ignored csv.
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))
from score_arms import TorchSmsDetector  # noqa: E402
from sentinel.pipeline import analyse  # noqa: E402

SRC = ROOT / "bench" / "heldout_ml" / "real_sms.csv"
ROWS_OUT = ROOT / "bench" / "heldout_ml" / "real_sms_levels.csv"
SUMMARY = ROOT / "docs" / "multilang" / "sms_levels_summary.json"


def sender_class(header):
    suffix = header.rsplit("-", 1)[-1] if "-" in header else ""
    return {"S": "genuine", "T": "genuine", "G": "genuine", "P": "promotional"}.get(suffix, "unknown")


def main():
    rows = list(csv.DictReader(open(SRC, encoding="utf-8", newline="")))
    for row in rows:
        row["sender_class"] = sender_class(row["header"])
    summary = {"rows": len(rows), "by_language": dict(Counter(r["language"] for r in rows)),
               "by_sender_class": dict(Counter(r["sender_class"] for r in rows)), "arms": {}}
    names = []
    for spec in sys.argv[1:]:
        name, _, rest = spec.partition("=")
        model_dir, _, id_map = rest.partition(",")
        names.append(name)
        det = TorchSmsDetector(model_dir, id_map or None, "cuda")
        table = defaultdict(Counter)
        for row in rows:
            evidence = analyse(row["text"], sms_det=det)["evidence"]
            row[name] = evidence["level"]
            row[name + "_label"] = evidence["label"]
            row[name + "_risk"] = evidence["risk"]
            for key in ("all", "lang:" + row["language"], "class:" + row["sender_class"],
                        f"lang:{row['language']}|class:{row['sender_class']}"):
                table[key][evidence["level"]] += 1
        summary["arms"][name] = {key: dict(counts) for key, counts in sorted(table.items())}
        print(name, {k: dict(v) for k, v in table.items() if k in ("all", "lang:Tamil", "lang:Latin", "class:genuine", "class:promotional")}, flush=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(ROWS_OUT, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def pct(name, key):
        counts = summary["arms"][name].get(key, {})
        total = sum(counts.values()) or 1
        return f"{100 * counts.get('medium', 0) / total:.1f} / {100 * counts.get('high', 0) / total:.1f}", total

    print("\n| Slice | n | " + " | ".join(f"{n}: % medium / % high" for n in names) + " |")
    for key in ("all", "lang:Latin", "lang:Tamil", "class:genuine", "class:promotional", "class:unknown",
                "lang:Tamil|class:genuine", "lang:Latin|class:genuine"):
        cells = [pct(n, key) for n in names]
        print(f"| {key} | {cells[0][1]} | " + " | ".join(c[0] for c in cells) + " |")


if __name__ == "__main__":
    main()
