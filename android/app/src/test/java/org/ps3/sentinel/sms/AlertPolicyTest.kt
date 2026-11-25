package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.core.SmsResult
import org.ps3.sentinel.core.TrustedDomainStore
import org.ps3.sentinel.core.fuse
import org.ps3.sentinel.core.smsCues
import java.io.File
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.pow

class AlertPolicyTest {
    @Before
    fun setUp() {
        TrustedDomainStore.loadFromFile(findRepoFile("sentinel/data/trusted_domains.txt"))
        Rules.activate(Rules.fromJson(findRepoFile("sentinel/data/rules.json").readText(Charsets.UTF_8)))
    }

    @Test
    fun testAlertDecisionHighAlertsAndQuietMediumDoesNot() {
        assertTrue(AlertPolicy.isThreatLevel("high"))
        assertTrue(AlertPolicy.isThreatLevel("medium"))
        assertFalse(AlertPolicy.isThreatLevel("low"))
        assertTrue(AlertPolicy.shouldPostAlert(evidence("high")))
        assertFalse(AlertPolicy.shouldPostAlert(evidence("medium")))
        assertFalse(AlertPolicy.shouldPostAlert(evidence("low")))
    }

    @Test
    fun testChooseEvidenceWithAndWithoutSmsModel() {
        val rule = evidence("high")
        val full = evidence("low")
        assertSame(rule, AlertPolicy.chooseEvidence(false, rule, full))
        assertSame(full, AlertPolicy.chooseEvidence(true, rule, full))
        assertTrue(AlertPolicy.shouldPostAlert(false, rule, full))
        assertFalse(AlertPolicy.shouldPostAlert(true, rule, full))
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

    @Test
    fun testSmsModelChangesAlertDecision() {
        val text = "Your parcel will be delivered today. Pay on delivery."
        val cues = smsCues(text)
        val ham = SmsResult(rawProbsForScaled(0.9, 0.05, 0.05), "ham")
        val withSms = fuse(text, ham, emptyList(), cues)
        val withoutSms = fuse(text, null, emptyList(), cues)
        assertSame(withSms, AlertPolicy.chooseEvidence(true, withoutSms, withSms))
        assertFalse(AlertPolicy.shouldStorePending(withSms))
        assertTrue(AlertPolicy.shouldStorePending(withoutSms))
    }

    @Test
    fun testNoStoreWriteForLowRisk() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val low = evidence("low")
        if (AlertPolicy.shouldStorePending(low)) {
            store.put("msg-low", "body")
        } else {
            store.delete("msg-low")
        }
        assertEquals(0, store.size())
        val high = evidence("high")
        if (AlertPolicy.shouldStorePending(high)) {
            store.put("msg-high", "scam body")
        }
        assertEquals(1, store.size())
        store.delete("msg-high")
        assertEquals(0, store.size())
    }

    @Test
    fun testSmsWaitTimeoutIsThreeSeconds() {
        assertEquals(3000L, AlertPolicy.SMS_MODEL_WAIT_TIMEOUT_MS)
    }

    private fun evidence(level: String): Evidence = Evidence(label = "ham", risk = 0.0, level = level)

    private fun tempDir(): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "alertpolicy-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    private class FakeCipher(private val counter: AtomicLong = AtomicLong(0)) : PendingCipher {
        override fun encrypt(plaintext: ByteArray): EncryptedBody {
            val iv = ByteArray(12) { counter.incrementAndGet().toByte() }
            return EncryptedBody(ciphertext = plaintext.reversedArray() + ByteArray(8) { 0x55 }, iv = iv)
        }

        override fun decrypt(body: EncryptedBody): ByteArray {
            return body.ciphertext.dropLast(8).toByteArray().reversedArray()
        }
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
