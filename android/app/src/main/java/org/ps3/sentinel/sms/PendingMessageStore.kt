/**
 * Encrypted persistent storage for pending and alerted SMS message bodies.
 * Uses AES-256-GCM backed by the Android KeyStore to safely retain messages across process death.
 * Enforces size limits and 24-hour expiration without leaving plaintext bodies on disk.
 */
package org.ps3.sentinel.sms

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Ciphertext plus the per-message IV needed to decrypt it. */
data class EncryptedBody(val ciphertext: ByteArray, val iv: ByteArray)

/**
 * Purpose:  Encrypts and decrypts pending SMS bodies for cold-start delivery.
 * Owns:     Nothing. Delegates to a PendingCipher.
 * Lifetime: Process
 * Thread:   any — implementations must be thread-safe.
 */
interface PendingCipher {
    /** Encrypts the plaintext byte array and returns the ciphertext with its initialization vector. */
    fun encrypt(plaintext: ByteArray): EncryptedBody

    /** Decrypts the given ciphertext using the initialization vector in [body]. */
    fun decrypt(body: EncryptedBody): ByteArray
}

/**
 * Purpose:  AES-256-GCM with a Keystore key never exported.
 * Owns:     The ps3_pending_sms Keystore key, created on first use.
 * Lifetime: Process
 * Thread:   any — Cipher instances are created per call.
 */
class KeystorePendingCipher : PendingCipher {

    companion object {
        const val KEY_ALIAS: String = "ps3_pending_sms"
        private const val GCM_TAG_BITS: Int = 128
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore")
        store.load(null)
        if (!store.containsAlias(KEY_ALIAS)) {
            val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            val spec = KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
            generator.init(spec)
            generator.generateKey()
        }
        return store.getKey(KEY_ALIAS, null) as SecretKey
    }

    /** Encrypts [plaintext] with AES-GCM using the non-exportable Android KeyStore key. */
    override fun encrypt(plaintext: ByteArray): EncryptedBody {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return EncryptedBody(ciphertext = cipher.doFinal(plaintext), iv = cipher.iv)
    }

    /** Decrypts [body] with AES-GCM using the non-exportable Android KeyStore key. */
    override fun decrypt(body: EncryptedBody): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(GCM_TAG_BITS, body.iv))
        return cipher.doFinal(body.ciphertext)
    }
}

/**
 * Purpose:  Persists pending SMS bodies across process death.
 * Owns:     One JSON file inside the no-backup files directory.
 * Lifetime: Process
 * Thread:   single — all access is synchronized.
 */
class PendingMessageStore internal constructor(
    private val dir: File,
    private val cipher: PendingCipher,
    private val clock: () -> Long = { System.currentTimeMillis() }
) {

    companion object {
        const val STORE_FILE_NAME: String = "pending_sms.json"
        const val TEMP_FILE_SUFFIX: String = ".tmp"
        const val CORRUPT_FILE_SUFFIX: String = ".corrupt"
        // 20 — matches the in-memory fast-path cap; past this the oldest entry is the
        // least likely to still matter and dropping it bounds disk use.
        const val MAX_ENTRIES: Int = 20
        // 24 h — a notification tap after a day is almost certainly stale; keeping
        // ciphertext longer only widens the window if the device is compromised.
        const val MAX_AGE_MS: Long = 24L * 60L * 60L * 1000L

        private val lock = Any()
        private var shared: PendingMessageStore? = null

        /** Shared instance backed by noBackupFilesDir and the Keystore cipher. */
        fun instance(context: Context): PendingMessageStore = synchronized(lock) {
            val current = shared
            if (current != null) {
                return current
            }
            val base = context.applicationContext.noBackupFilesDir ?: context.applicationContext.filesDir
            val created = PendingMessageStore(base, KeystorePendingCipher())
            shared = created
            created
        }
    }

    private data class Entry(
        val id: String,
        val receivedMs: Long,
        val ciphertext: ByteArray,
        val iv: ByteArray,
        val deferred: Boolean = false,
        val notificationId: Int = 0
    )

    private val storeFile: File get() = File(dir, STORE_FILE_NAME)

    /** Stores [body] under [id], pruning expired entries and enforcing the cap. */
    @Synchronized
    fun put(id: String, body: String, deferred: Boolean = false) {
        if (id.isBlank()) {
            return
        }
        val now = clock()
        val entries = loadEntries()
        val live = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (live.any { it.id == id }) {
            if (live.size != entries.size) {
                saveEntries(live)
            }
            return
        }
        val encrypted = cipher.encrypt(body.toByteArray(Charsets.UTF_8))
        val updated = live.toMutableList()
        updated.add(
            Entry(
                id = id,
                receivedMs = now,
                ciphertext = encrypted.ciphertext,
                iv = encrypted.iv,
                deferred = deferred,
                notificationId = 0
            )
        )
        saveEntries(capEntries(updated))
    }

    /** Returns the body for [id] without deleting it, pruning expired entries first. */
    @Synchronized
    fun peek(id: String): String? {
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (pruned.size != entries.size) {
            saveEntries(pruned)
        }
        val entry = pruned.firstOrNull { it.id == id } ?: return null
        return try {
            String(cipher.decrypt(EncryptedBody(entry.ciphertext, entry.iv)), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    /** Returns the body for [id] and deletes the entry, pruning expired entries first. */
    @Synchronized
    fun take(id: String): String? {
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        val entry = pruned.firstOrNull { it.id == id } ?: run {
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return null
        }
        val body = try {
            String(cipher.decrypt(EncryptedBody(entry.ciphertext, entry.iv)), Charsets.UTF_8)
        } catch (_: Exception) {
            // Decrypt failed: keep the entry so it expires by age instead of being lost.
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return null
        }
        val remaining = pruned.filter { it.id != id }
        saveEntries(remaining)
        return body
    }

    /** Deletes [id] without decrypting, for messages that never alerted. */
    @Synchronized
    fun delete(id: String) {
        if (id.isBlank()) {
            return
        }
        val now = clock()
        val entries = loadEntries()
        val kept = entries.filter { it.id != id && now - it.receivedMs <= MAX_AGE_MS }
        if (kept.size != entries.size) {
            saveEntries(kept)
        }
    }

    /** Number of live entries after pruning expired ones. */
    @Synchronized
    fun size(): Int {
        val now = clock()
        val loaded = loadEntries()
        val entries = loaded.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (entries.size != loaded.size) {
            saveEntries(entries)
        }
        return entries.size
    }

    /** Marks [id] as settled (full analysis no longer owed) while keeping the body. */
    @Synchronized
    fun markDeferredDone(id: String) {
        if (id.isBlank()) {
            return
        }
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        val index = pruned.indexOfFirst { it.id == id }
        if (index < 0) {
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return
        }
        val current = pruned[index]
        if (!current.deferred) {
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return
        }
        val updated = pruned.toMutableList()
        updated[index] = current.copy(deferred = false)
        saveEntries(updated)
    }

    /** Stores the posted notification id for [id], if the entry exists. */
    @Synchronized
    fun setNotificationId(id: String, notificationId: Int) {
        if (id.isBlank() || notificationId <= 0) {
            return
        }
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        val index = pruned.indexOfFirst { it.id == id }
        if (index < 0) {
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return
        }
        val current = pruned[index]
        if (current.notificationId == notificationId) {
            if (pruned.size != entries.size) {
                saveEntries(pruned)
            }
            return
        }
        val updated = pruned.toMutableList()
        updated[index] = current.copy(notificationId = notificationId)
        saveEntries(updated)
    }

    /** Returns the stored notification id for [id], or 0 when none was posted. */
    @Synchronized
    fun notificationIdOf(id: String): Int {
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (pruned.size != entries.size) {
            saveEntries(pruned)
        }
        return pruned.firstOrNull { it.id == id }?.notificationId ?: 0
    }

    /** Returns true when [id] has a live entry without decrypting; false for blank or missing. */
    @Synchronized
    fun hasEntry(id: String): Boolean {
        if (id.isBlank()) {
            return false
        }
        val now = clock()
        val entries = loadEntries()
        val pruned = entries.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (pruned.size != entries.size) {
            saveEntries(pruned)
        }
        return pruned.any { it.id == id }
    }

    /** Returns ids whose full analysis is still owed, after pruning expired ones. */
    @Synchronized
    fun deferredIds(): List<String> {
        val now = clock()
        val loaded = loadEntries()
        val entries = loaded.filter { now - it.receivedMs <= MAX_AGE_MS }
        if (entries.size != loaded.size) {
            saveEntries(entries)
        }
        return entries.filter { it.deferred }.map { it.id }
    }

    private fun capEntries(entries: MutableList<Entry>): List<Entry> {
        if (entries.size <= MAX_ENTRIES) {
            return entries
        }
        return entries.subList(entries.size - MAX_ENTRIES, entries.size)
    }

    private fun quarantineCorruptFile() {
        val corruptFile = File(dir, STORE_FILE_NAME + CORRUPT_FILE_SUFFIX)
        try {
            Files.move(storeFile.toPath(), corruptFile.toPath(), StandardCopyOption.REPLACE_EXISTING)
        } catch (_: Exception) {
            try {
                storeFile.delete()
            } catch (_: Exception) {
                // Quarantine must not hide the original read/parse failure.
            }
        }
        try {
            Log.w(TAG, "PendingMessageStore: corrupt pending file quarantined")
        } catch (_: Exception) {
            // Logging must not break the store on stubbed platforms.
        }
    }

    private fun pruneCorruptFileIfExpired() {
        val corruptFile = File(dir, STORE_FILE_NAME + CORRUPT_FILE_SUFFIX)
        if (!corruptFile.isFile) return
        try {
            val age = clock() - corruptFile.lastModified()
            if (age > MAX_AGE_MS) {
                corruptFile.delete()
            }
        } catch (_: Exception) {
            // Pruning must not break the store.
        }
    }

    private fun loadEntries(): List<Entry> {
        pruneCorruptFileIfExpired()
        val file = storeFile
        if (!file.isFile) {
            return emptyList()
        }
        val text = try {
            file.readText(Charsets.UTF_8)
        } catch (_: Exception) {
            quarantineCorruptFile()
            return emptyList()
        }
        if (text.isBlank()) {
            return emptyList()
        }
        val array = try {
            JSONArray(text)
        } catch (_: Exception) {
            quarantineCorruptFile()
            return emptyList()
        }
        val result = ArrayList<Entry>(array.length())
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id", "")
            if (id.isBlank()) {
                continue
            }
            val receivedMs = item.optLong("received_ms", 0L)
            val cipherText = item.optString("ciphertext", "")
            val ivText = item.optString("iv", "")
            if (cipherText.isEmpty() || ivText.isEmpty()) {
                continue
            }
            val ciphertext = try {
                Base64.getDecoder().decode(cipherText)
            } catch (_: IllegalArgumentException) {
                continue
            }
            val iv = try {
                Base64.getDecoder().decode(ivText)
            } catch (_: IllegalArgumentException) {
                continue
            }
            val deferred = item.optBoolean("deferred", false)
            val notificationId = item.optInt("notificationId", 0)
            result.add(
                Entry(
                    id = id,
                    receivedMs = receivedMs,
                    ciphertext = ciphertext,
                    iv = iv,
                    deferred = deferred,
                    notificationId = notificationId
                )
            )
        }
        return result
    }

    private fun saveEntries(entries: List<Entry>) {
        dir.mkdirs()
        val payload = buildPayload(entries)
        val tempFile = File(dir, STORE_FILE_NAME + TEMP_FILE_SUFFIX)
        try {
            FileOutputStream(tempFile).use { output ->
                output.write(payload.toByteArray(Charsets.UTF_8))
                output.flush()
                output.fd.sync()
            }
        } catch (e: Exception) {
            // The old file is untouched while the temp write fails, so the
            // previous entries stay readable behind an already-posted alert.
            try {
                tempFile.delete()
            } catch (_: Exception) {
                // Cleanup must not hide the original write failure.
            }
            throw e
        }
        moveTempIntoPlace(tempFile)
    }

    private fun buildPayload(entries: List<Entry>): String {
        val array = JSONArray()
        for (entry in entries) {
            val json = JSONObject()
            json.put("id", entry.id)
            json.put("received_ms", entry.receivedMs)
            json.put("ciphertext", Base64.getEncoder().encodeToString(entry.ciphertext))
            json.put("iv", Base64.getEncoder().encodeToString(entry.iv))
            json.put("deferred", entry.deferred)
            json.put("notificationId", entry.notificationId)
            array.put(json)
        }
        return array.toString()
    }

    private fun moveTempIntoPlace(tempFile: File) {
        try {
            try {
                Files.move(
                    tempFile.toPath(),
                    storeFile.toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE
                )
            } catch (e: AtomicMoveNotSupportedException) {
                Files.move(tempFile.toPath(), storeFile.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
        } catch (e: Exception) {
            try {
                tempFile.delete()
            } catch (_: Exception) {
                // Cleanup must not hide the move failure.
            }
            throw e
        }
    }
}

private const val TAG = "PS3Sms"
