"""URL and SMS on-device classification detectors for PS3 Sentinel.

Implements ExecuTorch runtime inference for character-level URL CNN models
and MiniLM SMS classification, alongside heuristic URL indicator checks.
Mirrored on Android by org.ps3.sentinel.ml (UrlDetector, SmsDetector) and core.UrlIndicators.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from sentinel.rules import CUE_RULES, DETECTOR_VERSIONS, FUSION_RULES
from sentinel.url_features import normalise_url

# Brand official domains for brand lookalike detection
BRAND_DOMAINS: dict[str, set[str]] = {
    "sbi": {"onlinesbi.sbi", "sbi.co.in"},
    "hdfc": {"hdfcbank.com"},
    "icici": {"icicibank.com"},
    "axis": {"axisbank.com"},
    "kotak": {"kotak.com"},
    "paytm": {"paytm.com"},
    "phonepe": {"phonepe.com"},
    "gpay": {"google.com", "pay.google.com"},
    "amazon": {"amazon.in", "amazon.com"},
    "flipkart": {"flipkart.com"},
    "irctc": {"irctc.co.in"},
    "indiapost": {"indiapost.gov.in"},
    "uidai": {"uidai.gov.in"},
    "aadhaar": {"uidai.gov.in"},
    "npci": {"npci.org.in", "bhimupi.org.in"},
}

RISKY_TLDS: set[str] = {
    "xyz", "top", "site", "online", "live", "click", "icu", "buzz", "shop", "info",
}

SHORTENERS: set[str] = {
    "bit.ly", "tinyurl.com", "tinyurl", "goo.gl", "t.co", "cutt.ly", "rb.gy", "is.gd",
}

TWO_PART_SUFFIXES: set[str] = {
    "co.in", "gov.in", "org.in", "nic.in", "net.in", "ac.in",
    "co.uk", "org.uk", "com.au", "net.au", "org.au",
}


def _sha256_hex(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_manifest_text(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        sep = trimmed.find("  ")
        if sep > 0:
            hash_part = trimmed[:sep].strip()
            name = trimmed[sep + 2 :].strip()
        else:
            parts = trimmed.split(None, 1)
            if len(parts) != 2:
                continue
            hash_part, name = parts[0].strip(), parts[1].strip()
        if hash_part and name:
            entries[name] = hash_part
    return entries


def _find_models_manifest(pte_path: str) -> Path | None:
    parent = Path(pte_path).parent
    for candidate in (parent / "models.sha256", parent.parent / "models.sha256"):
        if candidate.is_file():
            return candidate
    return None


def _find_all_models_manifests(pte_path: str) -> list[Path]:
    parent = Path(pte_path).parent
    manifests: list[Path] = []
    for candidate in (parent / "models.sha256", parent.parent / "models.sha256"):
        if candidate.is_file() and candidate not in manifests:
            manifests.append(candidate)
    return manifests


def _load_manifest_entries(manifest_path: Path) -> dict[str, str]:
    try:
        return _parse_manifest_text(manifest_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(f"Cannot read model hash manifest {manifest_path}: {error}") from error


def _expected_hash(entries: dict[str, str], file_path: str, manifest_path: Path) -> str | None:
    name = Path(file_path).name
    candidates = [name]
    try:
        rel = Path(file_path).resolve().relative_to(manifest_path.parent.resolve())
        candidates.append(rel.as_posix())
    except Exception:
        pass
    for cand in candidates:
        if cand in entries:
            return entries[cand]
    return None


def _verify_file_against_manifest(file_path: str, entries: dict[str, str], manifest_path: Path) -> None:
    expected = _expected_hash(entries, file_path, manifest_path)
    name = Path(file_path).name
    if expected is None:
        raise RuntimeError(f"No expected hash for {name} in {manifest_path}; refusing to load")
    actual = _sha256_hex(file_path)
    if actual.lower() != expected.lower():
        raise RuntimeError(
            f"SHA-256 mismatch for {name}; refusing to load (expected {expected}, got {actual})"
        )


def verify_model_files(file_paths: Iterable[str], anchor_path: str | None = None) -> bool:
    """Verify every model input file against the models.sha256 manifest.

    Returns True when every file matched the manifest, and False when no
    manifest was found (in which case a warning naming the unverified
    files is printed to stderr and the caller must treat the detector as
    degraded). Refuses (RuntimeError) on a mismatch or when the manifest
    has no hash for a file. Both the model subdirectory and its parent are
    tried, so a models-root manifest copied into a subdirectory still
    verifies root-relative entries.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for p in file_paths:
        if p not in seen:
            seen.add(p)
            paths.append(p)
    if not paths:
        return True
    anchor = anchor_path or paths[0]
    manifest_paths = _find_all_models_manifests(anchor)
    if not manifest_paths:
        print(
            f"warning: no models.sha256 manifest found for {anchor}; "
            f"unverified model files: {', '.join(paths)}",
            file=sys.stderr,
        )
        return False
    manifest_entries = [(mp, _load_manifest_entries(mp)) for mp in manifest_paths]
    for p in paths:
        last_error: Exception | None = None
        for manifest_path, entries in manifest_entries:
            try:
                _verify_file_against_manifest(p, entries, manifest_path)
                last_error = None
                break
            except RuntimeError as error:
                last_error = error
                continue
        if last_error is not None:
            raise last_error
    return True


def verify_pte_hash(pte_path: str) -> bool:
    """Verify a .pte against models.sha256 next to the models, when present.

    Returns False (with a stderr warning naming the file) when no manifest
    exists; the caller must mark the detector degraded in that case.
    Refuses (RuntimeError) on a mismatch or when the manifest has no hash
    for the file.
    """
    return verify_model_files([pte_path], anchor_path=pte_path)


def _tokenizer_files(tokenizer_dir: str) -> list[str]:
    """Return every file under tokenizer_dir that the tokenizer may load."""
    path = Path(tokenizer_dir)
    if path.is_file():
        return [str(path)]
    if path.is_dir():
        return [str(p) for p in sorted(path.rglob("*")) if p.is_file()]
    return []


def get_registered_domain(host: str) -> str:
    """Return the registered domain (e.g. sbi.co.in or example.com).

    Args:
        host: Hostname string from parsed URL.

    Returns:
        Registered domain taking into account two-part public suffixes (.co.in, .gov.in).
    """
    if not host or not isinstance(host, str):
        return ""
    host = host.lower().strip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    suffix_2 = f"{parts[-2]}.{parts[-1]}"
    if suffix_2 in TWO_PART_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _parse_url_host(url: str) -> str | None:
    """Return the lower-case host, or None when the URL cannot be parsed."""
    try:
        parsed = urlparse(url if "://" in url else "http://" + url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    return host or None


def _ip_host_indicator(host: str) -> str | None:
    """Return 'ip_host' when host is a literal IP address."""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return "ip_host"
    except ValueError:
        return None


def _punycode_indicator(host: str) -> str | None:
    """Return 'punycode' when the host uses an IDN punycode label."""
    return "punycode" if "xn--" in host else None


def _at_sign_indicator(url: str) -> str | None:
    """Return 'at_sign' when the raw URL contains an @ (userinfo trick)."""
    return "at_sign" if "@" in url else None


def _many_subdomains_indicator(labels: list[str]) -> str | None:
    """Return 'many_subdomains' when the host has four or more labels."""
    return "many_subdomains" if len(labels) >= 4 else None


def _risky_tld_indicator(labels: list[str]) -> str | None:
    """Return 'risky_tld' when the final label is a known risky TLD."""
    tld = labels[-1] if labels else ""
    return "risky_tld" if tld in RISKY_TLDS else None


def _shortener_indicator(host: str, reg_dom: str) -> str | None:
    """Return 'shortener' when host or registered domain is a known shortener."""
    return "shortener" if (host in SHORTENERS or reg_dom in SHORTENERS) else None


def _brand_lookalike_indicator(host: str, reg_dom: str) -> str | None:
    """Return 'brand_lookalike' when a brand token appears on a non-official domain."""
    for brand, official_domains in BRAND_DOMAINS.items():
        if brand in host:
            if reg_dom not in official_domains and host not in official_domains:
                return "brand_lookalike"
    return None


def url_indicators(url: str) -> list[str]:
    """Extract security indicators from a URL without ever raising on bad input.

    Args:
        url: Raw URL string to inspect.

    Returns:
        List of identified security indicator strings, such as 'ip_host',
        'punycode', 'at_sign', 'many_subdomains', 'risky_tld', 'shortener',
        'brand_lookalike', or 'unparseable_url'.
    """
    if not url or not isinstance(url, str):
        return []

    host = _parse_url_host(url)
    if host is None:
        return ["unparseable_url"]

    labels = [part for part in host.split(".") if part]
    reg_dom = get_registered_domain(host)

    indicators: list[str] = []
    for indicator in (
        _ip_host_indicator(host),
        _punycode_indicator(host),
        _at_sign_indicator(url),
        _many_subdomains_indicator(labels),
        _risky_tld_indicator(labels),
        _shortener_indicator(host, reg_dom),
        _brand_lookalike_indicator(host, reg_dom),
    ):
        if indicator is not None:
            indicators.append(indicator)
    return indicators


# Cue regexes are compiled once at import so a message never pays the cost of
# recompiling the same patterns, and a bad pattern fails at startup (rules.py
# already validates them) rather than mid-message.
_CUE_KEYWORD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    cue_type: [re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
               for term in CUE_RULES["keywords"][cue_type]]
    for cue_type in CUE_RULES["type_order"]
}

_CUE_REGEX_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    cue_type: [re.compile(regex, re.IGNORECASE) for regex in CUE_RULES["regexes"][cue_type]]
    for cue_type in CUE_RULES["type_order"]
}


def _cue_match(cue_type: str, start: int, end: int, matched_text: str) -> dict[str, Any]:
    """Build one cue-span record."""
    return {"type": cue_type, "start": start, "end": end, "text": matched_text}


def sms_cues(text: str) -> list[dict[str, Any]]:
    """Extract cue spans with character offsets and type, using the shared rules."""
    if not text or not isinstance(text, str):
        return []

    matches: list[dict[str, Any]] = []
    for cue_type in CUE_RULES["type_order"]:
        for pattern in _CUE_KEYWORD_PATTERNS[cue_type]:
            for match in pattern.finditer(text):
                matches.append(_cue_match(cue_type, match.start(), match.end(), match.group(0)))

    # Extra patterns, such as the time bound in "blocked in 2 hours".
    for cue_type in CUE_RULES["type_order"]:
        for pattern in _CUE_REGEX_PATTERNS[cue_type]:
            for match in pattern.finditer(text):
                matches.append(_cue_match(cue_type, match.start(), match.end(), match.group(0)))

    # Sort by start ascending, then length descending
    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))

    # Deduplicate overlapping spans
    filtered: list[dict[str, Any]] = []
    last_end = -1
    for match in matches:
        if match["start"] >= last_end:
            filtered.append(match)
            last_end = match["end"]

    return filtered

def sigmoid(logit: float) -> float:
    """Map a model logit to 0..1 without overflowing for extreme values.

    math.exp(-logit) overflows when a corrupted model emits a very negative
    logit, so use the algebraically equal form that keeps the exponent <= 0.
    """
    if logit >= 0.0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_logit = math.exp(logit)
    return exp_logit / (1.0 + exp_logit)


class UrlDetector:
    """ExecuTorch-based URL Phishing Detector."""

    name = "url_detector"
    version = DETECTOR_VERSIONS["url_detector"]

    # No threshold parameter here: the single source of truth for the URL phishing
    # label is sentinel/data/rules.json (fusion.url_phishing_label_threshold), and
    # fuse re-labels URLs with that value, so a second knob would silently do nothing.
    def __init__(self, pte_path: str, vocab_path: str) -> None:
        """Load the URL model, vocabulary and ExecuTorch runtime."""
        self.pte_path = pte_path
        self.vocab_path = vocab_path
        self.hash_verified = verify_model_files([pte_path, vocab_path], anchor_path=pte_path)

        with open(vocab_path, "r", encoding="utf-8") as f:
            vdata = json.load(f)
        self.pad = vdata.get("pad", 0)
        self.unk = vdata.get("unk", 1)
        self.max_len = vdata.get("max_len", 200)
        self.chars = vdata.get("chars", {})

        try:
            import torch
            from executorch.runtime import Runtime
            self._torch = torch
            self._runtime = Runtime.get()
            self._program = self._runtime.load_program(pte_path)
            self._method = self._program.load_method("forward")
        except ImportError as e:
            raise ImportError(f"ExecuTorch or Torch not available: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load URL ExecuTorch program: {e}") from e

    def encode(self, url: str) -> Any:
        """Encode a URL into a fixed-length integer tensor for the model."""
        norm = normalise_url(url)
        chars = [self.chars.get(c, self.unk) for c in str(norm)[:self.max_len]]
        arr = [self.pad] * self.max_len
        arr[:len(chars)] = chars

        if hasattr(self, "_torch") and self._torch is not None:
            return self._torch.tensor([arr], dtype=self._torch.int64)
        raise RuntimeError("UrlDetector has no torch runtime; refusing to encode without a verified model load")

    def score(self, url: str) -> dict[str, Any]:
        """Run the URL model and return prob, label and indicators."""
        norm = normalise_url(url)
        inputs = self.encode(url)
        outputs = self._method.execute([inputs])
        logit_tensor = outputs[0]
        if hasattr(logit_tensor, "item"):
            logit = float(logit_tensor.item())
        else:
            logit = float(logit_tensor[0])

        prob = sigmoid(logit)
        # Label with the rules.json threshold (see __init__ comment) to match fuse.
        label = "phishing" if prob >= FUSION_RULES["url_phishing_label_threshold"] else "benign"
        indicators = url_indicators(url)

        return {
            "url": url,
            "norm_url": norm,
            "prob": float(prob),
            "label": label,
            "indicators": indicators,
        }


def _remap_scalar(value: Any, id_map: list[int]) -> int:
    """Map one token id through id_map, falling back to id_map[0] for out-of-range ids."""
    if not id_map:
        raise RuntimeError("id_map is empty; refusing to remap token ids")
    index = int(value)
    if 0 <= index < len(id_map):
        return id_map[index]
    return id_map[0]


def _remap_tensor(ids: Any, id_map: list[int]) -> Any:
    """Remap a torch-like tensor of ids, preserving device, dtype and shape."""
    import torch

    device = ids.device if hasattr(ids, "device") else None
    dtype = ids.dtype if hasattr(ids, "dtype") else torch.long
    flat = ids.flatten().tolist()
    mapped = [_remap_scalar(value, id_map) for value in flat]
    result = torch.tensor(mapped, dtype=dtype)
    if device is not None:
        result = result.to(device)
    return result.view_as(ids)


def _remap_sequence(ids: Any, id_map: list[int]) -> list[Any]:
    """Remap a nested list/tuple of ids, preserving nesting."""
    remapped: list[Any] = []
    for item in ids:
        if isinstance(item, (list, tuple)):
            remapped.append(remap_ids(item, id_map))
        else:
            remapped.append(_remap_scalar(item, id_map))
    return remapped


def remap_ids(ids: Any, id_map: list[int]) -> Any:
    """Pure function to remap token IDs through id_map.

    Args:
        ids: Token ID scalar, sequence, or PyTorch tensor.
        id_map: List mapping original tokenizer IDs to pruned model vocab indices.

    Returns:
        Remapped structure matching the input type and shape.
    """
    if hasattr(ids, "tolist"):
        return _remap_tensor(ids, id_map)
    if isinstance(ids, (list, tuple)):
        return _remap_sequence(ids, id_map)
    return _remap_scalar(ids, id_map)


class SmsDetector:
    """ExecuTorch-based SMS Classification Detector."""

    name = "sms_detector"
    version = DETECTOR_VERSIONS["sms_detector"]

    def __init__(self, pte_path: str, tokenizer_dir: str, id_map_path: str | None = None, is_dynamic: bool | None = None) -> None:
        """Load the SMS model, tokenizer and ExecuTorch runtime."""
        self.pte_path = pte_path
        self.tokenizer_dir = tokenizer_dir
        if id_map_path is None:
            id_map_path = str(Path(pte_path).with_name("id_map.json"))
        if not os.path.isfile(id_map_path):
            raise RuntimeError(
                f"id_map.json is required for SmsDetector; refusing to load (missing: {id_map_path})"
            )

        _input_files = [pte_path, id_map_path]
        _input_files.extend(_tokenizer_files(tokenizer_dir))
        self.hash_verified = verify_model_files(_input_files, anchor_path=pte_path)

        with open(id_map_path, "r", encoding="utf-8") as f:
            self.id_map = json.load(f)
        if not isinstance(self.id_map, list) or len(self.id_map) == 0:
            raise RuntimeError(f"id_map.json is empty or not a list; refusing to load {id_map_path}")

        try:
            from transformers import AutoTokenizer
        except ImportError as e:
            raise ImportError(f"transformers is required for SmsDetector: {e}") from e

        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir)

        try:
            import torch
            from executorch.runtime import Runtime
            self._torch = torch
            self._runtime = Runtime.get()
            self._program = self._runtime.load_program(pte_path)
            self._method = self._program.load_method("forward")
        except ImportError as e:
            raise ImportError(f"ExecuTorch or Torch not available: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load SMS ExecuTorch program: {e}") from e

        # A dynamic-seq export (export_sms.py --dynamic-seq) accepts any length 2..128;
        # a static one only 128. Probe once with a short input to find out.
        if is_dynamic is None:
            try:
                probe = self._torch.ones((1, 16), dtype=self._torch.int64)
                self._method.execute([probe, probe])
                is_dynamic = True
            except Exception:
                is_dynamic = False
        self.is_dynamic = bool(is_dynamic) and os.environ.get("PS3_SMS_STATIC") != "1"

    def predict(self, text: str) -> dict[str, Any]:
        """Tokenise, run the SMS model and return probs and label."""
        # Dynamic: real length, no padding (tokenizer always adds <s> and </s>, so length >= 2).
        enc = self.tokenizer(
            [text],
            padding=False if self.is_dynamic else "max_length",
            truncation=True,
            max_length=128,
            return_tensors="pt",
        )
        input_ids = enc["input_ids"].to(self._torch.int64)
        if self.id_map is not None:
            input_ids = remap_ids(input_ids, self.id_map)
        attention_mask = enc["attention_mask"].to(self._torch.int64)

        outputs = self._method.execute([input_ids, attention_mask])
        logits = outputs[0][0]
        import torch.nn.functional as F
        probs_tensor = F.softmax(logits, dim=-1)

        probs = {
            "ham": float(probs_tensor[0].item()),
            "unwanted": float(probs_tensor[1].item()),
            "scam": float(probs_tensor[2].item()),
        }
        label = max(probs, key=probs.get)
        return {"probs": probs, "label": label}
