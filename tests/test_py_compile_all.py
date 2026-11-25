"""Compile every tracked .py under training/, data/, bench/ and deploy/ (via git ls-files)."""
from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("training/", "data/", "bench/", "deploy/")


def _tracked_py_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, f"git ls-files failed: {out.stderr}"
    files = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    return [f for f in files if f.endswith(".py") and f.startswith(PREFIXES)]


def test_py_compile_all_tracked():
    files = _tracked_py_files()
    assert files, "no tracked .py files found under training/, data/, bench/, deploy/"
    errors: list[str] = []
    for rel in files:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: {exc}")
    assert not errors, "py_compile failures:\n" + "\n".join(errors)


def test_make_android_tokenizer_helpers_on_fake_tokenizer(tmp_path):
    sys.path.insert(0, str(REPO_ROOT))
    from training.sms.make_android_tokenizer import format_vocab_header, parse_tokenizer_vocab

    fake = {
        "model": {"vocab": [["<s>", 0.0], ["hello", -1.5], ["world", -2.0]], "unk_id": 3},
        "added_tokens": [
            {"content": "<s>", "id": 0},
            {"content": "<pad>", "id": 1},
            {"content": "</s>", "id": 2},
            {"content": "<mask>", "id": 99},
        ],
    }
    p = tmp_path / "tokenizer.json"
    p.write_text(json.dumps(fake), encoding="utf-8")
    tok_data = json.loads(p.read_text(encoding="utf-8"))
    meta = parse_tokenizer_vocab(tok_data)
    assert meta["vocab_size"] == 3
    assert meta["unk_id"] == 3
    assert meta["bos_id"] == 0
    assert meta["pad_id"] == 1
    assert meta["eos_id"] == 2
    assert meta["mask_id"] == 99
    assert meta["min_score"] == -2.0
    header = format_vocab_header(meta)
    assert header.startswith("# unk_id=3")
    assert "bos_id=0" in header
    assert "min_score=-2.00000000" in header


def test_make_android_tokenizer_compiles():
    path = REPO_ROOT / "training" / "sms" / "make_android_tokenizer.py"
    py_compile.compile(str(path), doraise=True)
