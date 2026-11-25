"""Print held-out ham rows that the shipped rules flag, for a human read (run from repo root)."""
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
import dump_probs  # noqa: E402
import sim_script_gate as sim  # noqa: E402

lang = sys.argv[1] if len(sys.argv) > 1 else "Tamil"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
rows, _ = sim._load_rows()
levels = sim._fuse_levels(rows, sim.shipped_params())
text = {dump_probs.compute_text_hash(r["text"]): r["text"] for r in csv.DictReader(open(sim.HELDOUT_CSV, encoding="utf-8", newline=""))}
ham = [(r, lv) for r, lv in zip(rows, levels) if r["language"] == lang and r["truth"] == "ham"]
flagged = [(r, lv) for r, lv in ham if lv["level"] != "low"]
passed = [(r, lv) for r, lv in ham if lv["level"] == "low"]
print(f"{lang}: ham {len(ham)}, flagged {len(flagged)}, distinct flagged templates "
      f"{len({' '.join(text[r['text_hash']].split()[:6]) for r, _ in flagged})}")
random.seed(1)
for title, group in (("FLAGGED ham", flagged), ("ham left LOW", passed)):
    print(f"--- {title}")
    for r, lv in random.sample(group, min(n, len(group))):
        print(f"[{lv['level']} {lv['risk']:.2f} ham={r['p_ham']:.2f} unw={r['p_unwanted']:.2f} scam={r['p_scam']:.2f} cues={sorted(r['cue_types'])}] {text[r['text_hash']][:210]}")
