"""Round 4: choose sms_temperature for one model on validation data only (counts only).

    python bench/heldout_ml/calibrate_round4.py MODEL_DIR CORPUS_DIR SOURCE_MAP

Rule and data are fixed in docs/multilang/ROUND4_PREREGISTERED.md. Never reads the real test
half, the held-out set, the golden set or the phone messages.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout_ml"))

import policy_sim  # noqa: E402
from sentinel import fusion  # noqa: E402
from training.sms import finetune_sms  # noqa: E402

GRID = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
MAX_HAM_ALERT = 0.01
MAX_DEV_GENUINE_ALERT = 0.02
ML = ROOT / "bench" / "heldout_ml"


def alert_rate(texts, probs) -> float:
    return sum(policy_sim.verdicts(t, p)["policy2"][1] for t, p in zip(texts, probs)) / max(len(texts), 1)


def main() -> int:
    model_dir, corpus_dir, source_map = sys.argv[1:4]
    files = sorted(glob.glob(os.path.join(corpus_dir, "*.parquet")))
    _train, val, _stats = finetune_sms.build_train_val_split(
        files, finetune_sms.load_source_info(source_map), seed=42, sample_size=120000, val_size=4000)
    by_label = {label: list(group["text"]) for label, group in val.groupby("label")}
    dev = [r["text"] for r in csv.DictReader(open(ML / "real_sms.csv", encoding="utf-8", newline=""))
           if policy_sim.split_of(r["header"]) == "dev" and policy_sim.sender_class(r["header"]) == "genuine"]

    det = policy_sim.TorchSmsDetector(model_dir, None, "cuda")
    probs = {label: det.probs_batch(texts) for label, texts in by_label.items()}
    dev_probs = det.probs_batch(dev)

    table = []
    for temperature in GRID:
        fusion.FUSION_RULES["sms_temperature"] = temperature
        row = {"temperature": temperature, "dev_genuine_alert": round(alert_rate(dev, dev_probs), 4)}
        for label, texts in by_label.items():
            row[f"val_{label}_alert"] = round(alert_rate(texts, probs[label]), 4)
        row["qualifies"] = row["val_ham_alert"] <= MAX_HAM_ALERT and row["dev_genuine_alert"] <= MAX_DEV_GENUINE_ALERT
        table.append(row)
        print(row, flush=True)
    ok = [r for r in table if r["qualifies"]]
    chosen = max(ok, key=lambda r: (r["val_scam_alert"], r["temperature"]))["temperature"] if ok else 3.0
    out = {"model": model_dir, "val_rows": {k: len(v) for k, v in by_label.items()}, "dev_genuine_rows": len(dev),
           "grid": table, "chosen_temperature": chosen}
    (ROOT / "docs" / "multilang" / "round4_calibration.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("chosen", chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
