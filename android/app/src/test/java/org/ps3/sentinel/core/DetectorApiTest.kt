package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class DetectorApiTest {

    @Before
    fun setUp() {
        val rulesCandidates = listOf(
            File("../../sentinel/data/rules.json"),
            File("../sentinel/data/rules.json"),
            File("sentinel/data/rules.json")
        )
        val rulesFile = rulesCandidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("rules.json not found for the unit test")
        Rules.activate(Rules.fromJson(rulesFile.readText(Charsets.UTF_8)))
    }

    private class FixedDetector(
        override val name: String,
        override val version: String,
        private val risk: Double
    ) : Detector {
        override fun score(text: String): DetectorPart =
            DetectorPart(name, version, risk, listOf("flow_alert"))
    }

    private class ThrowingDetector : Detector {
        override val name: String = "boom"
        override val version: String = "0.0"

        override fun score(text: String): DetectorPart = throw IllegalStateException("boom")
    }

    @Test
    fun testExtraDetectorRaisesLevelAndAppearsInEvidence() {
        val text = "Hello friend, how are you?"
        val parts = runExtraDetectors(text, listOf(FixedDetector("phase2_network", "0.1", 0.9)))
        val evidence = fuse(text, null, emptyList(), emptyList(), extraParts = parts)

        assertEquals("high", evidence.level)
        assertEquals(0.9, evidence.risk, 1e-9)
        assertEquals(1, evidence.extraDetectors.size)
        assertEquals("phase2_network", evidence.extraDetectors[0].name)
    }

    @Test
    fun testThrowingDetectorYieldsNoPart() {
        val parts = runExtraDetectors("hello", listOf(ThrowingDetector()))

        assertTrue(parts.isEmpty())
    }

    @Test
    fun testEmptyExtraPartsKeepsEvidenceIdentical() {
        val text = "URGENT: your SBI account is blocked today. Update now: otp needed"
        val plain = fuse(text, null, emptyList(), emptyList())
        val withEmpty = fuse(text, null, emptyList(), emptyList(), extraParts = emptyList())

        assertEquals(plain, withEmpty)
        assertTrue(withEmpty.extraDetectors.isEmpty())
    }

    @Test
    fun testExtraDetectorRiskIsClamped() {
        val parts = runExtraDetectors(
            "hello",
            listOf(
                FixedDetector("high", "1", 1.7),
                FixedDetector("low", "1", -0.4)
            )
        )

        assertEquals(1.0, parts[0].risk, 1e-9)
        assertEquals(0.0, parts[1].risk, 1e-9)

        val clampedParts = runExtraDetectors("hello", listOf(FixedDetector("high", "1", 8.0)))
        val evidence = fuse("hello", null, emptyList(), emptyList(), extraParts = clampedParts)
        assertEquals(1.0, evidence.risk, 1e-9)
        assertEquals("high", evidence.level)
    }

    @Test
    fun testClampRiskNonFiniteIsZero() {
        assertEquals(0.0, clampRisk(Double.NaN), 1e-9)
        assertEquals(0.0, clampRisk(Double.POSITIVE_INFINITY), 1e-9)
        assertEquals(0.0, clampRisk(Double.NEGATIVE_INFINITY), 1e-9)
    }
}
