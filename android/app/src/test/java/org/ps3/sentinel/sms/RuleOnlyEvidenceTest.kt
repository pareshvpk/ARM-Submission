package org.ps3.sentinel.sms

import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.core.TrustedDomainStore
import java.io.File

class RuleOnlyEvidenceTest {
    @Before
    fun setUp() {
        TrustedDomainStore.loadFromFile(findRepoFile("sentinel/data/trusted_domains.txt"))
        Rules.activate(Rules.fromJson(findRepoFile("sentinel/data/rules.json").readText(Charsets.UTF_8)))
    }

    @Test
    fun testRuleOnlyUpiCollectPinIsHighOrMediumWithNoPipeline() {
        val text = "You have received a UPI collect request of INR 10,000. Approve by entering your UPI PIN."
        val evidence = SmsReceiver.ruleOnlyEvidence(null, text)
        assertTrue(
            "expected high or medium, got ${evidence.level} risk ${evidence.risk}",
            evidence.level == "high" || evidence.level == "medium"
        )
    }

    @Test
    fun testRuleOnlyApkLoanIsHighOrMediumWithNoPipeline() {
        val text = "Loan approved. Download APK from loan-instant.xyz"
        val evidence = SmsReceiver.ruleOnlyEvidence(null, text)
        assertTrue(
            "expected high or medium, got ${evidence.level} risk ${evidence.risk}",
            evidence.level == "high" || evidence.level == "medium"
        )
    }

    @Test
    fun testRuleOnlyHinglishElectricityIsHighOrMediumWithNoPipeline() {
        val text = "Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko 9876543210 call karein"
        val evidence = SmsReceiver.ruleOnlyEvidence(null, text)
        assertTrue(
            "expected high or medium, got ${evidence.level} risk ${evidence.risk}",
            evidence.level == "high" || evidence.level == "medium"
        )
    }

    @Test
    fun testRuleOnlyEvidenceIncludesCuesWithNoPipeline() {
        val text = "You have received a UPI collect request of INR 10,000. Approve by entering your UPI PIN."
        val evidence = SmsReceiver.ruleOnlyEvidence(null, text)
        assertTrue("rule-only evidence must include cues", evidence.cues.isNotEmpty())
        assertTrue("rule-only evidence cueSpans must not be empty", evidence.cueSpans.isNotEmpty())
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
