package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assume
import org.junit.Test
import java.io.File

class UrlEncoderTest {

    private val sampleVocabJson = """
        {
          "pad": 0,
          "unk": 1,
          "max_len": 200,
          "chars": {
            ".": 16,
            "/": 17,
            "a": 67,
            "b": 68,
            "c": 69,
            "m": 79,
            "o": 81,
            "x": 90
          }
        }
    """.trimIndent()

    @Test
    fun testVocabJsonParsing() {
        val encoder = UrlEncoder.fromJson(sampleVocabJson)
        assertEquals(0L, encoder.pad)
        assertEquals(1L, encoder.unk)
        assertEquals(200, encoder.maxLen)
        assertEquals(67L, encoder.chars['a'])
        assertEquals(68L, encoder.chars['b'])
        assertEquals(16L, encoder.chars['.'])
        assertEquals(69L, encoder.chars['c'])
        assertEquals(81L, encoder.chars['o'])
        assertEquals(79L, encoder.chars['m'])
        assertEquals(17L, encoder.chars['/'])
        assertEquals(90L, encoder.chars['x'])
    }

    @Test
    fun testEncodeMatchesHandComputedVector() {
        val encoder = UrlEncoder.fromJson(sampleVocabJson)
        val vector = encoder.encode("ab.com/x")

        // 1. Total length must equal maxLen (200)
        assertEquals(200, vector.size)

        // 2. Expected hand-computed prefix for "ab.com/x"
        val expectedPrefix = longArrayOf(67L, 68L, 16L, 69L, 81L, 79L, 17L, 90L)
        for (i in expectedPrefix.indices) {
            assertEquals("Char vector mismatch at index $i", expectedPrefix[i], vector[i])
        }

        // 3. Remainder must be pad (0L)
        for (i in expectedPrefix.size until 200) {
            assertEquals("Pad mismatch at index $i", 0L, vector[i])
        }
    }

    @Test
    fun testEncodeUnknownCharAndTruncation() {
        val encoder = UrlEncoder.fromJson(sampleVocabJson)

        // Unknown character '€' -> unk (1L)
        val unkVector = encoder.encode("a€b")
        assertEquals(67L, unkVector[0])
        assertEquals(1L, unkVector[1])
        assertEquals(68L, unkVector[2])
        assertEquals(0L, unkVector[3])

        // Truncation: string longer than 200 chars must be capped at 200
        val longUrl = "a".repeat(250)
        val truncVector = encoder.encode(longUrl)
        assertEquals(200, truncVector.size)
        for (i in 0 until 200) {
            assertEquals(67L, truncVector[i])
        }
    }

    @Test
    fun testEncodeNonBmpCharCountsAsOneCodePoint() {
        val encoder = UrlEncoder.fromJson(sampleVocabJson)
        val vector = encoder.encode("a😀b")
        assertEquals(67L, vector[0])
        assertEquals(1L, vector[1])
        assertEquals(68L, vector[2])
        assertEquals(0L, vector[3])
    }

    @Test
    fun testEncodeTruncatesByCodePoints() {
        val encoder = UrlEncoder.fromJson(sampleVocabJson)
        val longUrl = "a".repeat(199) + "😀" + "b".repeat(50)
        val vector = encoder.encode(longUrl)
        assertEquals(200, vector.size)
        for (i in 0 until 199) {
            assertEquals(67L, vector[i])
        }
        assertEquals(1L, vector[199])
    }

    @Test
    fun testEncodeFromRepoVocabIfPresent() {
        val candidates = listOf(
            File("../../models/url_v2/vocab.json"),
            File("../models/url_v2/vocab.json"),
            File("models/url_v2/vocab.json")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
        Assume.assumeTrue(
            "Skipping: models/url_v2/vocab.json not present on this machine",
            file != null
        )
        val encoder = UrlEncoder.fromFile(file!!)
        val vector = encoder.encode("ab.com/x")
        assertEquals(200, vector.size)
        val expectedPrefix = longArrayOf(67L, 68L, 16L, 69L, 81L, 79L, 17L, 90L)
        for (i in expectedPrefix.indices) {
            assertEquals("Repo vocab mismatch at $i", expectedPrefix[i], vector[i])
        }
    }
}
