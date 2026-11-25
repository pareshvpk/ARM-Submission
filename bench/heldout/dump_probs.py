from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

FIELDNAMES = [
    "text_hash",
    "source",
    "language",
    "truth",
    "p_ham",
    "p_unwanted",
    "p_scam",
    "fused_label",
    "fused_level",
    "fused_risk",
    "cue_types",
    "num_urls",
    "max_untrusted_url_prob",
    "indicators",
    "collect_pin",
    "shoe_store_promotion",
]

# The shoe-store promotion sent to the phones (deploy/android/device_test.ps1,
# message 5) is the DT-2 false positive. calibrate.py must be able to find it
# in a dump that never contains message text, so the dump marks it here.
SHOE_MARKERS = ("shoe",)
SHOE_SALE_MARKERS = ("sale", "off")


def compute_text_hash(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    collapsed = " ".join(text.strip().lower().split())
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()


def is_shoe_store_promotion(text: str) -> bool:
    lowered = (text or "").lower()
    return any(m in lowered for m in SHOE_MARKERS) and any(
        m in lowered for m in SHOE_SALE_MARKERS
    )


def build_dump_row(
    text: str,
    source: str,
    language: str,
    truth: str,
    sms_probs: dict[str, float],
    evidence: Any,
) -> dict[str, Any]:
    cue_spans = list(getattr(evidence, "cue_spans", []) or [])
    cue_types = sorted({c.get("type", "") for c in cue_spans if isinstance(c, dict) and c.get("type")})
    urls = list(getattr(evidence, "urls", []) or [])
    untrusted_probs = [float(u.get("prob", 0.0)) for u in urls if not u.get("trusted")]
    max_untrusted = max(untrusted_probs) if untrusted_probs else 0.0
    indicators = list(getattr(evidence, "indicators", []) or [])
    collect_pin = False
    try:
        from sentinel.fusion import _extra_cue_scores

        _app_install, collect_pin_score = _extra_cue_scores(cue_spans)
        collect_pin = collect_pin_score > 0.0
    except Exception:
        collect_pin = False
    return {
        "text_hash": compute_text_hash(text),
        "source": source,
        "language": language,
        "truth": truth,
        "p_ham": float(sms_probs.get("ham", 0.0)),
        "p_unwanted": float(sms_probs.get("unwanted", 0.0)),
        "p_scam": float(sms_probs.get("scam", 0.0)),
        "fused_label": str(getattr(evidence, "label", "ham") or "ham"),
        "fused_level": str(getattr(evidence, "level", "low") or "low"),
        "fused_risk": float(getattr(evidence, "risk", 0.0) or 0.0),
        "cue_types": ";".join(cue_types),
        "num_urls": len(urls),
        "max_untrusted_url_prob": max_untrusted,
        "indicators": ";".join(str(i) for i in indicators),
        "collect_pin": "true" if collect_pin else "false",
        "shoe_store_promotion": "true" if is_shoe_store_promotion(text) else "false",
    }


def dump_tokens_for_texts(
    texts: list[str], feed_fn: Callable[[str], list[int]], out_path: str | Path
) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        for index, text in enumerate(texts):
            ids = feed_fn(text)
            f.write(
                json.dumps(
                    {
                        "line": index,
                        "text_hash": compute_text_hash(text),
                        "input_ids": [int(v) for v in ids],
                    }
                )
                + "\n"
            )


def _detector_feed_fn(sms_det: Any) -> Callable[[str], list[int]]:
    from sentinel.detectors import remap_ids

    def feed(text: str) -> list[int]:
        enc = sms_det.tokenizer(
            [text],
            padding=False if sms_det.is_dynamic else "max_length",
            truncation=True,
            max_length=128,
            return_tensors="pt",
        )
        input_ids = enc["input_ids"].to(sms_det._torch.int64)
        if sms_det.id_map is not None:
            input_ids = remap_ids(input_ids, sms_det.id_map)
        ids = input_ids[0].tolist() if hasattr(input_ids[0], "tolist") else list(input_ids[0])
        if sms_det.is_dynamic:
            return [int(v) for v in ids]
        return [int(v) for v in ids]

    return feed


def load_detectors_for_dump(args: argparse.Namespace):
    from sentinel.cli import load_detectors

    load_args = argparse.Namespace(
        models_dir=args.models_dir,
        url_model=args.url_model,
        url_vocab=args.url_vocab,
        sms_model=args.sms_model,
        sms_tokenizer=args.sms_tokenizer,
        no_llm=True,
        llama_main=getattr(args, "llama_main", ""),
        llama_model=getattr(args, "llama_model", None),
        llama_tokenizer=getattr(args, "llama_tokenizer", None),
        llama_server=getattr(args, "llama_server", ""),
        threads=getattr(args, "threads", 4),
    )
    loaded = load_detectors(load_args)
    if len(loaded) == 4:
        url_det, sms_det, advisor, _status = loaded
    else:
        url_det, sms_det, advisor = loaded
    if advisor is not None and hasattr(advisor, "close"):
        try:
            advisor.close()
        except Exception:
            pass
    return url_det, sms_det


def build_parser() -> argparse.ArgumentParser:
    default_models_dir = os.getenv("PS3_MODELS_DIR", os.path.expanduser("~/ps3/models"))
    parser = argparse.ArgumentParser(description="Dump per-row model probabilities (no message text)")
    parser.add_argument("input_csv", nargs="?", help="Held-out CSV with text,truth,source,language")
    parser.add_argument("--out", "--out-csv", "--output", dest="out", required=True, help="Dump CSV path")
    parser.add_argument("--models-dir", default=default_models_dir, help="Directory containing model files")
    parser.add_argument("--models-manifest", default=os.getenv("PS3_MODELS_MANIFEST", None))
    parser.add_argument("--url-model", default=None)
    parser.add_argument("--url-vocab", default=None)
    parser.add_argument("--sms-model", default=None)
    parser.add_argument("--sms-tokenizer", default=None)
    parser.add_argument("--extra-texts", dest="extra_texts", default=None, help="File with one message per line")
    parser.add_argument(
        "--dump-token-ids",
        dest="dump_token_ids",
        nargs=2,
        metavar=("FILE", "OUT"),
        default=None,
        help="Write tokenizer input_ids (as fed to the SMS model) for each line of FILE to OUT as JSON lines",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with open(args.out, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=FIELDNAMES)
        writer.writeheader()
        sms_det = None
        url_det = None
        detectors_loaded = False

        def ensure_detectors():
            nonlocal url_det, sms_det, detectors_loaded
            if not detectors_loaded:
                url_det, sms_det = load_detectors_for_dump(args)
                if sms_det is None:
                    raise RuntimeError(
                        "SMS detector unavailable; refusing to dump rules-only verdicts (DT-13)"
                    )
                detectors_loaded = True

        def score_one(text: str, source: str, language: str, truth: str):
            ensure_detectors()
            from sentinel.pipeline import analyse

            sms_out = sms_det.predict(text)
            probs = sms_out.get("probs", {}) if isinstance(sms_out, dict) else {}
            result = analyse(text, url_det=url_det, sms_det=sms_det, advisor=None)
            evidence = result.get("evidence")
            writer.writerow(build_dump_row(text, source, language, truth, probs, evidence))

        if args.input_csv:
            with open(args.input_csv, "r", encoding="utf-8", newline="") as fin:
                for row in csv.DictReader(fin):
                    text = str(row.get("text", "") or "")
                    truth = str(row.get("truth", "")).strip().lower()
                    if truth not in ("ham", "risky"):
                        raise ValueError(f"unknown truth label {truth!r}: expected ham/risky")
                    score_one(text, str(row.get("source", "")).strip(), str(row.get("language", "")).strip(), truth)
        if args.extra_texts:
            with open(args.extra_texts, "r", encoding="utf-8") as f:
                for line in f.read().splitlines():
                    text = line.rstrip("\n")
                    if not text.strip():
                        continue
                    score_one(text, "extra", "unknown", "unknown")
    if args.dump_token_ids:
        texts_file, out_file = args.dump_token_ids
        url_det, sms_det = load_detectors_for_dump(args)
        if sms_det is None:
            raise RuntimeError("SMS detector unavailable; cannot dump token ids (DT-13)")
        with open(texts_file, "r", encoding="utf-8") as f:
            texts = [ln.rstrip("\n") for ln in f.read().splitlines() if ln.strip()]
        dump_tokens_for_texts(texts, _detector_feed_fn(sms_det), out_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
