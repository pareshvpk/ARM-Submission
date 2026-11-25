/**
 * Pure Kotlin plug-in detector contract and executor for modular analysis stages.
 * Contains no Android classes; mirrored by sentinel/detector_api.py.
 * Verified by DetectorApiTest.
 */
package org.ps3.sentinel.core

import java.util.logging.Logger

/**
 * Purpose:  Carries one evidence part produced by a plug-in detector.
 * Owns:     Nothing.
 * Lifetime: Process
 * Thread:   immutable — safe to share.
 *
 * @property name Unique identifier of the originating detector.
 * @property version Version string of the detector algorithm or model.
 * @property risk Evaluated probability score between 0.0 and 1.0.
 * @property indicators List of detected anomaly or feature labels.
 */
data class DetectorPart(
    val name: String,
    val version: String,
    val risk: Double,
    val indicators: List<String>
)

/**
 * Purpose:  Defines the contract a plug-in detector implements.
 * Owns:     Nothing.
 * Lifetime: Process
 * Thread:   implementation-defined.
 */
interface Detector {
    val name: String
    val version: String

    /**
     * Evaluates [text] and returns an evidence contribution with risk and indicators.
     *
     * @param text Raw message text to inspect.
     * @return Evaluated detector output part.
     */
    fun score(text: String): DetectorPart
}

// 0.0 and 1.0 — risk is a probability, so anything outside this range is a detector bug.
private const val MIN_RISK: Double = 0.0
private const val MAX_RISK: Double = 1.0

private val extraDetectorLogger: Logger = Logger.getLogger("PS3Sms")

/**
 * Clamps a detector risk to the 0..1 probability range.
 *
 * @param risk Raw risk value to clamp.
 * @return Value constrained to [0.0, 1.0], or 0.0 if not finite.
 */
internal fun clampRisk(risk: Double): Double {
    // Non-finite scores (NaN or Inf) default to MIN_RISK to prevent corrupting downstream math.
    if (!risk.isFinite()) return MIN_RISK
    return risk.coerceIn(MIN_RISK, MAX_RISK)
}

/**
 * Runs plug-in detectors and returns their clamped evidence parts.
 * A detector that throws contributes no part; the failure is logged without
 * the message text so SMS content never reaches the log.
 *
 * @param text Raw message text to inspect.
 * @param detectors List of plug-in detectors to invoke.
 * @return List of successfully evaluated and clamped detector parts.
 */
fun runExtraDetectors(text: String, detectors: List<Detector>): List<DetectorPart> {
    val parts = mutableListOf<DetectorPart>()
    for (detector in detectors) {
        try {
            val part = detector.score(text)
            parts.add(part.copy(risk = clampRisk(part.risk)))
        } catch (e: Exception) {
            extraDetectorLogger.warning(
                "extra detector ${detector.name} failed: ${e::class.simpleName}"
            )
        }
    }
    return parts
}
