package org.ps3.sentinel.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Base64
import java.util.concurrent.atomic.AtomicLong

class PendingMessageStoreTest {

    private fun tempDir(): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "pendingstore-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    private class FakeCipher(private val counter: AtomicLong = AtomicLong(0)) : PendingCipher {
        override fun encrypt(plaintext: ByteArray): EncryptedBody {
            val iv = ByteArray(12) { counter.incrementAndGet().toByte() }
            val cipher = plaintext.reversedArray() + ByteArray(8) { 0x55 }
            return EncryptedBody(ciphertext = cipher, iv = iv)
        }

        override fun decrypt(body: EncryptedBody): ByteArray {
            val stripped = body.ciphertext.dropLast(8).toByteArray()
            return stripped.reversedArray()
        }
    }

    @Test
    fun testRoundTripPutTake() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-1", "Your OTP is 123456")
        assertEquals("Your OTP is 123456", store.peek("msg-1"))
        // Plaintext must not appear on disk.
        val raw = File(dir, PendingMessageStore.STORE_FILE_NAME).readText(Charsets.UTF_8)
        assertFalse("cipher file must not contain plaintext body", raw.contains("Your OTP is 123456"))
        assertEquals("Your OTP is 123456", store.take("msg-1"))
    }

    @Test
    fun testCapDropsOldest() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        for (i in 1..21) {
            now.set(1_000_000L + i * 1000L)
            store.put("msg-$i", "body-$i")
        }
        assertEquals(PendingMessageStore.MAX_ENTRIES, store.size())
        assertNull("oldest entry dropped", store.peek("msg-1"))
        assertEquals("body-21", store.peek("msg-21"))
        assertEquals("body-2", store.peek("msg-2"))
    }

    @Test
    fun testCapKeepsNewestByInsertionOrderWhenClockMovesBackwards() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        for (i in 1..PendingMessageStore.MAX_ENTRIES) {
            now.set(1_000_000L + i * 1000L)
            store.put("msg-$i", "body-$i")
        }
        now.set(500_000L)
        store.put("msg-new", "new body")
        assertEquals(PendingMessageStore.MAX_ENTRIES, store.size())
        assertEquals("new body", store.peek("msg-new"))
        assertNull("oldest inserted id evicted", store.peek("msg-1"))
        assertEquals("body-2", store.peek("msg-2"))
    }

    @Test
    fun testExpiredEntriesRemovedOnWriteAndRead() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-old", "old body")
        now.set(1_000_000L + PendingMessageStore.MAX_AGE_MS + 1L)
        assertNull("expired id returns null on read", store.peek("msg-old"))
        assertEquals(0, store.size())
        val now2 = AtomicLong(1_000_000L)
        val store2 = PendingMessageStore(tempDir(), FakeCipher(), clock = { now2.get() })
        store2.put("msg-old", "old body")
        now2.set(1_000_000L + PendingMessageStore.MAX_AGE_MS + 1L)
        store2.put("msg-new", "new body")
        assertNull("expired entry removed on write", store2.peek("msg-old"))
        assertEquals("new body", store2.peek("msg-new"))
        assertEquals(1, store2.size())
    }

    @Test
    fun testDeleteOnRead() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-1", "secret body")
        assertEquals("secret body", store.peek("msg-1"))
        assertEquals(1, store.size())
        assertEquals("secret body", store.take("msg-1"))
        assertEquals(0, store.size())
        assertNull("second take returns null after delete", store.take("msg-1"))
    }

    @Test
    fun testMissingIdReturnsNull() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        assertNull(store.take("msg-missing"))
        assertNull(store.peek("msg-missing"))
        store.put("msg-a", "body-a")
        assertNull("unknown id still null after unrelated put", store.take("msg-b"))
        assertEquals("body-a", store.take("msg-a"))
    }

    @Test
    fun testPutNeverOverwritesExistingId() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-102", "first body")
        store.put("msg-102", "second body")
        assertEquals("existing entry is kept", "first body", store.peek("msg-102"))
        assertEquals(1, store.size())
    }

    @Test
    fun testTwoStoresSimulatingTwoProcessesNeverShareId() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val firstProcess = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val secondProcess = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val firstId = SmsReceiver.nextMessageId()
        firstProcess.put(firstId, "first process body")
        val secondId = SmsReceiver.nextMessageId()
        secondProcess.put(secondId, "second process body")
        assertFalse("ids unique across processes", firstId == secondId)
        assertEquals("first process body", firstProcess.peek(firstId))
        assertEquals("second process body", secondProcess.peek(secondId))
        assertEquals(2, firstProcess.size())
    }

    @Test
    fun testSecondProcessPutWithExistingIdKeepsFirstBody() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val firstProcess = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val secondProcess = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        firstProcess.put("msg-102", "first process body")
        secondProcess.put("msg-102", "second process body")
        assertEquals("reused id keeps first body", "first process body", secondProcess.peek("msg-102"))
    }

    @Test
    fun testAtomicWriteKeepsOldFileWhenTempWriteThrows() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-1", "old body")
        val tempFile = File(dir, PendingMessageStore.STORE_FILE_NAME + PendingMessageStore.TEMP_FILE_SUFFIX)
        assertFalse("temp file moved into place by the first write", tempFile.exists())
        check(tempFile.mkdir()) { "Could not create temp blocking directory" }
        var threw = false
        try {
            store.put("msg-2", "new body")
        } catch (_: Exception) {
            threw = true
        }
        assertTrue("put must fail when the temp write fails", threw)
        tempFile.delete()
        assertEquals("old body survives a failed temp write", "old body", store.peek("msg-1"))
        assertNull("failed write adds no entry", store.peek("msg-2"))
        assertFalse(tempFile.exists())
    }

    @Test
    fun testSuccessfulWriteLeavesNoTempFile() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-1", "body")
        val tempFile = File(dir, PendingMessageStore.STORE_FILE_NAME + PendingMessageStore.TEMP_FILE_SUFFIX)
        assertFalse("temp file renamed over the store file", tempFile.exists())
        assertTrue("store file written", File(dir, PendingMessageStore.STORE_FILE_NAME).isFile)
    }

    @Test
    fun testCorruptFileRenamedToCorruptAndPutKeepsWorking() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val storeFile = File(dir, PendingMessageStore.STORE_FILE_NAME)
        val corruptFile = File(dir, PendingMessageStore.STORE_FILE_NAME + PendingMessageStore.CORRUPT_FILE_SUFFIX)
        corruptFile.writeText("old corrupt marker", Charsets.UTF_8)
        storeFile.writeText("not json {{{ corrupt", Charsets.UTF_8)
        store.put("msg-new", "new body")
        assertTrue(".corrupt file created", corruptFile.isFile)
        assertEquals("corrupt bytes preserved and old .corrupt replaced", "not json {{{ corrupt",
            corruptFile.readText(Charsets.UTF_8))
        assertEquals("following put keeps working", "new body", store.peek("msg-new"))
        assertEquals(1, store.size())
    }

    @Test
    fun testExpiredCorruptFileDeletedOnNextRead() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        val corruptFile = File(dir, PendingMessageStore.STORE_FILE_NAME + PendingMessageStore.CORRUPT_FILE_SUFFIX)
        corruptFile.writeText("old corrupt", Charsets.UTF_8)
        corruptFile.setLastModified(now.get())
        assertEquals(0, store.size())
        assertTrue("fresh corrupt kept", corruptFile.isFile)
        now.set(now.get() + PendingMessageStore.MAX_AGE_MS + 1L)
        corruptFile.setLastModified(now.get() - PendingMessageStore.MAX_AGE_MS - 1L)
        assertEquals(0, store.size())
        assertFalse("expired corrupt deleted", corruptFile.exists())
    }

    @Test
    fun testTakeKeepsEntryWhenDecryptFails() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val good = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        good.put("msg-1", "secret body")
        val failing = PendingMessageStore(dir, FailingCipher(), clock = { now.get() })
        assertNull("decrypt failure returns null", failing.take("msg-1"))
        assertEquals("entry kept after decrypt failure", 1, failing.size())
        assertEquals("entry still readable with good cipher", "secret body", good.peek("msg-1"))
        assertEquals("secret body", good.take("msg-1"))
        assertEquals(0, good.size())
    }

    @Test
    fun testDeferredAndNotificationIdRoundTrip() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-a", "deferred body", deferred = true)
        store.setNotificationId("msg-a", 42)
        assertEquals(42, store.notificationIdOf("msg-a"))
        assertEquals(listOf("msg-a"), store.deferredIds())
        store.markDeferredDone("msg-a")
        assertTrue("markDeferredDone clears deferred", store.deferredIds().isEmpty())
        assertEquals("notification id survives markDeferredDone", 42, store.notificationIdOf("msg-a"))
        val second = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        assertEquals(42, second.notificationIdOf("msg-a"))
        assertTrue("deferred done persists across store instances", second.deferredIds().isEmpty())
        assertEquals("deferred body", second.peek("msg-a"))
    }

    @Test
    fun testOldEntriesWithoutNewFieldsLoadWithDefaults() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val cipher = FakeCipher()
        val encrypted = cipher.encrypt("old body".toByteArray(Charsets.UTF_8))
        val array = JSONArray()
        val item = JSONObject()
        item.put("id", "msg-old")
        item.put("received_ms", 1_000_000L)
        item.put("ciphertext", Base64.getEncoder().encodeToString(encrypted.ciphertext))
        item.put("iv", Base64.getEncoder().encodeToString(encrypted.iv))
        array.put(item)
        File(dir, PendingMessageStore.STORE_FILE_NAME).writeText(array.toString(), Charsets.UTF_8)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        assertEquals("old entry body readable", "old body", store.peek("msg-old"))
        assertEquals("old entry defaults to no notification", 0, store.notificationIdOf("msg-old"))
        assertTrue("old entry defaults to not deferred", store.deferredIds().isEmpty())
    }

    @Test
    fun testDeferredIdsListsOnlyDeferredEntries() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        store.put("msg-a", "body-a", deferred = true)
        store.put("msg-b", "body-b", deferred = false)
        store.put("msg-c", "body-c")
        assertEquals(listOf("msg-a"), store.deferredIds())
        store.markDeferredDone("msg-a")
        assertTrue("no deferred ids after markDeferredDone", store.deferredIds().isEmpty())
    }

    @Test
    fun testHasEntryDistinguishesExistingFromMissing() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val store = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        assertFalse("blank id has no entry", store.hasEntry(""))
        assertFalse("missing id has no entry", store.hasEntry("msg-missing"))
        store.put("msg-present", "body", deferred = true)
        assertTrue("stored id has an entry", store.hasEntry("msg-present"))
        store.delete("msg-present")
        assertFalse("deleted id has no entry", store.hasEntry("msg-present"))
    }

    @Test
    fun testHasEntryTrueWhenUndecryptableButStored() {
        val dir = tempDir()
        val now = AtomicLong(1_000_000L)
        val good = PendingMessageStore(dir, FakeCipher(), clock = { now.get() })
        good.put("msg-undecryptable", "secret body", deferred = true)
        val failing = PendingMessageStore(dir, FailingCipher(), clock = { now.get() })
        assertNull("decrypt failure returns null", failing.peek("msg-undecryptable"))
        assertTrue("durable entry still exists despite decrypt failure", failing.hasEntry("msg-undecryptable"))
        failing.delete("msg-undecryptable")
        assertFalse("deleted after hasEntry true", failing.hasEntry("msg-undecryptable"))
        assertTrue("deferred ids cleared after delete", failing.deferredIds().isEmpty())
    }

    private class FailingCipher : PendingCipher {
        override fun encrypt(plaintext: ByteArray): EncryptedBody =
            EncryptedBody(plaintext, ByteArray(12))
        override fun decrypt(body: EncryptedBody): ByteArray {
            throw RuntimeException("decrypt fails")
        }
    }
}
