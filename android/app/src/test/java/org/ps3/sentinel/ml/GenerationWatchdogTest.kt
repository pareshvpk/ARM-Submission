package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GenerationWatchdogTest {
    @Test
    fun testWatchdogTimeoutConstants() {
        assertEquals(20_000L, GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS)
        assertEquals(60_000L, GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS)
    }

    @Test
    fun testWatchdogFirstTokenTimeout() {
        assertEquals(
            GenerationWatchdog.REASON_FIRST_TOKEN_TIMEOUT,
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 1, hasFirstToken = false
            )
        )
        assertTrue(
            GenerationWatchdog.isTimedOut(GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 1, hasFirstToken = false)
        )
    }

    @Test
    fun testWatchdogNoTimeoutBeforeFirstTokenBudget() {
        assertNull(
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS - 1, hasFirstToken = false
            )
        )
    }

    @Test
    fun testWatchdogNoFirstTokenTimeoutAfterTokenArrived() {
        assertNull(
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 1, hasFirstToken = true
            )
        )
        assertNull(
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS - 1, hasFirstToken = true
            )
        )
    }

    @Test
    fun testWatchdogTotalTimeout() {
        assertEquals(
            GenerationWatchdog.REASON_TOTAL_TIMEOUT,
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS + 1, hasFirstToken = true
            )
        )
        assertEquals(
            GenerationWatchdog.REASON_TOTAL_TIMEOUT,
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS + 1, hasFirstToken = false
            )
        )
    }

    @Test
    fun testWatchdogLightBudgets() {
        assertEquals(45_000L, GenerationWatchdog.LIGHT_FIRST_TOKEN_TIMEOUT_MS)
        assertEquals(90_000L, GenerationWatchdog.LIGHT_TOTAL_GENERATION_TIMEOUT_MS)
    }

    @Test
    fun testWatchdogTierAwareReasonUsesLightBudgets() {
        val elapsedBetweenFullAndLight = GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 5_000L
        assertEquals(
            GenerationWatchdog.REASON_FIRST_TOKEN_TIMEOUT,
            GenerationWatchdog.watchdogReason(elapsedBetweenFullAndLight, hasFirstToken = false)
        )
        assertNull(
            GenerationWatchdog.watchdogReason(
                elapsedBetweenFullAndLight,
                hasFirstToken = false,
                GenerationWatchdog.LIGHT_FIRST_TOKEN_TIMEOUT_MS,
                GenerationWatchdog.LIGHT_TOTAL_GENERATION_TIMEOUT_MS
            )
        )
        assertNull(
            GenerationWatchdog.watchdogReason(
                elapsedBetweenFullAndLight,
                hasFirstToken = false,
                CpuFeatures.Tier.LIGHT
            )
        )
        assertEquals(
            GenerationWatchdog.REASON_FIRST_TOKEN_TIMEOUT,
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.LIGHT_FIRST_TOKEN_TIMEOUT_MS + 1,
                hasFirstToken = false,
                CpuFeatures.Tier.LIGHT
            )
        )
        assertEquals(
            GenerationWatchdog.REASON_TOTAL_TIMEOUT,
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.LIGHT_TOTAL_GENERATION_TIMEOUT_MS + 1,
                hasFirstToken = true,
                CpuFeatures.Tier.LIGHT
            )
        )
        assertFalse(
            GenerationWatchdog.isTimedOut(
                elapsedBetweenFullAndLight,
                hasFirstToken = false,
                CpuFeatures.Tier.LIGHT
            )
        )
        assertTrue(
            GenerationWatchdog.isTimedOut(
                GenerationWatchdog.LIGHT_TOTAL_GENERATION_TIMEOUT_MS + 1,
                hasFirstToken = true,
                CpuFeatures.Tier.LIGHT
            )
        )
    }

    @Test
    fun testWatchdogTierAwareReasonFullMatchesDefault() {
        assertEquals(
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 1, hasFirstToken = false
            ),
            GenerationWatchdog.watchdogReason(
                GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS + 1,
                hasFirstToken = false,
                CpuFeatures.Tier.FULL
            )
        )
    }

    @Test
    fun testWatchdogGenerationIdMatching() {
        assertTrue(isWatchdogGenerationCurrent(1L, 1L))
        assertTrue(isWatchdogGenerationCurrent(42L, 42L))
        assertFalse("different generation must not match", isWatchdogGenerationCurrent(2L, 1L))
        assertFalse("finished generation marked with 0 must not match", isWatchdogGenerationCurrent(0L, 1L))
        assertFalse("zero captured id must not match", isWatchdogGenerationCurrent(0L, 0L))
    }

    @Test
    fun testRunWatchdogStopOnlyWhenCurrent() {
        var stopped = false
        val executed = runWatchdogStop(true) { stopped = true }
        assertTrue(executed)
        assertTrue(stopped)

        stopped = false
        val skipped = runWatchdogStop(false) { stopped = true }
        assertFalse(skipped)
        assertFalse(stopped)
    }
}
