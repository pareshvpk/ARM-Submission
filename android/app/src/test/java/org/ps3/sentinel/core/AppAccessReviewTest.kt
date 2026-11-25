package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AppAccessReviewTest {

    @Test
    fun testRiskOrderPrioritisesScreenAndSms() {
        val highRisk = AppAccessEntry(
            packageName = "com.suspicious.app",
            label = "Suspicious App",
            canReadScreen = true,
            canPerformGestures = false,
            canReadSms = true,
            isSystem = false
        )
        val mediumRiskScreen = AppAccessEntry(
            packageName = "com.screen.app",
            label = "Screen App",
            canReadScreen = true,
            canPerformGestures = false,
            canReadSms = false,
            isSystem = false
        )
        val mediumRiskGestures = AppAccessEntry(
            packageName = "com.gesture.app",
            label = "Gesture App",
            canReadScreen = false,
            canPerformGestures = true,
            canReadSms = false,
            isSystem = false
        )
        val lowRisk = AppAccessEntry(
            packageName = "com.basic.app",
            label = "Basic App",
            canReadScreen = false,
            canPerformGestures = false,
            canReadSms = false,
            isSystem = false
        )

        assertTrue(riskOrder(highRisk) > riskOrder(mediumRiskScreen))
        assertTrue(riskOrder(highRisk) > riskOrder(mediumRiskGestures))
        assertTrue(riskOrder(mediumRiskScreen) > riskOrder(lowRisk))
        assertTrue(riskOrder(mediumRiskGestures) > riskOrder(lowRisk))
    }

    @Test
    fun testRiskOrderPutsSystemAppsLast() {
        val regularLow = AppAccessEntry(
            packageName = "com.user.app",
            label = "User App",
            canReadScreen = false,
            canPerformGestures = false,
            canReadSms = false,
            isSystem = false
        )
        val systemHigh = AppAccessEntry(
            packageName = "com.android.talkback",
            label = "TalkBack",
            canReadScreen = true,
            canPerformGestures = true,
            canReadSms = true,
            isSystem = true
        )
        val systemLow = AppAccessEntry(
            packageName = "com.android.system",
            label = "System Tool",
            canReadScreen = false,
            canPerformGestures = false,
            canReadSms = false,
            isSystem = true
        )

        assertTrue(riskOrder(regularLow) > riskOrder(systemHigh))
        assertTrue(riskOrder(systemHigh) > riskOrder(systemLow))
    }

    @Test
    fun testSortEntriesOrdersCorrectly() {
        val entry1 = AppAccessEntry("com.sys.app", "TalkBack", canReadScreen = true, canPerformGestures = true, canReadSms = true, isSystem = true)
        val entry2 = AppAccessEntry("com.scam.sms", "QuickCleaner", canReadScreen = true, canPerformGestures = true, canReadSms = true, isSystem = false)
        val entry3 = AppAccessEntry("com.tool.tap", "AutoClicker", canReadScreen = false, canPerformGestures = true, canReadSms = false, isSystem = false)
        val entry4 = AppAccessEntry("com.tool.screen", "ScreenReader", canReadScreen = true, canPerformGestures = false, canReadSms = false, isSystem = false)
        val entry5 = AppAccessEntry("com.simple.app", "Notes", canReadScreen = false, canPerformGestures = false, canReadSms = false, isSystem = false)

        val sorted = sortEntries(listOf(entry1, entry5, entry3, entry4, entry2))

        assertEquals(entry2.packageName, sorted[0].packageName)
        assertEquals(entry3.packageName, sorted[1].packageName)
        assertEquals(entry4.packageName, sorted[2].packageName)
        assertEquals(entry5.packageName, sorted[3].packageName)
        assertEquals(entry1.packageName, sorted[4].packageName)
    }

    @Test
    fun testSortEntriesEmptyAndSingle() {
        assertTrue(sortEntries(emptyList()).isEmpty())
        val single = listOf(AppAccessEntry("a.b.c", "App", false, false, null, false))
        assertEquals(single, sortEntries(single))
    }
}
