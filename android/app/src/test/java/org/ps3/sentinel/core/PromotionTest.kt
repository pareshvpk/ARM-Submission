package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.regex.Pattern

class PromotionTest {
    @Before
    fun setUp() {
        TrustedDomainStore.loadFromFile(findRepoFile("sentinel/data/trusted_domains.txt"))
        Rules.activate(Rules.fromJson(findRepoFile("sentinel/data/rules.json").readText(Charsets.UTF_8)))
    }

    private fun evidence(
        level: String = "medium",
        label: String = "unwanted",
        cues: List<CueSpan> = emptyList()
    ): Evidence = Evidence(label = label, risk = 0.45, level = level, cueSpans = cues)

    private fun findRepoFile(relativePath: String): File {
        val candidates = listOf(
            File("../../$relativePath"),
            File("../$relativePath"),
            File(relativePath)
        )
        return candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("$relativePath not found for the unit test")
    }

    @Test
    fun testPromotionRulesLoaded() {
        val promo = Rules.active().promotion
        assertEquals("medium", promo.level)
        assertEquals("unwanted", promo.label)
        assertEquals(
            setOf("urgency", "threat", "credential_request", "payment_request", "impersonation", "reward", "app_install"),
            promo.blockedCueTypes.toSet()
        )
        assertTrue(promo.replyContactPhrases.contains("reply"))
    }

    @Test
    fun testShoeStorePlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertTrue(isPlainPromotion(shoe, evidence()))
    }

    @Test
    fun testFallbackCompileKeepsPromotionSemantics() {
        val rules = Rules.active().promotion
        val compiler: (String, Int) -> Pattern = { regex, flags ->
            if ((flags and Pattern.UNICODE_CHARACTER_CLASS) != 0) {
                throw IllegalArgumentException("UNICODE_CHARACTER_CLASS not supported")
            } else {
                Pattern.compile("(?U)$regex", flags)
            }
        }
        val phonePattern = compilePatternWithFallback(
            rules.phoneDigitRunRegex,
            Pattern.UNICODE_CHARACTER_CLASS,
            compiler
        )
        assertNotNull(phonePattern)
        fun hasRun(value: String): Boolean {
            val matcher = phonePattern!!.matcher(value)
            while (matcher.find()) {
                if (matcher.group().filter { Character.isDigit(it) }.length >= rules.phoneMinDigits) return true
            }
            return false
        }
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(hasRun(shoe))
        assertTrue(hasRun("$shoe ९८७६५४३२१०"))
        val replyPattern = compilePatternWithFallback(
            "\\b" + Pattern.quote("reply") + "\\b",
            Pattern.CASE_INSENSITIVE or Pattern.UNICODE_CHARACTER_CLASS,
            compiler
        )
        assertNotNull(replyPattern)
        assertFalse(replyPattern!!.matcher(shoe).find())
        assertTrue(replyPattern.matcher("$shoe Reply YES to claim").find())
        assertNull(
            compilePatternWithFallback(
                rules.phoneDigitRunRegex,
                Pattern.UNICODE_CHARACTER_CLASS
            ) { _, _ -> throw IllegalArgumentException("always") }
        )
        assertTrue(isPlainPromotion(shoe, evidence()))
        assertFalse(isPlainPromotion("$shoe ९८७६५४३२१०", evidence()))
        assertFalse(isPlainPromotion("$shoe Call ९८७६५४३२१०", evidence()))
    }

    @Test
    fun testShoePlusUrlNotPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe Visit metroshoes.com now", evidence()))
        assertFalse(isPlainPromotion("$shoe http://example.com/offer", evidence()))
    }

    @Test
    fun testShoePlusDomainLikeNotPlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe Visit shop-now.world", evidence()))
    }

    @Test
    fun testShoePlusEmailNotPlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe mail offers@metro.in", evidence()))
    }

    @Test
    fun testShoePlusPaymentHandleNotPlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe pay to metro@ybl", evidence()))
    }

    @Test
    fun testShoePlusDigitsStillPlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertTrue(isPlainPromotion("$shoe Rs 499.99", evidence()))
    }

    @Test
    fun testShoePlusStarsStillPlainPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertTrue(isPlainPromotion("$shoe 4.5 stars", evidence()))
    }


    @Test
    fun testShoePlusPhoneNotPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe 9876543210", evidence()))
        assertFalse(isPlainPromotion("$shoe Call 9876543210", evidence()))
    }

    @Test
    fun testShoePlusDevanagariPhoneNotPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe ९८७६५४३२१०", evidence()))
        assertFalse(isPlainPromotion("$shoe Call ९८७६५४३२१०", evidence()))
    }

    @Test
    fun testBlockedCueTypesSubsetOfTypeOrder() {
        val known = Rules.active().cues.typeOrder.toSet()
        for (cueType in Rules.active().promotion.blockedCueTypes) {
            assertTrue("blocked cue type $cueType missing from cues.type_order", known.contains(cueType))
        }
    }

    @Test
    fun testShoePlusReplyNotPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion("$shoe Reply YES to claim", evidence()))
        assertFalse(isPlainPromotion("$shoe Please reply", evidence()))
    }

    @Test
    fun testShoeHighLevelNotPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        assertFalse(isPlainPromotion(shoe, evidence(level = "high")))
        assertFalse(isPlainPromotion(shoe, evidence(level = "low")))
        assertFalse(isPlainPromotion(shoe, evidence(label = "scam")))
        assertFalse(isPlainPromotion(shoe, evidence(label = "ham")))
    }

    @Test
    fun testCueBlocksPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        val cues = listOf(CueSpan(type = "urgency", start = 0, end = 5, text = "urgent"))
        assertFalse(isPlainPromotion(shoe, evidence(cues = cues)))
        val cues2 = listOf(CueSpan(type = "reward", start = 0, end = 4, text = "won"))
        assertFalse(isPlainPromotion(shoe, evidence(cues = cues2)))
    }

    @Test
    fun testReplyPhrasesBlock() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        for (phrase in listOf("WhatsApp us", "Please call us", "Message us now", "DM for details", "Send YES")) {
            assertFalse(phrase, isPlainPromotion("$shoe $phrase", evidence()))
        }
    }

    @Test
    fun testPromotionAdviceTextMatchesPython() {
        assertEquals(Rules.active().promotion.adviceText, PROMOTION_ADVICE)
        assertEquals(
            "Promotion: no action needed. Ignore it, or block the sender if you do not want these.",
            PROMOTION_ADVICE.lines().first()
        )
        assertFalse(PROMOTION_ADVICE.contains("No action needed. No action needed."))
        assertTrue(PROMOTION_ADVICE.startsWith("Promotion: no action needed."))
        assertTrue(PROMOTION_ADVICE.contains("Promotion: no action needed. Ignore it, or block the sender if you do not want these."))
        assertTrue(PROMOTION_ADVICE.contains("1. You do not need to reply or call."))
        assertTrue(PROMOTION_ADVICE.contains("2. Never share an OTP, PIN or password, even with a shop."))
        assertTrue(PROMOTION_ADVICE.contains("3. Block the sender if these messages bother you."))
    }

    @Test
    fun testFusePreservesVerdictForPromotion() {
        val shoe = "Flat 40 percent off on all shoes this weekend at Metro Shoes. Visit your nearest store. T&C apply"
        val sms = SmsResult(mapOf("ham" to 0.2, "unwanted" to 0.75, "scam" to 0.05), "unwanted")
        val ev = fuse(shoe, sms, emptyList(), smsCues(shoe))
        assertTrue(isPlainPromotion(shoe, ev))
        assertEquals("medium", ev.level)
        assertEquals("unwanted", ev.label)
    }
}
