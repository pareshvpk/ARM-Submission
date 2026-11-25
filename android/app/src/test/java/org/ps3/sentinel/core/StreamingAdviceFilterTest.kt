package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamingAdviceFilterTest {

    private fun scamEvidence(): Evidence = Evidence(label = "scam", risk = 0.9, level = "high")

    private fun stream(filter: StreamingAdviceFilter, tokens: List<String>): String {
        val out = StringBuilder()
        for (token in tokens) {
            out.append(filter.onToken(token))
        }
        return out.toString()
    }

    private fun byChars(text: String): List<String> = text.map { it.toString() }

    @Test
    fun testClickLinkSentenceNeverShown() {
        val filter = StreamingAdviceFilter(scamEvidence())
        val tokens = byChars("This message looks like a scam. Click the link and enter your OTP. This seems suspicious.")
        val shown = stream(filter, tokens)
        assertFalse("click sentence must never be shown", shown.contains("Click the link"))
        assertFalse("click sentence must never be shown", shown.contains("Click"))
        assertTrue("first sentence shown", shown.contains("This message looks like a scam."))
        assertTrue("last sentence shown", shown.contains("This seems suspicious."))
        assertTrue(
            "sentences stay in order",
            shown.indexOf("This message looks") < shown.indexOf("This seems")
        )
    }

    @Test
    fun testRefusalSentenceNeverShown() {
        val filter = StreamingAdviceFilter(scamEvidence())
        val tokens = byChars("This message looks like a scam. I cannot provide help for this. Do not share your OTP.")
        val shown = stream(filter, tokens)
        assertFalse("refusal sentence must never be shown", shown.contains("I cannot provide"))
        assertTrue("first sentence shown", shown.contains("This message looks like a scam."))
        assertTrue("last sentence shown", shown.contains("Do not share your OTP."))
    }

    @Test
    fun testSafeContradictionForScamNeverShown() {
        val filter = StreamingAdviceFilter(scamEvidence())
        val tokens = byChars("Do not share your OTP. This message is completely safe and legitimate. This looks suspicious.")
        val shown = stream(filter, tokens)
        assertFalse("contradiction sentence must never be shown", shown.contains("completely safe"))
        assertTrue("first sentence shown", shown.contains("Do not share your OTP."))
        assertTrue("last sentence shown", shown.contains("This looks suspicious."))
    }

    @Test
    fun testCleanStreamShowsAllSentencesInOrder() {
        val full = "This message looks like a scam. Do not share your OTP. Report this message."
        val filter = StreamingAdviceFilter(scamEvidence())
        val shown = stream(filter, byChars(full))
        assertEquals(full, shown)
    }

    @Test
    fun testNumberedStepsShownInOrder() {
        val full = "This message looks like a scam.\n1. Do not share your OTP.\n2. Report to the helpline."
        val filter = StreamingAdviceFilter(scamEvidence())
        val shown = stream(filter, byChars(full))
        assertEquals(full, shown)
    }

    @Test
    fun testFinalTextEqualsGuardOfFullOutput() {
        val evidence = scamEvidence()
        val full = "This message looks like a scam. Click the link to verify. Do not share your OTP."
        val filter = StreamingAdviceFilter(evidence)
        stream(filter, byChars(full))
        assertEquals(guard(full, evidence).first, filter.finish())
    }
}
