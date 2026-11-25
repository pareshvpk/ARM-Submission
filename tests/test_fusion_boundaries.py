from __future__ import annotations

import pytest

from sentinel.detectors import sms_cues
from sentinel.fusion import fuse, is_bank_alert, secret_request
from sentinel.rules import FUSION_RULES


MEDIUM_LEVEL_THRESHOLD = FUSION_RULES["medium_level_threshold"]
LABEL_THRESHOLD = FUSION_RULES["label_threshold"]
HIGH_LEVEL_THRESHOLD = FUSION_RULES["high_level_threshold"]
EPSILON = 0.001


def _sms_result(score: float) -> dict:
    temperature = FUSION_RULES["sms_temperature"]
    scam_weight = FUSION_RULES["sms_scam_weight"]
    scaled_scam = score / scam_weight
    scaled_ham = 1.0 - scaled_scam
    ham_pow = scaled_ham ** temperature
    scam_pow = scaled_scam ** temperature
    total = ham_pow + scam_pow
    raw_ham = ham_pow / total if total else 0.5
    raw_scam = scam_pow / total if total else 0.5
    return {
        "probs": {"ham": raw_ham, "unwanted": 0.0, "scam": raw_scam},
        "label": "scam" if score >= 0.5 else "ham",
    }


@pytest.mark.parametrize("score, expected_label, expected_level", [
    (MEDIUM_LEVEL_THRESHOLD - EPSILON, "ham", "low"),
    (MEDIUM_LEVEL_THRESHOLD, "unwanted", "medium"),
    (MEDIUM_LEVEL_THRESHOLD + EPSILON, "unwanted", "medium"),
])
def test_fusion_medium_level_threshold_boundary(score, expected_label, expected_level):
    evidence = fuse("boundary", _sms_result(score), [], [])
    assert evidence.label == expected_label
    assert evidence.level == expected_level
    assert evidence.threshold == LABEL_THRESHOLD


@pytest.mark.parametrize("score, expected_label, expected_level", [
    (LABEL_THRESHOLD - EPSILON, "unwanted", "medium"),
    (LABEL_THRESHOLD, "scam", "high"),
    (LABEL_THRESHOLD + EPSILON, "scam", "high"),
])
def test_fusion_label_threshold_boundary(score, expected_label, expected_level):
    evidence = fuse("boundary", _sms_result(score), [], [])
    assert evidence.label == expected_label
    assert evidence.level == expected_level
    assert evidence.threshold == LABEL_THRESHOLD


@pytest.mark.parametrize("score, expected_label, expected_level", [
    (HIGH_LEVEL_THRESHOLD - EPSILON, "unwanted", "medium"),
    (HIGH_LEVEL_THRESHOLD, "scam", "high"),
    (HIGH_LEVEL_THRESHOLD + EPSILON, "scam", "high"),
])
def test_fusion_high_level_threshold_boundary(score, expected_label, expected_level):
    evidence = fuse("boundary", _sms_result(score), [], [])
    assert evidence.label == expected_label
    assert evidence.level == expected_level
    assert evidence.threshold == LABEL_THRESHOLD

def _sender_cue():
    return [{"type": "sender_mismatch", "start": 0, "end": 0, "text": ""}]


def test_sender_mismatch_floors_risk_to_medium():
    evidence = fuse("sender", None, [], _sender_cue())
    assert evidence.level == "medium"
    assert evidence.risk >= MEDIUM_LEVEL_THRESHOLD
    assert "bank-style alert sent from a personal mobile number" in evidence.indicators


def test_sender_mismatch_keeps_high_verdict_high():
    evidence = fuse("sender", _sms_result(LABEL_THRESHOLD + EPSILON), [], _sender_cue())
    assert evidence.level == "high"


def test_empty_probs_map_leaves_sms_label_unset():
    evidence = fuse("empty probs", {"probs": {}, "label": "scam"}, [], [])
    assert evidence.sms_label is None


def _credential_cue():
    return [{"type": "credential_request", "start": 0, "end": 0, "text": "OTP"}]


def test_bank_alert_with_credential_request_floors_risk_to_high():
    text = "Rs 4,999 debited from A/c XX9012. Reply with OTP 4821 to reverse the debit."
    evidence = fuse(text, None, [], _credential_cue())
    assert evidence.level == "high"
    assert evidence.risk >= HIGH_LEVEL_THRESHOLD
    assert "bank alert asking for a secret code" in evidence.indicators


def test_genuine_otp_with_credential_cue_is_not_raised_by_bank_alert_rule():
    text = "Your OTP is 482913. Do not share it with anyone."
    evidence = fuse(text, None, [], _credential_cue())
    assert evidence.level != "high"
    assert "bank alert asking for a secret code" not in evidence.indicators


SECRET_REQUEST_BANK_ALERT_SCAMS = [
    "Rs 4,999 debited from A/c XX9012. Read out OTP 4821 to the officer.",
    "Rs 4,999 debited from A/c XX9012. Spell out the 6 digit code 482193.",
    "Rs 4,999 debited from A/c XX9012. Repeat the code 482193 to cancel the debit.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 bata do.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 bataye.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 daal do.",
    "Rs 5,000 debited from A/c XX1234. OTP 4821 required to stop the debit.",
    "Rs 5,000 debited from A/c XX1234. Don't worry, share OTP with our executive to stop the debit.",
    "Rs 5,000 debited from A/c XX1234. Do not panic - send OTP 4821 to reverse.",
    "Rs 5,000 debited from A/c XX1234. No need to visit branch, just tell the OTP to our agent to cancel.",
    "Rs 5,000 debited from A/c XX1234. Kindly reveal your OTP to reverse the debit.",
    "Rs 5,000 debited from A/c XX1234. Please disclose your OTP to stop the debit.",
    "Rs 5,000 debited from A/c XX1234. Don't worry, our officer will call you, share OTP to reverse.",
    "Rs 5,000 debited from A/c XX1234. Don't worry share OTP 4821 to cancel.",
    "Rs 5,000 debited from A/c XX1234. If not you share OTP 4821 to cancel.",
    "Rs 5,000 debited from A/c XX1234. If you did not authorise share OTP to cancel.",
    "Rs 5,000 debited from A/c XX1234. If not you, we ask you to share OTP to reverse the transaction.",
    "Rs 5,000 debited from A/c XX1234. Don't worry, we request you to share OTP to reverse debit.",
    "Rs 5000 debited from A/c XX1234. Fikr mat karo OTP 4821 bhejo cancel karne ke liye",
    "Rs 5,000 debited from A/c XX1234. If you have not done this transaction, share OTP 4821 to cancel debit.",
    "Rs 5,000 debited from A/c XX1234. If this is not you, share OTP 4821 to cancel debit.",
    "Rs 5,000 debited from A/c XX1234. If not recognized, share OTP 4821 to cancel debit.",
    "Rs 5,000 debited from A/c XX1234. Do not delay, share OTP 4821 to cancel debit.",
    "Rs 5,000 debited from A/c XX1234. Cancel karne ke liye OTP batao na.",
    "Rs 5,000 debited from your card. Share OTP 4821 to cancel debit.",
]


def test_secret_request_and_is_bank_alert_true_for_scams():
    for text in SECRET_REQUEST_BANK_ALERT_SCAMS:
        assert secret_request(text), text
        assert is_bank_alert(text), text
        evidence = fuse(text, None, [], sms_cues(text))
        assert evidence.level == "high", text
        assert "bank alert asking for a secret code" in evidence.indicators, text


SECRET_REQUEST_FALSE_CASES = [
    "Rs 5,000 debited from A/c XX1234. Never share your OTP with anyone.",
    "Rs 5,000 debited from A/c XX1234 at ATM using PIN. Avl bal Rs 20,000.",
    "INR 1,500 withdrawn from A/c XX1234 using card PIN at ATM.",
    "Rs 1,000 debited from card XX1234. CVV was not used.",
    "Rs 500 debited from A/c XX1234 via UPI. Never share your UPI PIN.",
    "Rs 5,000 debited from A/c XX1234. Please verify this transaction in the app.",
    "Rs 0.00 debited from A/c XX1234 for KYC update.",
    "OTP 482913 for debit of Rs 5,000 from A/c XX1234. Do not share with anyone.",
    "Rs 5,000 debited from A/c XX1234. Share nothing; we never ask for OTP.",
    "Rs 2,000 credited to A/c XX1234 on 12-Nov. Ref 123456. Avl bal Rs 25,000. Do not share OTP.",
    "Rs 5,000 debited from A/c XX1234. Please do not share OTP or PIN with anyone.",
    "Rs 5,000 debited from A/c XX1234. OTP kisi ko mat batao.",
    "Rs 5,000 debited from A/c XX1234. Bank never asks you to share your OTP.",
    "Rs 5,000 debited from A/c XX1234. We will not ask you to share your PIN.",
    "Rs 5,000 debited from A/c XX1234. OTP kisi ko na bataye.",
    "Rs 5,000 debited from A/c XX1234. We never, under any circumstances, and for no reason, ask you to share your OTP to reverse the debit.",
    "Rs 5,000 debited from A/c XX1234. We do not under any circumstances ever ask you to share your OTP to reverse the debit.",
    "Rs 5,000 debited from A/c XX1234. Never reveal your OTP, PIN or CVV to anyone.",
    "Rs 5,000 debited from A/c XX1234. HDFC Bank never calls to ask you to disclose your OTP.",
    "Rs 5,000 debited from A/c XX1234. Never, under any circumstances, share your OTP.",
    "Rs 5,000 debited from A/c XX1234. Do not - we repeat - share your OTP.",
    "Rs 5,000 debited from A/c XX1234. Share your OTP with no one.",
    "Rs 5,000 debited from A/c XX1234. Tell no one your OTP or PIN.",
    "Rs 5,000 debited from A/c XX1234. Give your PIN to no one.",
    "Rs 5,000 debited from A/c XX1234. Never share, tell or disclose your OTP to anyone.",
    "Rs 5,000 debited from A/c XX1234. Quote reference code 849201 for any query.",
    "Rs 5,000 debited from A/c XX1234. Show code to merchant to collect goods.",
    "Rs 5,000 debited from A/c XX1234. Please quote code 123456 for any dispute.",
    "Rs 4,500.00 spent on Card XX1234 at RELIANCE on 14-Nov-26. Auth code 849201 - if not you, SMS BLOCK to 56767.",
    "Rs 5,000 debited from A/c XX1234. SMS with OTP has been sent to your registered mobile.",
    "Rs 5,000 debited from A/c XX1234 at ATM using PIN, if not you send SMS to 56767",
    "Rs 10,000 debited from A/c XX1234 at ATM using PIN, if you didn't do this forward this SMS to 9223008333",
    "Rs 5,000 debited from A/c XX1234. Share your OTP with no-one.",
    "Rs 5,000 debited from A/c XX1234. Neither bank nor its employees will ask you to share your OTP.",
    "Rs 5,000 debited from A/c XX1234. Share your OTP with none.",
    "482913 is your OTP for txn of Rs 5,000 at Amazon. Enter it on the payment page within 10 minutes.",
]


def test_secret_request_false_cases():
    for text in SECRET_REQUEST_FALSE_CASES:
        assert not secret_request(text), text


def test_fuse_no_models_does_not_reach_high_for_disclaimers_and_routine_alerts():
    for text in SECRET_REQUEST_FALSE_CASES[:-1]:
        evidence = fuse(text, None, [], sms_cues(text))
        assert evidence.level != "high", text
        assert "bank alert asking for a secret code" not in evidence.indicators, text


def test_scam_script_floors_high_and_names_the_script():
    """A known scam script is high risk even when the SMS model is confident it is ham."""
    from sentinel.fusion import fuse, scam_script

    ham = {"probs": {"ham": 0.98, "unwanted": 0.01, "scam": 0.01}, "label": "ham"}
    text = "CBI calling. You are under digital arrest; join the video call now."
    assert scam_script(text) == "digital arrest threat"
    evidence = fuse(text, ham, [], [])
    assert evidence.level == "high"
    assert "digital arrest threat" in evidence.indicators

    advisory = "Digital arrest is a scam. Police never arrest on a video call. Call helpline 1930."
    assert scam_script(advisory) is None
    assert fuse(advisory, ham, [], []).level == "low"


def test_scam_script_amount_and_word_boundaries():
    """The refund script needs a payment under Rs 100 next to a pay verb; larger amounts do not match."""
    from sentinel.fusion import scam_script

    assert scam_script("Refund ke liye sirf Rs 5 bhejo, phir Rs 2,000 wapas milega") is not None
    assert scam_script("For refund, pay Rs 1,499 and it will be credited") is None
    assert scam_script("Refund of Rs 20 credited. Paytm balance updated.") is None
    assert scam_script("Guaranteed returns plan at 7.1% p.a. Speak to your advisor.") is None
    assert scam_script("Daily 5% profit guaranteed, join our WhatsApp group") is not None


def test_six_new_scam_scripts_positives_and_negatives():
    from sentinel.fusion import fuse, scam_script

    positives = [
        (
            "Refund of Rs 4,999 is pending. Enter your UPI PIN to receive it.",
            "asks for your UPI PIN to receive money",
        ),
        (
            "Your electricity connection will be cut tonight at 9:30 PM due to an unpaid bill. Call the officer now at 9876543210.",
            "power cut threat with a number to call",
        ),
        (
            "Earn Rs 5,000 a day working from home! Like YouTube videos and get paid.",
            "paid online task or work-from-home job offer",
        ),
        (
            "Hi Mom, I lost my phone and this is my new number. Please send Rs 15,000 urgently.",
            "new number asking for money",
        ),
        (
            "Congratulations! You won Rs 25,00,000 in the KBC lucky draw. Pay Rs 9,999 processing fee to claim.",
            "prize that needs a fee",
        ),
        (
            "Install this app to update your bank KYC.",
            "asks you to install an app file",
        ),
    ]
    for text, expected_indicator in positives:
        assert scam_script(text) == expected_indicator, text
        evidence = fuse(text, None, [], [])
        assert evidence.level == "high", text
        assert expected_indicator in evidence.indicators, text

    negatives = [
        "Never share your UPI PIN, it is not needed to receive money.",
        "Power shutdown for planned maintenance today 10 AM to 2 PM.",
        "IND vs SA T20 is live, Prize Pool 2,80,00,000, Entry Fee 49.",
        "Your Rs 2,000 payment to Ramesh was successful.",
        "Beware of fraud: do not install apps sent by unknown callers.",
        "Reached home, will call you later.",
    ]
    for text in negatives:
        assert scam_script(text) is None, text


def test_power_cut_script_consumer_number_regression():
    from sentinel.fusion import scam_script

    bill_reminder = (
        "Dear Consumer 1002345678, your electricity bill is due today. "
        "Pay now to avoid power disconnection."
    )
    scam = "Your electricity will be disconnected tonight at 9.30 pm. Call 9876543210 immediately."
    assert scam_script(bill_reminder) is None
    assert scam_script(scam) == "power cut threat with a number to call"


def test_registered_sender_discount_needs_an_sms_model_answer():
    """Without an SMS model answer the sender must not lower link risk or silence the alert."""
    from sentinel.alert_policy import evidence_should_alert
    from sentinel.fusion import fuse

    url = [{"url": "http://short.example/a1", "norm_url": "short.example/a1", "prob": 0.97, "indicators": []}]
    ham = {"probs": {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}, "label": "ham"}
    text = "Your statement is ready: http://short.example/a1"

    with_model = fuse(text, ham, url, [], None, "AD-HDFCBK-S")
    assert with_model.registered_sender is True
    assert with_model.level == "low"

    without_model = fuse(text, None, url, [], None, "AD-HDFCBK-S")
    assert without_model.registered_sender is False
    assert without_model.level == "high"
    assert evidence_should_alert(without_model) is True

