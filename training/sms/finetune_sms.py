"""DT-2 fine-tuning: continue the v5 checkpoint on corpus + mined hard negatives.

Fine-tunes the pruned v5 checkpoint (models/sms_v5d/sms_model, tokenizer and
id_map) for a short run (default 1 epoch, lr 1e-5, AdamW) on a mix of:
  (a) a stratified sample of the original training rows, built the same way
      train_sms.py builds its training set (same source exclusion, dedup,
      conflict drop, per-source caps, template-hash 80/10/10 split; the pure
      helpers fix_mojibake/template_key/should_exclude_source/map_label are
      imported from train_sms rather than copied), and
  (b) the mined hard negatives (mine_hard_negatives.py output), upweighted by
      --hn-weight (each row is resampled so the effective count is
      len(hn) * weight; weight 5 means each hard negative appears 5x).

Same tokenizer, labels (ham=0, unwanted=1, scam=2) and id_map as v5, max
length 128, fixed seed. Validation macro F1 and per-class recall are computed
on the held-back template-split validation portion of the training corpus;
the held-out CSV is never read here.

Saves into --out-dir: sms_model/ (config.json, model.safetensors), tokenizer/,
id_map.json (copy of the base id_map, so export_sms.py can find it next to the
model dir), parity_inputs.pt (old-space input_ids + attention_mask + logits on
the first validation rows, shaped for export_sms.py --parity-path), and
training_log.json.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

MAX_LEN = 128
SEED = 42

from training.sms.train_sms import (  # pure helpers: reused, not copied
    CLASS_MAP,
    CLASS_NAMES,
    FINAL_MODE,
    HOLDOUT_SOURCES,
    fix_mojibake,
    map_label,
    should_exclude_source,
    template_key,
)


def load_source_info(source_map_path):
    """Load source_map.yaml into {source_id: entry}, as in train_sms.main."""
    import yaml

    with open(source_map_path, "r", encoding="utf-8") as f:
        smap = yaml.safe_load(f)
    info = {}
    if isinstance(smap, list):
        for entry in smap:
            if isinstance(entry, dict) and "id" in entry:
                info[entry["id"]] = entry
    return info


def resolve_source_map(explicit, corpus_dir):
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.append(os.path.join(corpus_dir, "source_map.yaml"))
    candidates.append(os.path.join(corpus_dir, "..", "source_map.yaml"))
    candidates.append("data/source_map.yaml")
    candidates.append("data/processed/source_map.yaml")
    for c in candidates:
        p = os.path.normpath(c)
        if p and os.path.isfile(p):
            return p
    raise FileNotFoundError(f"source_map.yaml not found (looked in {candidates})")


def build_train_val_split(parquet_files, source_info, seed=SEED, sample_size=20000, val_size=2000):
    """Build (train_sample, val) the same way train_sms.py builds its training set.

    Mirrors train_sms.main pass 1 (cross-source label-conflict text_hashes),
    pass 2 (label mapping with fail-loud on unmapped, empty-text drop,
    fix_mojibake, conflict drop, per-file dedup on text_hash, per-source caps
    of 100k / 30k for synthetic), the FINAL_MODE holdout split and the
    template-hash 80/10/10 split, then takes a stratified (by class) sample.
    Never touches the held-out CSV.
    """
    import pandas as pd
    import pyarrow.parquet as pq

    random.seed(seed)
    parquet_files = sorted(str(p) for p in parquet_files)
    if not parquet_files:
        raise RuntimeError("no parquet files given")

    pairs = []
    failed = 0
    for pf in parquet_files:
        try:
            avail = pq.read_schema(pf).names
            if not all(c in avail for c in ("text_hash", "label", "source")):
                continue
            tbl = pq.read_table(pf, columns=["text_hash", "label", "source"])
            df = tbl.to_pandas()
            if len(df) == 0:
                continue
            src_id = str(df["source"].iloc[0])
            if should_exclude_source(source_info.get(src_id, {})):
                continue
            mapped = []
            for raw in df["label"]:
                cid = map_label(raw)
                if cid is None:
                    raise ValueError(f"unmapped label {raw!r} in {pf}")
                mapped.append(cid)
            df["class_id"] = mapped
            pairs.append(df[["text_hash", "class_id"]].drop_duplicates())
        except ValueError:
            raise
        except Exception as e:
            print(f"pass1 error {pf}: {e}", flush=True)
            failed += 1
    if failed:
        raise RuntimeError(f"pass1 failed on {failed} parquet file(s)")
    if pairs:
        all_pairs = pd.concat(pairs, ignore_index=True).drop_duplicates()
        counts = all_pairs.groupby("text_hash", sort=False)["class_id"].nunique()
        conflict_hashes = set(counts.index[counts > 1])
    else:
        conflict_hashes = set()
    print(f"conflict hashes: {len(conflict_hashes)}", flush=True)

    loaded = []
    holdout_chunks = []
    for pf in parquet_files:
        avail = pq.read_schema(pf).names
        cols = [c for c in ["text", "label", "source", "text_hash"] if c in avail]
        df = pq.read_table(pf, columns=cols).to_pandas()
        if len(df) == 0:
            continue
        src_id = str(df["source"].iloc[0]) if "source" in df.columns else Path(pf).stem
        s_meta = source_info.get(src_id, {})
        if should_exclude_source(s_meta):
            continue
        mapped = []
        for raw in df["label"]:
            cid = map_label(raw)
            if cid is None:
                raise ValueError(f"unmapped label {raw!r} in {pf} (allowed: ham/unwanted/spam/scam)")
            mapped.append(cid)
        df["class_id"] = mapped
        df = df.dropna(subset=["text"])
        df = df[df["text"].astype(str).str.strip().str.len() > 0].copy()
        df["text"] = df["text"].map(fix_mojibake)
        if conflict_hashes:
            df = df[~df["text_hash"].isin(conflict_hashes)]
        df = df.drop_duplicates(subset=["text_hash"])
        cap = 30000 if bool(s_meta.get("synthetic", False)) else 100000
        if len(df) > cap:
            df = df.sample(n=cap, random_state=seed)
        if not FINAL_MODE and src_id in HOLDOUT_SOURCES:
            holdout_chunks.append(df)
        else:
            loaded.append(df)
    if not loaded:
        raise RuntimeError("no training rows after filtering")
    if holdout_chunks:
        holdout = pd.concat(holdout_chunks, ignore_index=True)
        holdout["template_hash"] = holdout["text"].map(
            lambda t: int(hashlib.md5(template_key(t).encode("utf-8")).hexdigest(), 16)
        )
        holdout_text_hashes = set(holdout["text_hash"])
        holdout_template_hashes = set(holdout["template_hash"])
        kept = []
        for c in loaded:
            c = c.copy()
            c["template_hash"] = c["text"].map(
                lambda t: int(hashlib.md5(template_key(t).encode("utf-8")).hexdigest(), 16)
            )
            c = c[~c["text_hash"].isin(holdout_text_hashes) & ~c["template_hash"].isin(holdout_template_hashes)]
            kept.append(c)
        loaded = [c for c in kept if len(c)]
    df = pd.concat(loaded, ignore_index=True)
    df["template_hash"] = df["text"].map(
        lambda t: int(hashlib.md5(template_key(t).encode("utf-8")).hexdigest(), 16)
    )
    mod = df["template_hash"] % 100
    train_pool = df[mod < 80].reset_index(drop=True)
    val_pool = df[(mod >= 80) & (mod < 90)].reset_index(drop=True)
    print(f"train pool {len(train_pool)}, val pool {len(val_pool)}, corpus clean {len(df)}", flush=True)
    train_sample = stratified_sample(train_pool, sample_size, seed)
    val = stratified_sample(val_pool, val_size, seed + 1) if len(val_pool) > val_size else val_pool
    stats = {
        "rows_clean": len(df),
        "train_pool": len(train_pool),
        "val_pool": len(val_pool),
        "conflict_hashes": len(conflict_hashes),
    }
    return train_sample, val, stats


def stratified_sample(df, n, seed):
    """Proportional per-class sample (deterministic given seed)."""
    import pandas as pd

    if n is None or len(df) <= n:
        return df.reset_index(drop=True)
    rng = random.Random(seed)
    parts = []
    total = len(df)
    remaining = n
    groups = [(cls, grp) for cls, grp in sorted(df.groupby("class_id"))]
    for i, (cls, grp) in enumerate(groups):
        k = int(round(n * len(grp) / total))
        k = min(k, len(grp))
        if i == len(groups) - 1:
            k = min(max(0, remaining), len(grp))
        idx = list(grp.index)
        rng.shuffle(idx)
        parts.append(grp.loc[idx[:k]])
        remaining -= k
    out = pd.concat(parts, ignore_index=True) if parts else df.head(0).copy()
    out = out.sample(n=min(n, len(out)), random_state=seed).reset_index(drop=True) if len(out) else out
    return out


def mix_hard_negatives(train_df, hn_df, weight, seed):
    """Append upweighted hard negatives; return (combined, hn_effective_count).

    Effective hard-negative count is round(len(hn) * weight) rows resampled
    with replacement (seeded), which realises integer repetition exactly.
    Labels must already be class_id ints; texts are fix_mojibake repaired.
    """
    import pandas as pd

    if hn_df is None or len(hn_df) == 0 or weight is None or weight <= 0:
        return train_df.reset_index(drop=True), 0
    target = int(round(len(hn_df) * float(weight)))
    if target <= 0:
        return train_df.reset_index(drop=True), 0
    hn = hn_df.copy()
    hn["text"] = hn["text"].map(fix_mojibake)
    # Weight 1.0 keeps every row exactly once; other weights resample with replacement.
    hn = hn.sample(n=target, replace=target != len(hn), random_state=seed).reset_index(drop=True)
    combined = pd.concat([train_df, hn], ignore_index=True)
    combined = combined.sample(n=len(combined), random_state=seed).reset_index(drop=True)
    return combined, target


def classification_metrics(y_true, y_pred, n_classes=3):
    """Pure-python macro F1 and per-class precision/recall/F1 (no sklearn)."""
    cm = [[0] * n_classes for _ in range(n_classes)]
    for t, p in zip(y_true, y_pred):
        cm[int(t)][int(p)] += 1
    per_class = {}
    f1s = []
    for c in range(n_classes):
        tp = cm[c][c]
        fn = sum(cm[c]) - tp
        fp = sum(cm[r][c] for r in range(n_classes)) - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[CLASS_NAMES[c]] = {
            "precision": float(prec),
            "recall": float(rec),
            "f1": float(f1),
            "support": int(sum(cm[c])),
        }
        f1s.append(f1)
    return {"macro_f1": float(sum(f1s) / len(f1s)) if f1s else 0.0, "per_class": per_class,
            "confusion_matrix": cm}


def remap_ids_tensor(input_ids, id_map):
    """Remap old-space ids through the pruned id_map (out-of-range -> id_map[0])."""
    import torch

    lookup = torch.as_tensor(list(id_map), dtype=input_ids.dtype, device=input_ids.device)
    valid = (input_ids >= 0) & (input_ids < len(id_map))
    clamped = input_ids.clamp(min=0, max=len(id_map) - 1)
    remapped = lookup[clamped]
    return torch.where(valid, remapped, lookup[0])


def encode_texts(tokenizer, texts, id_map, max_length=MAX_LEN, encode_batch=1000):
    """Tokenise texts like train_sms (max_length 128, padding max_length) and
    remap old-space ids into the pruned checkpoint's space. Returns old-space
    ids (for parity) plus pruned-space ids ready for the model."""
    import torch

    old_all = []
    att_all = []
    for i in range(0, len(texts), encode_batch):
        enc = tokenizer(
            list(texts[i:i + encode_batch]),
            padding="max_length",
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        old_all.append(enc["input_ids"].long())
        att_all.append(enc["attention_mask"].long())
    old_ids = torch.cat(old_all, dim=0) if old_all else torch.zeros((0, max_length), dtype=torch.long)
    att = torch.cat(att_all, dim=0) if att_all else torch.zeros((0, max_length), dtype=torch.long)
    pruned_ids = remap_ids_tensor(old_ids, id_map) if id_map is not None else old_ids
    return pruned_ids, att, old_ids


def run_training(model, tokenizer, id_map, train_df, val_df, hn_count=0, hn_weight=0,
                 lr=1e-5, epochs=1, batch_size=64, seed=SEED, max_steps=None,
                 log_interval=50, max_length=MAX_LEN, device=None):
    """Fine-tune loop + validation. Returns the training log dict.

    Works with any model whose forward returns .logits and any tokenizer
    callable matching the transformers signature, so tests can pass fakes.
    """
    import torch
    from torch.optim import AdamW

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    random.seed(seed)
    torch.manual_seed(seed)

    train_texts = train_df["text"].tolist()
    train_labels = torch.tensor(train_df["class_id"].tolist(), dtype=torch.long)
    train_ids, train_att, _ = encode_texts(tokenizer, train_texts, id_map, max_length)
    val_texts = val_df["text"].tolist()
    val_labels = torch.tensor(val_df["class_id"].tolist(), dtype=torch.long)
    val_ids, val_att, val_old_ids = encode_texts(tokenizer, val_texts, id_map, max_length)

    n = len(train_texts)
    perm = torch.randperm(n) if n else torch.zeros((0,), dtype=torch.long)
    steps_per_epoch = (n + batch_size - 1) // batch_size if n else 0
    total_steps_planned = epochs * steps_per_epoch
    if max_steps is not None:
        total_steps_planned = min(total_steps_planned, int(max_steps))

    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    criterion = torch.nn.CrossEntropyLoss()

    loss_log = []
    step = 0
    interval_sum = 0.0
    interval_n = 0
    t0 = time.time()
    done = False
    for epoch in range(epochs):
        if done:
            break
        model.train()
        perm = torch.randperm(n)
        for b in range(steps_per_epoch):
            idx = perm[b * batch_size:(b + 1) * batch_size]
            input_ids = train_ids[idx].to(device)
            att = train_att[idx].to(device)
            labels = train_labels[idx].to(device)
            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=att)
            loss = criterion(outputs.logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            interval_sum += loss.item()
            interval_n += 1
            step += 1
            print(f"epoch {epoch + 1}/{epochs} step {step}/{total_steps_planned} loss {loss.item():.4f}", flush=True)
            if step % log_interval == 0 or step == total_steps_planned:
                loss_log.append({"step": int(step), "loss": float(interval_sum / max(1, interval_n))})
                interval_sum = 0.0
                interval_n = 0
            if max_steps is not None and step >= int(max_steps):
                done = True
                break

    model.eval()
    with torch.no_grad():
        preds = []
        for i in range(0, len(val_texts), batch_size):
            outputs = model(
                input_ids=val_ids[i:i + batch_size].to(device),
                attention_mask=val_att[i:i + batch_size].to(device),
            )
            preds.extend(outputs.logits.argmax(dim=-1).cpu().tolist())
    val_metrics = classification_metrics(val_labels.tolist(), preds, n_classes=len(CLASS_NAMES))

    parity = None
    if val_texts:
        with torch.no_grad():
            n_par = min(200, len(val_texts))
            parity_logits = model(
                input_ids=val_ids[:n_par].to(device),
                attention_mask=val_att[:n_par].to(device),
            ).logits.cpu()
        parity = {
            "input_ids": val_old_ids[:n_par].long(),
            "attention_mask": val_att[:n_par].long(),
            "logits": parity_logits,
        }

    log = {
        "rows_used": int(n),
        "train_sample_rows": int(len(train_df)),
        "hard_negative_count": int(hn_count),
        "hard_negative_weight": float(hn_weight),
        "hard_negative_effective_rows": int(round(hn_count * float(hn_weight))) if hn_count and hn_weight else 0,
        "validation_rows": int(len(val_df)),
        "epochs": int(epochs),
        "lr": float(lr),
        "seed": int(seed),
        "batch_size": int(batch_size),
        "steps_run": int(step),
        "loss_log": loss_log,
        "validation": val_metrics,
        "device": str(device),
        "elapsed_s": time.time() - t0,
    }
    return log, parity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DT-2 fine-tune from the v5 SMS checkpoint")
    parser.add_argument("--model-dir", default="models/sms_v5d/sms_model")
    parser.add_argument("--tokenizer-dir", default="models/sms_v5d/tokenizer")
    parser.add_argument("--id-map", default="models/sms_v5d/id_map.json")
    parser.add_argument("--corpus-dir", default="data/processed/sms")
    parser.add_argument("--source-map", default=None)
    parser.add_argument("--hard-negatives", default="tmp_work/hard_negatives/hard_negatives.parquet")
    parser.add_argument("--hn-weight", type=float, default=5.0, help="Hard-negative upweight (effective rows = round(n * weight)).")
    parser.add_argument("--sample-size", type=int, default=20000, help="Stratified sample size of the training pool.")
    parser.add_argument("--val-size", type=int, default=2000, help="Validation sample cap.")
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--max-steps", type=int, default=None, help="Cap optimizer steps (smoke runs).")
    parser.add_argument("--log-interval", type=int, default=50)
    parser.add_argument("--out-dir", default="tmp_work/finetuned_sms")
    parser.add_argument("--device", default=None)
    # Multilang experiment: rows of all three classes appended to the training sample.
    # --hard-negatives "" skips mining rows; --id-map identity trains the unpruned checkpoint.
    parser.add_argument("--extra-rows", nargs="*", default=[], help="Parquet files with text,label columns (ham/unwanted/scam).")
    parser.add_argument("--extra-weight", type=float, default=1.0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    import pandas as pd

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = torch.device(args.device) if args.device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device} lr={args.lr} epochs={args.epochs} hn_weight={args.hn_weight}", flush=True)

    source_map = resolve_source_map(args.source_map, args.corpus_dir)
    source_info = load_source_info(source_map)
    print(f"source_map={source_map} ({len(source_info)} sources)", flush=True)
    parquet_files = sorted(glob.glob(os.path.join(args.corpus_dir, "*.parquet")))
    train_df, val_df, stats = build_train_val_split(
        parquet_files, source_info, seed=args.seed, sample_size=args.sample_size, val_size=args.val_size
    )

    hn_df = pd.DataFrame(columns=["text", "label", "class_id"])
    if args.hard_negatives:
        hn_df = pd.read_parquet(args.hard_negatives)
        if not {"text", "label"}.issubset(hn_df.columns):
            raise RuntimeError(f"{args.hard_negatives} needs text,label columns")
        hn_df = hn_df.copy()
        hn_df["class_id"] = hn_df["label"].map(map_label)
        hn_df = hn_df[hn_df["class_id"].isin([0, 1])].reset_index(drop=True)
        train_df, hn_effective = mix_hard_negatives(train_df, hn_df, args.hn_weight, args.seed)
        print(f"train rows after mix: {len(train_df)} (hn effective {hn_effective})", flush=True)

    extra_counts = {}
    for path in args.extra_rows:
        extra = pd.read_parquet(path, columns=["text", "label"])
        extra["class_id"] = extra["label"].map(map_label)
        if extra["class_id"].isna().any():
            raise RuntimeError(f"{path} has labels outside ham/unwanted/spam/scam")
        extra["class_id"] = extra["class_id"].astype(int)
        train_df, effective = mix_hard_negatives(train_df, extra, args.extra_weight, args.seed)
        extra_counts[os.path.basename(path)] = {"rows": int(len(extra)), "effective": int(effective),
                                                "by_class": {str(k): int(v) for k, v in extra["class_id"].value_counts().items()}}
        print(f"extra rows {path}: {len(extra)} (effective {effective}); train rows now {len(train_df)}", flush=True)

    id_map = None
    if args.id_map != "identity":
        with open(args.id_map, "r", encoding="utf-8") as f:
            id_map = json.load(f)
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)

    log, parity = run_training(
        model, tokenizer, id_map, train_df, val_df,
        hn_count=len(hn_df), hn_weight=args.hn_weight,
        lr=args.lr, epochs=args.epochs, batch_size=args.batch_size, seed=args.seed,
        max_steps=args.max_steps, log_interval=args.log_interval, device=device,
    )
    log.update({
        "corpus_stats": stats,
        "base_model_dir": args.model_dir,
        "tokenizer_dir": args.tokenizer_dir,
        "id_map": args.id_map,
        "corpus_dir": args.corpus_dir,
        "source_map": source_map,
        "hard_negatives": args.hard_negatives,
        "extra_rows": extra_counts,
        "extra_weight": args.extra_weight,
    })

    os.makedirs(args.out_dir, exist_ok=True)
    model_dir = os.path.join(args.out_dir, "sms_model")
    tok_dir = os.path.join(args.out_dir, "tokenizer")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(tok_dir, exist_ok=True)
    model.save_pretrained(model_dir)
    tokenizer.save_pretrained(tok_dir)
    if id_map is not None:
        shutil.copyfile(args.id_map, os.path.join(args.out_dir, "id_map.json"))
    if parity is not None:
        torch.save(parity, os.path.join(args.out_dir, "parity_inputs.pt"))
    with open(os.path.join(args.out_dir, "training_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"saved model -> {model_dir}, tokenizer -> {tok_dir}, log -> training_log.json", flush=True)
    print(f"validation macro F1 {log['validation']['macro_f1']:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
