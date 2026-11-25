"""Checks for the pure helpers of the translation kernel (no torch needed)."""
import pandas as pd

from training.translate.translate_mt import check_row, must_keep, sample_rows, template_key

SRC = "Your account 9876543210 got Rs 500. Visit https://pay.xyz/a or mail refund@example.com"


def test_must_keep_finds_url_email_and_long_digits():
    keep = must_keep(SRC)
    assert "https://pay.xyz/a" in keep
    assert "refund@example.com" in keep
    assert "9876543210" in keep
    assert "500" not in keep  # short amounts may be reformatted by the translator


def test_check_row_keeps_good_translation():
    out = "உங்கள் கணக்கு 9876543210 க்கு ரூ 500 வந்தது. https://pay.xyz/a அல்லது refund@example.com"
    assert check_row(SRC, out, "ta") is None


def test_check_row_drops_lost_token_wrong_script_and_short():
    assert check_row(SRC, "உங்கள் கணக்கு 9876543210 க்கு பணம் வந்தது refund@example.com", "ta") == "lost_token"
    assert check_row("Hello how are you today my friend", "Hello how are you today my friend", "hi") == "wrong_script"
    assert check_row("Hello how are you today", "ஹாய்", "ta") == "too_short"


def test_sample_rows_respects_class_counts_and_source_cap():
    rows = [{"text": f"scam {i}", "label": "scam", "source": "big"} for i in range(100)]
    rows += [{"text": f"scam s{i}", "label": "scam", "source": f"s{i % 5}"} for i in range(50)]
    rows += [{"text": f"ham {i}", "label": "ham", "source": "h"} for i in range(40)]
    got = sample_rows(pd.DataFrame(rows), {"scam": 20, "ham": 8}, seed=1)
    scam = got[got["label"] == "scam"]
    assert len(scam) == 20
    assert (scam["source"] == "big").sum() <= 5  # 25 percent of the class target
    assert (got["label"] == "ham").sum() == 2  # single source is capped too


def test_looks_english_rejects_portuguese_and_keeps_english():
    from training.translate.translate_mt import looks_english
    assert looks_english("Dear customer, your account will be blocked. Please call now.")
    assert not looks_english("Falhou, o saldo da tua conta M-Pesa e insuficiente para transferir 2,000.00MT.")


def test_fix_punctuation_restores_colon_and_thousands():
    from training.translate.translate_mt import fix_punctuation
    assert fix_punctuation("உதவுங்கள்ஃ https://a.top/x 2, 000 ரூபாய்", "ta") == "உதவுங்கள்: https://a.top/x 2,000 ரூபாய்"
    assert fix_punctuation("जियोः आपका KYC 2ः40 बजे", "hi") == "जियो: आपका KYC 2:40 बजे"
    assert fix_punctuation("அஃது சரி", "ta") == "அஃது சரி"  # a real aytham inside a word is untouched


def test_sample_rows_prefers_indian_rows():
    rows = [{"text": f"t{i}", "label": "scam", "source": f"s{i % 8}", "india": (i // 8) % 2 == 0} for i in range(80)]
    got = sample_rows(pd.DataFrame(rows), {"scam": 10}, seed=3)
    assert len(got) == 10 and got["india"].all()


def test_template_key_matches_training_rule():
    from training.sms.train_sms import template_key as reference
    for text in (SRC, "Pay 1,200 at www.x.in NOW", "plain words"):
        assert template_key(text) == reference(text)
