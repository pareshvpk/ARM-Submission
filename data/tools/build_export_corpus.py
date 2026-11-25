"""Collect every text the export may see, so vocabulary pruning keeps their tokens.

    python data/tools/build_export_corpus.py ORIGINAL_CORPUS_DIR TOKENIZER_DIR OUT_DIR

export_sms.py keeps only tokens found in `--corpus-dir`. For the Tamil + Hindi model that folder
must hold the original corpus, the added Tamil and Hindi rows, the real development rows, and one
extra file with every Tamil and Devanagari piece of the tokenizer, so a word unseen in training
is not turned into the unknown token on the phone. OUT_DIR must be git-ignored: it holds real rows.
"""
import shutil
import sys
from pathlib import Path

import pandas as pd
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]


def in_script(piece: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" or "\u0b80" <= ch <= "\u0bff" for ch in piece)


def main() -> int:
    original, tokenizer_dir, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    sources = list(original.glob("*.parquet")) + list((ROOT / "data" / "processed_ml" / "sms").glob("*.parquet"))
    for path in sources:
        shutil.copyfile(path, out / path.name)
    real = Path(r"C:\kaggle_stage\ps3-sms-real-private")
    for path in real.glob("real_dev_x*.parquet"):
        pd.read_parquet(path)[["text"]].drop_duplicates().to_parquet(out / "real_dev.parquet", index=False)
    vocab = AutoTokenizer.from_pretrained(tokenizer_dir).get_vocab()
    pieces = sorted(p for p in vocab if in_script(p))
    # A piece alone and after a space, so both the word-start and the inside form are tokenised.
    texts = [p.replace("\u2581", " ").strip() for p in pieces] + ["a" + p.replace("\u2581", "") for p in pieces]
    pd.DataFrame({"text": texts}).to_parquet(out / "script_tokens.parquet", index=False)
    print(f"files {len(list(out.glob('*.parquet')))}; Tamil and Devanagari pieces {len(pieces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
