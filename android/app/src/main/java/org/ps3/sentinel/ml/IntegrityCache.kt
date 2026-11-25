// Persists verified model file hashes to avoid expensive SHA-256 recomputations on cold start.
// Stores metadata records in internal app storage and coordinates background re-hashing
// of large model weights while allowing immediate app initialization.

package org.ps3.sentinel.ml

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.concurrent.ConcurrentLinkedQueue

/** One integrity cache row: name, size, last-modified time, SHA-256 hex and last verified time. */
data class IntegrityRecord(
    val name: String,
    val sizeBytes: Long,
    val lastModifiedMs: Long,
    val sha256Hex: String,
    val lastVerifiedMs: Long = 0L
)

/**
 * Purpose:  Caches passing SHA-256 results to skip re-hashing large models.
 * Owns:     One JSON file inside the no-backup files directory.
 * Lifetime: Process
 * Thread:   any — cache file access is synchronized by the store.
 */
object IntegrityCache {
    const val CACHE_FILE_NAME: String = "integrity_cache.json"

    // A persisted record lets ModelStore load an unchanged app-private copy
    // without hashing it first. 0 means every trusted file is still re-hashed
    // once per process, on the low-priority background worker.
    const val REHASH_INTERVAL_MS: Long = 0L

    /**
     * Checks if a cached integrity record requires a background re-hash verification pass.
     *
     * @param record Stored integrity record, or null if unrecorded.
     * @return True if [record] is non-null.
     */
    fun shouldRehash(record: IntegrityRecord?): Boolean {
        if (record == null) {
            return false
        }
        return true
    }

    // Metadata check (size, last-modified and manifest hash). A match lets
    // ModelStore skip the synchronous hash for the app-private Llama copy only;
    // every other model file is always hashed before it loads. The background
    // re-hash of the trusted Llama file still runs.
    /**
     * Checks whether file metadata matches the cached record and expected manifest hash.
     *
     * @param record Previously recorded verification entry.
     * @param sizeBytes Current file length in bytes.
     * @param lastModifiedMs Current file last-modified epoch timestamp.
     * @param manifestHash Expected SHA-256 hex string from APK manifest.
     * @return True if size, timestamp, and hash match the cached record.
     */
    fun shouldTrust(
        record: IntegrityRecord?,
        sizeBytes: Long,
        lastModifiedMs: Long,
        manifestHash: String
    ): Boolean {
        if (record == null) {
            return false
        }
        return record.sizeBytes == sizeBytes &&
            record.lastModifiedMs == lastModifiedMs &&
            record.sha256Hex.equals(manifestHash, ignoreCase = true)
    }

    /**
     * Resolves the cache file location within the designated directory.
     *
     * @param cacheDir Parent directory for the cache file.
     * @return File reference to integrity_cache.json, or null if [cacheDir] is null.
     */
    fun cacheFile(cacheDir: File?): File? =
        cacheDir?.let { File(it, CACHE_FILE_NAME) }

    /**
     * Loads and parses integrity records from [cacheFile].
     *
     * @param cacheFile JSON cache file to read.
     * @return Map of model file names to their corresponding [IntegrityRecord].
     */
    fun loadEntries(cacheFile: File?): Map<String, IntegrityRecord> {
        if (cacheFile == null || !cacheFile.isFile) {
            return emptyMap()
        }
        val text = try {
            cacheFile.readText(Charsets.UTF_8)
        } catch (_: Exception) {
            // Unreadable cache is safe to ignore: it becomes a miss and the
            // full hash runs before load, which is the pre-cache behaviour.
            return emptyMap()
        }
        if (text.isBlank()) {
            return emptyMap()
        }
        return parseEntries(text)
    }

    private fun parseEntries(text: String): Map<String, IntegrityRecord> {
        val array = try {
            JSONArray(text)
        } catch (_: Exception) {
            return emptyMap()
        }
        val result = linkedMapOf<String, IntegrityRecord>()
        for (index in 0 until array.length()) {
            val item = array.optJSONObject(index) ?: continue
            val name = item.optString("name", "")
            if (name.isEmpty()) {
                continue
            }
            result[name] = IntegrityRecord(
                name = name,
                sizeBytes = item.optLong("size", -1L),
                lastModifiedMs = item.optLong("last_modified_ms", -1L),
                sha256Hex = item.optString("sha256", ""),
                lastVerifiedMs = item.optLong("last_verified_ms", 0L)
            )
        }
        return result
    }

    /**
     * Atomically serializes [entries] to [cacheFile] via temporary file and sync.
     *
     * @param cacheFile Target destination file.
     * @param entries Current map of verified file records.
     * @return True if the atomic write and replace succeeded.
     */
    fun saveEntries(cacheFile: File?, entries: Map<String, IntegrityRecord>): Boolean {
        if (cacheFile == null) {
            return false
        }
        val snapshot = entries.values.toList()
        val array = JSONArray()
        for (record in snapshot) {
            val json = JSONObject()
            json.put("name", record.name)
            json.put("size", record.sizeBytes)
            json.put("last_modified_ms", record.lastModifiedMs)
            json.put("sha256", record.sha256Hex)
            json.put("last_verified_ms", record.lastVerifiedMs)
            array.put(json)
        }
        val tempFile = cacheFile.parentFile?.let { File(it, cacheFile.name + ".tmp") }
            ?: File(cacheFile.path + ".tmp")
        return try {
            cacheFile.parentFile?.mkdirs()
            try {
                FileOutputStream(tempFile).use { output ->
                    output.write(array.toString().toByteArray(Charsets.UTF_8))
                    output.flush()
                    output.fd.sync()
                }
            } catch (e: Exception) {
                try {
                    tempFile.delete()
                } catch (_: Exception) {
                    // Cleanup must not hide the original write failure.
                }
                throw e
            }
            try {
                try {
                    Files.move(
                        tempFile.toPath(),
                        cacheFile.toPath(),
                        StandardCopyOption.REPLACE_EXISTING,
                        StandardCopyOption.ATOMIC_MOVE
                    )
                } catch (e: AtomicMoveNotSupportedException) {
                    Files.move(tempFile.toPath(), cacheFile.toPath(), StandardCopyOption.REPLACE_EXISTING)
                }
            } catch (e: Exception) {
                try {
                    tempFile.delete()
                } catch (_: Exception) {
                    // Cleanup must not hide the move failure.
                }
                throw e
            }
            true
        } catch (_: Exception) {
            // A cache write failure only costs one full hash next start, so
            // the caller reports it and startup continues without the cache.
            false
        }
    }

    // Re-hashes trusted Llama files on a low-priority thread while the native
    // model load and prefill run. Mismatches go to onMismatch; the caller logs,
    // refuses and releases the advisor.
    /**
     * Asynchronously re-hashes files on a low-priority background thread.
     *
     * @param files List of model files to re-verify.
     * @param manifest Map of expected file names to SHA-256 hex hashes.
     * @param sha256Of Digest function computing SHA-256 for a given file.
     * @param onMismatch Callback invoked if actual digest does not match manifest.
     * @param onSuccess Callback invoked when a file matches its expected digest.
     * @param onComplete Callback invoked when all queued files have been processed.
     */
    fun startBackgroundRehash(
        files: List<File>,
        manifest: Map<String, String>,
        sha256Of: (File) -> String,
        onMismatch: (File, String) -> Unit,
        onSuccess: (File) -> Unit = {},
        onComplete: () -> Unit = {}
    ) {
        if (files.isEmpty()) {
            onComplete()
            return
        }
        val queue = ConcurrentLinkedQueue(files)
        val thread = Thread({
            Thread.currentThread().priority = Thread.MIN_PRIORITY
            try {
                var next = queue.poll()
                while (next != null) {
                    val expected = manifest[next.name]
                    if (expected != null) {
                        val actual = try {
                            sha256Of(next)
                        } catch (_: Exception) {
                            ""
                        }
                        if (!actual.equals(expected, ignoreCase = true)) {
                            onMismatch(next, "SHA-256 mismatch for ${next.name}")
                        } else {
                            onSuccess(next)
                        }
                    }
                    next = queue.poll()
                }
            } finally {
                onComplete()
            }
        }, "ps3-integrity-rehash")
        thread.isDaemon = true
        thread.start()
    }
}
