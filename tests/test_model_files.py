"""Tests for the shared model file names (F2)."""

from __future__ import annotations

import json
from pathlib import Path

from sentinel.cli import REQUIRED_MODEL_ROLES, load_model_files, linux_default_name, phone_file_name

MODEL_FILES = Path(__file__).resolve().parent.parent / "sentinel" / "data" / "model_files.json"
EXPECTED_ROLES = (
    "url_model",
    "url_vocab",
    "sms_model",
    "sms_id_map",
    "sms_vocab",
    "sms_tokenizer_dir",
    "llama_model",
    "llama_tokenizer",
)


def test_model_files_has_all_roles():
    raw = json.loads(MODEL_FILES.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    files = raw["files"]
    assert set(EXPECTED_ROLES).issubset(files.keys())
    assert set(files.keys()) == set(EXPECTED_ROLES) | {"sms_fp32"}
    for role, entry in files.items():
        assert isinstance(entry["phone"], str) and entry["phone"]
        assert isinstance(entry["linux"], str) and entry["linux"]


def test_optional_sms_fp32_is_not_a_required_role():
    raw = json.loads(MODEL_FILES.read_text(encoding="utf-8"))
    entry = raw["files"]["sms_fp32"]
    assert entry["phone"] == "sms_fp32.pte"
    assert entry["linux"] == "sms_v6ml/sms_fp32_int8emb.pte"
    assert "optional" in entry.get("description", "").lower()
    assert "sms_fp32" not in REQUIRED_MODEL_ROLES
    assert "sms_fp32" not in EXPECTED_ROLES


def test_cli_linux_defaults_match_model_files():
    files = load_model_files()
    assert tuple(files.keys()) == REQUIRED_MODEL_ROLES
    for role in REQUIRED_MODEL_ROLES:
        assert linux_default_name(role) == files[role]["linux"]
        assert phone_file_name(role) == files[role]["phone"]


def test_expected_names_unchanged():
    files = load_model_files()
    assert files["url_model"] == {"phone": "url_cnn_v2.pte", "linux": "url_v2/url_cnn_v2.pte"}
    assert files["url_vocab"] == {"phone": "vocab.json", "linux": "url_v2/vocab.json"}
    assert files["sms_model"] == {"phone": "sms_int8.pte", "linux": "sms_v6ml/sms_int8.pte"}
    assert files["sms_id_map"] == {"phone": "id_map.json", "linux": "sms_v6ml/id_map.json"}
    assert files["sms_vocab"] == {"phone": "sms_vocab.txt", "linux": "sms_v6ml/sms_vocab.txt"}
    assert files["sms_tokenizer_dir"] == {"phone": "sms_vocab.txt", "linux": "sms_v6ml/tokenizer"}
    assert files["llama_model"] == {
        "phone": "llama.pte",
        "linux": "llama32_1b/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte",
    }
    assert files["llama_tokenizer"] == {"phone": "tokenizer.model", "linux": "llama32_1b/tokenizer.model"}


def test_linux_sms_id_map_is_next_to_model():
    files = load_model_files()
    assert files["sms_id_map"]["linux"] == "sms_v6ml/id_map.json"
