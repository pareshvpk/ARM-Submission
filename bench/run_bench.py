#!/usr/bin/env python3
"""Hardware benchmark runner for Arm Linux devices.

Measures Phase 1 KPIs from docs/requirements.md (NFR-02, NFR-03, NFR-04, NFR-09):
  1. mode 'detectors':
     - Loads SMS int8 model, URL model, regex cues and fusion (fails hard on error).
     - 20 warmup messages, then times all 1,000 benchmark messages end-to-end and per-stage.
     - Computes p50, p95, p99, min, max, mean latencies and RSS.
  2. mode 'llm':
     - Loads Llama 3.2 1B Instruct via ExecuTorch llama_main (fails hard on error).
     - Runs 50 medium/high-risk prompts from bench/llm_prompts.txt with SYNTHETIC
       evidence (SYNTHETIC_LLM_EVIDENCE=True): fuse() is fed fixed scam probs, so
       TTFT/decode/advice times measure Llama only, not the real detectors.
     - Parses PyTorchObserver JSON stats: TTFT, prefill tok/s, decode tok/s, advice latency.
  3. mode 'soak':
     - Loops over 1,000 messages for N minutes (default 30) with Llama on for medium/high risk.
     - Samples /proc/self/status VmRSS/VmHWM and CPU temperature every 30s.
     - Reports RSS growth percentage, peak RAM, and thermal stability.

Every JSON output contains a top-level 'record' block:
  device, os, kernel, cpu, python, executorch, torch, model files with sha256 & sizes,
  quantization notes, threads, temperature, offline flag, and timestamp.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sentinel.advisor import DEFAULT_LLAMA_THREADS, LlamaAdvisor
from sentinel.detectors import SmsDetector, UrlDetector, sms_cues, url_indicators
from sentinel.fusion import fuse
from sentinel.pipeline import analyse
from sentinel.url_features import extract_urls, normalise_url


# -----------------------------------------------------------------------------
# System and Environment Inspection Helpers
# -----------------------------------------------------------------------------

def get_cpu_info() -> str:
    """Extract CPU model name or architecture from /proc/cpuinfo or platform."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if ":" in line:
                    key, val = [x.strip() for x in line.split(":", 1)]
                    if key.lower() in ("model name", "hardware", "cpu architecture"):
                        return val
    except Exception:
        pass
    return platform.processor() or platform.machine()


def get_os_info() -> str:
    """Return OS pretty name from /etc/os-release or platform."""
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return platform.platform()


def get_cpu_temp() -> str:
    """Read CPU temperature from the Linux thermal zone when available."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            millicelsius = float(f.read().strip())
            return f"temp={millicelsius / 1000.0:.1f}'C"
    except Exception:
        return "temp=unknown"


def _default_route_present(proc_net_route_text: str) -> bool:
    """Return True if /proc/net/route text contains a default route (dest 0.0.0.0)."""
    lines = proc_net_route_text.strip().splitlines()
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        dest = parts[1] if len(parts) > 1 else ""
        gateway = parts[2] if len(parts) > 2 else "00000000"
        if dest == "00000000" and gateway not in ("00000000", "", "0"):
            return True
    return False


def _read_proc_stat() -> str | None:
    """Read /proc/stat text, or None when unavailable (for example on Windows)."""
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return None


def _proc_stat_cpu_ticks(text: str) -> dict[str, tuple[int, int]]:
    """Return label -> (busy, total) jiffies from a /proc/stat snapshot."""
    ticks: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        label = parts[0]
        if label != "cpu" and not label[3:].isdigit():
            continue
        values: list[int] = []
        for raw in parts[1:9]:
            try:
                values.append(int(raw))
            except ValueError:
                values.append(0)
        while len(values) < 8:
            values.append(0)
        user, nice, system, idle, iowait, irq, softirq, steal = values
        busy = user + nice + system + irq + softirq + steal
        total = busy + idle + iowait
        ticks[label] = (busy, total)
    return ticks


def cpu_util_from_proc_stat(prev_text: str, curr_text: str) -> tuple[float | None, list[float] | None]:
    """Overall and per-core CPU utilisation (%) between two /proc/stat snapshots."""
    before = _proc_stat_cpu_ticks(prev_text)
    after = _proc_stat_cpu_ticks(curr_text)
    if not before or not after:
        return None, None

    def util(label: str) -> float | None:
        if label not in before or label not in after:
            return None
        prev_busy, prev_total = before[label]
        curr_busy, curr_total = after[label]
        delta_total = curr_total - prev_total
        delta_busy = curr_busy - prev_busy
        if delta_total <= 0:
            return None
        return round(100.0 * delta_busy / delta_total, 3)

    overall = util("cpu")
    cores: list[float] = []
    index = 0
    while f"cpu{index}" in after or f"cpu{index}" in before:
        value = util(f"cpu{index}")
        if value is not None:
            cores.append(value)
        index += 1
    return overall, (cores or None)


def sample_cpu_util(prev_text: str | None, curr_text: str | None) -> dict[str, Any]:
    """CPU fields for a result; both null when /proc/stat is unavailable."""
    if prev_text is None or curr_text is None:
        return {"cpu_util_percent": None, "cpu_util_percent_per_core": None}
    overall, per_core = cpu_util_from_proc_stat(prev_text, curr_text)
    return {"cpu_util_percent": overall, "cpu_util_percent_per_core": per_core}


def check_is_offline() -> bool:
    """Check if internet connectivity is reachable (offline test verification).

    Preferred: inspect the default route in /proc/net/route on Linux.
    Fallback (non-Linux / no /proc): weak UDP probe, test-only — a bare UDP
    connect succeeds without a route, so it can report online when offline.
    """
    try:
        from pathlib import Path as _P

        route_file = _P("/proc/net/route")
        if route_file.is_file():
            text = route_file.read_text(encoding="utf-8", errors="ignore")
            return not _default_route_present(text)
    except Exception:
        pass
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 53))
        s.close()
        return False
    except Exception:
        return True


def _ru_maxrss_to_mb(ru_maxrss: float | int) -> float:
    """Convert ru_maxrss to MB by platform (Linux KB, macOS bytes)."""
    if sys.platform == "darwin":
        return float(ru_maxrss) / (1024.0 * 1024.0)
    return float(ru_maxrss) / 1024.0


def get_proc_status_rss() -> dict[str, float]:
    """Read VmRSS and VmHWM in MB from /proc/self/status."""
    res = {"vm_rss_mb": 0.0, "vm_hwm_mb": 0.0}
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        res["vm_rss_mb"] = round(float(parts[1]) / 1024.0, 2)
                elif line.startswith("VmHWM:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        res["vm_hwm_mb"] = round(float(parts[1]) / 1024.0, 2)
    except Exception:
        try:
            import resource

            ru = resource.getrusage(resource.RUSAGE_SELF)
            res["vm_hwm_mb"] = round(_ru_maxrss_to_mb(ru.ru_maxrss), 2)
            res["vm_rss_mb"] = res["vm_hwm_mb"]
        except Exception:
            pass
    return res

def get_children_ru_maxrss_mb() -> float:
    """Return RUSAGE_CHILDREN ru_maxrss in MB."""
    try:
        import resource

        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        return round(_ru_maxrss_to_mb(ru.ru_maxrss), 2)
    except Exception:
        return 0.0


def get_live_children_pids(parent_pid: int | None = None) -> set[int]:
    """Find all live descendant child process IDs for parent_pid by walking /proc/*/stat."""
    if parent_pid is None:
        parent_pid = os.getpid()

    ppid_map: dict[int, int] = {}
    if not os.path.isdir("/proc"):
        return set()

    try:
        for entry in os.scandir("/proc"):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            pid = int(entry.name)
            stat_path = os.path.join(entry.path, "stat")
            try:
                with open(stat_path, "r", encoding="utf-8") as f:
                    content = f.read()
                rparen = content.rfind(")")
                if rparen != -1:
                    rest = content[rparen + 1:].split()
                    if len(rest) >= 2:
                        ppid = int(rest[1])
                        ppid_map[pid] = ppid
            except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
                continue
    except Exception:
        pass

    children: set[int] = set()
    to_visit = [parent_pid]
    while to_visit:
        curr = to_visit.pop()
        for p, pp in ppid_map.items():
            if pp == curr and p not in children:
                children.add(p)
                to_visit.append(p)
    return children


def get_summed_process_tree_rss_mb(root_pid: int | None = None) -> float:
    """Return the summed VmRSS in MB of root_pid plus all its live children."""
    if root_pid is None:
        root_pid = os.getpid()

    target_pids = {root_pid} | get_live_children_pids(root_pid)
    total_rss_mb = 0.0

    for pid in target_pids:
        status_path = f"/proc/{pid}/status"
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            total_rss_mb += float(parts[1]) / 1024.0
                        break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        except Exception:
            pass

    return round(total_rss_mb, 2)


def inspect_file(path: str | None, quant_note: str) -> dict[str, Any] | None:
    """Return size, sha256, and quantization metadata for a model file."""
    if not path:
        return None
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        return {
            "path": str(p),
            "exists": False,
            "quantization": quant_note,
        }
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return {
        "path": str(p),
        "exists": True,
        "size_bytes": p.stat().st_size,
        "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
        "sha256": h.hexdigest(),
        "quantization": quant_note,
    }


def _sha256_file(path: str | Path) -> str:
    """Return lowercase hex SHA-256 of a file, streamed in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


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


def _candidate_manifest_names(file_path: Path, models_dir: str | None) -> list[str]:
    """Return candidate manifest names for a file, most specific first.

    Order is the models-directory-relative path, the role-map relative path,
    the phone name, then the bare base name. The base name is last because
    several model folders can share one (for example id_map.json), so the
    caller only uses it when the manifest has no conflicting hash for it.
    """
    names: list[str] = []
    rel_name: str | None = None
    if models_dir:
        try:
            rel_name = file_path.resolve().relative_to(
                Path(os.path.expanduser(str(models_dir))).resolve()
            ).as_posix()
        except (OSError, ValueError):
            rel_name = None
    role_names: list[str] = []
    phone_names: list[str] = []
    for linux_rel, phone in _model_files_phone_linux_pairs():
        linux_base = linux_rel.rstrip("/").split("/")[-1]
        if file_path.name in (linux_base, phone) or (rel_name is not None and rel_name == linux_rel):
            role_names.append(linux_rel)
            phone_names.append(phone)
    for candidate in (rel_name, *role_names, *phone_names):
        if candidate and candidate != file_path.name and candidate not in names:
            names.append(candidate)
    names.append(file_path.name)
    return names


def _expected_manifest_hash(hashes: dict[str, str], candidates: list[str]) -> str | None:
    """Return the most specific manifest hash, using the base name only if unambiguous."""
    base_name = candidates[-1]
    for name in candidates[:-1]:
        if name in hashes:
            return hashes[name]
    matching = {
        digest
        for name, digest in hashes.items()
        if name.replace("\\", "/").rstrip("/").split("/")[-1] == base_name
    }
    if len(matching) == 1:
        return next(iter(matching))
    return None


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
        expected = _expected_manifest_hash(hashes, candidates)
        if expected is None:
            continue
        actual = _sha256_file(p)
        if actual.lower() != expected.lower():
            raise RuntimeError(
                f"models manifest SHA-256 mismatch for {p}: "
                f"expected {expected}, got {actual} (manifest {manifest_path})"
            )


def build_record_block(args: argparse.Namespace, inspected_models: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the mandatory top-level record block required by PS3 evaluation spec."""
    et_ver = "unknown"
    try:
        from importlib.metadata import version
        et_ver = version("executorch")
    except Exception:
        pass

    torch_ver = "unknown"
    try:
        import torch
        torch_ver = torch.__version__
    except Exception:
        pass

    return {
        "device": platform.node(),
        "os": get_os_info(),
        "kernel": platform.release(),
        "cpu": get_cpu_info(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "executorch": et_ver,
        "torch": torch_ver,
        "threads": getattr(args, "threads", DEFAULT_LLAMA_THREADS),
        "temp": get_cpu_temp(),
        "offline": check_is_offline(),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "models": inspected_models,
    }


def _percentile_nearest_rank(sorted_vals: list[float], pct: float) -> float:
    """Standard nearest-rank percentile: sorted[ceil(p/100 * N) - 1], clamped."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    import math

    k = math.ceil((pct / 100.0) * n)
    idx = min(max(k - 1, 0), n - 1)
    return float(sorted_vals[idx])


def calc_stats(latencies: list[float], unit: str = "ms") -> dict[str, float]:
    """Compute p50, p95, p99, max, mean, min summary stats (nearest-rank)."""
    if not latencies:
        return {}
    s = sorted(latencies)
    n = len(s)
    p50 = _percentile_nearest_rank(s, 50.0)
    p95 = _percentile_nearest_rank(s, 95.0)
    p99 = _percentile_nearest_rank(s, 99.0)
    mean_val = sum(s) / n
    return {
        f"p50_{unit}": round(p50, 3),
        f"p95_{unit}": round(p95, 3),
        f"p99_{unit}": round(p99, 3),
        f"mean_{unit}": round(mean_val, 3),
        f"min_{unit}": round(s[0], 3),
        f"max_{unit}": round(s[-1], 3),
        "count": n,
    }


# -----------------------------------------------------------------------------
# Path Resolution & Strict Model Loading
# -----------------------------------------------------------------------------

def resolve_model_path(explicit: str | None, candidates: list[str]) -> str | None:
    if explicit:
        exp = os.path.expanduser(explicit)
        if os.path.exists(exp):
            return exp
        return explicit  # Return for explicit error handling
    for c in candidates:
        exp = os.path.expanduser(c)
        if os.path.exists(exp):
            return exp
    return candidates[0] if candidates else None


def load_detectors_strict(args: argparse.Namespace) -> tuple[UrlDetector, SmsDetector, list[dict[str, Any]]]:
    """Load URL and SMS detectors strictly. Any failure MUST abort with error."""
    models_dir = os.path.expanduser(args.models_dir)

    url_pte = resolve_model_path(
        args.url_model,
        [
            os.path.join(models_dir, "url_v2", "url_cnn_v2.pte"),
            os.path.join(models_dir, "url_model.pte"),
            os.path.join(models_dir, "url_cnn_v2.pte"),
        ],
    )
    url_vocab = resolve_model_path(
        args.url_vocab,
        [
            os.path.join(models_dir, "url_v2", "vocab.json"),
            os.path.join(models_dir, "vocab.json"),
        ],
    )

    if not url_pte or not os.path.isfile(url_pte):
        raise FileNotFoundError(f"Strict load failure: URL model file not found: {url_pte}")
    if not url_vocab or not os.path.isfile(url_vocab):
        raise FileNotFoundError(f"Strict load failure: URL vocab file not found: {url_vocab}")

    verify_model_files_against_manifest(
        models_dir, [url_pte, url_vocab], getattr(args, "models_manifest", None)
    )

    sys.stderr.write(f"[run_bench] Loading URL detector: {url_pte} with vocab: {url_vocab}\n")
    try:
        url_det = UrlDetector(url_pte, url_vocab)
    except Exception as e:
        raise RuntimeError(f"Strict load failure: Failed to initialise UrlDetector: {e}") from e

    sms_pte = resolve_model_path(
        args.sms_model,
        [
            os.path.join(models_dir, "sms_v6ml", "sms_int8.pte"),
        ],
    )
    sms_tok = resolve_model_path(
        args.sms_tokenizer,
        [
            os.path.join(models_dir, "sms_v6ml", "tokenizer"),
        ],
    )
    sms_id_map = resolve_model_path(
        args.sms_id_map,
        [
            os.path.join(models_dir, "sms_v6ml", "id_map.json"),
        ],
    )

    if not sms_pte or not os.path.isfile(sms_pte):
        raise FileNotFoundError(f"Strict load failure: SMS model file not found: {sms_pte}")
    if not sms_tok or not (os.path.isdir(sms_tok) or os.path.isfile(sms_tok)):
        raise FileNotFoundError(f"Strict load failure: SMS tokenizer directory not found: {sms_tok}")
    if not sms_id_map or not os.path.isfile(sms_id_map):
        raise FileNotFoundError(f"Strict load failure: SMS id_map file not found: {sms_id_map}")

    verify_model_files_against_manifest(
        models_dir, [sms_pte, sms_tok, sms_id_map], getattr(args, "models_manifest", None)
    )

    sys.stderr.write(f"[run_bench] Loading SMS detector: {sms_pte} with tokenizer: {sms_tok}\n")
    try:
        sms_det = SmsDetector(sms_pte, sms_tok, id_map_path=sms_id_map)
    except Exception as e:
        raise RuntimeError(f"Strict load failure: Failed to initialise SmsDetector: {e}") from e

    inspected = [
        inspect_file(url_pte, "ExecuTorch .pte, XNNPACK, fp32"),
        inspect_file(url_vocab, "character vocabulary mapping"),
        inspect_file(sms_pte, "ExecuTorch .pte, XNNPACK, static int8 quantized"),
        inspect_file(sms_id_map, "token ID vocabulary mapping"),
    ]
    return url_det, sms_det, [x for x in inspected if x is not None]


def load_llama_strict(args: argparse.Namespace) -> tuple[LlamaAdvisor, list[dict[str, Any]]]:
    """Load Llama advisor strictly. Any failure MUST abort with error."""
    models_dir = os.path.expanduser(args.models_dir)
    llama_main = os.path.expanduser(args.llama_main)

    llama_pte = resolve_model_path(
        args.llama_model,
        [
            os.path.join(models_dir, "llama32_1b", "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"),
            os.path.join(models_dir, "llama32_et_community", "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"),
            os.path.join(models_dir, "llama.pte"),
            os.path.join(models_dir, "llama32_1b.pte"),
        ],
    )
    llama_tok = resolve_model_path(
        args.llama_tokenizer,
        [
            os.path.join(models_dir, "llama32_1b", "tokenizer.model"),
            os.path.join(models_dir, "llama32_et_community", "tokenizer.model"),
            os.path.join(models_dir, "tokenizer.bin"),
            os.path.join(models_dir, "tokenizer.model"),
        ],
    )

    if not os.path.isfile(llama_main):
        raise FileNotFoundError(f"Strict load failure: llama_main runner binary not found: {llama_main}")
    if not os.access(llama_main, os.X_OK):
        raise PermissionError(f"Strict load failure: llama_main is not executable: {llama_main}")
    if not llama_pte or not os.path.isfile(llama_pte):
        raise FileNotFoundError(f"Strict load failure: Llama model .pte not found: {llama_pte}")
    if not llama_tok or not os.path.isfile(llama_tok):
        raise FileNotFoundError(f"Strict load failure: Llama tokenizer not found: {llama_tok}")

    verify_model_files_against_manifest(
        models_dir, [llama_pte, llama_tok], getattr(args, "models_manifest", None)
    )

    llama_server_raw = getattr(args, "llama_server", "") or None
    llama_server = os.path.expanduser(llama_server_raw) if llama_server_raw else None
    if llama_server is not None and not os.path.isfile(llama_server):
        raise FileNotFoundError(
            f"Strict load failure: explicit llama_server binary not found: {llama_server}"
        )
    sys.stderr.write(f"[run_bench] Initialising LlamaAdvisor: {llama_main} with {llama_pte} ({args.threads} threads)\n")
    try:
        advisor = LlamaAdvisor(
            llama_main=llama_main,
            model_path=llama_pte,
            tokenizer_path=llama_tok,
            threads=args.threads,
            llama_server=llama_server,
        )
    except Exception as e:
        raise RuntimeError(f"Strict load failure: Failed to instantiate LlamaAdvisor: {e}") from e

    inspected = [
        inspect_file(llama_main, "Llama C++ native executable"),
        inspect_file(llama_pte, "ExecuTorch SpinQuant INT4 weights / 8-bit dynamic activations"),
        inspect_file(llama_tok, "SentencePiece tokenizer binary"),
    ]
    if llama_server is not None:
        inspected.append(
            inspect_file(llama_server, "Llama resident server binary (optional)")
        )
    return advisor, [x for x in inspected if x is not None]


def load_lines(path: str) -> list[str]:
    """Read non-empty lines from file."""
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"Input file not found: {p}")
    lines: list[str] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
    return lines


# -----------------------------------------------------------------------------
# Mode Implementations
# -----------------------------------------------------------------------------

def run_detectors_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Run detector pipeline benchmark over 1,000 messages (NFR-02)."""
    url_det, sms_det, model_meta = load_detectors_strict(args)
    record = build_record_block(args, model_meta)

    messages = load_lines(args.bench_messages)
    total_msgs = len(messages)
    sys.stderr.write(f"[run_bench:detectors] Loaded {total_msgs} messages from {args.bench_messages}\n")

    cpu_stat_before = _read_proc_stat()

    # Warmup 20 messages
    warmup_n = min(20, total_msgs)
    sys.stderr.write(f"[run_bench:detectors] Running warmup over {warmup_n} messages...\n")
    for i in range(warmup_n):
        w_text = messages[i]
        w_urls = extract_urls(w_text)
        w_url_res = [url_det.score(u) for u in w_urls]
        w_cues = sms_cues(w_text)
        w_sms_res = sms_det.predict(w_text)
        fuse(w_text, w_sms_res, w_url_res, w_cues)

    sys.stderr.write("[run_bench:detectors] Benchmarking 1,000 messages end-to-end and per-stage...\n")

    lat_url_extraction: list[float] = []
    lat_url_detection: list[float] = []
    lat_cues: list[float] = []
    lat_sms_detection: list[float] = []
    lat_fusion: list[float] = []
    lat_total: list[float] = []

    for idx, text in enumerate(messages):
        t_start = time.perf_counter()

        # 1. URL extraction
        t0 = time.perf_counter()
        extracted = extract_urls(text)
        lat_url_extraction.append((time.perf_counter() - t0) * 1000.0)

        # 2. URL scoring
        t0 = time.perf_counter()
        url_results = [url_det.score(u) for u in extracted]
        lat_url_detection.append((time.perf_counter() - t0) * 1000.0)

        # 3. SMS cues
        t0 = time.perf_counter()
        cues = sms_cues(text)
        lat_cues.append((time.perf_counter() - t0) * 1000.0)

        # 4. SMS detector
        t0 = time.perf_counter()
        sms_res = sms_det.predict(text)
        lat_sms_detection.append((time.perf_counter() - t0) * 1000.0)

        # 5. Fusion
        t0 = time.perf_counter()
        fuse(text, sms_res, url_results, cues)
        lat_fusion.append((time.perf_counter() - t0) * 1000.0)

        total_elapsed = (time.perf_counter() - t_start) * 1000.0
        lat_total.append(total_elapsed)

        if (idx + 1) % 250 == 0 or (idx + 1) == total_msgs:
            sys.stderr.write(f"  Processed {idx + 1}/{total_msgs} messages...\n")

    cpu_util = sample_cpu_util(cpu_stat_before, _read_proc_stat())
    mem_usage = get_proc_status_rss()
    total_stats = calc_stats(lat_total)
    p95_total = total_stats.get("p95_ms", 0.0)
    target_p95 = 50.0
    nfr02_evaluable = total_stats.get("count", 0) > 0
    pass_nfr02 = (p95_total <= target_p95) if nfr02_evaluable else None

    nfr02: dict[str, Any] = {
        "nfr_id": "NFR-02",
        "description": "Detector latency (SMS + URLs + fusion) <= 50 ms p95 on Arm Linux",
        "target_p95_ms": target_p95,
        "measured_p95_ms": p95_total,
        "pass": pass_nfr02,
        "evaluable": nfr02_evaluable,
    }
    if not nfr02_evaluable:
        nfr02["note"] = "not evaluable: no latency samples"

    results = {
        "record": record,
        "mode": "detectors",
        "nfr": nfr02,
        "num_messages": total_msgs,
        "warmup_messages": warmup_n,
        "timings_ms": {
            "total": calc_stats(lat_total),
            "stages": {
                "url_extraction": calc_stats(lat_url_extraction),
                "url_detection": calc_stats(lat_url_detection),
                "cues": calc_stats(lat_cues),
                "sms_detection": calc_stats(lat_sms_detection),
                "fusion": calc_stats(lat_fusion),
            },
        },
        "memory": mem_usage,
        "cpu_util_percent": cpu_util["cpu_util_percent"],
        "cpu_util_percent_per_core": cpu_util["cpu_util_percent_per_core"],
        "temp_end": get_cpu_temp(),
    }
    return results


# Synthetic evidence isolates Llama timing from detector/fusion changes, so
# detector regressions do not move this benchmark; it is not an accuracy measure.
SYNTHETIC_LLM_EVIDENCE = True


def run_llm_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Run Llama advisory benchmark over 50 prompts (NFR-03)."""
    advisor, model_meta = load_llama_strict(args)
    record = build_record_block(args, model_meta)

    prompts = load_lines(args.llm_prompts)
    total_prompts = len(prompts)
    sys.stderr.write(f"[run_bench:llm] Loaded {total_prompts} prompts from {args.llm_prompts}\n")

    ttft_list: list[float] = []
    prefill_tps_list: list[float] = []
    decode_tps_list: list[float] = []
    advice_time_list: list[float] = []
    generated_tokens_list: list[int] = []

    prompt_details: list[dict[str, Any]] = []
    cpu_stat_before = _read_proc_stat()

    for idx, prompt_text in enumerate(prompts):
        sys.stderr.write(f"[run_bench:llm] Prompt {idx + 1}/{total_prompts}...\n")
        # Build evidence for high-risk message
        urls = extract_urls(prompt_text)
        url_results = [
            {
                "url": u,
                "norm_url": normalise_url(u),
                "prob": 0.90,
                "label": "phishing",
                "indicators": url_indicators(u),
            }
            for u in urls
        ]
        cues = sms_cues(prompt_text)
        sms_res = {"probs": {"ham": 0.05, "unwanted": 0.15, "scam": 0.80}, "label": "scam"}
        ev = fuse(prompt_text, sms_res, url_results, cues)

        t_wall_start = time.perf_counter()
        raw_advice, stats = advisor.generate(prompt_text, ev)
        wall_time_s = time.perf_counter() - t_wall_start

        inf_start = stats.get("inference_start_ms", 0)
        first_tok = stats.get("first_token_ms", 0)
        inf_end = stats.get("inference_end_ms", 0)

        if first_tok > inf_start > 0:
            ttft_s = (first_tok - inf_start) / 1000.0
        else:
            ttft_s = wall_time_s

        prefill_tps = float(stats.get("prefill_token_per_sec", 0.0))
        decode_tps = float(stats.get("decode_token_per_sec", 0.0))

        if inf_end > inf_start > 0:
            advice_time_s = (inf_end - inf_start) / 1000.0
        else:
            advice_time_s = wall_time_s

        gen_tokens = int(stats.get("generated_tokens", len(raw_advice.split())))

        ttft_list.append(ttft_s)
        if prefill_tps > 0:
            prefill_tps_list.append(prefill_tps)
        if decode_tps > 0:
            decode_tps_list.append(decode_tps)
        advice_time_list.append(advice_time_s)
        generated_tokens_list.append(gen_tokens)

        prompt_details.append({
            "idx": idx + 1,
            "text_sha256_prefix": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12],
            "prompt_path": stats.get("prompt_path"),
            "ttft_s": round(ttft_s, 3),
            "prefill_tok_s": round(prefill_tps, 2),
            "decode_tok_s": round(decode_tps, 2),
            "advice_time_s": round(advice_time_s, 3),
            "generated_tokens": gen_tokens,
            "advice_sha256_prefix": hashlib.sha256(raw_advice.encode("utf-8")).hexdigest()[:12],
        })

    cpu_util = sample_cpu_util(cpu_stat_before, _read_proc_stat())

    if hasattr(advisor, "close"):
        advisor.close()
    stats_ttft = calc_stats(ttft_list, unit="s")
    stats_prefill = calc_stats(prefill_tps_list, unit="tps")
    stats_decode = calc_stats(decode_tps_list, unit="tps")
    stats_total_time = calc_stats(advice_time_list, unit="s")

    # NFR-03 checks: TTFT <= 2s, decode >= 8 tok/s, advice <= 15s
    p95_ttft = stats_ttft.get("p95_s", 0.0)
    p50_decode = stats_decode.get("p50_tps", 0.0)
    p95_time = stats_total_time.get("p95_s", 0.0)

    nfr03_evaluable = all(
        s.get("count", 0) > 0 for s in (stats_ttft, stats_decode, stats_total_time)
    )
    if nfr03_evaluable:
        pass_ttft: bool | None = p95_ttft <= 2.0
        pass_decode: bool | None = p50_decode >= 8.0
        pass_time: bool | None = p95_time <= 15.0
        pass_nfr03: bool | None = pass_ttft and pass_decode and pass_time
    else:
        pass_ttft = pass_decode = pass_time = None
        pass_nfr03 = None

    results = {
        "record": record,
        "mode": "llm",
        "synthetic_evidence": SYNTHETIC_LLM_EVIDENCE,
        "nfr": {
            "nfr_id": "NFR-03",
            "description": "Llama TTFT <= 2.0 s, decode >= 8.0 tok/s, full advice <= 15.0 s",
            "targets": {
                "ttft_p95_s": 2.0,
                "decode_p50_tps": 8.0,
                "advice_p95_s": 15.0,
            },
            "measured": {
                "ttft_p95_s": p95_ttft,
                "decode_p50_tps": p50_decode,
                "advice_p95_s": p95_time,
            },
            "pass": pass_nfr03,
            "pass_ttft": pass_ttft,
            "pass_decode": pass_decode,
            "pass_time": pass_time,
            "evaluable": nfr03_evaluable,
            **({"note": "not evaluable: no latency samples"} if not nfr03_evaluable else {}),
        },
        "num_prompts": total_prompts,
        "cpu_util_percent": cpu_util["cpu_util_percent"],
        "cpu_util_percent_per_core": cpu_util["cpu_util_percent_per_core"],
        "metrics": {
            "ttft_seconds": stats_ttft,
            "prefill_tokens_per_sec": stats_prefill,
            "decode_tokens_per_sec": stats_decode,
            "total_advice_time_seconds": stats_total_time,
        },
        "memory": {
            "vm_rss_mb": get_proc_status_rss()["vm_rss_mb"],
            "vm_hwm_mb": get_proc_status_rss()["vm_hwm_mb"],
            "python_vm_hwm_mb": get_proc_status_rss()["vm_hwm_mb"],
            "children_ru_maxrss_mb": get_children_ru_maxrss_mb(),
            "upper_bound_rss_mb": round(get_proc_status_rss()["vm_hwm_mb"] + get_children_ru_maxrss_mb(), 2),
            "peak_total_rss_mb": round(get_proc_status_rss()["vm_hwm_mb"] + get_children_ru_maxrss_mb(), 2),
        },
        "python_vm_hwm_mb": get_proc_status_rss()["vm_hwm_mb"],
        "children_ru_maxrss_mb": get_children_ru_maxrss_mb(),
        "upper_bound_rss_mb": round(get_proc_status_rss()["vm_hwm_mb"] + get_children_ru_maxrss_mb(), 2),
        "peak_total_rss_mb": round(get_proc_status_rss()["vm_hwm_mb"] + get_children_ru_maxrss_mb(), 2),
        "prompt_samples": prompt_details,
        "temp_end": get_cpu_temp(),
    }
    return results


def run_soak_bench(args: argparse.Namespace) -> dict[str, Any]:
    """Run 30-minute continuous soak test with memory and thermal monitoring (NFR-04, NFR-09)."""
    url_det, sms_det, det_meta = load_detectors_strict(args)
    advisor, llama_meta = load_llama_strict(args)
    record = build_record_block(args, det_meta + llama_meta)

    messages = load_lines(args.bench_messages)
    if not messages:
        raise ValueError("no benchmark messages")
    soak_min = float(args.soak_min)
    soak_sec = soak_min * 60.0

    sys.stderr.write(f"[run_bench:soak] Starting {soak_min} min ({soak_sec:.0f}s) continuous soak test...\n")

    t_start = time.perf_counter()
    last_sample_t = t_start
    sample_interval_s = 30.0

    stop_sampler = threading.Event()
    sampled_tree_rss_values: list[float] = []

    def sampler_worker():
        while not stop_sampler.is_set():
            val = get_summed_process_tree_rss_mb()
            if val > 0.0:
                sampled_tree_rss_values.append(val)
            stop_sampler.wait(0.5)

    sampler_thread = threading.Thread(target=sampler_worker, daemon=True)
    sampler_thread.start()

    init_rss = get_proc_status_rss()
    init_tree_rss = get_summed_process_tree_rss_mb()
    if init_tree_rss <= 0.0:
        init_tree_rss = init_rss["vm_rss_mb"]

    samples: list[dict[str, Any]] = [
        {
            "elapsed_s": 0.0,
            "total_rss_mb": round(init_tree_rss, 2),
            "rss_mb": init_rss["vm_rss_mb"],
            "hwm_mb": init_rss["vm_hwm_mb"],
            "temp": get_cpu_temp(),
            "messages_processed": 0,
            "llama_invocations": 0,
        }
    ]

    msg_idx = 0
    msgs_done = 0
    llama_invocations = 0

    while (time.perf_counter() - t_start) < soak_sec:
        text = messages[msg_idx % len(messages)]
        msg_idx += 1

        res = analyse(text, url_det=url_det, sms_det=sms_det, advisor=advisor)
        msgs_done += 1
        if res.get("advice_source") == "llm":
            llama_invocations += 1

        now = time.perf_counter()
        if now - last_sample_t >= sample_interval_s:
            cur_rss = get_proc_status_rss()
            cur_tree_rss = get_summed_process_tree_rss_mb()
            interval_peak_tree_rss = max(sampled_tree_rss_values[-65:]) if sampled_tree_rss_values else cur_tree_rss
            effective_total_rss = max(cur_tree_rss, interval_peak_tree_rss)
            if effective_total_rss <= 0.0:
                effective_total_rss = cur_rss["vm_rss_mb"]

            cur_temp = get_cpu_temp()
            elapsed = round(now - t_start, 1)

            sample_entry = {
                "elapsed_s": elapsed,
                "total_rss_mb": round(effective_total_rss, 2),
                "rss_mb": cur_rss["vm_rss_mb"],
                "hwm_mb": cur_rss["vm_hwm_mb"],
                "temp": cur_temp,
                "messages_processed": msgs_done,
                "llama_invocations": llama_invocations,
            }
            samples.append(sample_entry)
            last_sample_t = now
            sys.stderr.write(
                f"[run_bench:soak] {elapsed:5.1f}s / {soak_sec:.0f}s | msgs: {msgs_done} "
            )

    # Stop sampler thread and take final sample
    stop_sampler.set()
    sampler_thread.join(timeout=2.0)

    final_now = time.perf_counter()
    final_rss = get_proc_status_rss()
    final_tree_rss = get_summed_process_tree_rss_mb()
    if final_tree_rss <= 0.0:
        final_tree_rss = final_rss["vm_rss_mb"]

    samples.append({
        "elapsed_s": round(final_now - t_start, 1),
        "total_rss_mb": round(final_tree_rss, 2),
        "rss_mb": final_rss["vm_rss_mb"],
        "hwm_mb": final_rss["vm_hwm_mb"],
        "temp": get_cpu_temp(),
        "messages_processed": msgs_done,
        "llama_invocations": llama_invocations,
    })

    python_vm_hwm_mb = final_rss["vm_hwm_mb"]
    children_ru_maxrss_mb = get_children_ru_maxrss_mb()
    upper_bound_mb = round(python_vm_hwm_mb + children_ru_maxrss_mb, 2)

    # peak_total_rss_mb as the largest summed sample
    all_summed_samples = [s.get("total_rss_mb", 0.0) for s in samples]
    if sampled_tree_rss_values:
        all_summed_samples.extend(sampled_tree_rss_values)
    peak_total_rss_mb = round(max(all_summed_samples), 2) if all_summed_samples else upper_bound_mb

    initial_rss_mb = samples[0]["rss_mb"]
    final_rss_mb = samples[-1]["rss_mb"]
    peak_rss_mb = max(s["hwm_mb"] for s in samples)
    if initial_rss_mb > 0:
        rss_growth_pct = round(((final_rss_mb - initial_rss_mb) / initial_rss_mb) * 100.0, 2)
    else:
        rss_growth_pct = 0.0

    # NFR evaluation:
    # NFR-04: Peak RAM <= 2.5 GB (2500 MB)
    pass_nfr04 = peak_total_rss_mb <= 2500.0
    # NFR-09: 30 min soak without throttling failure, memory growth <= 10%
    pass_nfr09 = rss_growth_pct <= 10.0

    results = {
        "record": record,
        "mode": "soak",
        "nfr": {
            "nfr_04": {
                "metric": "peak_total_rss_mb",
                "target_peak_mb": 2500.0,
                "measured_peak_mb": peak_total_rss_mb,
                "pass": pass_nfr04,
            },
            "nfr_09": {
                "target_growth_pct": 10.0,
                "measured_growth_pct": rss_growth_pct,
                "pass": pass_nfr09,
            },
        },
        "soak_minutes_configured": soak_min,
        "soak_seconds_elapsed": round(final_now - t_start, 2),
        "messages_processed": msgs_done,
        "llama_invocations": llama_invocations,
        "initial_rss_mb": initial_rss_mb,
        "final_rss_mb": final_rss_mb,
        "peak_rss_mb": peak_rss_mb,
        "peak_total_rss_mb": peak_total_rss_mb,
        "python_vm_hwm_mb": python_vm_hwm_mb,
        "children_ru_maxrss_mb": children_ru_maxrss_mb,
        "upper_bound_rss_mb": upper_bound_mb,
        "rss_growth_percent": rss_growth_pct,
        "samples": samples,
        "memory": {
            "peak_total_rss_mb": peak_total_rss_mb,
            "python_vm_hwm_mb": python_vm_hwm_mb,
            "children_ru_maxrss_mb": children_ru_maxrss_mb,
            "upper_bound_rss_mb": upper_bound_mb,
            "vm_rss_mb": final_rss["vm_rss_mb"],
            "vm_hwm_mb": python_vm_hwm_mb,
        },
    }
    return results


# -----------------------------------------------------------------------------
# Main CLI & Dispatcher
# -----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_bench",
        description="One-command Phase 1 Hardware Benchmark Kit for Arm Linux",
    )
    parser.add_argument(
        "--mode",
        choices=["detectors", "llm", "soak", "all"],
        default="detectors",
        help="Benchmark mode to execute (default: detectors)",
    )
    # Also allow mode as positional argument if provided
    parser.add_argument(
        "positional_mode",
        nargs="?",
        choices=["detectors", "llm", "soak", "all"],
        default=None,
        help="Positional shorthand for mode",
    )

    default_models = os.getenv("PS3_MODELS_DIR", os.path.expanduser("~/ps3/models"))
    default_llama = os.getenv(
        "PS3_LLAMA_MAIN",
        os.path.expanduser("~/ps3/executorch/cmake-out/examples/models/llama/llama_main"),
    )

    parser.add_argument("--models-dir", default=default_models, help="Base directory for models")
    parser.add_argument(
        "--models-manifest",
        default=os.getenv("PS3_MODELS_MANIFEST", None),
        help="Path to models.sha256 manifest (default: <models-dir>/models.sha256 when present)",
    )
    parser.add_argument("--llama-main", default=default_llama, help="Path to llama_main binary")
    parser.add_argument(
        "--llama-server",
        default=os.getenv("PS3_LLAMA_SERVER", ""),
        help="Path to sentinel_llama_server binary (optional resident server)",
    )
    parser.add_argument("--url-model", default=None, help="Path to url_model.pte")
    parser.add_argument("--url-vocab", default=None, help="Path to vocab.json")
    parser.add_argument("--sms-model", default=None, help="Path to sms_int8.pte")
    parser.add_argument("--sms-tokenizer", default=None, help="Path to SMS tokenizer dir")
    parser.add_argument("--sms-id-map", default=None, help="Path to id_map.json")
    parser.add_argument("--llama-model", default=None, help="Path to Llama .pte")
    parser.add_argument("--llama-tokenizer", default=None, help="Path to Llama tokenizer")
    parser.add_argument(
        "--threads", type=int, default=DEFAULT_LLAMA_THREADS, help="CPU threads for inference (default: %(default)s)"
    )

    parser.add_argument(
        "--bench-messages",
        default=str(ROOT_DIR / "bench" / "bench_messages.txt"),
        help="Path to 1,000 benchmark messages",
    )
    parser.add_argument(
        "--llm-prompts",
        default=str(ROOT_DIR / "bench" / "llm_prompts.txt"),
        help="Path to 50 LLM evaluation prompts",
    )
    parser.add_argument(
        "--soak-min",
        type=float,
        default=30.0,
        help="Duration in minutes for soak test (default: 30.0)",
    )
    parser.add_argument("--out", "-o", default=None, help="Output JSON path (optional)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    mode = args.positional_mode or args.mode
    args.mode = mode

    ts_slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = ROOT_DIR / "bench" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    try:
        if mode == "detectors":
            res = run_detectors_bench(args)
            default_out = results_dir / f"arm_linux_detectors_{ts_slug}.json"
        elif mode == "llm":
            res = run_llm_bench(args)
            default_out = results_dir / f"arm_linux_llm_{ts_slug}.json"
        elif mode == "soak":
            res = run_soak_bench(args)
            default_out = results_dir / f"arm_linux_soak_{ts_slug}.json"
        elif mode == "all":
            sys.stderr.write("[run_bench] Running all benchmarks in sequence...\n")
            det_res = run_detectors_bench(args)
            llm_res = run_llm_bench(args)
            soak_res = run_soak_bench(args) if args.soak_min > 0 else {}
            res = {
                "record": det_res["record"],
                "mode": "all",
                "detectors": det_res,
                "llm": llm_res,
                "soak": soak_res,
            }
            default_out = results_dir / f"arm_linux_all_{ts_slug}.json"
        else:
            sys.stderr.write(f"Unknown mode: {mode}\n")
            return 1

        out_path = Path(args.out) if args.out else default_out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)

        sys.stdout.write(json.dumps(res, indent=2) + "\n")
        sys.stderr.write(f"\n[run_bench] Benchmark completed successfully. Saved to: {out_path}\n")
        return 0

    except Exception as e:
        sys.stderr.write(f"\nFATAL: Benchmark failed with error: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
