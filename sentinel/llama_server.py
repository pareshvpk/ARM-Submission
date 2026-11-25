"""Resident Llama server process client for PS3 Sentinel.

Manages a long-running sentinel_llama_server C++ subprocess on Linux, caching
the system prompt prefix in the KV cache to accelerate time-to-first-token.
Communicates over stdin/stdout pipes with deadline-bounded request timeouts.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from sentinel.advisor import DEFAULT_LLAMA_THREADS

logger = logging.getLogger(__name__)

# s — cold llama_main spawn measured multiple seconds; 30 leaves headroom for a
# 1.14 GB mmap on a device while still failing fast when the binary is missing.
READY_TIMEOUT_S = 30.0
# s — matches LlamaAdvisor default timeout; decode of 130 tokens at ~12 tok/s
# plus tail prefill fits, so a stall longer than this is a dead server.
REQUEST_TIMEOUT_S = 40.0
# READY follows a complete prefix re-prefill; dead servers fail immediately.
RESYNC_TIMEOUT_S = 10.0
# s — pump/stderr threads end when the process pipes close; this bounds the
# join in _cleanup_locked so a wedged pipe cannot hang shutdown forever.
THREAD_JOIN_TIMEOUT_S = 2.0
READ_CHUNK_BYTES = 65536  # bytes — pipe reads stay well under any text size here


class LlamaServerError(RuntimeError):
    """The resident llama server failed or broke protocol."""


class LlamaServerTimeoutError(LlamaServerError):
    """No response from the resident llama server within the timeout."""


def _is_degraded_text(text: str) -> bool:
    """Return True when an ERR message reports a degraded server."""
    return "server degraded" in text or "prefix prefill failed" in text


def _is_framing_error(error: BaseException) -> bool:
    """Return True when the byte stream is desynchronised, not just failed.

    A per-request ERR line is followed by a resynchronising READY, so the
    server is still healthy and must not be restarted; EOF, timeouts and
    protocol violations mean the stream cannot be trusted. A degraded
    server (``server degraded`` / ``prefix prefill failed``) stays broken
    for every later request, so it is restart-worthy like a framing error;
    a plain ERR such as ``generation failed`` stays a per-request error.
    """
    if isinstance(error, LlamaServerTimeoutError):
        return True
    if _is_degraded_text(str(error)):
        return True
    return not str(error).startswith("llama server error:")


class LlamaServerClient:
    """Owns one resident sentinel_llama_server subprocess."""

    def __init__(
        self,
        server_path: str,
        model_path: str = "",
        tokenizer_path: str = "",
        prefix: str = "",
        threads: int = DEFAULT_LLAMA_THREADS,
        max_new_tokens: int = 130,
        seq_len: int = -1,
        ready_timeout_s: float = READY_TIMEOUT_S,
        request_timeout_s: float = REQUEST_TIMEOUT_S,
        command: list[str] | None = None,
    ) -> None:
        """Store server location and startup parameters.

        Args:
            server_path: path to the sentinel_llama_server binary.
            model_path: path to the Llama .pte file.
            tokenizer_path: path to the tokenizer file.
            prefix: fixed prompt prefix prefilled by the server on startup.
            seq_len: forwarded to the server like llama_main; -1 defers to
                the model context length instead of capping at 128 tokens.
            command: full argv override (used by tests with a fake server).
        """
        self.server_path = server_path
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.prefix = prefix
        self.threads = threads
        self.max_new_tokens = max_new_tokens
        self.seq_len = seq_len
        self.ready_timeout_s = ready_timeout_s
        self.request_timeout_s = request_timeout_s
        self.command = command
        self.prefill_ms = 0
        self._proc: subprocess.Popen[Any] | None = None
        self._lock = threading.Lock()
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._buffer = bytearray()
        self._prefix_file: str | None = None
        self._stderr_lines: list[str] = []
        self._reader: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._needs_restart = False
        self.hash_verified = False

    def __enter__(self) -> LlamaServerClient:
        """Start the server and return this client."""
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        """Close the server subprocess."""
        self.close()

    def build_command(self) -> list[str]:
        """Build the server argv from the configured paths."""
        if self.command:
            return list(self.command)
        if self._prefix_file is None:
            fd, prefix_path = tempfile.mkstemp(suffix=".txt")
            try:
                os.chmod(prefix_path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.prefix)
            self._prefix_file = prefix_path
        cmd = [
            os.path.expanduser(self.server_path),
            "--model_path", self.model_path,
            "--tokenizer_path", self.tokenizer_path,
            "--prefix_file", self._prefix_file,
            "--temperature", "0",
            f"--cpu_threads={self.threads}",
            f"--max_new_tokens={self.max_new_tokens}",
            f"--seq_len={self.seq_len}",
        ]
        return cmd

    def start(self) -> None:
        """Spawn the server and wait for its READY handshake line."""
        with self._lock:
            self._start_locked()

    def _start_locked(self) -> None:
        """Spawn and handshake; caller holds the lock."""
        if self._proc is not None and self._proc.poll() is None and not self._needs_restart:
            return
        self._cleanup_locked()
        if self.model_path and self.tokenizer_path:
            from sentinel.detectors import verify_model_files

            try:
                self.hash_verified = verify_model_files(
                    [self.model_path, self.tokenizer_path], anchor_path=self.model_path
                )
            except Exception as error:
                raise LlamaServerError(f"llama model verification failed: {error}") from error
        cmd = self.build_command()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise LlamaServerError(f"llama server binary not found: {cmd[0]}") from error
        except OSError as error:
            raise LlamaServerError(f"llama server failed to start: {error}") from error
        assert self._proc.stdout is not None
        self._chunks = queue.Queue()
        self._buffer = bytearray()
        self._drain_stderr()
        self._reader = self._reader_thread()
        self._reader.start()
        try:
            line = self._read_line_locked(self.ready_timeout_s)
        except LlamaServerError as error:
            self._cleanup_locked()
            raise error
        if line.startswith("READY"):
            self.prefill_ms = _parse_prefill_ms(line)
            return
        self._cleanup_locked()
        raise LlamaServerError(
            f"llama server handshake failed: {line!r}{self._stderr_context()}"
        )

    def generate(self, tail: str) -> tuple[str, dict[str, Any], float]:
        """Send one prompt tail; return (text, stats, ttft_ms_wall).

        Thread-safe: concurrent calls are serialised, because the server
        holds a single KV cache for the prefilled prefix. A framing error
        restarts the server once and retries this message; only when that
        retry also fails does the caller degrade (to llama_main).
        """
        with self._lock:
            try:
                return self._generate_once_locked(tail)
            except LlamaServerError as error:
                if not _is_framing_error(error):
                    raise
                logger.warning(
                    "llama server framing error, restarting server once before retry: %s", error
                )
                self._cleanup_locked()
                return self._generate_once_locked(tail)

    def _generate_once_locked(self, tail: str) -> tuple[str, dict[str, Any], float]:
        """Run one request; caller holds the lock and may restart on failure."""
        generate_start = time.perf_counter()
        restarted = False
        if self._needs_restart or self._proc is None or self._proc.poll() is not None:
            self._cleanup_locked()
            self._start_locked()
            restarted = True
        assert self._proc is not None and self._proc.stdin is not None
        payload = tail.encode("utf-8")
        try:
            self._proc.stdin.write(b"REQ " + str(len(payload)).encode() + b"\n")
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self._cleanup_locked()
            raise LlamaServerError(f"llama server pipe closed: {error}") from error
        # ttft_ms is wall-clock time from the request write to the first
        # RESP line (first generated output), the same definition the
        # llama_main path uses; a restart above is reported separately.
        # One overall deadline per request: each read below gets only the
        # time left, so a slow trickle cannot reset the clock per chunk.
        request_deadline = time.monotonic() + self.request_timeout_s
        start = time.perf_counter()
        head = self._read_line_locked(max(0.0, request_deadline - time.monotonic()))
        ttft_ms = (time.perf_counter() - start) * 1000.0
        if head.startswith("ERR"):
            self._read_ready_locked(head, deadline=request_deadline)
            raise LlamaServerError(f"llama server error: {head[4:].strip()}")
        if not head.startswith("RESP"):
            self._cleanup_locked()
            raise LlamaServerError(f"llama server protocol error: {head!r}")
        nbytes = _parse_count(head, "RESP")
        body = self._read_exact_locked(
            nbytes, max(0.0, request_deadline - time.monotonic())
        ).decode("utf-8", errors="replace")
        stats_line = self._read_line_locked(max(0.0, request_deadline - time.monotonic()))
        if not stats_line.startswith("STATS"):
            self._cleanup_locked()
            raise LlamaServerError(f"llama server protocol error: {stats_line!r}")
        self._read_ready_locked(stats_line, deadline=request_deadline)
        try:
            stats = json.loads(stats_line[5:].strip())
        except json.JSONDecodeError as error:
            raise LlamaServerError(f"llama server error: stats not JSON: {error}") from error
        if not isinstance(stats, dict):
            raise LlamaServerError("llama server error: stats are not an object")
        # A restart inside generate() costs a full handshake; record it in
        # the returned stats so the timing breakdown shows it instead of
        # reporting only the tail decode as ttft.
        restart_ms = (time.perf_counter() - generate_start) * 1000.0 if restarted else 0.0
        stats["restart_ms"] = round(restart_ms, 3)
        return body, stats, ttft_ms

    def close(self) -> None:
        """Stop the server subprocess and remove the prefix file."""
        with self._lock:
            self._cleanup_locked()

    # Internal helpers -------------------------------------------------

    def _cleanup_locked(self) -> None:
        """Kill the subprocess if alive and drop protocol state."""
        proc = self._proc
        if proc is not None:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            self._proc = None
        # The pump and stderr threads block on the old pipes; joining them
        # here stops a restart from leaving the previous process's threads
        # running alongside the new process's.
        for thread in (self._reader, self._stderr_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
        self._reader = None
        self._stderr_thread = None
        self._needs_restart = False
        if self._prefix_file is not None and os.path.exists(self._prefix_file):
            try:
                os.remove(self._prefix_file)
            except OSError:
                pass
            self._prefix_file = None

    def _stderr_context(self) -> str:
        """Return the last stderr lines for error messages, or empty string."""
        if not self._stderr_lines:
            return ""
        return " stderr: " + " | ".join(self._stderr_lines[-3:])

    def _drain_stderr(self) -> None:
        """Drain server stderr so ET_LOG lines cannot block the server."""

        def drain() -> None:
            assert self._proc is not None and self._proc.stderr is not None
            for raw in self._proc.stderr:
                self._stderr_lines.append(raw.decode("utf-8", errors="replace").strip())
                if len(self._stderr_lines) > 200:
                    self._stderr_lines.pop(0)

        self._stderr_thread = threading.Thread(target=drain, daemon=True)
        self._stderr_thread.start()

    def _reader_thread(self) -> threading.Thread:
        """Pump server stdout bytes into the chunk queue captured at start."""
        chunks: queue.Queue[bytes | None] = self._chunks

        def pump() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            stream = self._proc.stdout
            read = getattr(stream, "read1", stream.read)
            try:
                while True:
                    chunk = read(READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    chunks.put(chunk)
            except OSError:
                pass
            chunks.put(None)

        return threading.Thread(target=pump, daemon=True)

    def _fill_locked(self, timeout_s: float) -> None:
        """Pull one chunk into the buffer, raising on timeout or EOF."""
        try:
            chunk = self._chunks.get(timeout=timeout_s)
        except queue.Empty:
            self._cleanup_locked()
            raise LlamaServerTimeoutError(f"llama server timed out after {timeout_s:.1f}s")
        if chunk is None:
            raise LlamaServerError(f"llama server exited unexpectedly{self._stderr_context()}")
        self._buffer.extend(chunk)

    def _read_ready_locked(self, context: str, deadline: float | None = None) -> str:
        """Read until READY after an ERR or STATS line, with RESYNC_TIMEOUT_S.

        READY follows a full prefix re-prefill, so a live but slow server
        is given RESYNC_TIMEOUT_S; a dead one shows up as EOF at once.
        When a request deadline is given, the wait is capped at the
        earlier of RESYNC_TIMEOUT_S and that deadline, so the resync
        cannot exceed the per-request timeout while holding the lock.
        Extra ERR lines (a failed re-prefill after an ERR) are consumed
        until the READY. A consumed degraded ERR (``prefix prefill
        failed`` / ``server degraded``) after a successful STATS means the
        server will only answer degraded errors from now on, so remember
        it and restart before the next request instead of waiting for a
        degraded reply.
        """
        if self._proc is not None and self._proc.poll() is not None:
            self._cleanup_locked()
            raise LlamaServerError(
                f"llama server protocol error: server exited after {context!r}"
                f"{self._stderr_context()}"
            )
        resync_deadline = time.monotonic() + RESYNC_TIMEOUT_S
        if deadline is not None:
            resync_deadline = min(resync_deadline, deadline)
        while True:
            line = self._read_line_locked(max(0.0, resync_deadline - time.monotonic()))
            if line.startswith("READY"):
                return line
            if line.startswith("ERR"):
                if _is_degraded_text(line):
                    self._needs_restart = True
                continue
            self._cleanup_locked()
            raise LlamaServerError(
                f"llama server protocol error: expected READY after {context!r}, got {line!r}"
            )

    def _read_line_locked(self, timeout_s: float) -> str:
        """Read one newline-terminated line with one overall timeout."""
        deadline = time.monotonic() + timeout_s
        while True:
            idx = self._buffer.find(b"\n")
            if idx >= 0:
                raw = bytes(self._buffer[:idx])
                del self._buffer[: idx + 1]
                return raw.decode("utf-8", errors="replace").rstrip("\r")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._cleanup_locked()
                raise LlamaServerTimeoutError(f"llama server timed out after {timeout_s:.1f}s")
            self._fill_locked(remaining)

    def _read_exact_locked(self, nbytes: int, timeout_s: float) -> bytes:
        """Read exactly nbytes bytes, which may contain newlines."""
        deadline = time.monotonic() + timeout_s
        while len(self._buffer) < nbytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._cleanup_locked()
                raise LlamaServerTimeoutError(f"llama server timed out after {timeout_s:.1f}s")
            self._fill_locked(remaining)
        raw = bytes(self._buffer[:nbytes])
        del self._buffer[:nbytes]
        return raw


def _parse_prefill_ms(line: str) -> int:
    """Extract prefill_ms=<n> from a READY line, or 0 when absent."""
    for part in line.split():
        if part.startswith("prefill_ms="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return 0
    return 0


def _parse_count(line: str, prefix: str) -> int:
    """Parse the byte count from a '<prefix> <nbytes>' line."""
    try:
        count = int(line[len(prefix):].strip())
    except ValueError as error:
        raise LlamaServerError(f"bad byte count in line: {line!r}") from error
    if count < 0:
        raise LlamaServerError(f"negative byte count in line: {line!r}")
    return count


def is_server_available(server_path: str | None) -> bool:
    """Return True when a server binary path is configured.

    Args:
        server_path: Path to the sentinel_llama_server executable, or None.

    Returns:
        True if path is non-empty and points to an existing file.
    """
    return bool(server_path) and os.path.isfile(os.path.expanduser(server_path or ""))


__all__ = [
    "LlamaServerClient",
    "LlamaServerError",
    "LlamaServerTimeoutError",
    "is_server_available",
]
