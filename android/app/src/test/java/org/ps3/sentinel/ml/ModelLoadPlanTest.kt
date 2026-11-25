package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.llamaGatePollIntervalMs
import org.ps3.sentinel.shouldRefreshUrlClassifier

class ModelLoadPlanTest {
    @Test
    fun testLoadOrderIsRulesUrlSmsThenLlama() {
        assertEquals(listOf("rules", "url", "sms", "llama"), ModelLoadPlan.LOAD_ORDER)
    }

    @Test
    fun testLlamaGateWaitsForSmsReady() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = false, uiOpened = true, smsAnalysisWaiting = false, deferredPending = false
            )
        )
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = false, uiOpened = false, smsAnalysisWaiting = false, deferredPending = false
            )
        )
    }

    @Test
    fun testLlamaGateWaitsWhileSmsAnalysisWaitingWithoutUi() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = false, smsAnalysisWaiting = true, deferredPending = false
            )
        )
    }

    @Test
    fun testLlamaGateOpensWhenUiOpenedAndIdle() {
        assertTrue(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = true, smsAnalysisWaiting = false, deferredPending = false
            )
        )
    }

    @Test
    fun testLlamaGateWaitsWithoutUiEvenWhenIdle() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = false, smsAnalysisWaiting = false, deferredPending = false
            )
        )
    }

    @Test
    fun testLlamaGateWaitsWhileSmsAnalysisWaitingWithUi() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = true, smsAnalysisWaiting = true, deferredPending = false
            )
        )
    }

    @Test
    fun testLlamaGateWaitsWhileDeferredPendingOnBroadcast() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = false, smsAnalysisWaiting = false, deferredPending = true
            )
        )
    }

    @Test
    fun testLlamaGateWaitsWhileDeferredPendingWithUi() {
        assertFalse(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = true, smsAnalysisWaiting = false, deferredPending = true
            )
        )
    }

    @Test
    fun testLlamaGateOpensOnlyAfterDeferredDrained() {
        assertTrue(
            ModelLoadPlan.shouldLoadLlama(
                smsReady = true, uiOpened = true, smsAnalysisWaiting = false, deferredPending = false
            )
        )
    }

    @Test
    fun testLoadDecisionNeverTrueWithoutUiOpened() {
        for (smsReady in listOf(false, true)) {
            for (smsAnalysisWaiting in listOf(false, true)) {
                for (deferredPending in listOf(false, true)) {
                    assertFalse(
                        ModelLoadPlan.shouldLoadLlama(
                            smsReady = smsReady,
                            uiOpened = false,
                            smsAnalysisWaiting = smsAnalysisWaiting,
                            deferredPending = deferredPending
                        )
                    )
                }
            }
        }
    }

    @Test
    fun testReleaseDecisionRequiresLoaded() {
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_UI_HIDDEN, analysisRunning = false, llamaLoaded = false
            )
        )
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_BACKGROUND, analysisRunning = false, llamaLoaded = false
            )
        )
    }

    @Test
    fun testReleaseDecisionWaitsWhileAnalysisRunning() {
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_UI_HIDDEN, analysisRunning = true, llamaLoaded = true
            )
        )
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_BACKGROUND, analysisRunning = true, llamaLoaded = true
            )
        )
    }

    @Test
    fun testReleaseDecisionWaitsBelowUiHidden() {
        assertFalse(ModelLoadPlan.shouldReleaseLlama(trimLevel = 5, analysisRunning = false, llamaLoaded = true))
        assertFalse(ModelLoadPlan.shouldReleaseLlama(trimLevel = 10, analysisRunning = false, llamaLoaded = true))
        assertFalse(ModelLoadPlan.shouldReleaseLlama(trimLevel = 15, analysisRunning = false, llamaLoaded = true))
    }

    @Test
    fun testReleaseDecisionOnUiHiddenAndBackground() {
        assertTrue(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_UI_HIDDEN, analysisRunning = false, llamaLoaded = true
            )
        )
        assertTrue(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_BACKGROUND, analysisRunning = false, llamaLoaded = true
            )
        )
        assertTrue(ModelLoadPlan.shouldReleaseLlama(trimLevel = 60, analysisRunning = false, llamaLoaded = true))
        assertTrue(ModelLoadPlan.shouldReleaseLlama(trimLevel = 80, analysisRunning = false, llamaLoaded = true))
    }

    @Test
    fun testSelectThreadCountMatchesCoresHalfDefault() {
        assertEquals(4, ModelLoadPlan.selectThreadCount(8))
        assertEquals(2, ModelLoadPlan.selectThreadCount(4))
        assertEquals(2, ModelLoadPlan.selectThreadCount(5))
        assertEquals(1, ModelLoadPlan.selectThreadCount(2))
    }

    @Test
    fun testSelectThreadCountFallsBackToOne() {
        assertEquals(1, ModelLoadPlan.selectThreadCount(1))
        assertEquals(1, ModelLoadPlan.selectThreadCount(0))
        assertEquals(1, ModelLoadPlan.selectThreadCount(-3))
    }

    @Test
    fun testWaitForLlamaOnlyForMediumOrHighWhileLoading() {
        assertTrue(ModelLoadPlan.shouldWaitForLlama("medium", advisorLoaded = false, elapsedMs = 0L))
        assertTrue(ModelLoadPlan.shouldWaitForLlama("high", advisorLoaded = false, elapsedMs = 7999L))
    }

    @Test
    fun testWaitForLlamaNeverForLowOrLoadedOrExpired() {
        assertFalse(ModelLoadPlan.shouldWaitForLlama("low", advisorLoaded = false, elapsedMs = 0L))
        assertFalse(ModelLoadPlan.shouldWaitForLlama("medium", advisorLoaded = true, elapsedMs = 0L))
        assertFalse(ModelLoadPlan.shouldWaitForLlama("high", advisorLoaded = true, elapsedMs = 100L))
        assertFalse(
            ModelLoadPlan.shouldWaitForLlama(
                "medium",
                advisorLoaded = false,
                elapsedMs = ModelLoadPlan.LLAMA_LOAD_WAIT_MS
            )
        )
        assertFalse(
            ModelLoadPlan.shouldWaitForLlama(
                "high",
                advisorLoaded = false,
                elapsedMs = ModelLoadPlan.LLAMA_LOAD_WAIT_MS + 1
            )
        )
    }

    @Test
    fun testLlamaGatePollIntervalFastOnlyWhenSmsWaiting() {
        assertEquals(100L, llamaGatePollIntervalMs(uiOpened = false, smsAnalysisWaiting = true, fastIntervalMs = 100L, idleIntervalMs = 30000L))
        assertEquals(100L, llamaGatePollIntervalMs(uiOpened = true, smsAnalysisWaiting = true, fastIntervalMs = 100L, idleIntervalMs = 30000L))
    }

    @Test
    fun testLlamaGatePollIntervalIdleOtherwise() {
        assertEquals(30000L, llamaGatePollIntervalMs(uiOpened = true, smsAnalysisWaiting = false, fastIntervalMs = 100L, idleIntervalMs = 30000L))
        assertEquals(30000L, llamaGatePollIntervalMs(uiOpened = false, smsAnalysisWaiting = false, fastIntervalMs = 100L, idleIntervalMs = 30000L))
    }

    @Test
    fun testShouldRefreshUrlClassifierWhenNullOrFailed() {
        assertTrue(shouldRefreshUrlClassifier(isReady = true, classifierLoaded = null))
        assertTrue(shouldRefreshUrlClassifier(isReady = true, classifierLoaded = false))
        assertFalse(shouldRefreshUrlClassifier(isReady = true, classifierLoaded = true))
        assertFalse(shouldRefreshUrlClassifier(isReady = false, classifierLoaded = null))
        assertFalse(shouldRefreshUrlClassifier(isReady = false, classifierLoaded = true))
    }

    @Test
    fun testLlamaLoadWaitIsEightSeconds() {
        assertEquals(8000L, ModelLoadPlan.LLAMA_LOAD_WAIT_MS)
    }

    @Test
    fun testLlamaVerifyTimeoutIsThirtySeconds() {
        assertEquals(30000L, ModelLoadPlan.LLAMA_VERIFY_TIMEOUT_MS)
    }

    @Test
    fun testReleaseDecisionWaitsWhilePrefillRunning() {
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_UI_HIDDEN,
                analysisRunning = false,
                llamaLoaded = true,
                prefillRunning = true
            )
        )
        assertFalse(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_BACKGROUND,
                analysisRunning = false,
                llamaLoaded = true,
                prefillRunning = true
            )
        )
        assertTrue(
            ModelLoadPlan.shouldReleaseLlama(
                trimLevel = ModelLoadPlan.TRIM_LEVEL_UI_HIDDEN,
                analysisRunning = false,
                llamaLoaded = true,
                prefillRunning = false
            )
        )
    }

    @Test
    fun testSelectThreadCountWithAutoEnabledUsesProposal() {
        ModelLoadPlan.resetThreadsAutoCacheForTest()
        val dir = java.nio.file.Files.createTempDirectory("threads_auto_on").toFile()
        try {
            java.io.File(dir, CpuFeatures.THREADS_AUTO_FLAG_FILE_NAME).createNewFile()
            val proposal = CpuFeatures.proposeThreadCount(listOf(2200000000L to 2, 2000000000L to 6))
            assertEquals(2, proposal)
            assertEquals(
                proposal,
                ModelLoadPlan.selectThreadCountWithAuto(8, listOf(2200000000L to 2, 2000000000L to 6), dir)
            )
        } finally {
            ModelLoadPlan.resetThreadsAutoCacheForTest()
            dir.deleteRecursively()
        }
    }

    @Test
    fun testSelectThreadCountWithAutoDisabledUsesCoresHalf() {
        ModelLoadPlan.resetThreadsAutoCacheForTest()
        val dir = java.nio.file.Files.createTempDirectory("threads_auto_off").toFile()
        try {
            assertFalse(ModelLoadPlan.isThreadsAutoEnabled(dir))
            assertEquals(
                4,
                ModelLoadPlan.selectThreadCountWithAuto(8, listOf(2200000000L to 2, 2000000000L to 6), dir)
            )
        } finally {
            ModelLoadPlan.resetThreadsAutoCacheForTest()
            dir.deleteRecursively()
        }
    }

    @Test
    fun testIsThreadsAutoEnabledNullDirIsFalse() {
        ModelLoadPlan.resetThreadsAutoCacheForTest()
        try {
            assertFalse(ModelLoadPlan.isThreadsAutoEnabled(null))
        } finally {
            ModelLoadPlan.resetThreadsAutoCacheForTest()
        }
    }

    @Test
    fun testThreadsAutoReadOncePerProcessAllModelsAgree() {
        ModelLoadPlan.resetThreadsAutoCacheForTest()
        val dirA = java.nio.file.Files.createTempDirectory("threads_auto_a").toFile()
        val dirB = java.nio.file.Files.createTempDirectory("threads_auto_b").toFile()
        try {
            java.io.File(dirA, CpuFeatures.THREADS_AUTO_FLAG_FILE_NAME).createNewFile()
            assertTrue(ModelLoadPlan.isThreadsAutoEnabled(dirA))
            assertTrue(
                "second caller with another dir must see the same cached value",
                ModelLoadPlan.isThreadsAutoEnabled(dirB)
            )
            assertEquals(
                ModelLoadPlan.selectThreadCountWithAuto(8, listOf(2200000000L to 2), dirA),
                ModelLoadPlan.selectThreadCountWithAuto(8, listOf(2200000000L to 2), dirB)
            )
        } finally {
            ModelLoadPlan.resetThreadsAutoCacheForTest()
            dirA.deleteRecursively()
            dirB.deleteRecursively()
        }
    }

    @Test
    fun testThreadsAutoCachedFalseStaysFalseAfterFileAppears() {
        ModelLoadPlan.resetThreadsAutoCacheForTest()
        val dir = java.nio.file.Files.createTempDirectory("threads_auto_cache").toFile()
        try {
            assertFalse(ModelLoadPlan.isThreadsAutoEnabled(dir))
            java.io.File(dir, CpuFeatures.THREADS_AUTO_FLAG_FILE_NAME).createNewFile()
            assertFalse(
                "file appearing after the first read must not change the process-wide value",
                ModelLoadPlan.isThreadsAutoEnabled(dir)
            )
            assertEquals(
                4,
                ModelLoadPlan.selectThreadCountWithAuto(8, listOf(2200000000L to 2), dir)
            )
        } finally {
            ModelLoadPlan.resetThreadsAutoCacheForTest()
            dir.deleteRecursively()
        }
    }
}
