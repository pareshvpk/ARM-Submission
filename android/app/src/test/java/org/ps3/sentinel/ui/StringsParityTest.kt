package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Parity test for the Hindi and Tamil translations: same string names as the
 * English source (minus translatable=false), same format placeholders, no
 * empty values. Run from the module directory by the JVM test task.
 */
class StringsParityTest {

    private data class Entry(val name: String, val value: String, val translatable: Boolean)

    private val englishPath = "src/main/res/values/strings.xml"

    private val placeholder = Regex("%(?:\\d+\\x24)?[-#+0,(]*\\d*(?:\\.\\d+)?[a-zA-Z%]")

    private fun load(path: String): Map<String, Entry> {
        val file = File(path)
        assertTrue("Missing resource file: ${file.absolutePath}", file.isFile)
        val factory = DocumentBuilderFactory.newInstance()
        runCatching {
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
        }
        val doc = factory.newDocumentBuilder().parse(file)
        val nodes = doc.getElementsByTagName("string")
        val entries = LinkedHashMap<String, Entry>()
        for (index in 0 until nodes.length) {
            val element = nodes.item(index) as Element
            val name = element.getAttribute("name")
            val translatable = !element.getAttribute("translatable").equals("false", ignoreCase = true)
            entries[name] = Entry(name, element.textContent ?: "", translatable)
        }
        return entries
    }

    private fun placeholders(value: String): List<String> =
        placeholder.findAll(value)
            .map { it.value }
            .filter { it != "%%" }
            .sorted()
            .toList()

    private fun assertLocaleMatchesEnglish(localPath: String) {
        val english = load(englishPath)
        val local = load(localPath)

        val expectedNames = english.values.filter { it.translatable }.map { it.name }.toSet()
        assertEquals("String names in $localPath do not match the English source", expectedNames, local.keys)

        for ((name, entry) in local) {
            val source = english[name] ?: continue
            assertFalse("Value of $name in $localPath is empty", entry.value.isEmpty())
            assertEquals(
                "Format placeholders differ for $name in $localPath",
                placeholders(source.value),
                placeholders(entry.value)
            )
        }
    }

    @Test
    fun hindiMatchesEnglish() {
        assertLocaleMatchesEnglish("src/main/res/values-hi/strings.xml")
    }

    @Test
    fun tamilMatchesEnglish() {
        assertLocaleMatchesEnglish("src/main/res/values-ta/strings.xml")
    }
}
