"""Measure whether the on-device Llama 3.2 1B can write scam advice in Hindi and Tamil.

Measurement only: no app code is touched. For each selected risky code-mixed
message this script builds the real Evidence with the shipped SMS/URL detectors
(no Llama), then runs two prompts on the shipped phone model:

  EN      advisor.build_prompt(text, evidence), unchanged.
  NATIVE  the same prompt with "plain simple English" replaced once by
          "plain simple Hindi written in Devanagari script" (Hindi rows) or
          "plain simple Tamil written in Tamil script" (Tamil rows).

One JSON line per generation goes to <out-dir>/results.jsonl; a human review
file goes to <out-dir>/REVIEW.md. Rerunning resumes: (id, condition) pairs
already present are skipped.

Run in WSL with the executorch venv, from anywhere:

  cd /mnt/c/Users/<user>/arm-ps3-multilang
  ~/venvs/et/bin/python bench/multilang_advice/llama_lang_probe.py \
      --limit 1 --max-new-tokens 40 --out-dir /tmp/llprobe

Generation is a manual greedy loop over the .pte's `forward` method using
executorch's portable module binding. The wheel's `TextLLMRunner` cannot be
used for the NATIVE conditions: its token callback converts each piece with a
strict UTF-8 decode, and Tamil/Devanagari tokens are often partial UTF-8 byte
sequences, so `generate()` raises UnicodeDecodeError. The tokenizer is rebuilt
from the shipped `tokenizer.model` (tiktoken format) with the Llama 3 regex and
special-token table; it reproduces the runner's prompt token counts exactly
(381 on a sample prompt) and produced identical text on an English check.

The script dlopens the llama custom-ops and quantized kernel libraries from
the executorch wheel first; without them the model fails to load or run
("kernel 'llama::update_cache.out' not found").
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "bench" / "heldout_ml" / "code_mixed_ta_hi_1220.csv"
MODEL_PATH = ROOT / "models" / "llama32_et_community" / "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
TOKENIZER_PATH = ROOT / "models" / "llama32_et_community" / "tokenizer.model"

MESSAGES_PER_LANGUAGE = 10
EN_PHRASE = "plain simple English"
NATIVE_REPLACEMENT = {
    "Hindi": "plain simple Hindi written in Devanagari script",
    "Tamil": "plain simple Tamil written in Tamil script",
}
NATIVE_SCRIPT = {
    "Hindi": ("Devanagari", 0x0900, 0x097F),
    "Tamil": ("Tamil", 0x0B80, 0x0BFF),
}

PROJECTED_TOK_S = {"m31": 5.7, "f14": 10.0}

CLICK_RE_EN = re.compile(
    r"\b(?:click|open)\b[^.\n]{0,80}\b(?:link|url|website|site|page)\b", re.IGNORECASE
)
CLICK_WORDS = ("\u0915\u094d\u0932\u093f\u0915", "\u0b95\u0bbf\u0bb3\u0bbf\u0b95\u0bcd")
ASSISTANT_HEADER = "<|start_header_id|>assistant<|end_header_id|>"
SPECIAL_TOKEN_RE = re.compile(r"<\|[^|<>]{1,64}\|>")

TIKTOKEN_PATTERN = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}"
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
)
BASE_VOCAB_SIZE = 128000
SPECIAL_TOKEN_NAMES = [
    "<|begin_of_text|>",
    "<|end_of_text|>",
    "<|reserved_special_token_0|>",
    "<|reserved_special_token_1|>",
    "<|finetune_right_pad_id|>",
    "<|reserved_special_token_2|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|reserved_special_token_3|>",
    "<|eot_id|>",
    "<|python_tag|>",
] + [f"<|reserved_special_token_{i}|>" for i in range(4, 249)]
EOS_IDS = (128001, 128009)  # <|end_of_text|>, <|eot_id|>


def _is_letter(ch: str) -> bool:
    return unicodedata.category(ch).startswith("L")


def template_key(message_id: str) -> str:
    return message_id.rsplit("-", 1)[0]


def select_messages(csv_path: Path) -> list[dict[str, str]]:
    """First 10 distinct risky templates per language, one row each, ids sorted."""
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    risky = [row for row in rows if row.get("truth") == "risky"]
    risky.sort(key=lambda row: row["id"])

    selected: list[dict[str, str]] = []
    for language in ("Tamil", "Hindi"):
        seen: set[str] = set()
        for row in risky:
            if row.get("language") != language:
                continue
            key = template_key(row["id"])
            if key in seen:
                continue
            seen.add(key)
            selected.append(row)
            if len(seen) == MESSAGES_PER_LANGUAGE:
                break
    return selected


def build_evidence(text: str, url_det: Any, sms_det: Any) -> Any:
    """Same detector path as sentinel.pipeline.analyse, without the advisor."""
    from sentinel import pipeline as pl
    from sentinel.detector_api import run_extra_detectors

    urls = [pl._score_url_with_detector(url, url_det) for url in pl._extract_urls_safe(text)]
    cues = pl._safe_sms_cues(text)
    sms_result, sms_error = pl._safe_sms_predict_detailed(text, sms_det)
    extra_parts = run_extra_detectors(text, ())
    evidence = pl._safe_fuse(text, sms_result, urls, cues, extra_parts, None)
    if sms_error:
        if "sms_model_error" not in evidence.indicators:
            evidence.indicators.append("sms_model_error")
        if "analysis_error" not in evidence.indicators:
            evidence.indicators.append("analysis_error")
    return evidence


def make_prompt(advisor: Any, text: str, evidence: Any, language: str, condition: str) -> str:
    prompt = advisor.build_prompt(text, evidence)
    if condition == "EN":
        return prompt
    replacement = NATIVE_REPLACEMENT[language]
    count = prompt.count(EN_PHRASE)
    if count != 1:
        raise AssertionError(f"expected exactly one {EN_PHRASE!r} in prompt, found {count}")
    return prompt.replace(EN_PHRASE, replacement)


def clean_output(raw: str) -> str:
    text = raw.replace(ASSISTANT_HEADER, "")
    text = SPECIAL_TOKEN_RE.sub("", text)
    return text.strip()


def script_share(text: str, language: str, condition: str) -> float:
    letters = [ch for ch in text if _is_letter(ch)]
    if not letters:
        return 0.0
    if condition == "EN":
        wanted = [ch for ch in letters if "A" <= ch <= "Z" or "a" <= ch <= "z"]
        return round(len(wanted) / len(letters), 4)
    _, low, high = NATIVE_SCRIPT[language]
    wanted = [ch for ch in letters if low <= ord(ch) <= high]
    return round(len(wanted) / len(letters), 4)


def sms_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    for match in re.finditer(r"\d(?:[\d\s\-.()/]*\d)?", text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 10 and digits not in numbers:
            numbers.append(digits)
    return numbers


def leaks_sms_link(text: str, output: str, sms_urls: list[str]) -> bool:
    lowered = output.lower()
    for url in sms_urls:
        candidate = url.lower()
        if candidate in lowered:
            return True
        without_scheme = re.sub(r"^[a-z][a-z0-9+.-]*://", "", candidate)
        without_scheme = without_scheme.rstrip("/")
        if without_scheme and without_scheme in lowered:
            return True
    return False


def leaks_sms_phone(output: str, numbers: list[str]) -> bool:
    digits_out = re.sub(r"\D", "", output)
    return any(number in digits_out for number in numbers)


def says_click(output: str) -> bool:
    if CLICK_RE_EN.search(output):
        return True
    return any(word in output for word in CLICK_WORDS)


def load_tokenizer() -> Any:
    """Rebuild the Llama 3 tiktoken tokenizer the .pte was exported with."""
    import base64

    import tiktoken

    ranks: dict[bytes, int] = {}
    with TOKENIZER_PATH.open("rb") as handle:
        for line in handle.read().split(b"\n"):
            if not line:
                continue
            token, rank = line.split(b" ")
            ranks[base64.b64decode(token)] = int(rank)
    if len(ranks) != BASE_VOCAB_SIZE:
        raise AssertionError(f"expected {BASE_VOCAB_SIZE} base tokens, found {len(ranks)}")

    encoding = tiktoken.Encoding(
        name="llama3",
        pat_str=TIKTOKEN_PATTERN,
        mergeable_ranks=ranks,
        special_tokens={name: BASE_VOCAB_SIZE + i for i, name in enumerate(SPECIAL_TOKEN_NAMES)},
    )
    if encoding.encode("<|start_header_id|>", allowed_special="all") != [128006]:
        raise AssertionError("special-token table does not match the model")
    return encoding


def load_model() -> Any:
    """Load the .pte with the portable binding, after the llama runtime kernels.

    The wheel neither statically registers the llama custom kernels nor loads
    them with the portable binding, so without these libraries the model fails
    with "kernel 'llama::update_cache.out' not found". The custom-ops library
    is named *_aot_* but it also carries the portable runtime kernels.
    """
    import ctypes

    import torch  # noqa: F401  (preloads libtorch)
    import executorch.extension.pybindings.portable_lib as portable_lib
    import executorch.extension.llm.runner as runner_module

    site = Path(runner_module.__file__).resolve().parents[3]
    candidates = [
        site / "lib" / "libexecutorch_kernels_quantized.so",
        site / "lib" / "libexecutorch_kernels_optimized.so",
        site / "extension" / "llm" / "custom_ops" / "libcustom_ops_aot_lib.so",
    ]
    loaded = []
    for path in candidates:
        if path.exists():
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            loaded.append(path.name)
    print(f"runtime kernels loaded: {loaded}", flush=True)

    return portable_lib._load_for_executorch(str(MODEL_PATH))


def warm_up(module: Any, encoding: Any) -> None:
    """Page in the weights and warm the delegate before any timed run.

    The first forward after loading takes about 16 s here (lazy weight
    paging); later prefills of the same length take about 1.4 s.
    """
    import torch

    text = (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\nhi"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )
    ids = encoding.encode(text, allowed_special="all")
    started = time.perf_counter()
    module.run_method(
        "forward",
        [torch.tensor([ids], dtype=torch.long), torch.tensor([0], dtype=torch.long)],
    )
    module.run_method(
        "forward",
        [torch.tensor([[128006]], dtype=torch.long), torch.tensor([len(ids)], dtype=torch.long)],
    )
    print(f"warm-up done in {time.perf_counter() - started:.1f}s (not timed)", flush=True)


def generate_one(
    module: Any,
    encoding: Any,
    prompt: str,
    max_new_tokens: int,
    seq_len: int,
) -> dict[str, Any]:
    """Greedy decode one prompt with the model's forward method.

    Returns decoded text plus timing and token measurements. `temperature` is
    effectively 0 (argmax), echo is off, and the prompt already carries
    <|begin_of_text|>, so no BOS is added.
    """
    import torch

    ids = encoding.encode(prompt, allowed_special="all")
    if len(ids) + max_new_tokens > seq_len:
        raise ValueError(f"prompt {len(ids)} + {max_new_tokens} tokens exceeds seq_len {seq_len}")

    started = time.perf_counter()
    logits = module.run_method(
        "forward",
        [torch.tensor([ids], dtype=torch.long), torch.tensor([0], dtype=torch.long)],
    )[0]
    prefill_s = time.perf_counter() - started

    tokens = [int(torch.argmax(logits[0]))]
    pos = len(ids)
    while len(tokens) < max_new_tokens and tokens[-1] not in EOS_IDS:
        logits = module.run_method(
            "forward",
            [
                torch.tensor([[tokens[-1]]], dtype=torch.long),
                torch.tensor([pos], dtype=torch.long),
            ],
        )[0]
        tokens.append(int(torch.argmax(logits[0])))
        pos += 1

    total_s = time.perf_counter() - started
    decode_s = total_s - prefill_s
    ended_on_eos = tokens[-1] in EOS_IDS
    decode_steps = len(tokens) - 1

    return {
        "raw_text": encoding.decode(tokens),
        "generated_tokens": len(tokens),
        "prompt_tokens": len(ids),
        "ttft_s": round(prefill_s, 4),
        "decode_tps": round(decode_steps / decode_s, 3) if decode_steps > 0 and decode_s > 0 else None,
        "total_s": round(total_s, 4),
        "ended_on_eos": ended_on_eos,
        "stats": {
            "prompt_tokens": len(ids),
            "generated_tokens": len(tokens),
            "prefill_s": round(prefill_s, 4),
            "decode_s": round(decode_s, 4),
            "decode_steps": decode_steps,
            "ended_on_eos": ended_on_eos,
        },
    }


def load_done(results_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    done: dict[tuple[str, str], dict[str, Any]] = {}
    if not results_path.exists():
        return done
    with results_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            done[(record.get("id", ""), record.get("condition", ""))] = record
    return done


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def write_review(
    review_path: Path,
    messages: list[dict[str, str]],
    records: dict[tuple[str, str], dict[str, Any]],
) -> None:
    wanted_ids = {message["id"] for message in messages}
    rows = [record for key, record in records.items() if key[0] in wanted_ids]
    lines: list[str] = []
    lines.append("# Multilang advice probe: Llama 3.2 1B, Hindi and Tamil")
    lines.append("")
    lines.append(
        "Measurement only. Each risky code-mixed SMS runs through the shipped advice prompt "
        "(EN) and the same prompt with the language phrase switched to the target language "
        "(NATIVE). Prompts and evidence are the real ones; no guard() or advisor.py change."
    )
    lines.append("")
    lines.append(
        "- Model: `models/llama32_et_community/Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte` "
        "(the phone model), run with executorch's portable binding."
    )
    lines.append(
        "- Generation: manual greedy loop (argmax) over the .pte `forward` method, one prompt "
        "prefill then one token per step, stopping on `<|eot_id|>`/`<|end_of_text|>`. The wheel's "
        "`TextLLMRunner` is not usable here: its token callback strict-decodes each piece as UTF-8 "
        "and raises `UnicodeDecodeError` on partial Tamil/Devanagari byte sequences. The tokenizer "
        "is rebuilt from `tokenizer.model` with the Llama 3 regex and special-token table; on the "
        "English check it produced the same 381 prompt tokens and the same generated text as "
        "`TextLLMRunner`. Timings are after a one-off warm-up (first forward pages in the weights)."
    )
    lines.append(
        "- Settings: temperature 0, echo False, seq_len 1024, `num_bos=0` because "
        "`build_prompt` already starts with `<|begin_of_text|>`; adding a BOS would duplicate it. "
        "`max_new_tokens` is the CLI flag of the run that produced this file."
    )
    lines.append(
        "- Runtime: the executorch wheel does not register the llama custom kernels by itself, so "
        "the probe dlopens `libexecutorch_kernels_quantized.so`, "
        "`libexecutorch_kernels_optimized.so` and `custom_ops/libcustom_ops_aot_lib.so` "
        "before loading the model."
    )
    lines.append(
        "- NATIVE replacement: \"plain simple English\" -> \"plain simple Hindi written in "
        "Devanagari script\" (Hindi) or \"plain simple Tamil written in Tamil script\" (Tamil), "
        "asserted to occur exactly once."
    )
    lines.append(
        "- `projected M31 s` = generated tokens / 5.7 tok/s and `projected F14 s` = generated tokens "
        "/ 10.0 tok/s. These are ESTIMATES from the token count, not measurements on those phones."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| language | condition | n | median gen tok | max gen tok | median total s | "
        "median projected M31 s | hit_max | median script_share | has_1930 | leaks_link | "
        "leaks_phone | says_click |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for language in ("Tamil", "Hindi"):
        for condition in ("EN", "NATIVE"):
            group = [r for r in rows if r["language"] == language and r["condition"] == condition]
            tokens = [r["generated_tokens"] for r in group]
            totals = [r["total_s"] for r in group]
            projected = [r["generated_tokens"] / PROJECTED_TOK_S["m31"] for r in group]
            shares = [r["script_share"] for r in group]
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                    language,
                    condition,
                    len(group),
                    fmt(median(tokens)),
                    fmt(max(tokens) if tokens else None),
                    fmt(median(totals)),
                    fmt(median(projected)),
                    sum(1 for r in group if r["hit_max_tokens"]),
                    fmt(median(shares)),
                    sum(1 for r in group if r["has_1930"]),
                    sum(1 for r in group if r["leaks_sms_link"]),
                    sum(1 for r in group if r["leaks_sms_phone"]),
                    sum(1 for r in group if r["says_click"]),
                )
            )
    lines.append("")
    lines.append("## Messages (EN and NATIVE side by side)")
    lines.append("")

    for message in messages:
        message_id = message["id"]
        language = message["language"]
        en = records.get((message_id, "EN"))
        native = records.get((message_id, "NATIVE"))
        evidence = (en or native or {}).get("evidence", {})
        lines.append(f"### {message_id} ({language}, template {template_key(message_id)})")
        lines.append("")
        lines.append(
            "Evidence: label `{}`, risk {}, level `{}`".format(
                evidence.get("label", "-"), fmt(evidence.get("risk")), evidence.get("level", "-")
            )
        )
        lines.append("")
        lines.append("SMS text:")
        lines.append("")
        lines.append("```")
        lines.append(message["text"])
        lines.append("```")
        lines.append("")
        lines.append("| EN (plain simple English) | NATIVE |")
        lines.append("|---|---|")
        en_text = cell((en or {}).get("output", "(missing)"))
        native_text = cell((native or {}).get("output", "(missing)"))
        lines.append(f"| {en_text} | {native_text}<br><br>Quality (good/ok/bad): |")
        lines.append("")

    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="process only the first N messages")
    parser.add_argument("--max-new-tokens", type=int, default=300, help="generation cap (default 300)")
    parser.add_argument("--seq-len", type=int, default=1024, help="context length (default 1024)")
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "bench" / "multilang_advice"),
        help="directory for results.jsonl and REVIEW.md",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    from sentinel import advisor
    from sentinel import cli as sentinel_cli

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    review_path = out_dir / "REVIEW.md"

    messages = select_messages(CSV_PATH)
    if args.limit is not None:
        messages = messages[: args.limit]

    done = load_done(results_path)
    pending = [
        (message, condition)
        for message in messages
        for condition in ("EN", "NATIVE")
        if (message["id"], condition) not in done
    ]

    url_det = sms_det = None
    module = None
    encoding = None
    if pending:
        cli_args = sentinel_cli.build_parser().parse_args(
            ["scan", "--no-llm", "--models-dir", "models", "x"]
        )
        url_det, sms_det, _advisor, status = sentinel_cli.load_detectors(cli_args)
        print(f"detectors: {status}", flush=True)
        if url_det is None or sms_det is None:
            print("error: detectors failed to load", file=sys.stderr)
            return 1
        encoding = load_tokenizer()
        print(f"loading model: {MODEL_PATH}", flush=True)
        module = load_model()
        warm_up(module, encoding)

    with results_path.open("a", encoding="utf-8", newline="\n") as results_file:
        from sentinel.url_features import extract_urls

        evidence_cache: dict[str, Any] = {}
        evidence_fields_cache: dict[str, dict[str, Any]] = {}

        for index, (message, condition) in enumerate(pending, start=1):
            message_id = message["id"]
            language = message["language"]
            text = message["text"]

            if message_id not in evidence_cache:
                evidence_cache[message_id] = build_evidence(text, url_det, sms_det)
                built = evidence_cache[message_id]
                evidence_fields_cache[message_id] = {
                    "label": built.label,
                    "risk": built.risk,
                    "level": built.level,
                    "threshold": built.threshold,
                    "indicators": list(built.indicators),
                }
            evidence = evidence_cache[message_id]
            evidence_fields = evidence_fields_cache[message_id]

            prompt = make_prompt(advisor, text, evidence, language, condition)
            if not prompt.startswith("<|begin_of_text|>"):
                raise AssertionError("prompt no longer starts with <|begin_of_text|>")

            print(
                f"[{index}/{len(pending)}] {message_id} {condition} "
                f"({language}, {evidence.label}/{evidence.risk:.2f})",
                flush=True,
            )
            result = generate_one(
                module, encoding, prompt, args.max_new_tokens, args.seq_len
            )
            output = clean_output(result["raw_text"])

            try:
                sms_urls = [str(url) for url in extract_urls(text)]
            except Exception:
                sms_urls = []
            numbers = sms_numbers(text)
            lowered = output.lower()

            record = {
                "id": message_id,
                "language": language,
                "condition": condition,
                "evidence": evidence_fields,
                "output": output,
                "generated_tokens": result["generated_tokens"],
                "prompt_tokens": result["prompt_tokens"],
                "ttft_s": result["ttft_s"],
                "decode_tps": result["decode_tps"],
                "total_s": result["total_s"],
                "hit_max_tokens": result["generated_tokens"] >= args.max_new_tokens,
                "script_share": script_share(output, language, condition),
                "has_1930": "1930" in output,
                "has_cybercrime": "cybercrime.gov.in" in lowered,
                "leaks_sms_link": leaks_sms_link(text, output, sms_urls),
                "leaks_sms_phone": leaks_sms_phone(output, numbers),
                "says_click": says_click(output),
                "projected_m31_s": round(result["generated_tokens"] / PROJECTED_TOK_S["m31"], 3),
                "projected_f14_s": round(result["generated_tokens"] / PROJECTED_TOK_S["f14"], 3),
                "max_new_tokens": args.max_new_tokens,
                "stats": result["stats"],
            }
            results_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            results_file.flush()
            done[(message_id, condition)] = record
            print(
                f"    tokens={record['generated_tokens']} total={record['total_s']}s "
                f"ttft={record['ttft_s']}s share={record['script_share']}",
                flush=True,
            )

    write_review(review_path, messages, done)
    print(f"wrote {results_path}", flush=True)
    print(f"wrote {review_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
