/**
 * Pure Kotlin plain-promotion heuristics and static advice text.
 * Mirrored by sentinel/advisor.py (is_plain_promotion, PROMOTION_ADVICE).
 * Verified by PromotionTest and ParityTest.
 */
package org.ps3.sentinel.core

import java.util.regex.Pattern

/** Fixed short advice for a plain promotion; no Llama call. Read from the shared rules so Python and Kotlin cannot drift. */
val PROMOTION_ADVICE: String
    get() = Rules.active().promotion.adviceText

/**
 * Returns true when [text] with [evidence] is a plain promotion: medium/unwanted
 * with no URL, no 6+ digit phone run, no reply/contact request, and no blocked cue.
 * Driven by promotion_no_action in the shared rules so Python and Kotlin agree.
 *
 * @param text The raw SMS text.
 * @param evidence Evaluated detection evidence for the message.
 * @return True if the message qualifies as a benign promotional message without risk cues.
 */
fun isPlainPromotion(text: String?, evidence: Evidence?): Boolean {
    if (text.isNullOrEmpty() || evidence == null) return false
    val rules = try {
        Rules.active().promotion
    } catch (_: Exception) {
        return false
    }
    if (evidence.level != rules.level || evidence.label != rules.label) return false
    // Any URL presents potential phishing risk; promotions with links require full evaluation.
    if (extractUrls(text).isNotEmpty()) return false
    if (rules.domainLikeRegex.isNotBlank()) {
        val domainPattern = compilePattern(rules.domainLikeRegex, Pattern.CASE_INSENSITIVE) ?: return false
        if (domainPattern.matcher(text).find()) return false
    }
    if (rules.atHandleRegex.isNotBlank()) {
        val atHandlePattern = compilePattern(rules.atHandleRegex, 0) ?: return false
        if (atHandlePattern.matcher(text).find()) return false
    }
    // Long digit sequences indicate callback numbers for potential call-based fraud.
    if (hasPhoneDigitRun(text, rules)) return false
    // Interactive reply requests (SMS, WhatsApp, call) indicate solicitation or phishing.
    if (hasReplyContactRequest(text, rules)) return false
    val blocked = rules.blockedCueTypes.toSet()
    // High-risk cues (urgency, threat, credential/payment requests) disqualify the message.
    if (evidence.cueSpans.any { it.type in blocked }) return false
    return true
}

private val patternCache = mutableMapOf<String, Pattern>()

/**
 * Compiles a regex with a fallback attempt if standard compilation fails.
 *
 * When compilation with requested flags fails with [IllegalArgumentException] (e.g.
 * unsupported unicode character classes on older runtimes), retries without the
 * UNICODE_CHARACTER_CLASS flag.
 *
 * @param regex Regular expression string to compile.
 * @param flags Regex matching flags.
 * @param compiler Function that compiles pattern strings with specified flags.
 * @return Compiled [Pattern] instance, or null if compilation fails.
 */
internal fun compilePatternWithFallback(
    regex: String,
    flags: Int,
    compiler: (String, Int) -> Pattern
): Pattern? {
    return try {
        compiler(regex, flags)
    } catch (_: IllegalArgumentException) {
        try {
            // Strip UNICODE_CHARACTER_CLASS for regex engines lacking Unicode property support.
            compiler(regex, flags and Pattern.UNICODE_CHARACTER_CLASS.inv())
        } catch (_: Exception) {
            null
        }
    } catch (_: Exception) {
        null
    }
}

private fun compilePattern(regex: String, flags: Int): Pattern? {
    val key = "$flags\u0000$regex"
    synchronized(patternCache) {
        patternCache[key]?.let { return it }
    }
    val compiled = compilePatternWithFallback(regex, flags) { r, f -> Pattern.compile(r, f) }
        ?: return null
    synchronized(patternCache) {
        patternCache[key] = compiled
    }
    return compiled
}

private fun hasPhoneDigitRun(text: String, rules: PromotionRules): Boolean {
    val pattern = compilePattern(rules.phoneDigitRunRegex, Pattern.UNICODE_CHARACTER_CLASS)
        ?: return true
    val matcher = pattern.matcher(text)
    while (matcher.find()) {
        val digits = matcher.group().filter { Character.isDigit(it) }
        if (digits.length >= rules.phoneMinDigits) return true
    }
    return false
}

private fun hasReplyContactRequest(text: String, rules: PromotionRules): Boolean {
    for (phrase in rules.replyContactPhrases) {
        if (phrase.isBlank()) continue
        val pattern = compilePattern(
            "\\b" + Pattern.quote(phrase) + "\\b",
            Pattern.CASE_INSENSITIVE or Pattern.UNICODE_CHARACTER_CLASS
        ) ?: return true
        if (pattern.matcher(text).find()) return true
    }
    return false
}
