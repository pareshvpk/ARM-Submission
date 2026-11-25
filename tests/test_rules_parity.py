"""Tests for the shared rules file and the generated parity fixture."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sentinel.rules import RulesError, load_rules

MAKE_CASES_PATH = Path(__file__).with_name("make_parity_cases.py")


def _load_case_builder():
    spec = importlib.util.spec_from_file_location("make_parity_cases", MAKE_CASES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parity_fixture_is_up_to_date():
    builder = _load_case_builder()
    expected = builder.build_cases()
    actual = json.loads(builder.FIXTURE_PATH.read_text(encoding="utf-8"))
    assert actual == expected, "run python tests/make_parity_cases.py after changing rules"


def test_fixture_has_enough_cases():
    builder = _load_case_builder()
    fixture = json.loads(builder.FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(fixture["cases"]) >= 40
    assert any(case["sms_result"] is None for case in fixture["cases"])
    assert any(case["sms_result"] is not None for case in fixture["cases"])


def test_missing_rules_file_raises_clear_error(tmp_path):
    missing = tmp_path / "rules.json"
    with pytest.raises(RulesError) as error:
        load_rules(missing)
    assert str(missing) in str(error.value)


def test_malformed_rules_file_errors_name_the_file(tmp_path):
    malformed = tmp_path / "rules.json"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(RulesError) as error:
        load_rules(malformed)
    assert str(malformed) in str(error.value)


def test_unsupported_schema_version_raises(tmp_path):
    wrong_schema = tmp_path / "rules.json"
    wrong_schema.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(RulesError) as error:
        load_rules(wrong_schema)
    assert str(wrong_schema) in str(error.value)


def test_negative_risk_round_decimals_raises(tmp_path):
    rules_path = Path(__file__).resolve().parents[1] / "sentinel" / "data" / "rules.json"
    rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
    rules_data["fusion"]["risk_round_decimals"] = -1
    bad_rules = tmp_path / "rules.json"
    bad_rules.write_text(json.dumps(rules_data), encoding="utf-8")
    with pytest.raises(RulesError) as error:
        load_rules(bad_rules)
    assert "risk_round_decimals" in str(error.value)
