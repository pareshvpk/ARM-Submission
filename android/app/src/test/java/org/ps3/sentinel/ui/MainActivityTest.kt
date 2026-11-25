package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.R
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.core.TrustedDomainStore
import java.io.File

class MainActivityTest {

    @Test
    fun testSharedTextRejectionReasonBlank() {
        assertEquals("blank", MainActivity.sharedTextRejectionReason("", isAnalysing = false))
        assertEquals("blank", MainActivity.sharedTextRejectionReason("   ", isAnalysing = false))
        assertNull("null text is blank", MainActivity.sharedTextRejectionReason(null, isAnalysing = false))
    }

    @Test
    fun testSharedTextRejectionReasonTooLong() {
        val longText = "x".repeat(MainActivity.MAX_SHARED_TEXT_LENGTH + 1)
        assertEquals("too_long", MainActivity.sharedTextRejectionReason(longText, isAnalysing = false))
        // Exactly at the limit is acceptable.
        val limitText = "x".repeat(MainActivity.MAX_SHARED_TEXT_LENGTH)
        assertNull("limit length is acceptable", MainActivity.sharedTextRejectionReason(limitText, isAnalysing = false))
    }

    @Test
    fun testSharedTextRejectionReasonBusyWhileAnalysing() {
        assertEquals("busy", MainActivity.sharedTextRejectionReason("hello", isAnalysing = true))
        assertEquals("busy", MainActivity.sharedTextRejectionReason("", isAnalysing = true))
    }

    @Test
    fun testMaxSharedTextLengthIsTwoThousand() {
        assertEquals(2000, MainActivity.MAX_SHARED_TEXT_LENGTH)
    }

    @Test
    fun testCapManualInputTruncatesLongText() {
        val longText = "x".repeat(MainActivity.MAX_SHARED_TEXT_LENGTH + 500)
        val (capped, wasCut) = MainActivity.capManualInput(longText)
        assertTrue(wasCut)
        assertEquals(MainActivity.MAX_SHARED_TEXT_LENGTH, capped.length)
        val (short, shortCut) = MainActivity.capManualInput("hello")
        assertFalse(shortCut)
        assertEquals("hello", short)
        val limitText = "x".repeat(MainActivity.MAX_SHARED_TEXT_LENGTH)
        val (limit, limitCut) = MainActivity.capManualInput(limitText)
        assertFalse(limitCut)
        assertEquals(MainActivity.MAX_SHARED_TEXT_LENGTH, limit.length)
    }

    @Test
    fun testShouldDeletePendingBodyAfterRender() {
        assertTrue(MainActivity.shouldDeletePendingBodyAfterRender("msg-1"))
        assertFalse(MainActivity.shouldDeletePendingBodyAfterRender(null))
        assertFalse(MainActivity.shouldDeletePendingBodyAfterRender(""))
        assertFalse(MainActivity.shouldDeletePendingBodyAfterRender("   "))
    }

    @Test
    fun testHeadlineResPromotionKeepsAmberPill() {
        assertEquals(R.string.headline_promotion, MainActivity.headlineResFor("medium", true))
        assertEquals(R.string.headline_suspicious, MainActivity.headlineResFor("medium", false))
        assertEquals(R.string.headline_scam, MainActivity.headlineResFor("high", false))
        assertEquals(R.string.headline_safe, MainActivity.headlineResFor("low", false))
    }

    @Test
    fun testHeadlineResForShoeStorePromotion() {
        TrustedDomainStore.loadFromFile(findRepoFile("sentinel/data/trusted_domains.txt"))
        Rules.activate(Rules.fromJson(findRepoFile("sentinel/data/rules.json").readText(Charsets.UTF_8)))
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        val ev = Evidence(label = "unwanted", risk = 0.45, level = "medium")
        assertEquals(R.string.headline_promotion, MainActivity.headlineResFor(shoe, ev))
        assertEquals(R.string.headline_suspicious, MainActivity.headlineResFor("$shoe Reply YES to claim", ev))
        assertEquals(R.string.headline_suspicious, MainActivity.headlineResFor("$shoe metroshoes.com", ev))
    }

    private fun findRepoFile(relativePath: String): File {
        val candidates = listOf(
            File("../../$relativePath"),
            File("../$relativePath"),
            File(relativePath)
        )
        return candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("$relativePath not found for the unit test")
    }
}
