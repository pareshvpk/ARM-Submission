package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
class MmsPendingTest {

    @Test
    fun testBoundedFiltersNegativeIds() {
        val input = mapOf(-1L to 1000L, -5L to 2000L, 10L to 3000L, 20L to 4000L)
        val result = MmsPending.bounded(input)
        assertEquals(2, result.size)
        assertFalse(result.containsKey(-1L))
        assertFalse(result.containsKey(-5L))
        assertTrue(result.containsKey(10L))
        assertTrue(result.containsKey(20L))
    }

    @Test
    fun testBoundedSortsByValueDescendingAndCaps() {
        val input = (1L..200L).associateWith { id -> id * 100L }
        val result = MmsPending.bounded(input)
        assertEquals(MmsPending.MAX_ENTRIES, result.size)
        // Highest timestamp (200L with 20000L) must be included
        assertTrue(result.containsKey(200L))
        // Lowest timestamp (1L with 100L) must have been dropped
        assertFalse(result.containsKey(1L))
    }

    @Test
    fun testDeferNewIdAddsWithCurrentTime() {
        val initial = emptyMap<Long, Long>()
        val now = 1_000_000L
        val updated = MmsPending.defer(initial, 42L, now)
        assertEquals(mapOf(42L to now), updated)
    }

    @Test
    fun testDeferExistingIdPreservesFirstSeen() {
        val firstSeen = 1_000_000L
        val initial = mapOf(42L to firstSeen)
        val now = 1_060_000L // 1 minute later
        val updated = MmsPending.defer(initial, 42L, now)
        assertEquals(firstSeen, updated[42L])
    }

    @Test
    fun testDeferExpiresAfterRetryWindow() {
        val firstSeen = 1_000_000L
        val initial = mapOf(42L to firstSeen)
        val now = firstSeen + MmsPending.RETRY_WINDOW_MS // exactly 10 min later
        val updated = MmsPending.defer(initial, 42L, now)
        assertFalse("Entry must be removed after retry window expires", updated.containsKey(42L))
    }

    @Test
    fun testDeferDropsOnClockRollback() {
        val firstSeen = 1_000_000L
        val initial = mapOf(42L to firstSeen)
        val now = firstSeen - 5000L // Clock shifted backwards
        val updated = MmsPending.defer(initial, 42L, now)
        assertFalse("Entry must be removed if clock rolled back", updated.containsKey(42L))
    }
}
