package org.ps3.sentinel.ml

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ResetContextTest {

    @Test
    fun testFullPromptAlwaysResets() {
        assertTrue(needsResetBeforeGenerate("full_prompt"))
    }

    @Test
    fun testPrefixCacheDoesNotResetWhenReady() {
        assertFalse(needsResetBeforeGenerate("prefix_cache"))
    }
}
