package org.ps3.sentinel.a11y

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenCheckLogicTest {

    @Test
    fun testOwnPackageSkip() {
        val items = listOf(
            ScreenNodeItem("org.ps3.sentinel", "Sentinel UI text"),
            ScreenNodeItem("com.whatsapp", "Suspicious message from unknown sender"),
            ScreenNodeItem("org.ps3.sentinel", "Another Sentinel button")
        )
        val result = collectCleanScreenText(items, ownPackage = "org.ps3.sentinel")
        assertEquals("Suspicious message from unknown sender", result)
    }

    @Test
    fun testPasswordSkip() {
        val items = listOf(
            ScreenNodeItem("com.banking.app", "Enter PIN:"),
            ScreenNodeItem("com.banking.app", "123456", isPassword = true),
            ScreenNodeItem("com.banking.app", "Submit")
        )
        val result = collectCleanScreenText(items)
        assertEquals("Enter PIN:\nSubmit", result)
    }

    @Test
    fun testWhitespaceCollapse() {
        val items = listOf(
            ScreenNodeItem("com.example", "   Hello    world   with \t tabs   "),
            ScreenNodeItem("com.example", "Line 1   with   spaces\n\n\nLine 2   with   spaces")
        )
        val result = collectCleanScreenText(items)
        assertEquals("Hello world with tabs\nLine 1 with spaces\nLine 2 with spaces", result)
    }

    @Test
    fun test2000CharCut() {
        val longChunk = "a".repeat(1500)
        val secondChunk = "b".repeat(1000)
        val items = listOf(
            ScreenNodeItem("com.example", longChunk),
            ScreenNodeItem("com.example", secondChunk)
        )
        val result = collectCleanScreenText(items)
        assertEquals(2000, result.length)
        assertTrue(result.startsWith(longChunk + "\n" + "b".repeat(499)))
    }

    @Test
    fun testBlankResult() {
        val emptyList = emptyList<ScreenNodeItem>()
        assertEquals("", collectCleanScreenText(emptyList))

        val onlyOwnPackage = listOf(
            ScreenNodeItem("org.ps3.sentinel", "Internal text")
        )
        assertEquals("", collectCleanScreenText(onlyOwnPackage, ownPackage = "org.ps3.sentinel"))

        val onlyPasswords = listOf(
            ScreenNodeItem("com.example", "password123", isPassword = true)
        )
        assertEquals("", collectCleanScreenText(onlyPasswords))

        val onlyWhitespace = listOf(
            ScreenNodeItem("com.example", "   \t  \n  \n  ")
        )
        assertEquals("", collectCleanScreenText(onlyWhitespace))
    }
}
