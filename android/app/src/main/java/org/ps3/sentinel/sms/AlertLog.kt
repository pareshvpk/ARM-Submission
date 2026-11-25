package org.ps3.sentinel.sms

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.ps3.sentinel.core.shouldSkip
import java.util.Base64

/**
 * Log entry capturing metadata and encrypted message body for an analysed incoming SMS or MMS message.
 */
data class AlertEntry(
    val id: String,
    val timeMillis: Long,
    val level: String,
    val label: String,
    val sender: String,
    val message: String? = null,
    val kind: String = AlertLog.KIND_SCAM
)

/**
 * Manages persisted history of threat alerts and safe messages in SharedPreferences.
 * Stores up to 50 scam and 50 safe entries in JSON format with encrypted message bodies.
 */
object AlertLog {
    const val PREFS_NAME = "sentinel_alert_log"
    const val KEY_ALERTS = "alerts_json"
    const val MAX_ENTRIES = 50
    const val KIND_SCAM = "scam"
    const val KIND_SAFE = "safe"

    var cipher: PendingCipher = KeystorePendingCipher()

    /** Pure decision: returns false if skipped by routine filter or if deferred analysis has not given a model answer. */
    fun shouldRecord(isRoutineSkipped: Boolean, hasModelAnswer: Boolean): Boolean {
        if (isRoutineSkipped) return false
        return hasModelAnswer
    }

    // One-time codes and account balance/debit/credit alerts are never kept in the safe list, even when
    // the routine filter did not skip them (for example a bank header without the DLT suffix).
    private val SENSITIVE = Regex(
        "(?i)(\\botp\\b|one[- ]time|verification code|passcode|avail(able)?\\.?\\s*bal|a/c\\s*[*x]*\\d|\\b(debited|credited)\\b)"
    )

    /** True when [body] carries a one-time code or account balance/transaction details. */
    fun looksSensitive(body: String): Boolean = SENSITIVE.containsMatchIn(body)

    /** Pure decision helper evaluating routine skip and sensitive content against sender and body. */
    fun shouldRecord(sender: String, body: String, hasModelAnswer: Boolean): Boolean {
        return shouldRecord(shouldSkip(sender, body) || looksSensitive(body), hasModelAnswer)
    }

    /** Adds an alert entry, maintaining newest-first ordering and capping at 50 entries per kind. */
    @Synchronized
    fun add(context: Context, entry: AlertEntry) {
        // Safe entries never keep one-time codes or balance alerts; scam entries are always kept.
        if (entry.kind == KIND_SAFE && !shouldRecord(entry.sender, entry.message ?: "", true)) return
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val currentJson = prefs.getString(KEY_ALERTS, "[]") ?: "[]"
        val currentList = fromJson(currentJson)
        val updated = mutableListOf(entry)
        for (item in currentList) {
            if (item.id != entry.id) {
                updated.add(item)
            }
        }
        val trimmed = trim(updated, MAX_ENTRIES)
        prefs.edit().putString(KEY_ALERTS, toJson(trimmed)).apply()
    }

    /** Lists persisted alert entries, newest first, optionally filtered by kind. */
    @Synchronized
    fun list(context: Context, kind: String? = null): List<AlertEntry> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val currentJson = prefs.getString(KEY_ALERTS, "[]") ?: "[]"
        val all = fromJson(currentJson)
        return if (kind == null) all else all.filter { it.kind == kind }
    }

    /** Lists scam entries only, newest first. */
    @Synchronized
    fun listScam(context: Context): List<AlertEntry> = list(context, KIND_SCAM)

    /** Lists safe entries only, newest first. */
    @Synchronized
    fun listSafe(context: Context): List<AlertEntry> = list(context, KIND_SAFE)

    /** Clears logged alerts from storage; if [kind] is specified, clears only that kind. */
    @Synchronized
    fun clear(context: Context, kind: String? = null) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (kind == null) {
            prefs.edit().remove(KEY_ALERTS).apply()
        } else {
            val currentJson = prefs.getString(KEY_ALERTS, "[]") ?: "[]"
            val remaining = fromJson(currentJson).filter { it.kind != kind }
            prefs.edit().putString(KEY_ALERTS, toJson(remaining)).apply()
        }
    }

    /** Serializes alert entries into a JSON array string with an encrypted sender and message body. */
    fun toJson(entries: List<AlertEntry>, customCipher: PendingCipher? = cipher): String {
        val array = JSONArray()
        for (entry in entries) {
            val obj = JSONObject()
            obj.put("id", entry.id)
            obj.put("timeMillis", entry.timeMillis)
            obj.put("level", entry.level)
            obj.put("label", entry.label)
            // FIX 2: the sender identifies a person, so it is encrypted exactly like
            // the message body. Without a usable cipher it falls back to plaintext,
            // the same way the body is simply dropped.
            val encryptedSender = encryptValue(entry.sender, customCipher)
            if (encryptedSender != null) {
                obj.put("sender_ciphertext", Base64.getEncoder().encodeToString(encryptedSender.ciphertext))
                obj.put("sender_iv", Base64.getEncoder().encodeToString(encryptedSender.iv))
            } else {
                obj.put("sender", entry.sender)
            }
            obj.put("kind", entry.kind)
            val encryptedBody = encryptValue(entry.message ?: "", customCipher)
            if (encryptedBody != null) {
                obj.put("ciphertext", Base64.getEncoder().encodeToString(encryptedBody.ciphertext))
                obj.put("iv", Base64.getEncoder().encodeToString(encryptedBody.iv))
            }
            array.put(obj)
        }
        return array.toString()
    }

    /** Encrypts [value] with [customCipher], or null when it is empty or encryption fails. */
    private fun encryptValue(value: String, customCipher: PendingCipher?): EncryptedBody? {
        if (value.isEmpty() || customCipher == null) return null
        return try {
            customCipher.encrypt(value.toByteArray(Charsets.UTF_8))
        } catch (_: Exception) {
            null
        }
    }

    /** Decrypts a stored ciphertext/IV pair, or null when absent, undecodable or undecryptable. */
    private fun decryptValue(
        ciphertextB64: String?,
        ivB64: String?,
        customCipher: PendingCipher?
    ): String? {
        if (ciphertextB64.isNullOrEmpty() || ivB64.isNullOrEmpty() || customCipher == null) return null
        return try {
            val ciphertext = Base64.getDecoder().decode(ciphertextB64)
            val iv = Base64.getDecoder().decode(ivB64)
            String(customCipher.decrypt(EncryptedBody(ciphertext, iv)), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    /** Deserializes a JSON array string into alert entries, decrypting sender and message body. */
    fun fromJson(json: String, customCipher: PendingCipher? = cipher): List<AlertEntry> {
        if (json.isBlank()) return emptyList()
        val list = mutableListOf<AlertEntry>()
        return try {
            val array = JSONArray(json)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val ciphertextB64 = if (obj.has("ciphertext")) obj.optString("ciphertext") else null
                val ivB64 = if (obj.has("iv")) obj.optString("iv") else null
                val message = decryptValue(ciphertextB64, ivB64, customCipher)
                // FIX 2: entries written before the sender was encrypted only carry
                // the plaintext "sender" key, so fall back to it when there is no
                // encrypted sender to read.
                val sender = decryptValue(
                    if (obj.has("sender_ciphertext")) obj.optString("sender_ciphertext") else null,
                    if (obj.has("sender_iv")) obj.optString("sender_iv") else null,
                    customCipher
                ) ?: obj.optString("sender")
                val kind = if (obj.has("kind")) {
                    obj.optString("kind", KIND_SCAM).ifBlank { KIND_SCAM }
                } else {
                    KIND_SCAM
                }
                list.add(
                    AlertEntry(
                        id = obj.optString("id"),
                        timeMillis = obj.optLong("timeMillis"),
                        level = obj.optString("level"),
                        label = obj.optString("label"),
                        sender = sender,
                        message = message,
                        kind = kind
                    )
                )
            }
            list
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** Trims a list of entries to at most [max] elements per kind (scam and safe), preserving newest-first order. */
    fun trim(entries: List<AlertEntry>, max: Int = MAX_ENTRIES): List<AlertEntry> {
        var scamCount = 0
        var safeCount = 0
        val result = mutableListOf<AlertEntry>()
        for (entry in entries) {
            if (entry.kind == KIND_SAFE) {
                if (safeCount < max) {
                    result.add(entry)
                    safeCount++
                }
            } else {
                if (scamCount < max) {
                    result.add(entry)
                    scamCount++
                }
            }
        }
        return result
    }
}
