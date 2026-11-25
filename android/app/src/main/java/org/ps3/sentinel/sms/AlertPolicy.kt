/**
 * Pure Kotlin decision engine for SMS alert gating and storage policy.
 * Determines whether incoming messages warrant user notifications based on threat cues, URLs, and model verdicts.
 * Mirrored by Python policy logic and verified by unit tests without Android dependencies.
 */
package org.ps3.sentinel.sms

import org.ps3.sentinel.core.Evidence

/**
 * Purpose:  Decides whether an SMS evidence posts an alert.
 * Owns:     Nothing. Pure alert and pending-store decisions.
 * Lifetime: Process
 * Thread:   any — no mutable state is touched.
 */
object AlertPolicy {
    // 3000 ms — receiver deadline: longer waits delay the alert past the
    // broadcast window, so a cold SMS model falls back to rules plus URL.
    const val SMS_MODEL_WAIT_TIMEOUT_MS: Long = 3000L
    // 1000 ms — deferred retry cadence: wakes once per second to check
    // whether the SMS model has warmed up without busy-looping the CPU.
    const val DEFERRED_RETRY_INTERVAL_MS: Long = 1000L

    // Cue types that make a medium verdict a real threat on their own.
    val THREAT_CUE_TYPES: Set<String> = setOf(
        "credential_request",
        "payment_request",
        "threat",
        "app_install",
        "sender_mismatch"
    )
    // 0.5 — an untrusted URL at or above this probability is threat evidence.
    const val UNTRUSTED_URL_MIN_PROB: Double = 0.5

    /**
     * True only when the verdict posts a notification.
     *
     * Measured reason: on a real inbox half of all business SMS reached level
     * medium only because the SMS model called them unwanted, and every medium
     * posted a notification. A promotion is not a threat. Ignoring the SMS label
     * also lost 7 to 25 points of scam recall on held-out Hinglish and Hindi, so
     * a medium verdict whose model top class is scam still alerts.
     *
     * Registered senders: a medium verdict from a DLT header sender alerts only
     * when the SMS model says scam. Cue words such as "pay", "share" and "OTP"
     * are normal in genuine business SMS; with them counting, 12 to 26 percent
     * of three real inboxes still alerted, without them about 3 percent.
     */
    fun shouldAlert(
        level: String,
        cueTypes: Set<String>,
        hasUrl: Boolean,
        maxUntrustedUrlProb: Double,
        smsLabel: String? = null,
        registeredSender: Boolean = false
    ): Boolean {
        if (level == "high") return true
        if (level != "medium") return false
        if (smsLabel == "scam") return true
        if (registeredSender) return false
        if (cueTypes.any { it in THREAT_CUE_TYPES }) return true
        if ("impersonation" in cueTypes && hasUrl) return true
        return maxUntrustedUrlProb >= UNTRUSTED_URL_MIN_PROB
    }

    /** Apply the alert policy to the cues, URLs and SMS label of [evidence]. */
    fun shouldAlert(evidence: Evidence): Boolean = shouldAlert(
        evidence.level,
        evidence.cueSpans.map { it.type }.toSet(),
        evidence.urls.isNotEmpty(),
        evidence.urls.filter { !it.trusted }.maxOfOrNull { it.prob } ?: 0.0,
        evidence.smsLabel,
        evidence.registeredSender
    )

    /** Returns true if [level] is "high" or "medium", indicating a potential threat. */
    fun isThreatLevel(level: String): Boolean = level == "high" || level == "medium"

    /** Evaluates whether [evidence] constitutes an actionable threat requiring user notification. */
    fun isThreat(evidence: Evidence): Boolean = shouldAlert(evidence)

    /** Returns true if a notification should be posted for [evidence], delegating to [isThreat]. */
    fun shouldPostAlert(evidence: Evidence): Boolean = isThreat(evidence)

    /**
     * Determines whether [evidence] warrants saving to the pending message store.
     *
     * Pending store only when an alert is actually posted, so a low-risk
     * message must not be written even if it was queued earlier.
     */
    fun shouldStorePending(evidence: Evidence): Boolean = isThreat(evidence)

    /**
     * Selects between full model evidence and fast rule-only evidence based on model readiness.
     *
     * Picks the evidence to alert on: full SMS-model evidence when ready,
     * otherwise the rules plus URL evidence computed without the SMS model.
     */
    fun chooseEvidence(
        smsReady: Boolean,
        ruleEvidence: Evidence,
        fullEvidence: Evidence?
    ): Evidence = if (smsReady && fullEvidence != null) fullEvidence else ruleEvidence

    /** Determines if an alert should post after choosing between available evidence representations. */
    fun shouldPostAlert(
        smsReady: Boolean,
        ruleEvidence: Evidence,
        fullEvidence: Evidence?
    ): Boolean = isThreat(chooseEvidence(smsReady, ruleEvidence, fullEvidence))

    /**
     * Checks if [text] and [evidence] indicate a plain marketing or promotional message without scam traits.
     *
     * DT-2: a promotion that still alerts keeps the promotion wording and
     * priority; the alert policy above decides whether it posts at all.
     */
    fun isPlainPromotion(text: String, evidence: Evidence): Boolean =
        org.ps3.sentinel.core.isPlainPromotion(text, evidence)
}
