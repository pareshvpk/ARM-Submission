import pytest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.sms.train_sms import (
    template_key,
    should_exclude_source,
    map_label,
    fix_mojibake,
)

def test_template_key():
    assert template_key("Hello from 1234 at https://example.com/foo") == "hello from 0 at u"
    assert template_key("Call 9876543210 www.test.co.in/path?q=1 now") == "call 0 u now"
    assert template_key("") == ""
    assert template_key(None) == ""

def test_should_exclude_source():
    assert should_exclude_source({"preprocessed": True}) is True
    assert should_exclude_source({"channel": "email"}) is True
    assert should_exclude_source({"channel": "job_post"}) is True
    assert should_exclude_source({"skip": True}) is True
    assert should_exclude_source({"preprocessed": False, "channel": "sms"}) is False

def test_map_label():
    assert map_label("ham") == 0
    assert map_label("spam") == 1
    assert map_label("unwanted") == 1
    assert map_label("scam") == 2
    assert map_label("unknown") is None
    assert map_label(None) is None

def test_fix_mojibake():
    moji_quote = "I" + "\u00e2\u20ac\u2122" + "ve"
    expected_quote = "I" + "\u2019" + "ve"
    assert fix_mojibake(moji_quote) == expected_quote

    assert fix_mojibake("Hello World 123!") == "Hello World 123!"
    assert fix_mojibake("नमस्ते दुनिया") == "नमस्ते दुनिया"

    emoji_orig = "😀🎉"
    emoji_moji = emoji_orig.encode("utf-8").decode("latin-1")
    assert fix_mojibake(emoji_moji) == emoji_orig
from sentinel.detectors import remap_ids

def test_remap_ids():
    id_map = [10, 20, 30, 40]
    assert remap_ids([0, 2, 3], id_map) == [10, 30, 40]
    assert remap_ids((0, 1), id_map) == [10, 20]
    assert remap_ids(1, id_map) == 20
    try:
        import torch
        t = torch.tensor([[0, 1], [2, 3]], dtype=torch.long)
        remapped = remap_ids(t, id_map)
        assert isinstance(remapped, torch.Tensor)
        assert remapped.tolist() == [[10, 20], [30, 40]]
    except ImportError:
        pass
