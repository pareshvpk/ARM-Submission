// Evaluates execution timeouts during on-device Llama advice generation.
// Pure Kotlin logic with no Android framework dependencies, defining first-token
// and total generation budgets to trigger fallback to deterministic template advice.

package org.ps3.sentinel.ml

/**
 * Purpose:  Decides generation timeout outcome for template fallback.
 * Owns:     Nothing. Pure timeout decision rules.
 * Lifetime: Process
 * Thread:   any — no mutable state is touched.
 */
object GenerationWatchdog {
    // 20000 ms — first-token budget: normal first tokens arrive under about 6 s
    // on the Galaxy F14, while swapped weights stall for minutes. Twenty
    // seconds separates a slow device from a wedged generation.
    const val FIRST_TOKEN_TIMEOUT_MS: Long = 20_000L

    // 60000 ms — total budget: the whole advice is capped near 90 words, so a
    // healthy generation finishes far under this. Sixty seconds guarantees the
    // user never waits forever even when tokens keep trickling.
    const val TOTAL_GENERATION_TIMEOUT_MS: Long = 60_000L

    // 45000 ms — light-tier first-token budget: the Galaxy F12 measured TTFT
    // 8.7–12.6 s without dot-product support, so the normal 20 s budget leaves
    // too little headroom for a cold or contended little core. The Galaxy M31
    // (LIGHT tier, measured 2026-11-24) needs about 32 s to the first advice
    // token after a cold start: 26 s paging in the 1.7 GB model weights, then
    // 6.7 s prompt prefill. At the old 30 s budget the watchdog fired and the
    // template was shown even though Llama finished at 48 s, so the budget is
    // 45 s. The LIGHT total budget (90 s) still bounds the whole generation.
    const val LIGHT_FIRST_TOKEN_TIMEOUT_MS: Long = 45_000L

    // 90000 ms — light-tier total budget: fewer tokens are requested, but the
    // F12 was timing out at the normal 60 s limit under memory pressure.
    const val LIGHT_TOTAL_GENERATION_TIMEOUT_MS: Long = 90_000L

    const val REASON_FIRST_TOKEN_TIMEOUT: String = "first_token_timeout"
    const val REASON_TOTAL_TIMEOUT: String = "total_timeout"

    /**
     * Determines whether the default generation budget has expired.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @return [REASON_TOTAL_TIMEOUT], [REASON_FIRST_TOKEN_TIMEOUT], or null if within budget.
     */
    fun watchdogReason(elapsedMs: Long, hasFirstToken: Boolean): String? =
        watchdogReason(elapsedMs, hasFirstToken, FIRST_TOKEN_TIMEOUT_MS, TOTAL_GENERATION_TIMEOUT_MS)

    /**
     * Evaluates generation duration against custom first-token and total timeouts.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @param firstTokenTimeoutMs Maximum permitted duration before the initial token arrives.
     * @param totalTimeoutMs Overall generation deadline.
     * @return [REASON_TOTAL_TIMEOUT] if overall deadline exceeded, [REASON_FIRST_TOKEN_TIMEOUT]
     *         if initial token stalled past budget, or null if healthy.
     */
    fun watchdogReason(
        elapsedMs: Long,
        hasFirstToken: Boolean,
        firstTokenTimeoutMs: Long,
        totalTimeoutMs: Long
    ): String? {
        if (elapsedMs > totalTimeoutMs) return REASON_TOTAL_TIMEOUT
        if (!hasFirstToken && elapsedMs > firstTokenTimeoutMs) return REASON_FIRST_TOKEN_TIMEOUT
        return null
    }

    /**
     * Evaluates generation duration against the budget assigned to a hardware tier.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @param tier CPU/RAM tier determining generation deadlines.
     * @return Failure reason string, or null if within tier limits.
     */
    fun watchdogReason(elapsedMs: Long, hasFirstToken: Boolean, tier: CpuFeatures.Tier): String? {
        val firstTokenTimeoutMs = CpuFeatures.firstTokenTimeoutMsFor(tier)
        val totalTimeoutMs = CpuFeatures.totalGenerationTimeoutMsFor(tier)
        return watchdogReason(elapsedMs, hasFirstToken, firstTokenTimeoutMs, totalTimeoutMs)
    }

    /**
     * Checks if default timeouts have been exceeded.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @return True if either first-token or total budget has expired.
     */
    fun isTimedOut(elapsedMs: Long, hasFirstToken: Boolean): Boolean =
        watchdogReason(elapsedMs, hasFirstToken) != null

    /**
     * Checks if explicit custom timeouts have been exceeded.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @param firstTokenTimeoutMs Maximum duration before initial token.
     * @param totalTimeoutMs Overall generation deadline.
     * @return True if expired.
     */
    fun isTimedOut(
        elapsedMs: Long,
        hasFirstToken: Boolean,
        firstTokenTimeoutMs: Long,
        totalTimeoutMs: Long
    ): Boolean = watchdogReason(elapsedMs, hasFirstToken, firstTokenTimeoutMs, totalTimeoutMs) != null

    /**
     * Checks if tier-specific timeouts have been exceeded.
     *
     * @param elapsedMs Wall-clock duration elapsed since generation began.
     * @param hasFirstToken Whether at least one token has been emitted by the decoder.
     * @param tier Hardware capability tier.
     * @return True if expired.
     */
    fun isTimedOut(elapsedMs: Long, hasFirstToken: Boolean, tier: CpuFeatures.Tier): Boolean =
        watchdogReason(elapsedMs, hasFirstToken, tier) != null
}
