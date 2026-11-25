"""Alert policy: notify only when a verdict carries real threat evidence."""
from sentinel.alert_policy import evidence_should_alert, should_alert
from sentinel.fusion import Evidence, fuse


def _evidence(level, cue_types=(), urls=(), sms_label=None):
    return Evidence(
        label="unwanted",
        risk=0.45,
        level=level,
        threshold=0.7,
        cue_spans=[{"type": cue_type} for cue_type in cue_types],
        urls=list(urls),
        sms_label=sms_label,
    )


def test_high_always_alerts_and_low_never():
    assert should_alert("high", set(), False, 0.0)
    assert not should_alert("low", {"credential_request"}, True, 0.9)


def test_medium_needs_threat_evidence():
    assert not should_alert("medium", set(), False, 0.0)
    assert not should_alert("medium", {"urgency", "reward"}, True, 0.2)
    assert should_alert("medium", {"payment_request"}, False, 0.0)
    assert should_alert("medium", {"impersonation"}, True, 0.0)
    assert not should_alert("medium", {"impersonation"}, False, 0.0)
    assert should_alert("medium", set(), True, 0.5)


def test_evidence_high_alerts():
    assert evidence_should_alert(_evidence("high"))


def test_evidence_medium_with_scam_sms_label_alerts():
    assert evidence_should_alert(_evidence("medium", sms_label="scam"))


def test_evidence_medium_with_unwanted_sms_label_and_no_cue_is_quiet():
    assert not evidence_should_alert(_evidence("medium", sms_label="unwanted"))


def test_evidence_medium_with_credential_request_cue_alerts():
    assert evidence_should_alert(_evidence("medium", cue_types=["credential_request"]))


def test_evidence_low_is_quiet():
    evidence = _evidence(
        "low",
        cue_types=["credential_request"],
        urls=[{"prob": 0.9, "trusted": False}],
    )
    assert not evidence_should_alert(evidence)


def test_evidence_medium_with_untrusted_url_missing_trusted_flag_alerts():
    evidence = _evidence("medium", urls=[{"prob": 0.5}])
    assert evidence_should_alert(evidence)


def test_sms_label_comes_from_fused_sms_result_but_stays_out_of_output():
    evidence = fuse(
        "Hello",
        {"probs": {"ham": 0.8, "unwanted": 0.1, "scam": 0.1}, "label": "ham"},
        [],
        [],
    )
    assert evidence.sms_label == "ham"
    assert "sms_label" not in evidence.to_dict()


def test_evidence_medium_with_sender_mismatch_cue_alerts():
    assert evidence_should_alert(_evidence("medium", cue_types=["sender_mismatch"]))


def _fused(text, sms_label, sender, url="http://bit.ly/a1", prob=0.99, indicators=()):
    probs = {"ham": 0.02, "unwanted": 0.03, "scam": 0.95} if sms_label == "scam" else {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}
    return fuse(
        text,
        {"probs": probs, "label": sms_label},
        [{"url": url, "prob": prob, "indicators": list(indicators)}],
        [],
        None,
        sender,
    )


def test_registered_sender_link_alone_is_quiet():
    evidence = _fused("Sale is live. Shop now: http://bit.ly/a1", "ham", "AD-NEWSHP-P")
    assert evidence.level == "low"
    assert evidence.urls[0]["prob"] == 0.2 and evidence.urls[0]["raw_prob"] == 0.99
    assert not evidence_should_alert(evidence)


def test_link_keeps_full_risk_for_other_senders():
    for sender in (None, "+919876543210", "56161", "Unknown"):
        evidence = _fused("Sale is live. Shop now: http://bit.ly/a1", "ham", sender)
        assert evidence.level == "high", sender
        assert evidence_should_alert(evidence), sender


def test_registered_sender_link_counts_when_model_says_scam():
    evidence = _fused("Sale is live. Shop now: http://bit.ly/a1", "scam", "AD-NEWSHP-P")
    assert evidence.urls[0]["prob"] == 0.99
    assert evidence_should_alert(evidence)


def test_registered_sender_hard_url_indicator_is_never_capped():
    for indicator in ("risky_tld", "ip_host"):
        evidence = _fused("Open http://kyc-help.xyz/a1", "ham", "AD-HDFCBK-S", "http://kyc-help.xyz/a1", 0.9, [indicator])
        assert evidence.level == "high", indicator
        assert evidence_should_alert(evidence), indicator


def test_registered_sender_medium_needs_model_scam():
    assert not should_alert("medium", {"credential_request", "payment_request"}, True, 0.9, "ham", registered_sender=True)
    assert not should_alert("medium", {"threat"}, False, 0.0, None, registered_sender=True)
    assert should_alert("medium", set(), False, 0.0, "scam", registered_sender=True)
    assert should_alert("high", set(), False, 0.0, "ham", registered_sender=True)
    assert should_alert("medium", {"credential_request"}, False, 0.0, "ham", registered_sender=False)


def test_registered_sender_bank_alert_asking_for_secret_still_alerts():
    ham = {"probs": {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}, "label": "ham"}
    evidence = fuse("Rs 4,999 debited from A/c XX9012. Reply with OTP 4821 to reverse the debit.", ham, [], [], None, "AD-HDFCBK-S")
    assert evidence.level == "high" and evidence.registered_sender
    assert evidence_should_alert(evidence)


def test_bank_in_zone_is_trusted_and_lookalike_is_not():
    from sentinel.fusion import is_trusted

    assert is_trusted("1.hdfc.bank.in")
    assert not is_trusted("bank.in.evil.xyz")
    assert not is_trusted("hdfc-bank.in")
