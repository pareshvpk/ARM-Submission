/**
 * Pure Kotlin localized advice text builder for Hindi and Tamil locales.
 * Replaces Llama generative advice with pre-translated safe recommendation templates and actionable steps.
 * Pure string and resource lookup logic without direct Android framework dependencies.
 */
package org.ps3.sentinel.ui

import androidx.annotation.StringRes
import org.ps3.sentinel.R
import org.ps3.sentinel.core.Evidence
import java.util.Locale

/**
 * Purpose:  Builds the fixed Tamil/Hindi advice shown instead of Llama, and decides when it applies.
 * Owns:     Nothing.
 * Lifetime: Process
 * Thread:   any — pure functions, no Android or shared state is touched.
 */
object AdviceText {

    /**
     * Returns "ta" or "hi" when the fixed advice must replace Llama, else null.
     *
     * Uses the first per-app language when one is set, otherwise the resolved
     * resources language. English (including system default on an English
     * phone) returns null and keeps the existing Llama path.
     */
    fun fixedAdviceLanguage(appLanguages: List<String>, resolvedLanguage: String): String? {
        val candidate = appLanguages.firstOrNull { it.isNotBlank() } ?: resolvedLanguage
        val language = candidate.substringBefore('-').substringBefore('_').lowercase(Locale.US)
        return if (language == "ta" || language == "hi") language else null
    }

    @StringRes
    private fun introRes(label: String, isPromotion: Boolean): Int = when {
        isPromotion -> R.string.advice_promotion_intro
        label == "scam" -> R.string.advice_scam_intro
        label == "unwanted" -> R.string.advice_unwanted_intro
        else -> R.string.advice_safe_intro
    }

    @StringRes
    private fun stepRes(label: String, isPromotion: Boolean, step: Int): Int = when {
        isPromotion -> when (step) {
            1 -> R.string.advice_promotion_step1
            2 -> R.string.advice_promotion_step2
            else -> R.string.advice_promotion_step3
        }
        label == "scam" -> when (step) {
            1 -> R.string.advice_scam_step1
            2 -> R.string.advice_scam_step2
            else -> R.string.advice_scam_step3
        }
        label == "unwanted" -> when (step) {
            1 -> R.string.advice_unwanted_step1
            2 -> R.string.advice_unwanted_step2
            else -> R.string.advice_unwanted_step3
        }
        else -> when (step) {
            1 -> R.string.advice_safe_step1
            2 -> R.string.advice_safe_step2
            else -> R.string.advice_safe_step3
        }
    }

    /**
     * Builds the fixed advice in the templateAdvice shape: the intro line, then
     * "1. ", "2. ", "3. " step lines, so templateSteps and STEP_LINE_REGEX
     * still parse it. [lookup] resolves a string resource id.
     */
    fun localizedAdvice(evidence: Evidence, isPromotion: Boolean, lookup: (Int) -> String): String {
        val intro = lookup(introRes(evidence.label, isPromotion))
        val steps = (1..3).joinToString("\n") { step ->
            "$step. " + lookup(stepRes(evidence.label, isPromotion, step))
        }
        return intro + "\n" + steps
    }
}
