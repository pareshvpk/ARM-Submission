"""Write a sample of flagged real messages (redacted) to a local, git-ignored review file."""
import collections
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sentinel.detectors import sms_cues  # noqa: E402
from sentinel.url_features import extract_urls  # noqa: E402

rows = list(csv.DictReader(open(ROOT / "bench" / "heldout_ml" / "real_sms_levels.csv", encoding="utf-8")))
out = []
genuine = [r for r in rows if r["sender_class"] == "genuine"]
high = [r for r in genuine if r["shipped"] == "high"]
out.append(f"genuine {len(genuine)}, shipped HIGH {len(high)}; headers: {collections.Counter(r['header'] for r in high).most_common(12)}")
out.append(f"labels of HIGH: {dict(collections.Counter(r['shipped_label'] for r in high))}")
cue_counter = collections.Counter()
for r in high:
    cue_counter.update(sorted({c["type"] for c in sms_cues(r["text"])}))
out.append(f"cue types on shipped-HIGH genuine rows: {dict(cue_counter)}")
random.seed(3)


def show(title, group, n):
    out.append(f"## {title} ({len(group)})")
    for r in random.sample(group, min(n, len(group))):
        cues = sorted({c["type"] for c in sms_cues(r["text"])})
        urls = len(extract_urls(r["text"]))
        text = r["text"][:230].replace("\n", " / ")
        out.append(f"[{r['header']} {r['month']} ship={r['shipped']} {r['shipped_risk']} {r['shipped_label']} | "
                   f"run1={r['run1']} {r['run1_risk']} | cues={cues} urls={urls}] {text}")


show("English genuine, shipped HIGH", [r for r in high if r["language"] == "Latin"], 12)
show("Tamil genuine, shipped HIGH", [r for r in high if r["language"] == "Tamil"], 8)
show("English genuine, shipped MEDIUM", [r for r in genuine if r["shipped"] == "medium" and r["language"] == "Latin"], 8)
show("Tamil genuine, run1 MEDIUM", [r for r in genuine if r["run1"] == "medium" and r["language"] == "Tamil"], 6)
(ROOT / "tmp_work" / "real_sms_review.md").write_text("\n".join(out), encoding="utf-8")
print("written", len(out), "lines")
