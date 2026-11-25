"""Machine-translate English SMS training rows into Tamil and Hindi (IndicTrans2, MIT).

Kaggle script kernel for the multilang experiment (docs/multilang/PLAN_PREREGISTERED.md).
Input: the attached private dataset ps3-sms-corpus (sms/*.parquet + source_map.yaml).
Output: /kaggle/working/mt_<lang>.parquet and mt_summary.json. Rows are synthetic.

Leak removal against the held-out and golden sets is done locally after download
(data/tools/remove_ml_leaks.py); those files are deliberately not uploaded.

shortcut: rows are not restricted to the train part of the template split. Translated rows
are used for training only and acceptance is judged on external sets, so the only exposure
is the internal English test split, which is not an acceptance metric.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time

LIMIT = int(os.environ.get("MT_LIMIT", "0")) or None  # rows per class per language; None = full
SMOKE = os.environ.get("MT_SMOKE", "0") == "1"  # 30-row smoke version
TARGET = {"scam": 12000, "ham": 12000, "unwanted": 6000}
LANGS = {"ta": "tam_Taml", "hi": "hin_Deva"}
MODEL = "ai4bharat/indictrans2-en-indic-dist-200M"
SEED = 20261110
INPUT_DIR = os.environ.get("PS3_INPUT_DIR", "/kaggle/input")
OUT = os.environ.get("PS3_OUT_DIR", "/kaggle/working")

URL_RE = re.compile(r"(?:h(?:tt|xx)ps?://|www\.)[^\s<>\"']+|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/[^\s<>\"']*)?", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*")
DIGITS_RE = re.compile(r"\d{4,}")
TPL_URL_RE = re.compile(r"(?:h(?:tt|xx)ps?://|www\.|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{2,})+)[^\s<>\"']*", re.I)
SCRIPT_RANGES = {"ta": (0x0B80, 0x0BFF), "hi": (0x0900, 0x097F)}


def template_key(text):
    """Same rule as training/sms/train_sms.py:template_key."""
    text = TPL_URL_RE.sub(" u ", text)
    text = re.sub(r"\d+", "0", text)
    return " ".join(text.lower().split())


def should_exclude_source(entry):
    """Same rule as training/sms/train_sms.py:should_exclude_source."""
    if entry.get("preprocessed") is True or entry.get("skip") is True:
        return True
    return str(entry.get("channel", "")).lower() in ("email", "job_post")


EN_WORDS = set("the you your to is a for and of in on this that with have has will be are we i me my it at "
               "from not no please call now can do if or as an by our was get got just so but".split())
INDIA_RE = re.compile(r"₹|\brs\.?\s?\d|\binr\b|\bupi\b|\bkyc\b|aadhaa?r|\bpan\b|\bsbi\b|hdfc|icici|\baxis\b|paytm|"
                      r"phonepe|gpay|\blakh|\bcrore|\+91|\bjio\b|airtel|\bvi\b|bsnl|irctc|\botp\b|\bneft\b|\bimps\b", re.I)


def looks_english(text):
    """True when the text has at least three distinct common English words.

    The corpus has rows tagged English that are Portuguese or Tagalog; translating those
    gives transliterated noise, so they are kept out of the pool.
    """
    return len(EN_WORDS & set(re.findall(r"[a-z']+", text.lower()))) >= 3


def fix_punctuation(text, lang):
    """Undo two IndicTrans2 output quirks: colon as visarga, and a space inside 1,000."""
    visarga = "ஃ" if lang == "ta" else "ः"
    text = re.sub(visarga + r"(?=\s|$|\d|https?:)", ":", text)
    return re.sub(r"(\d),\s(\d{3})\b", r"\1,\2", text)


def must_keep(text):
    """Tokens that have to survive translation byte-identical."""
    keep = set(URL_RE.findall(text)) | set(EMAIL_RE.findall(text)) | set(DIGITS_RE.findall(text))
    return {k.rstrip(".,;:!?)") for k in keep if len(k) >= 4}


def script_share(text, lang):
    lo, hi = SCRIPT_RANGES[lang]
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(lo <= ord(c) <= hi for c in letters) / len(letters)


def check_row(src, out, lang):
    """Return a drop reason, or None when the translated row is usable."""
    if not out or len(out.strip()) < 10:
        return "too_short"
    missing = [k for k in must_keep(src) if k not in out]
    if missing:
        return "lost_token"
    # Messages that are mostly a URL legitimately stay Latin-heavy; require some target script.
    if script_share(out, lang) < 0.3:
        return "wrong_script"
    return None


def sample_rows(df, per_class, seed):
    """Stratified sample: per class, no source above 25 percent of the class target."""
    import pandas as pd
    parts = []
    for label, n in per_class.items():
        pool = df[df["label"] == label]
        cap = max(1, n // 4)
        pool = pool.sample(frac=1.0, random_state=seed)
        # Rows with Indian markers (Rs, UPI, KYC, bank names) first: they are the target domain.
        if "india" in pool.columns:
            pool = pool.sort_values("india", ascending=False, kind="stable")
        pool = pool.groupby("source", sort=False).head(cap)
        if "india" in pool.columns:
            pool = pool.sort_values("india", ascending=False, kind="stable")
        parts.append(pool.head(n))
    return pd.concat(parts, ignore_index=True)


def load_pool():
    import pandas as pd
    import yaml
    # Local runs name the two inputs directly; on Kaggle they are searched under /kaggle/input.
    local_map, local_sms = os.environ.get("PS3_SOURCE_MAP"), os.environ.get("PS3_SMS_DIR")
    found = [local_map] if local_map else sorted(glob.glob(f"{INPUT_DIR}/**/source_map.yaml", recursive=True))
    if not found:
        raise RuntimeError(f"source_map.yaml not found under {INPUT_DIR}")
    smap = {e["id"]: e for e in yaml.safe_load(open(found[0], encoding="utf-8")) if "id" in e}
    if local_sms:
        files = sorted(glob.glob(f"{local_sms}/*.parquet"))
    else:
        files = sorted(p for p in glob.glob(f"{INPUT_DIR}/**/*.parquet", recursive=True)
                       if os.path.basename(os.path.dirname(p)) == "sms")
    if not files or len(smap) < 50:
        raise RuntimeError(f"corpus looks wrong: {len(files)} parquet files, {len(smap)} sources")
    frames = []
    for pf in files:
        df = pd.read_parquet(pf, columns=["text", "label", "source"])
        if df.empty:
            continue
        meta = smap.get(str(df["source"].iloc[0]), {})
        if should_exclude_source(meta) or str(meta.get("lang", "")).lower() != "en":
            continue
        df["label"] = df["label"].astype(str).str.lower().replace({"spam": "unwanted"})
        df = df[df["label"].isin(TARGET)]
        df = df[df["text"].astype(str).str.len().between(20, 400)]
        df = df[df["text"].map(lambda t: t.isascii() or sum(c.isascii() for c in t) / len(t) > 0.95)]
        df = df[df["text"].map(looks_english)]
        frames.append(df)
    pool = pd.concat(frames, ignore_index=True)
    pool["india"] = pool["text"].map(lambda t: bool(INDIA_RE.search(t)))
    pool["tpl"] = pool["text"].map(template_key)
    pool = pool.drop_duplicates(subset=["tpl"])
    print(f"pool: {len(pool)} rows from {pool['source'].nunique()} English sources", flush=True)
    print(pool.groupby("label").size().to_string(), flush=True)
    return pool


def main():
    if os.path.isdir("/kaggle"):
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "transformers<5", "IndicTransToolkit", "sacremoses"])
    os.makedirs(OUT, exist_ok=True)
    import hashlib
    import pandas as pd
    import torch
    from IndicTransToolkit.processor import IndicProcessor
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    import transformers
    print("torch", torch.__version__, "transformers", transformers.__version__, "cuda", torch.cuda.is_available(), flush=True)

    per_class = {k: (30 if SMOKE else (LIMIT or v)) for k, v in TARGET.items()}
    if SMOKE:
        per_class = {"scam": 12, "ham": 12, "unwanted": 6}
    pool = load_pool()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        MODEL, trust_remote_code=True, torch_dtype=torch.float16 if device == "cuda" else torch.float32).to(device).eval()
    ip = IndicProcessor(inference=True)
    use_cache = True
    summary = {"model": MODEL, "seed": SEED, "per_class_target": per_class, "langs": {}}

    for i, (lang, tag) in enumerate(LANGS.items()):
        rows = sample_rows(pool, per_class, SEED + i)
        # Length-sorted batches keep padding small; an 8 GB laptop GPU ran out of memory at 48 mixed rows.
        rows = rows.assign(_len=rows["text"].str.len()).sort_values("_len", kind="stable").drop(columns="_len").reset_index(drop=True)
        texts = rows["text"].tolist()
        outs, t0, bs = [], time.time(), 24

        def translate(chunk):
            batch = ip.preprocess_batch(chunk, src_lang="eng_Latn", tgt_lang=tag)
            enc = tok(batch, truncation=True, padding="longest", max_length=256, return_tensors="pt").to(device)
            try:
                with torch.no_grad():
                    gen = model.generate(**enc, use_cache=True, max_length=256, num_beams=3)
            except RuntimeError as error:
                if "out of memory" not in str(error).lower() or len(chunk) == 1:
                    raise
                del enc
                torch.cuda.empty_cache()
                half = len(chunk) // 2
                return translate(chunk[:half]) + translate(chunk[half:])
            dec = tok.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=True)
            return ip.postprocess_batch(dec, lang=tag)

        for start in range(0, len(texts), bs):
            chunk = texts[start:start + bs]
            outs.extend(translate(chunk))
            if start % (bs * 50) == 0:
                print(f"{lang}: {start + len(chunk)}/{len(texts)} in {time.time() - t0:.0f}s", flush=True)
        rows = rows.assign(mt=[fix_punctuation(o, lang) for o in outs])
        rows["drop"] = [check_row(s, o, lang) for s, o in zip(rows["text"], rows["mt"])]
        kept = rows[rows["drop"].isna()].drop_duplicates(subset=["mt"])
        out_df = pd.DataFrame({
            "text": kept["mt"],
            "label": kept["label"],
            "label_raw": kept["label"],
            "source": f"sms_mt_indictrans2_{lang}",
            "file": "mt_" + lang,
            "channel": "sms",
            "lang": lang,
            "synthetic": True,
            "text_hash": kept["mt"].map(lambda t: hashlib.sha1(t.encode("utf-8")).hexdigest()),
            "origin": "mt_indictrans2",
            "source_id": kept["source"],
            "source_text": kept["text"],
        })
        out_df.to_parquet(f"{OUT}/mt_{lang}.parquet", index=False)
        summary["langs"][lang] = {
            "selected": int(len(rows)),
            "dropped": {k: int(v) for k, v in rows["drop"].value_counts().items()},
            "kept": int(len(out_df)),
            "kept_by_class": {k: int(v) for k, v in out_df["label"].value_counts().items()},
            "kept_with_india_marker": int(kept["india"].sum()),
            "sources": int(kept["source"].nunique()),
            "seconds": round(time.time() - t0, 1),
            "use_cache": use_cache,
        }
        print(json.dumps(summary["langs"][lang]), flush=True)
        for _, r in out_df.sample(n=min(10, len(out_df)), random_state=1).iterrows():
            print(f"[{lang}/{r['label']}] {r['source_text'][:200]}\n   => {r['text'][:200]}", flush=True)

    json.dump(summary, open(f"{OUT}/mt_summary.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
