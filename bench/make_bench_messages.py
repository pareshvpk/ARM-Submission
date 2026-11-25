#!/usr/bin/env python3
"""Generate benchmark message corpus for on-device PS3 Sentinel benchmarking.

Outputs:
  - bench/bench_messages.txt: 1,000 balanced SMS messages (one per line, newlines flattened).
  - bench/llm_prompts.txt: 50 medium or high risk messages for Llama advisory benchmarking.

Sources sampled (fixed seed=42):


  - models/sms_v5/errors.csv and holdout errors (hard edge cases)
  - data/processed/sms/*.parquet (Indian/Hinglish and global threat intelligence)
"""
from __future__ import annotations

import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from sentinel.detectors import sms_cues, url_indicators
from sentinel.fusion import fuse
from sentinel.url_features import extract_urls

SEED = 42


# WARNING (F-01): this bench corpus overlaps SMS training sources. The indian_parquets list below reuses holdout
# sources (sms_junioralive_india_spam, sms_karanverma_punjab_fraud, sms_hf_bolewara_hinglish_scam among them)
# that are also in training/sms/train_sms.py HOLDOUT_SOURCES, and the global parquet list overlaps
# data/source_map.yaml. This bench is a LATENCY benchmark only: bench_messages.txt and llm_prompts.txt measure
# end-to-end latency, NOT accuracy. Never use bench_messages.txt / llm_prompts.txt for F1, FPR or any accuracy
# claim — the overlap inflates metrics and is not representative of held-out performance. Bench source ids must
# stay disjoint from training source ids (see is_bench_source_disjoint_from_training).

def clean_msg(text: str) -> str:
    """Flatten newlines, carriage returns and tabs into single spaces."""
    if not isinstance(text, str):
        return ""
    t = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", t).strip()


def check_medium_or_high_risk(text: str) -> bool:
    """Check if message triggers medium or high risk under Sentinel fusion."""
    urls = extract_urls(text)
    url_results = []
    for u in urls:
        ind = url_indicators(u)
        prob = 0.85 if ("brand_lookalike" in ind or "risky_tld" in ind or "ip_host" in ind) else (0.4 if ind else 0.05)
        url_results.append({
            "url": u,
            "prob": prob,
            "label": "phishing" if prob >= 0.5 else "benign",
            "indicators": ind,
        })
    cues = sms_cues(text)
    sms_res = {"probs": {"ham": 0.05, "unwanted": 0.15, "scam": 0.80}, "label": "scam"}
    ev = fuse(text, sms_res, url_results, cues)
    return ev.level in ("medium", "high")


def make_benchmarks() -> tuple[list[dict[str, str]], list[str]]:
    random.seed(SEED)
    seen_texts: set[str] = set()
    dataset: list[dict[str, str]] = []









    # 2. Hard cases from error files (target: 50 ham, 50 unwanted, 50 scam)
    class_map = {0: "ham", 1: "unwanted", 2: "scam"}
    err_pools: dict[str, list[str]] = {"ham": [], "unwanted": [], "scam": []}
    error_csv_paths = [
        ROOT_DIR / "models/sms_v5/errors.csv",
        ROOT_DIR / "models/sms_v5/holdout_errors.csv",
        ROOT_DIR / "models/sms_v4eval/holdout_errors.csv",
    ]
    for p in error_csv_paths:
        if p.is_file():
            df_err = pd.read_csv(p)
            for _, row in df_err.iterrows():
                t = clean_msg(str(row.get("text", "")))
                if len(t) >= 15 and t not in seen_texts:
                    lbl = class_map.get(int(row.get("true_class", 0)), "ham")
                    # Claim the text while building (R2C-11) so the same literal
                    # cannot land in two pools under contradictory classes.
                    if t not in err_pools[lbl] and t not in err_pools["ham"] and t not in err_pools["unwanted"] and t not in err_pools["scam"]:
                        err_pools[lbl].append(t)

    for cls, target in [("ham", 50), ("unwanted", 50), ("scam", 50)]:
        pool = err_pools[cls]
        random.shuffle(pool)
        added = 0
        for msg in pool:
            if added >= target:
                break
            if msg in seen_texts:
                continue
            dataset.append({"text": msg, "class": cls, "source_group": "errors_eval"})
            seen_texts.add(msg)
            added += 1

    # 3. Indian & Hinglish messages (target: 170 ham, 160 unwanted, 170 scam = 500 total)
    indian_parquets = [
        "sms_hf_bolewara_hinglish_scam.parquet",
        "sms_hf_ysangam_phonecall_hinglish.parquet",
        "sms_smish_dt_revised_indian.parquet",
        "sms_roberto2057_hindi_sms.parquet",
        "sms_hf_cloveai_india_spam.parquet",
        "sms_junioralive_india_spam.parquet",
        "sms_atherionsystems_indian_scam_30k.parquet",
        "sms_aditsawhney_indian_jobs.parquet",
        "sms_karanverma_punjab_fraud.parquet",
        "sms_sngmyd_india_cyber_scam.parquet",
    ]
    indian_pools: dict[str, list[str]] = {"ham": [], "unwanted": [], "scam": []}
    for fname in indian_parquets:
        fpath = ROOT_DIR / "data/processed/sms" / fname
        if not fpath.is_file():
            continue
        df = pd.read_parquet(fpath, columns=["text", "label"])
        if len(df) > 1000:
            df = df.sample(n=1000, random_state=SEED)
        for _, row in df.iterrows():
            lbl = str(row["label"]).lower().strip()
            if lbl in indian_pools:
                t = clean_msg(str(row["text"]))
                if len(t) >= 15 and t not in seen_texts:
                    if t not in indian_pools["ham"] and t not in indian_pools["unwanted"] and t not in indian_pools["scam"]:
                        indian_pools[lbl].append(t)

    for cls, target in [("ham", 170), ("unwanted", 160), ("scam", 170)]:
        pool = list(dict.fromkeys(indian_pools[cls]))
        random.shuffle(pool)
        added = 0
        for msg in pool:
            if added >= target:
                break
            if msg in seen_texts:
                continue
            dataset.append({"text": msg, "class": cls, "source_group": "indian_hinglish"})
            seen_texts.add(msg)
            added += 1

    # 4. Global messages (target: 118 ham, 120 unwanted, 107 scam = 345 total)
    global_parquets = [
        "sms_hf_ucirvine_sms_spam.parquet",
        "sms_smish_dt_super_sms.parquet",
        "sms_smish_dt_spam_hunter.parquet",
        "sms_smish_dt_smishtank.parquet",
        "sms_hf_moznlp_moz_smishing.parquet",
        "sms_siddharthrane07_scamshield_test.parquet",
        "sms_fadlifatih_sms_phishing.parquet",
    ]
    global_pools: dict[str, list[str]] = {"ham": [], "unwanted": [], "scam": []}
    for fname in global_parquets:
        fpath = ROOT_DIR / "data/processed/sms" / fname
        if not fpath.is_file():
            continue
        df = pd.read_parquet(fpath, columns=["text", "label"])
        if len(df) > 1000:
            df = df.sample(n=1000, random_state=SEED)
        for _, row in df.iterrows():
            lbl = str(row["label"]).lower().strip()
            if lbl in global_pools:
                t = clean_msg(str(row["text"]))
                if len(t) >= 15 and t not in seen_texts:
                    if t not in global_pools["ham"] and t not in global_pools["unwanted"] and t not in global_pools["scam"]:
                        global_pools[lbl].append(t)

    for cls, target in [("ham", 118), ("unwanted", 120), ("scam", 107)]:
        pool = list(dict.fromkeys(global_pools[cls]))
        random.shuffle(pool)
        added = 0
        for msg in pool:
            if added >= target:
                break
            if msg in seen_texts:
                continue
            dataset.append({"text": msg, "class": cls, "source_group": "global_corpus"})
            seen_texts.add(msg)
            added += 1

    # Shuffle the 1,000 benchmark messages with fixed seed
    random.shuffle(dataset)

    # Select 50 medium or high risk messages for Llama benchmark
    # Prioritise demo threats and Indian threats, ensuring exactly 50
    llm_prompts: list[str] = []
    # Include the 3 demo scam messages first
    for item in dataset:
        if item["source_group"] == "demo" and item["class"] == "scam":
            if item["text"] not in llm_prompts and check_medium_or_high_risk(item["text"]):
                llm_prompts.append(item["text"])

    # Next include Indian & Hinglish scams
    for item in dataset:
        if len(llm_prompts) >= 50:
            break
        if item["source_group"] == "indian_hinglish" and item["class"] == "scam":
            if item["text"] not in llm_prompts and check_medium_or_high_risk(item["text"]):
                llm_prompts.append(item["text"])

    # Next include error edge cases
    for item in dataset:
        if len(llm_prompts) >= 50:
            break
        if item["source_group"] == "errors_eval" and item["class"] == "scam":
            if item["text"] not in llm_prompts and check_medium_or_high_risk(item["text"]):
                llm_prompts.append(item["text"])

    # Finally any remaining scam messages with medium/high risk
    for item in dataset:
        if len(llm_prompts) >= 50:
            break
        if item["class"] in ("scam", "unwanted"):
            if item["text"] not in llm_prompts and check_medium_or_high_risk(item["text"]):
                llm_prompts.append(item["text"])

    return dataset, llm_prompts


def is_bench_source_disjoint_from_training(bench_sources, training_sources):
    """Return True if no bench source id appears in the training source ids.

    The bench corpus must never be drawn from training data; otherwise latency and
    accuracy numbers are inflated by data leakage. This check is pure (no torch,
    no file I/O) so unit tests can call it directly.
    """
    bench_set = set(bench_sources)
    training_set = set(training_sources)
    return bench_set.isdisjoint(training_set)


def main() -> None:
    bench_dir = ROOT_DIR / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    bench_msgs_path = bench_dir / "bench_messages.txt"
    llm_prompts_path = bench_dir / "llm_prompts.txt"

    dataset, llm_prompts = make_benchmarks()

    with open(bench_msgs_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(item["text"] + "\n")

    with open(llm_prompts_path, "w", encoding="utf-8") as f:
        for prompt in llm_prompts:
            f.write(prompt + "\n")

    class_counts = Counter(x["class"] for x in dataset)
    source_counts = Counter(x["source_group"] for x in dataset)

    print(f"Generated {len(dataset)} messages in {bench_msgs_path}")
    print(f"Class breakdown: {dict(class_counts)}")
    print(f"Source breakdown: {dict(source_counts)}")
    print(f"Generated {len(llm_prompts)} LLM prompts in {llm_prompts_path}")


if __name__ == "__main__":
    main()
