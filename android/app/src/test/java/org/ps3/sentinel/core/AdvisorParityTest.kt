package org.ps3.sentinel.core

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Replays the Python-generated advisor fixture through the Kotlin guard and
 * template advice and requires identical text and flags. This is the guard
 * that stops the two shipped implementations from drifting apart.
 */
class AdvisorParityTest {

    @Test
    fun testKotlinMatchesPythonAdvisorCases() {
        val fixtureFile = findRepoFile("tests/fixtures/advisor_cases.json")
        val fixture = JSONObject(fixtureFile.readText(Charsets.UTF_8))
        val cases = fixture.getJSONArray("cases")
        assertTrue("Expected at least 30 advisor cases", cases.length() >= 30)

        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val name = case.getString("name")
            val evidenceJson = case.getJSONObject("evidence")
            val evidence = Evidence(
                label = evidenceJson.getString("label"),
                risk = evidenceJson.getDouble("risk"),
                level = evidenceJson.getString("level")
            )
            val expected = case.getJSONObject("expected")

            val (guarded, flags) = guard(case.getString("raw_output"), evidence)
            assertEquals(
                "guarded text for case $name",
                expected.getString("guarded_text"),
                guarded
            )
            assertEquals(
                "guard flags for case $name",
                readStringList(expected.getJSONArray("flags")),
                flags
            )
            assertEquals(
                "template text for case $name",
                expected.getString("template_text"),
                templateAdvice(evidence)
            )
        }
    }

    @Test
    fun testKotlinMatchesPythonAdvisorTemplates() {
        val fixtureFile = findRepoFile("tests/fixtures/advisor_cases.json")
        val fixture = JSONObject(fixtureFile.readText(Charsets.UTF_8))
        val templates = fixture.getJSONObject("templates")

        for (key in templates.keys()) {
            val parts = key.split("|")
            val evidence = Evidence(
                label = parts[0],
                risk = 0.5,
                level = parts[1]
            )
            assertEquals("template text for $key", templates.getString(key), templateAdvice(evidence))
        }
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
