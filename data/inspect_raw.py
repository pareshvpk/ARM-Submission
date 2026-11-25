"""Print a schema summary of every tabular file under data/raw/{sms,url,ext}: rows, columns, likely label counts.

Output feeds the per-source mapping in data/build_corpus.py. Reads data only, never executes it.
By default text samples are redacted to lengths and short hashes so real SMS bodies
are not copied into the output file; pass --show-samples to print raw text.
Usage: .venv/Scripts/python data/inspect_raw.py > data/raw_schema.txt
"""
import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

_parser = argparse.ArgumentParser(description="Summarise raw tabular files.")
_parser.add_argument(
    "--show-samples",
    action="store_true",
    help="Print raw first text samples (may contain phone numbers, names and OTPs; do not commit the output).",
)
_args = _parser.parse_args()

RAW = Path(__file__).resolve().parent / "raw"
EXT = {".csv", ".tsv", ".txt", ".json", ".jsonl", ".parquet", ".xlsx", ".xls"}
SKIP_NAMES = {"dataset-metadata.json", ".gitattributes"}
LABELISH = ("label", "class", "type", "category", "target", "result", "status", "spam", "is_", "v1")


def load(p):
    s = p.suffix.lower()
    if s == ".parquet":
        return pd.read_parquet(p)
    if s in (".xlsx", ".xls"):
        return pd.read_excel(p, nrows=200000)
    if s == ".jsonl":
        return pd.read_json(p, lines=True, nrows=200000)
    if s == ".json":
        return pd.read_json(p)
    sep = "\t" if s == ".tsv" else None
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(p, sep=sep, engine="python", encoding=enc, nrows=200000, on_bad_lines="skip")
        except UnicodeDecodeError:
            continue


for d in ("sms", "url", "ext"):
    for p in sorted((RAW / d).rglob("*")):
        if not p.is_file() or p.suffix.lower() not in EXT or p.name in SKIP_NAMES or ".git" in p.parts:
            continue
        rel = p.relative_to(RAW)
        try:
            df = load(p)
        except Exception as e:
            print(f"## {rel}  ({p.stat().st_size / 1e6:.1f}MB)  READ FAIL {type(e).__name__}: {str(e)[:120]}")
            continue
        print(f"## {rel}  ({p.stat().st_size / 1e6:.1f}MB)  rows>={len(df)}")
        print("   cols:", [str(c)[:30] for c in df.columns[:25]])
        for c in df.columns:
            if any(k in str(c).lower() for k in LABELISH) and df[c].nunique() <= 12:
                print(f"   {c}: {df[c].value_counts().head(12).to_dict()}")
        first_text = df.select_dtypes(include=["object", "string"]).columns[:1]
        if len(first_text):
            if _args.show_samples:
                print("   sample:", [str(v)[:90] for v in df[first_text[0]].dropna().head(2)])
            else:
                redacted = []
                for v in df[first_text[0]].dropna().head(2):
                    s = str(v)
                    redacted.append(f"len={len(s)}, sha256[:8]={hashlib.sha256(s.encode('utf-8', errors='ignore')).hexdigest()[:8]}")
                print("   sample_redacted:", redacted)
