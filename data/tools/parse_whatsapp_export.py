"""Build the real test set R from the owner's files (output is git-ignored: personal data).

    python data/tools/parse_whatsapp_export.py

Inputs under data/raw_ml/owner/:
  whatsapp_rbi/*.txt  a WhatsApp "Export chat" file. Lines start "dd/mm/yyyy, hh:mm - Sender: text".
  data_txt/Data.txt   advisories pasted one after another; each ends with the RBI sign-off line.
Only messages from the business sender are kept; the owner's own replies, names and system
lines are dropped. Every row is labelled ham: these are official advisories.
"""
import csv
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
from sim_script_gate import dominant_script  # noqa: E402

OWNER_DIR = ROOT / "data" / "raw_ml" / "owner"
OUT = ROOT / "bench" / "heldout_ml" / "real_owner.csv"
KEEP_SENDER = "Reserve Bank of India"
LINE_RE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?:\s?[ap]m)?) - (?:([^:]{1,60}): )?(.*)$", re.I)
SIGN_OFF_RE = re.compile(r"Kehta Hai|कहता है", re.I)
SCRIPT_TO_LANG = {"Tamil": "Tamil", "Devanagari": "Hindi", "Latin": "English"}


def parse_export(path):
    """Yield (date, sender, text) for each message of a WhatsApp export."""
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE_RE.match(line.lstrip("﻿‎"))
        if match:
            if current:
                yield current
            current = [match.group(1), match.group(3), match.group(4)]
        elif current:
            current[2] += "\n" + line
    if current:
        yield current


def parse_pasted(path):
    """Split a pasted file into messages: each ends on the line holding the sign-off."""
    block = []
    for line in path.read_text(encoding="utf-8").splitlines():
        block.append(line)
        if SIGN_OFF_RE.search(line):
            yield "\n".join(block).strip()
            block = []
    tail = "\n".join(block).strip()
    if tail:
        yield tail


def clean(text):
    text = re.sub(r"<Media omitted>|\(file attached\)|<This message was edited>", "", text)
    return "\n".join(part.rstrip() for part in text.strip().splitlines()).strip()


def main():
    rows, seen, dropped = [], set(), {"other_sender": 0, "system": 0, "empty_or_media": 0, "duplicate": 0}
    for path in sorted((OWNER_DIR / "whatsapp_rbi").glob("*.txt")):
        for date, sender, text in parse_export(path):
            if sender is None:
                dropped["system"] += 1
                continue
            if sender.strip() != KEEP_SENDER:
                dropped["other_sender"] += 1
                continue
            rows.append(("whatsapp_export", date, clean(text)))
    pasted = OWNER_DIR / "data_txt" / "Data.txt"
    if pasted.exists():
        rows.extend(("pasted_file", "", clean(text)) for text in parse_pasted(pasted))

    out = []
    for origin, date, text in rows:
        if len(text) < 20:
            dropped["empty_or_media"] += 1
            continue
        key = hashlib.sha1(re.sub(r"\W+", "", text.lower()).encode("utf-8")).hexdigest()
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        script, _share = dominant_script(text)
        out.append({"id": f"r{len(out) + 1:02d}", "language": SCRIPT_TO_LANG.get(script, script), "truth": "ham",
                    "category": "official_advisory", "origin": origin, "date": date, "chars": len(text), "text": text})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    by_lang = {}
    for row in out:
        by_lang[row["language"]] = by_lang.get(row["language"], 0) + 1
    print(f"kept {len(out)} messages {by_lang}; dropped {dropped}; wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
