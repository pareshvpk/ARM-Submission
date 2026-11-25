from sentinel.routine_filter import is_registered_sender, should_skip, skip_kind

OTP_TEXT = "123456 is your OTP for login. Valid for 10 minutes."


def test_otp_is_skipped():
    assert skip_kind(OTP_TEXT) == "otp"


def test_transaction_is_skipped():
    assert skip_kind("Rs.500.00 debited from A/c XX1234 on 12-11-26. Avl bal Rs 2,000.") == "transaction"


def test_phone_number_in_text_keeps_message():
    assert skip_kind("Your A/c is debited Rs 5000. Not you? Call 9876543210") is None


def test_request_words_keep_message():
    assert skip_kind("Share OTP 123456 with our agent to get refund") is None


def test_url_keeps_message():
    assert skip_kind("Your OTP is 4455. Verify at http://bit.ly/x") is None


def test_otp_autofill_ending_is_not_a_link():
    assert skip_kind("123456 is your OTP for login. Valid for 10 minutes.\n\n@example.com #123456") == "otp"
    assert skip_kind("Your OTP is 4455. Login at example.com/x now @example.com #4455") is None


def test_registered_header_with_otp_is_skipped():
    assert should_skip("AD-HDFCBK-S", OTP_TEXT)


def test_phone_sender_with_otp_is_not_skipped():
    assert not should_skip("+919876543210", OTP_TEXT)


def test_empty_sender_is_not_skipped():
    assert not should_skip("", OTP_TEXT)


def test_registered_sender_detection():
    assert is_registered_sender("AD-HDFCBK-S")
    assert not is_registered_sender("+91 98765-43210")
    assert not is_registered_sender("Unknown")


def test_dlt_header_true_examples():
    for sender in ("AD-HDFCBK", "VM-HDFCBK-S", "JM-JioPay", "AX-123456", "AD-123456-P", " ad-hdfcbk-s "):
        assert is_registered_sender(sender)


def test_dlt_header_false_examples():
    for sender in ("HDFCBK", "Google", "+919876543210", "9876543210", "Unknown", "", "HDFC-BANK-LTD", "A-HDFCBK"):
        assert not is_registered_sender(sender)


def test_toll_free_number_keeps_message():
    assert not should_skip(
        "AD-HDFCBK-S",
        "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.",
    )


def test_spaced_mobile_keeps_message():
    assert not should_skip(
        "AD-HDFCBK-S",
        "Rs 5,000 debited from A/c XX1234. Not you? Call 98765 43210",
    )


def test_plain_debit_is_skipped():
    assert should_skip(
        "AD-HDFCBK-S",
        "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000",
    )


def test_non_dlt_sender_is_not_skipped():
    assert not should_skip(
        "HDFCBK",
        "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000",
    )


def test_otp_from_dlt_header_is_skipped():
    assert should_skip(
        "AD-HDFCBK",
        "482913 is your OTP for login. Valid 10 min.",
    )


def test_upi_credit_with_reference_is_skipped():
    assert should_skip(
        "AD-HDFCBK-S",
        "Rs.500.00 credited to HDFC Bank A/c XX1234 on 12-11-26 from VPA user@okaxis (UPI 512345678901)",
    )


CREDENTIAL_REQUEST_TEXTS = [
    "Rs 4,999 debited from A/c XX9012. Reply with your UPI PIN to reverse it.",
    "A/c XX9012 debited Rs 4,999. Reply with OTP 4821 to reverse the debit.",
    "Rs 4,999 debited from A/c XX9012. Enter the 6 digit code we sent to cancel the debit.",
    "Rs 4,999 debited from A/c XX9012. Provide your card CVV to reverse.",
]


def test_credential_requests_from_dlt_header_are_not_skipped():
    for text in CREDENTIAL_REQUEST_TEXTS:
        assert not should_skip("AD-HDFCBK-S", text), text


def test_genuine_otp_from_dlt_header_is_still_skipped():
    assert should_skip(
        "AD-HDFCBK",
        "482913 is your One Time Password (OTP) for login at Example. This OTP will only be valid for 10 minutes",
    )


def test_genuine_credit_alert_from_dlt_header_is_still_skipped():
    assert should_skip(
        "AD-HDFCBK",
        "Rs.500.00 credited to HDFC Bank A/c XX1234 on 12-11-26 from VPA user@okaxis (UPI 512345678901)",
    )


def test_mobile_with_country_code_keeps_message():
    assert not should_skip(
        "AD-HDFCBK-S",
        "Rs 5,000 debited from A/c XX1234. Call +91 98765 43210",
    )


def test_hyphenated_toll_free_keeps_message():
    assert not should_skip(
        "AD-HDFCBK-S",
        "Rs 5,000 debited from A/c XX1234. Call 1860-500-1234",
    )


REQUEST_WORD_TEXTS = [
    "Rs 4,999 debited from A/c XX9012. Message OTP 4821 to stop debit.",
    "Rs 4,999 debited from A/c XX9012. Text OTP 4821 to block.",
    "Rs 4,999 debited from A/c XX9012. Quote the 6 digit code 482193 to stop the debit.",
    "Rs 4999 debit hua A/c XX9012 se. OTP 4821 bhejo.",
    "Rs 4,999 debited from A/c XX9012. Reach our helpline 011 2345 6789 to dispute.",
    "A/c XX9012 debited Rs 499. Pay Rs 99 via UPI to reactivate.",
]


def test_request_words_from_dlt_header_are_not_skipped():
    for text in REQUEST_WORD_TEXTS:
        assert not should_skip("AD-HDFCBK-S", text), text


SECRET_REQUEST_BANK_ALERT_SCAMS = [
    "Rs 4,999 debited from A/c XX9012. Read out OTP 4821 to the officer.",
    "Rs 4,999 debited from A/c XX9012. Spell out the 6 digit code 482193.",
    "Rs 4,999 debited from A/c XX9012. Repeat the code 482193 to cancel the debit.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 bata do.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 bataye.",
    "Rs 4,999 debited from A/c XX9012. OTP 4821 daal do.",
    "Rs 5,000 debited from A/c XX1234. OTP 4821 required to stop the debit.",
    "Rs 5,000 debited from your account. Code 4821 required to stop the debit.",
    "Rs 5,000 debited from card 1234. Code 4821 required to stop the debit.",
    "Rs 500 paid from A/c XX1234. Code 1234 required to stop the payment.",
]


def test_secret_request_bank_alerts_from_dlt_header_are_not_skipped():
    for text in SECRET_REQUEST_BANK_ALERT_SCAMS:
        assert not should_skip("AD-HDFCBK-S", text), text


def test_ascii_digits_ignore_devanagari_money():
    assert skip_kind("Rs ५,००० debited from A/c XX1234") is None


def test_ascii_digits_ignore_devanagari_code():
    assert skip_kind("आपका OTP ४८२१ है") is None


def test_ascii_digits_ignore_devanagari_sender():
    assert sender_cue("९८७६५४३२१०", ALERT_TEXT) is None


from sentinel.pipeline import analyse
from sentinel.routine_filter import sender_cue

ALERT_TEXT = "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now."


def test_sender_cue_fires_for_personal_number_alert():
    assert sender_cue("+919876543210", ALERT_TEXT) == {
        "type": "sender_mismatch",
        "start": 39,
        "end": 52,
        "text": "1800 123 4567",
    }


def test_sender_cue_fires_for_spaced_mobile_sender():
    assert sender_cue("98765 43210", ALERT_TEXT) is not None


def test_sender_cue_ignores_dlt_header():
    assert sender_cue("AD-HDFCBK-S", ALERT_TEXT) is None


def test_sender_cue_requires_a_callback_number():
    assert sender_cue("+919876543210", "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000") is None


def test_sender_cue_ignores_non_transaction_text():
    assert sender_cue("+919876543210", "Hi, call me on 98765 43210 when free") is None


def test_sender_cue_ignores_short_code():
    assert sender_cue("56161", ALERT_TEXT) is None


def test_sender_cue_ignores_empty_sender():
    assert sender_cue("", ALERT_TEXT) is None


def test_sender_cue_needs_transaction_words():
    assert sender_cue("+919876543210", "Call 1800 123 4567 about your account now") is None


def test_sender_cue_ignores_paid_via_upi_message():
    assert sender_cue("+919876543210", "Rs 500 paid via UPI, call me on 98765 43210") is None


def test_sender_cue_ignores_person_to_person_account_payment():
    assert sender_cue("+919876543210", "I paid Rs 500 to your account, call me on 98765 43210") is None


def test_sender_cue_fires_for_card_debit_from_personal_number():
    assert sender_cue("+919876543210", "Rs 5,000 debited from card XX1234. Not you? Call 98111 22333") is not None


def test_analyse_appends_sender_cue_and_floors_risk():
    result = analyse(ALERT_TEXT, sender="+919876543210")
    assert any(cue["type"] == "sender_mismatch" for cue in result["evidence"].cue_spans)
    assert result["evidence"].level == "medium"
    assert "bank-style alert sent from a personal mobile number" in result["evidence"].indicators


def test_analyse_without_sender_has_no_sender_cue():
    result = analyse(ALERT_TEXT)
    assert not any(cue["type"] == "sender_mismatch" for cue in result["evidence"].cue_spans)


def test_sender_cue_fires_for_transferred_alert_with_different_callback():
    assert sender_cue(
        "+919876543210",
        "Rs 5,000 transferred from A/c XX1234 to VPA x@okaxis. Call 98111 22333 if not you.",
    ) is not None


def test_sender_cue_ignores_own_number_on_debit_alert():
    assert sender_cue(
        "+919876543210",
        "Rs 5,000 debited from A/c XX1234. Call 98765 43210 if not you.",
    ) is None


def test_sender_cue_ignores_first_person_credit():
    assert sender_cue("9876543210", "Rs 2,000 credited to my a/c, call me on 98765 43210") is None


def test_sender_cue_ignores_own_number_on_credit_alert():
    assert sender_cue(
        "+919876543210",
        "Rs 500 credited to a/c XX1234. Call 98765 43210 for queries.",
    ) is None



def test_registered_sender_regression_cases():
    messages_not_skipped = [
        ("AD-HDFCBK-S", "Your OTP is 482913. Share this OTP with our agent to stop account block."),
        ("AD-SBIINB-S", "Congratulations! You won Rs 25000 prize. Claim: http://sbi-prize.xyz"),
        ("AD-HDFCBK-S", "Refund of Rs 4999 pending. Enter UPI PIN to receive refund: http://bit.ly/rf"),
        ("AD-JIOINF-S", "Activate your eSIM now or service stops today. Click http://jio-esim.top"),
        ("AD-SBIINB-S", "Your account will be blocked today. Update KYC: http://sbi-kyc.xyz"),
        ("AD-HDFCBK-S", "Rs 500 debited from a/c XX1234. Not you? call 9123456789 now"),
    ]
    for sender, text in messages_not_skipped:
        assert not should_skip(sender, text), f"Expected should_skip=False for {sender}: {text}"

    assert should_skip("AD-HDFCBK-S", "Rs 500 debited from a/c XX1234 on 23-11. Avl bal Rs 10000.")
