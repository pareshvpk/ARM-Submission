from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

LEVELS = ("low", "medium", "high")
PRED_LABELS = ("ham", "unwanted", "scam")
TRUTHS = ("ham", "risky")
THREAT_LEVELS = ("medium", "high")


def compute_text_hash(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    collapsed = " ".join(text.strip().lower().split())
    return hashlib.sha1(collapsed.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def get_git_commit(repo_root: str | Path | None = None) -> str:
    root = Path(repo_root) if repo_root is not None else ROOT_DIR
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    commit = (out.stdout or "").strip()
    return commit if commit else "unknown"


def is_risky_level(level: str) -> bool:
    return (level or "").strip().lower() in THREAT_LEVELS


def normalise_truth(truth: object) -> str:
    """Return validated ham/risky; raise on unknown."""
    key = str(truth or "").strip().lower()
    if key not in TRUTHS:
        raise ValueError(f"unknown truth label {truth!r}: expected one of {TRUTHS}")
    return key


def normalise_pred_label(pred_label: object) -> str:
    key = str(pred_label or "").strip().lower()
    if key not in PRED_LABELS:
        raise ValueError(f"unknown pred_label {pred_label!r}: expected one of {PRED_LABELS}")
    return key


def normalise_pred_level(pred_level: object) -> str:
    key = str(pred_level or "").strip().lower()
    if key not in LEVELS:
        raise ValueError(f"unknown pred_level {pred_level!r}: expected one of {LEVELS}")
    return key


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


def _median(sorted_vals: list[float]) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)


def _p95(sorted_vals: list[float]) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    idx = math.ceil(0.95 * n) - 1
    if idx < 0:
        idx = 0
    if idx > n - 1:
        idx = n - 1
    return float(sorted_vals[idx])


def new_accumulator() -> dict[str, Any]:
    return {
        "n": 0,
        "confusion_level": {
            "ham": {"low": 0, "medium": 0, "high": 0},
            "risky": {"low": 0, "medium": 0, "high": 0},
        },
        "confusion_label": {
            "ham": {"ham": 0, "unwanted": 0, "scam": 0},
            "risky": {"ham": 0, "unwanted": 0, "scam": 0},
        },
        "tp": 0,
        "fn": 0,
        "fp": 0,
        "tn": 0,
        "latencies": [],
    }


def update_accumulator(
    acc: dict[str, Any],
    truth: str,
    pred_label: str,
    pred_level: str,
    latency_ms: float,
) -> None:
    truth_key = normalise_truth(truth)
    level_key = normalise_pred_level(pred_level)
    label_key = normalise_pred_label(pred_label)
    acc["n"] += 1
    acc["confusion_level"][truth_key][level_key] += 1
    acc["confusion_label"][truth_key][label_key] += 1
    try:
        lat = float(latency_ms)
    except Exception:
        lat = 0.0
    acc["latencies"].append(lat)
    predicted_risky = is_risky_level(level_key)
    if truth_key == "risky" and predicted_risky:
        acc["tp"] += 1
    elif truth_key == "risky" and not predicted_risky:
        acc["fn"] += 1
    elif truth_key == "ham" and predicted_risky:
        acc["fp"] += 1
    else:
        acc["tn"] += 1


def finalize_accumulator(acc: dict[str, Any]) -> dict[str, Any]:
    tp = acc["tp"]
    fn = acc["fn"]
    fp = acc["fp"]
    tn = acc["tn"]
    recall = _safe_div(tp, tp + fn)
    fpr = _safe_div(fp, fp + tn)
    precision = _safe_div(tp, tp + fp)
    f1 = _safe_div(2.0 * precision * recall, precision + recall)
    lat_sorted = sorted(acc["latencies"])
    median_ms = _median(lat_sorted)
    p95_ms = _p95(lat_sorted)
    return {
        "n": acc["n"],
        "confusion_level": acc["confusion_level"],
        "confusion_label": acc["confusion_label"],
        "risky_recall": recall,
        "false_positive_rate": fpr,
        "precision": precision,
        "f1": f1,
        "latency_median_ms": median_ms,
        "latency_p95_ms": p95_ms,
    }


def compute_group_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    acc = new_accumulator()
    for rec in records:
        update_accumulator(
            acc,
            str(rec.get("truth", "")),
            str(rec.get("pred_label", "")),
            str(rec.get("pred_level", "")),
            float(rec.get("latency_ms", rec.get("latency", 0.0))),
        )
    return finalize_accumulator(acc)


def build_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    overall_acc = new_accumulator()
    per_source_acc: dict[str, dict[str, Any]] = {}
    per_language_acc: dict[str, dict[str, Any]] = {}
    for rec in records:
        truth = str(rec.get("truth", ""))
        pred_label = str(rec.get("pred_label", ""))
        pred_level = str(rec.get("pred_level", ""))
        latency = float(rec.get("latency_ms", rec.get("latency", 0.0)))
        source = str(rec.get("source", ""))
        language = str(rec.get("language", ""))
        update_accumulator(overall_acc, truth, pred_label, pred_level, latency)
        if source not in per_source_acc:
            per_source_acc[source] = new_accumulator()
        update_accumulator(per_source_acc[source], truth, pred_label, pred_level, latency)
        if language not in per_language_acc:
            per_language_acc[language] = new_accumulator()
        update_accumulator(per_language_acc[language], truth, pred_label, pred_level, latency)
    per_source = {k: finalize_accumulator(v) for k, v in per_source_acc.items()}
    per_language = {k: finalize_accumulator(v) for k, v in per_language_acc.items()}
    return {
        "overall": finalize_accumulator(overall_acc),
        "per_source": per_source,
        "per_language": per_language,
    }


def _evidence_value(evidence: Any, key: str, default: Any = None) -> Any:
    if evidence is None:
        return default
    if isinstance(evidence, dict):
        return evidence.get(key, default)
    try:
        return evidence.get(key, default)
    except Exception:
        pass
    return getattr(evidence, key, default)


def extract_prediction(result: dict[str, Any]) -> tuple[str, str, float, float]:
    evidence = result.get("evidence") if isinstance(result, dict) else None
    pred_label_raw = _evidence_value(evidence, "label", "ham")
    pred_level_raw = _evidence_value(evidence, "level", "low")
    risk_raw = _evidence_value(evidence, "risk", 0.0)
    pred_label = str(pred_label_raw or "ham").strip().lower() or "ham"
    pred_level = str(pred_level_raw or "low").strip().lower() or "low"
    try:
        risk = float(risk_raw)
    except Exception:
        risk = 0.0
    latency = 0.0
    if isinstance(result, dict):
        timings = result.get("timings_ms") or {}
        if isinstance(timings, dict):
            raw_lat = timings.get("total_ms", timings.get("total", 0.0))
            try:
                latency = float(raw_lat)
            except Exception:
                latency = 0.0
    return pred_label, pred_level, risk, latency


def evaluate_rows(
    rows: Any, analyse_fn: Callable[[str], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if row is None:
            continue
        if not isinstance(row, dict):
            row = dict(row)
        text = row.get("text", "")
        if text is None:
            text = ""
        text = str(text)
        truth_raw = str(row.get("truth", "")).strip().lower()
        if truth_raw not in TRUTHS:
            raise ValueError(f"unknown truth label {truth_raw!r}: expected one of {TRUTHS}")
        truth = truth_raw
        source = str(row.get("source", "")).strip()
        language = str(row.get("language", "")).strip()
        result = analyse_fn(text)
        pred_label, pred_level, risk, latency = extract_prediction(result)
        records.append(
            {
                "text_hash": compute_text_hash(text),
                "source": source,
                "language": language,
                "truth": truth,
                "pred_label": pred_label,
                "pred_level": pred_level,
                "risk": float(risk),
                "latency_ms": float(latency),
            }
        )
    return records, build_report(records)


def evaluate_csv(
    csv_path: str | Path, analyse_fn: Callable[[str], dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return evaluate_rows(reader, analyse_fn)


def _parse_models_manifest(manifest_path: str | Path) -> dict[str, str]:
    """Parse models.sha256 lines "<hash>  <name>" into name -> hash."""
    hashes: dict[str, str] = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            digest = parts[0].strip().lower()
            name = parts[1].strip().lstrip("*").strip()
            if not name:
                continue
            hashes[name] = digest
            base = name.replace("\\", "/").rstrip("/").split("/")[-1]
            if base and base not in hashes:
                hashes[base] = digest
    return hashes


def _model_files_phone_linux_pairs() -> list[tuple[str, str]]:
    """Return (linux_rel, phone_name) pairs from sentinel/data/model_files.json."""
    pairs: list[tuple[str, str]] = []
    try:
        raw = json.loads((ROOT_DIR / "sentinel" / "data" / "model_files.json").read_text(encoding="utf-8"))
        files = raw.get("files") if isinstance(raw, dict) else None
        if isinstance(files, dict):
            for entry in files.values():
                if isinstance(entry, dict):
                    linux_rel = entry.get("linux")
                    phone = entry.get("phone")
                    if isinstance(linux_rel, str) and isinstance(phone, str) and linux_rel and phone:
                        pairs.append((linux_rel.replace("\\", "/"), phone))
    except Exception:
        return []
    return pairs


def _find_models_manifest(models_dir: str | None, explicit_manifest: str | None = None) -> str | None:
    """Return the first present models.sha256, or None when absent."""
    candidates: list[str] = []
    if explicit_manifest:
        candidates.append(os.path.expanduser(str(explicit_manifest)))
    env_manifest = os.getenv("PS3_MODELS_MANIFEST")
    if env_manifest:
        candidates.append(os.path.expanduser(env_manifest))
    if models_dir:
        candidates.append(os.path.join(os.path.expanduser(str(models_dir)), "models.sha256"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _candidate_manifest_names(file_path: Path, models_dir: str | None) -> set[str]:
    """Candidate manifest names for a file via basename, relative path, and role map."""
    names = {file_path.name}
    try:
        if models_dir:
            rel = file_path.resolve().relative_to(Path(os.path.expanduser(str(models_dir))).resolve())
            names.add(rel.as_posix())
    except Exception:
        pass
    for linux_rel, phone in _model_files_phone_linux_pairs():
        linux_base = linux_rel.rstrip("/").split("/")[-1]
        if file_path.name in (linux_base, phone):
            names.add(linux_rel)
            names.add(phone)
            names.add(linux_base)
        try:
            if models_dir:
                rel = file_path.resolve().relative_to(Path(os.path.expanduser(str(models_dir))).resolve()).as_posix()
                if rel == linux_rel:
                    names.add(phone)
        except Exception:
            continue
    return names


def verify_model_files_against_manifest(
    models_dir: str | None, file_paths: list[str | None], explicit_manifest: str | None = None
) -> None:
    """Fail hard when a present models.sha256 disagrees with a model file."""
    manifest_path = _find_models_manifest(models_dir, explicit_manifest)
    if manifest_path is None:
        return
    hashes = _parse_models_manifest(manifest_path)
    if not hashes:
        return
    for file_path in file_paths:
        if not file_path:
            continue
        p = Path(os.path.expanduser(str(file_path)))
        if not p.is_file():
            continue
        candidates = _candidate_manifest_names(p, models_dir)
        expected = next((hashes[name] for name in candidates if name in hashes), None)
        if expected is None:
            continue
        actual = sha256_file(p)
        if actual.lower() != expected.lower():
            raise RuntimeError(
                f"models manifest SHA-256 mismatch for {p}: "
                f"expected {expected}, got {actual} (manifest {manifest_path})"
            )


def _resolve_linux_path(models_dir: str, role: str, explicit: str | None, fallback: str) -> str:
    """Resolve a model path via the Linux model_files.json name, or the fallback."""
    if explicit:
        return os.path.expanduser(explicit)
    try:
        from sentinel.cli import linux_default_name

        rel = linux_default_name(role)
    except Exception:
        rel = fallback
    return os.path.join(os.path.expanduser(models_dir), rel)


def resolve_sms_model_path(models_dir: str, explicit: str | None) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    try:
        from sentinel.cli import linux_default_name

        rel = linux_default_name("sms_model")
    except Exception:
        rel = "sms_v6ml/sms_int8.pte"
    return os.path.join(os.path.expanduser(models_dir), rel)


def build_parser() -> argparse.ArgumentParser:
    from sentinel.advisor import DEFAULT_LLAMA_THREADS

    parser = argparse.ArgumentParser(description="Held-out evaluation (no Llama)")
    parser.add_argument("input_csv", help="Held-out CSV with text,truth,source,language,synthetic")
    default_models_dir = os.getenv("PS3_MODELS_DIR", os.path.expanduser("~/ps3/models"))
    default_llama_main = os.getenv(
        "PS3_LLAMA_MAIN",
        os.path.expanduser("~/ps3/executorch/cmake-out/examples/models/llama/llama_main"),
    )
    parser.add_argument("--models-dir", default=default_models_dir, help="Directory containing model files")
    parser.add_argument(
        "--models-manifest",
        default=os.getenv("PS3_MODELS_MANIFEST", None),
        help="Path to models.sha256 manifest (default: <models-dir>/models.sha256 when present)",
    )
    parser.add_argument("--url-model", default=None, help="Path to url model")
    parser.add_argument("--url-vocab", default=None, help="Path to url vocab")
    parser.add_argument("--sms-model", default=None, help="Path to sms model")
    parser.add_argument("--sms-tokenizer", default=None, help="Path to sms tokenizer directory")
    parser.add_argument("--llama-main", default=default_llama_main, help="Path to llama_main binary")
    parser.add_argument("--llama-model", default=None, help="Path to llama model")
    parser.add_argument("--llama-tokenizer", default=None, help="Path to llama tokenizer")
    parser.add_argument(
        "--llama-server",
        default=os.getenv("PS3_LLAMA_SERVER", ""),
        help="Path to sentinel_llama_server binary",
    )
    parser.add_argument("--threads", type=int, default=DEFAULT_LLAMA_THREADS, help="CPU threads")
    parser.add_argument("--out-json", default=None, help="JSON report path")
    parser.add_argument("--out-csv", default=None, help="Per-row predictions CSV path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = Path(args.input_csv)
    models_dir = os.path.expanduser(args.models_dir)
    sms_model_path = resolve_sms_model_path(models_dir, args.sms_model)
    sms_model_file = Path(sms_model_path).name
    sms_model_sha256 = ""
    if os.path.isfile(sms_model_path):
        sms_model_sha256 = sha256_file(sms_model_path)
    input_sha256 = sha256_file(str(input_path))
    git_commit = get_git_commit(ROOT_DIR)
    from sentinel.cli import load_detectors
    from sentinel.pipeline import analyse

    url_model_path = _resolve_linux_path(models_dir, "url_model", args.url_model, "url_v2/url_cnn_v2.pte")
    url_vocab_path = _resolve_linux_path(models_dir, "url_vocab", args.url_vocab, "url_v2/vocab.json")
    sms_tokenizer_path = _resolve_linux_path(models_dir, "sms_tokenizer_dir", args.sms_tokenizer, "sms_v6ml/tokenizer")
    verify_model_files_against_manifest(
        models_dir,
        [url_model_path, url_vocab_path, sms_model_path, sms_tokenizer_path],
        getattr(args, "models_manifest", None),
    )

    load_args = argparse.Namespace(
        models_dir=args.models_dir,
        url_model=args.url_model,
        url_vocab=args.url_vocab,
        sms_model=args.sms_model,
        sms_tokenizer=args.sms_tokenizer,
        no_llm=True,
        llama_main=args.llama_main,
        llama_model=args.llama_model,
        llama_tokenizer=args.llama_tokenizer,
        llama_server=args.llama_server,
        threads=args.threads,
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
        advisor = None

    if args.out_json:
        out_json = Path(args.out_json)
    else:
        out_json = input_path.with_name(input_path.stem + "_report.json")
    if args.out_csv:
        out_csv = Path(args.out_csv)
    else:
        out_csv = input_path.with_name(input_path.stem + "_predictions.csv")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with open(input_path, "r", encoding="utf-8", newline="") as fin, open(
        out_csv, "w", encoding="utf-8", newline=""
    ) as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(
            fout,
            fieldnames=["text_hash", "source", "language", "truth", "pred_label", "pred_level", "risk"],
        )
        writer.writeheader()
        for row in reader:
            text = row.get("text", "")
            if text is None:
                text = ""
            text = str(text)
            truth_raw = str(row.get("truth", "")).strip().lower()
            if truth_raw not in TRUTHS:
                raise ValueError(f"unknown truth label {truth_raw!r}: expected one of {TRUTHS}")
            truth = truth_raw
            source = str(row.get("source", "")).strip()
            language = str(row.get("language", "")).strip()
            result = analyse(text, url_det=url_det, sms_det=sms_det, advisor=None)
            pred_label, pred_level, risk, latency = extract_prediction(result)
            text_hash = compute_text_hash(text)
            writer.writerow(
                {
                    "text_hash": text_hash,
                    "source": source,
                    "language": language,
                    "truth": truth,
                    "pred_label": pred_label,
                    "pred_level": pred_level,
                    "risk": float(risk),
                }
            )
            records.append(
                {
                    "text_hash": text_hash,
                    "source": source,
                    "language": language,
                    "truth": truth,
                    "pred_label": pred_label,
                    "pred_level": pred_level,
                    "risk": float(risk),
                    "latency_ms": float(latency),
                }
            )
    summary = build_report(records)
    report = {
        "input_file": str(input_path),
        "input_sha256": input_sha256,
        "models_dir": str(models_dir),
        "sms_model_file": sms_model_file,
        "sms_model_sha256": sms_model_sha256,
        "git_commit": git_commit,
        "overall": summary["overall"],
        "per_source": summary["per_source"],
        "per_language": summary["per_language"],
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
