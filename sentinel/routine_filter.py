"""Pre-model skip rule for routine OTP and bank-transaction SMS.

Text-only classification plus a registered-sender check. A message is skipped
only when both agree, so scams from unknown or numeric senders still reach the
detector.
"""
from __future__ import annotations

import re
from typing import Any

from sentinel import pipeline
from sentinel.fusion import SECRET, is_bank_alert, sender_header

MAX_CHARS = 320
# Every pattern is ASCII, matching java.util.regex (Kotlin) defaults. Devanagari
# script words still match because they are literal characters.
_PHONE_GAP = re.compile(r"(?<=\d)[ -](?=\d)", re.ASCII)
# A mobile or toll-free number, matched only after the gap removal. A plain 10+ digit
# run would also swallow 12-digit UPI references in genuine credit alerts.
_MOBILE = re.compile(r"(?<!\d)(?:\+?91|0)?[6-9]\d{9}(?!\d)", re.ASCII)
_TOLL_FREE = re.compile(r"(?<!\d)18[06]0\d{7}(?!\d)", re.ASCII)
# A personal number as the sender: digits, spaces and hyphens, with an optional
# leading plus. A DLT header or a short code never matches.
_SENDER_PHONE = re.compile(r"^\+?[\d -]+$", re.ASCII)
# The same mobile and toll-free numbers as _MOBILE/_TOLL_FREE, but matched on the
# original text with single gaps allowed so the cue can carry real offsets.
_PHONE_SPAN = re.compile(
    r"(?<!\d)(?:\+?91[ -]?|0)?[6-9](?:[ -]?\d){9}(?!\d)"
    r"|(?<!\d)18[06]0(?:[ -]?\d){7}(?!\d)",
    re.ASCII,
)
_OTP = re.compile(r"\b(?:otp|one[\s-]?time\s+pass(?:word|code)|verification\s+code|login\s+code)\b|ओटीपी|ஓடிபி", re.I | re.ASCII)
_CODE = re.compile(r"(?<![\d,.])\d{4,8}(?![\d,.])", re.ASCII)
_MONEY = re.compile(r"(?:\brs\.?|\binr|₹)\s*[\d,]+(?:\.\d+)?", re.I | re.ASCII)
_MOVED = re.compile(r"\b(?:debited|credited|withdrawn|spent|deposited|transferred|received|paid)\b", re.I | re.ASCII)
_ACCOUNT = re.compile(r"\b(?:a/c|acct?|account|card|upi|wallet)\b|\b[xX*]{2,}\d{2,}", re.I | re.ASCII)
# First-person wording marks a person-to-person message, never a bank alert.
_FIRST_PERSON = re.compile(r"\b(?:i|my|me)\b", re.I | re.ASCII)
# Words that turn a routine alert into a request: any of these keeps the message in analysis.
_ASK = re.compile(r"\b(?:share|send|forward|tell|give|click|update|verify|kyc|blocked|suspend\w*|expire\w*|refund|"
                  r"reward|won|prize|lottery|install|download|whatsapp|call|dial|contact|ring|missed\s+call|"
                  r"reply|enter|type|provide|confirm|submit|reverse|cancel|pin|mpin|cvv|passcode|"
                  r"message|msg|sms|text|quote|validate|revert|reversal|pay|transfer|reach|phone|ping|callback|"
                  r"helpline|batao|bhejo|bhej|daalo|dedo)\b|"
                  r"बताएं|शेयर|பகிர", re.I | re.ASCII)
_WEBOTP_TAIL = re.compile(r"\s*@[\w.-]+\s+#\w+\s*$", re.ASCII)


def _has_phone_number(text: str) -> bool:
    """True when a mobile or 1800/1860 toll-free number appears after ignoring single gaps between digits."""
    flat = _PHONE_GAP.sub("", text)
    return _MOBILE.search(flat) is not None or _TOLL_FREE.search(flat) is not None


def skip_kind(text: str) -> str | None:
    """Return 'otp' or 'transaction' when the message is routine and may be skipped, else None.

    Args:
        text: SMS message body text.

    Returns:
        'otp' for standard login codes, 'transaction' for debit/credit alerts,
        or None if the message contains URLs, phone numbers, or request phrasing.
    """
    # The standard auto-fill ending of a real OTP ("@example.com #123456") is not a link to follow.
    text = _WEBOTP_TAIL.sub("", text)
    if len(text) > MAX_CHARS or pipeline._extract_urls_safe(text) or _has_phone_number(text):
        return None
    # ponytail: 'do not share' in genuine OTP texts hits _ASK and keeps them in analysis;
    # the alert policy handles those. Loosen only with a measured recall check.
    if _ASK.search(text):
        return None
    kind = None
    if _OTP.search(text) and _CODE.search(text):
        kind = "otp"
    if kind is None and _MONEY.search(text) and _MOVED.search(text) and _ACCOUNT.search(text):
        kind = "transaction"
    if kind is None:
        return None
    # A transaction that names a secret code is never routine.
    if kind == "transaction" and SECRET.search(text) is not None:
        return None
    # An OTP that also reports money movement is a scam shape, not a routine OTP.
    if kind == "otp" and _MONEY.search(text) is not None and _MOVED.search(text) is not None:
        return None
    return kind


def _is_phone_sender(sender: str) -> bool:
    """True when the sender is a personal phone number with at least 10 digits."""
    if not isinstance(sender, str):
        return False
    trimmed = sender.strip()
    if not trimmed or _SENDER_PHONE.fullmatch(trimmed) is None:
        return False
    return sum(char.isdigit() for char in trimmed) >= 10


def _last_ten_digits(value: str) -> str:
    """Return the last ten digit characters of a string."""
    return "".join(char for char in value if char.isdigit())[-10:]


def sender_cue(sender: str, text: str) -> dict[str, Any] | None:
    """Return a sender_mismatch cue for a bank-style alert sent from a personal number.

    The cue fires only when the sender is a personal phone number, the text is a
    bank-alert shape, the text reads like a bank alert rather than a person, and
    the callback number differs from the sender. Genuine bank alerts arrive from a
    DLT header, so the same wording never fires there.

    Args:
        sender: Sender identifier string (phone number or DLT header).
        text: Message body text.

    Returns:
        Cue span dictionary with type, start, end, and matched text, or None.
    """
    if not isinstance(text, str) or not _is_phone_sender(sender):
        return None
    if not is_bank_alert(text):
        return None
    if _FIRST_PERSON.search(text):
        return None
    if not _has_phone_number(text):
        return None
    match = _PHONE_SPAN.search(text)
    if match is None:
        return None
    if _last_ten_digits(match.group(0)) == _last_ten_digits(sender):
        return None
    return {"type": "sender_mismatch", "start": match.start(), "end": match.end(), "text": match.group(0)}


def is_registered_sender(sender: str) -> bool:
    """True only for the Indian DLT header shape XX-XXXXXX or XX-XXXXXX-S.

    Args:
        sender: Sender identifier string.

    Returns:
        True if sender matches the Telecom Regulatory Authority DLT registration pattern.
    """
    if not sender:
        return False
    return sender_header(sender) is not None


def should_skip(sender: str, text: str) -> bool:
    """True only when a registered sender sent a routine OTP or transaction alert.

    Args:
        sender: Sender identifier string.
        text: Message body text.

    Returns:
        True if both sender is registered and message body qualifies as routine.
    """
    return is_registered_sender(sender) and skip_kind(text) is not None
