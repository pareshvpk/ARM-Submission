package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.ps3.sentinel.R

class ResultTextLabelsTest {

    @Test
    fun testEvidenceLabelMappingCoversKnownLabels() {
        assertEquals(R.string.evidence_label_scam, ResultTextLabels.evidenceLabelRes("scam"))
        assertEquals(R.string.evidence_label_unwanted, ResultTextLabels.evidenceLabelRes("unwanted"))
        assertEquals(R.string.evidence_label_ham, ResultTextLabels.evidenceLabelRes("ham"))
        assertEquals(R.string.evidence_label_scam, ResultTextLabels.evidenceLabelRes("SCAM"))
        assertNull("unknown labels stay unchanged", ResultTextLabels.evidenceLabelRes("phishing"))
    }

    @Test
    fun testUrlLabelMappingCoversKnownAndUnknownLabels() {
        assertEquals(R.string.link_label_phishing, ResultTextLabels.urlLabelRes("phishing"))
        assertEquals(R.string.link_label_benign, ResultTextLabels.urlLabelRes("benign"))
        assertEquals(R.string.link_label_benign, ResultTextLabels.urlLabelRes("BENIGN"))
        assertNull("unknown URL labels stay unchanged", ResultTextLabels.urlLabelRes("scam"))
    }

    @Test
    fun testUrlIndicatorMappingCoversKnownAndUnknownIndicators() {
        assertEquals(R.string.link_indicator_ip_host, ResultTextLabels.urlIndicatorRes("ip_host"))
        assertEquals(R.string.link_indicator_punycode, ResultTextLabels.urlIndicatorRes("punycode"))
        assertEquals(R.string.link_indicator_at_sign, ResultTextLabels.urlIndicatorRes("at_sign"))
        assertEquals(
            R.string.link_indicator_many_subdomains,
            ResultTextLabels.urlIndicatorRes("many_subdomains")
        )
        assertEquals(R.string.link_indicator_risky_tld, ResultTextLabels.urlIndicatorRes("risky_tld"))
        assertEquals(R.string.link_indicator_shortener, ResultTextLabels.urlIndicatorRes("shortener"))
        assertEquals(
            R.string.link_indicator_brand_lookalike,
            ResultTextLabels.urlIndicatorRes("brand_lookalike")
        )
        assertEquals(
            R.string.link_indicator_unparseable_url,
            ResultTextLabels.urlIndicatorRes("unparseable_url")
        )
        assertEquals(
            R.string.link_indicator_url_model_error,
            ResultTextLabels.urlIndicatorRes("url_model_error")
        )
        assertEquals(
            R.string.link_indicator_risky_tld,
            ResultTextLabels.urlIndicatorRes("RISKY_TLD")
        )
        assertNull(
            "unknown indicators stay unchanged",
            ResultTextLabels.urlIndicatorRes("some_new_indicator")
        )
    }

    @Test
    fun testModelStatusFixedPhrasesLocalizedAndDetailsKept() {
        val status = "All models available (URL CNN + Llama 3.2); SMS model: loaded (real length)"
        val localized = ResultTextLabels.localizeModelStatus(status) { id ->
            when (id) {
                R.string.model_status_all_available -> "ALL_AVAILABLE"
                R.string.model_status_sms_model -> "; SMS_MODEL:"
                R.string.sms_status_loaded_real_length -> "LOADED_REAL"
                else -> "?"
            }
        }
        assertEquals("ALL_AVAILABLE; SMS_MODEL: LOADED_REAL", localized)
    }
}
