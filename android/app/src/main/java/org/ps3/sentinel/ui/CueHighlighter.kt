/**
 * Builds styled spannable text highlighting detected scam cue spans in message text.
 * Merges overlapping and adjacent cue intervals into clean non-overlapping ranges.
 * Mirrored by sentinel/highlight.py and verified by CueHighlighterTest.
 */
package org.ps3.sentinel.ui

import android.graphics.Typeface
import android.os.Build
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.text.style.TypefaceSpan
import org.ps3.sentinel.core.CueSpan

/** A merged cue highlight: half-open character range [start, end) with its cue type. */
data class HighlightRange(
    val start: Int,
    val end: Int,
    val type: String
)

/**
 * Purpose:  Builds merged cue highlight ranges for message text.
 * Owns:     SpannableString instances it creates in [highlight].
 * Lifetime: Process
 * Thread:   any — stateless, so calls are safe from any thread.
 */
object CueHighlighter {

    /** Shown when a cue has no type. Mirrors sentinel/highlight.py DEFAULT_CUE_TYPE. */
    const val DEFAULT_CUE_TYPE = "cue"

    /**
     * Merges [cueSpans] into non-overlapping ranges, mirroring sentinel/highlight.py.
     *
     * Pure: no Android classes, so JVM tests can call it directly. Spans that are
     * out of range, empty, or reversed are ignored rather than crashing.
     */
    fun mergedRanges(textLength: Int, cueSpans: List<CueSpan>?): List<HighlightRange> {
        if (textLength <= 0 || cueSpans.isNullOrEmpty()) return emptyList()
        val valid = cueSpans
            .filter { it.start >= 0 && it.end <= textLength && it.end > it.start }
            .map { HighlightRange(it.start, it.end, it.type.ifBlank { DEFAULT_CUE_TYPE }) }
        if (valid.isEmpty()) return emptyList()
        // Earliest start first, longest first on ties, so a merged span keeps
        // the type of the first span in that order (as in sentinel/highlight.py).
        val ordered = valid.sortedWith(
            compareBy<HighlightRange>({ it.start }, { -(it.end - it.start) })
        )
        val merged = mutableListOf<HighlightRange>()
        for (span in ordered) {
            val current = merged.lastOrNull()
            // Strict overlap merges; a span starting where the previous ends is separate.
            if (current != null && span.start < current.end) {
                if (span.end > current.end) {
                    merged[merged.lastIndex] = current.copy(end = span.end)
                }
            } else {
                merged.add(span)
            }
        }
        return merged
    }

    /** Applies semibold plus a foreground colour per cue type to [text] as a spannable. */
    fun highlight(text: String, cueSpans: List<CueSpan>?, colorForType: (String) -> Int): SpannableString {
        val spannable = SpannableString(text)
        for (range in mergedRanges(text.length, cueSpans)) {
            spannable.setSpan(
                ForegroundColorSpan(colorForType(range.type)),
                range.start,
                range.end,
                Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
            )
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                spannable.setSpan(
                    TypefaceSpan(Typeface.create(null, 600, false)),
                    range.start,
                    range.end,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            } else {
                spannable.setSpan(
                    StyleSpan(Typeface.BOLD),
                    range.start,
                    range.end,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE
                )
            }
        }
        return spannable
    }
}
