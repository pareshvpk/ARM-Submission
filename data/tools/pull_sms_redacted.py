"""Read the SMS inbox of the connected phone over adb and write a redacted local test file.

    python data/tools/pull_sms_redacted.py [--include-personal] [--serial SERIAL]

Read-only on the phone: three `content query` calls, nothing installed or written there.
Raw message text is never written to disk; redaction happens in memory and only the
redacted rows are saved, to a git-ignored file. Automatic redaction is not perfect
(names inside sentences can survive), so the output stays local and is a test set only.
"""
import argparse
import csv
import hashlib
import os
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "heldout"))
from sim_script_gate import dominant_script  # noqa: E402

ADB = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
OUT = ROOT / "bench" / "heldout_ml" / "real_sms.csv"
ROW_RE = re.compile(r"^Row: \d+ _id=(\d+), (\w+)=(.*)$")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|net|org|co|io|me|ly|gl|app|xyz|top|info|biz|gov)(?:/[^\s<>\"']*)?", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
HANDLE_RE = re.compile(r"\b[\w.-]{2,}@(?:ok\w+|ybl|upi|paytm|axl|ibl|sbi|icici|hdfcbank|apl|jio|\w{2,10})\b")
GREETING_RE = re.compile(r"\b(?:Dear|Hi|Hello|Hey|Mr\.?|Mrs\.?|Ms\.?|Shri|Smt\.?)\s+([A-Z][a-zA-Z]{2,})(?:\s+([A-Z][a-zA-Z]{1,}))?")
NOT_NAMES = {"customer", "user", "sir", "madam", "member", "valued", "subscriber", "client", "student", "parent",
             "applicant", "cardholder", "card", "investor", "candidate", "team", "all", "friend", "guest", "consumer",
             "employee", "account", "sbi", "hdfc", "icici", "axis", "jio", "airtel", "vi", "bsnl", "upi", "there"}
SCRIPT_TO_LANG = {"Tamil": "Tamil", "Devanagari": "Hindi", "Latin": "Latin"}


def query(column, serial):
    cmd = [ADB] + (["-s", serial] if serial else []) + ["exec-out", "content", "query", "--uri", "content://sms/inbox",
                                                         "--projection", f"_id:{column}"]
    text = subprocess.run(cmd, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    values, current = {}, None
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if match and match.group(2) == column:
            current = match.group(1)
            values[current] = match.group(3)
        elif current is not None:
            values[current] += "\n" + line
    return values


def sender_type(address):
    digits = re.sub(r"\D", "", address)
    if re.search(r"[A-Za-z]", address):
        return "header"
    return "mobile" if len(digits) >= 10 else "shortcode"


def stable_digits(match):
    run = match.group(0)
    rng = random.Random(hashlib.sha1(run.encode()).hexdigest())
    return "".join(str(rng.randint(0, 9)) for _ in run)


def redact_url(match):
    url = match.group(0)
    head, sep, path = url.partition("/") if "://" not in url else (url.split("/", 3)[0] + "//" + url.split("/", 3)[2], "/", "/".join(url.split("/", 3)[3:]))
    path = re.sub(r"[A-Za-z0-9_-]{8,}", lambda m: "x" * len(m.group(0)), path)
    return head + (sep + path if path else "")


def keep_or_randomise(match):
    run = match.group(0)
    # Calendar years stay readable; every other long digit run is replaced.
    if len(run) == 4 and run[:2] in ("19", "20"):
        return run
    return stable_digits(match)


def redact(text, names, name_fragments):
    text = EMAIL_RE.sub("user@example.com", text)
    text = HANDLE_RE.sub(lambda m: "user@" + m.group(0).split("@")[1], text)
    text = URL_RE.sub(redact_url, text)
    text = re.sub(r"\d{4,}", keep_or_randomise, text)
    for name in names:
        text = re.sub(rf"\b{re.escape(name)}\b", "NAME", text, flags=re.I)
    for fragment in name_fragments:
        text = re.sub(rf"\b\w*{re.escape(fragment)}\w*\b", "NAME", text, flags=re.I)
    return text.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-personal", action="store_true", help="keep messages from plain mobile numbers too")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--name-fragments", default="", help="comma list; any word containing one is replaced (owner names)")
    parser.add_argument("--out", default=None, help="output CSV name inside bench/heldout_ml (must start with real_, git-ignored)")
    args = parser.parse_args()
    global OUT
    if args.out:
        if not args.out.startswith("real_") or "/" in args.out or "\\" in args.out:
            raise SystemExit("--out must be a bare file name starting with real_")
        OUT = OUT.parent / args.out

    address, date, body = (query(col, args.serial) for col in ("address", "date", "body"))
    ids = [i for i in body if i in address]
    print(f"inbox messages read: {len(ids)}")

    names = Counter()
    for i in ids:
        for match in GREETING_RE.finditer(body[i]):
            for part in match.groups():
                if part and part.lower() not in NOT_NAMES:
                    names[part] += 1
    # A first version replaced every word that ever followed "Dear/Hi", which turned "Your", "For"
    # and "At" into NAME across the whole file. A candidate is now a name only if it never occurs
    # in lower case anywhere in the inbox (real names are capitalised; ordinary words are not).
    lower_words = set()
    for i in ids:
        lower_words.update(re.findall(r"\b[a-z]{3,}\b", body[i]))
    name_list = sorted((n for n in names if n.lower() not in lower_words and len(n) >= 4), key=len, reverse=True)
    fragments = [f.strip().lower() for f in args.name_fragments.split(",") if f.strip()]

    rows, seen, skipped = [], set(), Counter()
    for i in ids:
        kind = sender_type(address[i])
        if kind == "mobile" and not args.include_personal:
            skipped["personal_number"] += 1
            continue
        text = redact(body[i], name_list, fragments)
        if len(text) < 15:
            skipped["too_short"] += 1
            continue
        template = re.sub(r"\d+", "0", re.sub(r"\s+", " ", text.lower()))
        if template in seen:
            skipped["duplicate_template"] += 1
            continue
        seen.add(template)
        script, _ = dominant_script(text)
        header = re.sub(r"^[A-Z]{2}-", "", address[i].upper()) if kind == "header" else kind
        year_month = ""
        if date.get(i, "").isdigit():
            import datetime
            year_month = datetime.datetime.fromtimestamp(int(date[i]) / 1000).strftime("%Y-%m")
        rows.append({"id": f"s{len(rows) + 1:04d}", "sender_type": kind, "header": header, "month": year_month,
                     "language": SCRIPT_TO_LANG.get(script, script), "truth": "", "chars": len(text), "text": text})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"kept {len(rows)}; skipped {dict(skipped)}; names replaced: {len(name_list)} distinct")
    print("by language:", dict(Counter(r["language"] for r in rows)))
    print("by sender type:", dict(Counter(r["sender_type"] for r in rows)))
    print("by year:", dict(sorted(Counter(r["month"][:4] for r in rows).items())))
    print("top headers:", Counter(r["header"] for r in rows).most_common(25))
    print(f"wrote {OUT.relative_to(ROOT)} (git-ignored)")


if __name__ == "__main__":
    main()
