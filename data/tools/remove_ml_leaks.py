"""Remove leaked rows from the multilingual corpus built from source_map_ml.yaml.

Run from the repository root:

    .venv\\Scripts\\python.exe data\\tools\\remove_ml_leaks.py

Brief B2 (part 1d): every row whose text hash (compute_text_hash) or template
hash (template_key from training/sms/train_sms.py) equals that of any row in
``bench/heldout/heldout_20261107.csv`` or ``bench/heldout_ml/golden_ta_hi.csv``
is removed from ``data/processed_ml/sms/*.parquet`` in place. The report is
written to ``data/processed_ml/ml_leak_removal.json`` and printed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from training.sms.train_sms import template_key  # noqa: E402

HELDOUT_CSV = ROOT_DIR / "bench" / "heldout" / "heldout_20261107.csv"
GOLDEN_CSV = ROOT_DIR / "bench" / "heldout_ml" / "golden_ta_hi.csv"
PROCESSED_SMS = ROOT_DIR / "data" / "processed_ml" / "sms"
REPORT_JSON = ROOT_DIR / "data" / "processed_ml" / "ml_leak_removal.json"


def compute_text_hash(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    collapsed = " ".join(text.strip().lower().split())
    import hashlib

    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()


def template_hash(text: str) -> int:
    key = template_key(text)
    import hashlib

    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def load_hash_sets() -> dict[str, set]:
    """Held-out and golden text/template hashes."""
    import hashlib

    heldout = pd.read_csv(HELDOUT_CSV, encoding="utf-8")
    golden = pd.read_csv(GOLDEN_CSV, encoding="utf-8")
    hashes = {"heldout_text": set(), "heldout_template": set(),
              "golden_text": set(), "golden_template": set()}
    for df, t_key, h_key in ((heldout, "text", "heldout_text"),
                             (golden, "text", "golden_template" if False else "golden_text")):
        pass
    for text in heldout["text"].fillna("").astype(str):
        hashes["heldout_text"].add(compute_text_hash(text))
        hashes["heldout_template"].add(hashlib.md5(template_key(text).encode("utf-8")).hexdigest())
    for text in golden["text"].fillna("").astype(str):
        hashes["golden_text"].add(compute_text_hash(text))
        hashes["golden_template"].add(hashlib.md5(template_key(text).encode("utf-8")).hexdigest())
    hashes["heldout_text"].discard("")
    hashes["golden_text"].discard("")
    return hashes


def template_hash_of_text(text: str) -> int:
    import hashlib

    return int(hashlib.md5(template_key(text).encode("utf-8")).hexdigest(), 16)


def main() -> int:
    import hashlib

    hashes = load_hash_sets()
    banned_text = hashes["heldout_text"] | hashes["golden_text"]
    banned_template = hashes["heldout_template"] | hashes["golden_template"]
    print(f"banned text hashes: {len(banned_text)}, banned template hashes: {len(banned_template)}")

    report: dict[str, dict] = {"generated": "2026-11-10", "sources": {}}
    template_cache: dict[str, int] = {}

    for parquet_file in sorted(PROCESSED_SMS.glob("*.parquet")):
        schema = pq.read_schema(parquet_file)
        table = pq.read_table(parquet_file)
        df = table.to_pandas()
        before = len(df)

        template_hashes = []
        for text in df["text"].astype(str):
            key = template_key(text)
            cache_key = text
            th = template_cache.get(cache_key)
            if th is None:
                th = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
                template_cache[cache_key] = th
            template_hashes.append(th)
        df["_template_hash"] = template_hashes

        leak_mask = (
            df["text_hash"].isin(banned_text) | df["_template_hash"].isin(banned_template)
        )
        leaked_examples = df.loc[leak_mask, ["source", "text_hash"]].head(10).to_dict("records")

        kept = df.loc[~leak_mask].drop(columns=["_template_hash"])
        after = len(kept)

        out_table = table.slice(0, 0)
        from pyarrow import Table

        out_table = Table.from_pandas(kept, schema=schema, preserve_index=False)
        pq.write_table(out_table, parquet_file, compression="snappy")

        report["sources"][parquet_file.stem] = {
            "rows_before": int(before),
            "rows_after": int(after),
            "rows_removed": int(before - after),
            "removed_examples_text_hash": [r["text_hash"] for r in leaked_examples],
        }
        print(f"{parquet_file.stem}: {before:,} -> {after:,} "
              f"({before - after} removed)")

    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
