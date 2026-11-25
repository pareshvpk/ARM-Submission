"""Build the Python-versus-Kotlin advisor parity fixture.

The fixture records, for each raw Llama output, the inputs both implementations
receive and the Python guard result the Kotlin side must reproduce. Run this
file directly after changing the advisor guard:

    .venv\\Scripts\\python.exe tests\\make_advisor_cases.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sentinel.advisor import guard, template_advice
from sentinel.fusion import Evidence

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "advisor_cases.json"

SCHEMA_VERSION = 1

# 0.90/0.50/0.10 match the fusion risk bands for scam/unwanted/ham; the guard
# only reads the label, but keeping risk plausible keeps the fixture honest.
RISK_BY_LABEL = {"scam": 0.90, "unwanted": 0.50, "ham": 0.10}

# (case name, evidence label, evidence level, raw Llama output). Coverage:
# clean advice per label, refusals, contradictions (including adverb forms),
# click/callback instructions, threat restatements, Hinglish, empty output,
# very long output, and Llama special tokens.
CASE_INPUTS: list[tuple[str, str, str, str]] = [
    ("plain_safe_scam", "scam", "high",
     "This message may be a scam and may try to steal your details.\n"
     "1. Do not click links.\n2. Verify on the official app.\n3. Report to 1930."),
    ("plain_safe_unwanted", "unwanted", "medium",
     "This looks like unwanted promotional spam and may contain offers.\n"
     "1. Do not share personal details.\n2. Verify offers officially.\n3. Block the sender."),
    ("plain_safe_ham", "ham", "low",
     "This message appears low risk and consistent with normal communication.\n"
     "1. Verify unexpected requests.\n2. Never share PIN or OTP.\n3. Use official apps only."),
    ("offdiag_ham_high_level", "ham", "high",
     "This message looks normal and may be low risk.\n"
     "1. Verify any request independently.\n2. Never share your OTP.\n3. Use the official app."),
    ("offdiag_scam_low_level", "scam", "low",
     "This message may be a scam. Do not share your OTP with anyone.\n"
     "1. Verify on the official app.\n2. Never share your PIN.\n3. Report to 1930."),
    ("empty_string", "ham", "low", ""),
    ("whitespace_only", "scam", "high", "   \n  \n"),
    ("refusal_cannot_provide", "scam", "high",
     "I cannot provide information that could be used for fraud. "
     "Is there anything else I can help you with?"),
    ("refusal_as_ai", "unwanted", "medium",
     "As an AI, I cannot answer that question. Please ask a human instead."),
    ("refusal_unable_to_help", "ham", "low", "I am unable to help with this request."),
    ("contradiction_scam_says_safe", "scam", "high",
     "This message is safe and legitimate. No risk found."),
    ("contradiction_scam_says_not_scam", "scam", "high",
     "This is not a scam. It is completely safe."),
    ("contradiction_ham_says_scam", "ham", "low",
     "This message is a scam. It is fraudulent."),
    ("contradiction_ham_says_high_risk", "ham", "low",
     "This message is at high risk of fraud."),
    ("contradiction_unwanted_says_scam", "unwanted", "medium",
     "This message looks like a scam. It is fraudulent."),
    ("unwanted_high_risk_kept", "unwanted", "medium",
     "This message may be high risk. Do not share your OTP.\n"
     "1. Verify offers officially.\n2. Never share your PIN.\n3. Block the sender."),
    ("certainty_then_contradiction", "scam", "high", "This is definitely safe."),
    ("certainty_hedged_scam", "scam", "high",
     "This is definitely a scam and 100% guaranteed fraud. "
     "It is certainly dangerous and surely risky.\n"
     "1. Do not share OTP.\n2. Verify officially.\n3. Report to 1930."),
    ("certainty_hundred_percent_word", "scam", "high",
     "I am 100 percent sure this is bad. Do not trust it.\n"
     "1. Verify on the official app.\n2. Never share your PIN.\n3. Report to 1930."),
    ("click_link_dropped", "scam", "high",
     "This message may be a scam.\nClick the link to verify your identity.\n"
     "Do not click the link under any circumstances.\n1. Report to 1930."),
    ("open_website_dropped", "scam", "high",
     "This message may be a scam. Open the website to verify your details now.\n"
     "1. Report to 1930."),
    ("visit_portal_dropped", "scam", "high",
     "This message may be a scam. Please visit the portal and enter your PAN now.\n"
     "1. Report to 1930."),
    ("tap_url_dropped", "scam", "high",
     "This message may be a scam. Tap the URL you received to continue.\n1. Report to 1930."),
    ("follow_link_dropped", "scam", "high",
     "This message may be a scam. Follow the link below to update your KYC.\n"
     "1. Report to 1930."),
    ("do_not_click_kept", "scam", "high",
     "This message may be a scam. Do not click the link in this message.\n1. Report to 1930."),
    ("never_click_official_kept", "scam", "high",
     "This message may be a scam. Never click the link, "
     "visit the official SBI website by typing it yourself.\n1. Report to 1930."),
    ("clause_negation_does_not_shield", "scam", "high",
     "This message may be a scam. Don't worry, click the link to verify your account.\n"
     "1. Report to 1930."),
    ("click_only_sentence_empties", "scam", "high",
     "Click the link to verify your account now."),
    ("callback_call_number_dropped", "scam", "high",
     "This message may be a scam. Please call the number in the message for help.\n"
     "1. Report to 1930."),
    ("callback_dialer_dropped", "scam", "high",
     "This message may be a scam.\n"
     "To stay safe, do not give out your phone number, and instead, "
     "type the number directly into your phone's dialer app.\nDo not call the number in the message."),
    ("do_not_call_kept", "scam", "high",
     "This message may be a scam. Do not call the number in the message.\n1. Report to 1930."),
    ("threat_blocked_dropped", "scam", "high",
     "Your account will be blocked tonight if you do not verify."),
    ("threat_attributed_kept", "scam", "high",
     "The message claims your account will be blocked, which is a common scam tactic."),
    ("threat_fine_dropped", "scam", "high", "You must pay a fine of Rs 5000 today."),
    ("threat_cut_dropped", "scam", "high", "Your electricity will be cut tonight."),
    ("threat_rupee_fine_dropped", "scam", "high", "A ₹ 500 fine applies."),
    ("threat_fine_benign_kept", "scam", "high", "If you ignore it, you will be fine."),
    ("threat_only_empties", "scam", "high", "Your account will be blocked."),
    ("mixed_sentences", "scam", "high",
     "This message may be a scam.\nClick the link to verify your identity.\n"
     "Do not click the link under any circumstances.\n"
     "The message claims your account will be blocked.\n1. Report to 1930."),
    ("no_steps_backfilled", "scam", "high",
     "This message may be a scam. Do not share any OTP or password with anyone."),
    ("uppercase_click_dropped", "scam", "high",
     "This message may be a scam. CLICK THE LINK NOW."),
    ("hinglish_safe_scam", "scam", "high",
     "Ye message scam jaisa lagta hai. OTP mat batao kisiko.\n"
     "1. Links mat kholo.\n2. Official app se check karo.\n3. 1930 par report karo."),
    ("hinglish_threat_unmatched", "scam", "high",
     "Aapka account block ho jayega. Turant officer ko call karein.\n"
     "1. Links mat kholo.\n2. Official app se check karo.\n3. 1930 par report karo."),
    ("devanagari_safe_ham", "ham", "low",
     "यह संदेश सामान्य लगता है। कृपया सतर्क रहें।\n"
     "1. कोई भी जानकारी साझा न करें।\n2. आधिकारिक ऐप से जांच करें।\n3. संदिग्ध लगने पर रिपोर्ट करें।"),
    ("special_tokens_preserved", "scam", "high",
     "This message may be a scam.<|eot_id|> Do not share your OTP.\n"
     "1. Verify officially.\n2. Report to 1930.\n3. Never share PIN."),
    ("special_tokens_with_markers", "ham", "low",
     "Hello <|start_header_id|>assistant<|end_header_id|> this looks normal. Do not share OTP.\n"
     "1. Verify independently.\n2. Never share OTP.\n3. Use official apps."),
    ("long_output_no_steps", "scam", "high", "Do not share your password. " * 40),
    ("long_output_with_steps", "scam", "high",
     "This message may be a scam. " * 20 + "\n1. Do not click links.\n"
     "2. Verify officially.\n3. Report at 1930."),
    ("duplicate_drop_flags", "scam", "high",
     "This message may be a scam.\nClick the link now.\nOpen the website to continue.\n"
     "Call the number in the message.\nRing the number they gave you.\n1. Report to 1930."),
    ("duplicate_threat_deduped", "scam", "high",
     "Your account will be blocked.\nYour electricity will be cut.\n"
     "Contact your bank through official channels.\n1. Report to 1930."),
    ("secret_share_otp_dropped", "scam", "high",
     "This message may be a scam.\nShare your OTP with the bank to verify.\n1. Report to 1930."),
    ("secret_give_pin_dropped", "scam", "high",
     "This message may be a scam.\nGive your PIN to the caller to confirm identity.\n1. Report to 1930."),
    ("secret_reply_upi_pin_dropped", "scam", "high",
     "This message may be a scam.\nReply with your UPI PIN to receive the refund.\n1. Report to 1930."),
    ("secret_negated_kept", "scam", "high",
     "This message may be a scam. Never share your OTP with anyone. "
     "Do not give your PIN to anyone.\n1. Report to 1930."),
    ("secret_dropped_steps_backfilled", "scam", "high",
     "This message may be a scam. Share your OTP with the bank to verify."),
    ("official_click_link_dropped", "scam", "high",
     "This message may be a scam. Click the official link to verify your account.\n"
     "1. Report to 1930."),
    ("official_tap_link_dropped", "scam", "high",
     "This message may be a scam. Tap the official link below.\n1. Report to 1930."),
    ("official_visit_website_kept", "scam", "high",
     "This message may be a scam. Visit the official website to check.\n1. Report to 1930."),
    ("official_open_app_kept", "scam", "high",
     "This message may be a scam. Open the official SBI app to check your account.\n"
     "1. Report to 1930."),
    ("official_type_website_kept", "scam", "high",
     "This message may be a scam. Type the official website address yourself.\n"
     "1. Report to 1930."),
    ("access_link_dropped", "scam", "high",
     "This message may be a scam. Access the link to verify your account.\n"
     "1. Report to 1930."),
    ("go_to_website_dropped", "scam", "high",
     "This message may be a scam. Go to the website to confirm your details.\n"
     "1. Report to 1930."),
    ("use_link_dropped", "scam", "high",
     "This message may be a scam. Use the link below to update KYC.\n"
     "1. Report to 1930."),
    ("navigate_portal_dropped", "scam", "high",
     "This message may be a scam. Navigate to the portal to verify.\n"
     "1. Report to 1930."),
    ("go_to_official_app_kept", "scam", "high",
     "This message may be a scam. Go to the official SBI app to check.\n"
     "1. Report to 1930."),
    ("open_official_app_kept", "scam", "high",
     "This message may be a scam. Open the official SBI app to check your account.\n"
     "1. Report to 1930."),
    ("type_official_website_kept", "scam", "high",
     "This message may be a scam. Type the official website address yourself.\n"
     "1. Report to 1930."),
    ("visit_official_website_kept", "scam", "high",
     "This message may be a scam. Visit the official website to check.\n"
     "1. Report to 1930."),
    ("do_not_go_to_website_kept", "scam", "high",
     "This message may be a scam. Do not go to the website in the message.\n"
     "1. Report to 1930."),
    ("secret_and_pin_dropped", "scam", "high",
     "This message may be a scam. Do not share your OTP and send your UPI PIN to the caller.\n"
     "1. Report to 1930."),
    ("do_not_click_and_share_kept", "scam", "high",
     "This message may be a scam. Do not click the link and do not share your OTP.\n"
     "1. Report to 1930."),
    ("never_share_and_report_kept", "scam", "high",
     "This message may be a scam. Never share your OTP and report the message to 1930.\n"
     "1. Report to 1930."),
    ("five_sentences_five_steps_truncated", "scam", "high",
     "This message may be a scam. It may try to steal your details. Do not trust the sender. "
     "Check your account carefully. Stay alert for suspicious requests.\n"
     "1. Do not share your OTP.\n2. Verify officially.\n3. Report to 1930.\n4. Block the sender.\n5. Delete the message."),
    ("contradiction_scam_totally_safe", "scam", "high", "This is totally safe."),
    ("contradiction_scam_genuine_safe_to_trust", "scam", "high",
     "This message is genuine and safe to trust."),
    ("contradiction_scam_looks_legit", "scam", "high", "It looks legit."),
    ("contradiction_scam_no_scam_here", "scam", "high", "No scam here."),
    ("contradiction_scam_not_a_scam_at_all", "scam", "high", "This is not a scam at all."),
    ("contradiction_scam_harmless", "scam", "high", "It is harmless."),
    ("contradiction_scam_nothing_to_worry", "scam", "high", "Nothing to worry about."),
    ("contradiction_scam_absolutely_safe", "scam", "high", "This is absolutely safe."),
    ("contradiction_scam_trustworthy", "scam", "high", "It seems trustworthy."),
    ("contradiction_scam_authentic", "scam", "high", "This message is authentic."),
    ("contradiction_scam_safe_to_reply", "scam", "high", "It is safe to reply."),
    ("contradiction_scam_100_percent_safe", "scam", "high", "This is 100 percent safe."),
    ("contradiction_scam_not_harmful", "scam", "high", "It is not harmful."),
    ("contradiction_scam_not_fraud", "scam", "high", "It is not fraud."),
    ("contradiction_scam_not_safe_to_click_kept", "scam", "high",
     "This message may be a scam. It is not safe to click the link.\n1. Report to 1930."),
    ("contradiction_scam_disguise_genuine_kept", "scam", "high",
     "This message may be a scam. Scammers make messages look genuine.\n1. Report to 1930."),
    ("contradiction_scam_disguise_legit_kept", "scam", "high",
     "This message may be a scam. This may look legit but it is a scam.\n1. Report to 1930."),
    ("secret_read_out_otp_dropped", "scam", "high",
     "This message may be a scam. Read out your OTP to the agent.\n1. Report to 1930."),
    ("secret_dictate_pin_dropped", "scam", "high",
     "This message may be a scam. Dictate your PIN to confirm identity.\n1. Report to 1930."),
    ("secret_reveal_cvv_dropped", "scam", "high",
     "This message may be a scam. Reveal your CVV number now.\n1. Report to 1930."),
    ("secret_confirm_otp_dropped", "scam", "high",
     "This message may be a scam. Confirm your OTP with the caller.\n1. Report to 1930."),
    ("secret_read_otp_dropped", "scam", "high",
     "This message may be a scam. Read your OTP to the agent.\n1. Report to 1930."),
    ("secret_say_password_dropped", "scam", "high",
     "This message may be a scam. Say your password to the caller.\n1. Report to 1930."),
    ("secret_state_otp_dropped", "scam", "high",
     "This message may be a scam. State your OTP to the agent.\n1. Report to 1930."),
    ("secret_recite_pin_dropped", "scam", "high",
     "This message may be a scam. Recite your PIN to the caller.\n1. Report to 1930."),
    ("secret_speak_otp_dropped", "scam", "high",
     "This message may be a scam. Speak your OTP to the agent.\n1. Report to 1930."),
    ("secret_disclose_password_dropped", "scam", "high",
     "This message may be a scam. Disclose your password to support.\n1. Report to 1930."),
    ("secret_show_cvv_dropped", "scam", "high",
     "This message may be a scam. Show your CVV to the caller.\n1. Report to 1930."),
    ("secret_hand_over_pin_dropped", "scam", "high",
     "This message may be a scam. Hand over your PIN to the caller.\n1. Report to 1930."),
    ("secret_pass_on_otp_dropped", "scam", "high",
     "This message may be a scam. Pass on your OTP to the agent.\n1. Report to 1930."),
    ("secret_verify_by_sharing_dropped", "scam", "high",
     "This message may be a scam. Verify by sharing your OTP with the caller.\n1. Report to 1930."),
    ("secret_never_reveal_kept", "scam", "high",
     "This message may be a scam. Never reveal your PIN to anyone.\n1. Report to 1930."),
    ("secret_do_not_disclose_kept", "scam", "high",
     "This message may be a scam. Do not disclose your OTP.\n1. Report to 1930."),
    ("secret_banks_never_confirm_kept", "scam", "high",
     "This message may be a scam. Banks never ask you to confirm your PIN.\n1. Report to 1930."),
    ("callback_ring_given_helpline_dropped", "scam", "high",
     "This message may be a scam. Ring the given helpline now.\n1. Report to 1930."),
    ("callback_dial_helpline_dropped", "scam", "high",
     "This message may be a scam. Dial the helpline.\n1. Report to 1930."),
    ("callback_contact_agent_dropped", "scam", "high",
     "This message may be a scam. Contact the agent mentioned in the message.\n1. Report to 1930."),
    ("callback_customer_care_number_dropped", "scam", "high",
     "This message may be a scam. Call the customer care number in the SMS.\n1. Report to 1930."),
    ("callback_phone_support_desk_dropped", "scam", "high",
     "This message may be a scam. Phone the support desk.\n1. Report to 1930."),
    ("callback_whatsapp_agent_dropped", "scam", "high",
     "This message may be a scam. WhatsApp the agent now.\n1. Report to 1930."),
    ("callback_text_caller_dropped", "scam", "high",
     "This message may be a scam. Text the caller now.\n1. Report to 1930."),
    ("callback_reach_officer_dropped", "scam", "high",
     "This message may be a scam. Reach the officer now.\n1. Report to 1930."),
    ("callback_call_1930_kept", "scam", "high",
     "This message may be a scam. Call 1930 to report the fraud.\n1. Report to 1930."),
    ("callback_contact_bank_card_kept", "scam", "high",
     "This message may be a scam. Contact your bank using the number on your card or the official app.\n"
     "1. Report to 1930."),
    ("callback_do_not_call_number_kept", "scam", "high",
     "This message may be a scam. Do not call the number in the message.\n1. Report to 1930."),
    ("contradiction_scam_you_are_safe_to_proceed", "scam", "high", "You are safe to proceed."),
    ("contradiction_scam_totally_harmless_message", "scam", "high", "Totally harmless message."),
    ("contradiction_scam_completely_harmless", "scam", "high", "Completely harmless."),
    ("contradiction_scam_it_is_safe_to_proceed", "scam", "high", "It is safe to proceed."),
    ("contradiction_scam_safe_to_open", "scam", "high", "Safe to open."),
    ("contradiction_scam_safe_to_continue", "scam", "high", "Safe to continue."),
    ("contradiction_scam_you_are_safe_to_continue", "scam", "high", "You are safe to continue."),
    ("contradiction_scam_it_is_safe_to_open", "scam", "high", "It is safe to open."),
    ("contradiction_scam_absolutely_harmless", "scam", "high", "Absolutely harmless."),
    ("contradiction_scam_perfectly_safe", "scam", "high", "Perfectly safe."),
    ("contradiction_scam_not_safe_to_proceed_kept", "scam", "high",
     "This message may be a scam. It is not safe to proceed.\n1. Report to 1930."),
    ("contradiction_scam_scammers_say_harmless_kept", "scam", "high",
     "This message may be a scam. Scammers say it is harmless.\n1. Report to 1930."),
    ("callback_call_sender_back_dropped", "scam", "high",
     "This message may be a scam. Call the sender back.\n1. Report to 1930."),
    ("callback_contact_sender_dropped", "scam", "high",
     "This message may be a scam. Contact the sender.\n1. Report to 1930."),
    ("callback_phone_sender_now_dropped", "scam", "high",
     "This message may be a scam. Phone the sender now.\n1. Report to 1930."),
    ("callback_telephone_sender_dropped", "scam", "high",
     "This message may be a scam. Telephone the sender right now.\n1. Report to 1930."),
    ("callback_message_sender_dropped", "scam", "high",
     "This message may be a scam. Message the sender to confirm.\n1. Report to 1930."),
    ("callback_call_person_sent_dropped", "scam", "high",
     "This message may be a scam. Call the person who sent this.\n1. Report to 1930."),
    ("callback_telephone_person_sent_dropped", "scam", "high",
     "This message may be a scam. Telephone the person who sent this.\n1. Report to 1930."),
    ("callback_message_person_sent_dropped", "scam", "high",
     "This message may be a scam. Message the person who sent this.\n1. Report to 1930."),
    ("callback_call_number_messaged_dropped", "scam", "high",
     "This message may be a scam. Call the number that messaged you.\n1. Report to 1930."),
    ("callback_telephone_number_messaged_dropped", "scam", "high",
     "This message may be a scam. Telephone the number that messaged you.\n1. Report to 1930."),
    ("callback_message_number_messaged_dropped", "scam", "high",
     "This message may be a scam. Message the number that messaged you.\n1. Report to 1930."),
    ("callback_do_not_call_sender_back_kept", "scam", "high",
     "This message may be a scam. Do not call the sender back.\n1. Report to 1930."),
    ("callback_never_contact_sender_kept", "scam", "high",
     "This message may be a scam. Never contact the sender.\n1. Report to 1930."),
    ("contradiction_scam_you_can_trust", "scam", "high", "You can trust this message."),
    ("contradiction_scam_no_need_to_worry", "scam", "high", "No need to worry about this message."),
    ("contradiction_scam_i_see_nothing_suspicious", "scam", "high",
     "I see nothing suspicious about this message."),
    ("contradiction_scam_comes_from_genuine_source", "scam", "high",
     "This message comes from a genuine source."),
    ("contradiction_scam_verified_genuine_entity", "scam", "high",
     "The sender is a verified genuine entity."),
    ("contradiction_scam_feel_free_to_use", "scam", "high", "Feel free to use this message."),
    ("contradiction_scam_in_fact_genuine", "scam", "high", "This message is in fact genuine."),
    ("contradiction_scam_nothing_about_suspicious", "scam", "high",
     "Nothing about this message is suspicious."),
    ("contradiction_scam_this_is_a_safe_message", "scam", "high", "This is a safe message."),
    ("secret_send_verification_code_dropped", "scam", "high",
     "This message may be a scam. Send the caller your verification code.\n1. Report to 1930."),
    ("secret_share_code_dropped", "scam", "high",
     "This message may be a scam. Share your code with the agent.\n1. Report to 1930."),
    ("click_head_to_website_dropped", "scam", "high",
     "This message may be a scam. Head to the website to verify your account.\n1. Report to 1930."),
    ("click_go_through_link_dropped", "scam", "high",
     "This message may be a scam. Go through the link to update your details.\n1. Report to 1930."),
    ("contradiction_scam_scammers_want_you_to_trust_kept", "scam", "high",
     "This message may be a scam. Scammers want you to trust this message.\n1. Report to 1930."),
    ("contradiction_scam_do_not_trust_kept", "scam", "high",
     "This message may be a scam. Do not trust this message.\n1. Report to 1930."),
    ("secret_never_share_verification_code_kept", "scam", "high",
     "This message may be a scam. Never share any verification code.\n1. Report to 1930."),
    ("contradiction_scam_may_look_like_safe_but_scam_kept", "scam", "high",
     "This message may be a scam. It may look like a safe message but it is a scam.\n1. Report to 1930."),
    ("click_head_to_official_app_kept", "scam", "high",
     "This message may be a scam. Head to the official app yourself to check.\n1. Report to 1930."),
    ("click_round10_click_bare_url_dropped", "scam", "high",
     "This message may be a scam. Click http://evil.com now.\n1. Report to 1930."),
    ("click_round10_go_to_bare_url_dropped", "scam", "high",
     "This message may be a scam. Go to http://evil.com/verify\n1. Report to 1930."),
    ("click_round10_navigate_bare_url_dropped", "scam", "high",
     "This message may be a scam. Navigate to http://evil.com\n1. Report to 1930."),
    ("click_round10_tap_bare_url_dropped", "scam", "high",
     "This message may be a scam. Tap http://evil.com\n1. Report to 1930."),
    ("click_round10_open_www_dropped", "scam", "high",
     "This message may be a scam. Open www.evil.com to verify.\n1. Report to 1930."),
    ("contradiction_scam_round10_you_are_safe", "scam", "high", "You are safe."),
    ("contradiction_scam_round10_it_is_fine", "scam", "high", "It is fine."),
    ("contradiction_scam_round10_nothing_looks_suspicious", "scam", "high",
     "Nothing looks suspicious here."),
    ("click_round10_do_not_click_bare_url_kept", "scam", "high",
     "This message may be a scam. Do not click http://evil.com.\n1. Report to 1930."),
    ("click_round10_never_open_links_kept", "scam", "high",
     "This message may be a scam. Never open links in the message.\n1. Report to 1930."),
    ("contradiction_scam_round10_you_are_not_safe_kept", "scam", "high",
     "This message may be a scam. You are not safe if you share your OTP.\n1. Report to 1930."),
    ("contradiction_scam_round10_it_is_fine_to_delete_kept", "scam", "high",
     "This message may be a scam. It is fine to delete this message.\n1. Report to 1930."),
    ("click_round10_report_official_url_kept", "scam", "high",
     "This message may be a scam. Report it at https://sancharsaathi.gov.in\n1. Report to 1930."),
    ("callback_plain_call_digits_dropped", "scam", "high",
     "This message may be a scam. Call 1800123456 now to verify.\n1. Report to 1930."),
    ("callback_plain_call_this_number_dropped", "scam", "high",
     "This message may be a scam. Call this number.\n1. Report to 1930."),
    ("callback_plain_phone_them_back_dropped", "scam", "high",
     "This message may be a scam. Phone them back.\n1. Report to 1930."),
    ("callback_call_official_card_kept", "scam", "high",
     "This message may be a scam. Call the official number printed on your card.\n1. Report to 1930."),
    ("callback_call_bank_official_website_kept", "scam", "high",
     "This message may be a scam. Call your bank using the number on its official website.\n1. Report to 1930."),
    ("contradiction_scam_safely_reply", "scam", "high", "You can safely reply to this message."),
    ("contradiction_scam_completely_safe", "scam", "high", "This is completely safe."),
    ("contradiction_scam_feels_totally_safe", "scam", "high", "This feels totally safe."),
    ("contradiction_scam_there_is_nothing_to_worry_about", "scam", "high",
     "There is nothing to worry about."),
    ("click_do_not_misunderstand_colon_dropped", "scam", "high",
     "This message may be a scam. Do not misunderstand: click the link to claim your refund.\n1. Report to 1930."),
    ("click_do_not_misunderstand_semicolon_dropped", "scam", "high",
     "This message may be a scam. Do not misunderstand; click the link to claim your refund.\n1. Report to 1930."),
    ("click_do_not_misunderstand_dash_dropped", "scam", "high",
     "This message may be a scam. Do not misunderstand - click the link to claim your refund.\n1. Report to 1930."),
    ("click_do_not_misunderstand_open_colon_dropped", "scam", "high",
     "This message may be a scam. Do not misunderstand: open the link to claim your refund.\n1. Report to 1930."),
    ("callback_official_bad_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number 9876543210 immediately.\n1. Report to 1930."),
    ("callback_official_spaced_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number 98765 43210.\n1. Report to 1930."),
    ("callback_official_dashed_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number 98765-43210.\n1. Report to 1930."),
    ("callback_official_bank_number_dropped", "scam", "high",
     "This message may be a scam. Contact the official bank at 1800123456.\n1. Report to 1930."),
    ("callback_call_1930_kept_round2", "scam", "high",
     "This message may be a scam. Call 1930 to report the fraud.\n1. Report to 1930."),
    ("callback_printed_card_kept_round2", "scam", "high",
     "This message may be a scam. Call the number printed on your card.\n1. Report to 1930."),
    ("callback_bank_official_website_kept_round2", "scam", "high",
     "This message may be a scam. Call your bank using the number on its official website.\n1. Report to 1930."),
    ("click_official_url_dropped", "scam", "high",
     "This message may be a scam. Click the official link http://evil.com now.\n1. Report to 1930."),
    ("click_official_website_url_dropped", "scam", "high",
     "This message may be a scam. Visit the official website http://evil.com.\n1. Report to 1930."),
    ("click_official_app_kept_round2", "scam", "high",
     "This message may be a scam. Open the official SBI app to check your account.\n1. Report to 1930."),
    ("callback_official_number_in_message_dropped", "scam", "high",
     "This message may be a scam. Call the official number in this message.\n1. Report to 1930."),
    ("callback_official_helpline_given_above_dropped", "scam", "high",
     "This message may be a scam. Call the official helpline given above.\n1. Report to 1930."),
    ("click_official_link_in_sms_dropped", "scam", "high",
     "This message may be a scam. Use the official link in the SMS.\n1. Report to 1930."),
    ("click_official_website_in_message_dropped", "scam", "high",
     "This message may be a scam. Visit the official website in this message to verify.\n1. Report to 1930."),
    ("callback_official_customer_care_in_message_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number in this message.\n1. Report to 1930."),
    ("callback_official_dot_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number 98765.43210 immediately.\n1. Report to 1930."),
    ("callback_official_slash_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number 98765/43210 immediately.\n1. Report to 1930."),
    ("callback_official_bracket_number_dropped", "scam", "high",
     "This message may be a scam. Call the official customer-care number (98765) 43210 immediately.\n1. Report to 1930."),
    ("callback_number_printed_passbook_kept", "scam", "high",
     "This message may be a scam. Call the number printed on your passbook.\n1. Report to 1930."),
    ("click_visit_bank_official_website_typed_kept", "scam", "high",
     "This message may be a scam. Visit your bank through its official website that you type yourself.\n1. Report to 1930."),
    ("click_visit_bank_official_app_typed_kept", "scam", "high",
     "This message may be a scam. Visit your bank through its official app that you type yourself.\n1. Report to 1930."),
    ("report_cybercrime_kept", "scam", "high",
     "This message may be a scam. Report the fraud at cybercrime.gov.in.\n1. Report to 1930."),
    ("report_sancharsaathi_kept_round2", "scam", "high",
     "This message may be a scam. Report it at https://sancharsaathi.gov.in\n1. Report to 1930."),
    ("amount_rs_4999_kept", "scam", "high",
     "This message may be a scam. You have to pay Rs 4999.\n1. Report to 1930."),
    ("otp_mention_kept", "scam", "high",
     "This message may be a scam. Your OTP is 123456.\n1. Report to 1930."),
    ("callback_official_number_in_this_text_dropped", "scam", "high",
     "This message may be a scam. Call the official number in this text.\n1. Report to 1930."),
    ("callback_official_number_given_in_text_dropped", "scam", "high",
     "This message may be a scam. Call the official number given in this text.\n1. Report to 1930."),
    ("callback_official_number_in_msg_dropped", "scam", "high",
     "This message may be a scam. Call the official number in this msg.\n1. Report to 1930."),
    ("click_link_in_the_text_dropped", "scam", "high",
     "This message may be a scam. Use the link in the text.\n1. Report to 1930."),
    ("click_official_website_given_in_text_dropped", "scam", "high",
     "This message may be a scam. Visit the official website given in this text.\n1. Report to 1930."),
    ("click_link_in_text_message_dropped", "scam", "high",
     "This message may be a scam. Use the link in this text message.\n1. Report to 1930."),
    ("click_official_link_in_sms_text_dropped", "scam", "high",
     "This message may be a scam. Use the official link in the sms text.\n1. Report to 1930."),
    ("click_link_in_msg_dropped", "scam", "high",
     "This message may be a scam. Use the link in the msg.\n1. Report to 1930."),
    ("click_check_bare_url_dropped", "scam", "high",
     "This message may be a scam. Check http://evil.example now.\n1. Report to 1930."),
    ("click_see_bare_url_dropped", "scam", "high",
     "This message may be a scam. See http://evil.example.\n1. Report to 1930."),
    ("click_view_bare_url_dropped", "scam", "high",
     "This message may be a scam. View http://evil.example.\n1. Report to 1930."),
    ("click_copy_bare_url_dropped", "scam", "high",
     "This message may be a scam. Copy http://evil.example into your browser.\n1. Report to 1930."),
    ("click_visit_www_dropped", "scam", "high",
     "This message may be a scam. Visit www.evil.example.\n1. Report to 1930."),
    ("click_go_through_url_dropped", "scam", "high",
     "This message may be a scam. Go through http://evil.example to verify.\n1. Report to 1930."),
    ("click_check_bare_domain_dropped", "scam", "high",
     "This message may be a scam. Check evil.com now.\n1. Report to 1930."),
    ("click_report_sancharsaathi_kept_r3", "scam", "high",
     "This message may be a scam. Report it at https://sancharsaathi.gov.in\n1. Report to 1930."),
    ("click_report_cybercrime_bare_kept_r3", "scam", "high",
     "This message may be a scam. Report the fraud at cybercrime.gov.in.\n1. Report to 1930."),
    ("click_do_not_check_bare_url_kept_r3", "scam", "high",
     "This message may be a scam. Do not check http://evil.example.\n1. Report to 1930."),
    ("click_visit_official_typed_kept_r3", "scam", "high",
     "This message may be a scam. Visit your bank through its official website that you type yourself.\n1. Report to 1930."),
    ("bare_click_here_dropped", "scam", "high",
     "This message may be a scam. Click here to claim your refund.\n1. Report to 1930."),
    ("bare_tap_here_dropped", "scam", "high",
     "This message may be a scam. Tap here to verify now.\n1. Report to 1930."),
    ("bare_open_here_dropped", "scam", "high",
     "This message may be a scam. Open here to continue.\n1. Report to 1930."),
    ("bare_click_to_claim_dropped", "scam", "high",
     "This message may be a scam. Click to claim your refund.\n1. Report to 1930."),
    ("bare_click_negated_here_kept", "scam", "high",
     "This message may be a scam. Do not click here.\n1. Report to 1930."),
    ("bare_click_negated_any_links_kept", "scam", "high",
     "This message may be a scam. Do not click any links.\n1. Report to 1930."),
    ("bare_visit_official_kept", "scam", "high",
     "This message may be a scam. Visit the official website to check.\n1. Report to 1930."),
    ("bare_open_official_sbi_app_kept", "scam", "high",
     "This message may be a scam. Open the official SBI app to check your account.\n1. Report to 1930."),
    ("bare_use_app_kept", "scam", "high",
     "This message may be a scam. Use the app to check your account.\n1. Report to 1930."),
    ("bare_open_official_two_words_kept", "scam", "high",
     "This message may be a scam. Open the official SBI mobile app to check your account.\n1. Report to 1930."),
]


def build_cases() -> dict[str, object]:
    """Return the complete fixture as a JSON-serialisable dictionary."""
    cases: list[dict[str, object]] = []
    for name, label, level, raw_output in CASE_INPUTS:
        evidence = Evidence(label=label, risk=RISK_BY_LABEL[label], level=level, threshold=0.7)
        guarded_text, flags = guard(raw_output, evidence)
        cases.append({
            "name": name,
            "evidence": {"label": label, "level": level, "risk": evidence.risk},
            "raw_output": raw_output,
            "expected": {
                "guarded_text": guarded_text,
                "flags": flags,
                "template_text": template_advice(evidence),
            },
        })

    templates = {}
    for label in ("scam", "unwanted", "ham"):
        for level in ("high", "medium", "low"):
            evidence = Evidence(label=label, risk=RISK_BY_LABEL[label], level=level, threshold=0.7)
            templates[f"{label}|{level}"] = template_advice(evidence)

    return {
        "schema_version": SCHEMA_VERSION,
        "description": "Python reference guard results that the Kotlin implementation must reproduce.",
        "cases": cases,
        "templates": templates,
    }


def write_fixture() -> Path:
    """Write the fixture to disk and return its path."""
    fixture = build_cases()
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return FIXTURE_PATH


if __name__ == "__main__":
    path = write_fixture()
    print(f"wrote {len(build_cases()['cases'])} advisor cases to {path}")
