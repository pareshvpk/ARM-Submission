"""Text highlighting and cue span formatting for PS3 Sentinel.

Formats matched cue spans using ANSI colour codes for terminal display or
bracketed [[cue]](type) annotations for plain logs and machine readability.
Mirrored on Android by UI span styling in the result screen.
"""
from __future__ import annotations

from typing import Any

# ANSI codes for a bold red span. Reset clears every attribute so the
# styling cannot leak into the rest of the line.
ANSI_BOLD_RED = "\x1b[1;31m"
ANSI_RESET = "\x1b[0m"

# Shown in plain (no-colour) output when a cue has no type.
DEFAULT_CUE_TYPE = "cue"


def _valid_spans(text: str, cue_spans: list[dict[str, Any]] | None) -> list[tuple[int, int, str]]:
    """Return only the spans that can be shown safely: in range and non-empty.

    A bad offset must never crash the CLI or garble the message, so any
    span that is out of range, empty, or not made of integers is dropped.
    """
    valid: list[tuple[int, int, str]] = []
    if not cue_spans:
        return valid
    text_len = len(text)
    for span in cue_spans:
        if not isinstance(span, dict):
            continue
        start = span.get("start")
        end = span.get("end")
        # bool is a subclass of int; treat it as invalid rather than 0/1.
        if not isinstance(start, int) or isinstance(start, bool):
            continue
        if not isinstance(end, int) or isinstance(end, bool):
            continue
        if start < 0 or end > text_len or end <= start:
            continue
        cue_type = span.get("type") or DEFAULT_CUE_TYPE
        if not isinstance(cue_type, str) or not cue_type:
            cue_type = DEFAULT_CUE_TYPE
        valid.append((start, end, cue_type))
    return valid


def _merge_overlapping(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Merge overlapping spans into single spans covering the union.

    The merged span keeps the type of the first span in sorted order
    (earliest start, longest first) so plain output names one cue type.
    """
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[list[Any]] = [[ordered[0][0], ordered[0][1], ordered[0][2]]]
    for start, end, cue_type in ordered[1:]:
        current = merged[-1]
        # Strictly inside the previous span means they overlap; a span
        # starting exactly where the previous ends is a separate cue.
        if start < current[1]:
            if end > current[1]:
                current[1] = end
        else:
            merged.append([start, end, cue_type])
    return [(start, end, cue_type) for start, end, cue_type in merged]


def format_highlighted(
    text: str,
    cue_spans: list[dict[str, Any]] | None,
    use_color: bool = False,
) -> str:
    """Mark each cue span in ``text`` and return the marked string.

    With colour, each span is wrapped in ANSI bold red. Without colour,
    each span becomes ``[[span]](type)`` so the cue type stays visible in
    pipes, logs, and terminals that cannot render colour. Overlapping
    spans are merged first, and out-of-range spans are ignored.

    Args:
        text: Original message text.
        cue_spans: List of cue span dicts with start, end, and type.
        use_color: Whether to use ANSI terminal escape sequences.

    Returns:
        Formatted string containing highlighted or annotated cue spans.
    """
    if not text:
        return text
    merged = _merge_overlapping(_valid_spans(text, cue_spans))
    if not merged:
        return text

    parts: list[str] = []
    cursor = 0
    for start, end, cue_type in merged:
        parts.append(text[cursor:start])
        span_text = text[start:end]
        if use_color:
            parts.append(f"{ANSI_BOLD_RED}{span_text}{ANSI_RESET}")
        else:
            parts.append(f"[[{span_text}]]({cue_type})")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)
