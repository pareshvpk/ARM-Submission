/**
 * BroadcastReceiver handling incoming SMS notifications and scam analysis.
 * Extracts message parts, runs fast rule-only or SMS model detection, and posts threat notifications.
 * Schedules background retries for deferred full model analysis when models are still loading.
 */
package org.ps3.sentinel.sms

import android.Manifest
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.provider.Telephony
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.ps3.sentinel.Pipeline
import org.ps3.sentinel.R
import org.ps3.sentinel.SentinelApp
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.UrlResult
import org.ps3.sentinel.core.extractUrls
import org.ps3.sentinel.core.fuse
import org.ps3.sentinel.core.isPlainPromotion
import org.ps3.sentinel.core.normaliseUrl
import org.ps3.sentinel.core.senderCue
import org.ps3.sentinel.core.shouldSkip
import org.ps3.sentinel.core.skipKind
import org.ps3.sentinel.core.smsCues
import org.ps3.sentinel.core.urlIndicators
import org.ps3.sentinel.ml.CpuFeatures
import org.ps3.sentinel.ml.ExecutorchGate
import org.ps3.sentinel.ml.sha256Short
import org.ps3.sentinel.ui.MainActivity
import java.util.Collections
import java.util.LinkedHashMap
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * BroadcastReceiver triggered on incoming SMS messages.
 *
 * Coordinates asynchronous execution via goAsync, stores alerted message bodies,
 * posts threat notifications, and manages deferred retries when models are loading.
 */
class SmsReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "PS3Sms"
        private const val TIMING_TAG = "PS3Timing"
        private const val UNKNOWN_SENDER = "Unknown"
        // Fallbacks used only when no Application context exists (JVM unit tests);
        // the app's own paths read the same text from res/values/strings.xml.
        private const val NOTIFICATION_TITLE_FALLBACK = "Possible scam message"
        private const val NOTIFICATION_PROMOTION_TITLE_FALLBACK = "Promotion message"
        private const val NOTIFICATION_PROTECTION_UNAVAILABLE_TITLE_FALLBACK = "Protection unavailable"
        private const val NOTIFICATION_VERDICT_FORMAT_FALLBACK = "Risk: %s"
        private const val NOTIFICATION_PROMOTION_TEXT_FALLBACK = "Promotion: no action needed. Tap to inspect."
        private const val NOTIFICATION_PROTECTION_UNAVAILABLE_TEXT_FALLBACK = "Sentinel rules could not be loaded. Tap to open app."
        // 50 ms — poll cadence for awaitPipelineReady: same cadence as Pipeline.awaitSmsReady.
        private const val PIPELINE_POLL_INTERVAL_MS: Long = 50L
        // 0.85 — indicator-only URL high prob: brand lookalike, risky TLD, or IP host.
        private const val URL_INDICATOR_HIGH_PROB: Double = 0.85
        // 0.40 — indicator-only URL medium prob: any other indicator present.
        private const val URL_INDICATOR_MEDIUM_PROB: Double = 0.4
        // 0.05 — indicator-only URL low prob: no indicator present.
        private const val URL_INDICATOR_LOW_PROB: Double = 0.05
        // 1 — lowest valid Android notification id; derivation never yields 0.
        private const val MIN_NOTIFICATION_ID: Int = 1
        // SharedPreferences file and key for the persisted notification id counter.
        private const val NOTIFICATION_ID_PREFS: String = "ps3_notification_ids"
        private const val NOTIFICATION_ID_KEY_NEXT: String = "next_id"
        private val pendingAnalysis = ConcurrentLinkedQueue<PendingAnalysis>()
        private val retryScheduled = AtomicBoolean(false)
        private val retryLock = Any()
        private val deferredActive = AtomicInteger(0)
        private val notificationIdLock = Any()
        private val lastAllocatedNotificationId = AtomicInteger(0)
        // One shared single-threaded scheduler for goAsync broadcasts (SEC-09).
        val executor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "ps3-sms-receiver").apply { isDaemon = true }
        }
        // Deferred retries run on a second single thread so a drain never blocks
        // an urgent goAsync broadcast behind it.
        val deferredExecutor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "ps3-sms-retry").apply { isDaemon = true }
        }
        const val MAX_STORED_MESSAGES = 20
        // Fast path for the deferred retry; the durable copy is PendingMessageStore.
        val messageStore: MutableMap<String, String> = Collections.synchronizedMap(
            object : LinkedHashMap<String, String>(MAX_STORED_MESSAGES, 0.75f, false) {
                override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?): Boolean =
                    size > MAX_STORED_MESSAGES
            }
        )
        data class PendingAnalysis(
            val messageId: String,
            val sender: String,
            val body: String,
            val receivedMs: Long = 0L,
            val attempts: Int = 0
        )
        private data class PreparedMessage(
            val sender: String,
            val body: String,
            val messageId: String,
            val stored: Boolean
        )
        /** Returns true if any message is queued or actively being processed by deferred analysis. */
        // True while deferred work is queued or being drained; the Llama gate
        // must wait on this, not queue emptiness alone (see retryPendingAnalysis).
        fun hasPendingAnalysis(): Boolean = pendingAnalysis.isNotEmpty() || deferredActive.get() > 0
        /** Generates a unique random message identifier prefixed with "msg-". */
        // Random UUID survives process death; a per-process counter would reissue
        // the same msg-<n> after every cold start and collide with stored entries.
        fun nextMessageId(): String = "msg-${UUID.randomUUID()}"
        /** Computes the next notification ID after [current], wrapping to 1 before Int.MAX_VALUE. */
        // Pure wrap for the persisted counter: wraps to 1 before overflowing Int.MAX_VALUE.
        fun nextNotificationIdAfter(current: Int): Int {
            return if (current < MIN_NOTIFICATION_ID || current >= Int.MAX_VALUE) {
                MIN_NOTIFICATION_ID
            } else {
                current + 1
            }
        }
        /**
         * Resolves the next monotonic notification ID based on persisted and in-memory states.
         *
         * Pure: picks the id to hand out given the persisted next value and the
         * last id handed out in this process. The result is always after the last
         * handed out (wrapping to MIN before Int overflow), even when the persisted
         * write failed and the persisted value is stale.
         */
        fun resolveNextNotificationId(persistedNext: Int, lastHandedOut: Int): Int {
            val persisted = if (persistedNext < MIN_NOTIFICATION_ID) MIN_NOTIFICATION_ID else persistedNext
            if (lastHandedOut < MIN_NOTIFICATION_ID) return persisted
            if (persisted > lastHandedOut) return persisted
            return nextNotificationIdAfter(lastHandedOut)
        }
        /** Allocates and commits the next persistent notification ID. */
        // Allocates the next notification id once, persisting the following value.
        // The in-memory counter keeps ids monotonic in this process even when commit() fails.
        fun allocateNotificationId(context: Context): Int {
            synchronized(notificationIdLock) {
                val appContext = context.applicationContext
                val prefs = appContext.getSharedPreferences(NOTIFICATION_ID_PREFS, Context.MODE_PRIVATE)
                var persisted = prefs.getInt(NOTIFICATION_ID_KEY_NEXT, MIN_NOTIFICATION_ID)
                if (persisted < MIN_NOTIFICATION_ID) {
                    persisted = MIN_NOTIFICATION_ID
                }
                val current = resolveNextNotificationId(persisted, lastAllocatedNotificationId.get())
                val next = nextNotificationIdAfter(current)
                val committed = prefs.edit().putInt(NOTIFICATION_ID_KEY_NEXT, next).commit()
                if (!committed) {
                    Log.w(TAG, "SmsReceiver: notification id commit failed")
                }
                lastAllocatedNotificationId.set(current)
                return current
            }
        }
        /** Allocates the next in-memory notification ID fallback without disk persistence. */
        // In-memory fallback used when persisted allocation throws: yields the next
        // id after the last one handed out in this process, so a failure never reuses 1.
        fun nextInMemoryNotificationId(): Int {
            synchronized(notificationIdLock) {
                return lastAllocatedNotificationId.updateAndGet { prev ->
                    if (prev < MIN_NOTIFICATION_ID) MIN_NOTIFICATION_ID else nextNotificationIdAfter(prev)
                }
            }
        }
        /** Returns the localized title string for scam alert notifications. */
        fun notificationTitle(): String =
            localizedString(R.string.notification_private_title, NOTIFICATION_TITLE_FALLBACK)
        /** Returns the appropriate notification title based on whether the message is a promotion. */
        fun notificationTitleFor(isPromotion: Boolean): String =
            if (isPromotion) {
                localizedString(R.string.notification_promotion_title, NOTIFICATION_PROMOTION_TITLE_FALLBACK)
            } else {
                notificationTitle()
            }
        /** Returns the notification body text reflecting promotion status or risk level verdict. */
        fun notificationTextFor(isPromotion: Boolean, level: String): String =
            if (isPromotion) {
                localizedString(R.string.notification_promotion_text, NOTIFICATION_PROMOTION_TEXT_FALLBACK)
            } else {
                notificationVerdict(level)
            }
        /** Returns the notification priority level (DEFAULT for promotions, HIGH for threats). */
        fun notificationPriorityFor(isPromotion: Boolean): Int =
            if (isPromotion) NotificationCompat.PRIORITY_DEFAULT else NotificationCompat.PRIORITY_HIGH
        /** Checks if notifications are enabled and permitted in the given [context]. */
        fun notificationsUsable(context: Context): Boolean = org.ps3.sentinel.sms.notificationsUsable(context)
        /** Evaluates notification usability given explicit permission, enabled, and importance flags. */
        fun notificationsUsable(
            permissionGranted: Boolean,
            notificationsEnabled: Boolean,
            channelImportance: Int?
        ): Boolean = org.ps3.sentinel.sms.notificationsUsable(permissionGranted, notificationsEnabled, channelImportance)
        const val MAX_DEFERRED_FAILURES: Int = 5
        /** Decides whether a deferred notification retry should be requeued based on whether it posted. */
        fun shouldRequeueDeferred(posted: Boolean): Boolean = !posted
        /** Decides whether a deferred notification retry should be requeued considering usability. */
        fun shouldRequeueDeferred(posted: Boolean, notificationsUsable: Boolean): Boolean =
            !posted && notificationsUsable
        /** Checks whether deferred analysis failure attempts remain below MAX_DEFERRED_FAILURES. */
        fun shouldRequeueAfterFailure(attempts: Int): Boolean = attempts < MAX_DEFERRED_FAILURES
        /** Action to take on a message during deferred retry processing. */
        enum class DeferredAction { POST, UPDATE, CANCEL_AND_DELETE, DELETE }
        /** Determines the deferred action to perform given threat verdict and prior notification status. */
        fun deferredAction(isThreat: Boolean, wasNotified: Boolean): DeferredAction = when {
            isThreat && wasNotified -> DeferredAction.UPDATE
            isThreat -> DeferredAction.POST
            wasNotified -> DeferredAction.CANCEL_AND_DELETE
            else -> DeferredAction.DELETE
        }
        /** Returns true if a deferred message should be marked settled once posted. */
        fun shouldMarkDeferredDone(posted: Boolean): Boolean = posted
        /**
         * Checks whether the evidence includes a definitive SMS model classification label.
         *
         * A verdict is full only when the SMS model answered. A model wait that timed out (a slow
         * phone still preparing Llama) leaves smsLabel null; that verdict is rule-only and the
         * message must be analysed again once the model is free.
         */
        fun hasModelAnswer(evidence: Evidence?): Boolean = evidence?.smsLabel != null
        /** Checks whether deferred processing should proceed based on stored entry existence. */
        fun shouldFinishDeferred(entryExists: Boolean): Boolean = entryExists
        private fun hasStoredEntry(store: PendingMessageStore?, messageId: String): Boolean {
            if (store == null) return false
            return try {
                store.hasEntry(messageId)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: pending store hasEntry failed: ${e::class.simpleName}: ${e.message}", e)
                false
            }
        }
        /**
         * Enqueues a message ID for deferred background analysis once models are warm.
         *
         * Startup re-queue: empty body is re-read from the durable store by drainPending.
         */
        fun enqueueDeferred(messageId: String) {
            if (messageId.isBlank()) {
                return
            }
            if (pendingAnalysis.any { it.messageId == messageId }) {
                return
            }
            pendingAnalysis.offer(PendingAnalysis(messageId, UNKNOWN_SENDER, "", 0L))
            notifyLlamaGateWaitersSafely()
        }
        /** Returns current queue size of pending deferred analyses for testing. */
        internal fun pendingAnalysisSize(): Int = pendingAnalysis.size
        /** Clears pending deferred analysis queue for testing. */
        internal fun clearPendingAnalysis() {
            pendingAnalysis.clear()
        }
        /**
         * Re-enqueues held alerts from the durable PendingMessageStore on a background thread
         * and schedules a deferred retry. Used when notifications transition to usable.
         */
        fun requeueHeldAlerts(context: Context) {
            val appContext = context.applicationContext
            try {
                deferredExecutor.execute {
                    try {
                        val store = PendingMessageStore.instance(appContext)
                        val ids = store.deferredIds()
                        for (id in ids) {
                            enqueueDeferred(id)
                        }
                        scheduleDeferredRetry()
                    } catch (e: Exception) {
                        Log.w(TAG, "SmsReceiver: requeueHeldAlerts failed: ${e::class.simpleName}: ${e.message}", e)
                    }
                }
            } catch (e: RejectedExecutionException) {
                Log.w(TAG, "SmsReceiver: deferredExecutor rejected requeueHeldAlerts", e)
            }
        }
        /** Formats the localized risk verdict string for display in notifications. */
        fun notificationVerdict(level: String): String =
            localizedString(
                R.string.notification_verdict_format,
                NOTIFICATION_VERDICT_FORMAT_FALLBACK,
                riskLevelText(level)
            )
        private fun riskLevelText(level: String): String {
            val fallback = level.uppercase(Locale.US)
            val resId = when (level.lowercase(Locale.US)) {
                "high" -> R.string.risk_level_high
                "medium" -> R.string.risk_level_medium
                "low" -> R.string.risk_level_low
                else -> return fallback
            }
            return localizedString(resId, fallback)
        }
        private fun localizedString(resId: Int, fallback: String, vararg args: Any): String {
            return try {
                val appContext = SentinelApp.instance
                localizedContext(appContext).getString(resId, *args)
            } catch (_: Throwable) {
                String.format(Locale.US, fallback, *args)
            }
        }
        // On Android 8-12 the application context does not follow the per-app locale chosen in
        // Settings, so notifications would stay in the system language. Below API 33, read the
        // string from a context configured with the AppCompat application locales instead.
        private fun localizedContext(context: Context): Context {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) return context
            return try {
                val locales = AppCompatDelegate.getApplicationLocales()
                if (locales.isEmpty) {
                    context
                } else {
                    val config = Configuration(context.resources.configuration)
                    config.setLocales(android.os.LocaleList.forLanguageTags(locales.toLanguageTags()))
                    context.createConfigurationContext(config)
                }
            } catch (_: Throwable) {
                context
            }
        }
        /**
         * Computes rule-based evidence for [text] without running ExecuTorch model inference.
         *
         * Pure check that rule-only needs no pipeline so a cold start can still alert.
         */
        fun ruleOnlyEvidence(pipeline: Pipeline?, text: String, sender: String? = null): Evidence {
            val baseCues = smsCues(text)
            val senderSpan = if (sender != null) senderCue(sender, text) else null
            val cues = if (senderSpan != null) baseCues + senderSpan else baseCues
            val urlResults = extractUrls(text).map { url ->
                val indicators = urlIndicators(url)
                val prob = when {
                    "brand_lookalike" in indicators || "risky_tld" in indicators || "ip_host" in indicators ->
                        URL_INDICATOR_HIGH_PROB
                    indicators.isNotEmpty() -> URL_INDICATOR_MEDIUM_PROB
                    else -> URL_INDICATOR_LOW_PROB
                }
                UrlResult(url, normaliseUrl(url), prob, if (prob >= 0.5) "phishing" else "benign", indicators)
            }
            return fuse(text, null, urlResults, cues, sender = sender)
        }
        private fun awaitPipelineReady(timeoutMs: Long): Pipeline? {
            val deadlineMs = SystemClock.elapsedRealtime() + timeoutMs
            while (SystemClock.elapsedRealtime() < deadlineMs) {
                val pipeline = activePipeline()
                if (pipeline != null) return pipeline
                try {
                    Thread.sleep(PIPELINE_POLL_INTERVAL_MS)
                } catch (e: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return activePipeline()
                }
            }
            return activePipeline()
        }
        /**
         * Builds intent extras map directing MainActivity to open the given [messageId].
         *
         * Pure so a JVM test can assert no body leaks into the intent (SEC-03).
         */
        fun openIntentExtras(messageId: String, storeSucceeded: Boolean = true): Map<String, String> {
            return if (storeSucceeded) {
                mapOf(MainActivity.EXTRA_SMS_ID to messageId)
            } else {
                mapOf(
                    MainActivity.EXTRA_SMS_ID to messageId,
                    MainActivity.EXTRA_SMS_UNSAVED to "true"
                )
            }
        }
        private fun pendingStore(context: Context?): PendingMessageStore? {
            if (context == null) return null
            return try {
                PendingMessageStore.instance(context.applicationContext)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: pending store unavailable: ${e::class.simpleName}: ${e.message}", e)
                null
            }
        }
        private fun peekPending(store: PendingMessageStore?, messageId: String): String? {
            if (store == null) return null
            return try {
                store.peek(messageId)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: pending store peek failed: ${e::class.simpleName}: ${e.message}", e)
                null
            }
        }
        private fun storePendingBody(
            context: Context,
            messageId: String,
            body: String,
            deferred: Boolean = false
        ): Boolean {
            messageStore[messageId] = body
            return try {
                PendingMessageStore.instance(context.applicationContext).put(messageId, body, deferred)
                true
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: pending store write failed " +
                    "message=${sha256Short(body)}: ${e::class.simpleName}: ${e.message}", e)
                false
            }
        }
        private fun deletePendingBody(context: Context, messageId: String) {
            messageStore.remove(messageId)
            try {
                PendingMessageStore.instance(context.applicationContext).delete(messageId)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: pending store delete failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }
        private fun storedNotificationId(store: PendingMessageStore?, messageId: String): Int {
            if (store == null) return 0
            return try {
                store.notificationIdOf(messageId)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: notification id read failed: ${e::class.simpleName}: ${e.message}", e)
                0
            }
        }
        private fun markDeferredDoneSafely(context: Context, messageId: String) {
            try {
                PendingMessageStore.instance(context.applicationContext).markDeferredDone(messageId)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: deferred done write failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }
        /**
         * Drains pending analyses queue once the SMS model is ready, re-analyzing stored bodies.
         *
         * Runs postponed full analyses once the SMS model is warm; cold items requeue.
         * Single drain under one lock: polled items stay "active" until requeued
         * or finished, so the Llama gate cannot see a transient empty queue.
         */
        fun retryPendingAnalysis() {
            try {
                synchronized(retryLock) {
                    val pipeline = activePipeline()
                    if (pipeline == null) {
                        if (pendingAnalysis.isNotEmpty()) scheduleDeferredRetry()
                        return
                    }
                    if (pendingAnalysis.isEmpty()) return
                    deferredActive.incrementAndGet()
                    try {
                        drainPending(pipeline)
                    } finally {
                        deferredActive.decrementAndGet()
                    }
                }
            } finally {
                notifyLlamaGateWaitersSafely()
            }
        }
        private fun drainPending(pipeline: Pipeline) {
            val context = activeContext()
            val store = pendingStore(context)
            val stillPending = ArrayList<PendingAnalysis>()
            var pending = pendingAnalysis.poll()
            try {
                while (pending != null) {
                    try {
                        val body = pending.body.ifEmpty {
                            messageStore[pending.messageId] ?: peekPending(store, pending.messageId) ?: ""
                        }
                        if (body.isEmpty()) {
                            if (context != null && store != null && hasStoredEntry(store, pending.messageId)) {
                                deletePendingBody(context, pending.messageId)
                            }
                            logDeferredDone(pending, posted = false, updated = false)
                            pending = pendingAnalysis.poll()
                            continue
                        }
                        if (CpuFeatures.isExecutorchBlocked()) {
                            if (context != null) {
                                val evidence = ruleOnlyEvidence(pipeline, body, pending.sender)
                                val threat = AlertPolicy.isThreat(evidence)
                                if (threat) {
                                    val stored = hasStoredEntry(store, pending.messageId)
                                    val posted = postThreatNotification(context, pending.sender, pending.messageId, evidence, stored, body)
                                    if (posted) {
                                        markDeferredDoneSafely(context, pending.messageId)
                                        logDeferredDone(pending, posted = true, updated = false)
                                    } else {
                                        val usable = notificationsUsable(context)
                                        if (shouldRequeueDeferred(posted, usable)) {
                                            if (shouldRequeueAfterFailure(pending.attempts)) {
                                                stillPending.add(pending.copy(attempts = pending.attempts + 1))
                                            } else {
                                                deletePendingBody(context, pending.messageId)
                                            }
                                        } else if (!usable) {
                                            Log.i(TAG, "SmsReceiver: notifications not usable; holding deferred entry messageId=${pending.messageId}")
                                        }
                                        logDeferredDone(pending, posted = false, updated = false)
                                    }
                                } else {
                                    deletePendingBody(context, pending.messageId)
                                    logDeferredDone(pending, posted = false, updated = false)
                                }
                            } else {
                                stillPending.add(pending)
                            }
                        } else if (!pipeline.isSmsModelLoaded()) {
                            if (pipeline.retrySmsLoadIfFilesChangedAsync() || !pipeline.isSmsWarmUpDone()) {
                                stillPending.add(pending)
                            } else {
                                if (context != null) {
                                    val evidence = ruleOnlyEvidence(pipeline, body, pending.sender)
                                    val threat = AlertPolicy.isThreat(evidence)
                                    if (threat) {
                                        val stored = hasStoredEntry(store, pending.messageId)
                                        val posted = postThreatNotification(context, pending.sender, pending.messageId, evidence, stored, body, recordAlert = false)
                                        if (posted) {
                                            markDeferredDoneSafely(context, pending.messageId)
                                            logDeferredDone(pending, posted = true, updated = false)
                                        } else {
                                            val usable = notificationsUsable(context)
                                            if (shouldRequeueDeferred(posted, usable)) {
                                                if (shouldRequeueAfterFailure(pending.attempts)) {
                                                    stillPending.add(pending.copy(attempts = pending.attempts + 1))
                                                } else {
                                                    deletePendingBody(context, pending.messageId)
                                                }
                                            } else if (!usable) {
                                                Log.i(TAG, "SmsReceiver: notifications not usable; holding deferred entry messageId=${pending.messageId}")
                                            }
                                            logDeferredDone(pending, posted = false, updated = false)
                                        }
                                    } else {
                                        if (storedNotificationId(store, pending.messageId) != 0) {
                                            markDeferredDoneSafely(context, pending.messageId)
                                        } else {
                                            deletePendingBody(context, pending.messageId)
                                        }
                                        logDeferredDone(pending, posted = false, updated = false)
                                    }
                                } else {
                                    stillPending.add(pending)
                                }
                            }
                        } else if (context != null) {
                            if (finishDeferred(pipeline, context, pending, body)) {
                                if (shouldRequeueAfterFailure(pending.attempts)) {
                                    stillPending.add(pending.copy(attempts = pending.attempts + 1))
                                } else {
                                    deletePendingBody(context, pending.messageId)
                                }
                            }
                        } else {
                            stillPending.add(pending)
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "SmsReceiver: deferred analysis failed " +
                            "message=${sha256Short(pending.messageId)}: ${e::class.simpleName}: ${e.message}", e)
                        if (shouldRequeueAfterFailure(pending.attempts)) {
                            stillPending.add(pending.copy(attempts = pending.attempts + 1))
                        } else {
                            if (context != null && store != null && hasStoredEntry(store, pending.messageId)) {
                                deletePendingBody(context, pending.messageId)
                            }
                            logDeferredDone(pending, posted = false, updated = false)
                        }
                    } catch (e: LinkageError) {
                        Log.w(TAG, "SmsReceiver: deferred analysis failed " +
                            "message=${sha256Short(pending.messageId)}: ${e::class.simpleName}: ${e.message}", e)
                        if (shouldRequeueAfterFailure(pending.attempts)) {
                            stillPending.add(pending.copy(attempts = pending.attempts + 1))
                        } else {
                            if (context != null && store != null && hasStoredEntry(store, pending.messageId)) {
                                deletePendingBody(context, pending.messageId)
                            }
                            logDeferredDone(pending, posted = false, updated = false)
                        }
                    }
                    pending = pendingAnalysis.poll()
                }
            } catch (t: Throwable) {
                pending?.let { if (it !in stillPending) stillPending.add(it) }
                throw t
            } finally {
                for (item in stillPending) pendingAnalysis.offer(item)
                if (stillPending.isNotEmpty()) scheduleDeferredRetry()
            }
        }
        private fun logDeferredDone(pending: PendingAnalysis, posted: Boolean, updated: Boolean) {
            val nowMs = SystemClock.elapsedRealtime()
            val baseMs = if (pending.receivedMs > 0L) pending.receivedMs else nowMs
            Log.i(TIMING_TAG, "deferred_analysis_done_ms=${nowMs - baseMs} posted=$posted updated=$updated")
        }
        private fun finishDeferred(pipeline: Pipeline, context: Context, pending: PendingAnalysis, body: String): Boolean {
            val store = pendingStore(context)
            if (!shouldFinishDeferred(hasStoredEntry(store, pending.messageId))) {
                logDeferredDone(pending, posted = false, updated = false)
                return false
            }
            val evidence = pipeline.analyseFast(body, sender = pending.sender)
            // Still no model answer: fail this attempt so drainPending requeues it (bounded).
            check(hasModelAnswer(evidence)) { "SMS model gave no answer" }
            val notificationId = storedNotificationId(store, pending.messageId)
            val wasNotified = notificationId != 0
            val action = deferredAction(AlertPolicy.isThreat(evidence), wasNotified)
            var posted = false
            var updated = false
            var shouldRequeue = false
            when (action) {
                DeferredAction.POST, DeferredAction.UPDATE -> {
                    val stored = storePendingBody(context, pending.messageId, body, deferred = true)
                    posted = postThreatNotification(context, pending.sender, pending.messageId, evidence, stored, body)
                    updated = posted && wasNotified
                    if (posted) {
                        markDeferredDoneSafely(context, pending.messageId)
                    } else {
                        val usable = notificationsUsable(context)
                        shouldRequeue = shouldRequeueDeferred(posted, usable)
                        if (!usable) {
                            Log.i(TAG, "SmsReceiver: notifications not usable; holding deferred entry messageId=${pending.messageId}")
                        }
                    }
                }
                DeferredAction.CANCEL_AND_DELETE -> {
                    try {
                        NotificationManagerCompat.from(context).cancel(notificationId)
                    } catch (e: Exception) {
                        Log.w(TAG, "SmsReceiver: notification cancel failed: ${e::class.simpleName}: ${e.message}", e)
                    }
                    deletePendingBody(context, pending.messageId)
                    AlertLog.add(
                        context,
                        AlertEntry(
                            id = pending.messageId,
                            timeMillis = System.currentTimeMillis(),
                            level = evidence.level,
                            label = evidence.label,
                            sender = pending.sender,
                            message = body,
                            kind = AlertLog.KIND_SAFE
                        )
                    )
                }
                DeferredAction.DELETE -> {
                    deletePendingBody(context, pending.messageId)
                    AlertLog.add(
                        context,
                        AlertEntry(
                            id = pending.messageId,
                            timeMillis = System.currentTimeMillis(),
                            level = evidence.level,
                            label = evidence.label,
                            sender = pending.sender,
                            message = body,
                            kind = AlertLog.KIND_SAFE
                        )
                    )
                }
            }
            logDeferredDone(pending, posted, updated)
            return shouldRequeue
        }
        private fun activePipeline(): Pipeline? = try {
            SentinelApp.instance.pipeline
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: activePipeline unavailable: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        private fun activeContext(): Context? = try {
            SentinelApp.instance
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: activeContext unavailable: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        private fun notifyLlamaGateWaitersSafely() {
            try {
                SentinelApp.instance.notifyLlamaGateWaiters()
            } catch (_: Throwable) {
                // No Application in unit tests or uninitialized process; ignore.
            }
        }
        private fun scheduleDeferredRetry() {
            if (!retryScheduled.compareAndSet(false, true)) return
            try {
                deferredExecutor.schedule({
                    try {
                        retryPendingAnalysis()
                    } finally {
                        retryScheduled.set(false)
                        if (pendingAnalysis.isNotEmpty()) scheduleDeferredRetry()
                    }
                }, AlertPolicy.DEFERRED_RETRY_INTERVAL_MS, TimeUnit.MILLISECONDS)
            } catch (_: RejectedExecutionException) {
                retryScheduled.set(false)
            }
        }
        // Posts verdict only; returns true only when notify succeeded.
        // Plain promotions post non-alarming promotion text at default priority.
        private fun postThreatNotification(
            context: Context,
            sender: String,
            messageId: String,
            evidence: Evidence,
            storeSucceeded: Boolean = true,
            body: String? = null,
            recordAlert: Boolean = true
        ): Boolean {
            if (!notificationsUsable(context)) {
                return false
            }
            val store = pendingStore(context)
            var notificationId = storedNotificationId(store, messageId)
            if (notificationId <= 0) {
                notificationId = try {
                    allocateNotificationId(context)
                } catch (e: Exception) {
                    Log.w(TAG, "SmsReceiver: notification id allocation failed: ${e::class.simpleName}: ${e.message}", e)
                    nextInMemoryNotificationId()
                }
                try {
                    store?.setNotificationId(messageId, notificationId)
                } catch (e: Exception) {
                    Log.w(TAG, "SmsReceiver: notification id store failed: ${e::class.simpleName}: ${e.message}", e)
                }
            }
            val openIntent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                for ((key, value) in openIntentExtras(messageId, storeSucceeded)) putExtra(key, value)
            }
            val pendingIntent = PendingIntent.getActivity(
                context, notificationId, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val levelColor = if (evidence.level == "high") {
                ContextCompat.getColor(context, R.color.danger)
            } else {
                ContextCompat.getColor(context, R.color.warn)
            }
            val isPromotion = body != null && isPlainPromotion(body, evidence)
            val builder = NotificationCompat.Builder(context, SentinelApp.CHANNEL_ID_ALERTS)
                .setSmallIcon(R.drawable.ic_stat_shield)
                .setColor(levelColor)
                .setContentTitle(notificationTitleFor(isPromotion))
                .setContentText(notificationTextFor(isPromotion, evidence.level))
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .setPriority(notificationPriorityFor(isPromotion))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .setPublicVersion(buildPublicNotification(context, pendingIntent, levelColor, isPromotion))
            return try {
                NotificationManagerCompat.from(context).notify(notificationId, builder.build())
                if (recordAlert) {
                    AlertLog.add(
                        context,
                        AlertEntry(
                            id = messageId,
                            timeMillis = System.currentTimeMillis(),
                            level = evidence.level,
                            label = evidence.label,
                            sender = sender,
                            message = body,
                            kind = AlertLog.KIND_SCAM
                        )
                    )
                }
                true
            } catch (_: SecurityException) {
                false
            }
        }
        private fun buildPublicNotification(
            context: Context,
            pendingIntent: PendingIntent,
            levelColor: Int,
            isPromotion: Boolean = false
        ): android.app.Notification {
            return NotificationCompat.Builder(context, SentinelApp.CHANNEL_ID_ALERTS)
                .setSmallIcon(R.drawable.ic_stat_shield)
                .setColor(levelColor)
                .setContentTitle(
                    if (isPromotion) context.getString(R.string.notification_promotion_title)
                    else context.getString(R.string.notification_public_title)
                )
                .setContentText(
                    if (isPromotion) context.getString(R.string.notification_promotion_text)
                    else context.getString(R.string.notification_public_text)
                )
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setPriority(notificationPriorityFor(isPromotion))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build()
        }

        private fun postProtectionUnavailableNotification(context: Context) {
            val notificationId = try {
                allocateNotificationId(context)
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: notification id allocation failed: ${e::class.simpleName}: ${e.message}", e)
                nextInMemoryNotificationId()
            }
            val openIntent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pendingIntent = PendingIntent.getActivity(
                context, notificationId, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val builder = NotificationCompat.Builder(context, SentinelApp.CHANNEL_ID_ALERTS)
                .setSmallIcon(R.drawable.ic_stat_shield)
                .setColor(ContextCompat.getColor(context, R.color.danger))
                .setContentTitle(
                    localizedString(
                        R.string.notification_protection_unavailable_title,
                        NOTIFICATION_PROTECTION_UNAVAILABLE_TITLE_FALLBACK
                    )
                )
                .setContentText(
                    localizedString(
                        R.string.notification_protection_unavailable_text,
                        NOTIFICATION_PROTECTION_UNAVAILABLE_TEXT_FALLBACK
                    )
                )
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
            try {
                NotificationManagerCompat.from(context).notify(notificationId, builder.build())
            } catch (e: SecurityException) {
                Log.w(TAG, "SmsReceiver: protection unavailable notification not allowed: ${e.message}")
            } catch (e: Exception) {
                Log.w(TAG, "SmsReceiver: protection unavailable notification failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }
    }
    /** Handles incoming SMS_RECEIVED broadcasts, parsing multipart PDUs and launching async analysis. */
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val messages = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (messages.isNullOrEmpty()) return
        val bodiesBySender = messages.groupBy { it.displayOriginatingAddress ?: UNKNOWN_SENDER }
            .mapValues { (_, parts) -> parts.joinToString("") { it.displayMessageBody ?: "" } }
        handleMessages(context, bodiesBySender, goAsync()::finish)
    }

    /** Runs the incoming-SMS path for sender-to-body pairs. Also the entry point of the debug-build test receiver. */
    internal fun handleMessages(context: Context, bodiesBySender: Map<String, String>, finish: () -> Unit) {
        val receivedMs = SystemClock.elapsedRealtime()
        val deadlineMs = receivedMs + AlertPolicy.SMS_MODEL_WAIT_TIMEOUT_MS
        val pipeline = (context.applicationContext as? SentinelApp)?.pipeline
        val applicationContext = context.applicationContext
        executor.submit {
            try {
                val prepared = ArrayList<PreparedMessage>()
                for ((sender, fullBody) in bodiesBySender) {
                    if (!fullBody.isBlank()) {
                        if (shouldSkip(sender, fullBody)) {
                            Log.i(TAG, "sms_skipped kind=${skipKind(fullBody)}")
                            continue
                        }
                        val messageId = nextMessageId()
                        val stored = storePendingBody(applicationContext, messageId, fullBody, deferred = true)
                        prepared.add(PreparedMessage(sender, fullBody, messageId, stored))
                    }
                }
                for (preparedMessage in prepared) {
                    processMessage(applicationContext, pipeline, preparedMessage.sender, preparedMessage.body, receivedMs,
                        deadlineMs, preparedMessage.messageId, preparedMessage.stored)
                }
            } finally {
                finish()
            }
        }
    }
    private fun processMessage(
        context: Context,
        pipeline: Pipeline?,
        sender: String,
        body: String,
        receivedMs: Long,
        deadlineMs: Long,
        messageId: String,
        stored: Boolean
    ) {
        // DT-18 cold-start: detection is expected now, so no prefill may start
        // ahead of the SMS model forward.
        try {
            ExecutorchGate.markDetectionExpected()
        } catch (_: Exception) {
        }
        try {
            val rulesError = SentinelApp.instance.rulesLoadError
            if (rulesError != null) {
                if (notificationsUsable(context)) {
                    postProtectionUnavailableNotification(context)
                }
                deletePendingBody(context, messageId)
                Log.w(
                    TAG,
                    "SmsReceiver: rules load error ($rulesError); " +
                        "protection unavailable notification posted, pending body deleted for messageId=$messageId"
                )
                return
            }
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: rules check failed " +
                "message=${sha256Short(body)} sender=${sha256Short(sender)}: ${e::class.simpleName}: ${e.message}", e)
        }
        markAnalysis(true)
        try {
            handleMessage(context, pipeline, sender, body, receivedMs, deadlineMs, messageId, stored)
        } finally {
            markAnalysis(false)
        }
    }
    private fun markAnalysis(begin: Boolean) {
        try {
            if (begin) SentinelApp.instance.beginSmsAnalysis() else SentinelApp.instance.endSmsAnalysis()
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: sms analysis gate failed: ${e::class.simpleName}: ${e.message}", e)
        }
    }
    private fun handleMessage(
        context: Context,
        pipeline: Pipeline?,
        sender: String,
        body: String,
        receivedMs: Long,
        deadlineMs: Long,
        messageId: String,
        stored: Boolean
    ) {
        // Armv8.0 without the stock baseline library cannot load any ExecuTorch module:
        // libexecutorch_jni.so executes an unsupported LSE atomic and crashes. Use the
        // rule-only path and never defer for an SMS model that can never load.
        if (CpuFeatures.isExecutorchBlocked()) {
            val evidence = ruleOnlyEvidence(pipeline, body, sender)
            val threat = AlertPolicy.isThreat(evidence)
            if (threat) {
                val posted = postThreatNotification(context, sender, messageId, evidence, stored, body)
                if (posted) {
                    markDeferredDoneSafely(context, messageId)
                    Log.i(TIMING_TAG, "sms_received_to_alert_ms=${SystemClock.elapsedRealtime() - receivedMs}")
                } else {
                    val usable = notificationsUsable(context)
                    if (shouldRequeueDeferred(posted, usable)) {
                        pendingAnalysis.offer(PendingAnalysis(messageId, sender, body, receivedMs))
                        notifyLlamaGateWaitersSafely()
                        scheduleDeferredRetry()
                    } else if (!usable) {
                        Log.i(TAG, "SmsReceiver: notifications not usable; holding deferred entry messageId=$messageId")
                    }
                }
            } else {
                deletePendingBody(context, messageId)
            }
            return
        }
        val fullEvidence = try {
            fullIfReady(pipeline, body, deadlineMs, sender)?.takeIf { hasModelAnswer(it) }
        } catch (e: UnsatisfiedLinkError) {
            Log.w(TAG, "SmsReceiver: full analysis failed " +
                "message=${sha256Short(body)} sender=${sha256Short(sender)}: ${e::class.simpleName}: ${e.message}", e)
            null
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: full analysis failed " +
                "message=${sha256Short(body)} sender=${sha256Short(sender)}: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        val evidence = fullEvidence ?: ruleOnlyEvidence(pipeline, body, sender)
        // Verdict line for device tests: level, model class and alert decision only, never text or sender.
        Log.i(TIMING_TAG, "sms_verdict level=${evidence.level} sms_label=${evidence.smsLabel} " +
            "full=${fullEvidence != null} alert=${AlertPolicy.isThreat(evidence)}")
        if (fullEvidence != null) {
            if (AlertPolicy.isThreat(evidence)) {
                val posted = postThreatNotification(context, sender, messageId, evidence, stored, body)
                if (posted) {
                    markDeferredDoneSafely(context, messageId)
                    Log.i(TIMING_TAG, "sms_received_to_alert_ms=${SystemClock.elapsedRealtime() - receivedMs}")
                } else {
                    val usable = notificationsUsable(context)
                    if (shouldRequeueDeferred(posted, usable)) {
                        pendingAnalysis.offer(PendingAnalysis(messageId, sender, body, receivedMs))
                        notifyLlamaGateWaitersSafely()
                        scheduleDeferredRetry()
                    } else if (!usable) {
                        Log.i(TAG, "SmsReceiver: notifications not usable; holding deferred entry messageId=$messageId")
                    }
                }
            } else {
                deletePendingBody(context, messageId)
                AlertLog.add(
                    context,
                    AlertEntry(
                        id = messageId,
                        timeMillis = System.currentTimeMillis(),
                        level = evidence.level,
                        label = evidence.label,
                        sender = sender,
                        message = body,
                        kind = AlertLog.KIND_SAFE
                    )
                )
            }
            return
        }
        if (AlertPolicy.isThreat(evidence)) {
            val posted = postThreatNotification(context, sender, messageId, evidence, stored, body, recordAlert = false)
            if (posted) {
                Log.i(TIMING_TAG, "sms_received_to_alert_ms=${SystemClock.elapsedRealtime() - receivedMs}")
            }
        }
        pendingAnalysis.offer(PendingAnalysis(messageId, sender, body, receivedMs))
        notifyLlamaGateWaitersSafely()
        scheduleDeferredRetry()
    }
    private fun fullIfReady(capturedPipeline: Pipeline?, body: String, deadlineMs: Long, sender: String? = null): Evidence? {
        val pipelineRemaining = (deadlineMs - SystemClock.elapsedRealtime()).coerceAtLeast(0L)
        awaitPipelineReady(pipelineRemaining)
        val freshPipeline: Pipeline? = try {
            SentinelApp.instance.pipeline
        } catch (e: Exception) {
            Log.w(TAG, "SmsReceiver: pipeline re-read failed: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        val pipeline = freshPipeline ?: capturedPipeline
        if (pipeline == null) return null
        if (!pipeline.isSmsModelLoaded()) {
            pipeline.retrySmsLoadIfFilesChangedAsync()
        }
        if (pipeline.isSmsModelLoaded()) return pipeline.analyseFast(body, sender = sender)
        val smsRemaining = (deadlineMs - SystemClock.elapsedRealtime()).coerceAtLeast(0L)
        if (smsRemaining <= 0L) return null
        if (!pipeline.awaitSmsReady(smsRemaining)) return null
        return pipeline.analyseFast(body, sender = sender)
    }
}

/**
 * Pure decision: returns true only if notifications are enabled, permission is granted,
 * and the scam alert channel (if configured) does not have IMPORTANCE_NONE.
 */
fun notificationsUsable(
    permissionGranted: Boolean,
    notificationsEnabled: Boolean,
    channelImportance: Int?
): Boolean {
    if (!permissionGranted) return false
    if (!notificationsEnabled) return false
    if (channelImportance != null && channelImportance == NotificationManager.IMPORTANCE_NONE) return false
    return true
}

/**
 * Returns true only if POST_NOTIFICATIONS is granted (on API 33+),
 * NotificationManagerCompat.areNotificationsEnabled() is true,
 * and the scam alert channel (if it exists) does not have IMPORTANCE_NONE.
 */
fun notificationsUsable(context: Context): Boolean {
    val permissionGranted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    } else {
        true
    }
    val notificationsEnabled = NotificationManagerCompat.from(context).areNotificationsEnabled()
    val channelImportance = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm?.getNotificationChannel(SentinelApp.CHANNEL_ID_ALERTS)?.importance
    } else {
        null
    }
    return notificationsUsable(permissionGranted, notificationsEnabled, channelImportance)
}
