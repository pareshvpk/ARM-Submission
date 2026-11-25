package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
class MmsRowsTest {

    @Test
    fun testConsumeMmsRowsInOrder() {
        val ids = mutableListOf(101L, 102L, 103L)
        val processed = mutableListOf<Long>()
        val checkpointed = mutableListOf<Long>()

        consumeMmsRows(
            nextId = { if (ids.isNotEmpty()) ids.removeAt(0) else null },
            active = { true },
            process = { processed.add(it) },
            checkpoint = { checkpointed.add(it) }
        )

        assertEquals(listOf(101L, 102L, 103L), processed)
        assertEquals(listOf(101L, 102L, 103L), checkpointed)
    }

    @Test
    fun testConsumeMmsRowsStopsWhenInactive() {
        val ids = mutableListOf(1L, 2L, 3L, 4L)
        val processed = mutableListOf<Long>()
        val checkpointed = mutableListOf<Long>()
        var activeState = true

        consumeMmsRows(
            nextId = { if (ids.isNotEmpty()) ids.removeAt(0) else null },
            active = { activeState },
            process = { id ->
                processed.add(id)
                if (id == 2L) {
                    activeState = false
                }
            },
            checkpoint = { checkpointed.add(it) }
        )

        assertEquals(listOf(1L, 2L), processed)
        // 2L became inactive after process, so checkpoint(2L) should not be reached
        assertEquals(listOf(1L), checkpointed)
    }
}
