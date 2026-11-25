from __future__ import annotations

from sentinel.detector_api import clamp_risk, run_extra_detectors
from sentinel.pipeline import analyse


class _DummyDetector:
    """Fixed-risk plug-in detector used to prove the extension point works."""

    name = "phase2_network"
    version = "0.1"

    def __init__(self, risk: float = 0.9) -> None:
        self._risk = risk

    def score(self, text: str) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "risk": self._risk,
            "indicators": ["flow_alert"],
        }


class _BoomDetector:
    name = "boom"
    version = "0.0"

    def score(self, text: str) -> dict:
        raise RuntimeError("boom")


def _evidence_dict(result: dict) -> dict:
    evidence = result["evidence"]
    return evidence.to_dict() if hasattr(evidence, "to_dict") else evidence


def test_extra_detector_raises_level_and_appears_in_evidence() -> None:
    result = analyse("Hello friend, how are you?", extra_detectors=(_DummyDetector(0.9),))
    evidence = result["evidence"]

    assert evidence.level == "high"
    assert evidence.risk == 0.9
    assert evidence.extra_detectors[0]["name"] == "phase2_network"
    assert "phase2_network" in {
        part["name"] for part in _evidence_dict(result)["extra_detectors"]
    }


def test_failing_extra_detector_does_not_break_analyse(caplog) -> None:
    result = analyse("Hello friend, how are you?", extra_detectors=(_BoomDetector(),))

    assert result["evidence"].level == "low"
    assert result["evidence"].extra_detectors == []
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_no_extra_detectors_keeps_evidence_identical() -> None:
    messages = [
        "Hello friend, how are you?",
        "URGENT: your SBI account is blocked today. Update now: otp needed",
        "Your OTP for HDFC NetBanking is 482910. Do not share it with anyone.",
    ]

    for message in messages:
        assert _evidence_dict(analyse(message)) == _evidence_dict(
            analyse(message, extra_detectors=())
        )


def test_extra_detector_risk_is_clamped() -> None:
    parts = run_extra_detectors("hello", (_DummyDetector(1.7), _DummyDetector(-0.4)))

    assert [part["risk"] for part in parts] == [1.0, 0.0]

    result = analyse("hello", extra_detectors=(_DummyDetector(8.0),))
    assert result["evidence"].risk == 1.0


def test_clamp_risk_non_finite_is_zero() -> None:
    assert clamp_risk(float("nan")) == 0.0
    assert clamp_risk(float("inf")) == 0.0
    assert clamp_risk(float("-inf")) == 0.0
