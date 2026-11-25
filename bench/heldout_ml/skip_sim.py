"""Measure a pre-model skip rule for routine OTP and bank-transaction SMS (counts only).

    python bench/heldout_ml/skip_sim.py

Idea (organiser session 2026-11-12): in real-time mode the app should not analyse or store
one-time passwords and transaction alerts. The rule is text-only here; on the phone it also
requires a registered sender header, which can only lower the scam-skip counts below.
Risk measured: scams that copy the OTP / transaction shape and would be skipped unseen.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench" / "heldout"))

import dump_probs  # noqa: E402
import sim_script_gate as sim  # noqa: E402
from sentinel import pipeline  # noqa: E402

ML = ROOT / "bench" / "heldout_ml"
MAX_CHARS = 320
_MOBILE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_OTP = re.compile(r"\b(?:otp|one[\s-]?time\s+pass(?:word|code)|verification\s+code|login\s+code)\b|ओटीपी|ஓடிபி", re.I)
_CODE = re.compile(r"(?<![\d,.])\d{4,8}(?![\d,.])")
_MONEY = re.compile(r"(?:\brs\.?|\binr|₹)\s*[\d,]+(?:\.\d+)?", re.I)
_MOVED = re.compile(r"\b(?:debited|credited|withdrawn|spent|deposited|transferred|received|paid)\b", re.I)
_ACCOUNT = re.compile(r"\b(?:a/c|acct?|account|card|upi|wallet)\b|\b[xX*]{2,}\d{2,}", re.I)
# Words that turn a routine alert into a request: any of these keeps the message in analysis.
_ASK = re.compile(r"\b(?:share|send|forward|tell|give|click|update|verify|kyc|blocked|suspend\w*|expire\w*|refund|"
                  r"reward|won|prize|lottery|install|download|whatsapp)\b|बताएं|शेयर|பகிர", re.I)


def skip_kind(text: str) -> str | None:
    """Return 'otp' or 'transaction' when the message is routine and may be skipped, else None."""
    text = re.sub(r"\s*@[\w.-]+\s+#\w+\s*$", "", text)  # standard OTP auto-fill ending, not a link
    if len(text) > MAX_CHARS or pipeline._extract_urls_safe(text) or _MOBILE.search(text):
        return None
    # ponytail: 'do not share' in genuine OTP texts hits _ASK and keeps them in analysis;
    # the alert policy handles those. Loosen only with a measured recall check.
    if _ASK.search(text):
        return None
    if _OTP.search(text) and _CODE.search(text):
        return "otp"
    if _MONEY.search(text) and _MOVED.search(text) and _ACCOUNT.search(text):
        return "transaction"
    return None


def main() -> int:
    out: dict = {"real": {}, "heldout": {}}
    real = Counter()
    for row in csv.DictReader(open(ML / "real_sms_levels.csv", encoding="utf-8", newline="")):
        kind = skip_kind(row["text"])
        for key in ("all", row["sender_class"]):
            real[(key, "n")] += 1
            real[(key, "flagged")] += row["shipped"] != "low"
            if kind:
                real[(key, "skipped")] += 1
                real[(key, "skipped_" + kind)] += 1
                real[(key, "skipped_was_flagged")] += row["shipped"] != "low"
                real[(key, "skipped_was_high")] += row["shipped"] == "high"
    for (key, name), value in sorted(real.items()):
        out["real"].setdefault(key, {})[name] = value

    rows, _missing = sim._load_rows()
    text_by_hash = {dump_probs.compute_text_hash(r["text"]): r["text"]
                    for r in csv.DictReader(open(sim.HELDOUT_CSV, encoding="utf-8", newline=""))}
    held = Counter()
    for row in rows:
        kind = skip_kind(text_by_hash[row["text_hash"]])
        for key in ("Overall", row["language"]):
            held[(key, row["truth"] + "_n")] += 1
            if kind:
                held[(key, row["truth"] + "_skipped")] += 1
    for (key, name), value in sorted(held.items()):
        out["heldout"].setdefault(key, {})[name] = value

    golden = list(csv.DictReader(open(ML / "golden_ta_hi.csv", encoding="utf-8", newline="")))
    out["golden"] = dict(Counter(f"{r['truth']}_{'skipped' if skip_kind(r['text']) else 'kept'}" for r in golden))
    (ROOT / "docs" / "multilang" / "skip_sim.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    # Self-check: shapes that must and must not be skipped.
    assert skip_kind("123456 is your OTP for login. Valid for 10 minutes.") == "otp"
    assert skip_kind("Rs.500.00 debited from A/c XX1234 on 12-11-26. Avl bal Rs 2,000.") == "transaction"
    assert skip_kind("Your A/c is debited Rs 5000. Not you? Call 9876543210") is None
    assert skip_kind("Share OTP 123456 with our agent to get refund") is None
    assert skip_kind("Your OTP is 4455. Verify at http://bit.ly/x") is None
    raise SystemExit(main())
