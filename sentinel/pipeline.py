"""End-to-end detection and advisory pipeline for PS3 Sentinel.

Coordinates URL extraction, URL scoring, SMS classification, cue matching,
evidence fusion, and LLM or template advice generation with strict error isolation.
Mirrored on Android by org.ps3.sentinel.Pipeline.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from sentinel.advisor import PROMOTION_ADVICE, guard, is_plain_promotion, template_advice
from sentinel.detector_api import run_extra_detectors
from sentinel.detectors import sms_cues, url_indicators
from sentinel.fusion import Evidence, fuse
from sentinel.url_features import extract_urls, normalise_url

logger = logging.getLogger(__name__)


def _safe_url_indicators(url: Any) -> list[str]:
    """Call url_indicators without ever raising."""
    try:
        return list(url_indicators(url))
    except Exception:
        return []


def _safe_normalise_url(url: Any) -> str:
    """Call normalise_url without ever raising."""
    try:
        return str(normalise_url(url))
    except Exception:
        try:
            return str(url).lower()
        except Exception:
            return ""


def _extract_urls_safe(text: Any) -> list[Any]:
    """Extract URLs from text, returning an empty list on any failure."""
    try:
        extracted = extract_urls(text)
        if not isinstance(extracted, list):
            extracted = list(extracted) if extracted is not None else []
        return extracted
    except Exception:
        return []


def _short_digest(value: Any) -> str:
    """Return the first 8 hex chars of the SHA-256 of value (mirrors sha256Short)."""
    try:
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]
    except Exception:
        return "unknown"


def _heuristic_url_prob(indicators: list[str]) -> float:
    if "brand_lookalike" in indicators or "risky_tld" in indicators or "ip_host" in indicators:
        return 0.85
    if indicators:
        return 0.4
    return 0.05


def _score_url_with_detector(url: Any, url_det: Any) -> dict[str, Any]:
    """Score one URL using the detector, falling back to heuristics on failure."""
    try:
        if url_det is not None:
            url_error = False
            try:
                result = url_det.score(url)
                if isinstance(result, dict):
                    return result
                url_error = True
                logger.warning("URL model failed on %s, using indicators: unexpected result", _short_digest(url))
            except Exception as error:
                url_error = True
                logger.warning("URL model failed on %s, using indicators: %s", _short_digest(url), error)

            indicators = _safe_url_indicators(url)
            prob = _heuristic_url_prob(indicators)
            if url_error and "url_model_error" not in indicators:
                indicators = indicators + ["url_model_error"]
            return {
                "url": url,
                "norm_url": _safe_normalise_url(url),
                "prob": prob,
                "label": "phishing" if prob >= 0.5 else "benign",
                "indicators": indicators,
            }

        indicators = _safe_url_indicators(url)
        prob = _heuristic_url_prob(indicators)
        return {
            "url": url,
            "norm_url": _safe_normalise_url(url),
            "prob": prob,
            "label": "phishing" if prob >= 0.5 else "benign",
            "indicators": indicators,
        }
    except Exception:
        return {
            "url": url,
            "norm_url": _safe_normalise_url(url),
            "prob": 0.0,
            "label": "benign",
            "indicators": [],
        }


def _safe_sms_cues(text: Any) -> list[dict[str, Any]]:
    """Extract SMS cues without ever raising."""
    try:
        cues = sms_cues(text)
        if not isinstance(cues, list):
            return []
        return cues
    except Exception:
        return []


def _safe_sms_predict(text: Any, sms_det: Any) -> dict[str, Any] | None:
    """Run the SMS detector without ever raising."""
    result, _ = _safe_sms_predict_detailed(text, sms_det)
    return result


def _safe_sms_predict_detailed(text: Any, sms_det: Any) -> tuple[dict[str, Any] | None, bool]:
    """Run the SMS detector, reporting whether it raised."""
    if sms_det is None:
        return None, False
    try:
        return sms_det.predict(text), False
    except Exception:
        return None, True


def _safe_fuse(
    text: Any,
    sms_result: Any,
    url_results: list[Any],
    cues: list[Any],
    extra_parts: list[dict[str, Any]] | None = None,
    sender: str | None = None,
) -> Evidence:
    """Fuse evidence without ever raising, retrying rule-only on fusion failure."""
    try:
        return fuse(text, sms_result, url_results, cues, extra_parts, sender)
    except Exception as e:
        logger.warning('safe_fuse: fusion attempt failed (%s); trying fallback', type(e).__name__)
        try:
            evidence = fuse(text, None, url_results, cues, extra_parts, sender)
            if "analysis_error" not in evidence.indicators:
                evidence.indicators.append("analysis_error")
            return evidence
        except Exception as e:
            logger.warning('safe_fuse: fusion attempt failed (%s); trying fallback', type(e).__name__)
            try:
                evidence = fuse(text, None, [], cues, extra_parts, sender)
                if "analysis_error" not in evidence.indicators:
                    evidence.indicators.append("analysis_error")
                return evidence
            except Exception as e:
                logger.warning('safe_fuse: fusion attempt failed (%s); trying fallback', type(e).__name__)
                return Evidence(label="unwanted", risk=0.4, level="medium", threshold=0.7, indicators=["analysis_error"])


def _run_advisor(text: Any, evidence: Evidence, advisor: Any) -> tuple[str, str]:
    """Run the advisor (or template) and return (advice, advice_source).

    Plain promotions (DT-2) never call Llama: they get the fixed promotion
    advice with a template source.
    """
    advice_source = "template"
    try:
        try:
            plain = is_plain_promotion(text, evidence)
        except Exception:
            plain = False
        if plain:
            return PROMOTION_ADVICE, "template"
        if advisor is not None and getattr(evidence, "level", "low") in ("medium", "high"):
            try:
                raw_advice, _stats = advisor.generate(text, evidence)
                guarded_advice, flags = guard(raw_advice, evidence)
                advice = guarded_advice
                if "refusal_fallback" in flags:
                    advice_source = "refusal_fallback"
                elif "contradiction_fallback" in flags or "empty_fallback" in flags:
                    advice_source = "template"
                else:
                    advice_source = "llm"
            except Exception as error:
                logger.warning("advisor failed (%s), using template advice", type(error).__name__)
                advice = template_advice(evidence)
                advice_source = "template"
        else:
            advice = template_advice(evidence)
            advice_source = "template"
    except Exception as error:
        logger.warning("advisor failed (%s), using template advice", type(error).__name__)
        advice = template_advice(evidence)
        advice_source = "template"
    return advice, advice_source


def analyse(
    text: str,
    url_det: Any = None,
    sms_det: Any = None,
    advisor: Any = None,
    extra_detectors: tuple[Any, ...] = (),
    sender: str | None = None,
) -> dict[str, Any]:
    """Execute the end-to-end detection and advisory pipeline.

    This function must never raise, no matter what ``text`` contains. When
    ``sender`` is given, a sender_mismatch cue is appended before fusion.

    Args:
        text: Input SMS message text.
        url_det: Optional UrlDetector instance.
        sms_det: Optional SmsDetector instance.
        advisor: Optional LlamaAdvisor instance.
        extra_detectors: Optional tuple of secondary plug-in detector instances.
        sender: Optional sender string (phone number or DLT header).

    Returns:
        Dictionary containing evidence (Evidence), advice (str), advice_source (str),
        timings_ms (dict of stage durations), and is_plain_promotion (bool).
    """
    t_start = time.perf_counter()
    timings: dict[str, float] = {}

    try:
        t0 = time.perf_counter()
        extracted = _extract_urls_safe(text)
        timings["url_extraction_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        url_results = [_score_url_with_detector(url, url_det) for url in extracted]
        timings["url_detection_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        cues = _safe_sms_cues(text)
        if sender is not None:
            try:
                from sentinel.routine_filter import sender_cue

                sender_span = sender_cue(sender, text)
            except Exception:
                sender_span = None
            if sender_span is not None:
                cues = list(cues) + [sender_span]
        timings["cues_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        sms_result, _sms_error = _safe_sms_predict_detailed(text, sms_det)
        timings["sms_detection_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        extra_parts = run_extra_detectors(text, extra_detectors)
        evidence = _safe_fuse(text, sms_result, url_results, cues, extra_parts, sender)
        if _sms_error:
            if "sms_model_error" not in evidence.indicators:
                evidence.indicators.append("sms_model_error")
            if "analysis_error" not in evidence.indicators:
                evidence.indicators.append("analysis_error")
        timings["fusion_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        t0 = time.perf_counter()
        advice, advice_source = _run_advisor(text, evidence, advisor)
        try:
            plain_promotion = is_plain_promotion(text, evidence)
        except Exception:
            plain_promotion = False
        timings["advisor_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        timings["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 3)
        return {"evidence": evidence, "advice": advice, "advice_source": advice_source, "timings_ms": timings, "is_plain_promotion": plain_promotion}
    except Exception:
        timings["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 3)
        evidence = Evidence(label="unwanted", risk=0.4, level="medium", threshold=0.7, indicators=["analysis_error"])
        try:
            plain_promotion = is_plain_promotion(text, evidence)
        except Exception:
            plain_promotion = False
        return {"evidence": evidence, "advice": template_advice(evidence), "advice_source": "template", "timings_ms": timings, "is_plain_promotion": plain_promotion}
