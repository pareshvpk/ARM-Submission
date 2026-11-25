"""Regression tests for low-severity Python backlog fixes (B/R2B/R3B)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_b21_missing_llama_server_warns(tmp_path, capsys):
    from sentinel.cli import _load_advisor

    llama_main = tmp_path / "llama_main"
    llama_main.write_bytes(b"stub")
    llama_dir = tmp_path / "llama32_1b"
    llama_dir.mkdir()
    (llama_dir / "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte").write_bytes(b"stub")
    (llama_dir / "tokenizer.model").write_bytes(b"stub")
    args = argparse.Namespace(
        no_llm=False,
        llama_main=str(llama_main),
        llama_model=str(llama_dir / "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"),
        llama_tokenizer=str(llama_dir / "tokenizer.model"),
        llama_server="/nonexistent/sentinel_llama_server",
        threads=3,
    )
    advisor, status = _load_advisor(str(tmp_path), args)
    captured = capsys.readouterr()
    assert "llama-server not found" in captured.err
    if advisor is not None:
        advisor.close()
    assert status in ("loaded",) or advisor is not None


def test_b22_file_with_latin1_does_not_crash(tmp_path):
    from sentinel.cli import gather_messages

    f = tmp_path / "msgs.txt"
    f.write_bytes(b"caf\xe9 message\nhello\n")
    args = argparse.Namespace(file=str(f), text_option=None, text=None)
    messages = gather_messages(args, None)
    assert messages is not None
    assert len(messages) == 2
    assert "hello" in messages[1]


def test_b23_resident_fallback_closes_client(monkeypatch):
    from sentinel.advisor import LlamaAdvisor
    from sentinel.fusion import Evidence

    def fake_run(*args, **kwargs):
        stats = {"prompt_tokens": 10}
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout="mocked llama_main advice\nPyTorchObserver " + json.dumps(stats) + "\n",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    advisor = LlamaAdvisor(
        llama_main="llama_main", model_path="llama.pte", tokenizer_path="tokenizer.bin",
        llama_server="ignored",
    )
    mock_client = MagicMock()
    mock_client.generate.side_effect = RuntimeError("boom")
    advisor._server_client = mock_client
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    text, stats = advisor.generate("your account is blocked", ev)
    assert text == "mocked llama_main advice"
    assert stats["prompt_path"] == "llama_main"
    assert advisor._server_client is None


def test_r2b8_empty_id_map_raises():
    from sentinel.detectors import _remap_scalar, remap_ids

    with pytest.raises(RuntimeError, match="empty"):
        _remap_scalar(0, [])
    with pytest.raises(RuntimeError, match="empty"):
        remap_ids([0, 1], [])


def test_r3b5_resident_strips_special_tokens():
    from sentinel.advisor import LlamaAdvisor

    advisor = object.__new__(LlamaAdvisor)
    advisor.llama_server = "srv"
    advisor.model_path = "m"
    advisor.tokenizer_path = "t"
    advisor.threads = 3
    advisor.max_new_tokens = 10
    advisor.timeout_s = 1.0
    mock_client = MagicMock()
    mock_client.generate.return_value = ("<|eot_id|>Advice **here**<|begin_of_text|>", {"x": 1}, 0.5)
    advisor._server_client = mock_client
    text, stats = advisor._generate_resident("tail")
    assert "<|eot_id|>" not in text
    assert "**" not in text
    assert "Advice" in text
    assert "here" in text


def test_r3b6_advisor_failure_logs_warning(caplog):
    from sentinel.fusion import Evidence
    from sentinel.pipeline import _run_advisor

    class BoomAdvisor:
        def generate(self, text, evidence):
            raise RuntimeError("llama crashed")

    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    with caplog.at_level("WARNING", logger="sentinel.pipeline"):
        advice, source = _run_advisor("hello", ev, BoomAdvisor())
    assert source == "template"
    assert "RuntimeError" in caplog.text


def test_r3b7_manifest_parent_fallback(tmp_path):
    from sentinel.detectors import verify_model_files

    model_dir = tmp_path / "sms_v6ml"
    model_dir.mkdir()
    pte = model_dir / "sms_int8.pte"
    pte.write_bytes(b"stub pte")
    digest = hashlib.sha256(b"stub pte").hexdigest()
    (tmp_path / "models.sha256").write_text(f"{digest}  sms_v6ml/sms_int8.pte\n", encoding="utf-8")
    (model_dir / "models.sha256").write_text(f"{digest}  sms_v6ml/sms_int8.pte\n", encoding="utf-8")
    assert verify_model_files([str(pte)], anchor_path=str(pte)) is True


def test_b28_encode_requires_torch():
    from sentinel.detectors import UrlDetector

    detector = object.__new__(UrlDetector)
    detector.chars = {}
    detector.unk = 1
    detector.pad = 0
    detector.max_len = 8
    detector._torch = None
    with pytest.raises(RuntimeError, match="no torch"):
        detector.encode("example.com")


def test_b25_download_streams_and_hashes(tmp_path, monkeypatch):
    from data.fetch_external import download_to_file

    class FakeResponse:
        def __init__(self, data: bytes):
            self._data = data
            self._pos = 0

        def read(self, n=-1):
            chunk = self._data[self._pos:self._pos + n]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    payload = b"x" * 70000 + b"hello"
    monkeypatch.setattr(
        "data.fetch_external.urllib.request.urlopen",
        lambda req, timeout=120: FakeResponse(payload),
    )
    dest = tmp_path / "out.bin"
    digest = download_to_file("http://example.test/file", dest)
    assert dest.read_bytes() == payload
    assert digest == hashlib.sha256(payload).hexdigest()


def test_b19_cli_import_is_lazy():
    text = (ROOT / "sentinel" / "cli.py").read_text(encoding="utf-8")
    header = text.split("def build_parser")[0]
    assert "from sentinel.advisor import" not in header
    assert "from sentinel.detectors import" not in header
    assert "from sentinel.pipeline import" not in header


def test_b24_kaggle_validates_ref():
    text = (ROOT / "data" / "fetch_kaggle.py").read_text(encoding="utf-8")
    assert "_REF_RE" in text
    assert "metadata" in text and "returncode" in text


def test_b26_inspector_redacts_by_default():
    text = (ROOT / "data" / "inspect_raw.py").read_text(encoding="utf-8")
    assert "--show-samples" in text
    assert "sample_redacted" in text
    assert "sha256" in text
