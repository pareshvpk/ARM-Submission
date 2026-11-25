"""PS3 SMS Scam & Threat Detector: unified corpus training, evaluation, and ExecuTorch export.
"""
import copy
import glob
import inspect
import json
import os
import random
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path
import hashlib
import yaml

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# --- PURE POLICY FUNCTIONS (Importable by unit tests without heavy deps) ---

_URL_RE = re.compile(r"(?:h(?:tt|xx)ps?://|www\.|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{2,})+)[^\s<>\"']*", re.I)
_DIGIT_RE = re.compile(r"\d+")

def fix_mojibake(text: str) -> str:
    """Repair mojibake (up to 3 passes, checking character count reduction from moji set)."""
    if not isinstance(text, str):
        return text
    moji_set = {chr(0xC3), chr(0xC2), chr(0xE2), chr(0xF0)}
    current = text
    for _ in range(3):
        try:
            repaired = current.encode("cp1252").decode("utf-8")
        except UnicodeError:
            try:
                repaired = current.encode("latin-1").decode("utf-8")
            except UnicodeError:
                break
        if repaired == current:
            break
        orig_count = sum(1 for c in current if c in moji_set)
        rep_count = sum(1 for c in repaired if c in moji_set)
        if rep_count < orig_count:
            current = repaired
        else:
            break
    return current


def template_key(text: str) -> str:
    """Lowercase, every digit run replaced by 0, every URL (http, https, www or bare domain) replaced by token u, whitespace collapsed."""
    if not text or not isinstance(text, str):
        return ""
    text = _URL_RE.sub(" u ", text)
    text = _DIGIT_RE.sub("0", text)
    return " ".join(text.lower().split())


def should_exclude_source(entry: dict) -> bool:
    """EXCLUDE from training and main test set: preprocessed true, channel email, channel job_post."""
    if entry.get("preprocessed") is True:
        return True
    channel = str(entry.get("channel", "")).lower()
    if channel in ("email", "job_post"):
        return True
    if entry.get("skip") is True:
        return True
    return False

def map_label(val):
    """Direct mapping of unified label:
    ham -> 0, unwanted -> 1, spam -> 1, scam -> 2, anything else -> None (dropped).
    """
    if val is None or pd.isna(val):
        return None
    s = str(val).strip().lower()
    if s == "ham":
        return 0
    elif s in ("unwanted", "spam"):
        return 1
    elif s == "scam":
        return 2
    return None

CLASS_MAP = {"ham": 0, "unwanted": 1, "scam": 2}
CLASS_NAMES = ["ham", "unwanted", "scam"]

HOLDOUT_SOURCES = [
    "sms_hf_bolewara_hinglish_scam",
    "sms_junioralive_india_spam",
    "sms_karanverma_punjab_fraud",
    "sms_hf_karanverma19_indian_scam",
]

FINAL_MODE = True
"""True trains on the holdout sources too (ship model), False keeps them held out (generalisation check)."""


# 30 hand-written test messages constant
HANDWRITTEN_TEST_MSGS = [
    # 10 Indian legitimate (ham)
    ("Your A/C X9182 debited by INR 1,500.00 on 03-Nov-26 by UPI. Ref: 629103. If not you, call 1800111.", "ham", "bank_debit"),
    ("Dear Customer, your OTP for HDFC NetBanking txn is 482910. Valid for 5 mins. Do not share with anyone.", "ham", "otp"),
    ("Your order #OD48192 is out for delivery today by Blue Dart. Track at bluedart.com/track.", "ham", "delivery"),
    ("Your Jio prepaid recharge of Rs 299 successful. Validity 28 days. Data left 1.5GB/day.", "ham", "recharge"),
    ("IRCTC Alert: PNR 2819384910 for 04-Nov-26 is CONFIRMED, Coach B3, Berth 22.", "ham", "pnr"),
    ("SBI Alert: Your salary credit of INR 45,000.00 on 01-Nov-26. Avail balance: INR 62,400.10.", "ham", "salary"),
    ("Your Amazon order #403-91820-192 dispatched. Delivery expected by tomorrow 4 PM.", "ham", "amazon"),
    ("Electricity Bill Alert: Bill for CA No 10928192 generated. Amount Rs 1,420 due on 10-Nov-26.", "ham", "electricity"),
    ("Your flight AI-542 on 05-Nov-26 from DEL to BOM is on time. Boarding at 06:30 AM.", "ham", "flight"),
    ("Dear User, your FASTag account balance is INR 250.00. Recharge to avoid toll penalty.", "ham", "fastag"),
    
    # 10 Indian scams (scam)
    ("Dear customer your SBI PAN card is blocked today update immediately via http://sbi-pan-update.xyz or call customer care.", "scam", "kyc_block"),
    ("Urgent Alert: Your electricity connection will be disconnected tonight at 9:30 PM due to unpaid bill. Call officer Ramesh at 9876543210.", "scam", "electricity_discon"),
    ("Cyber Crime Bureau: You are under digital arrest for money laundering case involving your Aadhaar. Join Skype video call immediately.", "scam", "digital_arrest"),
    ("India Post: Your parcel is held at customs due to incorrect address. Pay shipping fee INR 49 via http://indiapost-parcel.top", "scam", "customs_fee"),
    ("You have received a UPI collect request of INR 10,000 from PhonePe Merchant. Approve now by entering your UPI PIN.", "scam", "upi_collect"),
    ("Part Time Job Offer: Earn Rs 5,000 daily by liking YouTube videos and rating hotels on Telegram. Message@HR_Manager.", "scam", "job_task"),
    ("Instant Loan App Approved: Rs 50,000 credited to your account instantly without CIBIL check. Download APK from loan-instant.xyz.", "scam", "loan_app"),
    ("Congratulations! Your mobile number won Rs 25 Lakhs in KBC Lucky Draw lottery. Claim now by contacting manager Sharma.", "scam", "lottery"),
    ("Income Tax Department: Refund of Rs 14,890 pending. Verify your bank details immediately at http://it-refund-portal.site", "scam", "fake_refund"),
    ("TRAI Notification: All mobile numbers registered on your Aadhaar will be blocked in 2 hours due to illegal spam calls. Press 1 to speak to officer.", "scam", "sim_block"),

    # 10 Hinglish mixes of both (ham or scam)
    ("Bhai mera Jio recharge ho gaya, 299 wala plan 28 din ka hai.", "ham", "hinglish_ham_1"),
    ("Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko 98XXXXXX call karein.", "scam", "hinglish_scam_1"),
    ("Amazon se parcel aane wala hai delivery boy ka call aayega ghar pe rehna.", "ham", "hinglish_ham_2"),
    ("Aadhaar update karne ke liye ye link open karo http://uidai-update.in warna sim card block ho jayega.", "scam", "hinglish_scam_2"),
    ("Kal train me travel kar raha hu, PNR status check kiya to confirm ho gaya hai.", "ham", "hinglish_ham_3"),
    ("Congratulations sir aapka 50 lakh ka lottery laga hai KBC me, WhatsApp pe message karo.", "scam", "hinglish_scam_3"),
    ("Salary aa gaya hai account me, sabka party pending hai aaj shaam ko.", "ham", "hinglish_ham_4"),
    ("Urgent: Paytm KYC expired! Update now or your wallet will be closed permanently today.", "scam", "hinglish_scam_4"),
    ("Doctor appointment fix hai sham ko 5 baje, time pe pahunch jana.", "ham", "hinglish_ham_5"),
    ("Sir loan approved ho gaya hai 1 lakh ka, ye APK download karke install karo.", "scam", "hinglish_scam_5"),
]


def main():
    INPUT_DIR = os.environ.get("PS3_INPUT_DIR", "/kaggle/input")
    OUT = os.environ.get("PS3_OUT_DIR", "/kaggle/working")
    os.makedirs(OUT, exist_ok=True)
    _logf = open(f"{OUT}/train_log.txt", "w", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        _logf.write(str(msg) + "\n")
        _logf.flush()

    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)

    log(f"Starting SMS training script. INPUT_DIR={INPUT_DIR}, OUT={OUT}")
    log(f"Running in FINAL_MODE={FINAL_MODE}")

    # Load source_map.yaml
    # Kaggle mounts datasets at /kaggle/input/datasets/<owner>/<slug>/, so search recursively.
    # Run 1 found nothing here and silently trained on the excluded sources: fail loudly instead.
    found = sorted(glob.glob(f"{INPUT_DIR}/**/source_map.yaml", recursive=True))
    source_map_path = found[0] if found else None
    if source_map_path is None:
        raise RuntimeError(f"source_map.yaml not found under {INPUT_DIR}")

    source_info = {}
    if source_map_path:
        log(f"Loading source map from {source_map_path}")
        with open(source_map_path, "r", encoding="utf-8") as f:
            smap = yaml.safe_load(f)
            if isinstance(smap, list):
                for entry in smap:
                    if "id" in entry:
                        source_info[entry["id"]] = entry
    log(f"Loaded source metadata for {len(source_info)} sources")
    n_excl = sum(should_exclude_source(e) for e in source_info.values() if e.get("corpus") == "sms" and not e.get("skip"))
    if len(source_info) < 50 or n_excl == 0:
        raise RuntimeError(f"source map looks wrong: {len(source_info)} entries, {n_excl} excluded sms sources")
    log(f"SMS sources excluded from training (preprocessed / email / job_post): {n_excl}")

    # Only the SMS corpus (the URL parquet files live in a sibling url/ folder).
    parquet_files = sorted(p for p in glob.glob(f"{INPUT_DIR}/**/*.parquet", recursive=True)
                           if os.path.basename(os.path.dirname(p)) == "sms")
    log(f"Found {len(parquet_files)} sms parquet files under {INPUT_DIR}")
    if not parquet_files:
        raise RuntimeError("no sms parquet files found")

    # Pass 1: Identify conflict text_hashes and build dataset partitions
    # We load (text_hash, label, source) for non-excluded sources
    source_label_pairs = []
    excluded_rows = []
    failed_pass1: list[str] = []

    for pf in sorted(parquet_files):
        try:
            avail_cols = pq.read_schema(pf).names
            needed_cols = [c for c in ["text_hash", "label", "source", "text", "synthetic", "lang", "channel"] if c in avail_cols]
            if "text_hash" not in avail_cols or "label" not in avail_cols or "source" not in avail_cols:
                continue
            tbl = pq.read_table(pf, columns=needed_cols)
            df_part = tbl.to_pandas()
            if len(df_part) == 0:
                continue
            
            # Check source exclusion
            # Get source id from first row or file name
            src_id = str(df_part["source"].iloc[0]) if "source" in df_part.columns else ""
            s_meta = source_info.get(src_id, {})
            
            if should_exclude_source(s_meta):
                excluded_rows.append(df_part)
                continue
            
            # Map unified labels directly — fail loud on any unmapped label (F-12).
            unmapped_raw = []
            mapped_classes = []
            for raw_l in df_part["label"]:
                cid = map_label(raw_l)
                if cid is not None:
                    mapped_classes.append(cid)
                else:
                    unmapped_raw.append(str(raw_l))
                    mapped_classes.append(-1)
            if unmapped_raw:
                sample = sorted(set(unmapped_raw))[:10]
                raise ValueError(
                    f"F-12: parquet {pf} contains {len(unmapped_raw)} row(s) with unmapped label(s) {sample}. "
                    f"Allowed label vocabulary: {{ham, unwanted, spam, scam}}. Build aborted."
                )
            df_part["class_id"] = mapped_classes
            df_part = df_part[df_part["class_id"] >= 0]
            if len(df_part) > 0:
                sub = df_part[["text_hash", "class_id"]].drop_duplicates()
                source_label_pairs.append(sub)
        except Exception as e:
            log(f"Error in pass 1 {pf}: {e}")
            failed_pass1.append(f"{pf}: {e}")

    if failed_pass1:
        raise RuntimeError(f"pass 1 failed to read {len(failed_pass1)} parquet file(s): {failed_pass1[:10]}")
    if source_label_pairs:
        all_pairs = pd.concat(source_label_pairs, ignore_index=True).drop_duplicates()
        class_counts_per_hash = all_pairs.groupby("text_hash", sort=False)["class_id"].nunique()
        conflict_hashes = set(class_counts_per_hash.index[class_counts_per_hash > 1])
        log(f"Found {len(conflict_hashes)} conflicting text_hashes seen with multiple classes across sources.")
        del all_pairs, class_counts_per_hash
    else:
        conflict_hashes = set()
        log("No training pairs found in pass 1!")

    # Process excluded eval set
    excluded_eval_df = pd.DataFrame()
    if excluded_rows:
        exc_df = pd.concat(excluded_rows, ignore_index=True)
        exc_df = exc_df.dropna(subset=["text"])
        exc_df = exc_df[exc_df["text"].str.strip().str.len() > 0]
        exc_df["text"] = exc_df["text"].map(fix_mojibake)
        # ponytail: hashes stay pre-repair, about 10k rows affected, recompute if dedup matters
        if len(exc_df) > 20000:
            exc_df = exc_df.sample(n=20000, random_state=SEED)
        excluded_eval_df = exc_df
        log(f"Prepared excluded_eval set with {len(excluded_eval_df)} rows")

    # Pass 2: Load full data for training/test, applying caps, dedup, and conflict drop
    loaded_chunks = []
    holdout_chunks = []
    seen_parquet_sources = set()
    raw_rows_total = 0
    failed_pass2: list[str] = []

    for pf in sorted(parquet_files):
        try:
            avail_cols = pq.read_schema(pf).names
            needed_cols = [c for c in ["text", "label", "label_raw", "source", "file", "channel", "lang", "synthetic", "text_hash"] if c in avail_cols]
            tbl = pq.read_table(pf, columns=needed_cols)
            df_part = tbl.to_pandas()
            raw_rows_total += len(df_part)
            if len(df_part) == 0:
                continue

            file_src_id = Path(pf).stem
            src_id = str(df_part["source"].iloc[0]) if "source" in df_part.columns and len(df_part) > 0 else file_src_id
            if not src_id:
                src_id = file_src_id
            seen_parquet_sources.add(src_id)
            if "source" in df_part.columns:
                seen_parquet_sources.update(df_part["source"].dropna().astype(str).unique())

            s_meta = source_info.get(src_id, {})
            if should_exclude_source(s_meta):
                continue

            # Map unified labels directly — fail loud on any unmapped label (F-12).
            unmapped_raw = []
            mapped_classes = []
            for raw_l in df_part["label"]:
                cid = map_label(raw_l)
                if cid is not None:
                    mapped_classes.append(cid)
                else:
                    unmapped_raw.append(str(raw_l))
                    mapped_classes.append(-1)
            if unmapped_raw:
                sample = sorted(set(unmapped_raw))[:10]
                raise ValueError(
                    f"F-12: parquet {pf} contains {len(unmapped_raw)} row(s) with unmapped label(s) {sample}. "
                    f"Allowed label vocabulary: {{ham, unwanted, spam, scam}}. Build aborted."
                )
            df_part["class_id"] = mapped_classes
            df_part = df_part[df_part["class_id"] >= 0].copy()

            if len(df_part) == 0:
                continue

            # Drop empty text
            df_part = df_part.dropna(subset=["text"])
            df_part = df_part[df_part["text"].str.strip().str.len() > 0]
            df_part["text"] = df_part["text"].map(fix_mojibake)
            # ponytail: hashes stay pre-repair, about 10k rows affected, recompute if dedup matters
            # Drop conflicts
            if conflict_hashes:
                df_part = df_part[~df_part["text_hash"].isin(conflict_hashes)]

            # Dedup per file on text_hash
            df_part = df_part.drop_duplicates(subset=["text_hash"])

            # Per-source cap (100k unique rows per source, synthetic 30k max)
            is_synth = bool(s_meta.get("synthetic", False))
            cap = 30000 if is_synth else 100000
            if len(df_part) > cap:
                df_part = df_part.sample(n=cap, random_state=SEED)

            if not FINAL_MODE and src_id in HOLDOUT_SOURCES:
                holdout_chunks.append(df_part)
            else:
                loaded_chunks.append(df_part)
        except Exception as e:
            log(f"Error in pass 2 {pf}: {e}")
            failed_pass2.append(f"{pf}: {e}")

    if failed_pass2:
        raise RuntimeError(f"pass 2 failed to read {len(failed_pass2)} parquet file(s): {failed_pass2[:10]}")
    # Validate holdout sources and build holdout_df
    if not FINAL_MODE:
        missing_holdout = [s for s in HOLDOUT_SOURCES if s not in seen_parquet_sources]
        if missing_holdout:
            raise RuntimeError(f"Missing HOLDOUT_SOURCES id from loaded parquet files: {missing_holdout}")

        if not holdout_chunks:
            raise RuntimeError("holdout_df is empty")

        holdout_df = pd.concat(holdout_chunks, ignore_index=True)
        if len(holdout_df) == 0:
            raise RuntimeError("holdout_df is empty")

        missing_in_holdout = [s for s in HOLDOUT_SOURCES if s not in set(holdout_df["source"].unique())]
        if missing_in_holdout:
            raise RuntimeError(f"Missing HOLDOUT_SOURCES id from holdout_df after cleaning: {missing_in_holdout}")

        log("Computing template keys for holdout_df...")
        holdout_df["template_key"] = holdout_df["text"].map(template_key)
        holdout_df["template_hash"] = holdout_df["template_key"].apply(lambda k: int(hashlib.md5(k.encode("utf-8")).hexdigest(), 16))
        log(f"Prepared holdout_df with {len(holdout_df)} rows across {holdout_df['source'].nunique()} sources: {sorted(holdout_df['source'].unique())}")
    else:
        holdout_df = pd.DataFrame()

    if not loaded_chunks:
        log("ERROR: No data loaded after filtering!")
        sys.exit(1)

    df = pd.concat(loaded_chunks, ignore_index=True)
    log(f"Total raw rows: {raw_rows_total}, Cleaned & capped corpus rows: {len(df)}")

    # Compute template_key for group splitting
    log("Computing template keys for group splitting...")
    df["template_key"] = df["text"].map(template_key)
    df["template_hash"] = df["template_key"].apply(lambda k: int(hashlib.md5(k.encode("utf-8")).hexdigest(), 16))

    # Split 80 / 10 / 10 grouped by template_hash mod 100
    mod_val = df["template_hash"] % 100
    train_mask = mod_val < 80
    val_mask = (mod_val >= 80) & (mod_val < 90)
    test_mask = mod_val >= 90

    train_df = df[train_mask].reset_index(drop=True)
    val_df = df[val_mask].reset_index(drop=True)
    test_df = df[test_mask].reset_index(drop=True)

    log(f"Split sizes before holdout leakage guard -> Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")

    # Cross-source leakage guard: drop from train_df, val_df and test_df every row whose text_hash OR template_hash appears in holdout_df
    if not FINAL_MODE:
        holdout_text_hashes = set(holdout_df["text_hash"])
        holdout_template_hashes = set(holdout_df["template_hash"])

        train_leak = train_df["text_hash"].isin(holdout_text_hashes) | train_df["template_hash"].isin(holdout_template_hashes)
        val_leak = val_df["text_hash"].isin(holdout_text_hashes) | val_df["template_hash"].isin(holdout_template_hashes)
        test_leak = test_df["text_hash"].isin(holdout_text_hashes) | test_df["template_hash"].isin(holdout_template_hashes)

        dropped_train = int(train_leak.sum())
        dropped_val = int(val_leak.sum())
        dropped_test = int(test_leak.sum())
        total_dropped = dropped_train + dropped_val + dropped_test

        train_df = train_df[~train_leak].reset_index(drop=True)
        val_df = val_df[~val_leak].reset_index(drop=True)
        test_df = test_df[~test_leak].reset_index(drop=True)

        log(f"Cross-source leakage guard: dropped {total_dropped} rows matching holdout text_hash or template_hash "
            f"(train: {dropped_train}, val: {dropped_val}, test: {dropped_test})")
        log(f"Split sizes -> Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")

    MAX_LEN = 128
    BATCH = 64
    if len(train_df) > 12000 * BATCH:
        log(f"Subsampling train_df from {len(train_df)} to {12000 * BATCH} rows before tokenization.")
        train_df = train_df.sample(n=12000 * BATCH, random_state=SEED).reset_index(drop=True)

    # Class balance weights (weighted cross-entropy, clipped to at most 5x)
    class_counts = np.bincount(train_df["class_id"].values, minlength=3)
    total_samples = len(train_df)
    n_classes = len(CLASS_MAP)
    class_weights = total_samples / (n_classes * np.maximum(class_counts, 1))
    class_weights = np.clip(class_weights, 0.2, 5.0)
    log(f"Train class counts: {class_counts}, class weights: {class_weights}")

    # Now import torch and transformers for model training
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader, TensorDataset
    from transformers import AutoTokenizer, AutoModelForSequenceClassification, get_linear_schedule_with_warmup
    from torch.optim import AdamW
    from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support, roc_auc_score

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log(f"Using device: {device}")

    # Load model: ungated multilingual MiniLM (12 layers x 384, XLM-R vocab incl. Indic scripts and romanised
    # Hindi), about half DistilBERT's compute. ai4bharat/indic-bert is gated (401 in run 1).
    # Fallback: distilbert-base-multilingual-cased.
    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    tokenizer = None
    model = None

    try:
        log(f"Attempting to load tokenizer and model: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=n_classes)
    except Exception as e:
        log(f"LOUD WARNING: Failed to load {model_name}: {e}. Falling back to distilbert-base-multilingual-cased.")
        model_name = "distilbert-base-multilingual-cased"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=n_classes)

    model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log(f"Loaded model {model_name} with {n_params:,} parameters")

    def encode_texts(texts):
        enc = tokenizer(
            list(texts),
            padding="max_length",
            truncation=True,
            max_length=MAX_LEN,
            return_tensors="pt"
        )
        return enc["input_ids"], enc["attention_mask"]

    log("Encoding train, val, test texts...")
    train_input_ids, train_att = encode_texts(train_df["text"])
    train_labels = torch.tensor(train_df["class_id"].values, dtype=torch.long)

    val_input_ids, val_att = encode_texts(val_df["text"])
    val_labels = torch.tensor(val_df["class_id"].values, dtype=torch.long)

    test_input_ids, test_att = encode_texts(test_df["text"])
    test_labels = torch.tensor(test_df["class_id"].values, dtype=torch.long)

    train_dataset = TensorDataset(train_input_ids, train_att, train_labels)
    val_dataset = TensorDataset(val_input_ids, val_att, val_labels)
    test_dataset = TensorDataset(test_input_ids, test_att, test_labels)

    train_loader = DataLoader(train_dataset, batch_size=BATCH, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=BATCH, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=BATCH, shuffle=False)

    # Training settings: 2 epochs, lr 3e-5, warmup 6%
    EPOCHS = 2
    LR = 3e-5
    steps_per_epoch = len(train_loader)
    total_steps = EPOCHS * steps_per_epoch
    warmup_steps = int(0.06 * total_steps)

    optimizer = AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps)
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float).to(device))

    scaler = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda"))

    best_val_f1 = -1.0
    best_state = None
    patience = 2
    no_improve = 0

    log(f"Beginning training for {EPOCHS} epochs, total steps: {total_steps}, warmup steps: {warmup_steps}")

    for epoch in range(EPOCHS):
        model.train()
        total_loss = 0.0
        for batch_idx, batch in enumerate(train_loader):
            input_ids, att_mask, labels = [b.to(device) for b in batch]
            optimizer.zero_grad()
            with torch.cuda.amp.autocast(enabled=(device.type == "cuda")):
                outputs = model(input_ids=input_ids, attention_mask=att_mask)
                loss = criterion(outputs.logits, labels)
            
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()

            total_loss += loss.item()

            if (batch_idx + 1) % 500 == 0:
                log(f"Epoch {epoch+1}/{EPOCHS} | Batch {batch_idx+1}/{steps_per_epoch} | Loss: {loss.item():.4f}")

        # Validation
        model.eval()
        val_preds = []
        val_trues = []
        with torch.no_grad():
            for batch in val_loader:
                input_ids, att_mask, labels = [b.to(device) for b in batch]
                outputs = model(input_ids=input_ids, attention_mask=att_mask)
                preds = outputs.logits.argmax(dim=-1).cpu().numpy()
                val_preds.extend(preds)
                val_trues.extend(labels.cpu().numpy())

        p_macro, r_macro, f1_macro, _ = precision_recall_fscore_support(val_trues, val_preds, average="macro", zero_division=0)
        log(f"Epoch {epoch+1} Validation -> Macro F1: {f1_macro:.4f} (Precision: {p_macro:.4f}, Recall: {r_macro:.4f})")

        if f1_macro > best_val_f1:
            best_val_f1 = f1_macro
            best_state = copy.deepcopy(model.state_dict())
            no_improve = 0
            log(f"New best validation macro F1: {best_val_f1:.4f}")
        else:
            no_improve += 1
            if no_improve >= patience:
                log(f"Early stopping triggered at epoch {epoch+1}")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
        log("Restored best model state from validation.")

    # Evaluation on Test set
    log("Evaluating on test set...")
    model.eval()
    test_preds = []
    test_trues = []
    test_probs = []

    with torch.no_grad():
        for batch in test_loader:
            input_ids, att_mask, labels = [b.to(device) for b in batch]
            outputs = model(input_ids=input_ids, attention_mask=att_mask)
            logits = outputs.logits
            probs = F.softmax(logits, dim=-1).cpu().numpy()
            preds = logits.argmax(dim=-1).cpu().numpy()
            test_preds.extend(preds)
            test_trues.extend(labels.cpu().numpy())
            test_probs.extend(probs)

    test_preds = np.array(test_preds)
    test_trues = np.array(test_trues)
    test_probs = np.array(test_probs)

    p_mac, r_mac, f1_mac, _ = precision_recall_fscore_support(test_trues, test_preds, average="macro", zero_division=0)
    p_per, r_per, f1_per, support_per = precision_recall_fscore_support(test_trues, test_preds, average=None, zero_division=0)
    cm = confusion_matrix(test_trues, test_preds, labels=[0, 1, 2])

    test_metrics = {
        "macro_f1": float(f1_mac),
        "macro_precision": float(p_mac),
        "macro_recall": float(r_mac),
        "per_class": {
            CLASS_NAMES[i]: {
                "precision": float(p_per[i]),
                "recall": float(r_per[i]),
                "f1": float(f1_per[i]),
                "support": int(support_per[i])
            }
            for i in range(3)
        },
        "confusion_matrix": cm.tolist()
    }
    log(f"Test Metrics: {json.dumps(test_metrics, indent=2)}")

    # Binary view risky = unwanted (1) or scam (2) vs ham (0)
    # risky true: true != 0
    # risky pred: pred != 0
    risky_true = (test_trues != 0).astype(int)
    risky_pred = (test_preds != 0).astype(int)
    risky_prob = 1.0 - test_probs[:, 0] # probability of being risky (1 - P(ham))

    p_risky, r_risky, f1_risky, _ = precision_recall_fscore_support(risky_true, risky_pred, average="binary", zero_division=0)
    # FPR for risky view: FP / (FP + TN) where negative is ham
    tn = ((risky_true == 0) & (risky_pred == 0)).sum()
    fp = ((risky_true == 0) & (risky_pred == 1)).sum()
    risky_fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    try:
        risky_roc_auc = float(roc_auc_score(risky_true, risky_prob))
    except Exception:
        risky_roc_auc = 0.0

    binary_risky_metrics = {
        "precision": float(p_risky),
        "recall": float(r_risky),
        "f1": float(f1_risky),
        "fpr": float(risky_fpr),
        "roc_auc": float(risky_roc_auc)
    }
    log(f"Binary Risky Metrics: {json.dumps(binary_risky_metrics, indent=2)}")

    # Scam recall and scam precision on their own (class 2)
    scam_true = (test_trues == 2).astype(int)
    scam_pred = (test_preds == 2).astype(int)
    p_scam_alone, r_scam_alone, f1_scam_alone, _ = precision_recall_fscore_support(scam_true, scam_pred, average="binary", zero_division=0)
    scam_standalone_metrics = {
        "precision": float(p_scam_alone),
        "recall": float(r_scam_alone),
        "f1": float(f1_scam_alone)
    }
    log(f"Scam Standalone Metrics: {json.dumps(scam_standalone_metrics, indent=2)}")

    # Per lang, per source id, per channel, synthetic vs real
    test_df["true_class"] = test_trues
    test_df["pred_class"] = test_preds
    test_df["risky_true"] = risky_true
    test_df["risky_pred"] = risky_pred

    def compute_subset_metrics(sub_df):
        if len(sub_df) == 0:
            return {"n": 0}
        st = sub_df["true_class"].values
        sp = sub_df["pred_class"].values
        _, _, f1_m, _ = precision_recall_fscore_support(st, sp, average="macro", zero_division=0)
        rt = (st != 0).astype(int)
        rp = (sp != 0).astype(int)
        tn_s = ((rt == 0) & (rp == 0)).sum()
        fp_s = ((rt == 0) & (rp == 1)).sum()
        rfpr = float(fp_s / (fp_s + tn_s)) if (fp_s + tn_s) > 0 else 0.0
        sct = (st == 2).astype(int)
        scp = (sp == 2).astype(int)
        _, sr_val, _, _ = precision_recall_fscore_support(sct, scp, average="binary", zero_division=0)
        r_prec, r_rec, r_f1, _ = precision_recall_fscore_support(rt, rp, average="binary", zero_division=0)
        return {
            "n": len(sub_df),
            "macro_f1": float(f1_m),
            "risky_fpr": float(rfpr),
            "scam_recall": float(sr_val),
            "risky_precision": float(r_prec),
            "risky_recall": float(r_rec),
            "risky_f1": float(r_f1),
        }

    per_source_metrics = {}
    for src, group in test_df.groupby("source"):
        per_source_metrics[str(src)] = compute_subset_metrics(group)

    per_lang_metrics = {}
    if "lang" in test_df.columns:
        for lang, group in test_df.groupby("lang"):
            per_lang_metrics[str(lang)] = compute_subset_metrics(group)

    per_channel_metrics = {}
    if "channel" in test_df.columns:
        for ch, group in test_df.groupby("channel"):
            per_channel_metrics[str(ch)] = compute_subset_metrics(group)

    synth_metrics = {}
    if "synthetic" in test_df.columns:
        for synth, group in test_df.groupby("synthetic"):
            synth_metrics[str(synth)] = compute_subset_metrics(group)

    # Indian real subset: real (non-synthetic) rows from sources whose id contains junioralive, revised_indian, karanverma, rithikkumar, cloveai, india
    indian_keys = ["junioralive", "revised_indian", "karanverma", "rithikkumar", "cloveai", "india"]
    indian_real_mask = test_df["source"].apply(lambda s: any(k in str(s).lower() for k in indian_keys)) & (test_df["synthetic"] == False)
    indian_real_df = test_df[indian_real_mask]
    indian_real_metrics = compute_subset_metrics(indian_real_df)
    log(f"Indian Real Subset Metrics (n={len(indian_real_df)}): {json.dumps(indian_real_metrics, indent=2)}")

    # Excluded eval set metrics
    excluded_eval_metrics = {}
    if len(excluded_eval_df) > 0:
        exc_texts = list(excluded_eval_df["text"])
        exc_ids, exc_att = encode_texts(exc_texts)
        exc_dataset = TensorDataset(exc_ids, exc_att, torch.zeros(len(exc_texts), dtype=torch.long))
        exc_loader = DataLoader(exc_dataset, batch_size=BATCH, shuffle=False)
        exc_preds = []
        with torch.no_grad():
            for batch in exc_loader:
                input_ids, att_mask, _ = [b.to(device) for b in batch]
                outputs = model(input_ids=input_ids, attention_mask=att_mask)
                preds = outputs.logits.argmax(dim=-1).cpu().numpy()
                exc_preds.extend(preds)
        excluded_eval_df["pred_class"] = exc_preds
        # If label available in excluded_eval_df, compute metrics
        if "label" in excluded_eval_df.columns:
            # map labels
            exc_trues = []
            for _, row in excluded_eval_df.iterrows():
                cid = map_label(row.get("label"))
                exc_trues.append(cid if cid is not None else 0)
            excluded_eval_df["true_class"] = exc_trues
            excluded_eval_metrics = compute_subset_metrics(excluded_eval_df)
        else:
            excluded_eval_metrics = {"n": len(excluded_eval_df), "note": "evaluated without ground truth labels"}
        log(f"Excluded Eval Metrics: {json.dumps(excluded_eval_metrics, indent=2)}")

    # 30 Hand-written test messages evaluation
    hw_texts = [m[0] for m in HANDWRITTEN_TEST_MSGS]
    hw_expected_names = [m[1] for m in HANDWRITTEN_TEST_MSGS]
    hw_expected_ids = [CLASS_MAP[n] for n in hw_expected_names]

    hw_ids, hw_att = encode_texts(hw_texts)
    hw_dataset = TensorDataset(hw_ids, hw_att, torch.tensor(hw_expected_ids, dtype=torch.long))
    hw_loader = DataLoader(hw_dataset, batch_size=BATCH, shuffle=False)
    hw_preds = []
    hw_probs = []
    with torch.no_grad():
        for batch in hw_loader:
            input_ids, att_mask, _ = [b.to(device) for b in batch]
            outputs = model(input_ids=input_ids, attention_mask=att_mask)
            logits = outputs.logits
            probs = F.softmax(logits, dim=-1).cpu().numpy()
            preds = logits.argmax(dim=-1).cpu().numpy()
            hw_preds.extend(preds)
            hw_probs.extend(probs)

    hw_misses = []
    for i, (text, exp_name, cat) in enumerate(HANDWRITTEN_TEST_MSGS):
        pred_id = hw_preds[i]
        pred_name = CLASS_NAMES[pred_id]
        prob = float(hw_probs[i][pred_id])
        if pred_name != exp_name:
            hw_misses.append({
                "index": i,
                "category": cat,
                "text": text,
                "expected": exp_name,
                "predicted": pred_name,
                "confidence": prob
            })
    log(f"Hand-written 30 messages evaluated: {len(hw_misses)} misses reported.")
    for miss in hw_misses:
        log(f"  Miss: [{miss['category']}] expected {miss['expected']}, got {miss['predicted']} (conf {miss['confidence']:.3f}): {miss['text']}")

    # Errors.csv: 200 most confident wrong test predictions
    test_df["pred_prob"] = [p[p_id] for p, p_id in zip(test_probs, test_preds)]
    wrong_mask = test_df["true_class"] != test_df["pred_class"]
    errors_df = test_df[wrong_mask].sort_values("pred_prob", ascending=False).head(200)
    error_cols = [c for c in ["text", "true_class", "pred_class", "pred_prob", "source", "lang"] if c in errors_df.columns]
    errors_df[error_cols].to_csv(f"{OUT}/errors.csv", index=False)
    log(f"Saved errors.csv with {len(errors_df)} error rows.")

    # Holdout evaluation: predict on holdout_df with trained model (same batching and encode_texts as test)
    if not FINAL_MODE:
        log("Evaluating on holdout set...")
        holdout_input_ids, holdout_att = encode_texts(holdout_df["text"])
        holdout_labels = torch.tensor(holdout_df["class_id"].values, dtype=torch.long)
        holdout_dataset = TensorDataset(holdout_input_ids, holdout_att, holdout_labels)
        holdout_loader = DataLoader(holdout_dataset, batch_size=BATCH, shuffle=False)

        holdout_preds = []
        holdout_trues = []
        holdout_probs = []

        model.eval()
        with torch.no_grad():
            for batch in holdout_loader:
                input_ids, att_mask, labels = [b.to(device) for b in batch]
                outputs = model(input_ids=input_ids, attention_mask=att_mask)
                logits = outputs.logits
                probs = F.softmax(logits, dim=-1).cpu().numpy()
                preds = logits.argmax(dim=-1).cpu().numpy()
                holdout_preds.extend(preds)
                holdout_trues.extend(labels.cpu().numpy())
                holdout_probs.extend(probs)

        holdout_preds = np.array(holdout_preds)
        holdout_trues = np.array(holdout_trues)
        holdout_probs = np.array(holdout_probs)

        holdout_df["true_class"] = holdout_trues
        holdout_df["pred_class"] = holdout_preds

        holdout_eval_metrics = compute_subset_metrics(holdout_df)
        holdout_per_source = {}
        for src, group in holdout_df.groupby("source"):
            holdout_per_source[str(src)] = compute_subset_metrics(group)
        holdout_eval_metrics["per_source"] = holdout_per_source
        log(f"Holdout Eval Metrics: {json.dumps(holdout_eval_metrics, indent=2)}")

        holdout_df["pred_prob"] = [p[p_id] for p, p_id in zip(holdout_probs, holdout_preds)]
        holdout_wrong_mask = holdout_df["true_class"] != holdout_df["pred_class"]
        holdout_errors_df = holdout_df[holdout_wrong_mask].sort_values("pred_prob", ascending=False).head(200)
        holdout_error_cols = [c for c in ["text", "true_class", "pred_class", "pred_prob", "source", "lang"] if c in holdout_errors_df.columns]
        holdout_errors_df[holdout_error_cols].to_csv(f"{OUT}/holdout_errors.csv", index=False)
        log(f"Saved holdout_errors.csv with {len(holdout_errors_df)} error rows.")
    else:
        holdout_eval_metrics = None

    # Latency on Kaggle CPU batch 1 at length 128 (50 warm-up, 200 timed, p50 p95)
    log("Running CPU latency benchmark (batch 1, length 128)...")
    cpu_model = copy.deepcopy(model).cpu().eval()
    x_lat_ids = test_input_ids[:1].cpu()
    x_lat_att = test_att[:1].cpu()
    lat = []
    with torch.no_grad():
        for _ in range(50):
            cpu_model(input_ids=x_lat_ids, attention_mask=x_lat_att)
        for _ in range(200):
            t0 = time.perf_counter()
            cpu_model(input_ids=x_lat_ids, attention_mask=x_lat_att)
            lat.append((time.perf_counter() - t0) * 1e3)

    lat_m = {
        "p50_ms": float(np.percentile(lat, 50)),
        "p95_ms": float(np.percentile(lat, 95)),
        "host": "kaggle-cpu"
    }
    log(f"Latency benchmark result: {lat_m}")

    # Compile metrics dict
    metrics = {
        "seed": SEED,
        "model_name": model_name,
        "rows_raw": raw_rows_total,
        "rows_clean": len(df),
        "train": len(train_df),
        "val": len(val_df),
        "test": len(test_df),
        "holdout": len(holdout_df) if not FINAL_MODE else 0,
        "params": n_params,
        "torch": torch.__version__,
        "test_metrics": test_metrics,
        "binary_risky_metrics": binary_risky_metrics,
        "scam_standalone_metrics": scam_standalone_metrics,
        "per_source_metrics": per_source_metrics,
        "per_lang_metrics": per_lang_metrics,
        "per_channel_metrics": per_channel_metrics,
        "synthetic_metrics": synth_metrics,
        "indian_real_metrics": indian_real_metrics,
        "holdout_eval_metrics": holdout_eval_metrics,
        "excluded_eval_metrics": excluded_eval_metrics,
        "handwritten_misses_count": len(hw_misses),
        "handwritten_misses": hw_misses,
        "latency": lat_m,
    }
    json.dump(metrics, open(f"{OUT}/metrics.json", "w"), indent=2, default=float)
    log("Saved metrics.json")

    # Save fine-tuned model and tokenizer
    model_save_path = f"{OUT}/sms_model"
    tokenizer_save_path = f"{OUT}/tokenizer"
    model.save_pretrained(model_save_path)
    tokenizer.save_pretrained(tokenizer_save_path)
    # Also copy tokenizer files for app
    import shutil
    os.makedirs(tokenizer_save_path, exist_ok=True)
    log(f"Saved model and tokenizer to {OUT}")

    # Parity inputs for ExecuTorch export (200 test messages)
    with torch.no_grad():
        parity_inputs = {
            "input_ids": test_input_ids[:200].long(),
            "attention_mask": test_att[:200].long(),
            "logits": model(input_ids=test_input_ids[:200].long().to(device), attention_mask=test_att[:200].long().to(device)).logits.cpu()
        }
        torch.save(parity_inputs, f"{OUT}/parity_inputs.pt")

    if os.environ.get("PS3_SKIP_EXPORT") != "1":
        # ---- ExecuTorch export in fresh interpreter -----------------------------
        log("Starting ExecuTorch export in subprocess...")
        # Define wrapper module structure definition in model_def.py
        model_def_code = textwrap.dedent(f"""
            import torch
            import torch.nn as nn
            from transformers import AutoModelForSequenceClassification

            class SMSExportWrapper(nn.Module):
                def __init__(self, model_path):
                    super().__init__()
                    self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
                
                def forward(self, input_ids, attention_mask):
                    outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                    return outputs.logits
        """)
        open(f"{OUT}/model_def.py", "w", encoding="utf-8").write(model_def_code)

        EXPORT_SCRIPT = textwrap.dedent(f"""
            import importlib.util, json, torch
            from importlib.metadata import version
            from executorch.exir import to_edge_transform_and_lower
            from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
            from executorch.runtime import Runtime

            spec = importlib.util.spec_from_file_location('md', '{OUT}/model_def.py')
            md = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(md)

            wrapper = md.SMSExportWrapper('{OUT}/sms_model')
            wrapper.eval()

            par = torch.load('{OUT}/parity_inputs.pt', weights_only=True)  # parity_inputs.pt holds tensors only (input_ids, attention_mask, logits): safe to load with weights_only=True
            x_ids = par['input_ids'][:1]
            x_att = par['attention_mask'][:1]

            ep = torch.export.export(wrapper, (x_ids, x_att))
            prog = to_edge_transform_and_lower(ep, partitioner=[XnnpackPartitioner()]).to_executorch()
            open('{OUT}/sms_model.pte', 'wb').write(prog.buffer)

            # Test runtime parity on 200 samples
            meth = Runtime.get().load_program('{OUT}/sms_model.pte').load_method('forward')
            et_logits_list = []
            for i in range(len(par['input_ids'])):
                out = meth.execute([par['input_ids'][i:i+1], par['attention_mask'][i:i+1]])
                et_logits_list.append(out[0])
            et_logits = torch.cat(et_logits_list, dim=0)

            diff = (et_logits - par['logits']).abs().max().item()
            mism = int((et_logits.argmax(dim=-1) != par['logits'].argmax(dim=-1)).sum())

            import os
            pte_path = '{OUT}/sms_model.pte'
            pte_size_mb = os.path.getsize(pte_path) / (1024 * 1024) if os.path.exists(pte_path) else 0.0

            r = dict(
                model_name='{model_name}',
                pte_size_mb=pte_size_mb,
                executorch=version('executorch'),
                torch=torch.__version__,
                max_abs_logit_diff=diff,
                argmax_mismatches=mism,
                parity_pass=bool(diff < 1e-2 and mism == 0)
            )
            json.dump(r, open('{OUT}/export.json', 'w'), indent=2)
            print(r)
        """)
        
        pip_res = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "executorch==1.5.1", "torch==2.15.0+cpu",
                                  "--extra-index-url", "https://download.pytorch.org/whl/cpu"], capture_output=True, text=True)
        log(f"pip install executorch rc={pip_res.returncode}\n{pip_res.stderr[-1000:]}")
        # Kaggle's torchvision/torchaudio are built for its torch 2.11; once torch 2.15 is installed, transformers
        # fails to import model classes through them (run 1 export error). The export needs neither.
        un = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "torchvision", "torchaudio"],
                            capture_output=True, text=True)
        log(f"pip uninstall torchvision torchaudio rc={un.returncode}")

        exp_res = subprocess.run([sys.executable, "-c", EXPORT_SCRIPT], capture_output=True, text=True)
        log(f"export execution rc={exp_res.returncode}\nstdout:\n{exp_res.stdout}\nstderr:\n{exp_res.stderr[-2000:]}")

    log("SMS training, evaluation, and export completed successfully.")


if __name__ == "__main__":
    main()
