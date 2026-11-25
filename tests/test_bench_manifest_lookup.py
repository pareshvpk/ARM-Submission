"""Deterministic manifest lookup for bench.run_bench model verification."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bench.run_bench import verify_model_files_against_manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(models: Path, entries: list[tuple[str, str]]) -> Path:
    manifest = models / "models.sha256"
    lines = [f"{digest}  {name}" for digest, name in entries]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def _two_folder_models(tmp_path: Path) -> tuple[Path, Path, Path]:
    models = tmp_path / "models"
    first = models / "sms_v2q" / "id_map.json"
    second = models / "sms_v6ml" / "id_map.json"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text('["first"]', encoding="utf-8")
    second.write_text('["second"]', encoding="utf-8")
    _write_manifest(
        models,
        [
            (_sha256(first), "sms_v2q/id_map.json"),
            (_sha256(second), "sms_v6ml/id_map.json"),
        ],
    )
    return models, first, second


def test_both_shared_base_name_files_verify(tmp_path):
    models, first, second = _two_folder_models(tmp_path)
    for model_file in (first, second):
        verify_model_files_against_manifest(str(models), [str(model_file)])


def test_changed_file_in_second_folder_raises_mismatch(tmp_path):
    models, _, second = _two_folder_models(tmp_path)
    second.write_text('["tampered"]', encoding="utf-8")
    with pytest.raises(RuntimeError, match="models manifest SHA-256 mismatch"):
        verify_model_files_against_manifest(str(models), [str(second)])


def test_single_folder_manifest_keyed_by_base_name_verifies(tmp_path):
    models = tmp_path / "models"
    model_file = models / "sms_v2q" / "id_map.json"
    model_file.parent.mkdir(parents=True)
    model_file.write_text('["only"]', encoding="utf-8")
    _write_manifest(models, [(_sha256(model_file), "id_map.json")])
    verify_model_files_against_manifest(str(models), [str(model_file)])


def test_ambiguous_base_name_is_skipped_when_no_specific_entry(tmp_path):
    models = tmp_path / "models"
    first = models / "sms_v2q" / "id_map.json"
    other = models / "sms_v5d" / "id_map.json"
    first.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    first.write_text('["first"]', encoding="utf-8")
    other.write_text('["other"]', encoding="utf-8")
    _write_manifest(
        models,
        [
            (_sha256(first), "sms_v2q/id_map.json"),
            (_sha256(other), "sms_v5d/id_map.json"),
        ],
    )
    unlisted = models / "sms_v6ml" / "id_map.json"
    unlisted.parent.mkdir(parents=True)
    unlisted.write_text('["unlisted"]', encoding="utf-8")
    verify_model_files_against_manifest(str(models), [str(unlisted)])
