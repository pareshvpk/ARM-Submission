"""DT-2 hard-negative mining: run the v5 SMS checkpoint over the training corpus.

Loads the shipped pruned v5 checkpoint (models/sms_v5d/sms_model with its
tokenizer and id_map), scores every ham/unwanted row of data/processed/sms/*.parquet
on CUDA when available (otherwise CPU), and keeps the rows the model predicts as
scam. Rows whose text hash appears in the held-out CSV (bench/heldout/heldout_20261107.csv)
are excluded; the exclusion count is reported. The held-out CSV itself is never scored.

Outputs (into --out-dir):
  hard_negatives.parquet: text, label, source_file, p_scam for predicted-scam rows
  summary.json: counts by source file and label, rows scanned, excluded count

Tokenization matches training (train_sms.py): fix_mojibake, max length 128,
padding="max_length", then id_map remap into the pruned checkpoint's vocab.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

MAX_LEN = 128
SCAM_CLASS = 2

from training.sms.train_sms import fix_mojibake, map_label  # pure helpers, no heavy deps


def compute_text_hash(text: str) -> str:
    """Same hash as bench/heldout/eval_heldout.py:compute_text_hash.

    sha1 of the lowercased, whitespace-collapsed text. Identical to
    data/build_corpus.py:compute_text_hash, so corpus text_hash and held-out
    hashes are comparable.
    """
    if not text or not isinstance(text, str):
        return ""
    collapsed = " ".join(text.strip().lower().split())
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()


def load_heldout_hashes(csv_path: str | Path) -> set[str]:
    """Return the set of text hashes of every row in the held-out CSV."""
    hashes: set[str] = set()
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            text = row.get("text", "")
            h = compute_text_hash(str(text or ""))
            if h:
                hashes.add(h)
    return hashes


def remap_input_ids(input_ids, id_map):
    """Remap token ids through the pruned-checkpoint id_map (tensor, in place of detector).

    Out-of-range ids fall back to id_map[0], matching sentinel.detectors._remap_scalar.
    """
    import torch

    lookup = torch.as_tensor(list(id_map), dtype=input_ids.dtype, device=input_ids.device)
    valid = (input_ids >= 0) & (input_ids < len(id_map))
    clamped = input_ids.clamp(min=0, max=len(id_map) - 1)
    remapped = lookup[clamped]
    return torch.where(valid, remapped, lookup[0])


def score_texts(model, tokenizer, texts, id_map, batch_size, device, max_length=MAX_LEN):
    """Score texts with the checkpoint; return (p_scam list, pred_class list).

    Tokenization matches train_sms.py: padding="max_length", truncation, max_length,
    return_tensors="pt", then id_map remap into the pruned vocab.
    """
    import torch

    p_scam: list[float] = []
    pred_class: list[int] = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i:i + batch_size])
            enc = tokenizer(
                batch,
                padding="max_length",
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            input_ids = enc["input_ids"].to(device)
            attention_mask = enc["attention_mask"].to(device)
            input_ids = remap_input_ids(input_ids, id_map)
            outputs = model(input_ids=input_ids, attention_mask=attention_mask)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1).cpu()
            p_scam.extend(probs[:, SCAM_CLASS].tolist())
            pred_class.extend(logits.argmax(dim=-1).cpu().tolist())
    return p_scam, pred_class


def load_candidates(parquet_files, limit=None):
    """Load ham/unwanted candidate rows from parquet files.

    Returns a list of (filename, DataFrame) chunks where each frame has
    columns text (fix_mojibake repaired, as in training), label (ham/unwanted).
    Label filtering uses train_sms.map_label (ham -> 0, unwanted/spam -> 1).
    """
    import pandas as pd
    import pyarrow.parquet as pq

    chunks = []
    remaining = limit
    for pf in sorted(parquet_files):
        avail = pq.read_schema(pf).names
        if "text" not in avail or "label" not in avail:
            print(f"WARNING: skipping {pf}: missing text/label columns", flush=True)
            continue
        cols = [c for c in ["text", "label"] if c in avail]
        df = pq.read_table(pf, columns=cols).to_pandas()
        if len(df) == 0:
            continue
        keep = []
        for raw in df["label"]:
            cid = map_label(raw)
            keep.append(cid in (0, 1))
        df = df[keep].copy()
        df = df.dropna(subset=["text"])
        df = df[df["text"].astype(str).str.strip().str.len() > 0]
        df["text"] = df["text"].map(fix_mojibake)
        df["label"] = df["label"].map(lambda v: str(v).strip().lower())
        if remaining is not None:
            if remaining <= 0:
                break
            df = df.head(remaining)
            remaining -= len(df)
        if len(df):
            chunks.append((os.path.basename(str(pf)), df))
    return chunks


def mine_hard_negatives(model, tokenizer, id_map, parquet_files, heldout_hashes,
                        batch_size=256, device=None, limit=None, max_length=MAX_LEN):
    """Score candidates and return (hard_df, summary_dict).

    hard_df columns: text, label, source_file, p_scam (predicted-scam ham/unwanted rows).
    summary_dict: rows_scanned, by_label, by_source_file, excluded_heldout, hard_negatives.
    Held-out exclusion happens before scoring so excluded rows never reach the model.
    """
    import pandas as pd

    if device is None:
        import torch
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    chunks = load_candidates(parquet_files, limit=limit)
    hard_rows = []
    by_label: dict[str, int] = {"ham": 0, "unwanted": 0}
    by_source: dict[str, dict[str, int]] = {}
    rows_scanned = 0
    excluded_heldout = 0

    for filename, df in chunks:
        texts = df["text"].tolist()
        labels = df["label"].tolist()
        keep_idx: list[int] = []
        kept_texts: list[str] = []
        kept_labels: list[str] = []
        for idx, (text, label) in enumerate(zip(texts, labels)):
            if compute_text_hash(text) in heldout_hashes:
                excluded_heldout += 1
                continue
            keep_idx.append(idx)
            kept_texts.append(text)
            kept_labels.append(label)
        rows_scanned += len(kept_texts)
        if not kept_texts:
            continue
        p_scam_list, pred_list = score_texts(
            model, tokenizer, kept_texts, id_map, batch_size, device, max_length
        )
        for label, pred, p_scam, text in zip(kept_labels, pred_list, p_scam_list, kept_texts):
            if int(pred) == SCAM_CLASS:
                hard_rows.append({
                    "text": text,
                    "label": label,
                    "source_file": filename,
                    "p_scam": float(p_scam),
                })
                if label in by_label:
                    by_label[label] += 1
                src_entry = by_source.setdefault(filename, {"ham": 0, "unwanted": 0, "total": 0})
                src_entry["total"] += 1
                if label in src_entry:
                    src_entry[label] += 1
        print(f"scanned {filename}: {len(kept_texts)} rows, {len(hard_rows)} hard negatives so far", flush=True)

    hard_df = pd.DataFrame(hard_rows, columns=["text", "label", "source_file", "p_scam"])
    summary = {
        "rows_scanned": rows_scanned,
        "hard_negatives": len(hard_df),
        "excluded_heldout": excluded_heldout,
        "by_label": by_label,
        "by_source_file": by_source,
        "batch_size": batch_size,
        "device": str(device),
        "limit": limit,
        "max_length": max_length,
    }
    return hard_df, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DT-2 hard-negative mining with the v5 SMS checkpoint")
    parser.add_argument("--model-dir", default="models/sms_v5d/sms_model")
    parser.add_argument("--tokenizer-dir", default="models/sms_v5d/tokenizer")
    parser.add_argument("--id-map", default="models/sms_v5d/id_map.json")
    parser.add_argument("--corpus-dir", default="data/processed/sms")
    parser.add_argument("--heldout-csv", default="bench/heldout/heldout_20261107.csv")
    parser.add_argument("--out-dir", default="tmp_work/hard_negatives")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--limit", type=int, default=None, help="Score at most this many candidate rows (smoke runs).")
    parser.add_argument("--device", default=None, help="torch device (default: cuda if available else cpu).")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    import torch

    device = torch.device(args.device) if args.device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device}", flush=True)

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    with open(args.id_map, "r", encoding="utf-8") as f:
        id_map = json.load(f)
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)

    heldout_hashes = load_heldout_hashes(args.heldout_csv)
    print(f"held-out hashes loaded: {len(heldout_hashes)} (from {args.heldout_csv})", flush=True)

    parquet_files = sorted(glob.glob(os.path.join(args.corpus_dir, "*.parquet")))
    if not parquet_files:
        raise RuntimeError(f"no parquet files in {args.corpus_dir}")

    t0 = time.time()
    hard_df, summary = mine_hard_negatives(
        model, tokenizer, id_map, parquet_files, heldout_hashes,
        batch_size=args.batch_size, device=device, limit=args.limit,
    )
    summary["elapsed_s"] = time.time() - t0
    summary["heldout_csv"] = args.heldout_csv
    summary["model_dir"] = args.model_dir
    summary["tokenizer_dir"] = args.tokenizer_dir
    summary["corpus_dir"] = args.corpus_dir

    os.makedirs(args.out_dir, exist_ok=True)
    out_parquet = os.path.join(args.out_dir, "hard_negatives.parquet")
    hard_df.to_parquet(out_parquet, index=False)
    out_summary = os.path.join(args.out_dir, "summary.json")
    with open(out_summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"scanned {summary['rows_scanned']} ham/unwanted rows; "
          f"excluded {summary['excluded_heldout']} held-out-overlapping rows; "
          f"hard negatives: {summary['hard_negatives']} -> {out_parquet}", flush=True)
    print(f"summary -> {out_summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
