package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class SmsReceiverTest {

    @Test
    fun testExecutorIsSingleThreaded() {
        val taskCount = 6
        val latch = CountDownLatch(taskCount)
        val threadNames = java.util.Collections.synchronizedList(java.util.ArrayList<String>())

        for (i in 0 until taskCount) {
            SmsReceiver.executor.submit {
                threadNames.add(Thread.currentThread().name)
                Thread.sleep(15)
                latch.countDown()
            }
        }

        assertTrue("tasks should complete", latch.await(10, TimeUnit.SECONDS))
        val distinct = threadNames.toSet()
        // One shared single-threaded executor: every task runs on the same thread, never a thread per broadcast.
        assertEquals(1, distinct.size)
        assertTrue("all tasks ran on the receiver thread", threadNames.all { it == "ps3-sms-receiver" })
    }

    @Test
    fun testMessageStoreKeepsBodyById() {
        SmsReceiver.messageStore["msg-1"] = "From 12345: your account is blocked"
        assertEquals("From 12345: your account is blocked", SmsReceiver.messageStore["msg-1"])
        val removed = SmsReceiver.messageStore.remove("msg-1")
        assertEquals("From 12345: your account is blocked", removed)
        assertNull("body removed after delivery", SmsReceiver.messageStore["msg-1"])
    }

    @Test
    fun testNextMessageIdsAreUnique() {
        val id1 = SmsReceiver.nextMessageId()
        val id2 = SmsReceiver.nextMessageId()
        assertTrue("message id starts with msg-", id1.startsWith("msg-"))
        assertNotEquals("message ids are unique", id1, id2)
    }

    @Test
    fun testNextMessageIdsAreUuidAcrossColdStarts() {
        val ids = (1..50).map { SmsReceiver.nextMessageId() }.toSet()
        assertEquals(50, ids.size)
        assertTrue("uuid ids carry msg- prefix", ids.all { it.startsWith("msg-") && it.length > 10 })
    }

    @Test
    fun testNotificationIdWrapHelper() {
        assertEquals(2, SmsReceiver.nextNotificationIdAfter(1))
        assertEquals(42, SmsReceiver.nextNotificationIdAfter(41))
        assertEquals(Int.MAX_VALUE, SmsReceiver.nextNotificationIdAfter(Int.MAX_VALUE - 1))
        assertEquals(1, SmsReceiver.nextNotificationIdAfter(Int.MAX_VALUE))
        assertEquals(1, SmsReceiver.nextNotificationIdAfter(0))
        assertEquals(1, SmsReceiver.nextNotificationIdAfter(-5))
    }

    @Test
    fun testNotificationTitleHasNoSender() {
        val title = SmsReceiver.notificationTitle()
        assertEquals("Possible scam message", title)
        assertFalse("title must not contain a sender from earlier tests", title.contains("VM-SBIBNK"))
        assertFalse("title must not contain a message body", title.contains("OTP"))
    }

    @Test
    fun testNotificationVerdictIsUppercaseLevelOnly() {
        assertEquals("Risk: HIGH", SmsReceiver.notificationVerdict("high"))
        assertEquals("Risk: MEDIUM", SmsReceiver.notificationVerdict("medium"))
    }

    @Test
    fun testPromotionNotificationSaysPromotionNotScam() {
        val promoTitle = SmsReceiver.notificationTitleFor(true)
        assertTrue(promoTitle.lowercase().contains("promotion"))
        assertFalse(promoTitle.lowercase().contains("scam"))
        assertFalse(promoTitle.contains("Possible scam"))
        val promoText = SmsReceiver.notificationTextFor(true, "medium")
        assertTrue(promoText.lowercase().contains("promotion"))
        assertTrue(SmsReceiver.notificationPriorityFor(true) != androidx.core.app.NotificationCompat.PRIORITY_HIGH)
        assertEquals(androidx.core.app.NotificationCompat.PRIORITY_HIGH, SmsReceiver.notificationPriorityFor(false))
        assertEquals("Possible scam message", SmsReceiver.notificationTitleFor(false))
        assertEquals("Risk: MEDIUM", SmsReceiver.notificationTextFor(false, "medium"))
    }

    @Test
    fun testPendingIntentExtrasContainIdOnlyNoBody() {
        val body = "OTP 123456 do not share"
        val extras = SmsReceiver.openIntentExtras("msg-99")
        assertEquals(1, extras.size)
        assertTrue("only the sms id extra is present", extras.containsKey("extra_sms_id"))
        assertEquals("msg-99", extras["extra_sms_id"])
        assertFalse("extras must not contain the body", extras.values.any { it.contains(body) || it.contains("OTP") })
        assertFalse("no extra key may carry the body", extras.keys.any { it.contains(body) })
    }

    @Test
    fun testMissingPendingMessageTextIsExact() {
        assertEquals(
            "This message is no longer stored. Paste it to check it again.",
            org.ps3.sentinel.ui.MainActivity.MISSING_PENDING_MESSAGE_TEXT
        )
    }

    @Test
    fun testUnsavedIntentExtrasMarkSaveFailure() {
        val extras = SmsReceiver.openIntentExtras("msg-99", storeSucceeded = false)
        assertEquals(2, extras.size)
        assertEquals("msg-99", extras[org.ps3.sentinel.ui.MainActivity.EXTRA_SMS_ID])
        assertEquals(
            "true",
            extras[org.ps3.sentinel.ui.MainActivity.EXTRA_SMS_UNSAVED]
        )
        assertFalse(
            "extras must not contain the body",
            extras.values.any { it.contains("OTP") }
        )
    }

    @Test
    fun testSavedIntentExtrasHaveNoUnsavedMark() {
        val extras = SmsReceiver.openIntentExtras("msg-99", storeSucceeded = true)
        assertEquals(1, extras.size)
        assertFalse(extras.containsKey(org.ps3.sentinel.ui.MainActivity.EXTRA_SMS_UNSAVED))
    }

    @Test
    fun testUnsavedPendingMessageTextIsExact() {
        assertEquals(
            "This message could not be saved. Paste it to check it again.",
            org.ps3.sentinel.ui.MainActivity.UNSAVED_PENDING_MESSAGE_TEXT
        )
    }

    @Test
    fun testEnqueueDeferredTwiceWithSameIdLeavesOneQueuedEntry() {
        SmsReceiver.clearPendingAnalysis()
        try {
            SmsReceiver.enqueueDeferred("msg-dedupe-1")
            SmsReceiver.enqueueDeferred("msg-dedupe-1")
            assertEquals(1, SmsReceiver.pendingAnalysisSize())
        } finally {
            SmsReceiver.clearPendingAnalysis()
        }
    }

    @Test
    fun testDeferredActionThreatFreshPosts() {
        assertEquals(SmsReceiver.Companion.DeferredAction.POST, SmsReceiver.deferredAction(isThreat = true, wasNotified = false))
    }

    @Test
    fun testDeferredActionThreatNotifiedUpdates() {
        assertEquals(SmsReceiver.Companion.DeferredAction.UPDATE, SmsReceiver.deferredAction(isThreat = true, wasNotified = true))
    }

    @Test
    fun testDeferredActionNonThreatNotifiedCancelsAndDeletes() {
        assertEquals(SmsReceiver.Companion.DeferredAction.CANCEL_AND_DELETE, SmsReceiver.deferredAction(isThreat = false, wasNotified = true))
    }

    @Test
    fun testDeferredActionNonThreatFreshDeletes() {
        assertEquals(SmsReceiver.Companion.DeferredAction.DELETE, SmsReceiver.deferredAction(isThreat = false, wasNotified = false))
    }

    @Test
    fun testShouldMarkDeferredDoneOnlyWhenPosted() {
        assertTrue(SmsReceiver.shouldMarkDeferredDone(posted = true))
        assertFalse(SmsReceiver.shouldMarkDeferredDone(posted = false))
    }

    @Test
    fun testShouldFinishDeferredActsWhenEntryExists() {
        assertTrue(SmsReceiver.shouldFinishDeferred(entryExists = true))
    }

    @Test
    fun testShouldFinishDeferredSkipsWhenEntryMissing() {
        assertFalse(SmsReceiver.shouldFinishDeferred(entryExists = false))
    }

    @Test
    fun testResolveNextIdUsesPersistedWhenNoPriorHandout() {
        assertEquals(7, SmsReceiver.resolveNextNotificationId(7, 0))
        assertEquals(1, SmsReceiver.resolveNextNotificationId(0, 0))
        assertEquals(1, SmsReceiver.resolveNextNotificationId(-5, 0))
    }

    @Test
    fun testResolveNextIdUsesPersistedWhenAheadOfLast() {
        assertEquals(9, SmsReceiver.resolveNextNotificationId(9, 4))
    }

    @Test
    fun testResolveNextIdAfterLastWhenPersistedIsStale() {
        // Simulates a failed commit(): persisted value never advanced, so the
        // in-memory last handed-out id wins and the next id moves forward.
        assertEquals(6, SmsReceiver.resolveNextNotificationId(5, 5))
        assertEquals(8, SmsReceiver.resolveNextNotificationId(5, 7))
    }

    @Test
    fun testResolveNextIdMonotonicDespiteStalePersisted() {
        var lastHandedOut = 0
        val persisted = 5
        val first = SmsReceiver.resolveNextNotificationId(persisted, lastHandedOut)
        lastHandedOut = first
        val second = SmsReceiver.resolveNextNotificationId(persisted, lastHandedOut)
        lastHandedOut = second
        val third = SmsReceiver.resolveNextNotificationId(persisted, lastHandedOut)
        assertEquals(5, first)
        assertEquals(6, second)
        assertEquals(7, third)
        assertTrue(second > first)
        assertTrue(third > second)
    }

    @Test
    fun testResolveNextIdWrapsBeforeOverflowLikeCounter() {
        assertEquals(1, SmsReceiver.resolveNextNotificationId(1, Int.MAX_VALUE))
    }

    @Test
    fun testShouldRequeueDeferredOnlyWhenNotPosted() {
        assertTrue(SmsReceiver.shouldRequeueDeferred(posted = false))
        assertFalse(SmsReceiver.shouldRequeueDeferred(posted = true))
    }

    @Test
    fun testShouldRequeueDeferredWithNotificationsUsable() {
        assertTrue(SmsReceiver.shouldRequeueDeferred(posted = false, notificationsUsable = true))
        assertFalse(SmsReceiver.shouldRequeueDeferred(posted = false, notificationsUsable = false))
        assertFalse(SmsReceiver.shouldRequeueDeferred(posted = true, notificationsUsable = true))
        assertFalse(SmsReceiver.shouldRequeueDeferred(posted = true, notificationsUsable = false))
    }

    @Test
    fun testShouldRequeueAfterFailureBounded() {
        assertTrue(SmsReceiver.shouldRequeueAfterFailure(0))
        assertTrue(SmsReceiver.shouldRequeueAfterFailure(SmsReceiver.MAX_DEFERRED_FAILURES - 1))
        assertFalse(SmsReceiver.shouldRequeueAfterFailure(SmsReceiver.MAX_DEFERRED_FAILURES))
        assertFalse(SmsReceiver.shouldRequeueAfterFailure(SmsReceiver.MAX_DEFERRED_FAILURES + 5))
    }

    @Test
    fun testPendingAnalysisAttemptsDefaultZero() {
        val pending = SmsReceiver.Companion.PendingAnalysis("msg-1", "sender", "body", 123L)
        assertEquals(0, pending.attempts)
        val retried = pending.copy(attempts = 1)
        assertEquals(1, retried.attempts)
    }

    @Test
    fun testInMemoryFallbackIsMonotonicAndAfterHandout() {
        val first = SmsReceiver.nextInMemoryNotificationId()
        val second = SmsReceiver.nextInMemoryNotificationId()
        assertTrue(first >= 1)
        assertEquals(SmsReceiver.nextNotificationIdAfter(first), second)
        // The pure rule agrees: after `first`, the resolver also moves past it.
        assertEquals(second, SmsReceiver.resolveNextNotificationId(first, first))
    }

    @Test
    fun testNotificationsUsablePureRules() {
        assertTrue(SmsReceiver.notificationsUsable(permissionGranted = true, notificationsEnabled = true, channelImportance = 4))
        assertTrue(SmsReceiver.notificationsUsable(permissionGranted = true, notificationsEnabled = true, channelImportance = null))
        assertFalse(SmsReceiver.notificationsUsable(permissionGranted = false, notificationsEnabled = true, channelImportance = 4))
        assertFalse(SmsReceiver.notificationsUsable(permissionGranted = true, notificationsEnabled = false, channelImportance = 4))
        assertFalse(SmsReceiver.notificationsUsable(permissionGranted = true, notificationsEnabled = true, channelImportance = 0))
        assertFalse(SmsReceiver.notificationsUsable(permissionGranted = false, notificationsEnabled = false, channelImportance = 0))
    }
}
