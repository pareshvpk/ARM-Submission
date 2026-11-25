"""Command-line interface for PS3 Sentinel on Arm Linux.

Provides `sentinel scan` for single message strings, batch files, or standard
input streams, producing formatted terminal reports or structured JSON output.
Coordinates model loading, hardware acceleration logging, and degraded mode detection.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sentinel.cpu_features import log_once as _log_cpu_accel_once
from sentinel.highlight import _merge_overlapping, _valid_spans, format_highlighted

# Advisor, detectors and pipeline import the shared rules at import time, so
# they are loaded lazily inside functions. That lets `python -m sentinel
# --help` print help even when rules.json is missing or malformed.
DEFAULT_LLAMA_THREADS = 3

# Single source for Linux defaults and phone file names. They may differ by role.
MODEL_FILES_PATH = Path(__file__).resolve().parent / "data" / "model_files.json"

# Input caps (S-11): each message capped at 2000 characters (same as the
# Android share path) and each run at 10000 messages.
MAX_SMS_TEXT_CHARS = 2000
MAX_MESSAGES = 10000

# E7: standing uncertainty notice printed under every human-readable verdict.
UNCERTAINTY_NOTICE = "Sentinel can be wrong. When unsure, check with the official app or website."

REQUIRED_MODEL_ROLES = (
    "url_model",
    "url_vocab",
    "sms_model",
    "sms_id_map",
    "sms_vocab",
    "sms_tokenizer_dir",
    "llama_model",
    "llama_tokenizer",
)


def load_model_files(path: Path = MODEL_FILES_PATH) -> dict[str, dict[str, str]]:
    """Load Linux and phone file names per model role.

    Returns:
        Mapping of role to its ``phone`` and ``linux`` names from the file.
    """
    if not path.is_file():
        raise RuntimeError(f"Model files manifest not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Model files manifest {path} is not valid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise RuntimeError(f"Model files manifest {path} must be an object")
    if raw.get("schema_version") != 1:
        raise RuntimeError(f"Model files manifest {path} has unsupported schema_version")
    files = raw.get("files")
    if not isinstance(files, dict):
        raise RuntimeError(f"Model files manifest {path} must have a files object")
    result: dict[str, dict[str, str]] = {}
    for role in REQUIRED_MODEL_ROLES:
        entry = files.get(role)
        if not isinstance(entry, dict):
            raise RuntimeError(f"Model files manifest {path} is missing role {role}")
        phone = entry.get("phone")
        linux = entry.get("linux")
        if not isinstance(phone, str) or not phone or not isinstance(linux, str) or not linux:
            raise RuntimeError(f"Model files manifest {path}: role {role} needs phone/linux strings")
        result[role] = {"phone": phone, "linux": linux}
    return result


def linux_default_name(role: str) -> str:
    """Return the Linux default file name for a model role."""
    return load_model_files()[role]["linux"]


def phone_file_name(role: str) -> str:
    """Return the phone file name for a model role."""
    return load_model_files()[role]["phone"]


def _resolve_linux_path(models_dir: str, role: str) -> str:
    """Join a model role default name onto the models directory."""
    return os.path.join(models_dir, linux_default_name(role))


def highlight_cues(text: str, cues: list[dict[str, Any]]) -> str:
    """Highlight cue spans by wrapping them with [[ and ]] (legacy format).

    Kept for the JSON output, which must stay unchanged. Human-readable
    output uses format_highlighted from sentinel.highlight instead.
    """
    if not cues or not text:
        return text

    merged = _merge_overlapping(_valid_spans(text, cues))
    res = text
    for start, end, _ in reversed(merged):
        res = res[:start] + "[[" + res[start:end] + "]]" + res[end:]
    return res


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the sentinel CLI."""
    parser = argparse.ArgumentParser(prog="sentinel", description="Sentinel on-device scam and phishing detector")
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="Scan a message or file")
    scan_parser.add_argument("text", nargs="?", default=None, help="SMS message text to scan")
    scan_parser.add_argument("--file", "-f", default=None, help="File containing one message per line")
    scan_parser.add_argument("--sender", default=None, help="Sender of the message, for the sender-mismatch cue")
    scan_parser.add_argument("--no-llm", action="store_true", help="Disable Llama advisor and use template fallback")
    scan_parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    scan_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any detector (sms/url) is unavailable; default exit 0 for a scan that ran",
    )
    scan_parser.add_argument(
        "--text",
        dest="text_option",
        default=None,
        help="SMS message text to scan (alias for the positional text argument)",
    )
    scan_parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colour risky words: auto (only on a terminal), always, or never",
    )

    models_fallback = "models" if os.path.isdir("models") else os.path.expanduser("~/ps3/models")
    default_models_dir = os.getenv("PS3_MODELS_DIR") or models_fallback
    default_llama_main = os.getenv(
        "PS3_LLAMA_MAIN",
        os.path.expanduser("~/ps3/executorch/cmake-out/examples/models/llama/llama_main"),
    )

    scan_parser.add_argument("--models-dir", default=default_models_dir, help="Directory containing model files")
    scan_parser.add_argument("--llama-main", default=default_llama_main, help="Path to llama_main binary")
    scan_parser.add_argument(
        "--llama-server",
        default=os.getenv("PS3_LLAMA_SERVER", ""),
        help="Path to sentinel_llama_server binary (optional resident server)",
    )
    scan_parser.add_argument(
        "--url-model",
        default=None,
        help="Path to url_v2/url_cnn_v2.pte (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--url-vocab",
        default=None,
        help="Path to url_v2/vocab.json (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--sms-model",
        default=None,
        help="Path to sms_v6ml/sms_int8.pte (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--sms-tokenizer",
        default=None,
        help="Path to sms_v6ml/tokenizer directory (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--llama-model",
        default=None,
        help="Path to llama32_1b/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--llama-tokenizer",
        default=None,
        help="Path to llama32_1b/tokenizer.model (relative to --models-dir by default)",
    )
    scan_parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_LLAMA_THREADS,
        help="CPU threads for Llama inference (default: %(default)s)",
    )

    return parser


def _load_url_detector(models_dir: str, args: argparse.Namespace) -> tuple[Any, str]:
    """Load the URL detector, or None with a status string on failure."""
    from sentinel.detectors import UrlDetector

    url_pte = getattr(args, "url_model", None) or _resolve_linux_path(models_dir, "url_model")
    url_vocab = getattr(args, "url_vocab", None) or _resolve_linux_path(models_dir, "url_vocab")
    missing = [p for p in (url_pte, url_vocab) if not os.path.isfile(p)]
    if missing:
        status = f"missing: {', '.join(missing)}"
        print(f"warning: url detector unavailable (URL model unavailable): {status}", file=sys.stderr)
        return None, status
    try:
        return UrlDetector(url_pte, url_vocab), "loaded"
    except Exception as error:
        print(f"warning: url detector unavailable (URL model unavailable): {type(error).__name__}: {error}", file=sys.stderr)
        return None, f"{type(error).__name__}: {error}"


def _load_sms_detector(models_dir: str, args: argparse.Namespace) -> tuple[Any, str]:
    """Load the SMS detector, or None with a status string on failure."""
    from sentinel.detectors import SmsDetector

    sms_pte = getattr(args, "sms_model", None) or _resolve_linux_path(models_dir, "sms_model")
    sms_tokenizer = getattr(args, "sms_tokenizer", None) or _resolve_linux_path(models_dir, "sms_tokenizer_dir")
    sms_id_map = getattr(args, "sms_id_map", None) or _resolve_linux_path(models_dir, "sms_id_map")
    missing: list[str] = []
    if not os.path.isfile(sms_pte):
        missing.append(sms_pte)
    if not os.path.isfile(sms_id_map):
        missing.append(sms_id_map)
    if not (os.path.isdir(sms_tokenizer) or os.path.isfile(sms_tokenizer)):
        missing.append(sms_tokenizer)
    if missing:
        status = f"missing: {', '.join(missing)}"
        print(f"warning: sms detector unavailable (SMS model unavailable): {status}", file=sys.stderr)
        return None, status
    try:
        return SmsDetector(sms_pte, sms_tokenizer, id_map_path=sms_id_map), "loaded"
    except Exception as error:
        print(f"warning: sms detector unavailable (SMS model unavailable): {type(error).__name__}: {error}", file=sys.stderr)
        return None, f"{type(error).__name__}: {error}"


def _load_advisor(models_dir: str, args: argparse.Namespace) -> tuple[Any, str]:
    """Load the Llama advisor, or None with a status string on failure."""
    from sentinel.advisor import LlamaAdvisor

    if getattr(args, "no_llm", False):
        return None, "disabled (--no-llm)"
    llama_main = os.path.expanduser(getattr(args, "llama_main", ""))
    llama_pte = getattr(args, "llama_model", None) or _resolve_linux_path(models_dir, "llama_model")
    llama_tok = getattr(args, "llama_tokenizer", None) or _resolve_linux_path(models_dir, "llama_tokenizer")
    llama_server = getattr(args, "llama_server", "") or None
    if llama_server is not None and not os.path.isfile(os.path.expanduser(llama_server)):
        print(f"warning: llama-server not found ({llama_server}); using llama_main path", file=sys.stderr)
        llama_server = None
    missing = [p for p in (llama_main, llama_pte, llama_tok) if not os.path.isfile(p)]
    if missing:
        return None, f"missing: {', '.join(missing)}"
    try:
        threads = getattr(args, "threads", DEFAULT_LLAMA_THREADS)
        return LlamaAdvisor(llama_main, llama_pte, llama_tok, threads=threads, llama_server=llama_server), "loaded"
    except Exception as error:
        print(f"warning: advisor not loaded: {error!r}", file=sys.stderr)
        return None, f"{type(error).__name__}: {error}"


def load_detectors(args: argparse.Namespace) -> tuple[Any, Any, Any, dict[str, str]]:
    """Load detectors with a per-detector status for the JSON output.

    Returns:
        The url detector, sms detector, advisor, and status mapping whose
        values are ``loaded`` or the failure reason.
    """
    models_dir = os.path.expanduser(args.models_dir)
    url_det, url_status = _load_url_detector(models_dir, args)
    sms_det, sms_status = _load_sms_detector(models_dir, args)
    advisor, llama_status = _load_advisor(models_dir, args)
    status = {"url": url_status, "sms": sms_status, "llama": llama_status}
    return url_det, sms_det, advisor, status


def _degraded_detectors(
    url_det: Any, sms_det: Any, advisor: Any = None, llama_status: str | None = None
) -> list[str]:
    """Return the unavailable detector ids (``url``/``sms``/``llama``).

    A loaded detector whose model files were not hash-verified (no
    ``models.sha256`` manifest) counts as degraded. A refused or missing
    Llama advisor (anything but ``disabled (--no-llm)``) also counts as
    degraded, as does a loaded advisor that was not hash-verified.
    """
    degraded: list[str] = []
    if url_det is None or getattr(url_det, "hash_verified", True) is False:
        degraded.append("url")
    if sms_det is None or getattr(sms_det, "hash_verified", True) is False:
        degraded.append("sms")
    if llama_status is not None:
        if not str(llama_status).startswith("disabled") and llama_status != "not loaded":
            if advisor is None or getattr(advisor, "hash_verified", True) is False:
                degraded.append("llama")
    elif advisor is not None and getattr(advisor, "hash_verified", True) is False:
        degraded.append("llama")
    return degraded


def _fallback_status(url_det: Any, sms_det: Any, advisor: Any) -> dict[str, str]:
    """Derive a status mapping for a mocked three-value load result."""
    return {
        "url": "loaded" if url_det is not None else "not loaded",
        "sms": "loaded" if sms_det is not None else "not loaded",
        "llama": "loaded" if advisor is not None else "not loaded",
    }


def _use_color(choice: str) -> bool:
    """Resolve a --color choice to a boolean.

    ``auto`` colours only when stdout is a terminal, so piped output and
    logs stay plain and can be grepped without ANSI codes.
    """
    if choice == "always":
        return True
    if choice == "never":
        return False
    return sys.stdout.isatty()


def format_human_output(
    text: str,
    result: dict[str, Any],
    use_color: bool = False,
    degraded: list[str] | None = None,
) -> str:
    """Format a scan result as human-readable text.

    Args:
        text: Original message text.
        result: Pipeline result dictionary from analyse().
        use_color: Whether to highlight cues with ANSI colours.
        degraded: Optional list of degraded detector role names.

    Returns:
        Multi-line formatted summary string including risk, cues, URLs, advice, and notice.
    """
    ev = result["evidence"]
    label = ev.get("label", "unknown")
    level = ev.get("level", "low").upper()
    risk = ev.get("risk", 0.0)
    cues = ev.get("cue_spans", [])
    highlighted = format_highlighted(text, cues, use_color=use_color)
    urls = ev.get("urls", [])
    advice = result.get("advice", "")

    if degraded is None:
        degraded = result.get("degraded", [])
    effective_degraded = list(degraded)
    indicators = ev.get("indicators", [])
    if "sms_model_error" in indicators and "sms" not in effective_degraded:
        effective_degraded.append("sms")
    if "url_model_error" in indicators and "url" not in effective_degraded:
        effective_degraded.append("url")
    if (
        "analysis_error" in indicators
        and "analysis" not in effective_degraded
        and "sms_model_error" not in indicators
        and "url_model_error" not in indicators
    ):
        effective_degraded.append("analysis")

    lines = [
        f"Message: {highlighted}",
        f"Risk Level: {level}",
        f"Label: {label}",
        f"Risk Score: {risk:.2f}",
    ]
    if result.get("is_plain_promotion"):
        lines.append("Kind: promotion (no action needed)")
    if "sms" in effective_degraded:
        lines.append("Mode: rules only (SMS model unavailable)")
    if "url" in effective_degraded:
        lines.append("Mode: rules only (URL model unavailable)")
    if "analysis" in effective_degraded:
        lines.append("Mode: rules only (analysis failed)")

    if urls:
        lines.append("URLs:")
        for u in urls:
            u_str = u.get("url", "")
            u_trusted = u.get("trusted", False)
            u_prob = u.get("prob", 0.0)
            lines.append(f"  - {u_str} [trusted: {u_trusted}, prob: {u_prob:.2f}]")

    lines.append("Advice:")
    for a_line in advice.splitlines():
        lines.append(f"  {a_line}")

    lines.append(UNCERTAINTY_NOTICE)

    return "\n".join(lines)


def _cap_messages(messages: list[str]) -> list[str]:
    """Cap each message at MAX_SMS_TEXT_CHARS and the run at MAX_MESSAGES.

    Emits a clear warning on stderr whenever anything is cut.
    """
    capped: list[str] = []
    for message in messages:
        if len(message) > MAX_SMS_TEXT_CHARS:
            print(
                f"warning: message truncated to {MAX_SMS_TEXT_CHARS} characters "
                f"(was {len(message)})",
                file=sys.stderr,
            )
            message = message[:MAX_SMS_TEXT_CHARS]
        capped.append(message)
    if len(capped) > MAX_MESSAGES:
        print(
            f"warning: message count truncated to {MAX_MESSAGES} "
            f"(was {len(capped)}); extra messages dropped",
            file=sys.stderr,
        )
        capped = capped[:MAX_MESSAGES]
    return capped


def gather_messages(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str] | None:
    """Collect input messages from --file, positional text, or stdin.

    Returns None when no input is available so the caller can print help.
    Each message is capped at 2000 characters and the run at 10000
    messages; anything cut produces a warning on stderr.
    """
    messages: list[str] = []
    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as input_file:
            for line in input_file:
                line_stripped = line.strip()
                if line_stripped:
                    messages.append(line_stripped)
        return _cap_messages(messages)
    text_option = getattr(args, "text_option", None)
    if text_option:
        messages.append(text_option)
        return _cap_messages(messages)
    if args.text:
        messages.append(args.text)
        return _cap_messages(messages)
    if not sys.stdin.isatty():
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        for line in sys.stdin:
            line_stripped = line.strip()
            if line_stripped:
                messages.append(line_stripped)
        return _cap_messages(messages)
    return None


def _process_message(
    msg: str,
    args: argparse.Namespace,
    url_det: Any,
    sms_det: Any,
    advisor: Any,
    degraded: list[str],
    detectors_loaded: list[str],
    detector_status: dict[str, Any],
    use_color: bool,
    analyse: Any,
) -> bool:
    """Analyse a single message, write output, and return whether runtime degradation occurred."""
    result = analyse(
        msg,
        url_det=url_det,
        sms_det=sms_det,
        advisor=advisor,
        sender=getattr(args, "sender", None),
    )
    runtime_degraded = False
    msg_degraded = list(degraded)
    if "sms_model_error" in result["evidence"].get("indicators", []):
        runtime_degraded = True
        if "sms" not in msg_degraded:
            msg_degraded.append("sms")
    if "url_model_error" in result["evidence"].get("indicators", []):
        runtime_degraded = True
        if "url" not in msg_degraded:
            msg_degraded.append("url")
    if "analysis_error" in result["evidence"].get("indicators", []):
        runtime_degraded = True
        if (
            "sms_model_error" not in result["evidence"].get("indicators", [])
            and "url_model_error" not in result["evidence"].get("indicators", [])
            and "analysis" not in msg_degraded
        ):
            msg_degraded.append("analysis")
    if args.json:
        evidence = result["evidence"]
        evidence_dict = evidence.to_dict() if hasattr(evidence, "to_dict") else evidence
        is_promo = bool(result.get("is_plain_promotion"))
        output_obj = {
            "message": msg,
            "highlighted": highlight_cues(msg, result["evidence"].get("cue_spans", [])),
            "evidence": evidence_dict,
            "advice": result["advice"],
            "advice_source": result["advice_source"],
            "timings_ms": result["timings_ms"],
            "detectors_loaded": detectors_loaded,
            "detector_status": detector_status,
            "degraded": msg_degraded,
            "is_plain_promotion": is_promo,
            "kind": "promotion" if is_promo else "standard",
        }
        sys.stdout.write(json.dumps(output_obj, indent=2) + "\n")
    else:
        sys.stdout.write(format_human_output(msg, result, use_color=use_color, degraded=msg_degraded) + "\n\n")

    return runtime_degraded


def main(argv: list[str] | None = None) -> int:
    """Entry point for the sentinel CLI.

    Args:
        argv: Command-line arguments list, defaults to sys.argv[1:].

    Returns:
        0 on success, 1 on input/argument error, or 2 if --strict is requested and degraded.
    """
    _log_cpu_accel_once()
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] not in ("scan", "-h", "--help"):
        argv = ["scan"] + argv

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.file and not os.path.isfile(args.file):
        sys.stderr.write(f"Error: file not found: {args.file}\n")
        return 1

    messages = gather_messages(args, parser)
    if messages is None:
        sys.stderr.write("Error: no text or file provided.\n")
        parser.print_help()
        return 1

    try:
        loaded = load_detectors(args)
    except Exception as error:
        sys.stderr.write(f"Error: failed to load detectors ({type(error).__name__}: {error})\n")
        return 1
    if len(loaded) == 4:
        url_det, sms_det, advisor, detector_status = loaded
    else:
        url_det, sms_det, advisor = loaded
        detector_status = _fallback_status(url_det, sms_det, advisor)
    detectors_loaded: list[str] = []
    if url_det is not None:
        detectors_loaded.append("url")
    if sms_det is not None:
        detectors_loaded.append("sms")
    if advisor is not None:
        detectors_loaded.append("advisor")
    degraded = _degraded_detectors(url_det, sms_det, advisor, detector_status.get("llama"))
    use_color = _use_color(getattr(args, "color", "auto"))
    runtime_degraded = False
    try:
        from sentinel.pipeline import analyse
    except Exception as error:
        sys.stderr.write(f"Error: failed to load pipeline ({type(error).__name__}: {error})\n")
        return 1

    for msg in messages:
        if _process_message(
            msg,
            args=args,
            url_det=url_det,
            sms_det=sms_det,
            advisor=advisor,
            degraded=degraded,
            detectors_loaded=detectors_loaded,
            detector_status=detector_status,
            use_color=use_color,
            analyse=analyse,
        ):
            runtime_degraded = True

    if advisor is not None and hasattr(advisor, "close"):
        advisor.close()
    if getattr(args, "strict", False) and (degraded or runtime_degraded):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
