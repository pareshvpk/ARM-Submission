package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
class MmsScannerTest {

    @Test
    fun testTrimTextUnderOrAtLimit() {
        val short = "Hello World"
        assertEquals(short, trimText(short))

        val exact = "x".repeat(2000)
        assertEquals(exact, trimText(exact))
    }

    @Test
    fun testTrimTextOverLimit() {
        val longText = "a".repeat(2500)
        val trimmed = trimText(longText)
        assertEquals(2000, trimmed.length)
        assertEquals("a".repeat(2000), trimmed)
    }

    @Test
    fun testParseAndSerializePending() {
        val original = mapOf(10L to 1000L, 20L to 2000L)
        val serialized = serializePending(original)
        assertTrue(serialized.contains("10:1000"))
        assertTrue(serialized.contains("20:2000"))

        val parsed = parsePending(serialized)
        assertEquals(original, parsed)
    }

    @Test
    fun testParsePendingIgnoresMalformed() {
        val input = setOf("10:1000", "invalid", ":100", "100:", "abc:def", "20:2000")
        val parsed = parsePending(input)
        assertEquals(mapOf(10L to 1000L, 20L to 2000L), parsed)
    }
}
