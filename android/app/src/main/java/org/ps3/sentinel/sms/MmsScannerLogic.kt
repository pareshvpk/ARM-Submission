/**
 * Pure helper functions for MMS scanning logic: pending map parse/serialize and text trimming.
 * Extracted with no Android imports so they can be unit-tested on the JVM.
 *
 * Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
 */
// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
package org.ps3.sentinel.sms

internal const val MAX_MMS_TEXT_LENGTH = 2000

internal fun parsePending(serialized: Set<String>?): Map<Long, Long> {
    return serialized.orEmpty().mapNotNull { value ->
        val pair = value.split(':', limit = 2)
        val id = pair.getOrNull(0)?.toLongOrNull()
        val time = pair.getOrNull(1)?.toLongOrNull()
        if (id != null && time != null) id to time else null
    }.toMap()
}

internal fun serializePending(pending: Map<Long, Long>): Set<String> {
    return pending.map { "${it.key}:${it.value}" }.toSet()
}

internal fun trimText(text: String, maxChars: Int = MAX_MMS_TEXT_LENGTH): String {
    return if (text.length > maxChars) text.substring(0, maxChars) else text
}
