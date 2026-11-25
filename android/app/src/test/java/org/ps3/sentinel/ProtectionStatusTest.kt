package org.ps3.sentinel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.core.ProtectionStatus

class ProtectionStatusTest {

    @Test
    fun testAllOn() {
        val allOnStatus = ProtectionStatus(
            sms = true,
            mms = true,
            notifications = true,
            screenCheck = true
        )
        assertTrue(allOnStatus.allOn())
        assertTrue(allOnStatus.offItems().isEmpty())

        // screenCheck is optional: core all on with it off still counts as all on.
        val coreOnly = ProtectionStatus(
            sms = true,
            mms = true,
            notifications = true,
            screenCheck = false
        )
        assertTrue(coreOnly.allOn())
        assertTrue(coreOnly.offItems().isEmpty())

        assertFalse(ProtectionStatus(sms = false, mms = true, notifications = true, screenCheck = true).allOn())
        assertFalse(ProtectionStatus(sms = true, mms = false, notifications = true, screenCheck = true).allOn())
        assertFalse(ProtectionStatus(sms = true, mms = true, notifications = false, screenCheck = true).allOn())
        assertFalse(ProtectionStatus(sms = true, mms = true, notifications = false, screenCheck = false).allOn())
        assertFalse(ProtectionStatus(sms = false, mms = false, notifications = false, screenCheck = false).allOn())
    }

    @Test
    fun testOffItemsOrder() {
        // When all core items are off, keys must follow evaluation order: sms, mms, notifications
        val allOff = ProtectionStatus(
            sms = false,
            mms = false,
            notifications = false,
            screenCheck = false
        )
        val expectedAllOff = listOf(
            ProtectionStatus.ITEM_SMS,
            ProtectionStatus.ITEM_MMS,
            ProtectionStatus.ITEM_NOTIFICATIONS
        )
        assertEquals(expectedAllOff, allOff.offItems())

        // Single core item off
        val onlySmsOff = ProtectionStatus(sms = false, mms = true, notifications = true, screenCheck = true)
        assertEquals(listOf(ProtectionStatus.ITEM_SMS), onlySmsOff.offItems())

        val onlyMmsOff = ProtectionStatus(sms = true, mms = false, notifications = true, screenCheck = true)
        assertEquals(listOf(ProtectionStatus.ITEM_MMS), onlyMmsOff.offItems())

        val onlyNotifOff = ProtectionStatus(sms = true, mms = true, notifications = false, screenCheck = true)
        assertEquals(listOf(ProtectionStatus.ITEM_NOTIFICATIONS), onlyNotifOff.offItems())

        // Optional screen check off never appears as an off item.
        val onlyScreenOff = ProtectionStatus(sms = true, mms = true, notifications = true, screenCheck = false)
        assertEquals(emptyList<String>(), onlyScreenOff.offItems())

        // Subsets preserving order
        val smsAndScreenOff = ProtectionStatus(sms = false, mms = true, notifications = true, screenCheck = false)
        assertEquals(listOf(ProtectionStatus.ITEM_SMS), smsAndScreenOff.offItems())

        val mmsAndNotifOff = ProtectionStatus(sms = true, mms = false, notifications = false, screenCheck = true)
        assertEquals(
            listOf(ProtectionStatus.ITEM_MMS, ProtectionStatus.ITEM_NOTIFICATIONS),
            mmsAndNotifOff.offItems()
        )

        val noneOff = ProtectionStatus(sms = true, mms = true, notifications = true, screenCheck = true)
        assertEquals(emptyList<String>(), noneOff.offItems())
    }
}
