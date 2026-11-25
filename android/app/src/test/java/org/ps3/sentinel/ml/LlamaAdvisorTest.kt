package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Test

class LlamaAdvisorTest {

    @Test
    fun testResolveAdviceSourceFallbackFlags() {
        assertEquals("template", resolveAdviceSource(listOf("refusal_fallback")))
        assertEquals("template", resolveAdviceSource(listOf("contradiction_fallback")))
        assertEquals("template", resolveAdviceSource(listOf("empty_fallback")))
        assertEquals("template", resolveAdviceSource(listOf("refusal_fallback", "hedged_certainty")))
        assertEquals("template", resolveAdviceSource(listOf("contradiction_fallback", "dropped_click_sentence")))
    }

    @Test
    fun testResolveAdviceSourceLlm() {
        assertEquals("llm", resolveAdviceSource(emptyList()))
        assertEquals("llm", resolveAdviceSource(listOf("hedged_certainty")))
        assertEquals("llm", resolveAdviceSource(listOf("dropped_click_sentence", "added_template_steps")))
    }
}
