/**
 * Maps internal detector labels, URL indicators, and model status phrases to string resources.
 * Provides localized text for scam, unwanted, ham classifications and phishing indicators.
 * Pure mapping functions with no direct Android framework dependencies.
 */
package org.ps3.sentinel.ui

import androidx.annotation.StringRes
import org.ps3.sentinel.R
import java.util.Locale

/**
 * Purpose:  Maps detector and SMS class names, and fixed model status phrases, to UI strings.
 * Owns:     Nothing.
 * Lifetime: Process
 * Thread:   any — pure functions, no Android or shared state is touched.
 */
object ResultTextLabels {

    /**
     * Resource for an evidence label or SMS model class, or null for an unknown name.
     * The detector label set is scam/unwanted/ham (core/Fusion.kt and ml/SmsClassifier.kt).
     */
    @StringRes
    fun evidenceLabelRes(label: String): Int? = when (label.lowercase(Locale.US)) {
        "scam" -> R.string.evidence_label_scam
        "unwanted" -> R.string.evidence_label_unwanted
        "ham" -> R.string.evidence_label_ham
        else -> null
    }

    /**
     * Returns the string resource ID for URL classification label ("phishing" or "benign"), or null if unknown.
     */
    @StringRes
    fun urlLabelRes(label: String): Int? = when (label.lowercase(Locale.US)) {
        "phishing" -> R.string.link_label_phishing
        "benign" -> R.string.link_label_benign
        else -> null
    }

    /**
     * Returns the string resource ID for a heuristic URL indicator key, or null if unknown.
     */
    @StringRes
    fun urlIndicatorRes(indicator: String): Int? = when (indicator.lowercase(Locale.US)) {
        "ip_host" -> R.string.link_indicator_ip_host
        "punycode" -> R.string.link_indicator_punycode
        "at_sign" -> R.string.link_indicator_at_sign
        "many_subdomains" -> R.string.link_indicator_many_subdomains
        "risky_tld" -> R.string.link_indicator_risky_tld
        "shortener" -> R.string.link_indicator_shortener
        "brand_lookalike" -> R.string.link_indicator_brand_lookalike
        "unparseable_url" -> R.string.link_indicator_unparseable_url
        "url_model_error" -> R.string.link_indicator_url_model_error
        else -> null
    }

    // Longest and most specific phrases first so a shorter phrase never rewrites part of them.
    private val modelStatusPhrases: List<Pair<String, Int>> = listOf(
        "All models available (URL CNN + Llama 3.2)" to R.string.model_status_all_available,
        "URL CNN ready; Llama missing" to R.string.model_status_url_ready_llama_missing,
        "Missing models:" to R.string.model_status_missing_models,
        "Loaded: none" to R.string.model_status_loaded_none,
        "Loaded:" to R.string.model_status_loaded,
        "Refused:" to R.string.model_status_refused,
        "; RULES ERROR:" to R.string.model_status_rules_error,
        "; SMS model:" to R.string.model_status_sms_model,
        "; verifying model integrity" to R.string.model_status_verifying,
        "; MODEL ERRORS:" to R.string.model_status_model_errors,
        "; UNVERIFIED:" to R.string.model_status_unverified,
        "This phone's processor is older than the AI models need. Basic checks are on." to
            R.string.model_status_executorch_blocked,
        "loaded (real length)" to R.string.sms_status_loaded_real_length,
        "loaded (padded 128)" to R.string.sms_status_loaded_padded,
        "not installed" to R.string.sms_status_not_installed,
        "loading" to R.string.sms_status_loading,
        "loaded" to R.string.sms_status_loaded
    )

    /**
     * Replaces the fixed English phrases in [status] with the strings from [lookup], leaving
     * model file names, error details and any unknown text unchanged. Pure and testable.
     */
    fun localizeModelStatus(status: String, lookup: (Int) -> String): String {
        var text = status
        for ((phrase, resId) in modelStatusPhrases) {
            text = text.replace(phrase, lookup(resId))
        }
        return text
    }
}
