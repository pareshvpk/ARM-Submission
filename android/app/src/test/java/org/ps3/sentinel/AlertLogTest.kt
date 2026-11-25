package org.ps3.sentinel

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.ps3.sentinel.sms.AlertEntry
import org.ps3.sentinel.sms.AlertLog
import org.ps3.sentinel.sms.EncryptedBody
import org.ps3.sentinel.sms.PendingCipher
import java.util.Base64

class AlertLogTest {

    private class FakeCipher : PendingCipher {
        private var counter = 1
        override fun encrypt(plaintext: ByteArray): EncryptedBody {
            val iv = ByteArray(12) { (counter++).toByte() }
            val cipher = plaintext.map { (it.toInt() xor 0x5A).toByte() }.toByteArray()
            return EncryptedBody(ciphertext = cipher, iv = iv)
        }

        override fun decrypt(body: EncryptedBody): ByteArray {
            return body.ciphertext.map { (it.toInt() xor 0x5A).toByte() }.toByteArray()
        }
    }

    @Before
    fun setUp() {
        AlertLog.cipher = FakeCipher()
    }

    @Test
    fun testNewestFirst() {
        val entry1 = AlertEntry(
            id = "msg-old",
            timeMillis = 1000L,
            level = "medium",
            label = "UNWANTED",
            sender = "+11111"
        )
        val entry2 = AlertEntry(
            id = "msg-new",
            timeMillis = 2000L,
            level = "high",
            label = "SCAM",
            sender = "+22222"
        )

        // Newest entry at head of the list
        val list = listOf(entry2, entry1)
        val json = AlertLog.toJson(list)
        val parsed = AlertLog.fromJson(json)

        assertEquals(2, parsed.size)
        assertEquals("msg-new", parsed[0].id)
        assertEquals("msg-old", parsed[1].id)
        assertEquals(2000L, parsed[0].timeMillis)
        assertEquals(1000L, parsed[1].timeMillis)
    }

    @Test
    fun testCap50() {
        val entries = (1..60).map { i ->
            AlertEntry(
                id = "alert-$i",
                timeMillis = i * 1000L,
                level = if (i % 2 == 0) "high" else "medium",
                label = "SCAM",
                sender = "sender-$i"
            )
        }

        val trimmed = AlertLog.trim(entries, AlertLog.MAX_ENTRIES)
        assertEquals(50, trimmed.size)
        // Keeps the first 50 items (newest at the front)
        assertEquals("alert-1", trimmed.first().id)
        assertEquals("alert-50", trimmed.last().id)
    }

    @Test
    fun testClear() {
        val entries = listOf(
            AlertEntry("id-1", 1000L, "high", "SCAM", "sender1"),
            AlertEntry("id-2", 2000L, "medium", "UNWANTED", "sender2")
        )
        val json = AlertLog.toJson(entries)
        assertEquals(2, AlertLog.fromJson(json).size)

        val cleared = emptyList<AlertEntry>()
        val clearedJson = AlertLog.toJson(cleared)
        assertEquals("[]", clearedJson)
        assertTrue(AlertLog.fromJson(clearedJson).isEmpty())
        assertTrue(AlertLog.fromJson("").isEmpty())
    }

    @Test
    fun testNoTextFieldInJson() {
        val entry = AlertEntry(
            id = "id-check",
            timeMillis = 1700000000000L,
            level = "high",
            label = "SCAM",
            sender = "+9876543210"
        )

        val json = AlertLog.toJson(listOf(entry))
        val array = JSONArray(json)
        assertEquals(1, array.length())

        val obj = array.getJSONObject(0)
        // Verify no message body / text field is persisted
        assertFalse("JSON must not contain text field", obj.has("text"))
        assertFalse("JSON must not contain body field", obj.has("body"))
        assertFalse("JSON must not contain message field", obj.has("message"))
        assertFalse("JSON must not contain content field", obj.has("content"))
        // FIX 2: the sender is encrypted, so no plaintext sender key remains
        assertFalse("JSON must not contain a plaintext sender", obj.has("sender"))
        assertFalse("JSON must not contain the sender", json.contains(entry.sender))

        // Verify required metadata fields exist
        assertTrue(obj.has("id"))
        assertTrue(obj.has("timeMillis"))
        assertTrue(obj.has("level"))
        assertTrue(obj.has("label"))
        assertTrue(obj.has("sender_ciphertext"))
        assertTrue(obj.has("sender_iv"))
        assertTrue(obj.has("kind"))
        assertEquals(7, obj.length())
    }

    @Test
    fun testSenderIsEncryptedAndDecryptedOnLoad() {
        val sender = "+919876543210"
        val entry = AlertEntry(
            id = "alert-sender-enc",
            timeMillis = 1700000000000L,
            level = "high",
            label = "SCAM",
            sender = sender,
            message = "Your parcel is held. Pay the fee."
        )

        val json = AlertLog.toJson(listOf(entry))

        assertFalse("JSON must not contain the plaintext sender", json.contains(sender))
        val obj = JSONArray(json).getJSONObject(0)
        assertFalse(obj.has("sender"))
        assertTrue(obj.has("sender_ciphertext"))
        assertTrue(obj.has("sender_iv"))
        // The sender is encrypted with the same cipher as the body.
        val decrypted = FakeCipher().decrypt(
            EncryptedBody(
                Base64.getDecoder().decode(obj.getString("sender_ciphertext")),
                Base64.getDecoder().decode(obj.getString("sender_iv"))
            )
        )
        assertEquals(sender, String(decrypted, Charsets.UTF_8))

        val loaded = AlertLog.fromJson(json)
        assertEquals(1, loaded.size)
        assertEquals(sender, loaded[0].sender)
        assertEquals("Your parcel is held. Pay the fee.", loaded[0].message)
    }

    @Test
    fun testPlaintextSenderStillLoadsFromOldEntries() {
        val oldJson = """
            [{"id":"old-2","timeMillis":1700000000000,"level":"medium","label":"UNWANTED",
              "sender":"+11111","kind":"safe","ciphertext":"","iv":""}]
        """.trimIndent()

        val loaded = AlertLog.fromJson(oldJson)

        assertEquals(1, loaded.size)
        assertEquals("+11111", loaded[0].sender)
        assertEquals(AlertLog.KIND_SAFE, loaded[0].kind)
    }

    @Test
    fun testNullCipherFallsBackToPlaintextSender() {
        val entry = AlertEntry(
            id = "no-cipher",
            timeMillis = 1700000000000L,
            level = "high",
            label = "SCAM",
            sender = "+919876543210",
            message = "Body is dropped without a cipher"
        )

        val json = AlertLog.toJson(listOf(entry), customCipher = null)
        val obj = JSONArray(json).getJSONObject(0)

        assertEquals("+919876543210", obj.getString("sender"))
        assertFalse(obj.has("sender_ciphertext"))
        assertFalse(obj.has("ciphertext"))

        val loaded = AlertLog.fromJson(json, customCipher = null)
        assertEquals(1, loaded.size)
        assertEquals("+919876543210", loaded[0].sender)
        assertNull(loaded[0].message)
    }

    @Test
    fun testCipherFailureFallsBackToPlaintextSender() {
        val broken = object : PendingCipher {
            override fun encrypt(plaintext: ByteArray): EncryptedBody = throw IllegalStateException("no key")
            override fun decrypt(body: EncryptedBody): ByteArray = throw IllegalStateException("no key")
        }
        val entry = AlertEntry(
            id = "broken-cipher",
            timeMillis = 1700000000000L,
            level = "high",
            label = "SCAM",
            sender = "+919876543210",
            message = "Body is dropped when encryption fails"
        )

        val json = AlertLog.toJson(listOf(entry), customCipher = broken)
        val obj = JSONArray(json).getJSONObject(0)

        assertEquals("+919876543210", obj.getString("sender"))
        assertFalse(obj.has("sender_ciphertext"))
        assertFalse(obj.has("ciphertext"))
    }

    @Test
    fun testEncryptedMessageInJsonAndDecryptedOnLoad() {
        val plainText = "Refund of Rs 4,999 is pending. Enter your UPI PIN to receive it."
        val entry = AlertEntry(
            id = "alert-enc",
            timeMillis = 1700000000000L,
            level = "high",
            label = "SCAM",
            sender = "+919876543210",
            message = plainText
        )

        val json = AlertLog.toJson(listOf(entry))
        // Plain text must not appear anywhere in the serialized JSON string
        assertFalse("JSON must not contain the plain text", json.contains(plainText))
        assertFalse("JSON must not contain partial plain text", json.contains("Refund"))
        assertFalse("JSON must not contain UPI PIN", json.contains("UPI PIN"))

        val array = JSONArray(json)
        assertEquals(1, array.length())
        val obj = array.getJSONObject(0)
        assertTrue(obj.has("ciphertext"))
        assertTrue(obj.has("iv"))
        assertFalse(obj.has("message"))
        assertFalse(obj.has("text"))
        assertFalse(obj.has("body"))

        // Decrypt on load
        val loaded = AlertLog.fromJson(json)
        assertEquals(1, loaded.size)
        assertEquals(plainText, loaded[0].message)
    }

    @Test
    fun testOldEntriesWithoutTextStillLoad() {
        val oldJson = """
            [{"id":"old-1","timeMillis":1700000000000,"level":"medium","label":"UNWANTED","sender":"+11111"}]
        """.trimIndent()
        val loaded = AlertLog.fromJson(oldJson)
        assertEquals(1, loaded.size)
        assertEquals("old-1", loaded[0].id)
        assertNull(loaded[0].message)
    }

    @Test
    fun testKindSeparation() {
        val scamEntry = AlertEntry(
            id = "scam-1",
            timeMillis = 2000L,
            level = "high",
            label = "SCAM",
            sender = "+11111",
            message = "Scam text",
            kind = AlertLog.KIND_SCAM
        )
        val safeEntry = AlertEntry(
            id = "safe-1",
            timeMillis = 1000L,
            level = "low",
            label = "HAM",
            sender = "+22222",
            message = "Safe text",
            kind = AlertLog.KIND_SAFE
        )

        val json = AlertLog.toJson(listOf(scamEntry, safeEntry))
        val loaded = AlertLog.fromJson(json)

        assertEquals(2, loaded.size)
        assertEquals(AlertLog.KIND_SCAM, loaded[0].kind)
        assertEquals(AlertLog.KIND_SAFE, loaded[1].kind)
        assertEquals("Scam text", loaded[0].message)
        assertEquals("Safe text", loaded[1].message)

        val scamOnly = loaded.filter { it.kind == AlertLog.KIND_SCAM }
        val safeOnly = loaded.filter { it.kind == AlertLog.KIND_SAFE }
        assertEquals(1, scamOnly.size)
        assertEquals(1, safeOnly.size)
        assertEquals("scam-1", scamOnly[0].id)
        assertEquals("safe-1", safeOnly[0].id)
    }

    @Test
    fun test50PerKindCap() {
        val scamEntries = (1..60).map { i ->
            AlertEntry(
                id = "scam-$i",
                timeMillis = 10000L - i,
                level = "high",
                label = "SCAM",
                sender = "sender-scam-$i",
                kind = AlertLog.KIND_SCAM
            )
        }
        val safeEntries = (1..60).map { i ->
            AlertEntry(
                id = "safe-$i",
                timeMillis = 10000L - i,
                level = "low",
                label = "HAM",
                sender = "sender-safe-$i",
                kind = AlertLog.KIND_SAFE
            )
        }

        // Interleave scam and safe
        val mixed = mutableListOf<AlertEntry>()
        for (i in 0 until 60) {
            mixed.add(scamEntries[i])
            mixed.add(safeEntries[i])
        }

        val trimmed = AlertLog.trim(mixed, AlertLog.MAX_ENTRIES)
        assertEquals(100, trimmed.size)

        val trimmedScam = trimmed.filter { it.kind == AlertLog.KIND_SCAM }
        val trimmedSafe = trimmed.filter { it.kind == AlertLog.KIND_SAFE }

        assertEquals(50, trimmedScam.size)
        assertEquals(50, trimmedSafe.size)

        // Newest 50 preserved for each kind
        assertEquals("scam-1", trimmedScam.first().id)
        assertEquals("scam-50", trimmedScam.last().id)
        assertEquals("safe-1", trimmedSafe.first().id)
        assertEquals("safe-50", trimmedSafe.last().id)
    }

    @Test
    fun testOldEntriesWithoutKindLoadAsScam() {
        val oldJson = """
            [{"id":"old-entry","timeMillis":1700000000000,"level":"high","label":"SCAM","sender":"+11111"}]
        """.trimIndent()
        val loaded = AlertLog.fromJson(oldJson)
        assertEquals(1, loaded.size)
        assertEquals("old-entry", loaded[0].id)
        assertEquals(AlertLog.KIND_SCAM, loaded[0].kind)
    }

    @Test
    fun testRoutineSkippedNeverRecorded() {
        // Pure decision function tests
        // 1. Routine OTP / bank alerts are skipped -> shouldRecord must be false
        assertTrue(AlertLog.shouldRecord(isRoutineSkipped = false, hasModelAnswer = true))
        assertFalse(AlertLog.shouldRecord(isRoutineSkipped = true, hasModelAnswer = true))
        assertFalse(AlertLog.shouldRecord(isRoutineSkipped = true, hasModelAnswer = false))

        // 2. Rules-only verdict without model answer -> shouldRecord must be false
        assertFalse(AlertLog.shouldRecord(isRoutineSkipped = false, hasModelAnswer = false))

        // 3. Sender & body based routine skip evaluation
        // OTP message with bank header
        assertFalse(AlertLog.shouldRecord(
            sender = "VK-HDFCBK",
            body = "123456 is your secret OTP for txn of INR 500.00 at XYZ. Do not share it.",
            hasModelAnswer = true
        ))

        // Bank balance / debit alert with header
        assertFalse(AlertLog.shouldRecord(
            sender = "AX-AXISBK",
            body = "A/C *1234 debited by INR 1,500.00 on 22-Nov-26. Avail Bal: INR 12,345.00.",
            hasModelAnswer = true
        ))

        // Normal analysed message with model answer
        assertTrue(AlertLog.shouldRecord(
            sender = "+919876543210",
            body = "Your power supply will be disconnected tonight at 9:30 PM. Call this number.",
            hasModelAnswer = true
        ))

        // Normal analysed safe message with model answer
        assertTrue(AlertLog.shouldRecord(
            sender = "+919876543210",
            body = "Hey, are we still meeting for lunch tomorrow at 1?",
            hasModelAnswer = true
        ))
    }
}
