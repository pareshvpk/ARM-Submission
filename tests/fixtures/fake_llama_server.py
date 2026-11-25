"""Fake resident llama server speaking the sentinel_llama_server protocol.

Usage: python fake_llama_server.py [--startup-delay S] [--response-delay S]
       [--resync-delay S] [--error-first] [--die-immediately] [--hang] [--bad-stats]
       [--degraded-after N] [--generation-failed]
"""
from __future__ import annotations

import json
import sys
import time

STATS = {
    "prompt_tokens": 5,
    "generated_tokens": 3,
    "inference_start_ms": 1000,
    "first_token_ms": 1010,
    "inference_end_ms": 1200,
    "SCALING_FACTOR_UNITS_PER_SECOND": 1000,
}


def _line(text: str) -> None:
    """Write one protocol line and flush."""
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _ready() -> None:
    """Report the prefetched prefix as ready."""
    _line("READY prefill_ms=1")


def _ready_with_delay(delay_s: float) -> None:
    """Report resync READY after a simulated prefix re-prefill delay."""
    if delay_s > 0:
        time.sleep(delay_s)
    _ready()


def _read_line() -> str | None:
    """Read one header line, or None on EOF."""
    raw = sys.stdin.buffer.readline()
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace").rstrip("\r\n")


def _read_exact(nbytes: int) -> str | None:
    """Read exactly nbytes bytes, which may contain newlines."""
    data = b""
    while len(data) < nbytes:
        chunk = sys.stdin.buffer.read(nbytes - len(data))
        if not chunk:
            return None
        data += chunk
    return data.decode("utf-8", errors="replace")


def main(argv: list[str]) -> int:
    """Run the fake protocol loop."""
    startup_delay = _flag_value(argv, "--startup-delay", 0.0)
    response_delay = _flag_value(argv, "--response-delay", 0.0)
    resync_delay = _flag_value(argv, "--resync-delay", 0.0)
    degraded_after = _int_flag_value(argv, "--degraded-after", None)
    if "--die-immediately" in argv:
        return 3
    if "--hang" in argv:
        while True:
            time.sleep(60)
    if startup_delay > 0:
        time.sleep(startup_delay)
    _ready()
    error_pending = "--error-first" in argv
    bad_stats_pending = "--bad-stats" in argv
    generation_failed_pending = "--generation-failed" in argv
    degraded = False
    successes = 0
    if degraded_after is not None and degraded_after <= 0:
        degraded = True
    while True:
        head = _read_line()
        if head is None:
            return 0
        if not head.startswith("REQ "):
            _line("ERR bad request")
            if error_pending:
                error_pending = False
            _ready_with_delay(resync_delay)
            continue
        try:
            nbytes = int(head[4:].strip())
        except ValueError:
            _line("ERR bad byte count")
            _ready_with_delay(resync_delay)
            continue
        tail = _read_exact(nbytes)
        if tail is None:
            return 0
        if response_delay > 0:
            time.sleep(response_delay)
        if degraded:
            _line("ERR server degraded: prefix prefill failed")
            _ready_with_delay(resync_delay)
            continue
        if error_pending:
            error_pending = False
            _line("ERR injected fake failure")
            _ready_with_delay(resync_delay)
            continue
        if generation_failed_pending:
            generation_failed_pending = False
            _line("ERR generation failed")
            _ready_with_delay(resync_delay)
            continue
        body = ("FAKE:" + tail).encode("utf-8")
        sys.stdout.buffer.write(b"RESP " + str(len(body)).encode() + b"\n")
        sys.stdout.buffer.write(body)
        if bad_stats_pending:
            bad_stats_pending = False
            _line("STATS not-json")
        else:
            _line("STATS " + json.dumps(STATS))
        successes += 1
        if degraded_after is not None and not degraded and successes >= degraded_after:
            degraded = True
            _line("ERR prefix prefill failed")
            _ready_with_delay(resync_delay)
        else:
            _ready_with_delay(resync_delay)
    return 0


def _flag_value(argv: list[str], flag: str, default: float) -> float:
    """Parse a '--flag SECONDS' float option."""
    if flag in argv:
        try:
            return float(argv[argv.index(flag) + 1])
        except (IndexError, ValueError):
            return default
    return default


def _int_flag_value(argv: list[str], flag: str, default: int | None) -> int | None:
    """Parse a '--flag N' int option."""
    if flag in argv:
        try:
            return int(argv[argv.index(flag) + 1])
        except (IndexError, ValueError):
            return default
    return default


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
