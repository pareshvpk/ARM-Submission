"""Multi-signal evidence fusion engine for PS3 Sentinel.

Combines SMS classifier probabilities, URL detector scores, regex cue matches,
and registered sender identity into a unified risk score and verdict.
Mirrored on Android by org.ps3.sentinel.core.Fusion and verified by parity tests.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sentinel.detector_api import clamp_risk
from sentinel.detectors import get_registered_domain
from sentinel.rules import DETECTOR_VERSIONS, FUSION_RULES, SCAM_SCRIPT_RULES
from sentinel.url_features import normalise_url

# Load trusted domains
TRUSTED_DOMAINS_FILE = Path(__file__).parent / "data" / "trusted_domains.txt"

TRUSTED_DOMAINS: set[str] = set()
if TRUSTED_DOMAINS_FILE.is_file():
    with open(TRUSTED_DOMAINS_FILE, "r", encoding="utf-8") as trusted_file:
        for line in trusted_file:
            line = line.strip().lower()
            if line and not line.startswith("#"):
                TRUSTED_DOMAINS.add(line)

# Hosting platforms are never trusted because phishing is frequently hosted there
UNTRUSTED_HOSTING_PLATFORMS: set[str] = {
    "sites.google.com",
    "docs.google.com",
    "drive.google.com",
    "forms.gle",
    "firebaseapp.com",
    "web.app",
    "blogspot.com",
    "github.io",
    "sharepoint.com",
    "ipfs",
}

# Readable evidence wording for cue types that are not named by their rule key.
SENDER_MISMATCH_INDICATOR = "bank-style alert sent from a personal mobile number"
BANK_ALERT_CREDENTIAL_INDICATOR = "bank alert asking for a secret code"

# The shared bank-alert shape: an amount, a debit/credit verb and a bank account marker.
_MONEY = re.compile(r"(?:\brs\.?|\binr|₹)\s*[\d,]+(?:\.\d+)?", re.I | re.ASCII)
_MOVED = re.compile(
    r"\b(?:debited|debit|credited|withdrawn|spent|transferred|received|deposited|paid)\b",
    re.I | re.ASCII,
)
_ACCOUNT = re.compile(
    r"\b(?:a/c|acct)\b|[xX*]{2,}\d{2,}|\byour\s+(?:a/c|acct|account|card)\b",
    re.I | re.ASCII,
)


def is_bank_alert(text: str) -> bool:
    """True when the text reads like a real bank debit/credit alert.

    Args:
        text: Message text to inspect.

    Returns:
        True if text contains money amount, debit/credit verb, and account reference.
    """
    if not isinstance(text, str):
        return False
    return (
        _MONEY.search(text) is not None
        and _MOVED.search(text) is not None
        and _ACCOUNT.search(text) is not None
    )


# Clause-level secret request: a secret word plus an ask to transmit it, in the same clause.
SECRET = re.compile(r"\b(?:otp|pin|mpin|cvv|passcode|password|code)\b", re.I | re.ASCII)
NEG = re.compile(
    r"\b(?:never|not|don'?t|nobody|nothing|no\s+one|no-one|none|neither|nor|mat|kabhi|nahi|nahin|na)\b",
    re.I | re.ASCII,
)
EN_SEND = re.compile(
    r"\b(?:reply|send|share|provide|give|tell|quote|forward|read|spell|repeat|dictate|reveal|disclose|inform|mention|show)\b",
    re.I | re.ASCII,
)
HI_SEND = re.compile(
    r"\b(?:batao|bata|bataye|bataiye|bhejo|bhej|bhejiye|daalo|daal|dedo|de)\b",
    re.I | re.ASCII,
)
CHANNEL_SEND = re.compile(
    r"\b(?:message|msg|sms|text|whatsapp)\s+(?:(?:your|the|us|me|that|this)\s+)?(?:otp|pin|mpin|cvv|passcode|password|(?:\d[\s-]?digit\s+)?code)\b",
    re.I | re.ASCII,
)
DEMAND = re.compile(
    r"\b(?:enter|type|validate|confirm|submit|use|needed|required|mandatory)\b",
    re.I | re.ASCII,
)
PURPOSE = re.compile(
    r"\b(?:reverse|revert|reversal|cancel|stop|block|unblock|hold|prevent|"
    r"reactivate|activate|refund|avoid)\b",
    re.I | re.ASCII,
)
STRONG_SECRET = re.compile(
    r"\b(?:otp|pin|mpin|cvv|passcode|password)\b|"
    r"\b(?:verification|security|secret|otp|digit|one[\s-]?time|login)\s+code\b",
    re.I | re.ASCII,
)
CODE_WORD = re.compile(r"\bcode\b", re.I | re.ASCII)
REASSURE = re.compile(
    r"\b(?:don'?t|do\s+not|not\s+to)\s+(?:worry|panic)\b|"
    r"\bno\s+need\s+to\b|"
    r"\bif\s+not\s+(?:you|done\s+by\s+you|by\s+you|authori[sz]ed|initiated(?:\s+by\s+you)?)\b|"
    r"\bif\s+(?:you\s+)?(?:did\s+not|didn'?t|have\s+not|haven'?t)\s+(?:authori[sz]e\w*|initiate\w*|do\s+this|make\s+this)\b|"
    r"\b(?:fikr|chinta|tension)\s+(?:mat|na)\s+(?:karo|karein|kijiye|lo)\b|"
    r"\bghabra\w*\s+mat\b|"
    r"\bif\s+(?:you\s+)?(?:have\s+|had\s+)?(?:not|n'?t)\s+(?:done|made|authori[sz]ed|initiated|requested|recogni[sz]ed?)\b|"
    r"\bif\s+(?:this|it|that)\s+(?:is|was)\s+not\s+(?:you|done\s+by\s+you|by\s+you)\b|"
    r"\bif\s+not\s+recogni[sz]ed\b|"
    r"\b(?:don'?t|do\s+not)\s+delay\b|"
    r"\bna\b(?=\W*$)",
    re.I | re.ASCII,
)
_CLAUSE_SPLIT = re.compile(r"[.!?;\n]+")


def _has_secret(tokens: list[str], c: str) -> bool:
    if not tokens:
        return False
    span = " ".join(tokens)
    return STRONG_SECRET.search(span) is not None or (
        CODE_WORD.search(span) is not None and PURPOSE.search(c) is not None
    )


def secret_request(text: str) -> bool:
    """True when one clause asks the reader to transmit a secret code.

    Args:
        text: Message text to inspect.

    Returns:
        True if an imperative clause requests transmitting an OTP, PIN, or password.
    """
    if not isinstance(text, str):
        return False
    for clause in _CLAUSE_SPLIT.split(text):
        c = REASSURE.sub(" ", clause)
        if not (
            STRONG_SECRET.search(c) is not None
            or (CODE_WORD.search(c) is not None and PURPOSE.search(c) is not None)
        ):
            continue
        if NEG.search(c) is not None:
            continue
        if CHANNEL_SEND.search(c) is not None:
            return True
        for m in EN_SEND.finditer(c):
            after_tokens = c[m.end():].split()[:6]
            if _has_secret(after_tokens, c):
                return True
        for m in HI_SEND.finditer(c):
            before_tokens = c[:m.start()].split()[-6:]
            if _has_secret(before_tokens, c):
                return True
        if DEMAND.search(c) is not None and PURPOSE.search(c) is not None:
            return True
    return False


# Known scam scripts from rules.json: (indicator, patterns that must all match, patterns that must not).
_SCAM_SCRIPTS = [
    (
        script["indicator"],
        [re.compile(pattern, re.IGNORECASE) for pattern in script["all"]],
        [re.compile(pattern, re.IGNORECASE) for pattern in script["none"]],
    )
    for script in SCAM_SCRIPT_RULES
]


def scam_script(text: str) -> str | None:
    """Return the indicator of the first known scam script the text follows, or None.

    Why: the SMS model calls some fixed scam scripts normal or promotional (digital arrest,
    "pay Rs 1 to get your refund", guaranteed daily profit groups). Measured 2026-11-15: no hit
    on 4,785 real inbox messages or 1,705 held-out and code-mixed genuine messages.
    """
    if not isinstance(text, str):
        return None
    for indicator, required, forbidden in _SCAM_SCRIPTS:
        if all(p.search(text) for p in required) and not any(p.search(text) for p in forbidden):
            return indicator
    return None


def is_untrusted_hosting(host: str) -> bool:
    """Check if host belongs to an untrusted hosting/content platform.

    Args:
        host: Hostname string.

    Returns:
        True if host matches free hosting or cloud storage services commonly abused for phishing.
    """
    host = host.lower().strip(".")
    for platform in UNTRUSTED_HOSTING_PLATFORMS:
        if platform == "ipfs":
            if host == "ipfs" or "ipfs" in host.split("."):
                return True
        else:
            if host == platform or host.endswith("." + platform):
                return True
    return False


def is_trusted(host: str) -> bool:
    """Check if host is an official trusted domain or gov suffix.

    Args:
        host: Hostname string.

    Returns:
        True if domain is government (.gov.in), official banking (.bank.in), or in trusted_domains.txt.
    """
    if not host or not isinstance(host, str):
        return False

    host = host.lower().strip(".")
    if ":" in host:
        host = host.split(":")[0]

    # Hosting platforms are never trusted
    if is_untrusted_hosting(host):
        return False

    # Official government domains
    if host.endswith(".gov.in") or host.endswith(".nic.in") or host == "gov.in" or host == "nic.in":
        return True

    # ".bank.in" is the RBI-mandated zone that only licensed Indian banks can register in.
    if host.endswith(".bank.in"):
        return True

    reg_dom = get_registered_domain(host)
    if host in TRUSTED_DOMAINS or reg_dom in TRUSTED_DOMAINS:
        return True

    return False


# Indian DLT sender header: XX-XXXXXX with an optional one-letter suffix (-S, -P, -T, -G).
DLT_HEADER = re.compile(r"^[A-Za-z]{2}-([A-Za-z0-9]{3,8})(?:-[A-Za-z])?$", re.ASCII)
# URL indicators that keep a link risky whoever sent it.
HARD_URL_INDICATORS = frozenset({"risky_tld", "ip_host", "unparseable_url"})


def sender_header(sender: Any) -> str | None:
    """Return the upper-case entity code of a DLT header sender, or None for any other sender.

    Args:
        sender: Sender identifier string.

    Returns:
        Upper-case entity header code if DLT format matches, otherwise None.
    """
    if not isinstance(sender, str):
        return None
    match = DLT_HEADER.fullmatch(sender.strip())
    return match.group(1).upper() if match else None


def _discount_registered_sender_urls(processed_urls: list[dict[str, Any]]) -> None:
    """Cap link risk for a registered (DLT header) sender whose message the SMS model does not call a scam.

    Why: the URL model scores brand short links (bank, shop and telecom link shorteners) as
    phishing. On three real inboxes 27 to 53 percent of genuine business SMS alerted, most of
    them with the link as the only strong evidence. A link with a risky TLD, a bare IP host or
    an unparseable form is never capped. Unknown and phone-number senders are untouched.
    """
    cap = FUSION_RULES["trusted_prob_cap"]
    threshold = FUSION_RULES["url_phishing_label_threshold"]
    for url in processed_urls:
        if url["trusted"] or HARD_URL_INDICATORS & set(url["indicators"]):
            continue
        url["prob"] = min(url["prob"], cap)
        url["label"] = "phishing" if url["prob"] >= threshold else "benign"


def _host_from_url(raw_url: str) -> str:
    """Return the lower-case host of a URL, raising ValueError when it cannot be parsed."""
    parsed = urlparse(raw_url if "://" in raw_url else "http://" + raw_url)
    return (parsed.hostname or "").lower()


@dataclass
class Evidence:
    """Structured evidence model output by the fusion engine.

    Holds the computed risk score, categorical level (low, medium, high),
    classification label (ham, unwanted, scam), extracted cue spans,
    analyzed URLs, and active security indicators.
    """
    label: str
    risk: float
    level: str
    threshold: float
    indicators: list[str] = field(default_factory=list)
    cue_spans: list[dict[str, Any]] = field(default_factory=list)
    urls: list[dict[str, Any]] = field(default_factory=list)
    detector_versions: dict[str, str] = field(default_factory=dict)
    extra_detectors: list[dict[str, Any]] = field(default_factory=list)
    # SMS model top class, kept out of to_dict so the JSON output is unchanged.
    sms_label: str | None = None
    # True when the sender is a DLT header and the SMS model gave an answer; used only by the
    # alert policy, never serialised.
    registered_sender: bool = False

    @property
    def cues(self) -> list[dict[str, Any]]:
        """Alias for cue_spans, used by Kotlin twin and callers."""
        return self.cue_spans

    def __getitem__(self, key: str) -> Any:
        """Look up an evidence field by name, raising KeyError when absent."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Look up an evidence field by name, returning default when absent."""
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the evidence to a plain dict for JSON output."""
        serialised = {
            "label": self.label,
            "risk": self.risk,
            "level": self.level,
            "threshold": self.threshold,
            "indicators": self.indicators,
            "cue_spans": self.cue_spans,
            "cues": self.cue_spans,
            "urls": self.urls,
            "detector_versions": self.detector_versions,
        }
        if self.extra_detectors:
            serialised["extra_detectors"] = self.extra_detectors
        return serialised


def _process_urls(url_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise each URL result: parse host, cap trusted probability, label it."""
    processed_urls: list[dict[str, Any]] = []
    url_phishing_threshold = FUSION_RULES["url_phishing_label_threshold"]
    trusted_prob_cap = FUSION_RULES["trusted_prob_cap"]

    for url_result in url_results:
        raw_url = url_result.get("url", "")
        parse_failed = False
        try:
            host = _host_from_url(raw_url)
        except Exception:
            host = ""
            parse_failed = True

        indicators = list(url_result.get("indicators", []))
        if raw_url and (parse_failed or not host):
            parse_failed = True
            if "unparseable_url" not in indicators:
                indicators.append("unparseable_url")

        raw_prob = float(url_result.get("prob", 0.0))
        if parse_failed:
            # A URL we cannot even parse is at least as suspicious as a phishing label,
            # but we still keep any higher model probability that came in.
            raw_prob = max(raw_prob, url_phishing_threshold)

        trusted = is_trusted(host) and not parse_failed

        # Rule: url prob on a trusted host is capped at the configured trusted cap
        effective_prob = min(raw_prob, trusted_prob_cap) if trusted else raw_prob

        processed_urls.append({
            "url": raw_url,
            "norm_url": url_result.get("norm_url", normalise_url(raw_url)),
            "prob": effective_prob,
            "raw_prob": raw_prob,
            "trusted": trusted,
            "indicators": indicators,
            "label": "phishing" if effective_prob >= url_phishing_threshold else "benign",
        })

    return processed_urls


def _apply_temperature(probs: tuple[float, float, float], temperature: float) -> tuple[float, float, float]:
    """Temperature-scale class probabilities as in bench/heldout/calibrate.py."""
    if temperature == 1.0:
        return probs
    logs = [math.log(p) if p > 0.0 else -math.inf for p in probs]
    top = max(logs) / temperature
    weights = [math.exp((lg / temperature) - top) if math.isfinite(lg) else 0.0 for lg in logs]
    total = sum(weights)
    if total <= 0.0:
        return probs
    return (weights[0] / total, weights[1] / total, weights[2] / total)


def _sms_components(sms_result: dict[str, Any] | None) -> tuple[float, float | None]:
    """Return (sms_score, sms_ham_prob) from an optional SMS model result."""
    if not sms_result or "probs" not in sms_result:
        return 0.0, None

    raw_ham = float(sms_result["probs"].get("ham", 0.0))
    raw_unwanted = float(sms_result["probs"].get("unwanted", 0.0))
    raw_scam = float(sms_result["probs"].get("scam", 0.0))
    scaled_ham, scaled_unwanted, scaled_scam = _apply_temperature(
        (raw_ham, raw_unwanted, raw_scam), float(FUSION_RULES["sms_temperature"])
    )
    sms_score = (
        FUSION_RULES["sms_scam_weight"] * scaled_scam
        + FUSION_RULES["sms_unwanted_weight"] * scaled_unwanted
    )
    return sms_score, scaled_ham


def _url_score(processed_urls: list[dict[str, Any]]) -> float:
    """Max untrusted URL probability, scaled by the configured URL weight."""
    untrusted_probs = [url["prob"] for url in processed_urls if not url["trusted"]]
    if not untrusted_probs:
        return 0.0
    return max(untrusted_probs) * FUSION_RULES["url_weight"]


def _cue_score(cues: list[dict[str, Any]]) -> tuple[float, set[str]]:
    """Return (cues_score, distinct cue types)."""
    distinct_cue_types = {cue["type"] for cue in cues if isinstance(cue, dict) and "type" in cue}
    cues_score = min(
        FUSION_RULES["cue_cap"],
        FUSION_RULES["cue_weight"] * len(distinct_cue_types),
    )
    return cues_score, distinct_cue_types


def _combo_score(distinct_cue_types: set[str], sms_ham_prob: float | None) -> float:
    """Score the classic urgency + threat/credential/payment scam combination."""
    combo = "urgency" in distinct_cue_types and bool(
        distinct_cue_types & {"threat", "credential_request", "payment_request"})
    confident_ham = (
        sms_ham_prob is not None
        and sms_ham_prob >= FUSION_RULES["sms_ham_confidence_threshold"]
    )
    if combo and not confident_ham:
        return FUSION_RULES["combo_score"]
    return 0.0


def _extra_cue_scores(cues: list[dict[str, Any]]) -> tuple[float, float]:
    """Return (app_install_score, collect_pin_score) from special cue combinations."""
    has_app_install = any(cue.get("type") == "app_install" for cue in cues if isinstance(cue, dict))
    app_install_score = FUSION_RULES["app_install_score"] if has_app_install else 0.0

    has_collect_request = any(
        cue.get("type") == "payment_request" and "collect request" in cue.get("text", "").lower()
        for cue in cues if isinstance(cue, dict)
    )
    has_pin_cue = any(
        cue.get("type") == "credential_request" and cue.get("text", "").lower() == "pin"
        for cue in cues if isinstance(cue, dict)
    )
    collect_pin_score = FUSION_RULES["collect_pin_score"] if (has_collect_request and has_pin_cue) else 0.0
    return app_install_score, collect_pin_score


def _label_and_level(risk: float, sms_result: dict[str, Any] | None) -> tuple[str, str]:
    """Derive label and level from the fused risk score."""
    if risk >= FUSION_RULES["label_threshold"]:
        label = "scam"
    elif (sms_result and sms_result.get("label") == "unwanted") or risk >= FUSION_RULES["medium_level_threshold"]:
        label = "unwanted"
    else:
        label = "ham"

    if risk >= FUSION_RULES["high_level_threshold"] or label == "scam":
        level = "high"
    elif risk >= FUSION_RULES["medium_level_threshold"]:
        level = "medium"
    else:
        level = "low"

    return label, level


def _collect_indicators(processed_urls: list[dict[str, Any]], distinct_cue_types: set[str]) -> list[str]:
    """Gather the unique indicator list reported in the evidence."""
    all_indicators: list[str] = []
    for url in processed_urls:
        for indicator in url.get("indicators", []):
            if indicator not in all_indicators:
                all_indicators.append(indicator)
    for cue_type in sorted(distinct_cue_types):
        label = SENDER_MISMATCH_INDICATOR if cue_type == "sender_mismatch" else cue_type
        if label not in all_indicators:
            all_indicators.append(label)
    return all_indicators


def fuse(
    text: str,
    sms_result: dict | None,
    url_results: list[dict],
    cues: list[dict],
    extra_parts: list[dict[str, Any]] | None = None,
    sender: str | None = None,
) -> Evidence:
    """Fuse detector outputs and cue spans into one Evidence object.

    Parameters:
        text: the original message text.
        sms_result: optional SMS detector result dict with "probs" and "label".
        url_results: list of URL detector result dicts.
        cues: list of cue span dicts extracted from the text.
        extra_parts: optional evidence parts from plug-in detectors.
        sender: optional SMS sender; for a DLT header sender the links count only when the
            SMS model calls the message a scam. Without an SMS model answer the sender is
            ignored, so a message is never waved through on the sender alone.
    """
    processed_urls = _process_urls(url_results)
    sms_score, sms_ham_prob = _sms_components(sms_result)
    cues_score, distinct_cue_types = _cue_score(cues)
    sms_answered = bool(sms_result and sms_result.get("probs"))
    sms_says_scam = sms_answered and sms_result.get("label") == "scam"
    registered_sender = sms_answered and sender_header(sender) is not None
    if registered_sender and not sms_says_scam:
        _discount_registered_sender_urls(processed_urls)
    url_score = _url_score(processed_urls)
    combo_score = _combo_score(distinct_cue_types, sms_ham_prob)
    app_install_score, collect_pin_score = _extra_cue_scores(cues)
    extra_parts = list(extra_parts or [])
    extra_risk = max((clamp_risk(part.get("risk", 0.0)) for part in extra_parts), default=0.0)

    risk = max(
        sms_score,
        url_score,
        cues_score,
        combo_score,
        app_install_score,
        collect_pin_score,
        extra_risk,
    )
    # A bank-style alert from a personal number is never routine: floor at medium.
    if "sender_mismatch" in distinct_cue_types:
        risk = max(risk, FUSION_RULES["medium_level_threshold"])
    # A bank alert that also asks for a secret code is a credential-phishing shape.
    bank_credential_request = secret_request(text) and is_bank_alert(text)
    if bank_credential_request:
        risk = max(risk, FUSION_RULES["high_level_threshold"])
    # A message that follows a known scam script is a scam whatever the model says.
    script_indicator = scam_script(text)
    if script_indicator is not None:
        risk = max(risk, FUSION_RULES["high_level_threshold"])
    risk = round(min(1.0, max(0.0, risk)), FUSION_RULES["risk_round_decimals"])

    label, level = _label_and_level(risk, sms_result)
    indicators = _collect_indicators(processed_urls, distinct_cue_types)
    if bank_credential_request and BANK_ALERT_CREDENTIAL_INDICATOR not in indicators:
        indicators.append(BANK_ALERT_CREDENTIAL_INDICATOR)
    if script_indicator is not None and script_indicator not in indicators:
        indicators.append(script_indicator)
    sms_label = (
        sms_result.get("label")
        if sms_result and sms_result.get("probs")
        else None
    )

    return Evidence(
        label=label,
        risk=risk,
        level=level,
        threshold=FUSION_RULES["label_threshold"],
        indicators=indicators,
        cue_spans=list(cues),
        urls=processed_urls,
        detector_versions=dict(DETECTOR_VERSIONS),
        extra_detectors=extra_parts,
        sms_label=sms_label,
        registered_sender=registered_sender,
    )
