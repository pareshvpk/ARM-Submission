package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.ps3.sentinel.R
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.firstStepIndex

class AdviceTextTest {

    @Test
    fun fixedAdviceLanguageUsesAppLanguageThenResolvedLocale() {
        assertEquals("ta", AdviceText.fixedAdviceLanguage(listOf("ta"), "en"))
        assertEquals("hi", AdviceText.fixedAdviceLanguage(listOf("hi-IN"), "en"))
        assertEquals("ta", AdviceText.fixedAdviceLanguage(emptyList(), "ta"))
        assertEquals("hi", AdviceText.fixedAdviceLanguage(emptyList(), "hi-IN"))
        assertEquals("ta", AdviceText.fixedAdviceLanguage(listOf("TA"), "en"))
        assertNull(AdviceText.fixedAdviceLanguage(listOf("en"), "hi"))
        assertNull(AdviceText.fixedAdviceLanguage(emptyList(), "en"))
    }

    @Test
    fun localizedAdviceHasTemplateShapeAndPicksTheBlock() {
        val lookup: (Int) -> String = { id ->
            when (id) {
                R.string.advice_scam_intro -> "scam intro"
                R.string.advice_scam_step1 -> "scam one"
                R.string.advice_scam_step2 -> "scam two"
                R.string.advice_scam_step3 -> "scam three"
                R.string.advice_unwanted_intro -> "unwanted intro"
                R.string.advice_unwanted_step1 -> "unwanted one"
                R.string.advice_unwanted_step2 -> "unwanted two"
                R.string.advice_unwanted_step3 -> "unwanted three"
                R.string.advice_safe_intro -> "safe intro"
                R.string.advice_safe_step1 -> "safe one"
                R.string.advice_safe_step2 -> "safe two"
                R.string.advice_safe_step3 -> "safe three"
                R.string.advice_promotion_intro -> "promotion intro"
                R.string.advice_promotion_step1 -> "promotion one"
                R.string.advice_promotion_step2 -> "promotion two"
                R.string.advice_promotion_step3 -> "promotion three"
                else -> "?"
            }
        }

        val scam = AdviceText.localizedAdvice(Evidence("scam", 0.9, "high"), isPromotion = false, lookup)
        assertEquals("scam intro\n1. scam one\n2. scam two\n3. scam three", scam)
        assertEquals("scam intro\n", scam.substring(0, firstStepIndex(scam)))

        val unwanted = AdviceText.localizedAdvice(Evidence("unwanted", 0.5, "medium"), isPromotion = false, lookup)
        assertEquals("unwanted intro\n1. unwanted one\n2. unwanted two\n3. unwanted three", unwanted)

        val safe = AdviceText.localizedAdvice(Evidence("ham", 0.1, "low"), isPromotion = false, lookup)
        assertEquals("safe intro\n1. safe one\n2. safe two\n3. safe three", safe)

        val promotion = AdviceText.localizedAdvice(Evidence("unwanted", 0.5, "medium"), isPromotion = true, lookup)
        assertEquals("promotion intro\n1. promotion one\n2. promotion two\n3. promotion three", promotion)
    }
}
