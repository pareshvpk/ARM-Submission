package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File

class CuesTest {

    @Before
    fun loadRules() {
        val candidates = listOf(
            File("../../sentinel/data/rules.json"),
            File("../sentinel/data/rules.json"),
            File("sentinel/data/rules.json")
        )
        val file = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw IllegalStateException("rules.json not found for the unit test")
        Rules.activate(Rules.fromJson(file.readText(Charsets.UTF_8)))
    }

    @Test
    fun testSmsCuesOffsetsAndTypes() {
        val text = "URGENT: your SBI account is blocked today. Update now: otp needed or legal action will follow"
        val cues = smsCues(text)
        assertTrue("Expected cues to be found", cues.isNotEmpty())

        val typesFound = cues.map { it.type }.toSet()
        val expectedSubset = setOf("urgency", "impersonation", "credential_request", "threat")
        for (exp in expectedSubset) {
            assertTrue("Expected cue type '$exp' to be in $typesFound", exp in typesFound)
        }

        // Verify character offsets slice exact text
        for (c in cues) {
            val sliced = text.substring(c.start, c.end)
            assertEquals("Span slice must match cue text", c.text, sliced)
            assertEquals("Length must match end - start", c.end - c.start, c.text.length)
        }
    }

    @Test
    fun testSmsCuesAllTypes() {
        val text = "URGENT update now pay electricity board won lottery arrest"
        val cues = smsCues(text)
        val typesFound = cues.map { it.type }.toSet()

        val expectedAll = setOf(
            "urgency",
            "credential_request",
            "payment_request",
            "impersonation",
            "reward",
            "threat"
        )

        for (exp in expectedAll) {
            assertTrue("Expected cue type '$exp' to be found in $typesFound", exp in typesFound)
        }
    }

    @Test
    fun testHinglishThreats() {
        val threatPhrases = listOf(
            Pair("Aapka bijli connection aaj raat 9 baje kat jayega, turant officer ko call karein", listOf("urgency", "threat")),
            Pair("Line kaat diya jayega aaj", listOf("threat")),  // bare "aaj" is not a cue (Python reference: "aaj raat")
            Pair("Aapka account band ho jayega", listOf("threat")),
            Pair("SIM block ho jayega jaldi", listOf("threat", "urgency")),
            Pair("Connection band kar diya jayega", listOf("threat"))
        )

        for ((phrase, expectedTypes) in threatPhrases) {
            val cues = smsCues(phrase)
            val foundTypes = cues.map { it.type }.toSet()
            for (exp in expectedTypes) {
                assertTrue("Expected cue '$exp' in '$phrase', found $foundTypes", exp in foundTypes)
            }
        }
    }

    @Test
    fun testBlockedAndSuspendedAreThreatsNotUrgency() {
        for (phrase in listOf("Your account is blocked", "Your account is suspended")) {
            val types = smsCues(phrase).map { it.type }.toSet()
            assertTrue("Expected threat in '$phrase', found $types", "threat" in types)
            assertTrue("Did not expect urgency in '$phrase', found $types", "urgency" !in types)
        }
    }

    @Test
    fun testTimeBoundUrgencyPattern() {
        val cues = smsCues("Your number will be blocked in 2 hours")
        val timeBound = cues.any { it.type == "urgency" && it.text.equals("in 2 hours", ignoreCase = true) }
        assertTrue("Expected an urgency cue for 'in 2 hours', found $cues", timeBound)
    }

    @Test
    fun testUppercaseMessageYieldsSameCuesAsLowercase() {
        val lower = "Your number will be blocked in 2 hours"
        val upper = "YOUR NUMBER WILL BE BLOCKED IN 2 HOURS"
        assertEquals(
            "Uppercase message must yield the same cue types as lowercase",
            smsCues(lower).map { it.type },
            smsCues(upper).map { it.type }
        )
        assertEquals(
            "Uppercase message must yield the same cue positions as lowercase",
            smsCues(lower).map { it.start to it.end },
            smsCues(upper).map { it.start to it.end }
        )
    }

    @Test
    fun testApkIsAppInstallCue() {
        val types = smsCues("Download APK from the link").map { it.type }.toSet()
        assertTrue("Expected app_install cue, found $types", "app_install" in types)
    }
}
