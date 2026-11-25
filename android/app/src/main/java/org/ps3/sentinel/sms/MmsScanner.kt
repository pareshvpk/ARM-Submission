/**
 * Scans content://mms for newly arrived MMS rows above the stored watermark.
 * Hands non-blank message text to SmsReceiver.handleMessages.
 *
 * Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
 */
// Adapted from pareshvpk/Phase (MIT), see .ref licence; this repo is Apache-2.0.
package org.ps3.sentinel.sms

import android.content.Context
import android.net.Uri
import android.os.CancellationSignal
import android.util.Log

object MmsScanner {
    private const val TAG = "PS3Mms"
    private const val PREFS = "ps3_mms_scanner"
    private const val LAST_ID = "last_mms_id"
    private const val PENDING = "pending_mms_ids"
    const val MAX_MMS_TEXT_LENGTH = 2000
    private val inbox by lazy { Uri.parse("content://mms") }

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun reset(context: Context) {
        prefs(context).edit().remove(LAST_ID).remove(PENDING).apply()
    }

    // Called at registration, before waiting for the first provider change.
    fun initialize(context: Context, commitIfCurrent: (() -> Unit) -> Boolean): Boolean {
        if (prefs(context).contains(LAST_ID)) return commitIfCurrent {}
        val maximum = requireNotNull(context.contentResolver.query(
            inbox, arrayOf("_id"), null, null, "_id DESC"
        )).use { if (it.moveToFirst()) it.getLong(0) else 0L }
        return commitIfCurrent {
            if (!prefs(context).contains(LAST_ID)) {
                prefs(context).edit().putLong(LAST_ID, maximum).apply()
            }
        }
    }

    fun parsePending(serialized: Set<String>?): Map<Long, Long> =
        org.ps3.sentinel.sms.parsePending(serialized)

    fun serializePending(pending: Map<Long, Long>): Set<String> =
        org.ps3.sentinel.sms.serializePending(pending)

    fun trimText(text: String, maxChars: Int = MAX_MMS_TEXT_LENGTH): String =
        org.ps3.sentinel.sms.trimText(text, maxChars)

    fun scanNew(context: Context, signal: CancellationSignal): Boolean {
        val prefs = prefs(context)
        val previous = prefs.getLong(LAST_ID, -1L)
        if (previous < 0) return false
        var pending = MmsPending.bounded(parsePending(prefs.getStringSet(PENDING, emptySet())))
        val missing = pending.keys.toMutableSet()
        val pendingClause = if (pending.isEmpty()) "" else
            " OR _id IN (${pending.keys.joinToString(",") { "?" }})"
        val selectionArgs = arrayOf(previous.toString(), *pending.keys.map { it.toString() }.toTypedArray())
        requireNotNull(context.contentResolver.query(
            inbox, arrayOf("_id"), "(_id > ?$pendingClause) AND msg_box = 1 AND m_type = 132",
            selectionArgs, "_id ASC", signal
        )).use { cursor ->
            val active = { !signal.isCanceled && MmsWatcher.allowed(context) }
            consumeMmsRows(
                nextId = { if (cursor.moveToNext()) cursor.getLong(0) else null },
                active = active,
                process = { id ->
                    missing.remove(id)
                    val text = readText(context, id, signal)
                    // The parent row can arrive before its text parts. Retain only
                    // its ID for bounded retries; later messages can still proceed.
                    pending = if (text.isBlank()) {
                        MmsPending.defer(pending, id, System.currentTimeMillis())
                    } else pending - id
                    // A capped prefix may omit a sensitive suffix. Skip the entire message.
                    if (text.length < MmsText.MAX_CHARS && text.isNotBlank()) {
                        val sender = readSender(context, id, signal)
                        if (active()) {
                            val trimmedText = trimText(text)
                            SmsReceiver().handleMessages(context, mapOf(sender to trimmedText)) {}
                        }
                    }
                },
                checkpoint = { id ->
                    MmsWatcher.checkpoint(context, signal) {
                        prefs.edit().putLong(LAST_ID, maxOf(previous, id))
                            .putStringSet(PENDING, serializePending(pending)).apply()
                    }
                }
            )
        }
        // A completed query omitting a pending ID means it was deleted or moved.
        pending = pending - missing
        MmsWatcher.checkpoint(context, signal) {
            prefs.edit().putStringSet(PENDING, serializePending(pending)).apply()
        }
        return pending.isNotEmpty()
    }

    private fun readText(context: Context, id: Long, signal: CancellationSignal): String {
        val text = StringBuilder()
        requireNotNull(context.contentResolver.query(
            Uri.parse("content://mms/part"), arrayOf("_id", "_data", "text"),
            "mid = ? AND ct = ?", arrayOf(id.toString(), "text/plain"), "seq ASC, _id ASC", signal
        )).use { cursor ->
            while (text.length < MmsText.MAX_CHARS && cursor.moveToNext()) {
                signal.throwIfCanceled()
                if (cursor.isNull(1)) {
                    cursor.getString(2)?.let { MmsText.append(text, it) }
                } else {
                    val uri = Uri.parse("content://mms/part/${cursor.getLong(0)}")
                    requireNotNull(context.contentResolver.openAssetFileDescriptor(uri, "r", signal)).use { asset ->
                        asset.createInputStream().reader(Charsets.UTF_8).use { reader ->
                            MmsText.append(text, reader, signal::throwIfCanceled)
                        }
                    }
                }
            }
        }
        return text.toString()
    }

    private fun readSender(context: Context, id: Long, signal: CancellationSignal): String {
        requireNotNull(context.contentResolver.query(
            Uri.parse("content://mms/$id/addr"), arrayOf("address"), "type = 137", null, null, signal
        )).use { cursor ->
            while (cursor.moveToNext()) {
                val address = cursor.getString(0)
                if (!address.isNullOrBlank() && address != "insert-address-token") return address
            }
        }
        return ""
    }
}
