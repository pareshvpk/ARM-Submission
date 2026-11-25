package org.ps3.sentinel.ml

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.text.Regex

/**
 * Parity test for FRAG-01 (URL phishing threshold) and FRAG-02 (SMS label order).
 *
 * The source of truth for the URL phishing threshold is sentinel/data/rules.json
 * (fusion.url_phishing_label_threshold). The SMS label order still comes from
 * sentinel/detectors.py (Python).
 *
 * This test reads those sources and asserts the URL threshold and the SMS label order match the Kotlin
 * constants in UrlClassifier and SmsClassifier.
 */
class MlConstantsTest {

    private fun readDetectorsPy(): String {
        val candidates = listOf(
            File("../../../sentinel/detectors.py"),
            File("../../sentinel/detectors.py"),
            File("../sentinel/detectors.py"),
            File("sentinel/detectors.py")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw AssertionError("sentinel/detectors.py not found on the test classpath")
        return file.readText()
    }

    private fun readRulesJson(): JSONObject {
        val candidates = listOf(
            File("../../../sentinel/data/rules.json"),
            File("../../sentinel/data/rules.json"),
            File("../sentinel/data/rules.json"),
            File("sentinel/data/rules.json")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw AssertionError("sentinel/data/rules.json not found on the test classpath")
        return JSONObject(file.readText())
    }

    @Test
    fun testUrlThresholdMatchesPython() {
        val fusion = readRulesJson().getJSONObject("fusion")
        assertTrue(
            "Could not find url_phishing_label_threshold in sentinel/data/rules.json",
            fusion.has("url_phishing_label_threshold")
        )
        val rulesThreshold = fusion.getDouble("url_phishing_label_threshold")
        assertEquals("URL phishing threshold must match sentinel/data/rules.json", UrlClassifier.URL_PHISHING_THRESHOLD, rulesThreshold, 0.001)
    }

    @Test
    fun testSmsLabelOrderMatchesPython() {
        val text = readDetectorsPy()
        val probsMatch = Regex("probs\\s*=\\s*\\{([^}]*)\\}").find(text)
        assertTrue("Could not find probs dict in sentinel/detectors.py", probsMatch != null)
        val fields = probsMatch!!.groupValues[1]

        val labelsInPythonOrder = listOf("ham", "unwanted", "scam")
            .map { label -> label to fields.indexOf("\"$label\"") }
            .sortedBy { it.second }
            .map { it.first }

        assertEquals(
            "SMS labels must appear in Python order ham, unwanted, scam",
            listOf("ham", "unwanted", "scam"),
            labelsInPythonOrder
        )

        assertEquals("SMS_LABEL_HAM must match Python index 0", 0, SmsClassifier.SMS_LABEL_HAM)
        assertEquals("SMS_LABEL_UNWANTED must match Python index 1", 1, SmsClassifier.SMS_LABEL_UNWANTED)
        assertEquals("SMS_LABEL_SCAM must match Python index 2", 2, SmsClassifier.SMS_LABEL_SCAM)
    }
}
