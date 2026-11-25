"""DT-2 plain-promotion detector and presentation tests (Python)."""
from __future__ import annotations

from unittest.mock import MagicMock

from sentinel.advisor import PROMOTION_ADVICE, is_plain_promotion
from sentinel.cli import format_human_output, main
from sentinel.fusion import Evidence, fuse
from sentinel.pipeline import analyse
from sentinel.rules import CUE_RULES, PROMOTION_RULES


def _evidence(level="medium", label="unwanted", cues=None, risk=0.45):
    return Evidence(
        label=label,
        risk=risk,
        level=level,
        threshold=0.7,
        indicators=[],
        cue_spans=cues or [],
        urls=[],
        detector_versions={},
    )


SHOE = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"


def test_promotion_rules_loaded():
    assert PROMOTION_RULES["level"] == "medium"
    assert PROMOTION_RULES["label"] == "unwanted"
    assert set(PROMOTION_RULES["blocked_cue_types"]) == {
        "urgency",
        "threat",
        "credential_request",
        "payment_request",
        "impersonation",
        "reward",
        "app_install",
    }
    assert "reply" in PROMOTION_RULES["reply_contact_phrases"]


def test_shoe_store_plain_promotion():
    assert is_plain_promotion(SHOE, _evidence()) is True


def test_shoe_plus_domain_not_plain_promotion():
    assert is_plain_promotion(SHOE + " Visit shop-now.world", _evidence()) is False


def test_shoe_plus_email_not_plain_promotion():
    assert is_plain_promotion(SHOE + " mail offers@metro.in", _evidence()) is False


def test_shoe_plus_payment_handle_not_plain_promotion():
    assert is_plain_promotion(SHOE + " pay to metro@ybl", _evidence()) is False


def test_shoe_plus_digits_still_plain_promotion():
    assert is_plain_promotion(SHOE + " Rs 499.99", _evidence()) is True


def test_shoe_plus_stars_still_plain_promotion():
    assert is_plain_promotion(SHOE + " 4.5 stars", _evidence()) is True

def test_shoe_plus_url_not_promotion():
    assert is_plain_promotion(SHOE + " Visit metroshoes.com now", _evidence()) is False
    assert is_plain_promotion(SHOE + " http://example.com/offer", _evidence()) is False


def test_shoe_plus_phone_not_promotion():
    assert is_plain_promotion(SHOE + " 9876543210", _evidence()) is False
    assert is_plain_promotion(SHOE + " Call 9876543210", _evidence()) is False


def test_shoe_plus_devanagari_phone_not_promotion():
    # Python re treats \d as Unicode; Kotlin must match with UNICODE_CHARACTER_CLASS.
    assert is_plain_promotion(SHOE + " ९८७६५४३२१०", _evidence()) is False
    assert is_plain_promotion(SHOE + " Call ९८७६५४३२१०", _evidence()) is False


def test_blocked_cue_types_subset_of_type_order():
    known = set(CUE_RULES["type_order"])
    for cue_type in PROMOTION_RULES["blocked_cue_types"]:
        assert cue_type in known, f"blocked cue type {cue_type!r} missing from cues.type_order"


def test_shoe_plus_reply_not_promotion():
    assert is_plain_promotion(SHOE + " Reply YES to claim", _evidence()) is False
    assert is_plain_promotion(SHOE + " Please reply", _evidence()) is False


def test_shoe_level_high_not_promotion():
    assert is_plain_promotion(SHOE, _evidence(level="high")) is False
    assert is_plain_promotion(SHOE, _evidence(level="low")) is False
    assert is_plain_promotion(SHOE, _evidence(label="scam")) is False
    assert is_plain_promotion(SHOE, _evidence(label="ham")) is False


def test_cue_blocks_promotion():
    cues = [{"type": "urgency", "start": 0, "end": 5, "text": "urgent"}]
    assert is_plain_promotion(SHOE, _evidence(cues=cues)) is False
    cues2 = [{"type": "reward", "start": 0, "end": 4, "text": "won"}]
    assert is_plain_promotion(SHOE, _evidence(cues=cues2)) is False


def test_reply_phrases_block():
    for phrase in ("WhatsApp us", "Please call us", "Message us now", "DM for details", "Send YES"):
        assert is_plain_promotion(f"{SHOE} {phrase}", _evidence()) is False


def test_promotion_advice_matches_shared_rules():
    # Python and Kotlin both read promotion_no_action.advice_text from rules.json.
    assert PROMOTION_ADVICE == PROMOTION_RULES["advice_text"]
    assert PROMOTION_ADVICE.splitlines()[0] == "Promotion: no action needed. Ignore it, or block the sender if you do not want these."
    assert "No action needed. No action needed." not in PROMOTION_ADVICE


def test_promotion_advice_text_and_no_llama():
    assert PROMOTION_ADVICE.startswith("Promotion: no action needed.")
    assert "Promotion: no action needed. Ignore it, or block the sender if you do not want these." in PROMOTION_ADVICE
    assert "1. You do not need to reply or call." in PROMOTION_ADVICE
    assert "2. Never share an OTP, PIN or password, even with a shop." in PROMOTION_ADVICE
    assert "3. Block the sender if these messages bother you." in PROMOTION_ADVICE

    advisor = MagicMock()
    advisor.generate.return_value = ("should not be called", {})
    sms = MagicMock()
    sms.predict.return_value = {"probs": {"ham": 0.2, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"}
    result = analyse(SHOE, sms_det=sms, advisor=advisor)
    advisor.generate.assert_not_called()
    assert result["is_plain_promotion"] is True
    assert result["advice"] == PROMOTION_ADVICE
    assert result["advice_source"] == "template"
    assert result["evidence"].level == "medium"
    assert result["evidence"].label == "unwanted"


def test_cli_kind_line(monkeypatch, capsys):
    sms = MagicMock()
    sms.predict.return_value = {"probs": {"ham": 0.2, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"}
    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, sms, None))
    assert main(["scan", SHOE, "--no-llm"]) == 0
    out = capsys.readouterr().out
    assert "Kind: promotion (no action needed)" in out
    assert "Promotion: no action needed." in out


def test_cli_json_kind(monkeypatch, capsys):
    import json

    sms = MagicMock()
    sms.predict.return_value = {"probs": {"ham": 0.2, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"}

    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, sms, None))
    assert main(["scan", SHOE, "--no-llm", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["is_plain_promotion"] is True
    assert data["kind"] == "promotion"
    assert data["advice"] == PROMOTION_ADVICE
    assert data["advice_source"] == "template"


def test_non_promotion_keeps_standard():
    result = analyse("URGENT your SBI account is blocked today. Update now: otp needed")
    assert result["is_plain_promotion"] is False
    out = format_human_output("URGENT your SBI account is blocked today.", result)
    assert "Kind: promotion" not in out


def test_fuse_preserves_verdict_for_promotion():
    from sentinel.detectors import sms_cues

    sms = {"probs": {"ham": 0.2, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"}
    ev = fuse(SHOE, sms, [], sms_cues(SHOE))
    assert is_plain_promotion(SHOE, ev) is True
    assert ev.level == "medium"
    assert ev.label == "unwanted"
