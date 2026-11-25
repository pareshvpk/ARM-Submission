package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
class MmsWatcherTest {

    @Test
    fun testIsAllowedLogic() {
        // True only when RECEIVE_SMS, RECEIVE_MMS and READ_SMS are all granted
        assertTrue(MmsWatcher.isAllowed(receiveSms = true, receiveMms = true, readSms = true))

        assertFalse(MmsWatcher.isAllowed(receiveSms = false, receiveMms = true, readSms = true))
        assertFalse(MmsWatcher.isAllowed(receiveSms = true, receiveMms = false, readSms = true))
        assertFalse(MmsWatcher.isAllowed(receiveSms = true, receiveMms = true, readSms = false))
        assertFalse(MmsWatcher.isAllowed(receiveSms = false, receiveMms = false, readSms = false))
    }

    @Test
    fun testJobIdsAreDistinct() {
        assertEquals(4711, MmsWatcher.JOB_ID)
        assertEquals(4712, MmsWatcher.SCAN_JOB_ID)
        assertNotEquals(MmsWatcher.JOB_ID, MmsWatcher.SCAN_JOB_ID)
    }
}
