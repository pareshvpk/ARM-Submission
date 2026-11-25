"""Tests for the resident llama server client and advisor fallback."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sentinel.advisor import FIXED_PROMPT_PREFIX, LlamaAdvisor, build_prompt, split_prompt
from sentinel.fusion import Evidence
from sentinel.llama_server import (
    LlamaServerClient,
    LlamaServerError,
    LlamaServerTimeoutError,
)

ROOT = Path(__file__).resolve().parents[1]
FAKE_SERVER = ROOT / "tests" / "fixtures" / "fake_llama_server.py"


def _client(*fake_args: str, **kwargs) -> LlamaServerClient:
    """Build a client running the fake server."""
    kwargs.setdefault("ready_timeout_s", 5.0)
    kwargs.setdefault("request_timeout_s", 5.0)
    return LlamaServerClient(
        server_path="unused", command=[sys.executable, str(FAKE_SERVER), *fake_args], **kwargs
    )


def _mock_llama_main(monkeypatch: pytest.MonkeyPatch, text: str = "mocked llama_main advice") -> None:
    """Replace subprocess.run with a canned llama_main success."""

    def fake_run(*args, **kwargs):
        assert kwargs.get("check", False)
        stats = {"prompt_tokens": 10, "first_token_ms": 1100, "inference_start_ms": 1000}
        stdout = f"{text}\nPyTorchObserver {json.dumps(stats)}\n"
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout)

    monkeypatch.setattr("subprocess.run", fake_run)


def test_ready_handshake():
    """The client waits for the READY line and records prefill_ms."""
    with _client() as client:
        assert client.prefill_ms >= 0
        text, stats, ttft_ms = client.generate("hello")
        assert text == "FAKE:hello"
        assert stats["prompt_tokens"] == 5
        assert ttft_ms >= 0


def test_roundtrip_with_newlines_and_unicode():
    """Length-prefixed framing keeps newlines and multibyte UTF-8 intact."""
    tail = "first line\nsecond ₹ line with <<<SMS_BEGIN>>> marker"
    with _client() as client:
        text, stats, ttft_ms = client.generate(tail)
        assert text == "FAKE:" + tail


def test_error_line_then_resync():
    """An ERR line raises, and the following READY resyncs the server."""
    with _client("--error-first") as client:
        with pytest.raises(LlamaServerError, match="injected"):
            client.generate("boom")
        text, _, _ = client.generate("again")
        assert text == "FAKE:again"


def test_delayed_ready_after_stats_accepted_without_restart(monkeypatch: pytest.MonkeyPatch):
    """A READY delayed past one prefill is accepted, not a framing error.

    Production RESYNC_TIMEOUT_S covers a Arm Linux prefix re-prefill (~1.95 s
    warm, 4.5 s cold); the test patches it down so the delays stay short.
    """
    monkeypatch.setattr("sentinel.llama_server.RESYNC_TIMEOUT_S", 0.5)
    with _client("--resync-delay", "0.2") as client:
        text, stats, _ = client.generate("delayed")
        assert text == "FAKE:delayed"
        assert stats["restart_ms"] == 0.0
    with _client("--resync-delay", "0.8") as client:
        with pytest.raises(LlamaServerTimeoutError):
            client.generate("too-slow")


def test_resync_bounded_by_request_deadline(monkeypatch: pytest.MonkeyPatch):
    """A slow resync READY must not outrun the per-request deadline.

    RESYNC_TIMEOUT_S is large, so without the deadline cap the client
    would wait out the full fake-server resync delay (and succeed)
    instead of timing out within the request budget.
    """
    import time

    monkeypatch.setattr("sentinel.llama_server.RESYNC_TIMEOUT_S", 10.0)
    started = time.monotonic()
    with _client("--resync-delay", "3", request_timeout_s=0.5) as client:
        with pytest.raises(LlamaServerTimeoutError):
            client.generate("slow-resync")
    elapsed = time.monotonic() - started
    assert elapsed < 2.5


def test_bad_stats_is_per_request_error_without_restart():
    """Malformed STATS after READY raises without restarting the server."""
    with _client("--bad-stats") as client:
        assert client._proc is not None
        pid_before = client._proc.pid
        with pytest.raises(LlamaServerError, match=r"^llama server error: stats not JSON"):
            client.generate("first")
        assert client._proc is not None
        assert client._proc.pid == pid_before
        text, stats, _ = client.generate("again")
        assert text == "FAKE:again"
        assert stats["restart_ms"] == 0.0


def test_degraded_after_prefill_failure_restarts_and_next_request_succeeds():
    """A degraded re-prefill after STATS restarts the server before the next request."""
    with _client("--degraded-after", "1") as client:
        text, stats, _ = client.generate("first")
        assert text == "FAKE:first"
        assert stats["restart_ms"] == 0.0
        assert client._proc is not None
        pid_before = client._proc.pid
        text, stats, _ = client.generate("second")
        assert text == "FAKE:second"
        assert stats["restart_ms"] > 0.0
        assert client._proc is not None
        assert client._proc.pid != pid_before
        text, _, _ = client.generate("third")
        assert text == "FAKE:third"


def test_generation_failed_does_not_restart():
    """A plain ERR generation failed is a per-request error without restart."""
    with _client("--generation-failed") as client:
        assert client._proc is not None
        pid_before = client._proc.pid
        with pytest.raises(LlamaServerError, match="generation failed"):
            client.generate("boom")
        assert client._proc is not None
        assert client._proc.pid == pid_before
        text, stats, _ = client.generate("again")
        assert text == "FAKE:again"
        assert stats["restart_ms"] == 0.0
        assert client._proc is not None
        assert client._proc.pid == pid_before


def test_startup_timeout():
    """A server that never sends READY makes start raise a timeout."""
    client = _client("--startup-delay", "5", ready_timeout_s=0.3)
    with pytest.raises(LlamaServerTimeoutError):
        client.start()
    client.close()


def test_request_timeout():
    """A server slow to answer RESP makes generate raise a timeout."""
    with _client("--response-delay", "5", request_timeout_s=0.3) as client:
        with pytest.raises(LlamaServerTimeoutError):
            client.generate("slow")


def test_read_line_deadline_not_per_chunk():
    """A trickle of chunks each under the timeout still times out overall."""
    import queue
    import threading
    import time

    client = LlamaServerClient(
        server_path="unused",
        command=[sys.executable, str(FAKE_SERVER)],
        ready_timeout_s=5.0,
        request_timeout_s=0.5,
    )
    client._buffer = bytearray()
    client._chunks = queue.Queue()

    def trickle() -> None:
        time.sleep(0.2)
        client._chunks.put(b"RE")
        time.sleep(0.2)
        client._chunks.put(b"SP ")
        time.sleep(0.2)
        client._chunks.put(b"5\n")

    thread = threading.Thread(target=trickle, daemon=True)
    thread.start()
    with pytest.raises(LlamaServerTimeoutError):
        client._read_line_locked(0.5)
    thread.join(timeout=2)


def test_read_exact_deadline_not_per_chunk():
    """Reading a body in small chunks cannot reset the overall deadline."""
    import queue
    import threading
    import time

    client = LlamaServerClient(
        server_path="unused",
        command=[sys.executable, str(FAKE_SERVER)],
        ready_timeout_s=5.0,
        request_timeout_s=0.5,
    )
    client._buffer = bytearray()
    client._chunks = queue.Queue()

    def trickle() -> None:
        for _ in range(5):
            time.sleep(0.2)
            client._chunks.put(b"x")

    thread = threading.Thread(target=trickle, daemon=True)
    thread.start()
    with pytest.raises(LlamaServerTimeoutError):
        client._read_exact_locked(5, 0.5)
    thread.join(timeout=2)


def test_process_death_falls_back_to_llama_main(monkeypatch: pytest.MonkeyPatch):
    """A dead resident server makes the advisor fall back to llama_main."""
    _mock_llama_main(monkeypatch)
    advisor = LlamaAdvisor(
        llama_main="llama_main", model_path="llama.pte", tokenizer_path="tokenizer.bin",
        llama_server="ignored-because-client-mocked",
    )
    fake_client = _client("--die-immediately", ready_timeout_s=0.5)
    advisor._server_client = fake_client
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    text, stats = advisor.generate("your account is blocked, click here", ev)
    assert text == "mocked llama_main advice"
    assert stats["prompt_path"] == "llama_main"
    assert stats["ttft_ms"] >= 0
    advisor.close()


def test_error_line_falls_back_to_llama_main(monkeypatch: pytest.MonkeyPatch):
    """A per-message ERR makes the advisor fall back for that message."""
    _mock_llama_main(monkeypatch)
    advisor = LlamaAdvisor(
        llama_main="llama_main", model_path="llama.pte", tokenizer_path="tokenizer.bin",
        llama_server="ignored",
    )
    advisor._server_client = _client("--error-first")
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    text, stats = advisor.generate("your account is blocked", ev)
    assert text == "mocked llama_main advice"
    assert stats["prompt_path"] == "llama_main"
    advisor.close()


def test_advisor_uses_resident_server_when_healthy(monkeypatch: pytest.MonkeyPatch):
    """A healthy resident server serves the tail; llama_main is untouched."""

    def fail(*args, **kwargs):
        raise AssertionError("llama_main must not run")

    monkeypatch.setattr("subprocess.run", fail)
    advisor = LlamaAdvisor(
        llama_main="llama_main", model_path="llama.pte", tokenizer_path="tokenizer.bin",
        llama_server="ignored",
    )
    advisor._server_client = _client()
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    text, stats = advisor.generate("your account is blocked", ev)
    assert text.startswith("FAKE:")
    assert stats["prompt_path"] == "resident_prefix"
    assert stats["ttft_ms"] >= 0
    advisor.close()


def test_split_prompt_invariant():
    """split_prompt partitions build_prompt output without losing bytes."""
    ev = Evidence(label="scam", risk=0.9, level="high", threshold=0.7)
    full = build_prompt("hello", ev)
    prefix, tail = split_prompt(full)
    assert prefix == FIXED_PROMPT_PREFIX
    assert prefix + tail == full
    assert prefix.startswith("<|begin_of_text|>")


def test_prefix_matches_kotlin():
    """FIXED_PROMPT_PREFIX must equal the Kotlin FIXED_PROMPT_PREFIX construction."""
    import codecs

    kt = ROOT / "android/app/src/main/java/org/ps3/sentinel/core/Advisor.kt"
    source = kt.read_text(encoding="utf-8")
    block = source.split("const val FIXED_PROMPT_PREFIX: String =")[1].split("\n\n")[0]
    literals = []
    for raw in _kotlin_strings(block):
        literals.append(codecs.decode(raw, "unicode_escape"))
    assert "SYSTEM_PROMPT" in block
    assert literals[0] + _kotlin_system_prompt(source) + literals[-1] == FIXED_PROMPT_PREFIX


def _kotlin_strings(block: str) -> list[str]:
    """Extract Kotlin double-quoted literals from a code block."""
    import re

    return re.findall(r'"((?:[^"\\]|\\.)*)"', block)


def _kotlin_system_prompt(source: str) -> str:
    """Reconstruct the Kotlin SYSTEM_PROMPT value from its literals."""
    block = source.split("const val SYSTEM_PROMPT: String =")[1].split("\n\n")[0]
    import codecs

    return "".join(codecs.decode(raw, "unicode_escape") for raw in _kotlin_strings(block))


def _hash(path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_advisor_refuses_tampered_llama_model(tmp_path):
    model = tmp_path / "llama.pte"
    model.write_bytes(b"tampered")
    tok = tmp_path / "tokenizer.model"
    tok.write_bytes(b"tok")
    lines = [
        f"{'0' * 64}  llama.pte",
        f"{_hash(tok)}  tokenizer.model",
    ]
    (tmp_path / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        LlamaAdvisor("llama_main", str(model), str(tok))


def test_advisor_refuses_tampered_llama_tokenizer(tmp_path):
    model = tmp_path / "llama.pte"
    model.write_bytes(b"stub model")
    tok = tmp_path / "tokenizer.model"
    tok.write_bytes(b"tampered tok")
    lines = [
        f"{_hash(model)}  llama.pte",
        f"{'0' * 64}  tokenizer.model",
    ]
    (tmp_path / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch for tokenizer.model"):
        LlamaAdvisor("llama_main", str(model), str(tok))


def test_advisor_no_manifest_is_unverified_not_refused(tmp_path, capsys):
    model = tmp_path / "llama.pte"
    model.write_bytes(b"stub model")
    tok = tmp_path / "tokenizer.model"
    tok.write_bytes(b"tok")
    advisor = LlamaAdvisor("llama_main", str(model), str(tok))
    assert advisor.hash_verified is False
    captured = capsys.readouterr()
    assert "unverified" in captured.err


def test_llama_server_client_refuses_tampered_before_start(tmp_path):
    model = tmp_path / "llama.pte"
    model.write_bytes(b"tampered")
    tok = tmp_path / "tokenizer.model"
    tok.write_bytes(b"tok")
    lines = [
        f"{'0' * 64}  llama.pte",
        f"{_hash(tok)}  tokenizer.model",
    ]
    (tmp_path / "models.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    client = LlamaServerClient(
        server_path="unused",
        model_path=str(model),
        tokenizer_path=str(tok),
        command=[sys.executable, str(FAKE_SERVER)],
        ready_timeout_s=5.0,
        request_timeout_s=5.0,
    )
    with pytest.raises(LlamaServerError, match="llama model verification failed"):
        client.start()
    assert client._proc is None
