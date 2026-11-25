"""Measure the Tamil/Hindi script coverage and labels of candidate datasets.

Run from the repository root:

    .venv\\Scripts\\python.exe data\\tools\\survey_ml_datasets.py

The script reads only the folders already downloaded under ``data/raw_ml``,
reuses ``dominant_script`` from ``bench/heldout/sim_script_gate.py``, and prints
one Markdown block per dataset with:

* row count,
* label column and value counts,
* rows whose dominant script is Tamil or Devanagari (share of letters >= 0.5),
* 5 random rows per label per script (seed 20261110, truncated to 160 chars).

No file is written; the output is meant to be pasted into
``docs/multilang/dataset_survey.md``.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "bench" / "heldout"))

from sim_script_gate import dominant_script  # noqa: E402

RAW_DIR = ROOT_DIR / "data" / "raw_ml"
SEED = 20261110
SAMPLES_PER_GROUP = 5
TRUNCATE = 160
MIN_SCRIPT_SHARE = 0.5
TARGET_SCRIPTS = ("Tamil", "Devanagari")


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", **kwargs)


def _standardise(frame: pd.DataFrame, text_col: str, label_col: str | None, label: str | None = None) -> pd.DataFrame:
    out = pd.DataFrame()
    out["text"] = frame[text_col].fillna("").astype(str)
    out["label"] = frame[label_col].fillna("MISSING").astype(str) if label_col else (label or "unlabeled")
    if "lang" in frame.columns:
        out["lang"] = frame["lang"].fillna("").astype(str)
    return out


def _load_yasmeen(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path / "manual.xlsx", engine="openpyxl")
    return _standardise(frame, "body", "label")


def _load_onkarbhanarkar(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "spam_hindi.csv")
    return _standardise(frame, "v2", "v1")


def _load_adithyanits(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "Spam_or_ham_workingset.csv")
    return _standardise(frame, "Message", "Category")


def _load_debapampal(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "dataset.csv")
    return _standardise(frame, "text", "labels")


def _load_nikhil7g(path: Path) -> pd.DataFrame:
    frames = [
        _read_csv(path / "indian_financial_fraud_scam_dataset_12500.csv"),
        _read_csv(path / "mul-fraud_data.csv"),
    ]
    combined = pd.concat(frames, ignore_index=True)
    return _standardise(combined, "message_text", "is_fraud")


def _load_muthumarii(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "tamil_data.csv")
    return _standardise(frame, "text", "label")


def _load_muhammadhumyun(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "Pakistan_sms_dataset.csv")
    return _standardise(frame, "Messages", "Label")


def _load_anudeep(path: Path) -> pd.DataFrame:
    frames = [pd.read_parquet(file) for file in sorted((path / "data").glob("*.parquet"))]
    combined = pd.concat(frames, ignore_index=True)
    return _standardise(combined, "input_devanagari", None, label="unlabeled")


def _load_tokenbender(path: Path) -> pd.DataFrame:
    texts = []
    with open(path / "combined_data_no_duplicates_reloaded.jsonl", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            parts = [turn.get("value", "") for turn in record.get("conversations", [])]
            texts.append("\n".join(parts))
    frame = pd.DataFrame({"text": texts})
    return _standardise(frame, "text", None, label="unlabeled")


def _load_karanverma(path: Path) -> pd.DataFrame:
    frame = _read_csv(path / "trilingual_fraud_consumer_protection.csv")
    return _standardise(frame, "text", "label")


CASES: list[dict[str, Any]] = [
    {
        "id": "kaggle_yasmeenahmadabadwala_hindi-spam-dataset",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/yasmeenahmadabadwala/hindi-spam-dataset",
        "licence": "MIT",
        "folder": "kaggle__yasmeenahmadabadwala__hindi-spam-dataset",
        "loader": _load_yasmeen,
    },
    {
        "id": "kaggle_onkarbhanarkar_hindi-spam-dataset",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/onkarbhanarkar/hindi-spam-dataset",
        "licence": "Unknown",
        "folder": "kaggle__onkarbhanarkar__hindi-spam-dataset",
        "loader": _load_onkarbhanarkar,
    },
    {
        "id": "kaggle_adithyanits_2000spam-ham-labeleddataset-hindi",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/adithyanits/2000spam-ham-labeleddataset-hindi",
        "licence": "Unknown",
        "folder": "kaggle__adithyanits__2000spam-ham-labeleddataset-hindi",
        "loader": _load_adithyanits,
    },
    {
        "id": "kaggle_debapampal2002_sms-dataset1",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/debapampal2002/sms-dataset1",
        "licence": "MIT",
        "folder": "kaggle__debapampal2002__sms-dataset1",
        "loader": _load_debapampal,
    },
    {
        "id": "kaggle_nikhil7g_multilingual-cross-market-financial-fraud-dataset",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/nikhil7g/multilingual-cross-market-financial-fraud-dataset",
        "licence": "CC-BY-SA-4.0",
        "folder": "kaggle__nikhil7g__multilingual-cross-market-financial-fraud-dataset",
        "loader": _load_nikhil7g,
    },
    {
        "id": "kaggle_muthumarii_tamil-nlp-sentiment-and-fake-news-dataset",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/muthumarii/tamil-nlp-sentiment-and-fake-news-dataset",
        "licence": "CC-BY-SA-4.0",
        "folder": "kaggle__muthumarii__tamil-nlp-sentiment-and-fake-news-dataset",
        "loader": _load_muthumarii,
    },
    {
        "id": "kaggle_muhammadhumyun_pakistan-sms-classification-dataset",
        "source": "kaggle",
        "url": "https://www.kaggle.com/datasets/muhammadhumyun/pakistan-sms-classification-dataset",
        "licence": "CC0-1.0",
        "folder": "kaggle__muhammadhumyun__pakistan-sms-classification-dataset",
        "loader": _load_muhammadhumyun,
    },
    {
        "id": "hf_AnudeepRao_Hinglish-Everyday-Conversations-1M-Devanagari",
        "source": "huggingface",
        "url": "https://huggingface.co/datasets/AnudeepRao/Hinglish-Everyday-Conversations-1M-Devanagari",
        "licence": "Unknown",
        "folder": "hf__AnudeepRao__Hinglish-Everyday-Conversations-1M-Devanagari",
        "loader": _load_anudeep,
    },
    {
        "id": "hf_TokenBender_Tamil_chat_dataset",
        "source": "huggingface",
        "url": "https://huggingface.co/datasets/TokenBender/Tamil_chat_dataset",
        "licence": "Apache-2.0",
        "folder": "hf__TokenBender__Tamil_chat_dataset",
        "loader": _load_tokenbender,
    },
    {
        "id": "hf_karanverma19_tri-fraud-alerts-india",
        "source": "huggingface",
        "url": "https://huggingface.co/datasets/karanverma19/tri-fraud-alerts-india",
        "licence": "MIT",
        "folder": "hf__karanverma19__tri-fraud-alerts-india",
        "loader": _load_karanverma,
    },
]


def _clean(text: str) -> str:
    return " ".join(text.split())[:TRUNCATE]


def _script_name(text: str) -> str:
    script, share = dominant_script(text)
    if script in TARGET_SCRIPTS and share >= MIN_SCRIPT_SHARE:
        return script
    return "Other"


def analyse(case: dict[str, Any]) -> dict[str, Any]:
    folder = RAW_DIR / case["folder"]
    frame = case["loader"](folder)
    frame["script"] = frame["text"].map(_script_name)

    label_counts = frame["label"].value_counts(dropna=False).to_dict()
    script_counts = frame["script"].value_counts().to_dict()
    cross = (
        frame.groupby(["label", "script"]).size().reset_index(name="rows").to_dict("records")
    )

    rng = random.Random(SEED)
    samples: list[dict[str, str]] = []
    for (label, script), group in frame[frame["script"].isin(TARGET_SCRIPTS)].groupby(["label", "script"]):
        indices = list(group.index)
        take = min(SAMPLES_PER_GROUP, len(indices))
        for index in rng.sample(indices, take):
            samples.append(
                {
                    "label": str(label),
                    "script": script,
                    "text": _clean(frame.at[index, "text"]),
                }
            )
    samples.sort(key=lambda item: (item["label"], item["script"]))

    return {
        "id": case["id"],
        "source": case["source"],
        "url": case["url"],
        "licence": case["licence"],
        "rows": int(len(frame)),
        "label_counts": {str(key): int(value) for key, value in label_counts.items()},
        "tamil_rows": int(script_counts.get("Tamil", 0)),
        "devanagari_rows": int(script_counts.get("Devanagari", 0)),
        "script_counts": {str(key): int(value) for key, value in script_counts.items()},
        "label_script_cross": cross,
        "samples": samples,
    }


def _print_markdown(results: list[dict[str, Any]]) -> None:
    print("## Candidate measurements\n")
    print("| Source id | Rows | Tamil-script | Devanagari | Label column values |")
    print("|---|---:|---:|---:|---|")
    for result in results:
        labels = ", ".join(f"{key}={value}" for key, value in sorted(result["label_counts"].items()))
        print(
            f"| {result['id']} | {result['rows']:,} | {result['tamil_rows']:,} | "
            f"{result['devanagari_rows']:,} | {labels} |"
        )

    for result in results:
        print(f"\n### {result['id']}\n")
        print(f"Licence: {result['licence']} | URL: {result['url']}\n")
        print("| Label | Script | Rows |")
        print("|---|---|---:|")
        for row in result["label_script_cross"]:
            print(f"| {row['label']} | {row['script']} | {row['rows']:,} |")
        print("\nSamples (seed 20261110, truncated to 160 chars):\n")
        for sample in result["samples"]:
            print(f"- **{sample['label']} / {sample['script']}**: {sample['text']}")


def main() -> int:
    results = [analyse(case) for case in CASES]
    _print_markdown(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
