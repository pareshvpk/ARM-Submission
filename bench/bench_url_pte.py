"""Benchmark the URL classifier .pte on the target device (ExecuTorch Python runtime).

Usage: python bench/bench_url_pte.py MODEL.pte VOCAB.json [--runs 1000] [--out results.json]
Records the fields the PS3 briefing asks for: device/OS, model, ExecuTorch version, latency, memory.
"""
import argparse
import hashlib
import json
import math
import os
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path

try:
    import resource
except ImportError:  # Windows has no resource module
    resource = None

try:
    import torch
    from executorch.runtime import Runtime
except ImportError:
    torch = None
    Runtime = None

ROOT_DIR = Path(__file__).resolve().parent.parent

SAMPLES = ["sbi-kyc-update.xyz/login", "onlinesbi.sbi/personal", "docs.google.com/forms/d/e/1FAIpQL/viewform",
           "amazon.in/gp/help/customer/display.html", "paytm-kyc-complete.online/login"]


def percentile_nearest_rank(sorted_vals, pct: float) -> float:
    """Standard nearest-rank percentile on already-sorted values."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    k = math.ceil((pct / 100.0) * n)
    idx = min(max(k - 1, 0), n - 1)
    return float(sorted_vals[idx])


def max_rss_mb() -> float:
    """Return peak RSS in MB, guarded for missing resource and platform units."""
    if resource is None:
        return 0.0
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform == "darwin":
            return float(ru.ru_maxrss) / (1024.0 * 1024.0)
        # Linux: kilobytes
        return float(ru.ru_maxrss) / 1024.0
    except Exception:
        return 0.0


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _parse_models_manifest(manifest_path):
    hashes = {}
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


def _model_files_phone_linux_pairs():
    pairs = []
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


def _find_models_manifest(pte_path, vocab_path, explicit_manifest=None):
    candidates = []
    if explicit_manifest:
        candidates.append(os.path.expanduser(str(explicit_manifest)))
    env_manifest = os.getenv("PS3_MODELS_MANIFEST")
    if env_manifest:
        candidates.append(os.path.expanduser(env_manifest))
    for base_path in (pte_path, vocab_path):
        if base_path:
            directory = os.path.dirname(os.path.abspath(str(base_path)))
            candidates.append(os.path.join(directory, "models.sha256"))
            candidates.append(os.path.join(os.path.dirname(directory), "models.sha256"))
    candidates.append(os.path.join(os.getcwd(), "models.sha256"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def verify_model_files_against_manifest(file_paths, pte_path=None, vocab_path=None, explicit_manifest=None):
    manifest_path = _find_models_manifest(pte_path, vocab_path, explicit_manifest)
    if manifest_path is None:
        return
    hashes = _parse_models_manifest(manifest_path)
    if not hashes:
        return
    pairs = _model_files_phone_linux_pairs()
    for file_path in file_paths:
        if not file_path:
            continue
        p = Path(os.path.expanduser(str(file_path)))
        if not p.is_file():
            continue
        candidates = {p.name}
        for linux_rel, phone in pairs:
            linux_base = linux_rel.rstrip("/").split("/")[-1]
            if p.name in (linux_base, phone):
                candidates.add(linux_rel)
                candidates.add(phone)
                candidates.add(linux_base)
        expected = next((hashes[name] for name in candidates if name in hashes), None)
        if expected is None:
            continue
        actual = _sha256_file(p)
        if actual.lower() != expected.lower():
            raise RuntimeError(
                f"models manifest SHA-256 mismatch for {p}: "
                f"expected {expected}, got {actual} (manifest {manifest_path})"
            )


def encode(url, vocab):
    ids = [vocab["chars"].get(c, vocab["unk"]) for c in url[:vocab["max_len"]]]
    return torch.tensor([ids + [vocab["pad"]] * (vocab["max_len"] - len(ids))], dtype=torch.long)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pte"); ap.add_argument("vocab")
    ap.add_argument("--runs", type=int, default=1000); ap.add_argument("--out")
    ap.add_argument(
        "--models-manifest",
        default=os.getenv("PS3_MODELS_MANIFEST", None),
        help="Path to models.sha256 manifest (default: models.sha256 next to the model when present)",
    )
    a = ap.parse_args()
    verify_model_files_against_manifest(
        [a.pte, a.vocab], pte_path=a.pte, vocab_path=a.vocab, explicit_manifest=a.models_manifest
    )
    vocab = json.load(open(a.vocab))
    t0 = time.perf_counter()
    meth = Runtime.get().load_program(a.pte).load_method("forward")
    load_ms = (time.perf_counter() - t0) * 1e3
    xs = [encode(u, vocab) for u in SAMPLES]
    for x in xs * 10:  # warm-up
        meth.execute([x])
    lat = []
    for i in range(a.runs):
        x = xs[i % len(xs)]
        t = time.perf_counter(); meth.execute([x]); lat.append((time.perf_counter() - t) * 1e3)
    lat.sort()
    scores = {u: round(float(torch.sigmoid(meth.execute([x])[0]).item()), 4) for u, x in zip(SAMPLES, xs)}
    r = {"device": platform.node(), "machine": platform.machine(), "os": platform.platform(),
         "executorch": version("executorch"), "torch": torch.__version__, "model": a.pte,
         "load_ms": round(load_ms, 2), "runs": a.runs,
         "p50_ms": round(percentile_nearest_rank(lat, 50.0), 4),
         "p95_ms": round(percentile_nearest_rank(lat, 95.0), 4),
         "max_rss_mb": round(max_rss_mb(), 1),
         "sample_scores": scores}
    print(json.dumps(r, indent=2))
    if a.out:
        json.dump(r, open(a.out, "w"), indent=2)


if __name__ == "__main__":
    main()
