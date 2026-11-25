package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class LlamaStatsTest {

    @Test
    fun testParseLlamaStatsSample() {
        val json = """
            {
                "prompt_tokens": 120,
                "generated_tokens": 60,
                "inference_start_ms": 1000,
                "prompt_eval_end_ms": 2000,
                "first_token_ms": 2100,
                "inference_end_ms": 12100,
                "SCALING_FACTOR_UNITS_PER_SECOND": 1000
            }
        """.trimIndent()

        val stats = parseLlamaStats(json)
        assertNotNull("Expected non-null stats", stats)
        assertEquals(120, stats!!.promptTokens)
        assertEquals(60, stats.generatedTokens)
        assertEquals(120.0, stats.prefillTokensPerSec, 0.001)
        assertEquals(5.9, stats.decodeTokensPerSec, 0.001)
        assertEquals(1100.0, stats.ttftMs, 0.001)
        assertEquals(11100.0, stats.totalTimeMs, 0.001)
    }

    @Test
    fun testParseLlamaStatsNullEmptyGarbage() {
        assertNull(parseLlamaStats(null))
        assertNull(parseLlamaStats(""))
        assertNull(parseLlamaStats("   "))
        assertNull(parseLlamaStats("invalid json string"))
        assertNull(parseLlamaStats("{not valid json"))

        val emptyObjStats = parseLlamaStats("{}")
        assertNotNull(emptyObjStats)
        assertEquals(0, emptyObjStats!!.promptTokens)
        assertEquals(0, emptyObjStats.generatedTokens)
        assertEquals(0.0, emptyObjStats.prefillTokensPerSec, 0.001)
        assertEquals(0.0, emptyObjStats.decodeTokensPerSec, 0.001)
        assertEquals(0.0, emptyObjStats.totalTimeMs, 0.001)
        assertEquals(0.0, emptyObjStats.ttftMs, 0.001)
    }

    @Test
    fun testParseLlamaStatsOldKeyFallback() {
        val json = """
            {
                "prompt_tokens": 50,
                "generated_tokens": 25,
                "prefill_tokens_per_sec": 33.3,
                "decode_tokens_per_sec": 12.5,
                "total_time_ms": 2000.0,
                "ttft_ms": 180.0
            }
        """.trimIndent()

        val stats = parseLlamaStats(json)
        assertNotNull(stats)
        assertEquals(50, stats!!.promptTokens)
        assertEquals(25, stats.generatedTokens)
        assertEquals(33.3, stats.prefillTokensPerSec, 0.001)
        assertEquals(12.5, stats.decodeTokensPerSec, 0.001)
        assertEquals(2000.0, stats.totalTimeMs, 0.001)
        assertEquals(180.0, stats.ttftMs, 0.001)
    }
}
