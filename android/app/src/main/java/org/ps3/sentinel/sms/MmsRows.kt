/**
 * Provider cursor iterator processing rows in ascending ID order with checkpoints.
 *
 * Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
 */
// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
package org.ps3.sentinel.sms

/** Process provider rows in ID order. A failed or interrupted row remains eligible for retry. */
internal fun consumeMmsRows(
    nextId: () -> Long?,
    active: () -> Boolean,
    process: (Long) -> Unit,
    checkpoint: (Long) -> Unit
) {
    while (active()) {
        val id = nextId() ?: return
        process(id)
        if (!active()) return
        checkpoint(id)
    }
}
