"""Alert policy and warning-clause cue filter (round 3 experiment, not wired into the pipeline yet).

Why: on a real inbox half of all business SMS reached level medium only because the SMS model
called them `unwanted`, and every medium posted a notification. A promotion is not a threat.
`should_alert` keeps the notification for high risk and for medium risk with threat evidence.

`filter_warning_cues` drops a credential or payment cue that sits in a clause which warns
against the act ("never share your OTP", "beware of fake KYC messages"): official advisories
quote scam wording and were being scored by the urgency-plus-credential rule.

shortcut: constants live here while the experiment is measured; they move into
sentinel/data/rules.json (shared with Kotlin) when the change is wired in.
"""
from __future__ import annotations

import re
from typing import Any

THREAT_CUE_TYPES = frozenset({"credential_request", "payment_request", "threat", "app_install"})
FILTERED_CUE_TYPES = frozenset({"credential_request", "payment_request"})
UNTRUSTED_URL_MIN_PROB = 0.5

_CLAUSE_BREAK = re.compile(r"[.!?;\n।]|(?<=\s)[-–—•·](?=\s)|[✅❌\U0001F449➡\U0001F4CC⚠]")
_WARNING = re.compile(
    r"\b(?:never|do\s+not|don'?t|do\s+n't|dont|will\s+not\s+ask|won'?t\s+ask|does\s+not\s+ask|beware|avoid|"
    r"be\s+careful|not\s+to\s+share|should\s+not|must\s+not)\b"
    r"|வேண்டாம்|பகிராதீர்|ஒருபோதும்|கவனமாக\s+இருங்கள்|எச்சரிக்கையாக"
    r"|न\s+करें|न\s+बताएँ|न\s+बताएं|न\s+दें|कभी\s+न|मत\s|सावधान"
    r"|\bmat\s+(?:karo|karein|kare|batao|dena|do)\b|\bna\s+(?:karein|kare|batayein|dein)\b|\bkabhi\s+na",
    re.IGNORECASE,
)


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for match in _CLAUSE_BREAK.finditer(text, 0, start):
        left = match.end()
    right_match = _CLAUSE_BREAK.search(text, end)
    return left, right_match.start() if right_match else len(text)


def in_warning_clause(text: str, start: int, end: int) -> bool:
    """True when the clause around text[start:end] warns against the act it names."""
    left, right = _clause_bounds(text, start, end)
    return bool(_WARNING.search(text[left:right]))


def filter_warning_cues(text: str, cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cues without credential or payment cues that sit in a warning clause."""
    if not isinstance(text, str):
        return list(cues)
    kept = []
    for cue in cues:
        if cue.get("type") in FILTERED_CUE_TYPES and "start" in cue and "end" in cue:
            if in_warning_clause(text, int(cue["start"]), int(cue["end"])):
                continue
        kept.append(cue)
    return kept


def should_alert(level: str, cue_types: set[str], has_url: bool, max_untrusted_url_prob: float,
                 sms_label: str | None = None) -> bool:
    """Decide whether a verdict posts a notification.

    sms_label is the SMS model's own top class. Version 1 of this policy ignored it and lost 7 to
    25 points of scam recall on held-out Hinglish and Hindi: many scams reach only medium risk after
    calibration and carry no keyword cue. A medium verdict whose model class is `scam` is a threat;
    only `unwanted` or `ham` at medium without other evidence is quiet.
    """
    if level == "high":
        return True
    if level != "medium":
        return False
    if sms_label == "scam":
        return True
    if cue_types & THREAT_CUE_TYPES:
        return True
    if "impersonation" in cue_types and has_url:
        return True
    return max_untrusted_url_prob >= UNTRUSTED_URL_MIN_PROB
