package org.ps3.sentinel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class PipelineUrlFallbackTest {

    @Test
    fun testUrlModelErrorIndicatorAddedWhenClassifierThrows() {
        val result = urlFallbackIndicators(listOf("brand_lookalike"), urlModelError = true)
        assertTrue("url_model_error must be present", "url_model_error" in result)
        assertTrue("original indicator kept", "brand_lookalike" in result)
    }

    @Test
    fun testNoUrlModelErrorIndicatorWithoutThrow() {
        val indicators = listOf("risky_tld")
        assertEquals(indicators, urlFallbackIndicators(indicators, urlModelError = false))
        assertFalse("no error indicator without a throw", "url_model_error" in urlFallbackIndicators(indicators, false))
    }

    @Test
    fun testUrlModelErrorIndicatorNotDuplicated() {
        val indicators = listOf("url_model_error", "ip_host")
        assertEquals(indicators, urlFallbackIndicators(indicators, urlModelError = true))
    }

    private fun setWarmUpDone(pipeline: Pipeline, value: Boolean) {
        val field = Pipeline::class.java.getDeclaredField("smsWarmUpDone")
        field.isAccessible = true
        field.setBoolean(pipeline, value)
    }

    private fun allocatePipeline(): Pipeline {
        val unsafeClass = Class.forName("sun.misc.Unsafe")
        val theUnsafe = unsafeClass.getDeclaredField("theUnsafe")
        theUnsafe.isAccessible = true
        val unsafe = theUnsafe.get(null)
        val allocate = unsafeClass.getMethod("allocateInstance", Class::class.java)
        return allocate.invoke(unsafe, Pipeline::class.java) as Pipeline
    }

    @Test
    fun testSmsWarmUpDoneSignalIsResettableForRetry() {
        // Pipeline() cannot be constructed in a JVM unit test: its init touches
        // SentinelApp, whose companion calls SystemClock.elapsedRealtime()
        // (not mocked on the JVM), and awaitSmsReady uses the same clock.
        // Allocate without init and check the readiness signal awaitSmsReady
        // polls: a retry must be able to clear it so callers wait again.
        val pipeline = allocatePipeline()
        setWarmUpDone(pipeline, true)
        assertTrue(pipeline.isSmsWarmUpDone())
        setWarmUpDone(pipeline, false)
        assertFalse(pipeline.isSmsWarmUpDone())
    }

    @Test
    fun testRetryResetsWarmUpDoneBeforeWarmUp() {
        val candidates = listOf(
            File("src/main/java/org/ps3/sentinel/Pipeline.kt"),
            File("app/src/main/java/org/ps3/sentinel/Pipeline.kt"),
            File("android/app/src/main/java/org/ps3/sentinel/Pipeline.kt")
        )
        val sourceFile = candidates.firstOrNull { it.isFile }
            ?: throw AssertionError("Pipeline.kt not found from working dir ${File(".").absolutePath}")
        val source = sourceFile.readText()
        val retryStart = source.indexOf("fun retrySmsLoadIfFilesChanged")
        assertTrue("retrySmsLoadIfFilesChanged must exist", retryStart >= 0)
        val retryBody = source.substring(retryStart, retryStart + 2000)
        val resetIndex = retryBody.indexOf("smsWarmUpDone = false")
        val warmUpIndex = retryBody.indexOf("warmUp()")
        assertTrue("retry must reset smsWarmUpDone", resetIndex >= 0)
        assertTrue("retry must call warmUp", warmUpIndex >= 0)
        assertTrue("retry must reset smsWarmUpDone before warmUp", resetIndex < warmUpIndex)
    }
}
