"""Build training rows from the DEVELOPMENT half of the real SMS set (round 3, step 3).

    python data/tools/build_real_train.py OUT_DIR [--repeat 10]

Only senders in the development half (bench/heldout_ml/real_sms_split.json) are used; the test
half is never read here. Labels are weak, from the sender, on the stated assumption that a
registered business header does not send scams:
  header suffix -S / -T / -G                      -> ham
  header suffix -P                                -> unwanted
  no suffix, bank / payment / government header   -> ham
  no suffix, anything else                        -> ham if shipped v5 said ham, else unwanted
Rows are repeated `--repeat` times in the file so the fine-tune needs no per-file weight.
The output goes to a private Kaggle dataset (owner decision 2026-11-12); text is already redacted.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ML = ROOT / "bench" / "heldout_ml"
OFFICIAL = re.compile(r"SBI|HDFC|ICICI|AXIS|IDFC|KOTAK|CANB|IOB|PNB|BOB|UNION|INDB|CBS|BNK|BANK|UPI|NPCI|RBI|GOV|GOI|UIDAI|"
                      r"EPFO|IRCTC|LIC|TRAI|DOT|ITD|CBDT|NSDL|CDSL|CAMS|KFIN|MFD|MF$|JIOPAY|VAAHAN|TNEB|TANGED|IPPB|POST")


def weak_label(header: str, shipped_label: str) -> tuple[str, str]:
    suffix = header.rsplit("-", 1)[-1] if "-" in header else ""
    if suffix in ("S", "T", "G"):
        return "ham", "suffix"
    if suffix == "P":
        return "unwanted", "suffix"
    if OFFICIAL.search(header.upper()):
        return "ham", "official_header"
    return ("ham" if shipped_label == "ham" else "unwanted"), "model_non_scam"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("--repeat", type=int, default=10)
    args = parser.parse_args()
    split = json.load(open(ML / "real_sms_split.json", encoding="utf-8"))
    levels = {r["id"]: r for r in csv.DictReader(open(ML / "real_sms_levels.csv", encoding="utf-8", newline=""))}
    rows, how = [], Counter()
    for row in csv.DictReader(open(ML / "real_sms.csv", encoding="utf-8", newline="")):
        if split.get(row["header"]) != "dev":
            continue
        label, reason = weak_label(row["header"], levels[row["id"]]["shipped_label"])
        how[(reason, label)] += 1
        rows.append({"text": row["text"], "label": label, "lang": row["language"], "source": "real_owner_inbox_dev"})
    frame = pd.DataFrame(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.concat([frame] * args.repeat, ignore_index=True).to_parquet(out / f"real_dev_x{args.repeat}.parquet", index=False)
    print(f"dev rows {len(frame)} x{args.repeat}; labels {dict(frame.label.value_counts())}; by language {dict(frame.lang.value_counts())}")
    print("label sources:", dict(how))
    return 0


if __name__ == "__main__":
    sys.exit(main())
