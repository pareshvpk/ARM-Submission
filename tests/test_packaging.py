"""Packaging metadata: console script and package-data globs in pyproject.toml."""
from __future__ import annotations

import fnmatch
import importlib
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _config() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_console_script_target_is_importable_and_callable():
    target = _config()["project"]["scripts"]["sentinel"]
    module_name, _, attr_name = target.partition(":")
    assert module_name and attr_name, f"malformed console script target: {target}"
    module = importlib.import_module(module_name)
    entry = getattr(module, attr_name)
    assert callable(entry)


def test_package_data_glob_matches_shipped_json_files():
    globs = _config()["tool"]["setuptools"]["package-data"]["sentinel"]
    data_dir = ROOT / "sentinel" / "data"
    names = [p.name for p in data_dir.iterdir() if p.is_file()]
    matched = {
        name
        for name in names
        if any(fnmatch.fnmatch(f"data/{name}", pattern) for pattern in globs)
    }
    assert "rules.json" in matched
    assert "model_files.json" in matched
