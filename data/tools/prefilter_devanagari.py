"""Filter the reviewed Hindi candidate sources down to Devanagari rows.

Run from the repository root:

    .venv\\Scripts\\python.exe data\\tools\\prefilter_devanagari.py

Manager decisions (brief B2, 2026-11-10): only three sources are used, and only
their Devanagari-script rows (reuse ``dominant_script`` from
``bench/heldout/sim_script_gate.py``; keep a row when the dominant script is
Devanagari and its share of letters is at least 0.5). One filtered CSV per
source is written under ``data/raw_ml/derived/``; the entries in
``data/source_map_ml.yaml`` point at these derived files, the raw downloads are
never loaded by the corpus builder itself.

Column choices reuse ``data/tools/survey_ml_datasets.py`` so the derived counts
are directly comparable with the survey's cross-tab.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT_DIR / "bench" / "heldout"))

from sim_script_gate import dominant_script  # noqa: E402

RAW_ML = ROOT_DIR / "data" / "raw_ml"
DERIVED = RAW_ML / "derived"
COUNTS_JSON = DERIVED / "prefilter_counts_20261110.json"
MIN_SHARE = 0.5
TARGET_SCRIPT = "Devanagari"

ENCODE_NOTES = True


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def load_yasmeen(folder: Path) -> pd.DataFrame:
    # Same columns as survey_ml_datasets._load_yasmeen (body / label).
    frame = pd.read_excel(folder / "manual.xlsx", engine="openpyxl")
    return pd.DataFrame({
        "text": frame["body"].fillna("").astype(str),
        "label": frame["label"].astype(str),
    })


def load_nikhil7g(folder: Path) -> pd.DataFrame:
    frames = [
        read_csv(folder / "indian_financial_fraud_scam_dataset_12500.csv"),
        read_csv(folder / "mul-fraud_data.csv"),
    ]
    combined = pd.concat(frames, ignore_index=True)
    return pd.DataFrame({
        "text": combined["message_text"].fillna("").astype(str),
        "label": combined["is_fraud"].astype(str),
    })


def load_debapampal(folder: Path) -> pd.DataFrame:
    frame = read_csv(folder / "dataset.csv")
    return pd.DataFrame({
        "text": frame["text"].fillna("").astype(str),
        "label": frame["labels"].astype(str),
    })


SOURCES = [
    {
        "id": "kaggle_yasmeenahmadabadwala_hindi-spam-dataset",
        "folder": "kaggle__yasmeenahmadabadwala__hindi-spam-dataset",
        "loader": load_yasmeen,
        "derived": "kaggle__yasmeenahmadabadwala__hindi-spam-dataset.csv",
    },
    {
        "id": "kaggle_nikhil7g_multilingual-cross-market-financial-fraud-dataset",
        "folder": "kaggle__nikhil7g__multilingual-cross-market-financial-fraud-dataset",
        "loader": load_nikhil7g,
        "derived": "kaggle__nikhil7g__multilingual-cross-market-financial-fraud-dataset.csv",
    },
    {
        "id": "kaggle_debapampal2002_sms-dataset1",
        "folder": "kaggle__debapampal2002__sms-dataset1",
        "loader": load_debapampal,
        "derived": "kaggle__debapampal2002__sms-dataset1.csv",
    },
]


def label_counts(series: pd.Series) -> dict[str, int]:
    counts = series.value_counts(dropna=False)
    return {str(key): int(value) for key, value in counts.items()}


def prefilter_source(spec: dict) -> dict:
    folder = RAW_ML / spec["folder"]
    frame = spec["loader"](folder)

    before_counts = label_counts(frame["label"])

    keep: list[int] = []
    for index, text in frame["text"].items():
        if not text.strip():
            continue
        script, share = dominant_script(text)
        if script == TARGET_SCRIPT and share >= MIN_SHARE:
            keep.append(index)
    filtered = frame.loc[keep, ["text", "label"]].reset_index(drop=True)

    DERIVED.mkdir(parents=True, exist_ok=True)
    out_path = DERIVED / spec["derived"]
    filtered.to_csv(out_path, index=False, encoding="utf-8")

    after_counts = label_counts(filtered["label"])
    return {
        "id": spec["id"],
        "derived_csv": str(out_path.relative_to(ROOT_DIR)),
        "rows_before": int(len(frame)),
        "rows_after": int(len(filtered)),
        "label_counts_before": before_counts,
        "label_counts_after": after_counts,
    }


def main() -> int:
    results = [prefilter_source(spec) for spec in SOURCES]
    totals_after: dict[str, int] = {}
    for result in results:
        for label, count in result["label_counts_after"].items():
            totals_after[label] = totals_after.get(label, 0) + count

    report = {
        "generated": "2026-11-10",
        "tool": "data/tools/prefilter_devanagari.py",
        "rule": (f"keep a row when dominant_script(text) is {TARGET_SCRIPT} "
                 f"and the script's share of letters is at least {MIN_SHARE}; "
                 f"empty texts dropped"),
        "sources": results,
        "totals_after": totals_after,
    }
    COUNTS_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")

    for result in results:
        print(f"{result['id']}: {result['rows_before']:,} -> {result['rows_after']:,} "
              f"({result['label_counts_after']})")
    print(f"totals after filtering: {totals_after}")
    print(f"wrote {COUNTS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
