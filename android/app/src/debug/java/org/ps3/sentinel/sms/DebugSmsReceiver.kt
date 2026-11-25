package org.ps3.sentinel.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import org.json.JSONObject
import org.ps3.sentinel.SentinelApp
import java.io.File

/**
 * Debug builds only. A real SMS_RECEIVED broadcast cannot be sent from adb, and a registered
 * (DLT header) sender cannot be produced on demand. Only a caller holding DUMP (adb shell) can send here.
 *
 * Extras "sender" + "body": runs the same code path as a real incoming SMS (stores, notifies).
 * Extra "file": name of a JSON-lines file (id, text, optional sender) in the app's external files
 *   folder. Each line gets a dry-run verdict (models, fusion, alert policy) logged as
 *   debug_verdict; nothing is stored and no notification is posted. Keep the app open while it runs.
 */
class DebugSmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val file = intent.getStringExtra("file")
        if (file != null) {
            val app = context.applicationContext as SentinelApp
            Thread { runBatch(app, File(app.getExternalFilesDir(null), File(file).name)) }.start()
            return
        }
        val sender = intent.getStringExtra("sender") ?: return
        val body = intent.getStringExtra("body") ?: return
        SmsReceiver().handleMessages(context, mapOf(sender to body), goAsync()::finish)
    }

    private fun runBatch(app: SentinelApp, file: File) {
        val pipeline = app.pipeline
        if (pipeline == null || !pipeline.isSmsModelLoaded()) {
            Log.w(TAG, "debug_batch_error models_not_loaded")
            return
        }
        var count = 0
        try {
            file.forEachLine(Charsets.UTF_8) { line ->
                if (line.isBlank()) return@forEachLine
                val row = JSONObject(line)
                val sender = if (row.has("sender")) row.getString("sender") else null
                val evidence = pipeline.analyseFast(row.getString("text"), sender)
                Log.i(TAG, "debug_verdict id=${row.getString("id")} level=${evidence.level} " +
                    "sms_label=${evidence.smsLabel} risk=${evidence.risk} alert=${AlertPolicy.isThreat(evidence)}")
                count++
            }
            Log.i(TAG, "debug_batch_done count=$count")
        } catch (e: Throwable) {
            Log.w(TAG, "debug_batch_error after=$count ${e::class.simpleName}: ${e.message}")
        }
    }

    private companion object {
        const val TAG = "PS3Debug"
    }
}
