import os
import sys
import json
import argparse
import hashlib
import re
import zipfile
import fnmatch
import io
from pathlib import Path
from collections import Counter, defaultdict
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import tldextract
import yaml
from sentinel.url_features import normalise_url

# Initialize tldextract offline
extractor = tldextract.TLDExtract(suffix_list_urls=())

KNOWN_DOMAINS = {
    "google.com",
    "wikipedia.org",
    "amazon.in",
    "sbi.co.in",
    "microsoft.com",
    "youtube.com",
    "irctc.co.in",
    "facebook.com"
}

TABULAR_EXTS = {".csv", ".tsv", ".txt", ".json", ".jsonl", ".parquet", ".xlsx", ".xls"}
SKIP_NAMES = {"dataset-metadata.json", ".gitattributes"}

# S-3: source_map.yaml names two WhatsApp exports anonymously as
# "WhatsApp Chat with chat_1.txt" / "chat_2.txt" so no phone number is
# committed. Downloaded copies on disk may still carry the original
# "WhatsApp Chat with <phone number>.txt" names. The helpers below map a
# canonical chat_N path to the corresponding downloaded file by sorted
# order, without storing any phone number in code: legacy exports are
# those whose name after the prefix is digits/spaces only, so named
# chats (with letters) never match.
_WHATSAPP_CHAT_PREFIX = "WhatsApp Chat with "
_CHAT_ALIAS_RE = re.compile(r"chat_(\d+)")


def legacy_whatsapp_chat_files(parent: Path) -> list[Path]:
    """Return downloaded WhatsApp exports named with a phone number, sorted."""
    if not parent.is_dir():
        return []
    legacy = []
    for p in sorted(parent.glob(_WHATSAPP_CHAT_PREFIX + "*.txt")):
        middle = p.name[len(_WHATSAPP_CHAT_PREFIX):-len(".txt")]
        if middle and any(c.isdigit() for c in middle) and not any(c.isalpha() for c in middle):
            legacy.append(p)
    return legacy


def resolve_legacy_chat_file(canonical_path: Path) -> Path | None:
    """Map an anonymised ``chat_N`` path to its downloaded legacy file.

    ``chat_1`` maps to the first legacy export in sorted order, ``chat_2``
    to the second, and so on. Returns None when the canonical path is not
    a chat_N name or no corresponding legacy file is present.
    """
    match = _CHAT_ALIAS_RE.search(canonical_path.stem)
    if not match:
        return None
    legacy = legacy_whatsapp_chat_files(canonical_path.parent)
    index = int(match.group(1)) - 1
    if 0 <= index < len(legacy):
        return legacy[index]
    return None


resolve_source_file = resolve_legacy_chat_file

# PyArrow schemas
SMS_PYARROW_SCHEMA = pa.schema([
    ("text", pa.string()),
    ("label", pa.string()),
    ("label_raw", pa.string()),
    ("source", pa.string()),
    ("file", pa.string()),
    ("channel", pa.string()),
    ("lang", pa.string()),
    ("synthetic", pa.bool_()),
    ("text_hash", pa.string()),
])

URL_PYARROW_SCHEMA = pa.schema([
    ("url", pa.string()),
    ("label", pa.string()),
    ("label_raw", pa.string()),
    ("source", pa.string()),
    ("file", pa.string()),
    ("norm_url", pa.string()),
    ("host", pa.string()),
    ("registered_domain", pa.string()),
    ("has_path", pa.bool_()),
])

def compute_text_hash(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    collapsed = " ".join(text.strip().lower().split())
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()

def process_url_record(url_str, label, label_raw, source, file):
    if not url_str or not isinstance(url_str, str):
        return None, "empty_url"
    url_str = url_str.strip()
    if not url_str:
        return None, "empty_url"
    
    norm = normalise_url(url_str)
    try:
        p = urlparse(norm if "://" in norm else "http://" + norm)
        host = (p.hostname or "").lower()
    except ValueError:  # e.g. "Invalid IPv6 URL" from a stray '[': drop the row, keep the run alive
        return None, "malformed_url"
    if not host and "/" in norm:
        host = norm.split("/")[0].lower()
    elif not host:
        host = norm.lower()

    ext = extractor(host)
    reg_domain = f"{ext.domain}.{ext.suffix}" if (ext.domain and ext.suffix) else host
    has_path = bool(p.path and p.path != "/")

    return {
        "url": url_str,
        "label": label,
        "label_raw": str(label_raw),
        "source": source,
        "file": file,
        "norm_url": norm,
        "host": host,
        "registered_domain": reg_domain,
        "has_path": has_path
    }, None

def map_label(raw_val, label_map):
    if label_map is None:
        return None, "no_label_map"
    if raw_val in label_map:
        return label_map[raw_val], None
    if isinstance(raw_val, float) and raw_val.is_integer() and int(raw_val) in label_map:
        return label_map[int(raw_val)], None
    if isinstance(raw_val, int) and float(raw_val) in label_map:
        return label_map[float(raw_val)], None
    
    s_val = str(raw_val).strip()
    if s_val in label_map:
        return label_map[s_val], None
    
    s_lower = s_val.lower()
    if s_lower in label_map:
        return label_map[s_lower], None
    
    if pd.isna(raw_val):
        # YAML parses bare `nan`/`NaN` as float NaN keys; match them explicitly so
        # unlabelled rows are counted as `drop_label` instead of `unmapped_label`.
        # (Cannot use `float("nan") in label_map` — NaN != NaN.)
        for key in label_map:
            if pd.isna(key):
                return "DROP", None

    return None, "unmapped_label"

def stream_entry_raw_batches(entry, raw_dir, limit=0, chunksize=10000):
    fmt = entry.get("format", "csv")
    path_pattern = entry["path"]
    read_opts = entry.get("read_options") or {}
    chunk_sz = min(chunksize, limit) if limit > 0 else chunksize

    if fmt == "folder_docs":
        dir_path = raw_dir / path_pattern
        if dir_path.is_dir():
            txt_files = sorted(dir_path.glob("*.txt"))
            if limit > 0:
                txt_files = txt_files[:limit]
            current_batch = []
            for tf in txt_files:
                try:
                    with open(tf, "r", encoding=read_opts.get("encoding", "latin1"), errors="ignore") as fx:
                        content = fx.read()
                    rel_file = str(tf.relative_to(raw_dir)).replace("\\", "/")
                    current_batch.append(({"text": content}, rel_file))
                    if len(current_batch) >= chunk_sz:
                        yield current_batch
                        current_batch = []
                except Exception:
                    continue
            if current_batch:
                yield current_batch
        return

    # Find matching files
    rel_overrides: dict[Path, str] = {}
    if any(c in path_pattern for c in "*?[]"):
        matching_files = sorted(raw_dir.glob(path_pattern))
    else:
        single_p = raw_dir / path_pattern
        if single_p.exists():
            matching_files = [single_p]
        else:
            legacy = resolve_legacy_chat_file(single_p)
            matching_files = [legacy] if legacy is not None else []
            if legacy is not None:
                rel_overrides[legacy] = str(single_p.relative_to(raw_dir)).replace("\\", "/")

    rows_yielded = 0
    for fpath in matching_files:
        if limit > 0 and rows_yielded >= limit:
            break
        rel_f = rel_overrides.get(fpath, str(fpath.relative_to(raw_dir)).replace("\\", "/"))
        if fmt in ("csv", "tsv"):
            enc = read_opts.get("encoding", "utf-8")
            sep = "\t" if fmt == "tsv" else read_opts.get("sep", ",")
            hdr = read_opts.get("header", "infer")
            names = read_opts.get("names", None)
            on_bad = read_opts.get("on_bad_lines", "skip")
            try:
                reader = pd.read_csv(
                    fpath,
                    sep=sep,
                    encoding=enc,
                    header=hdr,
                    names=names,
                    on_bad_lines=on_bad,
                    chunksize=chunk_sz,
                    low_memory=False
                )
                for chunk in reader:
                    batch = [(row, rel_f) for row in chunk.to_dict(orient="records")]
                    rows_yielded += len(batch)
                    yield batch
                    if limit > 0 and rows_yielded >= limit:
                        break
            except UnicodeDecodeError:
                reader = pd.read_csv(
                    fpath,
                    sep=sep,
                    encoding="latin1",
                    header=hdr,
                    names=names,
                    on_bad_lines=on_bad,
                    chunksize=chunk_sz,
                    low_memory=False
                )
                for chunk in reader:
                    batch = [(row, rel_f) for row in chunk.to_dict(orient="records")]
                    rows_yielded += len(batch)
                    yield batch
                    if limit > 0 and rows_yielded >= limit:
                        break
            except Exception as e:
                print(f"Error reading {rel_f}: {e}", file=sys.stderr)

        elif fmt == "zip_csv":
            try:
                with zipfile.ZipFile(fpath, "r") as z:
                    member = read_opts.get("zip_member")
                    if not member:
                        csvs = [m for m in z.namelist() if m.lower().endswith(".csv")]
                        member = csvs[0] if csvs else z.namelist()[0]
                    with z.open(member) as zf:
                        wrapper = io.TextIOWrapper(zf, encoding=read_opts.get("encoding", "utf-8"), errors="ignore")
                        hdr = read_opts.get("header", "infer")
                        names = read_opts.get("names", None)
                        reader = pd.read_csv(wrapper, header=hdr, names=names, chunksize=chunk_sz, low_memory=False)
                        for chunk in reader:
                            batch = [(row, rel_f) for row in chunk.to_dict(orient="records")]
                            rows_yielded += len(batch)
                            yield batch
                            if limit > 0 and rows_yielded >= limit:
                                break
            except Exception as e:
                print(f"Error reading zip {rel_f}: {e}", file=sys.stderr)

        elif fmt == "jsonl":
            try:
                current_batch = []
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fx:
                    for line in fx:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            current_batch.append((obj, rel_f))
                            rows_yielded += 1
                            if len(current_batch) >= chunk_sz:
                                yield current_batch
                                current_batch = []
                            if limit > 0 and rows_yielded >= limit:
                                break
                        except Exception:
                            continue
                if current_batch:
                    yield current_batch
            except Exception as e:
                print(f"Error reading jsonl {rel_f}: {e}", file=sys.stderr)

        elif fmt == "json":
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fx:
                    data = json.load(fx)
                rows = []
                if isinstance(data, dict):
                    if "rows" in data and isinstance(data["rows"], list):
                        rows = data["rows"]
                    elif "smsCorpus" in data and isinstance(data["smsCorpus"], dict) and "message" in data["smsCorpus"]:
                        for m in data["smsCorpus"]["message"]:
                            txt = m.get("text", {})
                            val = txt.get("$", "") if isinstance(txt, dict) else str(txt)
                            rows.append({"text": val})
                    elif "data" in data and isinstance(data["data"], list):
                        rows = data["data"]
                    else:
                        rows = [data]
                elif isinstance(data, list):
                    rows = data
                
                if limit > 0:
                    rows = rows[:limit]

                for i in range(0, len(rows), chunk_sz):
                    batch = rows[i:i + chunk_sz]
                    yield [(row, rel_f) for row in batch]
            except Exception as e:
                print(f"Error reading json {rel_f}: {e}", file=sys.stderr)

        elif fmt in ("xlsx", "xls"):
            try:
                sheet = read_opts.get("sheet_name", 0)
                df = pd.read_excel(fpath, sheet_name=sheet, nrows=limit if limit > 0 else None)
                rows = df.to_dict(orient="records")
                for i in range(0, len(rows), chunk_sz):
                    batch = rows[i:i + chunk_sz]
                    yield [(row, rel_f) for row in batch]
            except Exception as e:
                print(f"Error reading excel {rel_f}: {e}", file=sys.stderr)

        elif fmt == "parquet":
            try:
                pf = pq.ParquetFile(fpath)
                for b in pf.iter_batches(batch_size=chunk_sz):
                    df_b = b.to_pandas()
                    batch = [(row, rel_f) for row in df_b.to_dict(orient="records")]
                    rows_yielded += len(batch)
                    yield batch
                    if limit > 0 and rows_yielded >= limit:
                        break
            except Exception as e:
                print(f"Error reading parquet {rel_f}: {e}", file=sys.stderr)

        elif fmt == "txt_lines":
            try:
                current_batch = []
                col = entry.get("text_col", "text") if entry.get("corpus") == "sms" else entry.get("url_col", "url")
                with open(fpath, "r", encoding=read_opts.get("encoding", "utf-8"), errors="ignore") as fx:
                    for line in fx:
                        line = line.strip()
                        if line:
                            current_batch.append(({col: line}, rel_f))
                            rows_yielded += 1
                            if len(current_batch) >= chunk_sz:
                                yield current_batch
                                current_batch = []
                            if limit > 0 and rows_yielded >= limit:
                                break
                if current_batch:
                    yield current_batch
            except Exception as e:
                print(f"Error reading txt_lines {rel_f}: {e}", file=sys.stderr)

def process_entry(entry, raw_dir, processed_dir, limit=0):
    entry_id = entry["id"]
    corpus = entry["corpus"]
    out_dir = processed_dir / corpus
    out_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = out_dir / f"{entry_id}.parquet"
    tmp_parquet = out_dir / f"{entry_id}.parquet.tmp"

    schema = SMS_PYARROW_SCHEMA if corpus == "sms" else URL_PYARROW_SCHEMA
    writer = pq.ParquetWriter(tmp_parquet, schema=schema, compression="snappy")

    stats = {
        "rows_kept": 0,
        "label_counts": {},
        "drops": {"empty_text": 0, "empty_url": 0, "unmapped_label": 0, "drop_label": 0},
    }
    unmapped_counter = Counter()
    homepage_counts = Counter()
    hosted_counts = Counter()
    known_site_counts = Counter()
    known_site_labels = defaultdict(lambda: Counter())

    fixed_label = entry.get("fixed_label")
    label_col = entry.get("label_col")
    label_map = entry.get("label_map")
    text_col = entry.get("text_col", "text")
    url_col = entry.get("url_col", "url")
    channel = entry.get("channel", "sms" if corpus == "sms" else "web")
    fixed_lang = entry.get("lang", "en")
    lang_col = entry.get("lang_col")
    lang_map = entry.get("lang_map") or {}
    synthetic = bool(entry.get("synthetic", False))
    source_name = entry.get("source", entry_id)

    rows_kept = 0

    try:
        for raw_batch in stream_entry_raw_batches(entry, raw_dir, limit=limit, chunksize=5000):
            batch_records = []
            for row_dict, rel_file in raw_batch:
                if limit > 0 and rows_kept >= limit:
                    break

                # Extract label
                if fixed_label:
                    unified_lbl = fixed_label
                    raw_lbl_str = fixed_label
                else:
                    if label_col == "messages" and isinstance(row_dict.get("messages"), list):
                        msgs = row_dict.get("messages", [])
                        asst_msg = next((m.get("content", "") for m in msgs if m.get("role") == "assistant"), "")
                        raw_val = asst_msg.strip().split(",")[-1].strip()
                    else:
                        raw_val = row_dict.get(label_col)

                    unified_lbl, err = map_label(raw_val, label_map)
                    if err:
                        stats["drops"]["unmapped_label"] += 1
                        unmapped_counter[str(raw_val)] += 1
                        continue
                    if unified_lbl == "DROP":
                        stats["drops"]["drop_label"] += 1
                        continue
                    raw_lbl_str = str(raw_val)

                if corpus == "sms":
                    if text_col == "messages" and isinstance(row_dict.get("messages"), list):
                        msgs = row_dict.get("messages", [])
                        text_val = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
                    else:
                        text_val = row_dict.get(text_col, "")
                    
                    if not text_val or not isinstance(text_val, str) or not text_val.strip():
                        stats["drops"]["empty_text"] += 1
                        continue
                    
                    text_str = text_val.strip()
                    t_hash = compute_text_hash(text_str)

                    # Determine language
                    if lang_col and row_dict.get(lang_col):
                        raw_l = str(row_dict.get(lang_col)).strip()
                        row_lang = lang_map.get(raw_l, raw_l.lower())
                    else:
                        row_lang = fixed_lang

                    rec = {
                        "text": text_str,
                        "label": unified_lbl,
                        "label_raw": raw_lbl_str,
                        "source": source_name,
                        "file": rel_file,
                        "channel": channel,
                        "lang": row_lang,
                        "synthetic": synthetic,
                        "text_hash": t_hash,
                    }
                    batch_records.append(rec)
                    rows_kept += 1
                    stats["label_counts"][unified_lbl] = stats["label_counts"].get(unified_lbl, 0) + 1

                elif corpus == "url":
                    u_val = row_dict.get(url_col)
                    if u_val is None:
                        u_val = row_dict.get(url_col.upper()) or row_dict.get(url_col.lower()) or row_dict.get(url_col.capitalize(), "")
                    if isinstance(u_val, float) and pd.isna(u_val):
                        stats["drops"]["empty_url"] += 1
                        continue
                    rec, err = process_url_record(u_val, unified_lbl, raw_lbl_str, source_name, rel_file)
                    if err:
                        stats["drops"][err] = stats["drops"].get(err, 0) + 1
                        continue

                    # Sanity check known site tracking
                    reg_domain = rec["registered_domain"]
                    if reg_domain in KNOWN_DOMAINS:
                        host = rec["host"]
                        host_minus_www = host[4:] if host.startswith("www.") else host
                        is_homepage = (host_minus_www in KNOWN_DOMAINS) and (not rec["has_path"])
                        if is_homepage:
                            homepage_counts[unified_lbl] += 1
                        else:
                            hosted_counts[unified_lbl] += 1
                        known_site_counts[unified_lbl] += 1
                        known_site_labels[reg_domain][unified_lbl] += 1
                    batch_records.append(rec)
                    rows_kept += 1
                    stats["label_counts"][unified_lbl] = stats["label_counts"].get(unified_lbl, 0) + 1

            if batch_records:
                col_data = {col_name: [r[col_name] for r in batch_records] for col_name in schema.names}
                table = pa.Table.from_pydict(col_data, schema=schema)
                writer.write_table(table)

            if limit > 0 and rows_kept >= limit:
                break
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        try:
            if tmp_parquet.exists():
                tmp_parquet.unlink()
        except Exception:
            pass
        raise
    else:
        writer.close()

    stats["rows_kept"] = rows_kept
    if unmapped_counter:
        stats["unmapped_labels_top5"] = [k for k, _ in unmapped_counter.most_common(5)]

    if corpus == "url":
        total_homepage = sum(homepage_counts.values())
        non_benign_homepage = total_homepage - homepage_counts.get("benign", 0)
        probable_inversion = bool(total_homepage > 0 and (non_benign_homepage > total_homepage / 2))
        stats["homepage_rows"] = dict(homepage_counts)
        stats["hosted_rows"] = dict(hosted_counts)
        stats["known_site_labels"] = {k: dict(v) for k, v in known_site_labels.items()}
        stats["known_site_counts"] = dict(known_site_counts)
        stats["probable_inversion"] = probable_inversion

    if rows_kept == 0:
        try:
            if tmp_parquet.exists():
                tmp_parquet.unlink()
        except Exception:
            pass
        try:
            if out_parquet.exists():
                out_parquet.unlink()
        except Exception:
            pass
    else:
        tmp_parquet.replace(out_parquet)

    return stats

def compute_corpus_totals(processed_dir, corpus):
    corpus_dir = processed_dir / corpus
    parquet_files = sorted(corpus_dir.glob("*.parquet"))
    if not parquet_files:
        return {"total_rows": 0, f"unique_{'text_hash' if corpus == 'sms' else 'norm_url'}": 0, "label_conflicts_count": 0, "label_conflicts_examples": []}

    id_col = "text_hash" if corpus == "sms" else "norm_url"
    
    dfs = []
    for pf in parquet_files:
        try:
            tbl = pq.read_table(pf, columns=[id_col, "label"])
            df = tbl.to_pandas()
            if not df.empty:
                dfs.append(df)
        except Exception as e:
            print(f"Error reading totals from {pf}: {e}", file=sys.stderr)

    if not dfs:
        return {"total_rows": 0, f"unique_{id_col}": 0, "label_conflicts_count": 0, "label_conflicts_examples": []}

    combined = pd.concat(dfs, ignore_index=True)
    total_rows = len(combined)
    unique_ids = combined[id_col].nunique()

    # Identify label conflicts
    grouped = combined.groupby(id_col)["label"].unique()
    conflicts = grouped[grouped.apply(len) > 1]
    conflict_count = len(conflicts)

    conflict_examples = []
    for cid in conflicts.index[:10]:
        conflict_examples.append({id_col: cid, "labels": list(conflicts[cid])})

    return {
        "total_rows": total_rows,
        f"unique_{id_col}": int(unique_ids),
        "label_conflicts_count": int(conflict_count),
        "label_conflicts_examples": conflict_examples
    }

def find_unlisted_tabular_files(raw_dir, entries):
    disk_tabular = []
    for sub in ["sms", "url", "ext"]:
        sub_dir = raw_dir / sub
        if not sub_dir.exists():
            continue
        for p in sub_dir.rglob("*"):
            if ".git" in p.parts:
                continue
            if p.is_file() and p.suffix.lower() in TABULAR_EXTS and p.name not in SKIP_NAMES:
                disk_tabular.append(p.relative_to(raw_dir).as_posix())

    exact_paths = {e["path"] for e in entries if not any(c in e["path"] for c in "*?[]") and e.get("format") != "folder_docs"}
    for e in entries:
        if any(c in e["path"] for c in "*?[]") or e.get("format") == "folder_docs":
            continue
        legacy = resolve_legacy_chat_file(raw_dir / e["path"])
        if legacy is not None:
            exact_paths.add(legacy.relative_to(raw_dir).as_posix())
    folder_prefixes = tuple(e["path"] + "/" for e in entries if e.get("format") == "folder_docs")
    glob_patterns = [e["path"] for e in entries if any(c in e["path"] for c in "*?[]")]

    unlisted = []
    for f in disk_tabular:
        if f in exact_paths:
            continue
        if f.startswith(folder_prefixes):
            continue
        if any(fnmatch.fnmatch(f, pat) for pat in glob_patterns):
            continue
        unlisted.append(f)

    return unlisted

def build_corpus(source_map_path="data/source_map.yaml", raw_dir="data/raw", processed_dir="data/processed", only=None, limit=0, sources_filter=""):
    raw_path = Path(raw_dir)
    proc_path = Path(processed_dir)
    source_map_file = Path(source_map_path)

    if not source_map_file.exists():
        raise FileNotFoundError(f"Source map file not found: {source_map_file}")

    with open(source_map_file, "r", encoding="utf-8") as fx:
        entries = yaml.safe_load(fx)
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"source_map.yaml at {source_map_file} must be a non-empty list of entries; got {type(entries).__name__} with {len(entries) if isinstance(entries, list) else 'unknown'} entries")
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"source_map.yaml entry #{idx} must be a mapping; got {type(entry).__name__}")
        for key in ("id", "corpus", "path"):
            if not entry.get(key):
                raise RuntimeError(f"source_map.yaml entry #{idx} missing required field {key!r}: {entry!r}")

    sms_stats = {"sources": {}, "skipped": {}, "totals": {}, "unlisted_files": []}
    url_stats = {"sources": {}, "skipped": {}, "totals": {}, "unlisted_files": [], "probable_inversion_sources": []}

    # Catalogued / documented gaps
    sms_stats["skipped"]["nikhilchauhan02/indian-social-media-fraud-and-scam-detection-d"] = "403 Client Error Forbidden from Kaggle API"
    url_stats["skipped"]["urlhaus_feed"] = "Feed returned 410 Gone"
    url_stats["skipped"]["phreshphish"] = "Not downloaded (732 GB HTML)"
    url_stats["skipped"]["net_datasets"] = "Network and malware sets catalogued only in data/kaggle_sources.csv"

    # Find unlisted tabular files across raw
    unlisted_files = find_unlisted_tabular_files(raw_path, entries)
    sms_stats["unlisted_files"] = [f for f in unlisted_files if f.startswith("sms/")]
    url_stats["unlisted_files"] = [f for f in unlisted_files if f.startswith("url/") or f.startswith("ext/")]

    written_parquets: list[Path] = []
    try:
        for entry in entries:
            eid = entry["id"]
            corpus = entry.get("corpus")

            if sources_filter and sources_filter not in eid and sources_filter not in entry.get("path", ""):
                continue

            if entry.get("skip"):
                reason = entry.get("reason", "Skipped by configuration")
                if corpus == "sms":
                    sms_stats["skipped"][eid] = reason
                elif corpus == "url":
                    url_stats["skipped"][eid] = reason
                else:
                    if "sms" in eid or "sms" in entry.get("path", ""):
                        sms_stats["skipped"][eid] = reason
                    else:
                        url_stats["skipped"][eid] = reason
                continue

            if only and corpus != only:
                continue

            print(f"Processing {corpus.upper()} entry: {eid} ({entry['path']})...")
            st = process_entry(entry, raw_path, proc_path, limit=limit)
            parquet_path = proc_path / corpus / f"{eid}.parquet"
            if parquet_path.exists():
                written_parquets.append(parquet_path)
            if corpus == "sms":
                sms_stats["sources"][eid] = st
            elif corpus == "url":
                url_stats["sources"][eid] = st
                if st.get("probable_inversion"):
                    url_stats["probable_inversion_sources"].append(eid)
                    if not entry.get("allow_inversion"):
                        raise SystemExit(
                            f"F-11: URL corpus build failed — probable label inversion detected for source '{eid}' "
                            f"({entry.get('path', '')}). Known-site homepage labels are not predominantly benign, "
                            f"which indicates a mislabeled source. To allow this source, add allow_inversion: true "
                            f"with a reason to its source_map.yaml entry. Build aborted to prevent training on "
                            f"inverted labels. No stats files were written; removing {len(written_parquets)} parquet(s) written in this run."
                        )
    except SystemExit:
        for p in written_parquets:
            try:
                if p.exists():
                    p.unlink()
            except Exception as cleanup_exc:
                print(f"Warning: could not remove partial parquet {p}: {cleanup_exc}", file=sys.stderr)
        raise

    # Compute cross-source totals and label conflicts
    if not only or only == "sms":
        print("Computing SMS cross-source totals and conflicts...")
        sms_stats["totals"] = compute_corpus_totals(proc_path, "sms")

    if not only or only == "url":
        print("Computing URL cross-source totals and conflicts...")
        url_stats["totals"] = compute_corpus_totals(proc_path, "url")

    # Save stats files
    proc_path.mkdir(parents=True, exist_ok=True)
    # --only rebuilds one corpus: leave the other corpus's stats file untouched
    for name, st in (("sms", sms_stats), ("url", url_stats)):
        if not only or only == name:
            with open(proc_path / f"{name}_stats.json", "w", encoding="utf-8") as f:
                json.dump(st, f, indent=2)

    print("Corpus build completed successfully.")
    return sms_stats, url_stats

def main():
    parser = argparse.ArgumentParser(description="Build unified SMS and URL corpora from source map.")
    parser.add_argument("--only", choices=["sms", "url"], help="Build only sms or url corpus")
    parser.add_argument("--limit", type=int, default=0, help="Row limit per source entry")
    parser.add_argument("--sources", type=str, default="", help="Substring filter for source id/path")
    parser.add_argument("--source-map", type=str, default="data/source_map.yaml", help="Path to source map YAML")
    parser.add_argument("--raw-dir", type=str, default="data/raw", help="Path to raw data directory")
    parser.add_argument("--processed-dir", type=str, default="data/processed", help="Path to processed directory")
    args = parser.parse_args()

    build_corpus(
        source_map_path=args.source_map,
        raw_dir=args.raw_dir,
        processed_dir=args.processed_dir,
        only=args.only,
        limit=args.limit,
        sources_filter=args.sources
    )

if __name__ == "__main__":
    main()
