package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class PrefixCacheTest {

    private fun tempDir(): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "prefixcache-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    @Test
    fun testFlagFilePresentEnablesPrefixCache() {
        val dir = tempDir()
        File(dir, LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME).createNewFile()
        val decision = resolvePrefixCacheDecision(dir, null)
        assertTrue(decision.enabled)
        assertTrue(decision.reason.contains(LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME))
    }

    @Test
    fun testNoFlagFileUsesConstantDefaultOn() {
        val dir = tempDir()
        val decision = resolvePrefixCacheDecision(dir, null)
        assertEquals(LlamaAdvisor.USE_PREFIX_CACHE, decision.enabled)
        assertTrue(LlamaAdvisor.USE_PREFIX_CACHE)
        assertTrue(decision.enabled)
        assertTrue(decision.reason.contains("USE_PREFIX_CACHE"))
    }

    @Test
    fun testOffFlagFileDisablesPrefixCache() {
        val dir = tempDir()
        File(dir, LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME).createNewFile()
        val decision = resolvePrefixCacheDecision(dir, null)
        assertFalse(decision.enabled)
        assertTrue(decision.reason.contains(LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME))
    }

    @Test
    fun testOffFlagFileWinsOverOnFlagFile() {
        val dir = tempDir()
        File(dir, LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME).createNewFile()
        File(dir, LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME).createNewFile()
        val decision = resolvePrefixCacheDecision(dir, null)
        assertFalse(decision.enabled)
        assertTrue(decision.reason.contains(LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME))
    }

    @Test
    fun testExplicitOverrideWinsOverFlag() {
        val dir = tempDir()
        File(dir, LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME).createNewFile()
        assertFalse(resolvePrefixCacheDecision(dir, false).enabled)
        val offDir = tempDir()
        File(offDir, LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME).createNewFile()
        assertTrue(resolvePrefixCacheDecision(offDir, true).enabled)
    }

    @Test
    fun testFormatBenchLineHasRequiredFieldsAndHash() {
        val advice = "This message looks like a scam."
        val stats = LlamaStats(
            promptTokens = 42,
            generatedTokens = 30,
            prefillTokensPerSec = 50.0,
            decodeTokensPerSec = 12.5,
            totalTimeMs = 3000.0,
            ttftMs = 180.0,
            promptPath = "prefix_cache"
        )
        val line = formatBenchLine("prefix_cache", stats, advice)
        assertTrue(line.contains("prompt_path=prefix_cache"))
        assertTrue(line.contains("prompt_tokens=42"))
        assertTrue(line.contains("ttft_ms="))
        assertTrue(line.contains("decode_tok_s="))
        assertTrue(line.contains("advice_sha8=${sha256Short(advice)}"))
        assertFalse(line.contains(advice))
        assertFalse(line.contains("scam and"))
    }

    @Test
    fun testFormatBenchLineNullStatsUsesZeros() {
        val line = formatBenchLine("full_prompt", null, "advice text")
        assertTrue(line.contains("prompt_path=full_prompt"))
        assertTrue(line.contains("prompt_tokens=0"))
        assertTrue(line.contains("ttft_ms=0.0"))
        assertTrue(line.contains("decode_tok_s=0.0"))
        assertTrue(line.contains("advice_sha8=${sha256Short("advice text")}"))
    }

    @Test
    fun testResolvePathPrefixReadyGivesPrefix() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_CACHE,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_CACHE, true, true)
        )
    }

    @Test
    fun testResolvePathPrefixNotReadyGivesFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_CACHE, false, true)
        )
    }

    @Test
    fun testResolvePathFullPromptStaysFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_FULL_PROMPT, true, false)
        )
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_FULL_PROMPT, false, false)
        )
    }

    @Test
    fun testResolvePathFullPromptActiveAndReadyGivesPrefix() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_CACHE,
            resolvePathUnderLock(LlamaAdvisor.PATH_FULL_PROMPT, true, true)
        )
    }

    @Test
    fun testResolvePathFullPromptActiveNotReadyGivesFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_FULL_PROMPT, false, true)
        )
    }

    @Test
    fun testLightPrefillIdleDelayIsFiveSeconds() {
        assertEquals(5_000L, LlamaAdvisor.LIGHT_PREFILL_IDLE_DELAY_MS)
        assertEquals(5_000L, ExecutorchGate.LIGHT_PREFILL_IDLE_DELAY_MS)
        assertEquals(5_000L, prefillIdleDelayMs(true))
        assertEquals(0L, prefillIdleDelayMs(false))
    }

    @Test
    fun testLightTierNeverSchedulesBackgroundPrefill() {
        // FIX 1: a LIGHT background prefill held the ExecuTorch gate for 11-25 s and
        // stalled an arriving SMS by 7-12 s, so LIGHT must not schedule one at all.
        assertFalse(shouldScheduleBackgroundPrefill(true))
    }

    @Test
    fun testFullTierStillSchedulesBackgroundPrefill() {
        assertTrue(shouldScheduleBackgroundPrefill(false))
    }

    @Test
    fun testLightTierAdvicePathWithoutPrefillIsOnDemand() {
        // With no background prefill ever scheduled, prefixReady stays false on
        // LIGHT, so advice takes the foreground on-demand path rather than waiting
        // for a prefill or silently running the full prompt.
        assertFalse(shouldScheduleBackgroundPrefill(true))
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_ON_DEMAND,
            selectPromptPath(prefixCacheActive = true, prefixReady = false, isLightTier = true)
        )
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            selectPromptPath(prefixCacheActive = false, prefixReady = false, isLightTier = true)
        )
    }

    @Test
    fun testShouldDeferPrefillWhenPendingOrRecent() {
        assertTrue(shouldDeferPrefill(true, 1_000L, 0L, 0L))
        assertTrue(shouldDeferPrefill(false, 1_000L, 500L, 5_000L))
        assertFalse(shouldDeferPrefill(false, 6_000L, 500L, 5_000L))
        assertFalse(shouldDeferPrefill(false, 1_000L, 0L, 5_000L))
        assertFalse(shouldDeferPrefill(false, 1_000L, 500L, 0L))
    }

    @Test
    fun testIsPrefillIdleEdges() {
        assertTrue(isPrefillIdle(1_000L, 0L, 5_000L))
        assertFalse(isPrefillIdle(1_000L, 500L, 5_000L))
        assertTrue(isPrefillIdle(5_500L, 500L, 5_000L))
        assertTrue(isPrefillIdle(1_000L, 500L, 0L))
    }

    @Test
    fun testIdleDelayFromActivityEndNotDetectionStart() {
        // Detection started 20_000 ms ago and advice ended just now:
        // the baseline passed in must be the activity end, so not idle.
        assertFalse(isPrefillIdle(20_000L, 20_000L, 5_000L))
        assertTrue(isPrefillIdle(25_000L, 20_000L, 5_000L))
        assertTrue(shouldDeferPrefill(false, false, 20_000L, 20_000L, 5_000L))
        assertFalse(shouldDeferPrefill(false, false, 25_000L, 20_000L, 5_000L))
    }

    @Test
    fun testSelectPromptPathLightNoReadyIsOnDemand() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_ON_DEMAND,
            selectPromptPath(true, false, true)
        )
    }

    @Test
    fun testSelectPromptPathLightReadyIsPrefixCache() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_CACHE,
            selectPromptPath(true, true, true)
        )
    }

    @Test
    fun testSelectPromptPathInactiveIsFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            selectPromptPath(false, false, true)
        )
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            selectPromptPath(false, true, false)
        )
    }

    @Test
    fun testSelectPromptPathFullTierUnchanged() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            selectPromptPath(true, false, false)
        )
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_CACHE,
            selectPromptPath(true, true, false)
        )
    }

    @Test
    fun testResolvePathOnDemandReadyGivesPrefixCache() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_CACHE,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_ON_DEMAND, true, true, true)
        )
    }

    @Test
    fun testResolvePathOnDemandNotReadyStaysOnDemandOnLight() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_ON_DEMAND,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_ON_DEMAND, false, true, true)
        )
    }

    @Test
    fun testResolvePathOnDemandInactiveGivesFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_ON_DEMAND, false, false, true)
        )
    }

    @Test
    fun testResolvePathPrefixNotReadyLightGivesOnDemand() {
        assertEquals(
            LlamaAdvisor.PATH_PREFIX_ON_DEMAND,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_CACHE, false, true, true)
        )
    }

    @Test
    fun testResolvePathPrefixNotReadyFullStillGivesFullPrompt() {
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_CACHE, false, true, false)
        )
        assertEquals(
            LlamaAdvisor.PATH_FULL_PROMPT,
            resolvePathUnderLock(LlamaAdvisor.PATH_PREFIX_CACHE, false, true)
        )
    }

    @Test
    fun testNeedsResetOnDemand() {
        assertTrue(needsResetBeforeGenerate(LlamaAdvisor.PATH_PREFIX_ON_DEMAND))
        assertTrue(needsResetBeforeGenerate("prefix_on_demand"))
    }

    @Test
    fun testShouldDeferPrefillWhileAdvicePending() {
        assertTrue(shouldDeferPrefill(false, true, 1_000L, 0L, 0L))
        assertTrue(shouldDeferPrefill(false, true, 6_000L, 500L, 5_000L))
        assertEquals("advice_pending", prefillDeferReason(false, true, 6_000L, 500L, 5_000L))
        assertEquals("detection_pending", prefillDeferReason(true, false, 6_000L, 500L, 5_000L))
        assertEquals("idle_delay", prefillDeferReason(false, false, 1_000L, 500L, 5_000L))
        assertEquals(null, prefillDeferReason(false, false, 6_000L, 500L, 5_000L))
        assertEquals(null, prefillDeferReason(false, false, 1_000L, 500L, 0L))
    }

    @Test
    fun testFormatBenchLineOnDemandPath() {
        val line = formatBenchLine(LlamaAdvisor.PATH_PREFIX_ON_DEMAND, null, "advice")
        assertTrue(line.contains("prompt_path=prefix_on_demand"))
    }
}
