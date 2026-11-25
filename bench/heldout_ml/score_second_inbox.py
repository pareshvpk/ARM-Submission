"""Score a second real inbox (never used for training or tuning) with the alert policy. Counts only.

    python bench/heldout_ml/score_second_inbox.py real_sms_f14.csv NAME=MODEL_DIR[,ID_MAP] [NAME=...]

A sender header is "seen" when it is in the development half of the first inbox (real_sms.csv),
whose messages were used to fine-tune run 3; every other header is "unseen". A message whose
template (digits masked) also occurs in the first inbox is counted separately as "same_template",
because the two phones belong to one owner and share some senders.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))

import policy_sim  # noqa: E402

ML = ROOT / "bench" / "heldout_ml"


def template(text: str) -> str:
    return re.sub(r"\d+", "0", re.sub(r"\s+", " ", text.lower()))


def main() -> int:
    name = sys.argv[1]
    first = list(csv.DictReader(open(ML / "real_sms.csv", encoding="utf-8", newline="")))
    dev_headers = {r["header"] for r in first if policy_sim.split_of(r["header"]) == "dev"}
    first_templates = {template(r["text"]) for r in first}
    rows = list(csv.DictReader(open(ML / name, encoding="utf-8", newline="")))
    report = {"file": name, "rows": len(rows), "arms": {}}
    for spec in sys.argv[2:]:
        arm, _, rest = spec.partition("=")
        model_dir, _, id_map = rest.partition(",")
        det = policy_sim.TorchSmsDetector(model_dir, id_map or None, "cuda")
        probs = det.probs_batch([r["text"] for r in rows])
        counts = defaultdict(lambda: {"n": 0, "old_policy_alert": 0, "alert": 0, "high": 0})
        for row, p in zip(rows, probs):
            result = policy_sim.verdicts(row["text"], p)
            level, alert = result["policy2"]
            seen = "seen_sender" if row["header"] in dev_headers else "unseen_sender"
            fresh = "same_template" if template(row["text"]) in first_templates else "new_template"
            sender = policy_sim.sender_class(row["header"])
            for key in ("all", sender, seen, fresh, f"{sender}|{fresh}", f"{fresh}|{seen}", f"{sender}|{row['language']}"):
                cell = counts[key]
                cell["n"] += 1
                cell["old_policy_alert"] += result["base"][1]
                cell["alert"] += alert
                cell["high"] += level == "high"
        report["arms"][arm] = {k: dict(v, alert_rate=policy_sim.rate(v["alert"], v["n"]),
                                       high_rate=policy_sim.rate(v["high"], v["n"])) for k, v in sorted(counts.items())}
        print(arm)
        for key, cell in sorted(counts.items()):
            print(f"  {key:34s} n={cell['n']:4d} old-policy alerts={cell['old_policy_alert']:4d} alerts={cell['alert']:4d} high={cell['high']:4d}")
    out = ROOT / "docs" / "multilang" / (Path(name).stem + "_score.json")
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
