package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.core.CueSpan

class CueHighlighterTest {

    private fun cue(start: Int, end: Int, type: String, text: String = ""): CueSpan =
        CueSpan(type = type, start = start, end = end, text = text)

    private fun cueOf(text: String, needle: String, type: String): CueSpan {
        val start = text.indexOf(needle)
        return CueSpan(type = type, start = start, end = start + needle.length, text = needle)
    }

    @Test
    fun testNoSpansReturnsEmptyRanges() {
        val text = "Your SBI account is blocked today"
        assertTrue(CueHighlighter.mergedRanges(text.length, emptyList()).isEmpty())
        assertTrue(CueHighlighter.mergedRanges(text.length, null).isEmpty())
        assertTrue(CueHighlighter.mergedRanges(0, listOf(cue(0, 1, "threat"))).isEmpty())
    }

    @Test
    fun testOneSpanIncludesType() {
        val text = "Your SBI account is blocked today"
        val ranges = CueHighlighter.mergedRanges(text.length, listOf(cueOf(text, "blocked", "threat")))
        assertEquals(listOf(HighlightRange(20, 27, "threat")), ranges)
        assertEquals("blocked", text.substring(ranges[0].start, ranges[0].end))
    }

    @Test
    fun testOneSpanAtKnownOffsets() {
        val text = "account blocked"
        val ranges = CueHighlighter.mergedRanges(text.length, listOf(cue(8, 15, "threat")))
        assertEquals(listOf(HighlightRange(8, 15, "threat")), ranges)
        assertEquals("blocked", text.substring(ranges[0].start, ranges[0].end))
    }

    @Test
    fun testOverlappingSpansAreMerged() {
        val text = "0123456789"
        val ranges = CueHighlighter.mergedRanges(
            text.length,
            listOf(cue(0, 5, "urgency"), cue(3, 8, "threat"))
        )
        assertEquals(listOf(HighlightRange(0, 8, "urgency")), ranges)
        assertEquals("01234567", text.substring(ranges[0].start, ranges[0].end))
    }

    @Test
    fun testSpanAtStartAndEnd() {
        val text = "blocked KYC"
        val ranges = CueHighlighter.mergedRanges(
            text.length,
            listOf(cue(0, 7, "threat"), cue(8, 11, "credential_request"))
        )
        assertEquals(
            listOf(
                HighlightRange(0, 7, "threat"),
                HighlightRange(8, 11, "credential_request")
            ),
            ranges
        )
    }

    @Test
    fun testHinglishText() {
        val text = "Aapka bijli connection aaj raat kat jayega"
        val ranges = CueHighlighter.mergedRanges(
            text.length,
            listOf(cueOf(text, "bijli", "impersonation"))
        )
        assertEquals(1, ranges.size)
        assertEquals("impersonation", ranges[0].type)
        assertEquals("bijli", text.substring(ranges[0].start, ranges[0].end))
    }

    @Test
    fun testOutOfRangeSpanIsIgnoredNotCrash() {
        val text = "hello world"
        val ranges = CueHighlighter.mergedRanges(
            text.length,
            listOf(
                cue(-1, 3, "threat"),
                cue(0, 999, "threat"),
                cue(50, 60, "threat"),
                cue(5, 5, "threat"),
                cue(7, 3, "threat")
            )
        )
        assertTrue(ranges.isEmpty())
    }

    @Test
    fun testValidSpanSurvivesAlongsideInvalidSpan() {
        val text = "hello blocked"
        val ranges = CueHighlighter.mergedRanges(
            text.length,
            listOf(cue(0, 999, "urgency"), cue(6, 13, "threat"))
        )
        assertEquals(listOf(HighlightRange(6, 13, "threat")), ranges)
        assertEquals("blocked", text.substring(ranges[0].start, ranges[0].end))
    }

    @Test
    fun testAdjacentSpansAreNotMerged() {
        val ranges = CueHighlighter.mergedRanges(
            10,
            listOf(cue(0, 5, "urgency"), cue(5, 8, "threat"))
        )
        assertEquals(
            listOf(HighlightRange(0, 5, "urgency"), HighlightRange(5, 8, "threat")),
            ranges
        )
    }

    @Test
    fun testContainedSpanKeepsOuterType() {
        val ranges = CueHighlighter.mergedRanges(
            10,
            listOf(cue(2, 3, "threat"), cue(0, 10, "urgency"))
        )
        assertEquals(listOf(HighlightRange(0, 10, "urgency")), ranges)
    }

    @Test
    fun testUnsortedSpansAreSortedBeforeMerging() {
        val ranges = CueHighlighter.mergedRanges(
            12,
            listOf(cue(8, 12, "reward"), cue(0, 4, "threat"), cue(3, 9, "urgency"))
        )
        assertEquals(listOf(HighlightRange(0, 12, "threat")), ranges)
    }

    @Test
    fun testBlankTypeDefaultsToCue() {
        val ranges = CueHighlighter.mergedRanges(10, listOf(cue(0, 3, "")))
        assertEquals(listOf(HighlightRange(0, 3, CueHighlighter.DEFAULT_CUE_TYPE)), ranges)
        assertEquals("cue", CueHighlighter.DEFAULT_CUE_TYPE)
    }
}
