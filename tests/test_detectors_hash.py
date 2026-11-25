"""Tests for model hash verification (B-9)."""
from __future__ import annotations

import hashlib

import pytest

from sentinel.detectors import SmsDetector, UrlDetector, verify_model_files, verify_pte_hash


def _hash(path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_verify_skips_when_no_manifest(tmp_path, capsys):
    pte = tmp_path / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    assert verify_pte_hash(str(pte)) is False
    captured = capsys.readouterr()
    assert "unverified" in captured.err
    assert "url_cnn_v2.pte" in captured.err


def test_verify_returns_true_with_correct_hash(tmp_path):
    pte = tmp_path / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    digest = _hash(pte)
    (tmp_path / "models.sha256").write_text(f"{digest}  url_cnn_v2.pte\n", encoding="utf-8")
    assert verify_pte_hash(str(pte)) is True


def test_verify_model_files_warns_listing_all_unverified(tmp_path, capsys):
    pte = tmp_path / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    vocab = tmp_path / "vocab.json"
    vocab.write_text('{"pad": 0, "unk": 1}', encoding="utf-8")
    assert verify_model_files([str(pte), str(vocab)]) is False
    captured = capsys.readouterr()
    assert "url_cnn_v2.pte" in captured.err
    assert "vocab.json" in captured.err


def test_verify_passes_with_correct_hash_next_to_pte(tmp_path):
    pte = tmp_path / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    digest = _hash(pte)
    (tmp_path / "models.sha256").write_text(f"{digest}  url_cnn_v2.pte\n", encoding="utf-8")
    verify_pte_hash(str(pte))


def test_verify_passes_with_relative_path_entry(tmp_path):
    models = tmp_path / "models"
    sub = models / "url_v2"
    sub.mkdir(parents=True)
    pte = sub / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    digest = _hash(pte)
    (models / "models.sha256").write_text(f"{digest}  url_v2/url_cnn_v2.pte\n", encoding="utf-8")
    verify_pte_hash(str(pte))


def test_verify_refuses_mismatch(tmp_path):
    pte = tmp_path / "sms_int8.pte"
    pte.write_bytes(b"tampered")
    (tmp_path / "models.sha256").write_text(
        "0" * 64 + "  sms_int8.pte\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        verify_pte_hash(str(pte))


def test_verify_refuses_missing_entry_when_manifest_present(tmp_path):
    pte = tmp_path / "sms_int8.pte"
    pte.write_bytes(b"stub")
    (tmp_path / "models.sha256").write_text(
        "0" * 64 + "  url_cnn_v2.pte\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="No expected hash"):
        verify_pte_hash(str(pte))


def test_url_detector_refuses_mismatch(tmp_path):
    sub = tmp_path / "url_v2"
    sub.mkdir()
    pte = sub / "url_cnn_v2.pte"
    pte.write_bytes(b"tampered")
    vocab = sub / "vocab.json"
    vocab.write_text('{"pad": 0, "unk": 1}', encoding="utf-8")
    (sub / "models.sha256").write_text(
        "0" * 64 + "  url_cnn_v2.pte\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        UrlDetector(str(pte), str(vocab))


def test_sms_detector_refuses_mismatch(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"tampered")
    id_map = sub / "id_map.json"
    id_map.write_text("[1, 2, 3]", encoding="utf-8")
    lines = [
        "0" * 64 + "  sms_int8.pte",
        f"{_hash(id_map)}  id_map.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        SmsDetector(str(pte), str(sub / "tokenizer"))


def test_url_detector_refuses_tampered_vocab(tmp_path):
    sub = tmp_path / "url_v2"
    sub.mkdir()
    pte = sub / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    vocab = sub / "vocab.json"
    vocab.write_text('{"pad": 0, "unk": 1}', encoding="utf-8")
    lines = [
        f"{_hash(pte)}  url_cnn_v2.pte",
        f"{'0' * 64}  vocab.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch for vocab.json"):
        UrlDetector(str(pte), str(vocab))


def test_url_detector_refuses_missing_vocab_entry(tmp_path):
    sub = tmp_path / "url_v2"
    sub.mkdir()
    pte = sub / "url_cnn_v2.pte"
    pte.write_bytes(b"stub pte")
    vocab = sub / "vocab.json"
    vocab.write_text('{"pad": 0, "unk": 1}', encoding="utf-8")
    (sub / "models.sha256").write_text(f"{_hash(pte)}  url_cnn_v2.pte\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No expected hash for vocab.json"):
        UrlDetector(str(pte), str(vocab))


def test_sms_detector_refuses_tampered_id_map(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    id_map = sub / "id_map.json"
    id_map.write_text("[1, 2, 3]", encoding="utf-8")
    lines = [
        f"{_hash(pte)}  sms_int8.pte",
        f"{'0' * 64}  id_map.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch for id_map.json"):
        SmsDetector(str(pte), str(sub / "tokenizer"))


def test_sms_detector_refuses_missing_id_map_entry(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    (sub / "id_map.json").write_text("[1, 2, 3]", encoding="utf-8")
    (sub / "models.sha256").write_text(f"{_hash(pte)}  sms_int8.pte\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No expected hash for id_map.json"):
        SmsDetector(str(pte), str(sub / "tokenizer"))


def test_sms_detector_refuses_tampered_tokenizer_file(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    id_map = sub / "id_map.json"
    id_map.write_text("[1, 2, 3]", encoding="utf-8")
    tok = sub / "tokenizer"
    tok.mkdir()
    (tok / "tokenizer.json").write_text("{}", encoding="utf-8")
    lines = [
        f"{_hash(pte)}  sms_int8.pte",
        f"{_hash(id_map)}  id_map.json",
        f"{'0' * 64}  tokenizer.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch for tokenizer.json"):
        SmsDetector(str(pte), str(tok))


def test_sms_detector_refuses_missing_tokenizer_entry(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    id_map = sub / "id_map.json"
    id_map.write_text("[1, 2, 3]", encoding="utf-8")
    tok = sub / "tokenizer"
    tok.mkdir()
    (tok / "tokenizer.json").write_text("{}", encoding="utf-8")
    lines = [
        f"{_hash(pte)}  sms_int8.pte",
        f"{_hash(id_map)}  id_map.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="No expected hash for tokenizer.json"):
        SmsDetector(str(pte), str(tok))


def test_sms_detector_refuses_missing_id_map_file(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    lines = [
        f"{_hash(pte)}  sms_int8.pte",
        f"{'0' * 64}  id_map.json",
    ]
    (sub / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="id_map.json is required"):
        SmsDetector(str(pte), str(sub / "tokenizer"))


def test_sms_detector_refuses_missing_id_map_without_manifest(tmp_path):
    sub = tmp_path / "sms_v6ml"
    sub.mkdir()
    pte = sub / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    with pytest.raises(RuntimeError, match="id_map.json is required"):
        SmsDetector(str(pte), str(sub / "tokenizer"), id_map_path=str(sub / "id_map.json"))
