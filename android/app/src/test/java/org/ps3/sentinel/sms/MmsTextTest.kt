package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.StringReader

// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
class MmsTextTest {

    @Test
    fun testAppendShortText() {
        val sb = StringBuilder()
        MmsText.append(sb, "Hello MMS")
        assertEquals("Hello MMS", sb.toString())
    }

    @Test
    fun testAppendOverMaxCharsTruncates() {
        val sb = StringBuilder()
        val chunk = "a".repeat(10_000)
        for (i in 0 until 15) {
            MmsText.append(sb, chunk)
        }
        assertEquals(MmsText.MAX_CHARS, sb.length)
    }

    @Test
    fun testAppendReader() {
        val sb = StringBuilder()
        val content = "Multi-part MMS content streamed from descriptor"
        val reader = StringReader(content)
        MmsText.append(sb, reader) { /* active check */ }
        assertEquals(content, sb.toString())
    }

    @Test
    fun testAppendReaderRespectsCancellation() {
        val sb = StringBuilder()
        val content = "A".repeat(10_000)
        val reader = StringReader(content)
        var checks = 0
        var cancelled = false
        try {
            MmsText.append(sb, reader) {
                checks++
                if (checks >= 2) {
                    cancelled = true
                    throw RuntimeException("Cancelled")
                }
            }
        } catch (_: RuntimeException) {
        }
        assertTrue("Cancellation check should have triggered", cancelled)
        assertTrue("Some characters should have been appended before cancel", sb.isNotEmpty())
        assertTrue("Length should be less than total content", sb.length < content.length)
    }

    @Test
    fun testJoinFiltersNonPlainParts() {
        val parts = listOf(
            "image/jpeg" to "BINARY_BYTES_SHOULD_BE_IGNORED",
            "text/plain" to "First line.",
            "text/html" to "<b>Html line</b>",
            "text/plain" to " Second line.",
            "text/plain" to null
        )
        val result = MmsText.join(parts)
        assertEquals("First line. Second line.", result)
    }
}
