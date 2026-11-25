package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import kotlin.math.pow

class FusionTest {

    @Before
    fun setUp() {
        val trustedDomainCandidates = listOf(
            File("../../sentinel/data/trusted_domains.txt"),
            File("../sentinel/data/trusted_domains.txt"),
            File("sentinel/data/trusted_domains.txt")
        )
        val trustedDomainFile = trustedDomainCandidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("trusted_domains.txt not found for the unit test")
        TrustedDomainStore.loadFromFile(trustedDomainFile)

        val rulesCandidates = listOf(
            File("../../sentinel/data/rules.json"),
            File("../sentinel/data/rules.json"),
            File("sentinel/data/rules.json")
        )
        val rulesFile = rulesCandidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("rules.json not found for the unit test")
        Rules.activate(Rules.fromJson(rulesFile.readText(Charsets.UTF_8)))
    }

    @Test
    fun testIsTrustedDomains() {
        // Official trusted domains
        assertTrue("sbi.co.in should be trusted", isTrusted("sbi.co.in"))
        assertTrue("login.sbi.co.in should be trusted", isTrusted("login.sbi.co.in"))
        assertTrue("onlinesbi.sbi should be trusted", isTrusted("onlinesbi.sbi"))
        assertTrue("hdfcbank.com should be trusted", isTrusted("hdfcbank.com"))
        assertTrue("netbanking.hdfcbank.com should be trusted", isTrusted("netbanking.hdfcbank.com"))
        assertTrue("google.com should be trusted", isTrusted("google.com"))

        // Gov / nic suffixes
        assertTrue("incometax.gov.in should be trusted", isTrusted("incometax.gov.in"))
        assertTrue("epfindia.gov.in should be trusted", isTrusted("epfindia.gov.in"))
        assertTrue("uidai.gov.in should be trusted", isTrusted("uidai.gov.in"))
        assertTrue("something.nic.in should be trusted", isTrusted("something.nic.in"))

        // Untrusted hosting platforms (MUST NOT be trusted even if Google subdomains)
        assertTrue("sites.google.com is untrusted hosting", isUntrustedHosting("sites.google.com"))
        assertFalse("sites.google.com must NOT be trusted", isTrusted("sites.google.com"))
        assertFalse("docs.google.com must NOT be trusted", isTrusted("docs.google.com"))
        assertFalse("drive.google.com must NOT be trusted", isTrusted("drive.google.com"))
        assertFalse("forms.gle must NOT be trusted", isTrusted("forms.gle"))
        assertFalse("foo.firebaseapp.com must NOT be trusted", isTrusted("foo.firebaseapp.com"))
        assertFalse("bar.web.app must NOT be trusted", isTrusted("bar.web.app"))
        assertFalse("myblog.blogspot.com must NOT be trusted", isTrusted("myblog.blogspot.com"))
        assertFalse("phish.github.io must NOT be trusted", isTrusted("phish.github.io"))
        assertFalse("corp.sharepoint.com must NOT be trusted", isTrusted("corp.sharepoint.com"))
        assertFalse("gateway.ipfs.io must NOT be trusted", isTrusted("gateway.ipfs.io"))
        assertFalse("ipfs.io must NOT be trusted", isTrusted("ipfs.io"))
        assertTrue("gateway.ipfs.io is untrusted hosting", isUntrustedHosting("gateway.ipfs.io"))
        assertTrue("ipfs.io is untrusted hosting", isUntrustedHosting("ipfs.io"))
        assertFalse("myipfs.example.com is not untrusted hosting", isUntrustedHosting("myipfs.example.com"))
        assertFalse("cdn-ipfs.example.org is not untrusted hosting", isUntrustedHosting("cdn-ipfs.example.org"))

        // Untrusted lookalikes
        assertFalse("sbi-kyc.xyz must NOT be trusted", isTrusted("sbi-kyc.xyz"))
        assertFalse("hdfc-security.com must NOT be trusted", isTrusted("hdfc-security.com"))
        assertFalse("random-domain.in must NOT be trusted", isTrusted("random-domain.in"))
    }

    @Test
    fun testFuseScenario1TrustedBankDebitAlertHam() {
        val text = "Rs 500 debited from SBI account. Check balance at https://sbi.co.in"
        val smsRes = SmsResult(mapOf("ham" to 0.95, "unwanted" to 0.04, "scam" to 0.01), "ham")
        val urlRes = listOf(UrlResult("https://sbi.co.in", "sbi.co.in", 0.95, "benign", emptyList()))
        val cues = listOf(CueSpan("impersonation", 21, 24, "SBI"))

        val ev = fuse(text, smsRes, urlRes, cues)
        assertEquals("ham", ev.label)
        assertEquals("low", ev.level)
        assertTrue("URL must be marked trusted", ev.urls[0].trusted)
        assertEquals(0.95, ev.urls[0].rawProb, 0.000001)
        assertEquals("Trusted URL prob must be capped at the shared cap", 0.2, ev.urls[0].prob, 0.000001)
    }

    @Test
    fun testFuseScenario2LookalikeLinkKycUrgencyScam() {
        val text = "Dear customer your SBI account is blocked today. Update KYC now: http://sbi-kyc.xyz"
        val smsRes = SmsResult(mapOf("ham" to 0.02, "unwanted" to 0.08, "scam" to 0.90), "scam")
        val urlRes = listOf(
            UrlResult(
                "http://sbi-kyc.xyz",
                "sbi-kyc.xyz",
                0.95,
                "phishing",
                listOf("brand_lookalike", "risky_tld")
            )
        )
        val cues = listOf(
            CueSpan("urgency", 34, 41, "blocked"),
            CueSpan("credential_request", 56, 59, "KYC")
        )

        val ev = fuse(text, smsRes, urlRes, cues)
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
        assertTrue("Risk score should be >= 0.7", ev.risk >= 0.7)
        assertFalse("Lookalike link must not be trusted", ev.urls[0].trusted)
    }

    @Test
    fun testFuseScenario3NoModelCuesOnly() {
        val text = "URGENT! You won lottery cash prize! Legal action if not claimed today!"
        val cues = listOf(
            CueSpan("urgency", 0, 6, "URGENT"),
            CueSpan("reward", 16, 23, "lottery"),
            CueSpan("threat", 36, 48, "Legal action")
        )

        val ev = fuse(text, null, emptyList(), cues)
        // urgency + threat combination triggers combo rule: 0.72
        assertEquals(0.72, ev.risk, 0.001)
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
    }

    @Test
    fun testFuseHinglishThreatComboIsScam() {
        val text = "Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko 9876543210 call karein"
        val cues = smsCues(text)
        val ev = fuse(text, null, emptyList(), cues)
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
    }

    @Test
    fun testFuseOtpAlertStaysLow() {
        val text = "Your OTP for HDFC NetBanking is 482910. Valid for 5 mins. Do not share it with anyone."
        val cues = smsCues(text)
        val ev = fuse(text, null, emptyList(), cues)
        assertEquals("low", ev.level)
    }

    @Test
    fun testFuseScenario4HostedDocsGooglePhishingNotTrusted() {
        val text = "Verify your account immediately: https://docs.google.com/forms/d/e/123/viewform"
        val smsRes = SmsResult(mapOf("ham" to 0.1, "unwanted" to 0.2, "scam" to 0.7), "scam")
        val urlRes = listOf(
            UrlResult(
                "https://docs.google.com/forms/d/e/123/viewform",
                "docs.google.com/forms/d/e/123/viewform",
                0.92,
                "phishing",
                emptyList()
            )
        )
        val cues = listOf(
            CueSpan("credential_request", 0, 6, "Verify"),
            CueSpan("urgency", 23, 34, "immediately")
        )

        val ev = fuse(text, smsRes, urlRes, cues)
        assertFalse("docs.google.com must NOT be trusted", ev.urls[0].trusted)
        assertEquals(0.92, ev.urls[0].prob, 0.001)
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
    }

    @Test
    fun testFuseScenario5UnwantedMarketingPromo() {
        val text = "Mega sale cashback offer today! Use code SAVE50."
        val smsRes = SmsResult(mapOf("ham" to 0.2, "unwanted" to 0.75, "scam" to 0.05), "unwanted")
        val cues = listOf(CueSpan("reward", 10, 18, "cashback"))

        val ev = fuse(text, smsRes, emptyList(), cues)
        assertEquals("unwanted", ev.label)
    }

    @Test
    fun testAppInstallCueFloorsRiskAtScam() {
        val text = "Loan approved. Download APK from loan-instant.xyz"
        val ev = fuse(text, null, emptyList(), smsCues(text))
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
        assertTrue("Expected risk to reach the shared app-install score", ev.risk >= 0.75)
    }

    @Test
    fun testCollectRequestPlusPinFloorsRiskAtScam() {
        val text = "You have received a UPI collect request of INR 10,000. Approve by entering your UPI PIN."
        val ev = fuse(text, null, emptyList(), smsCues(text))
        assertEquals("scam", ev.label)
        assertEquals("high", ev.level)
        assertTrue("Expected risk to reach the shared collect-plus-PIN score", ev.risk >= 0.75)
    }

    @Test
    fun testSenderMismatchFloorsRiskToMedium() {
        val cue = CueSpan("sender_mismatch", 0, 0, "")
        val ev = fuse("sender", null, emptyList(), listOf(cue))
        assertEquals("medium", ev.level)
        assertTrue("Risk must be at least the medium threshold", ev.risk >= 0.4)
        assertTrue(
            "Expected readable sender indicator",
            "bank-style alert sent from a personal mobile number" in ev.indicators
        )
    }

    @Test
    fun testSenderMismatchKeepsHighVerdictHigh() {
        val cue = CueSpan("sender_mismatch", 0, 0, "")
        val ev = fuse("sender", smsForScore(0.701), emptyList(), listOf(cue))
        assertEquals("high", ev.level)
    }

    @Test
    fun testEmptyProbsMapLeavesSmsLabelUnset() {
        val ev = fuse("empty probs", SmsResult(emptyMap(), "scam"), emptyList(), emptyList())
        assertNull(ev.smsLabel)
    }

    @Test
    fun testBankAlertWithCredentialRequestFloorsRiskToHigh() {
        val text = "Rs 4,999 debited from A/c XX9012. Reply with OTP 4821 to reverse the debit."
        val cues = listOf(CueSpan("credential_request", 0, 0, "OTP"))
        val ev = fuse(text, null, emptyList(), cues)
        assertEquals("high", ev.level)
        assertTrue("Risk must reach the high threshold", ev.risk >= 0.7)
        assertTrue(
            "Expected readable bank-alert indicator",
            "bank alert asking for a secret code" in ev.indicators
        )
    }

    @Test
    fun testGenuineOtpWithCredentialCueIsNotRaisedByBankAlertRule() {
        val text = "Your OTP is 482913. Do not share it with anyone."
        val cues = listOf(CueSpan("credential_request", 0, 0, "OTP"))
        val ev = fuse(text, null, emptyList(), cues)
        assertTrue("Level must not be high", ev.level != "high")
        assertTrue(
            "Bank-alert indicator must be absent",
            "bank alert asking for a secret code" !in ev.indicators
        )
    }

    @Test
    fun testSecretRequestAndIsBankAlertTrueForScams() {
        val texts = listOf(
            "Rs 4,999 debited from A/c XX9012. Read out OTP 4821 to the officer.",
            "Rs 4,999 debited from A/c XX9012. Spell out the 6 digit code 482193.",
            "Rs 4,999 debited from A/c XX9012. Repeat the code 482193 to cancel the debit.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 bata do.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 bataye.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 daal do.",
            "Rs 5,000 debited from A/c XX1234. OTP 4821 required to stop the debit.",
            "Rs 5,000 debited from A/c XX1234. Don't worry, share OTP with our executive to stop the debit.",
            "Rs 5,000 debited from A/c XX1234. Do not panic - send OTP 4821 to reverse.",
            "Rs 5,000 debited from A/c XX1234. No need to visit branch, just tell the OTP to our agent to cancel.",
            "Rs 5,000 debited from A/c XX1234. Kindly reveal your OTP to reverse the debit.",
            "Rs 5,000 debited from A/c XX1234. Please disclose your OTP to stop the debit.",
            "Rs 5,000 debited from A/c XX1234. Don't worry, our officer will call you, share OTP to reverse.",
            "Rs 5,000 debited from A/c XX1234. Don't worry share OTP 4821 to cancel.",
            "Rs 5,000 debited from A/c XX1234. If not you share OTP 4821 to cancel.",
            "Rs 5,000 debited from A/c XX1234. If you did not authorise share OTP to cancel.",
            "Rs 5,000 debited from A/c XX1234. If not you, we ask you to share OTP to reverse the transaction.",
            "Rs 5,000 debited from A/c XX1234. Don't worry, we request you to share OTP to reverse debit.",
            "Rs 5000 debited from A/c XX1234. Fikr mat karo OTP 4821 bhejo cancel karne ke liye",
            "Rs 5,000 debited from A/c XX1234. If you have not done this transaction, share OTP 4821 to cancel debit.",
            "Rs 5,000 debited from A/c XX1234. If this is not you, share OTP 4821 to cancel debit.",
            "Rs 5,000 debited from A/c XX1234. If not recognized, share OTP 4821 to cancel debit.",
            "Rs 5,000 debited from A/c XX1234. Do not delay, share OTP 4821 to cancel debit.",
            "Rs 5,000 debited from A/c XX1234. Cancel karne ke liye OTP batao na.",
            "Rs 5,000 debited from your card. Share OTP 4821 to cancel debit."
        )
        for (text in texts) {
            assertTrue(text, secretRequest(text))
            assertTrue(text, isBankAlert(text))
            val ev = fuse(text, null, emptyList(), smsCues(text))
            assertEquals("high", ev.level)
            assertTrue(text, "bank alert asking for a secret code" in ev.indicators)
        }
    }

    private val secretRequestFalseCases = listOf(
        "Rs 5,000 debited from A/c XX1234. Never share your OTP with anyone.",
        "Rs 5,000 debited from A/c XX1234 at ATM using PIN. Avl bal Rs 20,000.",
        "INR 1,500 withdrawn from A/c XX1234 using card PIN at ATM.",
        "Rs 1,000 debited from card XX1234. CVV was not used.",
        "Rs 500 debited from A/c XX1234 via UPI. Never share your UPI PIN.",
        "Rs 5,000 debited from A/c XX1234. Please verify this transaction in the app.",
        "Rs 0.00 debited from A/c XX1234 for KYC update.",
        "OTP 482913 for debit of Rs 5,000 from A/c XX1234. Do not share with anyone.",
        "Rs 5,000 debited from A/c XX1234. Share nothing; we never ask for OTP.",
        "Rs 2,000 credited to A/c XX1234 on 12-Nov. Ref 123456. Avl bal Rs 25,000. Do not share OTP.",
        "Rs 5,000 debited from A/c XX1234. Please do not share OTP or PIN with anyone.",
        "Rs 5,000 debited from A/c XX1234. OTP kisi ko mat batao.",
        "Rs 5,000 debited from A/c XX1234. Bank never asks you to share your OTP.",
        "Rs 5,000 debited from A/c XX1234. We will not ask you to share your PIN.",
        "Rs 5,000 debited from A/c XX1234. OTP kisi ko na bataye.",
        "Rs 5,000 debited from A/c XX1234. We never, under any circumstances, and for no reason, ask you to share your OTP to reverse the debit.",
        "Rs 5,000 debited from A/c XX1234. We do not under any circumstances ever ask you to share your OTP to reverse the debit.",
        "Rs 5,000 debited from A/c XX1234. Never reveal your OTP, PIN or CVV to anyone.",
        "Rs 5,000 debited from A/c XX1234. HDFC Bank never calls to ask you to disclose your OTP.",
        "Rs 5,000 debited from A/c XX1234. Never, under any circumstances, share your OTP.",
        "Rs 5,000 debited from A/c XX1234. Do not - we repeat - share your OTP.",
        "Rs 5,000 debited from A/c XX1234. Share your OTP with no one.",
        "Rs 5,000 debited from A/c XX1234. Tell no one your OTP or PIN.",
        "Rs 5,000 debited from A/c XX1234. Give your PIN to no one.",
        "Rs 5,000 debited from A/c XX1234. Never share, tell or disclose your OTP to anyone.",
        "Rs 5,000 debited from A/c XX1234. Quote reference code 849201 for any query.",
        "Rs 5,000 debited from A/c XX1234. Show code to merchant to collect goods.",
        "Rs 5,000 debited from A/c XX1234. Please quote code 123456 for any dispute.",
        "Rs 4,500.00 spent on Card XX1234 at RELIANCE on 14-Nov-26. Auth code 849201 - if not you, SMS BLOCK to 56767.",
        "Rs 5,000 debited from A/c XX1234. SMS with OTP has been sent to your registered mobile.",
        "Rs 5,000 debited from A/c XX1234 at ATM using PIN, if not you send SMS to 56767",
        "Rs 10,000 debited from A/c XX1234 at ATM using PIN, if you didn't do this forward this SMS to 9223008333",
        "Rs 5,000 debited from A/c XX1234. Share your OTP with no-one.",
        "Rs 5,000 debited from A/c XX1234. Neither bank nor its employees will ask you to share your OTP.",
        "Rs 5,000 debited from A/c XX1234. Share your OTP with none.",
        "482913 is your OTP for txn of Rs 5,000 at Amazon. Enter it on the payment page within 10 minutes."
    )

    @Test
    fun testSecretRequestFalseCases() {
        for (text in secretRequestFalseCases) {
            assertFalse(text, secretRequest(text))
        }
    }

    @Test
    fun testFuseNoModelsDoesNotReachHighForDisclaimersAndRoutineAlerts() {
        for (text in secretRequestFalseCases.dropLast(1)) {
            val ev = fuse(text, null, emptyList(), smsCues(text))
            assertTrue(text, ev.level != "high")
            assertFalse(text, "bank alert asking for a secret code" in ev.indicators)
        }
    }

    private fun rawProbsForScaled(hamScaled: Double, unwantedScaled: Double, scamScaled: Double): Map<String, Double> {
        val temperature = Rules.active().fusion.smsTemperature
        val hamPow = hamScaled.pow(temperature)
        val unwantedPow = unwantedScaled.pow(temperature)
        val scamPow = scamScaled.pow(temperature)
        val total = hamPow + unwantedPow + scamPow
        return mapOf(
            "ham" to hamPow / total,
            "unwanted" to unwantedPow / total,
            "scam" to scamPow / total
        )
    }

    private fun smsForScore(score: Double): SmsResult {
        val fusion = Rules.active().fusion
        val temperature = fusion.smsTemperature
        val scamWeight = fusion.smsScamWeight
        val scaledScam = score / scamWeight
        val scaledHam = 1.0 - scaledScam
        val hamPow = scaledHam.pow(temperature)
        val scamPow = scaledScam.pow(temperature)
        val total = hamPow + scamPow
        return SmsResult(
            mapOf("ham" to hamPow / total, "unwanted" to 0.0, "scam" to scamPow / total),
            if (score >= 0.5) "scam" else "ham"
        )
    }

    @Test
    fun testConfidentHamSuppressesUrgencyPaymentCombo() {
        val text = "Your parcel will be delivered today. Pay on delivery."
        val cues = smsCues(text)
        val confidentHam = SmsResult(rawProbsForScaled(0.9, 0.05, 0.05), "ham")

        val withModel = fuse(text, confidentHam, emptyList(), cues)
        assertEquals("ham", withModel.label)
        assertEquals("low", withModel.level)
        assertTrue("Combo must be suppressed for a confident ham", withModel.risk < 0.72)

        val withoutModel = fuse(text, null, emptyList(), cues)
        assertEquals(0.72, withoutModel.risk, 0.000001)
        assertEquals("scam", withoutModel.label)
    }

    @Test
    fun testHamConfidenceBoundaryControlsCombo() {
        val text = "Your parcel will be delivered today. Pay on delivery."
        val cues = smsCues(text)
        val atThreshold = SmsResult(rawProbsForScaled(0.8, 0.1, 0.1), "ham")
        val belowThreshold = SmsResult(rawProbsForScaled(0.79, 0.11, 0.1), "ham")

        assertTrue(fuse(text, atThreshold, emptyList(), cues).risk < 0.72)
        assertEquals(0.72, fuse(text, belowThreshold, emptyList(), cues).risk, 0.000001)
    }

    @Test
    fun testMalformedUrlDoesNotThrowAndIsSuspicious() {
        val urlResults = listOf(UrlResult("http://[bad-host", "http://[bad-host", 0.0, "benign", emptyList()))
        val ev = fuse("Pay fee at http://[bad-host", null, urlResults, emptyList())

        assertFalse("Malformed URLs must not be trusted", ev.urls[0].trusted)
        assertTrue("Malformed URL must carry the unparseable indicator", "unparseable_url" in ev.urls[0].indicators)
        assertTrue("Malformed URL must be at least suspicious", ev.urls[0].prob >= 0.5)
    }

    @Test
    fun testLabelAndLevelBoundaries() {
        val cases = listOf(
            Triple(0.399, "ham", "low"),
            Triple(0.4, "unwanted", "medium"),
            Triple(0.401, "unwanted", "medium"),
            Triple(0.699, "unwanted", "medium"),
            Triple(0.7, "scam", "high"),
            Triple(0.701, "scam", "high")
        )
        for ((score, expectedLabel, expectedLevel) in cases) {
            val sms = smsForScore(score)
            val ev = fuse("boundary check", sms, emptyList(), emptyList())
            assertEquals("label at $score", expectedLabel, ev.label)
            assertEquals("level at $score", expectedLevel, ev.level)
            assertEquals(0.7, ev.threshold, 0.000001)
        }
    }

    @Test
    fun testSixNewScamScriptsPositivesAndNegatives() {
        val positives = listOf(
            Pair(
                "Refund of Rs 4,999 is pending. Enter your UPI PIN to receive it.",
                "asks for your UPI PIN to receive money"
            ),
            Pair(
                "Your electricity connection will be cut tonight at 9:30 PM due to an unpaid bill. Call the officer now at 9876543210.",
                "power cut threat with a number to call"
            ),
            Pair(
                "Earn Rs 5,000 a day working from home! Like YouTube videos and get paid.",
                "paid online task or work-from-home job offer"
            ),
            Pair(
                "Hi Mom, I lost my phone and this is my new number. Please send Rs 15,000 urgently.",
                "new number asking for money"
            ),
            Pair(
                "Congratulations! You won Rs 25,00,000 in the KBC lucky draw. Pay Rs 9,999 processing fee to claim.",
                "prize that needs a fee"
            ),
            Pair(
                "Install this app to update your bank KYC.",
                "asks you to install an app file"
            )
        )
        for ((text, expectedIndicator) in positives) {
            assertEquals(text, expectedIndicator, scamScript(text))
            val ev = fuse(text, null, emptyList(), emptyList())
            assertEquals("high", ev.level)
            assertTrue(text, expectedIndicator in ev.indicators)
        }

        val negatives = listOf(
            "Never share your UPI PIN, it is not needed to receive money.",
            "Power shutdown for planned maintenance today 10 AM to 2 PM.",
            "IND vs SA T20 is live, Prize Pool 2,80,00,000, Entry Fee 49.",
            "Your Rs 2,000 payment to Ramesh was successful.",
            "Beware of fraud: do not install apps sent by unknown callers.",
            "Reached home, will call you later."
        )
        for (text in negatives) {
            assertNull(text, scamScript(text))
        }
    }

    @Test
    fun testPowerCutScriptConsumerNumberRegression() {
        val billReminder =
            "Dear Consumer 1002345678, your electricity bill is due today. Pay now to avoid power disconnection."
        val scam =
            "Your electricity will be disconnected tonight at 9.30 pm. Call 9876543210 immediately."
        assertNull(billReminder, scamScript(billReminder))
        assertEquals(scam, "power cut threat with a number to call", scamScript(scam))
    }
}
