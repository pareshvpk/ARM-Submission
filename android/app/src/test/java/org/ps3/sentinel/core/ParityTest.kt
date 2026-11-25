package org.ps3.sentinel.core

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Replays the Python-generated fixture through the Kotlin detector and requires
 * the same cue spans, URL extraction, URL indicators per URL, label, level and
 * risk. This is the guard that stops the two shipped implementations from
 * drifting apart.
 */
class ParityTest {

    @Before
    fun setUp() {
        val trustedDomainFile = findRepoFile("sentinel/data/trusted_domains.txt")
        TrustedDomainStore.loadFromFile(trustedDomainFile)

        val rulesFile = findRepoFile("sentinel/data/rules.json")
        Rules.activate(Rules.fromJson(rulesFile.readText(Charsets.UTF_8)))
    }

    @Test
    fun testKotlinMatchesPythonParityCases() {
        val fixtureFile = findRepoFile("tests/fixtures/parity_cases.json")
        val fixture = JSONObject(fixtureFile.readText(Charsets.UTF_8))
        val cases = fixture.getJSONArray("cases")
        assertTrue("Expected at least 40 parity cases", cases.length() >= 40)

        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val text = case.getString("text")
            val expected = case.getJSONObject("expected")
            val sender = if (case.has("sender") && !case.isNull("sender")) case.getString("sender") else null

            val baseCues = smsCues(text)
            val senderSpan = if (sender != null) senderCue(sender, text) else null
            val cues = if (senderSpan != null) baseCues + senderSpan else baseCues
            assertEquals("cue spans for case $index", readCues(expected.getJSONArray("cues")), cues)

            val expectedSkipKind = if (expected.isNull("skip_kind")) null else expected.getString("skip_kind")
            assertEquals("skipKind for case $index", expectedSkipKind, skipKind(text))
            if (sender != null) {
                assertTrue("should_skip missing for case $index", expected.has("should_skip"))
                assertEquals(
                    "shouldSkip for case $index",
                    expected.getBoolean("should_skip"),
                    shouldSkip(sender, text)
                )
            }

            val evidence = fuse(
                text,
                readSmsResult(case),
                readUrlResults(case.getJSONArray("url_results")),
                cues,
                sender = sender
            )

            assertEquals("label for case $index", expected.getString("label"), evidence.label)
            assertEquals("level for case $index", expected.getString("level"), evidence.level)
            assertEquals("risk for case $index", expected.getDouble("risk"), evidence.risk, 1e-6)
            assertEquals("threshold for case $index", expected.getDouble("threshold"), evidence.threshold, 1e-6)
            assertEquals(
                "is_plain_promotion for case $index",
                expected.getBoolean("is_plain_promotion"),
                isPlainPromotion(text, evidence)
            )

            assertUrlExtraction(index, text, expected)
            assertUrlIndicators(index, case)
        }
    }

    /** Verify URL extraction and normalisation match the Python reference for one case. */
    private fun assertUrlExtraction(index: Int, text: String, expected: JSONObject) {
        val extracted = extractUrls(text)
        assertEquals(
            "extracted URLs for case $index",
            readStringList(expected.getJSONArray("extracted_urls")),
            extracted
        )

        val normalised = readStringList(expected.getJSONArray("normalised_urls"))
        for (position in extracted.indices) {
            assertEquals(
                "normalised URL $position for case $index",
                normalised[position],
                normaliseUrl(extracted[position])
            )
        }
    }

    /** Verify URL indicators match the Python reference for each URL in one case. */
    private fun assertUrlIndicators(index: Int, case: JSONObject) {
        val urlResults = case.getJSONArray("url_results")
        for (position in 0 until urlResults.length()) {
            val item = urlResults.getJSONObject(position)
            val url = item.getString("url")
            assertEquals(
                "URL indicators for URL $position in case $index ($url)",
                readStringList(item.getJSONArray("indicators")),
                urlIndicators(url)
            )
        }
    }

    private fun readCues(array: JSONArray): List<CueSpan> {
        val cues = mutableListOf<CueSpan>()
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            cues.add(
                CueSpan(
                    type = item.getString("type"),
                    start = item.getInt("start"),
                    end = item.getInt("end"),
                    text = item.getString("text")
                )
            )
        }
        return cues
    }

    private fun readSmsResult(case: JSONObject): SmsResult? {
        if (case.isNull("sms_result")) return null
        val result = case.getJSONObject("sms_result")
        val probsObject = result.getJSONObject("probs")
        val probs = mutableMapOf<String, Double>()
        val keys = probsObject.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            probs[key] = probsObject.getDouble(key)
        }
        return SmsResult(probs, result.getString("label"))
    }

    private fun readUrlResults(array: JSONArray): List<UrlResult> {
        val results = mutableListOf<UrlResult>()
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            results.add(
                UrlResult(
                    url = item.getString("url"),
                    normUrl = item.getString("norm_url"),
                    prob = item.getDouble("prob"),
                    label = item.getString("label"),
                    indicators = readStringList(item.getJSONArray("indicators"))
                )
            )
        }
        return results
    }

    private fun readStringList(array: JSONArray): List<String> {
        val values = mutableListOf<String>()
        for (index in 0 until array.length()) {
            values.add(array.getString(index))
        }
        return values
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
