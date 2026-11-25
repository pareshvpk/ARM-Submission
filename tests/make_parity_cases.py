"""Build the Python-versus-Kotlin parity fixture.

The fixture records, for each SMS, the inputs both implementations receive and
the Python verdict the Kotlin side must reproduce. Run this file directly after
changing cue or fusion rules:

    .venv\\Scripts\\python.exe tests\\make_parity_cases.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sentinel.detectors import sms_cues, url_indicators
from sentinel.fusion import fuse
from sentinel.routine_filter import sender_cue, should_skip, skip_kind
from sentinel.url_features import extract_urls, normalise_url

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "parity_cases.json"

SCHEMA_VERSION = 1

# Fixed fake SMS-model outputs keep the fixture independent of torch and models.
SMS_MODEL_RESULTS: dict[str, dict[str, Any] | None] = {
    "none": None,
    "ham": {"probs": {"ham": 0.90, "unwanted": 0.05, "scam": 0.05}, "label": "ham"},
    "weak_ham": {"probs": {"ham": 0.60, "unwanted": 0.25, "scam": 0.15}, "label": "ham"},
    "unwanted": {"probs": {"ham": 0.20, "unwanted": 0.75, "scam": 0.05}, "label": "unwanted"},
    "scam": {"probs": {"ham": 0.02, "unwanted": 0.08, "scam": 0.90}, "label": "scam"},
    "shoe_store": {
        "probs": {
            "ham": 0.013988708145916462,
            "unwanted": 0.29926422238349915,
            "scam": 0.6867470741271973,
        },
        "label": "scam",
    },
    "clear_scam": {"probs": {"ham": 0.0001, "unwanted": 0.0001, "scam": 0.9998}, "label": "scam"},
}

# (SMS text, fixed SMS-model result name). Coverage: scams, ham, Hinglish,
# UPI collect plus PIN, APK, time bounds, blocked, delivery, bad URLs, IPv6
# hosts and two-letter country-code domains.
CASE_INPUTS: list[tuple[str, str]] = [
    ("URGENT: your SBI account is blocked today. Update now: otp needed or legal action will follow", "none"),
    ("Dear customer your SBI account is suspended. Verify KYC now: http://sbi-kyc.xyz", "scam"),
    ("Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko 9876543210 call karein", "none"),
    ("Line kaat diya jayega aaj", "none"),
    ("SIM block ho jayega jaldi", "none"),
    ("You have received a UPI collect request of INR 10,000 from PhonePe Merchant. Approve now by entering your UPI PIN.", "none"),
    ("Instant Loan App Approved: Rs 50,000 credited instantly without CIBIL check. Download APK from loan-instant.xyz.", "none"),
    ("Install APK from http://loan-instant.top to get your loan", "none"),
    ("TRAI Notification: All mobile numbers registered on your Aadhaar will be blocked in 2 hours due to illegal spam calls. Press 1 to speak to officer.", "none"),
    ("Your parcel will be delivered today. Pay on delivery.", "none"),
    ("Your parcel will be delivered today. Pay on delivery.", "ham"),
    ("Electricity board: pay your bill immediately or connection will disconnect", "none"),
    ("Income tax notice: legal action and arrest if you do not pay fine", "none"),
    ("You won lottery prize cashback, claim within 24 hours", "none"),
    ("KBC lucky draw winner! Share your OTP to claim prize", "none"),
    ("Customs: your parcel held. Pay processing fee via UPI now", "none"),
    ("Police cyber crime: your account blocked, transfer refund fee urgently", "none"),
    ("Central bank of india: update your PAN and Aadhaar now", "none"),
    ("Your account is suspended, verify immediately", "none"),
    ("Visit http://192.168.1.1/login to verify your KYC", "none"),
    ("Verify at http://user:pass@phish.com now", "none"),
    ("Login at http://xn--80ak6aa92e.com/page to update KYC", "none"),
    ("Check http://a.b.c.example.com/test for your refund", "none"),
    ("Update at https://bit.ly/3xYz12 for KYC", "none"),
    ("Pay at https://sbi.co.in/pay?a=1|2 now", "none"),
    ("Check https://www.example.com/{x}/A now", "none"),
    ("Pay at http://[bad-host immediately", "none"),
    ("Your parcel is at http://[bad-host", "scam"),
    ("Rs 500 debited from SBI account. Check balance at https://sbi.co.in", "ham"),
    ("Your OTP for HDFC NetBanking is 482910. Valid for 5 mins. Do not share it with anyone.", "none"),
    ("Your OTP for HDFC NetBanking is 482910. Valid for 5 mins. Do not share it with anyone.", "ham"),
    ("Rs 500 received from Ravi via UPI. Ref 4821. Check balance in the app.", "none"),
    ("Hello friend, how are you?", "none"),
    ("Meeting moved to 5 pm in the office", "ham"),
    ("Your order has been shipped and will arrive tomorrow", "ham"),
    ("Happy birthday! Have a great day", "none"),
    ("Please call me when you reach home", "none"),
    ("Lunch at 1 pm today?", "none"),
    ("Payment of 500 upi received. Check at http://example.com", "weak_ham"),
    ("Visit www.google.com today", "none"),
    ("Update at paytm-help.xyz now", "none"),
    ("Offer amazon(.)in/offer", "unwanted"),
    ("Click bit.ly/3abc", "none"),
    ("mail me at ravi@gmail.com", "none"),
    ("I am ok.See you", "none"),
    ("Your bill is Rs.500 pay now", "none"),
    ("Use code SAVE50 for cashback offer today", "unwanted"),
    ("Aaj shaam ghar aa jao", "none"),
    ("Server at http://[2001:db8::1]/login is down", "none"),
    ("Access http://[2001:db8::1]:8080/login now", "none"),
    ("Visit http://secure.co.zz/login", "none"),
    ("Visit https://example.de/path", "none"),
    ("Check http://foo.gov.zz/file", "none"),
    ("Update KYC at sbi-kyc.co.in/verify now", "scam"),
    ("Pay processing fee via http://a.b.c.d.example.xyz/login", "none"),
    ("Your account is blocked. Verify now.", "none"),
    ("Your account is blocked today", "none"),
    ("Loan approved! Download apk now", "none"),
    ("HDFC bank: your netbanking is locked, verify immediately", "weak_ham"),
    # One isolated case per URL indicator, so ParityTest can compare the
    # Kotlin urlIndicators output against the Python reference per URL.
    ("Verify now at http://example.xyz/login", "none"),
    ("Click https://tinyurl.com/abc123 now", "none"),
    ("Check http://10.0.0.1/verify now", "none"),
    ("Login at http://xn--80ak6aa92e.com/login now", "none"),
    ("Verify at http://sbi-login.com now", "none"),
    ("Check http://a.b.c.d.example.com/test for your refund", "none"),
    ("Verify at http://user@example.com/login now", "none"),
    ("Verify at http://myipfs.example.com/login now", "none"),
    ("Check https://cdn-ipfs.example.org/verify now", "none"),
    ("Visit http://gateway.ipfs.io/login now", "none"),
    ("Verify at http://ipfs.io/login now", "none"),
    ("Welcome to our store. Thank you for shopping with us. Enjoy your day.", "shoe_store"),
    ("Verify now at http://sbi-kyc.xyz/login", "clear_scam"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply metroshoes.com", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply 9876543210", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply Reply YES to claim", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply ९८७६५४३२१०", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply Visit shop-now.world", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply mail offers@metro.in", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply pay to metro@ybl", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply Rs 499.99", "unwanted"),
    ("Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply 4.5 stars", "unwanted"),
    # Bank alert plus credential request: the shared floor must reach high.
    ("Rs 4,999 debited from A/c XX9012. Reply with OTP 4821 to reverse the debit.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Don't worry, share OTP with our executive to stop the debit.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Please do not share OTP or PIN with anyone.", "none"),
    ("Rs 5,000 debited from A/c XX1234. OTP kisi ko mat batao.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Kindly reveal your OTP to reverse the debit.", "none"),
    ("Rs 5,000 debited from A/c XX1234. We never, under any circumstances, and for no reason, ask you to share your OTP to reverse the debit.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Don't worry share OTP 4821 to cancel.", "none"),
    ("Rs 5,000 debited from A/c XX1234. If not you share OTP 4821 to cancel.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Never, under any circumstances, share your OTP.", "none"),
    ("Rs 5,000 debited from A/c XX1234. Quote reference code 849201 for any query.", "none"),
    # Devanagari digits must not match ASCII \\d in either implementation.
    ("आपका OTP ४८२१ है", "none"),
]


def _heuristic_url_probability(indicators: list[str]) -> float:
    """Mirror the no-model URL score used by both pipelines."""
    if "brand_lookalike" in indicators or "risky_tld" in indicators or "ip_host" in indicators:
        return 0.85
    if indicators:
        return 0.4
    return 0.05


def build_url_results(text: str) -> list[dict[str, Any]]:
    """Build the URL detector output for one message without loading a model."""
    results: list[dict[str, Any]] = []
    for url in extract_urls(text):
        indicators = url_indicators(url)
        probability = _heuristic_url_probability(indicators)
        results.append({
            "url": url,
            "norm_url": normalise_url(url),
            "prob": probability,
            "label": "phishing" if probability >= 0.5 else "benign",
            "indicators": indicators,
        })
    return results


# (SMS text, fixed SMS-model result name, sender). The sender is optional so
# the Python and Kotlin sides can compare the sender_mismatch cue.
SENDER_CASES: list[tuple[str, str, str | None]] = [
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "none", "+919876543210"),
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "none", "98765 43210"),
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "none", "AD-HDFCBK-S"),
    ("Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000", "none", "+919876543210"),
    ("Hi, call me on 98765 43210 when free", "none", "+919876543210"),
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "none", "56161"),
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "none", None),
    ("Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.", "clear_scam", "+919876543210"),
    ("Rs 500 paid via UPI, call me on 98765 43210", "none", "+919876543210"),
    ("I paid Rs 500 to your account, call me on 98765 43210", "none", "+919876543210"),
    # Round 2: request words must keep an attack in analysis from a DLT header.
    ("Rs 4,999 debited from A/c XX9012. Message OTP 4821 to stop debit.", "none", "AD-HDFCBK-S"),
    ("Rs 4,999 debited from A/c XX9012. Text OTP 4821 to block.", "none", "AD-HDFCBK-S"),
    ("Rs 4,999 debited from A/c XX9012. Quote the 6 digit code 482193 to stop the debit.", "none", "AD-HDFCBK-S"),
    ("Rs 4999 debit hua A/c XX9012 se. OTP 4821 bhejo.", "none", "AD-HDFCBK-S"),
    ("Rs 4,999 debited from A/c XX9012. Reach our helpline 011 2345 6789 to dispute.", "none", "AD-HDFCBK-S"),
    ("A/c XX9012 debited Rs 499. Pay Rs 99 via UPI to reactivate.", "none", "AD-HDFCBK-S"),
    # Round 2: genuine routine alerts stay skipped.
    (
        "482913 is your One Time Password (OTP) for login at Example. "
        "This OTP will only be valid for 10 minutes",
        "none",
        "AD-HDFCBK",
    ),
    (
        "Rs.500.00 credited to HDFC Bank A/c XX1234 on 12-11-26 from VPA user@okaxis (UPI 512345678901)",
        "none",
        "AD-HDFCBK",
    ),
    # Round 2: sender cue tightening.
    (
        "Rs 5,000 transferred from A/c XX1234 to VPA x@okaxis. Call 98111 22333 if not you.",
        "none",
        "+919876543210",
    ),
    ("Rs 5,000 debited from A/c XX1234. Call 98765 43210 if not you.", "none", "+919876543210"),
    ("Rs 2,000 credited to my a/c, call me on 98765 43210", "none", "9876543210"),
    ("Rs 500 credited to a/c XX1234. Call 98765 43210 for queries.", "none", "+919876543210"),
    # Round 3: secret request vs disclaimer cases.
    ("Rs 4,999 debited from A/c XX9012. Read out OTP 4821 to the officer.", "none", "AD-HDFCBK-S"),
    ("Rs 5,000 debited from A/c XX1234. OTP 4821 required to stop the debit.", "none", "AD-HDFCBK-S"),
    ("Rs 5,000 debited from A/c XX1234. Never share your OTP with anyone.", "none", "AD-HDFCBK-S"),
    ("Rs 5,000 debited from A/c XX1234 at ATM using PIN. Avl bal Rs 20,000.", "none", "AD-HDFCBK-S"),
    # Round 7: transaction naming a secret from DLT header is not skipped.
    ("Rs 5,000 debited from your account. Code 4821 required to stop the debit.", "none", "AD-HDFCBK-S"),
    ("Rs 5,000 debited from card 1234. Code 4821 required to stop the debit.", "none", "AD-HDFCBK-S"),
    ("Rs 500 paid from A/c XX1234. Code 1234 required to stop the payment.", "none", "AD-HDFCBK-S"),
    # Links from a registered sender count only when the SMS model says scam.
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "unwanted", "AD-NEWSHP-P"),
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "unwanted", None),
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "unwanted", "+919876543210"),
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "unwanted", "56161"),
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "clear_scam", "AD-NEWSHP-P"),
    ("Sale is live! Shop now: http://shop-deals.example.com/a1", "none", "AD-NEWSHP-P"),
    ("Your KYC is pending. Verify now: http://bit.ly/a1", "ham", "AD-HDFCBK-S"),
    ("Your KYC is pending. Verify now: http://bit.ly/a1", "ham", None),
    # A risky TLD or a bare IP host stays risky for a registered sender too.
    ("Your KYC is pending. Verify now: http://kyc-help.xyz/HDFCBK/a1", "ham", "AD-HDFCBK-S"),
    ("Your KYC is pending. Verify now: http://192.168.4.7/a1", "none", "AD-HDFCBK-S"),
    # The bank-only .bank.in zone is trusted for any sender.
    ("Offer for you: https://1.hdfc.bank.in/HDFCBK/s/abc", "none", None),
    ("Offer for you: https://bank.in.evil.xyz/s/abc", "none", None),
    # Without an SMS model answer a registered sender gets no link discount.
    ("Your KYC is pending. Verify now: http://bit.ly/a1", "none", "AD-HDFCBK-S"),
    # Known scam scripts floor the risk at high whatever the model says (rules.json scam_scripts).
    ("CBI பேசுகிறோம். உங்கள் Aadhaar money laundering case-ல் use ஆகியுள்ளது. நீங்கள் digital arrest-ல் இருக்கிறீர்கள்; video call-ல் உடனே join ஆகவும்.", "ham", None),
    ("CBI से बोल रहे हैं। आप digital arrest में हैं; तुरंत video call join करें।", "ham", None),
    ("You are under Digital Arrest. Join the video call with the officer now.", "ham", "+919876543210"),
    ("Digital arrest என்ற பெயரில் வரும் calls scam ஆக இருக்கலாம். Cybercrime helpline 1930-ஐ தொடர்பு கொள்ளவும்.", "ham", None),
    ("Police never place anyone under digital arrest on a video call. Report such calls.", "ham", None),
    ("Refund process செய்ய ₹1 மட்டும் pay செய்யுங்கள். அதன் பிறகு உங்கள் UPI account-க்கு ₹5,000 credit ஆகும்.", "ham", None),
    ("Refund process करने के लिए सिर्फ ₹1 pay करें। उसके बाद आपके UPI account में ₹1,999 credit होगा।", "ham", None),
    ("Refund ke liye sirf Rs 5 bhejo, phir Rs 2,000 wapas milega", "ham", None),
    ("To get your refund pay Rs. 10 now and receive Rs 4,999 in your account", "none", None),
    ("Your refund of Rs 499 has been credited to your account. Thank you for shopping.", "ham", "AD-NEWSHP-S"),
    ("Refund initiated. Pay Rs 1,499 on your next order and get free delivery. Amount will be credited in 5 days.", "ham", None),
    ("Daily 10% guaranteed profit! Minimum investment ₹499. இன்று மட்டும் VIP trading group-ல் join ஆகுங்கள்.", "unwanted", None),
    ("Daily 10% guaranteed profit! Minimum investment ₹499। आज ही VIP trading group join करें।", "unwanted", None),
    ("Earn guaranteed returns weekly. Join our Telegram channel today.", "unwanted", "AD-NEWSHP-P"),
    ("Guaranteed returns plan at 7.1% p.a. for 10 years. Speak to your insurance advisor.", "unwanted", "AD-NEWSHP-P"),
    ("Profit is never guaranteed in the stock market. Invest carefully.", "ham", None),
    # Newer scam scripts (upi_pin_to_receive, power_cut_call, task_job, new_number_money, prize_fee, apk_install).
    ("Enter your UPI PIN to receive Rs 2,000 cashback directly in your bank account.", "ham", None),
    ("Never enter your UPI PIN to receive money. PIN is only needed to send money.", "ham", None),
    ("Dear customer, your electricity power will be disconnected tonight at 9:30 pm. Call our officer immediately.", "ham", None),
    ("Scheduled power shutdown today for maintenance from 10:00 am to 2:00 pm. Call 1912 for queries.", "ham", None),
    ("Work from home job: earn Rs 3,000 per day by giving like and review on YouTube videos.", "ham", None),
    ("Beware of fake work from home offers promising Rs 2,000 per day for telegram tasks. Report to cybercrime.", "ham", None),
    ("Hi mom, I lost my phone and this is my new number. I urgently need you to transfer Rs 5,000.", "ham", None),
    ("This is my new number. Please do not send money to my old account.", "ham", None),
    ("Congratulations! You won a cash prize of Rs 25,00,000 in KBC lucky draw. Pay processing fee to claim.", "ham", None),
    ("Join our fantasy sports contest with entry fee Rs 49 and win from a prize pool of Rs 10 Lakhs.", "ham", None),
    ("Your bank account is suspended. Install the app from update-bank.apk to verify your KYC.", "ham", None),
    ("Never install any .apk file sent via SMS to update bank KYC details. Beware of fraud.", "ham", None),
]


def _build_cases() -> list[dict[str, Any]]:
    from sentinel.advisor import is_plain_promotion

    cases: list[dict[str, Any]] = []
    inputs: list[tuple[str, str, str | None]] = [(text, kind, None) for text, kind in CASE_INPUTS]
    inputs.extend(SENDER_CASES)
    for text, sms_kind, sender in inputs:
        sms_result = SMS_MODEL_RESULTS[sms_kind]
        url_results = build_url_results(text)
        cues = sms_cues(text)
        sender_span = sender_cue(sender, text) if sender is not None else None
        if sender_span is not None:
            cues = cues + [sender_span]
        evidence = fuse(text, sms_result, url_results, cues, None, sender)
        extracted = [item["url"] for item in url_results]

        case: dict[str, Any] = {
            "text": text,
            "sms_result": sms_result,
            "url_results": url_results,
            "expected": {
                "cues": cues,
                "cue_types": sorted({cue["type"] for cue in cues}),
                "risk": evidence.risk,
                "label": evidence.label,
                "level": evidence.level,
                "threshold": evidence.threshold,
                "extracted_urls": extracted,
                "normalised_urls": [normalise_url(url) for url in extracted],
                "is_plain_promotion": is_plain_promotion(text, evidence),
                "skip_kind": skip_kind(text),
            },
        }
        if sender is not None:
            case["sender"] = sender
            case["expected"]["should_skip"] = should_skip(sender, text)
        cases.append(case)
    return cases


def build_cases() -> dict[str, Any]:
    """Return the complete fixture as a JSON-serialisable dictionary."""
    return {
        "schema_version": SCHEMA_VERSION,
        "description": "Python reference verdicts that the Kotlin implementation must reproduce.",
        "cases": _build_cases(),
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
    print(f"wrote {len(build_cases()['cases'])} parity cases to {path}")
