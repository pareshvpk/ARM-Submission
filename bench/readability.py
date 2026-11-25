#!/usr/bin/env python3
"""Flesch Reading Ease over the Llama advice texts in a bench result JSON.

Standard library only. Usage:
    python bench/readability.py <llm_result.json> [--out file.json]

The score is the standard Flesch Reading Ease formula:
    206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)

Syllables use a simple vowel-group counter (aeiouy), with at least one
syllable per word.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

_VOWEL_GROUP = re.compile(r"[aeiouy]+", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _count_syllables(word: str) -> int:
    """Count vowel groups in a word; every word has at least one syllable."""
    groups = _VOWEL_GROUP.findall(word.lower())
    return max(1, len(groups))


def flesch_reading_ease(text: str) -> float:
    """Return the Flesch Reading Ease score for text (0.0 for empty text)."""
    words = _WORD.findall(text)
    if not words:
        return 0.0
    sentences = [part for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    if not sentences:
        sentences = [text]
    syllables = sum(_count_syllables(word) for word in words)
    return 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))


def extract_advice_texts(data: dict[str, Any]) -> tuple[list[str], str]:
    """Return (texts, input_kind) from a bench result JSON.

    input_kind is "full" when the result stores complete advice and "excerpt"
    when it stores only the truncated raw_advice_excerpt field.
    """
    samples = data.get("prompt_samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("no prompt_samples list found in the result JSON")

    full = [
        sample.get("raw_advice")
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("raw_advice"), str)
    ]
    if full:
        return full, "full"

    excerpts = [
        sample.get("raw_advice_excerpt")
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("raw_advice_excerpt"), str)
    ]
    if excerpts:
        return excerpts, "excerpt"

    raise ValueError("no raw_advice or raw_advice_excerpt text found in prompt_samples")


def summarise(texts: list[str], input_kind: str, source: str) -> dict[str, Any]:
    """Compute the readability summary fields reported by the CLI."""
    scored = [flesch_reading_ease(text) for text in texts if text.strip()]
    if not scored:
        return {
            "source": source,
            "input_kind": input_kind,
            "n": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "share_ge_60": None,
        }
    return {
        "source": source,
        "input_kind": input_kind,
        "n": len(scored),
        "mean": round(statistics.fmean(scored), 3),
        "median": round(statistics.median(scored), 3),
        "min": round(min(scored), 3),
        "max": round(max(scored), 3),
        "share_ge_60": round(sum(1 for score in scored if score >= 60.0) / len(scored), 4),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flesch Reading Ease over bench advice texts")
    parser.add_argument("result_json", help="Path to a run_bench LLM result JSON")
    parser.add_argument("--out", default=None, help="Write the summary JSON to this path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.result_json)
    data = json.loads(path.read_text(encoding="utf-8"))
    texts, input_kind = extract_advice_texts(data)
    summary = summarise(texts, input_kind, str(path))

    print(f"source: {summary['source']}")
    print(f"input_kind: {summary['input_kind']}")
    print(f"n: {summary['n']}")
    print(f"mean: {summary['mean']}")
    print(f"median: {summary['median']}")
    print(f"min: {summary['min']}")
    print(f"max: {summary['max']}")
    print(f"share_ge_60: {summary['share_ge_60']}")

    if summary["input_kind"] == "excerpt":
        print("NOTE: the source JSON stores truncated advice excerpts, not full advice texts.")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        sys.stderr.write(f"wrote {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
