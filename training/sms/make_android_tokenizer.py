#!/usr/bin/env python3
"""
make_android_tokenizer.py

Reads <model-dir>/tokenizer/tokenizer.json (default models/sms_v6ml) and:
1. Writes compact vocab file sms_vocab.txt (one line per id: piece TAB score, in id order)
   with header/sidecar containing unk_id and special token ids.
2. Writes android/app/src/test/resources/sms_tok_fixture.json containing about 300 texts
   with exact input_ids and attention_mask from Python tokenizer (padding max_length 128, truncation).
"""

import csv
import json
import os
from pathlib import Path


def parse_tokenizer_vocab(tok_data: dict) -> dict:
    """Pure helper: extract vocab stats and special-token ids from tokenizer.json data."""
    vocab = tok_data["model"]["vocab"]
    unk_id = tok_data["model"].get("unk_id", 3)
    vocab_size = len(vocab)
    min_score = min(score for _, score in vocab)
    special_ids = {}
    for at in tok_data.get("added_tokens", []):
        special_ids[at["content"]] = at["id"]
    bos_id = special_ids.get("<s>", 0)
    pad_id = special_ids.get("<pad>", 1)
    eos_id = special_ids.get("</s>", 2)
    mask_id = special_ids.get("<mask>", 250001)
    return {
        "vocab": vocab,
        "unk_id": unk_id,
        "vocab_size": vocab_size,
        "min_score": min_score,
        "bos_id": bos_id,
        "pad_id": pad_id,
        "eos_id": eos_id,
        "mask_id": mask_id,
    }


def format_vocab_header(meta: dict) -> str:
    return (
        f"# unk_id={meta['unk_id']} bos_id={meta['bos_id']} eos_id={meta['eos_id']} "
        f"pad_id={meta['pad_id']} mask_id={meta['mask_id']} min_score={meta['min_score']:.8f}\n"
    )


def main() -> None:
    import argparse
    repo_root = Path(__file__).resolve().parent.parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(repo_root / "models" / "sms_v6ml"),
                    help="export dir holding tokenizer/; sms_vocab.txt is written here")
    model_dir = Path(ap.parse_args().model_dir)
    tok_json_path = model_dir / "tokenizer" / "tokenizer.json"
    tok_dir = model_dir / "tokenizer"

    print(f"Loading tokenizer from {tok_json_path}...")
    with open(tok_json_path, "r", encoding="utf-8") as f:
        tok_data = json.load(f)

    meta = parse_tokenizer_vocab(tok_data)
    vocab = meta["vocab"]
    unk_id = meta["unk_id"]
    vocab_size = meta["vocab_size"]
    min_score = meta["min_score"]
    bos_id = meta["bos_id"]
    pad_id = meta["pad_id"]
    eos_id = meta["eos_id"]
    mask_id = meta["mask_id"]

    print(f"Vocab size: {vocab_size}, unk_id: {unk_id}, bos: {bos_id}, eos: {eos_id}, pad: {pad_id}")

    # Output vocab file paths
    v5q_dir = model_dir
    res_dir = repo_root / "android" / "app" / "src" / "test" / "resources"
    res_dir.mkdir(parents=True, exist_ok=True)

    v5q_vocab_file = v5q_dir / "sms_vocab.txt"
    res_vocab_file = res_dir / "sms_vocab.txt"

    header_line = format_vocab_header(meta)

    print(f"Writing {v5q_vocab_file}...")
    with open(v5q_vocab_file, "w", encoding="utf-8") as f:
        f.write(header_line)
        for piece, score in vocab:
            f.write(f"{piece}\t{score:.8f}\n")

    size_bytes = v5q_vocab_file.stat().st_size
    print(f"Wrote {v5q_vocab_file} ({size_bytes / (1024 * 1024):.2f} MB)")

    # Also copy to test resources
    print(f"Copying to {res_vocab_file}...")
    with open(res_vocab_file, "w", encoding="utf-8") as f:
        f.write(header_line)
        for piece, score in vocab:
            f.write(f"{piece}\t{score:.8f}\n")

    # Sidecar JSON metadata
    sidecar_data = {
        "unk_id": unk_id,
        "bos_id": bos_id,
        "eos_id": eos_id,
        "pad_id": pad_id,
        "mask_id": mask_id,
        "vocab_size": vocab_size,
        "min_score": min_score,
    }
    with open(v5q_dir / "sms_vocab_meta.json", "w", encoding="utf-8") as f:
        json.dump(sidecar_data, f, indent=2)
    with open(res_dir / "sms_vocab_meta.json", "w", encoding="utf-8") as f:
        json.dump(sidecar_data, f, indent=2)

    # Build fixture texts
    texts = []

    # 1. errors.csv — derived from --model-dir so the fixture matches the model being packaged.
    errors_csv = model_dir / "errors.csv"
    if errors_csv.exists():
        with open(errors_csv, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("text")
                if t:
                    texts.append(t)
        print(f"Loaded {len(texts)} texts from {errors_csv}")
    else:
        print(f"WARNING: errors.csv not found at {errors_csv}; fixture will have fewer hard-case texts")

    # 2. holdout_errors.csv — derived from --model-dir; falls back to sms_v4eval only if
    #    the model-dir sibling does not exist.
    holdout_v5 = model_dir / "holdout_errors.csv"
    holdout_v4 = repo_root / "models" / "sms_v4eval" / "holdout_errors.csv"
    if holdout_v5.exists():
        prev_len = len(texts)
        with open(holdout_v5, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("text")
                if t:
                    texts.append(t)
        print(f"Loaded {len(texts) - prev_len} texts from {holdout_v5}")
    elif holdout_v4.exists():
        prev_len = len(texts)
        # target about 285 texts before demo and hand-written cases
        target_error_count = 285
        with open(holdout_v4, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if len(texts) >= target_error_count:
                    break
                t = row.get("text")
                if t:
                    texts.append(t)
        print(f"Loaded {len(texts) - prev_len} texts from {holdout_v4} (fallback to reach ~300)")



    # 3. Hand-written test cases
    # 4. 10 Hand-written test cases
    handwritten = [
        # 1. Hindi Devanagari
        "प्रिय ग्राहक, आपका एसबीआई खाता केवाईसी लंबित है, आज ही अपडेट करें: http://sbi.co.in",
        # 2. Bengali
        "প্রিয় গ্রাহক, আপনার ব্যাংক অ্যাকাউন্ট সাময়িকভাবে স্থগিত করা হয়েছে। অবিলম্বে যোগাযোগ করুন।",
        # 3. Tamil
        "அன்பான வாடிக்கையாளரே, உங்கள் வங்கி கணக்கு தற்காலிகமாக முடக்கப்பட்டுள்ளது. உடனடியாக சரிபார்க்கவும்.",
        # 4. Hinglish
        "Bhai tera parcel deliver nahi ho paya, turant is link pe click karke address verify karle http://bit.ly/track-pkg",
        # 5. Emoji
        "🎉 Congratulations! You have won 💰 Rs 1,00,000 cash prize! 🎁 Claim now: http://win-prize.xyz 🚀",
        # 6. Full-width digits
        "Your OTP is １２３４５６. Valid for ５ minutes. Do not share.",
        # 7. Multiple spaces
        "Hello    world!   This    has    lots    of    spaces.",
        # 8. Tabs
        "Column1\tColumn2\tColumn3\tValue1\tValue2\tValue3",
        # 9. 600-character message
        "Urgent alert: " + (
            "Dear user your account security verification is pending due to unusual activity detected on your network. "
            "Please click the official portal link to verify your identity immediately or your services will be terminated within 24 hours. "
            * 3
        )[:580],
        # 10. Empty string
        "",
    ]
    texts.extend(handwritten)
    print(f"Total fixture texts: {len(texts)} (including {len(handwritten)} hand-written cases)")

    # Tokenize with transformers AutoTokenizer
    from transformers import AutoTokenizer

    print(f"Tokenizing texts with transformers AutoTokenizer from {tok_dir}...")
    tok = AutoTokenizer.from_pretrained(str(tok_dir))

    fixture = []
    for t in texts:
        enc = tok(t, padding="max_length", truncation=True, max_length=128)
        fixture.append({
            "text": t,
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
        })

    fixture_path = res_dir / "sms_tok_fixture.json"
    print(f"Writing {len(fixture)} items to {fixture_path}...")
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(f"Done! sms_tok_fixture.json size: {fixture_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
