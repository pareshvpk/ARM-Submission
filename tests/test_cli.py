from __future__ import annotations

import argparse
import json
import os
import tempfile

import pytest

from sentinel.cli import load_detectors, main
from sentinel.detectors import UrlDetector


def _args(models_dir: str, no_llm: bool = True) -> argparse.Namespace:
    return argparse.Namespace(
        models_dir=models_dir,
        url_model=None,
        url_vocab=None,
        sms_model=None,
        sms_tokenizer=None,
        no_llm=no_llm,
        llama_main="llama_main",
        llama_model=None,
        llama_tokenizer=None,
        llama_server="",
        text_option=None,
        text=None,
        file=None,
        json=False,
        color="never",
    )


def test_load_detectors_warns_on_failure(monkeypatch, capsys):
    class Boom(Exception):
        pass

    def boom_init(self, *a, **k):
        raise Boom("bad pte")

    monkeypatch.setattr(UrlDetector, "__init__", boom_init)

    args = argparse.Namespace(
        models_dir=".",
        url_model="url_model.pte",
        url_vocab="vocab.json",
        sms_model="sms_model.pte",
        sms_tokenizer="sms_tokenizer",
        no_llm=True,
        llama_main="llama_main",
        llama_model="llama.pte",
        llama_tokenizer="tokenizer.bin",
    )

    # create dummy files so the load path is attempted
    d = tempfile.mkdtemp()
    open(os.path.join(d, "url_model.pte"), "w").close()
    open(os.path.join(d, "vocab.json"), "w").close()
    args.models_dir = d
    args.url_model = os.path.join(d, "url_model.pte")
    args.url_vocab = os.path.join(d, "vocab.json")

    url_det, sms_det, advisor, status = load_detectors(args)
    assert url_det is None
    assert "bad pte" in status["url"]
    captured = capsys.readouterr()
    assert "url detector" in captured.err.lower()
    assert "bad pte" in captured.err


def test_load_detectors_missing_files_status(tmp_path):
    args = _args(str(tmp_path), no_llm=True)
    url_det, sms_det, advisor, status = load_detectors(args)
    assert url_det is None
    assert sms_det is None
    assert advisor is None
    assert status["url"].startswith("missing:")
    assert "url_cnn_v2.pte" in status["url"]
    assert "vocab.json" in status["url"]
    assert status["sms"].startswith("missing:")
    assert "sms_int8.pte" in status["sms"]
    assert status["llama"] == "disabled (--no-llm)"


def test_load_detectors_missing_llama_when_enabled(tmp_path):
    args = _args(str(tmp_path), no_llm=False)
    args.llama_main = str(tmp_path / "llama_main")
    url_det, sms_det, advisor, status = load_detectors(args)
    assert advisor is None
    assert status["llama"].startswith("missing:")
    assert "llama_main" in status["llama"]
    assert "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte" in status["llama"]


def test_load_detectors_invalid_stub_vocab_status(tmp_path):
    (tmp_path / "url_model.pte").write_bytes(b"stub pte")
    (tmp_path / "vocab.json").write_text("not json", encoding="utf-8")
    args = _args(str(tmp_path), no_llm=True)
    args.url_model = str(tmp_path / "url_model.pte")
    args.url_vocab = str(tmp_path / "vocab.json")
    url_det, sms_det, advisor, status = load_detectors(args)
    assert url_det is None
    assert "JSONDecodeError" in status["url"] or "Expecting value" in status["url"]


def test_url_detector_from_stub_files_raises_with_reason(tmp_path):
    pte = tmp_path / "url_model.pte"
    pte.write_bytes(b"stub pte")
    valid_vocab = tmp_path / "vocab.json"
    valid_vocab.write_text('{"pad": 0, "unk": 1}', encoding="utf-8")
    with pytest.raises(OSError):
        UrlDetector(str(pte), str(tmp_path / "missing_vocab.json"))
    bad_vocab = tmp_path / "bad_vocab.json"
    bad_vocab.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        UrlDetector(str(pte), str(bad_vocab))


def test_cli_json_includes_detectors_loaded(monkeypatch, capsys):
    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, None, None))

    msg = "Hello there"
    exit_code = main(["scan", msg, "--no-llm", "--json"])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "detectors_loaded" in data
    assert data["detectors_loaded"] == []
    assert "detector_status" in data
    assert data["detector_status"] == {
        "url": "not loaded",
        "sms": "not loaded",
        "llama": "not loaded",
    }


def test_cli_json_detector_status_reports_reasons(monkeypatch, capsys):
    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda args: (
            None,
            None,
            None,
            {"url": "missing: /x/url_model.pte", "sms": "loaded", "llama": "disabled (--no-llm)"},
        ),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["detectors_loaded"] == []
    assert data["detector_status"]["url"] == "missing: /x/url_model.pte"
    assert data["detector_status"]["sms"] == "loaded"
    assert data["detector_status"]["llama"] == "disabled (--no-llm)"


class _FakeCpuinfoPath:
    """Fake Path that serves a simulated aarch64 /proc/cpuinfo."""

    def __init__(self, *args):
        self._path = str(args[0]) if args else ""

    def read_text(self, *args, **kwargs):
        return "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp\n"

    def iterdir(self):
        return []

    def is_file(self):
        return False


def test_cli_json_valid_on_simulated_aarch64(monkeypatch, capsys):
    import sentinel.cpu_features as cpu_features

    monkeypatch.setattr("sentinel.cli.load_detectors", lambda args: (None, None, None))
    monkeypatch.setattr(cpu_features, "_is_linux_aarch64", lambda: True)
    monkeypatch.setattr(cpu_features, "Path", _FakeCpuinfoPath)
    monkeypatch.setattr(cpu_features, "_logged", False)
    capsys.readouterr()
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "accel_path" not in captured.out
    assert "accel_path=DOTPROD" in captured.err
    data = json.loads(captured.out)
    assert data["message"] == "Hello there"


def test_analyse_never_raises_on_malformed_url():
    from sentinel.pipeline import analyse

    text = "pay at http://[bad-host"
    result = analyse(text)
    assert "evidence" in result
    assert "advice" in result
    assert result["advice_source"] in ("template", "llm")


def test_degraded_sms_detector_warning_mode_json_and_strict(monkeypatch, capsys, tmp_path):
    from sentinel.cli import load_detectors
    from sentinel.detectors import SmsDetector

    def boom_init(self, *a, **k):
        raise ImportError("transformers not installed")

    monkeypatch.setattr(SmsDetector, "__init__", boom_init)

    sms_pte = tmp_path / "sms_int8.pte"
    sms_pte.write_bytes(b"stub pte")
    sms_id_map_dir = tmp_path / "sms_v6ml"
    sms_id_map_dir.mkdir(exist_ok=True)
    (sms_id_map_dir / "id_map.json").write_text("[1, 2, 3]", encoding="utf-8")
    tok_dir = tmp_path / "sms_tokenizer"
    tok_dir.mkdir()
    (tok_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    args = _args(str(tmp_path), no_llm=True)
    args.sms_model = str(sms_pte)
    args.sms_tokenizer = str(tok_dir)
    url_det, sms_det, advisor, status = load_detectors(args)
    assert sms_det is None
    assert "transformers" in status["sms"]
    captured = capsys.readouterr()
    assert "sms detector" in captured.err.lower()
    assert "SMS model unavailable" in captured.err
    assert "transformers" in captured.err

    dummy_url_det = object()
    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (dummy_url_det, None, None, {"url": "loaded", "sms": "ImportError: transformers not installed", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["degraded"] == ["sms"]

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (dummy_url_det, None, None, {"url": "loaded", "sms": "ImportError: transformers not installed", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json", "--strict"])
    assert exit_code == 2
    capsys.readouterr()
    exit_code = main(["scan", "Hello there", "--no-llm"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Mode: rules only (SMS model unavailable)" in captured.out


def test_unverified_detectors_degraded_and_strict(monkeypatch, capsys):
    class _UnverifiedUrl:
        hash_verified = False

        def score(self, url):
            return {"url": url, "norm_url": "example.com", "prob": 0.05, "label": "benign", "indicators": []}

    class _UnverifiedSms:
        hash_verified = False

        def predict(self, text):
            return {"probs": {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}, "label": "ham"}

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_UnverifiedUrl(), _UnverifiedSms(), None, {"url": "loaded", "sms": "loaded", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "url" in data["degraded"]
    assert "sms" in data["degraded"]

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_UnverifiedUrl(), _UnverifiedSms(), None, {"url": "loaded", "sms": "loaded", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json", "--strict"])
    assert exit_code == 2


def test_url_model_error_degraded_and_strict(monkeypatch, capsys):
    class _BoomUrl:
        def score(self, url):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_BoomUrl(), None, None, {"url": "loaded", "sms": "missing: /x/sms_int8.pte", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Verify now http://sbi-fake.xyz/login", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "url_model_error" in data["evidence"]["indicators"]
    assert "url" in data["degraded"]

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_BoomUrl(), None, None, {"url": "loaded", "sms": "missing: /x/sms_int8.pte", "llama": "disabled (--no-llm)"}),
    )
    # url load-time degraded is absent (detector exists) but runtime URL
    # errors plus the missing SMS detector still trip --strict.
    exit_code = main(["scan", "Verify now http://sbi-fake.xyz/login", "--no-llm", "--json", "--strict"])
    assert exit_code == 2


def test_missing_id_map_sms_degraded_and_strict(tmp_path, capsys):
    sms_dir = tmp_path / "sms_v6ml"
    sms_dir.mkdir()
    (sms_dir / "sms_int8.pte").write_bytes(b"stub pte")
    tok_dir = sms_dir / "tokenizer"
    tok_dir.mkdir()
    (tok_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    args = _args(str(tmp_path), no_llm=True)
    url_det, sms_det, advisor, status = load_detectors(args)
    assert sms_det is None
    assert "id_map.json" in status["sms"]
    assert status["sms"].startswith("missing:")
    capsys.readouterr()
    exit_code = main(["scan", "Hello there", "--no-llm", "--json", "--strict", "--models-dir", str(tmp_path)])
    assert exit_code == 2
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "sms" in data["degraded"]


def test_unverified_llama_degraded_and_strict(monkeypatch, capsys):
    class _VerifiedUrl:
        hash_verified = True

        def score(self, url):
            return {"url": url, "norm_url": "example.com", "prob": 0.05, "label": "benign", "indicators": []}

    class _VerifiedSms:
        hash_verified = True

        def predict(self, text):
            return {"probs": {"ham": 0.9, "unwanted": 0.05, "scam": 0.05}, "label": "ham"}

    class _UnverifiedAdvisor:
        hash_verified = False

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_VerifiedUrl(), _VerifiedSms(), _UnverifiedAdvisor(), {"url": "loaded", "sms": "loaded", "llama": "loaded"}),
    )
    exit_code = main(["scan", "Hello there", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "llama" in data["degraded"]

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_VerifiedUrl(), _VerifiedSms(), _UnverifiedAdvisor(), {"url": "loaded", "sms": "loaded", "llama": "loaded"}),
    )
    exit_code = main(["scan", "Hello there", "--json", "--strict"])
    assert exit_code == 2


def test_tampered_llama_refused_by_load_detectors(tmp_path, capsys):
    import hashlib

    def _hash(path) -> str:
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    llama_dir = tmp_path / "llama32_1b"
    llama_dir.mkdir()
    model = llama_dir / "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
    model.write_bytes(b"tampered")
    tok = llama_dir / "tokenizer.model"
    tok.write_bytes(b"tok")
    lines = [
        f"{'0' * 64}  Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte",
        f"{_hash(tok)}  tokenizer.model",
    ]
    (llama_dir / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "llama_main").write_bytes(b"stub")
    args = _args(str(tmp_path), no_llm=False)
    args.llama_main = str(tmp_path / "llama_main")
    url_det, sms_det, advisor, status = load_detectors(args)
    assert advisor is None
    assert "SHA-256 mismatch" in status["llama"]
    captured = capsys.readouterr()
    assert "advisor not loaded" in captured.err
    assert "SHA-256 mismatch" in captured.err


def test_analysis_error_only_degraded_mode_and_strict(monkeypatch, capsys):
    class _VerifiedUrl:
        hash_verified = True

        def score(self, url):
            return {"url": url, "norm_url": "example.com", "prob": 0.05, "label": "benign", "indicators": []}

    class _BadSms:
        hash_verified = True

        def predict(self, text):
            return {"probs": {"ham": 0.1, "unwanted": 0.1, "scam": "invalid"}, "label": "scam"}

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_VerifiedUrl(), _BadSms(), None, {"url": "loaded", "sms": "loaded", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "analysis_error" in data["evidence"]["indicators"]
    assert "sms_model_error" not in data["evidence"]["indicators"]
    assert "analysis" in data["degraded"]

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_VerifiedUrl(), _BadSms(), None, {"url": "loaded", "sms": "loaded", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm", "--json", "--strict"])
    assert exit_code == 2
    capsys.readouterr()

    monkeypatch.setattr(
        "sentinel.cli.load_detectors",
        lambda a: (_VerifiedUrl(), _BadSms(), None, {"url": "loaded", "sms": "loaded", "llama": "disabled (--no-llm)"}),
    )
    exit_code = main(["scan", "Hello there", "--no-llm"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Mode: rules only (analysis failed)" in captured.out


def test_highlight_cues_merges_overlapping():
    from sentinel.cli import highlight_cues

    text = "urgent payment request"
    cues = [
        {"start": 0, "end": 14, "type": "payment_request"},
        {"start": 0, "end": 6, "type": "urgency"},
    ]
    result = highlight_cues(text, cues)
    assert result == "[[urgent payment]] request"


def test_highlight_cues_non_overlapping():
    from sentinel.cli import highlight_cues

    text = "pay bill now"
    cues = [
        {"start": 0, "end": 3, "type": "payment"},
        {"start": 9, "end": 12, "type": "urgency"},
    ]
    result = highlight_cues(text, cues)
    assert result == "[[pay]] bill [[now]]"


def test_default_models_dir_choice(tmp_path, monkeypatch):
    from sentinel.cli import build_parser

    # 1. When ./models exists in current directory, default is "models"
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PS3_MODELS_DIR", raising=False)

    parser = build_parser()
    args = parser.parse_args(["scan", "test message", "--no-llm"])
    assert args.models_dir == "models"

    # 2. When ./models does not exist, default falls back to ~/ps3/models
    models_dir.rmdir()
    parser = build_parser()
    args = parser.parse_args(["scan", "test message", "--no-llm"])
    assert args.models_dir == os.path.expanduser("~/ps3/models")

    # 3. When PS3_MODELS_DIR is explicitly set in env, it wins
    monkeypatch.setenv("PS3_MODELS_DIR", "/custom/models/path")
    parser = build_parser()
    args = parser.parse_args(["scan", "test message", "--no-llm"])
    assert args.models_dir == "/custom/models/path"

