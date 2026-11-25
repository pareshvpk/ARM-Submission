"""Tests for the generated advisor parity fixture."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MAKE_CASES_PATH = Path(__file__).with_name("make_advisor_cases.py")


def _load_case_builder():
    spec = importlib.util.spec_from_file_location("make_advisor_cases", MAKE_CASES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_advisor_fixture_is_up_to_date():
    builder = _load_case_builder()
    expected = builder.build_cases()
    actual = json.loads(builder.FIXTURE_PATH.read_text(encoding="utf-8"))
    assert actual == expected, "run python tests/make_advisor_cases.py after changing advisor"


def test_advisor_fixture_has_enough_cases():
    builder = _load_case_builder()
    fixture = json.loads(builder.FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(fixture["cases"]) >= 30
    assert len(fixture["templates"]) == 9
    assert any(case["raw_output"] == "" for case in fixture["cases"])
    assert any(case["expected"]["flags"] == ["refusal_fallback"] for case in fixture["cases"])
    assert any(case["expected"]["flags"] == ["contradiction_fallback"] for case in fixture["cases"])
