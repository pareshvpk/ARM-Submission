"""Tooling backlog regression tests (C-18, R2C-14, R3B-9)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_show_results_usage_exit(tmp_path):
    script = ROOT / "bench" / "show_results.py"
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "usage" in (proc.stderr + proc.stdout).lower()


def test_show_results_non_numeric_timings(tmp_path):
    script = ROOT / "bench" / "show_results.py"
    payload = {"evidence": {"level": "high", "label": "scam", "risk": 0.9},
               "advice_source": "llm", "advice": "x",
               "timings_ms": {"total_ms": 12.6, "note": "n/a"}}
    f = tmp_path / "bench.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script), str(f)], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "n/a" in proc.stdout


def test_write_models_manifest_rejects_newline_phone(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "write_models_manifest",
        ROOT / "deploy" / "android" / "write_models_manifest.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    src = tmp_path / "model.pte"
    src.write_bytes(b"bytes")
    out = tmp_path / "models.sha256"
    with pytest.raises(ValueError, match="unsafe phone"):
        mod.write_manifest_from_pairs([(str(src), "evil\nurl_cnn_v2.pte")], str(out))


def test_make_heldout_empty_corpus_fails(monkeypatch):
    import bench.heldout.make_heldout as mh

    monkeypatch.setattr(mh, "load_corpus_hashes", lambda _dir: set())
    assert mh.main() == 1
