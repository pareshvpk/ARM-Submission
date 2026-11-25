"""Plug-in detector interface and evidence clamping for PS3 Sentinel.

Defines the Detector protocol and validation logic allowing secondary detectors
(e.g., Phase 2 network traffic analysis) to feed evidence into the fusion engine.
Mirrored on Android by org.ps3.sentinel.core.Detector contract.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)

# 0.0 and 1.0 — risk is a probability, so anything outside this range is a detector bug.
MIN_RISK = 0.0
MAX_RISK = 1.0


class Detector(Protocol):
    """Read-only contract for a plug-in detector that contributes evidence."""

    name: str
    version: str

    def score(self, text: str) -> dict[str, Any]:
        """Return one evidence part with name, version, risk and indicators."""
        ...


def clamp_risk(value: Any) -> float:
    """Clamp a detector risk to the 0..1 probability range.

    Args:
        value: Numeric risk value to clamp.

    Returns:
        Float clamped between MIN_RISK (0.0) and MAX_RISK (1.0). Returns MIN_RISK
        on non-numeric or non-finite inputs (NaN, Inf).
    """
    try:
        risk = float(value)
    except (TypeError, ValueError):
        return MIN_RISK
    if not math.isfinite(risk):
        return MIN_RISK
    return max(MIN_RISK, min(MAX_RISK, risk))


def _detector_attribute(detector: Any, attribute: str) -> str:
    """Read a detector attribute without letting a broken property escape."""
    try:
        return str(getattr(detector, attribute, "unknown"))
    except Exception:
        return "unknown"


def _part_from_result(raw: Any, detector: Any) -> dict[str, Any]:
    """Build one validated evidence part from a detector's raw score result."""
    if not isinstance(raw, dict):
        raise TypeError("score() must return a dict")
    indicators = raw.get("indicators", [])
    if not isinstance(indicators, (list, tuple)):
        indicators = []
    return {
        "name": str(raw.get("name", _detector_attribute(detector, "name"))),
        "version": str(raw.get("version", _detector_attribute(detector, "version"))),
        "risk": clamp_risk(raw.get("risk", MIN_RISK)),
        "indicators": [str(indicator) for indicator in indicators],
    }


def run_extra_detectors(text: str, detectors: Iterable[Any]) -> list[dict[str, Any]]:
    """Run plug-in detectors and return their clamped evidence parts.

    A detector that raises contributes no part. The failure is logged without
    the message text so SMS content never reaches the log.

    Args:
        text: SMS message text to score.
        detectors: Iterable of plug-in detector instances conforming to Detector.

    Returns:
        List of validated evidence part dicts with clamped risk and indicators.
    """
    parts: list[dict[str, Any]] = []
    for detector in detectors or ():
        try:
            parts.append(_part_from_result(detector.score(text), detector))
        except Exception as error:
            logger.warning(
                "extra detector %s failed: %s",
                _detector_attribute(detector, "name"),
                type(error).__name__,
            )
    return parts
