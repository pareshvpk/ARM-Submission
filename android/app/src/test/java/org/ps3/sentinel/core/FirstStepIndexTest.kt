package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FirstStepIndexTest {

    private val scam = Evidence(label = "scam", risk = 0.9, level = "high")
    private val unwanted = Evidence(label = "unwanted", risk = 0.6, level = "medium")
    private val ham = Evidence(label = "ham", risk = 0.1, level = "low")

    @Test
    fun stepOnNewLineIsFound() {
        val text = "This message looks like a scam.\n1. Do not click any links."
        val index = firstStepIndex(text)
        assertTrue(index >= 0)
        assertFalse(text.substring(0, index).contains("1."))
    }

    @Test
    fun stepAfterFullStopOnSameLineIsFound() {
        val text = "This message looks like a scam. 1. Do not click any links."
        val index = firstStepIndex(text)
        assertTrue(index >= 0)
        assertEquals("This message looks like a scam.", text.substring(0, index))
    }

    @Test
    fun parenthesisVariantIsFound() {
        val text = "This message looks risky.\n1) Verify it through the official app."
        assertTrue(firstStepIndex(text) >= 0)
    }

    @Test
    fun numbersThatAreNotStepsAreIgnored() {
        val text = "The call 1930 was logged. The risk 1.5 and Rs 1.00 are odd. See 11. item and 21. more."
        assertEquals(-1, firstStepIndex(text))
    }

    @Test
    fun emptyTextHasNoStep() {
        assertEquals(-1, firstStepIndex(""))
    }

    @Test
    fun textStartingWithAStepReturnsZero() {
        assertEquals(0, firstStepIndex("1. Do not click any links."))
    }

    @Test
    fun guardBackfillsTemplateStepsAfterCut() {
        val text = "This message looks like a scam. 1. Do not click any links."
        val index = firstStepIndex(text)
        assertTrue(index >= 0)
        val explanation = text.substring(0, index)

        val (guarded, flags) = guard(explanation, scam)

        assertTrue("added_template_steps" in flags)
        assertTrue(guarded.endsWith(templateSteps(scam).joinToString("\n")))
    }

    @Test
    fun templateStepsHasThreeLinesForEachLabel() {
        assertEquals(3, templateSteps(scam).size)
        assertEquals(3, templateSteps(unwanted).size)
        assertEquals(3, templateSteps(ham).size)
    }

    @Test
    fun composeStreamingAdviceUsesPlaceholderWhenEmpty() {
        val steps = templateSteps(scam)
        assertEquals(
            "Analysing message...\n\n" + steps.joinToString("\n"),
            composeStreamingAdvice("", steps, "Analysing message...")
        )
    }

    @Test
    fun composeStreamingAdviceUsesStreamedTextWhenPresent() {
        val steps = templateSteps(scam)
        assertEquals(
            "This looks risky.\n\n" + steps.joinToString("\n"),
            composeStreamingAdvice("This looks risky.", steps, "Analysing message...")
        )
    }
}
