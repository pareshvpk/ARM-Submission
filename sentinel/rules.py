"""Load the shared detection rules exactly once when the package is imported.

The same rules.json file ships with the Android app, so a rule change can never
make the Linux CLI and the phone disagree. A missing or malformed file is a fatal
configuration error: this module raises instead of quietly using old defaults.
Mirrored on Android by org.ps3.sentinel.core.Rules and checked by parity tests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

RULES_FILE = Path(__file__).resolve().parent / "data" / "rules.json"

# The only schema this code understands. Bump it together with the readers.
SUPPORTED_SCHEMA_VERSION = 1


class RulesError(RuntimeError):
    """Raised when the shared rules file is missing, unreadable or malformed."""


def _require_dict(value: Any, name: str) -> dict:
    """Require value to be a dict, or raise RulesError."""
    if not isinstance(value, dict):
        raise RulesError(f"{RULES_FILE}: expected an object at {name}")
    return value


def _require_list(value: Any, name: str) -> list:
    """Require value to be a list, or raise RulesError."""
    if not isinstance(value, list):
        raise RulesError(f"{RULES_FILE}: expected a list at {name}")
    return value


def _read_string_list(container: dict, name: str, key: str) -> list[str]:
    """Read and validate a list of strings from container[key]."""
    values = _require_list(container.get(key), f"{name}.{key}")
    for index, item in enumerate(values):
        if not isinstance(item, str):
            raise RulesError(f"{RULES_FILE}: {name}.{key}[{index}] must be a string")
    return values


def _read_cue_rules(raw: Any) -> dict[str, Any]:
    """Parse and validate the cues section of the rules file."""
    cues = _require_dict(raw, "cues")
    type_order = _read_string_list(cues, "cues", "type_order")
    keywords_raw = _require_dict(cues.get("keywords"), "cues.keywords")
    regexes_raw = _require_dict(cues.get("regexes"), "cues.regexes")

    keywords: dict[str, list[str]] = {}
    regexes: dict[str, list[str]] = {}
    for cue_type in type_order:
        keywords[cue_type] = _read_string_list(keywords_raw, "cues.keywords", cue_type)
        patterns = _read_string_list(regexes_raw, "cues.regexes", cue_type)
        # Compile at load time so a bad pattern fails at startup, not mid-SMS.
        for index, pattern in enumerate(patterns):
            try:
                re.compile(pattern)
            except re.error as error:
                raise RulesError(
                    f"{RULES_FILE}: cues.regexes.{cue_type}[{index}] is not a valid regex: {error}"
                ) from error
        regexes[cue_type] = patterns

    return {"type_order": type_order, "keywords": keywords, "regexes": regexes}


def _read_fusion_rules(raw: Any) -> dict[str, Any]:
    """Parse and validate the fusion section of the rules file."""
    fusion = _require_dict(raw, "fusion")
    required_numbers = [
        "sms_temperature",
        "sms_scam_weight",
        "sms_unwanted_weight",
        "url_weight",
        "cue_weight",
        "cue_cap",
        "combo_score",
        "app_install_score",
        "collect_pin_score",
        "label_threshold",
        "high_level_threshold",
        "medium_level_threshold",
        "trusted_prob_cap",
        "url_phishing_label_threshold",
        "sms_ham_confidence_threshold",
    ]
    result: dict[str, Any] = {}
    for key in required_numbers:
        value = fusion.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RulesError(f"{RULES_FILE}: fusion.{key} must be a number")
        result[key] = float(value)

    decimals = fusion.get("risk_round_decimals")
    if not isinstance(decimals, int) or isinstance(decimals, bool):
        raise RulesError(f"{RULES_FILE}: fusion.risk_round_decimals must be an integer")
    if decimals < 0:
        raise RulesError(f"{RULES_FILE}: fusion.risk_round_decimals must be non-negative")
    result["risk_round_decimals"] = decimals
    return result


def _read_detector_versions(raw: Any) -> dict[str, str]:
    """Parse and validate detector version strings."""
    section = _require_dict(raw, "detector_versions")
    versions_raw = _require_dict(section.get("versions"), "detector_versions.versions")
    versions: dict[str, str] = {}
    for name, value in versions_raw.items():
        if not isinstance(value, str):
            raise RulesError(f"{RULES_FILE}: detector_versions.versions.{name} must be a string")
        versions[name] = value
    return versions


def _read_promotion_rules(raw: Any) -> dict[str, Any]:
    """Parse and validate the promotion_no_action (plain-promotion) section."""
    promotion = _require_dict(raw, "promotion_no_action")
    level = promotion.get("level")
    if not isinstance(level, str) or not level:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.level must be a non-empty string")
    label = promotion.get("label")
    if not isinstance(label, str) or not label:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.label must be a non-empty string")
    blocked_cue_types = _read_string_list(promotion, "promotion_no_action", "blocked_cue_types")
    phrase_regex = promotion.get("phone_digit_run_regex")
    if not isinstance(phrase_regex, str) or not phrase_regex:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.phone_digit_run_regex must be a non-empty string")
    try:
        re.compile(phrase_regex)
    except re.error as error:
        raise RulesError(
            f"{RULES_FILE}: promotion_no_action.phone_digit_run_regex is not a valid regex: {error}"
        ) from error
    phone_min_digits = promotion.get("phone_min_digits")
    if not isinstance(phone_min_digits, int) or isinstance(phone_min_digits, bool) or phone_min_digits <= 0:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.phone_min_digits must be a positive integer")
    reply_contact_phrases = _read_string_list(promotion, "promotion_no_action", "reply_contact_phrases")
    advice_text = promotion.get("advice_text")
    if not isinstance(advice_text, str) or not advice_text:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.advice_text must be a non-empty string")
    domain_like = promotion.get("domain_like_regex")
    if not isinstance(domain_like, str) or not domain_like:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.domain_like_regex must be a non-empty string")
    try:
        re.compile(domain_like)
    except re.error as error:
        raise RulesError(
            f"{RULES_FILE}: promotion_no_action.domain_like_regex is not a valid regex: {error}"
        ) from error
    at_handle = promotion.get("at_handle_regex")
    if not isinstance(at_handle, str) or not at_handle:
        raise RulesError(f"{RULES_FILE}: promotion_no_action.at_handle_regex must be a non-empty string")
    try:
        re.compile(at_handle)
    except re.error as error:
        raise RulesError(
            f"{RULES_FILE}: promotion_no_action.at_handle_regex is not a valid regex: {error}"
        ) from error
    return {
        "level": level,
        "label": label,
        "blocked_cue_types": blocked_cue_types,
        "phone_digit_run_regex": phrase_regex,
        "phone_min_digits": phone_min_digits,
        "reply_contact_phrases": reply_contact_phrases,
        "domain_like_regex": domain_like,
        "at_handle_regex": at_handle,
        "advice_text": advice_text,
    }


def _read_scam_scripts(raw: Any) -> list[dict[str, Any]]:
    """Parse and validate the scam_scripts section: named regex scripts with an indicator."""
    section = _require_dict(raw, "scam_scripts")
    scripts_raw = section.get("scripts")
    if not isinstance(scripts_raw, list):
        raise RulesError(f"{RULES_FILE}: scam_scripts.scripts must be a list")
    scripts: list[dict[str, Any]] = []
    for index, script_raw in enumerate(scripts_raw):
        where = f"scam_scripts.scripts[{index}]"
        script = _require_dict(script_raw, where)
        name = script.get("name")
        indicator = script.get("indicator")
        if not isinstance(name, str) or not name or not isinstance(indicator, str) or not indicator:
            raise RulesError(f"{RULES_FILE}: {where} needs a non-empty name and indicator")
        all_patterns = _read_string_list(script, where, "all")
        none_patterns = _read_string_list(script, where, "none")
        if not all_patterns:
            raise RulesError(f"{RULES_FILE}: {where}.all must not be empty")
        for pattern in all_patterns + none_patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise RulesError(f"{RULES_FILE}: {where} pattern {pattern!r} is not a valid regex: {error}") from error
        scripts.append({"name": name, "indicator": indicator, "all": all_patterns, "none": none_patterns})
    return scripts


def load_rules(path: Path = RULES_FILE) -> dict[str, Any]:
    """Read and validate the rules file, naming the file in every error message.

    Args:
        path: Path to rules.json, defaults to sentinel/data/rules.json.

    Returns:
        Validated configuration dictionary with cues, fusion parameters,
        detector versions, promotion rules, and known scam scripts.

    Raises:
        RulesError: If the file is missing, unreadable, invalid JSON, or malformed.
    """
    if not path.is_file():
        raise RulesError(f"Shared rules file not found: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RulesError(f"Could not read shared rules file {path}: {error}") from error
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise RulesError(f"Shared rules file {path} is not valid JSON: {error}") from error

    root = _require_dict(data, "root")
    schema_version = root.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise RulesError(
            f"{path}: unsupported schema_version {schema_version!r}; "
            f"this code supports {SUPPORTED_SCHEMA_VERSION}"
        )

    return {
        "schema_version": schema_version,
        "cues": _read_cue_rules(root.get("cues")),
        "fusion": _read_fusion_rules(root.get("fusion")),
        "detector_versions": _read_detector_versions(root.get("detector_versions")),
        "promotion_no_action": _read_promotion_rules(root.get("promotion_no_action")),
        "scam_scripts": _read_scam_scripts(root.get("scam_scripts")),
    }


# Loaded once at import. Readers use these names directly.
RULES = load_rules()
CUE_RULES = RULES["cues"]
FUSION_RULES = RULES["fusion"]
DETECTOR_VERSIONS = RULES["detector_versions"]
PROMOTION_RULES = RULES["promotion_no_action"]
SCAM_SCRIPT_RULES = RULES["scam_scripts"]
