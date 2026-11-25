package org.ps3.sentinel.sms

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.core.CueSpan
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.ProcessedUrl
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.core.SmsResult
import org.ps3.sentinel.core.fuse
import org.junit.Assert.assertEquals
import java.io.File

class AlertPolicyRuleTest {
    @Test
    fun testHighAlwaysAlertsAndLowNever() {
        assertTrue(AlertPolicy.shouldAlert("high", emptySet(), false, 0.0))
        assertFalse(AlertPolicy.shouldAlert("low", setOf("credential_request"), true, 0.9))
    }

    @Test
    fun testMediumNeedsThreatEvidence() {
        assertFalse(AlertPolicy.shouldAlert("medium", emptySet(), false, 0.0))
        assertFalse(AlertPolicy.shouldAlert("medium", setOf("urgency", "reward"), true, 0.2))
        assertTrue(AlertPolicy.shouldAlert("medium", setOf("payment_request"), false, 0.0))
        assertTrue(AlertPolicy.shouldAlert("medium", setOf("impersonation"), true, 0.0))
        assertFalse(AlertPolicy.shouldAlert("medium", setOf("impersonation"), false, 0.0))
        assertTrue(AlertPolicy.shouldAlert("medium", emptySet(), true, 0.5))
    }

    @Test
    fun testRegisteredSenderMediumNeedsModelScam() {
        assertFalse(AlertPolicy.shouldAlert("medium", setOf("credential_request", "payment_request"), true, 0.9, "ham", registeredSender = true))
        assertFalse(AlertPolicy.shouldAlert("medium", setOf("threat"), false, 0.0, null, registeredSender = true))
        assertTrue(AlertPolicy.shouldAlert("medium", emptySet(), false, 0.0, "scam", registeredSender = true))
        assertTrue(AlertPolicy.shouldAlert("high", emptySet(), false, 0.0, "ham", registeredSender = true))
        assertTrue(AlertPolicy.shouldAlert("medium", setOf("credential_request"), false, 0.0, "ham", registeredSender = false))
    }

    @Test
    fun testRegisteredSenderLinkAloneIsQuietAndOtherSendersAlert() {
        val ham = org.ps3.sentinel.core.SmsResult(mapOf("ham" to 0.9, "unwanted" to 0.05, "scam" to 0.05), "ham")
        val urls = listOf(org.ps3.sentinel.core.UrlResult("http://bit.ly/a1", "bit.ly/a1", 0.99, "phishing", emptyList()))
        val text = "Sale is live. Shop now: http://bit.ly/a1"
        val registered = org.ps3.sentinel.core.fuse(text, ham, urls, emptyList(), emptySet(), sender = "AD-NEWSHP-P")
        assertTrue(registered.registeredSender)
        assertFalse(AlertPolicy.shouldAlert(registered))
        for (sender in listOf(null, "+919876543210", "56161")) {
            assertTrue("sender $sender", AlertPolicy.shouldAlert(org.ps3.sentinel.core.fuse(text, ham, urls, emptyList(), emptySet(), sender = sender)))
        }
    }

    @Test
    fun testEvidenceHighAlerts() {
        assertTrue(AlertPolicy.shouldAlert(evidence("high")))
    }

    @Test
    fun testEvidenceMediumWithScamSmsLabelAlerts() {
        assertTrue(AlertPolicy.shouldAlert(evidence("medium", smsLabel = "scam")))
    }

    @Test
    fun testEvidenceMediumWithUnwantedSmsLabelAndNoCueIsQuiet() {
        assertFalse(AlertPolicy.shouldAlert(evidence("medium", smsLabel = "unwanted")))
    }

    @Test
    fun testEvidenceMediumWithCredentialRequestCueAlerts() {
        assertTrue(
            AlertPolicy.shouldAlert(evidence("medium", cueTypes = setOf("credential_request")))
        )
    }

    @Test
    fun testEvidenceLowIsQuiet() {
        val low = evidence(
            "low",
            cueTypes = setOf("credential_request"),
            urls = listOf(url(0.9))
        )
        assertFalse(AlertPolicy.shouldAlert(low))
    }

    @Test
    fun testEvidenceMediumWithSenderMismatchCueAlerts() {
        assertTrue(
            AlertPolicy.shouldAlert(evidence("medium", cueTypes = setOf("sender_mismatch")))
        )
    }

    @Test
    fun testEvidenceMediumWithUntrustedUrlAlerts() {
        val medium = evidence("medium", urls = listOf(url(0.5)))
        assertTrue(AlertPolicy.shouldAlert(medium))
    }

    @Test
    fun testEvidenceMediumWithTrustedUrlIsQuiet() {
        val medium = evidence("medium", urls = listOf(url(0.9, trusted = true)))
        assertFalse(AlertPolicy.shouldAlert(medium))
    }

    private fun evidence(
        level: String,
        cueTypes: Set<String> = emptySet(),
        urls: List<ProcessedUrl> = emptyList(),
        smsLabel: String? = null
    ): Evidence = Evidence(
        label = "unwanted",
        risk = 0.45,
        level = level,
        cueSpans = cueTypes.map { CueSpan(type = it, start = 0, end = 0, text = it) },
        urls = urls,
        smsLabel = smsLabel
    )

    private fun url(prob: Double, trusted: Boolean = false): ProcessedUrl = ProcessedUrl(
        url = "https://example.test",
        normUrl = "example.test",
        prob = prob,
        rawProb = prob,
        trusted = trusted,
        indicators = emptyList(),
        label = "benign"
    )

    private fun loadRules() {
        val file = listOf("../../sentinel/data/rules.json", "../sentinel/data/rules.json", "sentinel/data/rules.json")
            .map { File(it) }.first { it.isFile }
        Rules.activate(Rules.fromJson(file.readText(Charsets.UTF_8)))
    }

    @Test
    fun modelLessVerdictIsNotFull() {
        // A model wait that timed out leaves smsLabel null: the receiver must retry, not finish.
        loadRules()
        val ham = SmsResult(mapOf("ham" to 0.9, "unwanted" to 0.05, "scam" to 0.05), "ham")
        assertTrue(SmsReceiver.hasModelAnswer(fuse("Lunch at 1 pm?", ham, emptyList(), emptyList())))
        assertFalse(SmsReceiver.hasModelAnswer(fuse("Lunch at 1 pm?", null, emptyList(), emptyList())))
        assertFalse(SmsReceiver.hasModelAnswer(null))
    }

    @Test
    fun scamScriptIsHighAndAdvisoryIsNot() {
        loadRules()
        val ham = SmsResult(mapOf("ham" to 0.98, "unwanted" to 0.01, "scam" to 0.01), "ham")
        val scam = fuse("CBI calling. You are under digital arrest; join the video call now.", ham, emptyList(), emptyList())
        assertEquals("high", scam.level)
        assertTrue("digital arrest threat" in scam.indicators)
        val advisory = fuse("Digital arrest is a scam. Call helpline 1930.", ham, emptyList(), emptyList())
        assertEquals("low", advisory.level)
    }
}
