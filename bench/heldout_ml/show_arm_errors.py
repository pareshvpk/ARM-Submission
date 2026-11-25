"""Print held-out rows where an arm is wrong and a reference arm is right (human read).

    python bench/heldout_ml/show_arm_errors.py LANGUAGE ARM_DIR[,ID_MAP] REF_DIR[,ID_MAP] [n]
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))
import dump_probs  # noqa: E402
import sim_script_gate as sim  # noqa: E402
from score_arms import TorchSmsDetector  # noqa: E402

lang, arm_spec, ref_spec = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 15
rows = [r for r in sim._load_rows()[0] if r["language"] == lang]
text = {dump_probs.compute_text_hash(r["text"]): r["text"] for r in csv.DictReader(open(sim.HELDOUT_CSV, encoding="utf-8", newline=""))}
texts = [text[r["text_hash"]] for r in rows]


def levels(spec):
    model_dir, _, id_map = spec.partition(",")
    probs = TorchSmsDetector(model_dir, id_map or None, "cuda").probs_batch(texts)
    arm_rows = [dict(r, p_ham=p[0], p_unwanted=p[1], p_scam=p[2]) for r, p in zip(rows, probs)]
    return sim._fuse_levels(arm_rows, sim.shipped_params()), probs


arm, arm_probs = levels(arm_spec)
ref, _ = levels(ref_spec)
shown = 0
for r, a, b, p, t in zip(rows, arm, ref, arm_probs, texts):
    risky_a, risky_b = a["level"] != "low", b["level"] != "low"
    wrong_a = risky_a != (r["truth"] == "risky")
    wrong_b = risky_b != (r["truth"] == "risky")
    if wrong_a and not wrong_b and shown < limit:
        shown += 1
        print(f"[truth {r['truth']} arm {a['level']} {a['risk']:.2f} ham={p[0]:.2f} unw={p[1]:.2f} scam={p[2]:.2f} cues={sorted(r['cue_types'])}] {t[:220]}")
print(f"{lang}: arm wrong and reference right on "
      f"{sum(((a['level'] != 'low') != (r['truth'] == 'risky')) and not ((b['level'] != 'low') != (r['truth'] == 'risky')) for r, a, b in zip(rows, arm, ref))} rows; "
      f"reference wrong and arm right on "
      f"{sum(((b['level'] != 'low') != (r['truth'] == 'risky')) and not ((a['level'] != 'low') != (r['truth'] == 'risky')) for r, a, b in zip(rows, arm, ref))} rows")
