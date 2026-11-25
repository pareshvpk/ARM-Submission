"""F-11: train_url_v2 must fail loudly if labels are inverted.

Loads only the pure sanity check from train_url_v2.py so the test
runs without torch, pandas, sklearn or pyarrow.
"""
import ast
from pathlib import Path

import pytest

TRAIN = Path(__file__).resolve().parents[1] / "training" / "url_v2" / "train_url_v2.py"
SANITY_NAMES = {"_well_known_host", "check_well_known_domains_not_phishing"}


def load_sanity_check():
    tree = ast.parse(TRAIN.read_text(encoding="utf-8"))
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "WELL_KNOWN_BENIGN_DOMAINS" for t in node.targets
        ):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<sanity>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in SANITY_NAMES:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<sanity>", "exec"), ns)
    assert "check_well_known_domains_not_phishing" in ns
    assert "WELL_KNOWN_BENIGN_DOMAINS" in ns
    return ns["check_well_known_domains_not_phishing"]


check = load_sanity_check()


def test_well_known_benign_passes():
    check(["google.com", "sbi.co.in", "irctc.co.in", "incometax.gov.in/x"], [0, 0, 0, 0], ["a"] * 4)


def test_well_known_subdomain_and_www_match():
    with pytest.raises(AssertionError, match=r"irctc\.co\.in"):
        check(["www.irctc.co.in/train"], [1], ["indian_parquets"])


def test_phishing_well_known_fails_with_source():
    with pytest.raises(AssertionError, match=r"google\.com.*source=global_parquets"):
        check(["https://www.google.com/"], [1], ["global_parquets"])


def test_gov_in_site_labelled_phishing_fails():
    with pytest.raises(AssertionError, match=r"source=src1"):
        check(["incometax.gov.in/iec"], [1], ["src1"])


def test_lookalike_not_matched():
    check(["sbi-kyc-update.xyz/login", "google-verify.xyz/login"], [1, 1], ["a", "a"])


def test_train_script_calls_check_after_labels_loaded():
    text = TRAIN.read_text(encoding="utf-8")
    assert "check_well_known_domains_not_phishing(df.norm_url, df.target, df.source)" in text
