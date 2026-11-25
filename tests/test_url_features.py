from pathlib import Path

import pytest

from sentinel.url_features import extract_urls, normalise_url

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("url,expected", [
    ("https://www.example.com/path/", "example.com/path"),
    ("http://EXAMPLE.com", "example.com"),
    ("www.test.co.in/foo/bar/", "test.co.in/foo/bar"),
    ("hxxp://www.phish.org/login", "phish.org/login"),
    ("bad[.]com/x?a=1", "bad.com/x?a=1"),
    ("bare-domain.com", "bare-domain.com"),
    ("http://[bad-host", "http://[bad-host"),
    ("", ""),
])
def test_normalise_url(url, expected):
    assert normalise_url(url) == expected


@pytest.mark.parametrize("text", [
    "Hello. World is fine",
    "Your bill is Rs.500 pay now",
    "Call me. Thanks",
    "Score was 3.5 today",
    "e.g. this",
    "I am ok.See you",
    "Version v1.2 released",
    "mail me at ravi@gmail.com",
])
def test_extract_urls_negatives(text):
    assert extract_urls(text) == []


@pytest.mark.parametrize("text,expected", [
    ("Go to https://example.com.", ["https://example.com"]),
    ("Use www.google.com today", ["www.google.com"]),
    ("visit hxxp://bad[.]com/x", ["http://bad.com/x"]),
    ("Update KYC at sbi-kyc.co.in/verify now", ["sbi-kyc.co.in/verify"]),
    ("Click bit.ly/3abc", ["bit.ly/3abc"]),
    ("Update at paytm-help.xyz now", ["paytm-help.xyz"]),
    ("Offer amazon(.)in/offer", ["amazon.in/offer"]),
    ("a.com and a.com again", ["a.com"]),
])
def test_extract_urls_positives(text, expected):
    assert extract_urls(text) == expected


def _block(path):
    s = (ROOT / path).read_text(encoding="utf-8")
    return s.split("# --- SENTINEL URL FEATURES BLOCK START ---")[1].split("# --- SENTINEL URL FEATURES BLOCK END ---")[0]


def test_training_copy_matches_package():
    for script in ("training/url/train_url.py", "training/url_v2/train_url_v2.py"):
        assert _block(script) == _block("sentinel/url_features.py"), script


def test_indian_urls_csv_embedded_copy_matches():
    # Kaggle uploads only the script, so the CSV is embedded; it must not drift from the file
    s = (ROOT / "training/url_v2/train_url_v2.py").read_text(encoding="utf-8")
    embedded = s.split('INDIAN_URLS_CSV = """', 1)[1].split('"""', 1)[0]
    assert embedded.strip() == (ROOT / "training/url_v2/indian_urls.csv").read_text(encoding="utf-8").strip()
