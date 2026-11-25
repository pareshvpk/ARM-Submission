from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from sentinel.advisor import (
    SYSTEM_PROMPT,
    build_prompt,
    guard,
    parse_llama_output,
    template_advice,
)
from sentinel.cli import format_human_output, highlight_cues, main
from sentinel.detectors import (
    get_registered_domain,
    sigmoid,
    sms_cues,
    url_indicators,
)
from sentinel.fusion import Evidence, fuse, is_trusted, is_untrusted_hosting
from sentinel.pipeline import analyse
from sentinel.rules import FUSION_RULES


def _raw_probs_for_scaled(ham_scaled: float, unwanted_scaled: float, scam_scaled: float) -> dict:
    temperature = FUSION_RULES["sms_temperature"]
    ham_pow = ham_scaled ** temperature
    unwanted_pow = unwanted_scaled ** temperature
    scam_pow = scam_scaled ** temperature
    total = ham_pow + unwanted_pow + scam_pow
    return {
        "ham": ham_pow / total,
        "unwanted": unwanted_pow / total,
        "scam": scam_pow / total,
    }


def _sms_result_for_score(score: float) -> dict:
    scam_weight = FUSION_RULES["sms_scam_weight"]
    temperature = FUSION_RULES["sms_temperature"]
    scaled_scam = score / scam_weight
    scaled_ham = 1.0 - scaled_scam
    ham_pow = scaled_ham ** temperature
    scam_pow = scaled_scam ** temperature
    total = ham_pow + scam_pow
    return {
        "probs": {
            "ham": ham_pow / total,
            "unwanted": 0.0,
            "scam": scam_pow / total,
        },
        "label": "scam" if score >= 0.5 else "ham",
    }


# --- 1. url_indicators cases ---
def test_url_indicators_ip_host():
    ind = url_indicators("http://192.168.1.1/login")
    assert "ip_host" in ind


def test_url_indicators_punycode():
    ind = url_indicators("http://xn--80ak6aa92e.com/page")
    assert "punycode" in ind


def test_url_indicators_at_sign():
    ind = url_indicators("http://user:pass@phish.com")
    assert "at_sign" in ind


def test_url_indicators_many_subdomains():
    ind = url_indicators("http://a.b.c.example.com/test")
    assert "many_subdomains" in ind


def test_url_indicators_risky_tld():
    ind = url_indicators("http://secure-update.xyz/login")
    assert "risky_tld" in ind


def test_url_indicators_shortener():
    ind = url_indicators("https://bit.ly/3xYz12")
    assert "shortener" in ind
    ind2 = url_indicators("http://tinyurl.com/abc")
    assert "shortener" in ind2


def test_url_indicators_brand_lookalike():
    # SBI lookalike
    ind_sbi = url_indicators("http://sbi-kyc-update.xyz/login")
    assert "brand_lookalike" in ind_sbi

    # HDFC lookalike
    ind_hdfc = url_indicators("http://hdfc-security-alert.top/verify")
    assert "brand_lookalike" in ind_hdfc

    # Genuine SBI domain should NOT have brand_lookalike
    ind_gen_sbi = url_indicators("https://retail.onlinesbi.sbi/retail/login.htm")
    assert "brand_lookalike" not in ind_gen_sbi
    ind_gen_sbi2 = url_indicators("https://login.sbi.co.in/portal")
    assert "brand_lookalike" not in ind_gen_sbi2

    # Genuine HDFC domain should NOT have brand_lookalike
    ind_gen_hdfc = url_indicators("https://netbanking.hdfcbank.com/netbanking/")
    assert "brand_lookalike" not in ind_gen_hdfc


# --- 2. sms_cues offsets ---
def test_sms_cues_offsets_and_types():
    text = "URGENT: your SBI account is blocked today. Update now: otp needed or legal action will follow"
    cues = sms_cues(text)

    assert len(cues) > 0
    cue_types = {c["type"] for c in cues}
    assert "urgency" in cue_types
    assert "impersonation" in cue_types
    assert "credential_request" in cue_types
    assert "threat" in cue_types

    # Every cue offset must map exactly to text
    for c in cues:
        s, e, t = c["start"], c["end"], c["text"]
        assert text[s:e] == t
        assert len(t) == e - s


def test_sms_cues_all_types():
    text = "URGENT update now pay electricity board won lottery arrest"
    cues = sms_cues(text)
    types_found = {c["type"] for c in cues}
    expected = {"urgency", "credential_request", "payment_request", "impersonation", "reward", "threat"}
    assert expected.issubset(types_found)


# --- 3. is_trusted incl. hosting exception and gov.in ---
def test_is_trusted_domains():
    # Official trusted domains
    assert is_trusted("sbi.co.in") is True
    assert is_trusted("login.sbi.co.in") is True
    assert is_trusted("onlinesbi.sbi") is True
    assert is_trusted("hdfcbank.com") is True
    assert is_trusted("netbanking.hdfcbank.com") is True
    assert is_trusted("google.com") is True

    # Gov / nic suffixes
    assert is_trusted("incometax.gov.in") is True
    assert is_trusted("epfindia.gov.in") is True
    assert is_trusted("uidai.gov.in") is True
    assert is_trusted("something.nic.in") is True

    # Untrusted hosting platforms (MUST NOT be trusted even if subdomains or google)
    assert is_untrusted_hosting("sites.google.com") is True
    assert is_trusted("sites.google.com") is False
    assert is_trusted("docs.google.com") is False
    assert is_trusted("drive.google.com") is False
    assert is_trusted("forms.gle") is False
    assert is_trusted("foo.firebaseapp.com") is False
    assert is_trusted("bar.web.app") is False
    assert is_trusted("myblog.blogspot.com") is False
    assert is_trusted("phish.github.io") is False
    assert is_trusted("corp.sharepoint.com") is False
    assert is_trusted("gateway.ipfs.io") is False
    assert is_trusted("ipfs.io") is False
    assert is_untrusted_hosting("gateway.ipfs.io") is True
    assert is_untrusted_hosting("ipfs.io") is True
    assert is_untrusted_hosting("myipfs.example.com") is False
    assert is_untrusted_hosting("cdn-ipfs.example.org") is False

    # Untrusted lookalikes
    assert is_trusted("sbi-kyc.xyz") is False
    assert is_trusted("hdfc-security.com") is False
    assert is_trusted("random-domain.in") is False


# --- 4. fuse labels for at least 5 scenarios ---
def test_fuse_scenario_1_trusted_bank_debit_alert_ham():
    # Scenario 1: Trusted bank link + debit alert -> ham
    text = "Rs 500 debited from SBI account. Check balance at https://sbi.co.in"
    sms_res = {"probs": {"ham": 0.95, "unwanted": 0.04, "scam": 0.01}, "label": "ham"}
    url_res = [{"url": "https://sbi.co.in", "prob": 0.95, "indicators": []}]
    cues = [{"type": "impersonation", "start": 21, "end": 24, "text": "SBI"}]

    ev = fuse(text, sms_res, url_res, cues)
    assert ev.label == "ham"
    assert ev.level == "low"
    assert ev.urls[0]["trusted"] is True
    # The raw model probability is above the cap, so this proves the cap is applied.
    assert ev.urls[0]["raw_prob"] == 0.95
    assert ev.urls[0]["prob"] == 0.2


def test_fuse_scenario_2_lookalike_link_kyc_urgency_scam():
    # Scenario 2: Look-alike link + KYC urgency -> scam
    text = "Dear customer your SBI account is blocked today. Update KYC now: http://sbi-kyc.xyz"
    sms_res = {"probs": {"ham": 0.02, "unwanted": 0.08, "scam": 0.90}, "label": "scam"}
    url_res = [{"url": "http://sbi-kyc.xyz", "prob": 0.95, "indicators": ["brand_lookalike", "risky_tld"]}]
    cues = [
        {"type": "urgency", "start": 34, "end": 41, "text": "blocked"},
        {"type": "credential_request", "start": 56, "end": 59, "text": "KYC"},
    ]

    ev = fuse(text, sms_res, url_res, cues)
    assert ev.label == "scam"
    assert ev.level == "high"
    assert ev.risk >= 0.7
    assert ev.urls[0]["trusted"] is False


def test_fuse_scenario_3_no_model_cues_only():
    # Scenario 3: No model (sms_res is None) + cues only
    text = "URGENT! You won lottery cash prize! Legal action if not claimed today!"
    sms_res = None
    url_res = []
    cues = [
        {"type": "urgency", "start": 0, "end": 6, "text": "URGENT"},
        {"type": "reward", "start": 16, "end": 23, "text": "lottery"},
        {"type": "threat", "start": 36, "end": 48, "text": "Legal action"},
    ]

    ev = fuse(text, sms_res, url_res, cues)
    # urgency + threat is the classic scam combination -> combo rule 0.72 (beats 3 * 0.15 = 0.45)
    assert ev.risk == 0.72
    assert ev.label == "scam"
    assert ev.level == "high"


def test_fuse_hinglish_threat_combo_is_scam():
    from sentinel.detectors import sms_cues
    text = "Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko 9876543210 call karein"
    ev = fuse(text, None, [], sms_cues(text))
    assert ev.label == "scam" and ev.level == "high"


def test_fuse_otp_alert_stays_low():
    from sentinel.detectors import sms_cues
    text = "Your OTP for HDFC NetBanking is 482910. Valid for 5 mins. Do not share it with anyone."
    ev = fuse(text, None, [], sms_cues(text))
    assert ev.level == "low"


def test_fuse_scenario_4_hosted_docs_google_phishing_not_trusted():
    # Scenario 4: Hosted docs.google.com phishing not trusted
    text = "Verify your account immediately: https://docs.google.com/forms/d/e/123/viewform"
    sms_res = {"probs": {"ham": 0.1, "unwanted": 0.2, "scam": 0.7}, "label": "scam"}
    url_res = [{"url": "https://docs.google.com/forms/d/e/123/viewform", "prob": 0.92, "indicators": []}]
    cues = [
        {"type": "credential_request", "start": 0, "end": 6, "text": "Verify"},
        {"type": "urgency", "start": 23, "end": 34, "text": "immediately"},
    ]

    ev = fuse(text, sms_res, url_res, cues)
    # docs.google.com must NOT be trusted
    assert ev.urls[0]["trusted"] is False
    assert ev.urls[0]["prob"] == 0.92  # not capped at 0.2
    assert ev.label == "scam"
    assert ev.level == "high"


def test_fuse_scenario_5_unwanted_marketing_promo():
    # Scenario 5: Promotional marketing SMS
    text = "Mega sale cashback offer today! Use code SAVE50."
    sms_res = {"probs": {"ham": 0.2, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"}
    url_res = []
    cues = [{"type": "reward", "start": 10, "end": 18, "text": "cashback"}]

    ev = fuse(text, sms_res, url_res, cues)
    assert ev.label == "unwanted"


def test_url_indicators_unparseable_url_does_not_raise():
    assert url_indicators("http://[bad-host") == ["unparseable_url"]


def test_fuse_malformed_url_does_not_raise_and_marks_untrusted():
    ev = fuse("Pay fee at http://[bad-host", None, [{"url": "http://[bad-host", "prob": 0.0, "indicators": []}], [])
    assert ev.urls[0]["trusted"] is False
    assert "unparseable_url" in ev.urls[0]["indicators"]
    assert ev.urls[0]["prob"] >= 0.5


def test_analyse_malformed_url_does_not_raise():
    result = analyse("Pay the fee at http://[bad-host now")
    assert result["evidence"]["label"] in ("ham", "unwanted", "scam")
    assert "unparseable_url" in result["evidence"]["indicators"]


def test_sigmoid_is_safe_for_extreme_logits():
    assert sigmoid(-1000.0) == 0.0
    assert sigmoid(1000.0) == 1.0
    assert sigmoid(0.0) == 0.5


def test_fuse_confident_ham_suppresses_urgency_payment_combo():
    text = "Your parcel will be delivered today. Pay on delivery."
    cues = sms_cues(text)
    confident_ham = {"probs": _raw_probs_for_scaled(0.9, 0.05, 0.05), "label": "ham"}

    ev = fuse(text, confident_ham, [], cues)
    assert ev.label == "ham"
    assert ev.level == "low"
    assert ev.risk < 0.72


def test_fuse_without_sms_model_keeps_urgency_payment_combo():
    text = "Your parcel will be delivered today. Pay on delivery."
    cues = sms_cues(text)

    ev = fuse(text, None, [], cues)
    assert ev.risk == 0.72
    assert ev.label == "scam"


def test_fuse_ham_confidence_boundary_controls_combo():
    text = "Your parcel will be delivered today. Pay on delivery."
    cues = sms_cues(text)
    at_threshold = {"probs": _raw_probs_for_scaled(0.8, 0.1, 0.1), "label": "ham"}
    below_threshold = {"probs": _raw_probs_for_scaled(0.79, 0.11, 0.1), "label": "ham"}

    assert fuse(text, at_threshold, [], cues).risk < 0.72
    assert fuse(text, below_threshold, [], cues).risk == 0.72


@pytest.mark.parametrize("score,expected_label,expected_level", [
    (0.399, "ham", "low"),
    (0.4, "unwanted", "medium"),
    (0.401, "unwanted", "medium"),
    (0.699, "unwanted", "medium"),
    (0.7, "scam", "high"),
    (0.701, "scam", "high"),
])
def test_fuse_label_and_level_boundaries(score, expected_label, expected_level):
    sms_result = _sms_result_for_score(score)
    ev = fuse("boundary check", sms_result, [], [])
    assert ev.label == expected_label
    assert ev.level == expected_level
    assert ev.threshold == 0.7


def test_fuse_untrusted_url_below_scam_with_credential_cue():
    text = "Verify your account"
    cues = sms_cues(text)
    url_results = [{"url": "http://example.com/verify", "prob": 0.5, "indicators": []}]

    ev = fuse(text, None, url_results, cues)
    assert ev.label == "unwanted"
    assert ev.level == "medium"
    assert ev.risk < 0.7


# --- 5. guard tests ---
def test_guard_certainty_replacement():
    ev = Evidence(
        label="scam",
        risk=0.9,
        level="high",
        threshold=0.7,
        indicators=["brand_lookalike"],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    raw_advice = "This is definitely a scam and 100 percent guaranteed fraud. It is certainly dangerous."
    guarded, flags = guard(raw_advice, ev)

    assert "definitely" not in guarded.lower()
    assert "100 percent" not in guarded.lower()
    assert "guaranteed" not in guarded.lower()
    assert "certainly" not in guarded.lower()
    assert "hedged_certainty" in flags


def test_guard_link_click_sentence_removal():
    ev = Evidence(
        label="scam",
        risk=0.85,
        level="high",
        threshold=0.7,
        indicators=[],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    raw_advice = (
        "This message looks like a scam.\n"
        "Click the link to verify your identity.\n"
        "Do not click the link under any circumstances.\n"
        "1. Report to 1930."
    )
    guarded, flags = guard(raw_advice, ev)

    # Positive click link instruction should be removed
    assert "Click the link to verify your identity." not in guarded
    # Negative link instruction ("Do not click") should be retained
    assert "Do not click the link under any circumstances." in guarded
    assert "dropped_click_sentence" in flags


def test_guard_contradiction_fallback():
    ev_scam = Evidence(
        label="scam",
        risk=0.9,
        level="high",
        threshold=0.7,
        indicators=[],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    # Contradiction: model says message is safe when label is scam
    raw_scam_contra = "This message is completely safe and legitimate. No risk found."
    guarded, flags = guard(raw_scam_contra, ev_scam)
    assert "contradiction_fallback" in flags
    assert guarded == template_advice(ev_scam)

    ev_ham = Evidence(
        label="ham",
        risk=0.1,
        level="low",
        threshold=0.7,
        indicators=[],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    # Contradiction: model says message is a scam when label is ham
    raw_ham_contra = "This message is a scam. It is fraudulent."
    guarded_h, flags_h = guard(raw_ham_contra, ev_ham)
    assert "contradiction_fallback" in flags_h
    assert guarded_h == template_advice(ev_ham)


def test_guard_empty_fallback():
    ev = Evidence(
        label="ham",
        risk=0.1,
        level="low",
        threshold=0.7,
        indicators=[],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    guarded, flags = guard("   \n  ", ev)
    assert "empty_fallback" in flags
    assert guarded == template_advice(ev)

def test_guard_threat_restatement():
    ev = Evidence(
        label="scam",
        risk=0.9,
        level="high",
        threshold=0.7,
        indicators=[],
        cue_spans=[],
        urls=[],
        detector_versions={},
    )
    # 1. the sentence above is dropped and the flag is set
    threat_sentence = "It's likely that the account will be blocked, and you should not click on the link."
    guarded1, flags1 = guard(threat_sentence, ev)
    assert "blocked" not in guarded1
    assert "dropped_threat_restatement" in flags1

    # Mixed with safe sentence: threat dropped, safe sentence kept
    mixed_threat = (
        "It's likely that the account will be blocked, and you should not click on the link.\n"
        "Contact your bank through official channels."
    )
    guarded_mixed, flags_mixed = guard(mixed_threat, ev)
    assert "blocked" not in guarded_mixed
    assert "Contact your bank through official channels." in guarded_mixed
    assert "dropped_threat_restatement" in flags_mixed

    # 2. The message claims your account will be blocked, which is a common scam tactic. is kept
    attributed = "The message claims your account will be blocked, which is a common scam tactic."
    guarded2, flags2 = guard(attributed, ev)
    assert "The message claims your account will be blocked, which is a common scam tactic." in guarded2
    assert "dropped_threat_restatement" not in flags2

    # 3. a sentence without threat words is kept
    safe = "Check your account status by logging into the official app."
    guarded3, flags3 = guard(safe, ev)
    assert "Check your account status by logging into the official app." in guarded3
    assert "dropped_threat_restatement" not in flags3
    # kept, no flag: If you ignore it, you will be fine.
    safe_fine1 = "If you ignore it, you will be fine."
    guarded_sf1, flags_sf1 = guard(safe_fine1, ev)
    assert safe_fine1 in guarded_sf1
    assert "dropped_threat_restatement" not in flags_sf1

    # kept, no flag: It is fine to ignore this message.
    safe_fine2 = "It is fine to ignore this message."
    guarded_sf2, flags_sf2 = guard(safe_fine2, ev)
    assert safe_fine2 in guarded_sf2
    assert "dropped_threat_restatement" not in flags_sf2

    # dropped, flag: You must pay a fine of Rs 5000 today.
    penalty_fine = "You must pay a fine of Rs 5000 today."
    guarded_pf, flags_pf = guard(penalty_fine, ev)
    assert "fine" not in guarded_pf
    assert "dropped_threat_restatement" in flags_pf

    # dropped, flag: Your electricity will be cut tonight.
    electricity_cut = "Your electricity will be cut tonight."
    guarded_ec, flags_ec = guard(electricity_cut, ev)
    assert "cut" not in guarded_ec
    assert "dropped_threat_restatement" in flags_ec

    # dropped, flag: A \u20b9 500 fine applies.
    rupee_fine = "A \u20b9 500 fine applies."
    guarded_rf, flags_rf = guard(rupee_fine, ev)
    assert "fine" not in guarded_rf
    assert "dropped_threat_restatement" in flags_rf



# --- 6. template_advice non-empty for each label ---
def test_template_advice_non_empty():
    for lbl in ["scam", "unwanted", "ham"]:
        ev = Evidence(
            label=lbl,
            risk=0.8 if lbl == "scam" else (0.5 if lbl == "unwanted" else 0.1),
            level="high" if lbl == "scam" else ("medium" if lbl == "unwanted" else "low"),
            threshold=0.7,
            indicators=[],
            cue_spans=[],
            urls=[],
            detector_versions={},
        )
        adv = template_advice(ev)
        assert isinstance(adv, str)
        assert len(adv.strip()) > 20
        assert "1." in adv and "2." in adv and "3." in adv


# --- 7. parse of a sample llama_main stdout with PyTorchObserver line ---
def test_parse_llama_output_with_pytorch_observer():
    sample_stdout = """
<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are a digital safety assistant...<|eot_id|><|start_header_id|>user<|end_header_id|>

Message: "Dear customer your account is suspended"<|eot_id|><|start_header_id|>assistant<|end_header_id|>

This message looks like a scam. It asks for urgent verification through an untrusted channel.
1. Do not click or open any links.
2. Check your account using the official bank mobile app.
3. Report the scam to 1930.<|eot_id|>
PyTorchObserver {"prefill_tok_per_s": 32.5, "decode_tok_per_s": 14.8, "ttft_ms": 115.2}
"""
    text, stats = parse_llama_output(sample_stdout)
    assert "This message looks like a scam." in text
    assert "1. Do not click or open any links." in text
    assert "<|start_header_id|>" not in text
    assert "<|eot_id|>" not in text
    assert "PyTorchObserver" not in text

    assert stats.get("prefill_tok_per_s") == 32.5
    assert stats.get("decode_tok_per_s") == 14.8
    assert stats.get("ttft_ms") == 115.2


# --- 8. CLI --no-llm with fake detectors monkeypatched ---
def test_cli_no_llm_with_monkeypatched_detectors(monkeypatch, capsys):
    fake_url_det = MagicMock()
    fake_url_det.score.return_value = {
        "url": "http://sbi-fake.xyz",
        "norm_url": "sbi-fake.xyz",
        "prob": 0.96,
        "label": "phishing",
        "indicators": ["brand_lookalike", "risky_tld"],
    }

    fake_sms_det = MagicMock()
    fake_sms_det.predict.return_value = {
        "probs": {"ham": 0.05, "unwanted": 0.05, "scam": 0.90},
        "label": "scam",
    }

    # Monkeypatch load_detectors to return fake detectors and no advisor
    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda args: (fake_url_det, fake_sms_det, None),
    )

    msg = "SBI alert: account blocked today. Verify now http://sbi-fake.xyz"
    exit_code = main(["scan", msg, "--no-llm"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Risk Level: HIGH" in captured.out
    assert "Label: scam" in captured.out
    assert "[[SBI]]" in captured.out or "[[blocked]]" in captured.out
    assert "http://sbi-fake.xyz" in captured.out
    assert "Advice:" in captured.out


def test_cli_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda args: (None, None, None),
    )

    msg = "Payment of 500 upi received. Check at http://example.com"
    exit_code = main(["scan", msg, "--no-llm", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["message"] == msg
    assert "evidence" in data
    assert "advice" in data
    assert data["advice_source"] == "template"
    assert "timings_ms" in data


def test_pipeline_analyse_defaults():
    # End to end analyse call with no detectors provided
    res = analyse("Hello friend, how are you?")
    assert "evidence" in res
    assert res["evidence"]["label"] == "ham"
    assert res["advice_source"] == "template"
    assert "total_ms" in res["timings_ms"]

def test_new_scam_rules_and_regressions():
    from sentinel.detectors import sms_cues
    from sentinel.fusion import fuse

    # A: Collect request + UPI PIN -> label scam, level high
    text_a = "You have received a UPI collect request of INR 10,000 from PhonePe Merchant. Approve now by entering your UPI PIN."
    cues_a = sms_cues(text_a)
    ev_a = fuse(text_a, sms_result=None, url_results=[], cues=cues_a)
    assert ev_a.label == "scam"
    assert ev_a.level == "high"

    # B: App install (.apk / download apk) -> label scam, level high
    text_b = "Instant Loan App Approved: Rs 50,000 credited to your account instantly without CIBIL check. Download APK from loan-instant.xyz."
    cues_b = sms_cues(text_b)
    ev_b = fuse(text_b, sms_result=None, url_results=[], cues=cues_b)
    assert ev_b.label == "scam"
    assert ev_b.level == "high"

    # C: TRAI / Aadhaar blocked in 2 hours -> label scam, level high
    text_c = "TRAI Notification: All mobile numbers registered on your Aadhaar will be blocked in 2 hours due to illegal spam calls. Press 1 to speak to officer."
    cues_c = sms_cues(text_c)
    ev_c = fuse(text_c, sms_result=None, url_results=[], cues=cues_c)
    assert ev_c.label == "scam"
    assert ev_c.level == "high"

    # sms_cues on text C contains a cue of type threat with text blocked and a cue of type urgency with text in 2 hours
    cue_tuples = [(c["type"], c["text"].lower()) for c in cues_c]
    assert ("threat", "blocked") in cue_tuples
    assert ("urgency", "in 2 hours") in cue_tuples

    # Regression 1: OTP must stay ham, valid for 5 mins must not be urgency
    text_otp = "Your OTP for HDFC NetBanking is 482910. Valid for 5 mins. Do not share it with anyone."
    cues_otp = sms_cues(text_otp)
    ev_otp = fuse(text_otp, sms_result=None, url_results=[], cues=cues_otp)
    assert ev_otp.label == "ham"
    assert not any(c["type"] == "urgency" for c in cues_otp)

    # Regression 2: Rs 500 received from Ravi via UPI must stay ham
    text_upi = "Rs 500 received from Ravi via UPI. Ref 4821. Check balance in the app."
    cues_upi = sms_cues(text_upi)
    ev_upi = fuse(text_upi, sms_result=None, url_results=[], cues=cues_upi)
    assert ev_upi.label == "ham"

def test_sms_detector_padding_follows_dynamic_flag():
    """Dynamic-seq pte gets the real length (no padding); static pte gets max_length 128."""
    from unittest.mock import MagicMock
    torch = pytest.importorskip("torch")
    from sentinel.detectors import SmsDetector

    for dynamic, expected in ((True, False), (False, "max_length")):
        det = object.__new__(SmsDetector)
        det.is_dynamic, det.id_map, det._torch = dynamic, None, torch
        det._method = MagicMock()
        det._method.execute.return_value = [torch.tensor([[0.1, 0.2, 3.0]])]
        n = 7 if dynamic else 128
        det.tokenizer = MagicMock(return_value={
            "input_ids": torch.ones((1, n), dtype=torch.int64),
            "attention_mask": torch.ones((1, n), dtype=torch.int64),
        })
        out = det.predict("hello")
        assert det.tokenizer.call_args.kwargs["padding"] == expected
        assert det._method.execute.call_args.args[0][0].shape == (1, n)
        assert out["label"] == "scam"


def test_system_prompt_matches_kotlin():
    """Android Advisor.kt and sentinel/advisor.py must send Llama the same instructions."""
    import re
    from pathlib import Path
    kt = Path(__file__).resolve().parents[1] / "android/app/src/main/java/org/ps3/sentinel/core/Advisor.kt"
    block = kt.read_text(encoding="utf-8").split("const val SYSTEM_PROMPT: String =")[1].split("\n\n")[0]
    kotlin_prompt = "".join(re.findall(r'"([^"]*)"', block))
    assert kotlin_prompt == SYSTEM_PROMPT


def test_guard_replaces_llama_refusal_with_template():
    ev = Evidence(label="scam", risk=1.0, level="high", threshold=0.7)
    refusal = "I cannot provide information that could be used for fraud. Is there anything else I can help you with?"
    out, flags = guard(refusal, ev)
    assert flags == ["refusal_fallback"]
    assert out == template_advice(ev)
    ok, flags_ok = guard("This message may be a scam. Do not share your OTP.", ev)
    assert "refusal_fallback" not in flags_ok


def test_guard_drops_call_the_scammer_back():
    """Real Llama output on the phone (bijli scam): it told the user to dial the scammer's number."""
    ev = Evidence(label="scam", risk=0.95, level="high", threshold=0.7)
    adv = ("This message may be a scam.\n"
           "To stay safe, do not give out your phone number, and instead, type the number directly into your phone's dialer app.\n"
           "Do not call the number in the message.")
    out, flags = guard(adv, ev)
    assert "dropped_callback_sentence" in flags
    assert "dialer" not in out
    assert "Do not call the number in the message." in out
    assert "This message may be a scam." in out
    assert "added_template_steps" in flags and "\n1. " in out


CLICK_CASES = [
    ("Don't worry, click the link to verify your account.", False),
    ("Visit the link in the message to update your KYC.", False),
    ("Do not click the link.", True),
    ("Never click the link, visit the official SBI website by typing it yourself.", True),
]


def test_click_guard_checks_each_clause():
    """Same cases as AdvisorTest.testClickGuardChecksEachClause in Kotlin."""
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    for sentence, kept in CLICK_CASES:
        out, flags = guard("This message may be a scam.\n" + sentence, ev)
        assert (sentence in out) == kept, sentence
        assert ("dropped_click_sentence" in flags) == (not kept), sentence


def test_safe_fuse_malformed_sms_probs_falls_back_to_rule_only():
    from sentinel.detectors import sms_cues
    from sentinel.pipeline import _safe_fuse

    text = "Your parcel will be delivered today. Pay on delivery."
    cues = sms_cues(text)
    bad_sms = {"probs": {"ham": 0.1, "unwanted": 0.1, "scam": "invalid"}, "label": "scam"}
    ev = _safe_fuse(text, bad_sms, [], cues)
    assert ev.label == "scam"
    assert ev.level == "high"
    assert ev.risk == 0.72
    assert "analysis_error" in ev.indicators


def test_safe_fuse_always_raises_returns_unwanted_medium_with_analysis_error():
    from sentinel.pipeline import _safe_fuse

    with patch("sentinel.pipeline.fuse", side_effect=RuntimeError("boom")):
        ev = _safe_fuse("anything", {"probs": {"ham": 0.1, "unwanted": 0.1, "scam": 0.9}}, [], [])
        assert ev.label == "unwanted"
        assert ev.level == "medium"
        assert ev.risk == 0.4
        assert "analysis_error" in ev.indicators


def test_analyse_sms_model_error_carries_indicators_and_degraded_cli(monkeypatch, capsys):
    from sentinel.pipeline import analyse

    class _BoomSms:
        def predict(self, text):
            raise RuntimeError("boom")

    result = analyse("Hello there", sms_det=_BoomSms())
    assert "sms_model_error" in result["evidence"].indicators
    assert "analysis_error" in result["evidence"].indicators

    from sentinel.cli import format_human_output, main

    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, _BoomSms(), None))
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "sms_model_error" in data["evidence"]["indicators"]
    assert "sms" in data["degraded"]

    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, _BoomSms(), None))
    exit_code = main(["scan", "Hello there", "--no-llm"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Mode: rules only (SMS model unavailable)" in captured.out


def test_url_model_error_falls_back_like_kotlin():
    from sentinel.pipeline import _score_url_with_detector, analyse

    class _BoomUrl:
        def score(self, url):
            raise RuntimeError("boom")

    brand = _score_url_with_detector("http://sbi-fake.xyz/login", _BoomUrl())
    assert brand["prob"] == 0.85
    assert brand["label"] == "phishing"
    assert "brand_lookalike" in brand["indicators"]
    assert "url_model_error" in brand["indicators"]

    indicator = _score_url_with_detector("https://bit.ly/abc", _BoomUrl())
    assert indicator["prob"] == 0.4
    assert "url_model_error" in indicator["indicators"]

    clean = _score_url_with_detector("http://example.com/verify", _BoomUrl())
    assert clean["prob"] == 0.05
    assert "url_model_error" in clean["indicators"]

    result = analyse("Verify now http://sbi-fake.xyz/login", url_det=_BoomUrl())
    assert "url_model_error" in result["evidence"].indicators
    assert "url_model_error" in result["evidence"]["urls"][0]["indicators"]


def test_safe_fuse_malformed_url_prob_falls_back_to_cue_only_threat():
    from sentinel.detectors import sms_cues
    from sentinel.pipeline import _safe_fuse

    text = "Your parcel will be delivered today. Pay on delivery."
    cues = sms_cues(text)
    bad_urls = [{"url": "http://example.com/verify", "prob": "invalid", "indicators": []}]
    ev = _safe_fuse(text, None, bad_urls, cues)
    assert ev.label == "scam"
    assert ev.level == "high"
    assert ev.risk == 0.72
    assert "analysis_error" in ev.indicators
