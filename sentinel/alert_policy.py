"""Alert policy: notify only when a verdict carries real threat evidence.

Why: on a real inbox half of all business SMS reached level medium only because the SMS model
called them `unwanted`, and every medium posted a notification. A promotion is not a threat.
`should_alert` keeps the notification for high risk and for medium risk with threat evidence.

Version 1 of this policy ignored the SMS model label and lost 7 to 25 points of scam recall on
held-out Hinglish and Hindi: many scams reach only medium risk after calibration and carry no
keyword cue. A medium verdict whose model class is `scam` is a threat; only `unwanted` or `ham`
at medium without other evidence is quiet.

The warning-clause cue filter from the same experiment was measured and rejected, so it is not
ported here.

Registered senders (2026-11-15): a medium verdict from a DLT header sender alerts only when the
SMS model itself says scam. Cue words such as "pay", "share" and "OTP" are normal in genuine
business SMS; with them counting, 12 to 26 percent of three real inboxes still alerted, without
them about 3 percent. High verdicts (model, cue combinations, bank alert asking for a secret)
alert for every sender.
"""
from __future__ import annotations

from typing import Any

THREAT_CUE_TYPES = frozenset({"credential_request", "payment_request", "threat", "app_install", "sender_mismatch"})
UNTRUSTED_URL_MIN_PROB = 0.5


def should_alert(
    level: str,
    cue_types: set[str],
    has_url: bool,
    max_untrusted_url_prob: float,
    sms_label: str | None = None,
    registered_sender: bool = False,
) -> bool:
    """Decide whether a verdict posts a notification."""
    if level == "high":
        return True
    if level != "medium":
        return False
    if sms_label == "scam":
        return True
    if registered_sender:
        return False
    if cue_types & THREAT_CUE_TYPES:
        return True
    if "impersonation" in cue_types and has_url:
        return True
    return max_untrusted_url_prob >= UNTRUSTED_URL_MIN_PROB


def evidence_should_alert(evidence: Any) -> bool:
    """Apply the alert policy to the cues, URLs and SMS label of an Evidence object."""
    cues = getattr(evidence, "cue_spans", None) or []
    cue_types = {cue["type"] for cue in cues if isinstance(cue, dict) and "type" in cue}

    urls = getattr(evidence, "urls", None) or []
    untrusted_probs = [
        float(url.get("prob", 0.0))
        for url in urls
        if isinstance(url, dict) and not url.get("trusted", False)
    ]

    return should_alert(
        evidence.level,
        cue_types,
        bool(urls),
        max(untrusted_probs, default=0.0),
        getattr(evidence, "sms_label", None),
        bool(getattr(evidence, "registered_sender", False)),
    )
