from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import pyarrow.parquet as pq

from data.build_corpus import compute_text_hash

RAW_DIR = ROOT_DIR / "data" / "raw" / "ext" / "heldout_20261107"
CARNAGE_PATH = RAW_DIR / "carnageiron_scam_hum_india.csv"
ANMOL_PATH = RAW_DIR / "anmolshrivastav_scam_ham_india_14_languages.csv"
PROCESSED_DIR = ROOT_DIR / "data" / "processed" / "sms"
OUT_CSV = ROOT_DIR / "bench" / "heldout" / "heldout_20261107.csv"
OUT_JSON = ROOT_DIR / "bench" / "heldout" / "heldout_20261107_build.json"


def load_corpus_hashes(processed_dir: Path) -> set[str]:
    hashes: set[str] = set()
    files = sorted(processed_dir.glob("*.parquet"))
    for path in files:
        table = pq.read_table(path, columns=["text_hash"])
        for value in table.column("text_hash").to_pylist():
            if value is None:
                continue
            text_hash = str(value)
            if text_hash:
                hashes.add(text_hash)
    return hashes


def _label_to_truth(label_value: object) -> str | None:
    """Map a source label to ``ham``/``risky``, or ``None`` when unmapped.

    Only the labels the two held-out sources actually use are mapped:
    ``ham`` to ``ham``, ``spam``/``scam``/``risky`` to ``risky``. Anything
    else (``None``, ``NaN``, empty, or a typo/renamed column) returns
    ``None`` so the caller drops and counts the row instead of silently
    classing it as risky.
    """
    if label_value is None:
        return None
    try:
        if pd.isna(label_value):
            return None
    except Exception:
        pass
    label = str(label_value).strip().lower()
    if label == "ham":
        return "ham"
    if label in {"spam", "scam", "risky"}:
        return "risky"
    return None


def _row_text(row_text: object) -> str:
    if row_text is None:
        return ""
    try:
        if pd.isna(row_text):
            return ""
    except Exception:
        pass
    return str(row_text)


def process_source(
    csv_path: Path,
    source_name: str,
    synthetic: str,
    use_language_col: bool,
    corpus_hashes: set[str],
    seen_hashes: set[str],
    out_rows: list[dict[str, str]],
) -> dict[str, object]:
    df = pd.read_csv(csv_path)
    rows_read = len(df)
    dropped_seen = 0
    dropped_duplicate = 0
    dropped_empty = 0
    dropped_unmapped = 0
    kept = 0
    kept_per_truth = {"ham": 0, "risky": 0}
    records = df.to_dict(orient="records")
    for rec in records:
        text_str = _row_text(rec.get("text"))
        if not text_str.strip():
            dropped_empty += 1
            continue
        truth = _label_to_truth(rec.get("label"))
        if truth is None:
            dropped_unmapped += 1
            continue
        text_hash = compute_text_hash(text_str)
        if text_hash in corpus_hashes:
            dropped_seen += 1
            continue
        if text_hash in seen_hashes:
            dropped_duplicate += 1
            continue
        seen_hashes.add(text_hash)
        if use_language_col:
            raw_lang = rec.get("language")
            try:
                if raw_lang is None or (isinstance(raw_lang, float) and pd.isna(raw_lang)):
                    language = "English"
                else:
                    language = str(raw_lang).strip() or "English"
            except Exception:
                language = "English"
        else:
            language = "English"
        out_rows.append(
            {
                "text": text_str,
                "truth": truth,
                "source": source_name,
                "language": language,
                "synthetic": synthetic,
            }
        )
        kept += 1
        kept_per_truth[truth] += 1
    if dropped_unmapped:
        print(
            "WARNING: {}: dropped {} rows with unknown/empty labels".format(
                source_name, dropped_unmapped
            ),
            file=sys.stderr,
        )
    return {
        "rows_read": rows_read,
        "dropped_seen_in_corpus": dropped_seen,
        "dropped_duplicate": dropped_duplicate,
        "dropped_empty": dropped_empty,
        "dropped_unmapped": dropped_unmapped,
        "kept": kept,
        "kept_per_truth": kept_per_truth,
    }


def main() -> int:
    corpus_hashes = load_corpus_hashes(PROCESSED_DIR)
    if not corpus_hashes:
        print(
            "ERROR: no corpus hashes loaded from {} (missing/empty data/processed/sms?); "
            "refusing to build a held-out set that may overlap training".format(PROCESSED_DIR),
            file=sys.stderr,
        )
        return 1
    seen_hashes: set[str] = set()
    out_rows: list[dict[str, str]] = []
    stats = {}
    stats["carnageiron"] = process_source(
        CARNAGE_PATH, "carnageiron", "mixed", False, corpus_hashes, seen_hashes, out_rows
    )
    stats["anmolshrivastav"] = process_source(
        ANMOL_PATH, "anmolshrivastav", "true", True, corpus_hashes, seen_hashes, out_rows
    )
    total = {
        "rows_read": int(stats["carnageiron"]["rows_read"] + stats["anmolshrivastav"]["rows_read"]),
        "dropped_seen_in_corpus": int(
            stats["carnageiron"]["dropped_seen_in_corpus"]
            + stats["anmolshrivastav"]["dropped_seen_in_corpus"]
        ),
        "dropped_duplicate": int(
            stats["carnageiron"]["dropped_duplicate"] + stats["anmolshrivastav"]["dropped_duplicate"]
        ),
        "dropped_empty": int(
            stats["carnageiron"].get("dropped_empty", 0) + stats["anmolshrivastav"].get("dropped_empty", 0)
        ),
        "dropped_unmapped": int(
            stats["carnageiron"].get("dropped_unmapped", 0)
            + stats["anmolshrivastav"].get("dropped_unmapped", 0)
        ),
        "kept": int(stats["carnageiron"]["kept"] + stats["anmolshrivastav"]["kept"]),
        "kept_per_truth": {
            "ham": int(
                stats["carnageiron"]["kept_per_truth"]["ham"]
                + stats["anmolshrivastav"]["kept_per_truth"]["ham"]
            ),
            "risky": int(
                stats["carnageiron"]["kept_per_truth"]["risky"]
                + stats["anmolshrivastav"]["kept_per_truth"]["risky"]
            ),
        },
    }
    build = {
        "corpus_unique_hashes": len(corpus_hashes),
        "output_rows": len(out_rows),
        "per_source": stats,
        "total": total,
    }
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out_df = pd.DataFrame(out_rows, columns=["text", "truth", "source", "language", "synthetic"])
    out_df.to_csv(OUT_CSV, index=False)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(build, f, indent=2)
    print(json.dumps(build, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
