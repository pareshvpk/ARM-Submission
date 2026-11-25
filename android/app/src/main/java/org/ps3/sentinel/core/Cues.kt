/**
 * Pure Kotlin scam cue extraction and span deduplication.
 * Mirrored by sentinel/detectors.py (sms_cues) and pinned by parity tests.
 * Extracts non-overlapping suspicious keyword and regex cue spans based on shared rules.
 */
package org.ps3.sentinel.core

import java.util.regex.Pattern

/**
 * Represents a suspicious textual cue identified within a message.
 *
 * @property type Identifier of the cue category (e.g. "urgency", "threat", "payment_request").
 * @property start Start character offset in the source text (inclusive).
 * @property end End character offset in the source text (exclusive).
 * @property text Exact substring that triggered the cue match.
 */
data class CueSpan(
    val type: String,
    val start: Int,
    val end: Int,
    val text: String
)

/**
 * Extracts non-overlapping SMS cue spans using shared rules to match Python pipeline behavior.
 *
 * Evaluates keywords and precompiled regular expressions in rule order, resolving overlapping
 * spans by prioritizing earlier start offsets and longer match lengths.
 *
 * @param text The message body to scan, or null/empty.
 * @return List of non-overlapping [CueSpan] objects in chronological text order.
 */
fun smsCues(text: String?): List<CueSpan> {
    if (text.isNullOrEmpty()) return emptyList()

    val cueRules = Rules.active().cues
    val matches = mutableListOf<CueSpan>()

    for (cueType in cueRules.typeOrder) {
        for (term in cueRules.keywords[cueType].orEmpty()) {
            val pattern = Pattern.compile("\\b${Pattern.quote(term)}\\b", Pattern.CASE_INSENSITIVE)
            collectMatches(pattern, text, cueType, matches)
        }
    }

    // Extra patterns, precompiled and validated at load in [Rules.parseCues]; never compiled here.
    
    for (cueType in cueRules.typeOrder) {
        for (pattern in cueRules.regexes[cueType].orEmpty()) {
            collectMatches(pattern, text, cueType, matches)
        }
    }

    // Sort by start ascending, then length descending (longer spans win ties).
    matches.sortWith(Comparator { a, b ->
        val startCmp = a.start.compareTo(b.start)
        if (startCmp != 0) startCmp else (b.end - b.start).compareTo(a.end - a.start)
    })

    // Deduplicate overlapping spans: discard spans starting before the previous span ends.
    val filtered = mutableListOf<CueSpan>()
    var lastEnd = -1
    for (match in matches) {
        if (match.start >= lastEnd) {
            filtered.add(match)
            lastEnd = match.end
        }
    }

    return filtered
}

/** Append every non-overlapping regex hit to [target] with its character offsets. */
private fun collectMatches(
    pattern: Pattern,
    text: String,
    cueType: String,
    target: MutableList<CueSpan>
) {
    val matcher = pattern.matcher(text)
    while (matcher.find()) {
        target.add(
            CueSpan(
                type = cueType,
                start = matcher.start(),
                end = matcher.end(),
                text = matcher.group()
            )
        )
    }
}
