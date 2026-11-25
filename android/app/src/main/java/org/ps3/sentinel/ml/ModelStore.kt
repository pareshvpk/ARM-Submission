// Manages on-device model discovery, verification, integrity checking, and staging.
// Validates model weights against APK-bundled hashes, imports external files into private app storage,
// and coordinates background integrity re-hashing.

package org.ps3.sentinel.ml

import android.content.Context
import android.util.Log
import kotlinx.coroutines.delay
import org.json.JSONObject
import org.ps3.sentinel.SentinelApp
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Result of checking a single model file against the expected hashes bundled in the APK.
 *
 * [loadable] is false when the file must be refused (unsafe name, missing expected hash, or hash mismatch).
 * [verified] is true only when the streamed SHA-256 matched the APK hash.
 * [message] is a human-readable refusal reason, null when fine.
 */
data class ModelCheck(
    val fileName: String,
    val loadable: Boolean,
    val verified: Boolean,
    val message: String?
)

/** Phone file names per model role from the shared model_files.json asset. */
data class ModelFileNames(
    val urlModel: String,
    val urlVocab: String,
    val smsModel: String,
    val smsIdMap: String,
    val smsVocab: String,
    val smsTokenizerDir: String,
    val llamaModel: String,
    val llamaTokenizer: String,
    val smsFp32: String = "sms_fp32.pte"
) {
    /** Helper parsers and fallback defaults for model file naming conventions. */
    companion object {
        /** Built-in names used when the asset cannot be read; kept in sync by ModelFilesTest. */
        fun defaults(): ModelFileNames = ModelFileNames(
            urlModel = "url_cnn_v2.pte",
            urlVocab = "vocab.json",
            smsModel = "sms_int8.pte",
            smsIdMap = "id_map.json",
            smsVocab = "sms_vocab.txt",
            smsTokenizerDir = "sms_vocab.txt",
            llamaModel = "llama.pte",
            llamaTokenizer = "tokenizer.model",
            smsFp32 = "sms_fp32.pte"
        )

        /** Parses model_files.json text into phone names per role. */
        fun fromJson(text: String): ModelFileNames {
            val phones = parsePhoneNames(text)
            return ModelFileNames(
                urlModel = phones.getValue("url_model"),
                urlVocab = phones.getValue("url_vocab"),
                smsModel = phones.getValue("sms_model"),
                smsIdMap = phones.getValue("sms_id_map"),
                smsVocab = phones.getValue("sms_vocab"),
                smsTokenizerDir = phones.getValue("sms_tokenizer_dir"),
                llamaModel = phones.getValue("llama_model"),
                llamaTokenizer = phones.getValue("llama_tokenizer"),
                smsFp32 = optionalPhoneName(text, "sms_fp32") ?: "sms_fp32.pte"
            )
        }

        /** Returns the optional phone name for [role], or null when the role is absent. */
        fun optionalPhoneName(text: String, role: String): String? {
            val files = try {
                JSONObject(text).optJSONObject("files")
            } catch (error: Exception) {
                return null
            } ?: return null
            val entry = files.optJSONObject(role) ?: return null
            return entry.optString("phone", "").ifEmpty { null }
        }

        /** Returns the phone file name for every required role in the file. */
        fun parsePhoneNames(text: String): Map<String, String> {
            val root = try {
                JSONObject(text)
            } catch (error: Exception) {
                throw IllegalArgumentException("model_files.json is not valid JSON: ${error.message}", error)
            }
            if (root.optInt("schema_version", -1) != 1) {
                throw IllegalArgumentException("model_files.json: unsupported schema_version")
            }
            val files = root.getJSONObject("files")
            val roles = listOf(
                "url_model", "url_vocab", "sms_model", "sms_id_map",
                "sms_vocab", "sms_tokenizer_dir", "llama_model", "llama_tokenizer"
            )
            val result = linkedMapOf<String, String>()
            for (role in roles) {
                val entry = files.getJSONObject(role)
                val phone = entry.optString("phone", "")
                if (phone.isEmpty()) {
                    throw IllegalArgumentException("model_files.json: role $role needs a phone name")
                }
                result[role] = phone
            }
            return result
        }
    }
}

/**
 * Purpose:  Validates model files before they load.
 * Owns:     The expected-hash parse and the per-start verification cache.
 * Lifetime: Process
 * Thread:   any — caches are concurrent.
 */
class ModelStore internal constructor(
    val sourceDir: File,
    val modelsDir: File,
    val fileNames: ModelFileNames = ModelFileNames.defaults(),
    val cacheDir: File? = null,
    val expectedHashes: Map<String, String> = emptyMap(),
    private val sha256Of: (File) -> String = { ModelStore.sha256Hex(it) }
) {
    /**
     * Initializes the model store using standard application storage directories and bundled assets.
     *
     * @param context Application context used to resolve internal and external storage paths.
     */
    constructor(context: Context) : this(
        File(context.getExternalFilesDir(null), "models"),
        File(context.filesDir, "models"),
        loadFileNames(context),
        context.noBackupFilesDir ?: context.filesDir,
        loadExpectedHashes(context)
    )

    val urlModelFile: File = File(modelsDir, fileNames.urlModel)
    val vocabFile: File = File(modelsDir, fileNames.urlVocab)
    val llamaModelFile: File = File(modelsDir, fileNames.llamaModel)
    val tokenizerFile: File = File(modelsDir, fileNames.llamaTokenizer)

    // Optional SMS classifier files
    val smsModelFile: File = File(modelsDir, fileNames.smsModel)
    val smsFp32File: File = File(modelsDir, fileNames.smsFp32)
    val idMapFile: File = File(modelsDir, fileNames.smsIdMap)
    val smsVocabFile: File = File(modelsDir, fileNames.smsVocab)
    val optionalFiles: List<File> = listOf(smsModelFile, idMapFile, smsVocabFile)
    @Volatile var smsStatus: String? = null

    /** Set when the shared rules failed to load at startup; surfaced in [statusSummary]. */
    var rulesStatus: String? = null

    /** Runtime model load failures (constructor/init), surfaced alongside manifest errors. */
    val loadErrors: MutableList<String> = java.util.Collections.synchronizedList(mutableListOf())

    /** Parsed expected hashes from the APK asset for backward compatibility. */
    val manifest: Map<String, String> get() = expectedHashes

    private data class VerificationEntry(val check: ModelCheck, val sizeBytes: Long, val lastModifiedMs: Long)

    /** Per-process verification cache: hashed once per ModelStore instance; size/mtime change invalidates. */
    private val verificationCache = ConcurrentHashMap<String, VerificationEntry>()
    private val fileLocks = ConcurrentHashMap<String, Any>()
    private val integrityCacheFile: File? = IntegrityCache.cacheFile(cacheDir)
    private val integrityEntries: MutableMap<String, IntegrityRecord> =
        IntegrityCache.loadEntries(integrityCacheFile).toMutableMap()
    private val integrityLock = Any()
    private val pendingRehash = java.util.concurrent.ConcurrentLinkedQueue<File>()
    private val rehashRunning = java.util.concurrent.atomic.AtomicBoolean(false)

    // Files that were trusted on size/mtime alone and are still waiting for their
    // background re-hash. Only the Llama model is ever trusted this way.
    private val pendingRehashNames: MutableSet<String> =
        java.util.Collections.newSetFromMap(ConcurrentHashMap<String, Boolean>())

    // Files whose background re-hash found a SHA-256 mismatch; they were refused.
    private val rehashFailedNames: MutableSet<String> =
        java.util.Collections.newSetFromMap(ConcurrentHashMap<String, Boolean>())

    // Files that passed a SHA-256 check in this process, synchronously or in the
    // background re-hash. Used by awaitVerified to gate model output.
    private val verifiedThisProcess: MutableSet<String> =
        java.util.Collections.newSetFromMap(ConcurrentHashMap<String, Boolean>())

    /** Number of integrity checks currently hashing files, exposed so the UI can say "verifying". */
    private val verificationsInProgress = AtomicInteger(0)

    /** True while at least one model file is being hashed against the manifest. */
    val isVerifying: Boolean get() = verificationsInProgress.get() > 0

    /** Invoked on the verifying thread when the last check finishes; the UI posts it to the main thread. */
    @Volatile var onVerificationFinished: (() -> Unit)? = null

    /** Wakes a registered listener once verification has fully finished. */
    fun notifyVerificationFinished() {
        val listener = onVerificationFinished
        try {
            listener?.invoke()
        } catch (e: Exception) {
            warnLog("ModelStore: verification listener failed: ${e::class.simpleName}: ${e.message}", e)
        }
    }

    /**
     * Re-hashes files that [trustPersisted] accepted on size/mtime alone, at low priority.
     *
     * Only the Llama model is trusted this way; every other file is hashed
     * synchronously in [checkFile] before it may load. A trusted file stays in
     * the pending set until its re-hash finishes, so [awaitVerified] can keep
     * model output gated while the hash runs in parallel with the Llama load and
     * prefill. Safe to call more than once: each call drains whatever is queued
     * at that time, and at most one re-hash worker runs at a time.
     */
    fun startBackgroundRehash() {
        if (!rehashRunning.compareAndSet(false, true)) {
            return
        }
        val worker = Thread({
            try {
                while (true) {
                    val pending = drainPendingRehash()
                    if (pending.isEmpty()) {
                        break
                    }
                    val done = java.util.concurrent.CountDownLatch(1)
                    IntegrityCache.startBackgroundRehash(
                        pending,
                        expectedHashes,
                        { sha256Of(it) },
                        { file, message ->
                            verificationCache[file.name] = VerificationEntry(
                                ModelCheck(file.name, false, false, message),
                                -1L,
                                -1L
                            )
                            file.delete()
                            synchronized(integrityLock) {
                                integrityEntries.remove(file.name)
                                IntegrityCache.saveEntries(
                                    integrityCacheFile,
                                    HashMap(integrityEntries)
                                )
                            }
                            // Fail last: awaitVerified() short-circuits on rehashFailedNames, so the delete and cache updates must land first.
                            markRehashFailed(file.name)
                            releaseLlamaAfterRehashFailure(file.name)
                            warnLog("ModelStore: background re-hash $message", Exception(message))
                        },
                        { file ->
                            markVerified(file.name)
                            synchronized(integrityLock) {
                                integrityEntries[file.name]?.let { record ->
                                    integrityEntries[file.name] =
                                        record.copy(lastVerifiedMs = System.currentTimeMillis())
                                    IntegrityCache.saveEntries(
                                        integrityCacheFile,
                                        HashMap(integrityEntries)
                                    )
                                }
                            }
                        },
                        { done.countDown() }
                    )
                    try {
                        done.await()
                    } catch (e: InterruptedException) {
                        Thread.currentThread().interrupt()
                        break
                    }
                }
            } finally {
                rehashRunning.set(false)
                if (pendingRehash.isNotEmpty()) {
                    startBackgroundRehash()
                }
            }
        }, "ps3-model-rehash-worker")
        worker.isDaemon = true
        worker.priority = Thread.MIN_PRIORITY
        worker.start()
    }

    /** Polls every queued file out of [pendingRehash] in queue order. */
    private fun drainPendingRehash(): List<File> {
        val pending = ArrayList<File>()
        var next = pendingRehash.poll()
        while (next != null) {
            pending.add(next)
            next = pendingRehash.poll()
        }
        return pending
    }

    /** True while [name] is trusted on size/mtime but its background re-hash has not finished. */
    fun isPendingRehash(name: String): Boolean = pendingRehashNames.contains(name)

    /** True when the background re-hash of [name] found a mismatch and refused the file. */
    fun rehashFailed(name: String): Boolean = rehashFailedNames.contains(name)

    /**
     * Waits up to [timeoutMs] for [name] to pass SHA-256 in this process.
     *
     * True only once the background re-hash of a trusted file passed, or [checkFile]
     * hashed and matched it synchronously. False on a mismatch or a timeout, so a
     * caller can refuse model output instead of using unverified bytes.
     */
    suspend fun awaitVerified(name: String, timeoutMs: Long): Boolean {
        val startNs = System.nanoTime()
        while (true) {
            if (rehashFailedNames.contains(name)) {
                return false
            }
            if (verifiedThisProcess.contains(name) && !pendingRehashNames.contains(name)) {
                return true
            }
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            if (elapsedMs >= timeoutMs) {
                return false
            }
            delay(AWAIT_VERIFY_POLL_INTERVAL_MS)
        }
    }

    private fun markVerified(name: String) {
        pendingRehashNames.remove(name)
        rehashFailedNames.remove(name)
        verifiedThisProcess.add(name)
    }

    private fun markRehashFailed(name: String) {
        pendingRehashNames.remove(name)
        verifiedThisProcess.remove(name)
        rehashFailedNames.add(name)
    }

    /** Releases the Llama advisor after its file failed the background re-hash. */
    private fun releaseLlamaAfterRehashFailure(name: String) {
        if (name != fileNames.llamaModel) {
            return
        }
        try {
            SentinelApp.instance.releaseLlamaAfterIntegrityFailure()
        } catch (_: Exception) {
            // No application instance (unit tests) or no advisor to release: the
            // Pipeline verification gate still refuses output from this file.
        } catch (_: LinkageError) {
            // Android framework stubs are unavailable under JVM unit tests.
        }
    }

    /**
     * Ensures the internal models directory exists, creating parent directories if needed.
     *
     * @return True if the directory exists or was successfully created.
     */
    fun ensureDirExists(): Boolean {
        return modelsDir.exists() || modelsDir.mkdirs()
    }

    /**
     * Scans for missing required model files.
     *
     * @return List of file names for required models that are absent from storage.
     */
    fun missingModels(): List<String> {
        val missing = mutableListOf<String>()
        if (!isPresent(urlModelFile)) missing.add(fileNames.urlModel)
        if (!isPresent(vocabFile)) missing.add(fileNames.urlVocab)
        if (!isPresent(llamaModelFile)) missing.add(fileNames.llamaModel)
        if (!isPresent(tokenizerFile)) missing.add(fileNames.llamaTokenizer)
        return missing
    }

    /**
     * Cheap readiness check for the URL classifier: presence and safe file names only.
     *
     * This is called from Application.onCreate on the main thread, so it must never hash. The
     * contract is verified later by [verifyForLoad] on a background thread before the model loads.
     */
    fun isUrlClassifierReady(): Boolean = regularFiles(listOf(urlModelFile, vocabFile))

    /** Cheap readiness check for the Llama advisor. See [isUrlClassifierReady] for why this does not hash. */
    fun isLlamaReady(): Boolean = regularFiles(listOf(llamaModelFile, tokenizerFile))

    /**
     * Cheap readiness check for the SMS classifier. See [isUrlClassifierReady] for why this does not hash.
     *
     * Phones without the Arm dot-product extension prefer the fp32 model when it is
     * installed; every other phone keeps using int8. The fp32 file is optional, so its
     * absence falls back to int8 rather than hiding the SMS model.
     */
    fun isSmsClassifierReady(): Boolean = isSmsClassifierReadyFor(CpuFeatures.currentFlags())

    /**
     * Evaluates whether SMS classification assets matching [flags] are present and loadable.
     *
     * @param flags Detected CPU features determining whether int8 or fp32 is preferred.
     * @return True if vocabulary, idMap, and a compatible model file are present.
     */
    fun isSmsClassifierReadyFor(flags: CpuFlags): Boolean =
        isPresent(idMapFile) && isPresent(smsVocabFile) && smsModelFileFor(flags) != null

    /** Picks the SMS model file for [flags], or null when no usable pte is present. */
    fun smsModelFileFor(flags: CpuFlags): File? {
        if (!flags.asimddp && isPresent(smsFp32File)) return smsFp32File
        if (isPresent(smsModelFile)) return smsModelFile
        return if (isPresent(smsFp32File)) smsFp32File else null
    }

    /** True when the optional fp32 SMS model is installed (phone without dot product). */
    fun isSmsFp32Available(): Boolean = isPresent(smsFp32File)

    /** Metadata-only size/mtime snapshot of one SMS classifier file: internal copy and external source. */
    data class SmsFileSnapshot(
        val internal: Pair<Long, Long>,
        val external: Pair<Long, Long>
    )

    private fun fileSnapshot(file: File): Pair<Long, Long> =
        if (file.isFile) file.length() to file.lastModified() else -1L to -1L

    /**
     * Size/mtime snapshot of every SMS classifier file, keyed by file name.
     * Snapshots both the internal copy and the external source file so a
     * corrected external file pushed after a failed SMS load triggers a retry.
     * Presence, size and modification time only — never a hash.
     */
    fun smsFileSnapshot(): Map<String, SmsFileSnapshot> {
        val files = listOf(smsModelFile, smsFp32File, idMapFile, smsVocabFile)
        return files.associate { file ->
            val name = file.name
            name to SmsFileSnapshot(
                internal = fileSnapshot(File(modelsDir, name)),
                external = fileSnapshot(File(sourceDir, name))
            )
        }
    }

    /** True when every file exists as a regular file and has a name safe to load. */
    private fun regularFiles(files: List<File>): Boolean =
        files.all { isPresent(it) }

    private fun isPresent(file: File): Boolean {
        if (!isValidModelFileName(file.name)) {
            return false
        }
        return file.isFile || File(sourceDir, file.name).isFile
    }

    /**
     * Verifies [files] against the expected APK hashes before they are first loaded.
     *
     * Blocking and hash-heavy (the Llama model alone is about 1 GB), so callers must run it off the
     * main thread. Returns the first failing [ModelCheck], or null when every file may be loaded.
     * Results are cached for the rest of the app start and surface through [errors] and [warnings].
     */
    fun verifyForLoad(files: List<File>): ModelCheck? {
        verificationsInProgress.incrementAndGet()
        try {
            for (file in files) {
                val check = checkFile(file)
                if (!check.loadable) {
                    return check
                }
            }
            return null
        } finally {
            if (verificationsInProgress.decrementAndGet() == 0) {
                notifyVerificationFinished()
            }
        }
    }

    /**
     * Checks [file] against the expected hashes. Hashes are streamed (never read whole into memory).
     * Only an app-private copy of the Llama model whose size, mtime and expected hash match the
     * persisted record may load before hashing: it is trusted at start, queued in [pendingRehash]
     * and re-hashed in the background (see [trustPersisted] and [awaitVerified]). Every other file
     * is hashed synchronously before it loads. Model file names with path separators or ".." are refused.
     */
    fun checkFile(file: File): ModelCheck {
        val name = file.name
        val lock = fileLocks.computeIfAbsent(name) { Any() }
        synchronized(lock) {
            val cached = verificationCache[name]
            if (cached != null) {
                val (curSize, curMtime) = snapshotFor(name, file)
                if (curSize == cached.sizeBytes && curMtime == cached.lastModifiedMs) {
                    return cached.check
                }
                verificationCache.remove(name)
            }
            val check = verifyFile(file)
            val (snapSize, snapMtime) = snapshotFor(name, file)
            verificationCache[name] = VerificationEntry(check, snapSize, snapMtime)
            return check
        }
    }

    private fun snapshotFor(name: String, file: File): Pair<Long, Long> {
        val internal = File(modelsDir, name)
        if (internal.isFile) return internal.length() to internal.lastModified()
        return if (file.isFile) file.length() to file.lastModified() else -1L to -1L
    }

    /**
     * True when the app-private Llama copy matches the record written after its last successful hash.
     *
     * Why: hashing the 1.1 GB Llama file took 6 to 8 s on every cold start (Galaxy M31, moto g73,
     * 2026-11-15). The copy lives in storage other apps cannot write, so an unchanged size and mtime
     * is trusted for loading, and only for the Llama file: every other model is hashed synchronously
     * before it loads. The Llama file is still re-hashed on the low-priority worker
     * ([startBackgroundRehash]) in parallel with the load; a mismatch there deletes it, records the
     * failure and releases any loaded advisor, and Pipeline refuses to stream advice until
     * [awaitVerified] reports success for this process.
     */
    private fun trustPersisted(name: String, internalFile: File, expected: String): Boolean {
        if (name != fileNames.llamaModel) {
            return false
        }
        val record = synchronized(integrityLock) { integrityEntries[name] }
        if (!IntegrityCache.shouldTrust(record, internalFile.length(), internalFile.lastModified(), expected)) {
            return false
        }
        verifiedThisProcess.remove(name)
        rehashFailedNames.remove(name)
        pendingRehashNames.add(name)
        pendingRehash.offer(internalFile)
        startBackgroundRehash()
        return true
    }

    /** Performs the actual expected-hash lookup and hashing for [file]. */
    private fun verifyFile(file: File): ModelCheck {
        val name = file.name
        if (!isValidModelFileName(name)) {
            return ModelCheck(name, loadable = false, verified = false,
                message = "Refused unsafe model file name: $name")
        }
        val expected = expectedHashes[name]
            ?: return ModelCheck(name, loadable = false, verified = false,
                message = "No expected hash for $name; refusing to load")
        if (sourceDir.canonicalPath == modelsDir.canonicalPath) {
            return verifySingleFile(name, expected)
        }
        val internalFile = File(modelsDir, name)
        if (internalFile.isFile) {
            val trusted = tryInternal(name, internalFile, expected)
            if (trusted != null) {
                return trusted
            }
        }
        return verifyExternal(name, expected)
    }

    private fun verifySingleFile(name: String, expected: String): ModelCheck {
        val file = File(modelsDir, name)
        if (!file.isFile) {
            return ModelCheck(name, loadable = false, verified = false,
                message = "Missing $name; refusing to load")
        }
        if (trustPersisted(name, file, expected)) {
            return ModelCheck(name, loadable = true, verified = true, message = null)
        }
        val actual = try {
            sha256Of(file)
        } catch (e: Exception) {
            warnLog("ModelStore: hash failed for $name: ${e::class.simpleName}: ${e.message}", e)
            return ModelCheck(name, loadable = false, verified = false,
                message = "Failed to hash $name; refusing to load")
        }
        if (!actual.equals(expected, ignoreCase = true)) {
            return ModelCheck(name, loadable = false, verified = false,
                message = "SHA-256 mismatch for $name; refusing to load")
        }
        recordIntegrity(name, file.length(), file.lastModified(), actual)
        markVerified(name)
        return ModelCheck(name, loadable = true, verified = true, message = null)
    }

    private fun tryInternal(name: String, internalFile: File, expected: String): ModelCheck? {
        if (trustPersisted(name, internalFile, expected)) {
            return ModelCheck(name, loadable = true, verified = true, message = null)
        }
        val actual = try {
            sha256Of(internalFile)
        } catch (e: Exception) {
            warnLog("ModelStore: internal hash failed for $name: ${e::class.simpleName}: ${e.message}", e)
            internalFile.delete()
            return null
        }
        if (actual.equals(expected, ignoreCase = true)) {
            recordIntegrity(name, internalFile.length(), internalFile.lastModified(), actual)
            deleteExternalAfterVerifiedImport(name, internalFile)
            markVerified(name)
            return ModelCheck(name, loadable = true, verified = true, message = null)
        }
        internalFile.delete()
        return null
    }

    private fun verifyExternal(name: String, expected: String): ModelCheck {
        val externalFile = File(sourceDir, name)
        if (!externalFile.isFile) {
            warnLog("ModelStore: external file missing: $name in ${sourceDir.absolutePath}")
            return ModelCheck(name, loadable = false, verified = false,
                message = "Missing $name; refusing to load")
        }
        if (!modelsDir.exists()) {
            modelsDir.mkdirs()
        }
        val tempFile = File(modelsDir, "$name.tmp")
        if (tempFile.exists()) {
            tempFile.delete()
        }
        val actual = try {
            copyAndHash(externalFile, tempFile)
        } catch (e: Exception) {
            tempFile.delete()
            warnLog("ModelStore: failed to copy $name: ${e::class.simpleName}: ${e.message}", e)
            return ModelCheck(name, loadable = false, verified = false,
                message = "Failed to copy $name; refusing to load")
        }
        if (!actual.equals(expected, ignoreCase = true)) {
            tempFile.delete()
            warnLog("ModelStore: SHA-256 mismatch for $name (expected $expected, actual $actual)")
            return ModelCheck(name, loadable = false, verified = false,
                message = "SHA-256 mismatch for $name; refusing to load")
        }
        val finalFile = File(modelsDir, name)
        if (!tempFile.renameTo(finalFile)) {
            tempFile.delete()
            warnLog("ModelStore: failed to rename $name to $name")
            return ModelCheck(name, loadable = false, verified = false,
                message = "Failed to finalize $name; refusing to load")
        }
        recordIntegrity(name, finalFile.length(), finalFile.lastModified(), actual)
        deleteExternalAfterVerifiedImport(name, finalFile)
        markVerified(name)
        return ModelCheck(name, loadable = true, verified = true, message = null)
    }

    /**
     * Removes the external source file once its verified copy lives in filesDir.
     *
     * Called only after the internal file matched the expected SHA-256, so a missing or
     * unverified copy never triggers a deletion. Failures are logged and ignored: the
     * duplicate only costs space, while the internal copy is already loadable.
     */
    private fun deleteExternalAfterVerifiedImport(name: String, internalFile: File) {
        try {
            if (sourceDir.canonicalPath == modelsDir.canonicalPath) return
            if (name == EXTERNAL_MANIFEST_FILE_NAME) return
            if (File(sourceDir, KEEP_EXTERNAL_FLAG_FILE_NAME).exists()) return
            if (!internalFile.isFile) return
            val externalFile = File(sourceDir, name)
            if (!externalFile.isFile) return
            if (!externalFile.delete()) {
                warnLog("ModelStore: could not delete external duplicate $name")
            }
        } catch (e: Exception) {
            Log.w(
                TAG,
                "ModelStore: failed to delete external duplicate $name: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
        }
    }

    private fun copyAndHash(source: File, destination: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(source).use { input ->
            FileOutputStream(destination).use { output ->
                val buffer = ByteArray(BUFFER_SIZE)
                var read = input.read(buffer)
                while (read != -1) {
                    digest.update(buffer, 0, read)
                    output.write(buffer, 0, read)
                    read = input.read(buffer)
                }
                output.flush()
                output.fd.sync()
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun recordIntegrity(
        name: String,
        sizeBytes: Long,
        lastModifiedMs: Long,
        hash: String,
        nowMs: Long = System.currentTimeMillis()
    ) {
        val saved = synchronized(integrityLock) {
            integrityEntries[name] = IntegrityRecord(name, sizeBytes, lastModifiedMs, hash, nowMs)
            IntegrityCache.saveEntries(integrityCacheFile, HashMap(integrityEntries))
        }
        if (!saved && integrityCacheFile != null) {
            warnLog("ModelStore: integrity cache write failed for $name, next start will re-hash")
        }
    }

    /**
     * Checks if all specified [files] pass loadability verification.
     *
     * @param files List of candidate files to verify.
     * @return True if every file is loadable.
     */
    fun allLoadable(files: List<File>): Boolean = files.all { checkFile(it).loadable }

    /**
     * Collects non-fatal integrity warning messages for verified files.
     *
     * @return Distinct list of warning messages.
     */
    fun warnings(): List<String> =
        verificationCache.values.map { it.check }.filter { it.verified == false && it.loadable }.map { it.message!! }.distinct()

    /**
     * Collects fatal model load or verification error messages.
     *
     * @return Distinct list of error messages.
     */
    fun errors(): List<String> =
        (verificationCache.values.map { it.check }.filter { !it.loadable }.map { it.message!! } + loadErrors.toList()).distinct()

    /** Records a runtime model load failure so the UI status line can show it. */
    fun recordModelLoadError(message: String) {
        loadErrors.add(message)
    }

    /**
     * Formats an aggregated model readiness and integrity status summary string.
     *
     * @param smsStatus Optional explicit SMS status override.
     * @return Formatted status string.
     */
    @JvmOverloads
    fun statusSummary(smsStatus: String? = null): String {
        val missing = missingModels()

        val resolved = smsStatus ?: this.smsStatus ?: try {
            SentinelApp.instance.pipeline?.smsStatus
        } catch (e: Exception) {
            Log.w(
                TAG,
                "ModelStore: pipeline smsStatus unavailable: ${e::class.simpleName}: ${e.message}",
                e
            )
            null
        } ?: if (isSmsClassifierReady()) "loaded" else "not installed"

        val checks = verificationCache.values.map { it.check }.toList()
        val loaded = checks.filter { it.loadable }.map { it.fileName }.distinct().sorted()
        val refused = checks.filter { !it.loadable }.map { it.fileName }.distinct().sorted()
        return ModelStatus.build(
            ModelStatusInput(
                missing = missing,
                isUrlReady = isUrlClassifierReady(),
                loaded = loaded,
                refused = refused,
                errors = errors(),
                warnings = warnings(),
                isVerifying = isVerifying,
                rulesStatus = rulesStatus,
                smsStatus = resolved
            )
        )
    }

    /** Companion utilities for manifest parsing, hashing, and file verification. */
    companion object {
        private const val TAG = "PS3Sms"
        private const val BUFFER_SIZE = 8192

        /** 100 ms — poll cadence for [awaitVerified] while a background re-hash runs. */
        private const val AWAIT_VERIFY_POLL_INTERVAL_MS: Long = 100L

        /** Asset name shared with the Python package for phone and Linux file names. */
        const val ASSET_NAME: String = "model_files.json"

        /** Asset holding expected SHA-256 hashes bundled with the APK. */
        const val HASHES_ASSET_NAME: String = "models.sha256"

        /** Developer switch in the external models folder: keep the adb-pushed duplicates. */
        const val KEEP_EXTERNAL_FLAG_FILE_NAME: String = "keep_external.on"

        /** External manifest name; never deleted even though it sits beside the imported models. */
        private const val EXTERNAL_MANIFEST_FILE_NAME: String = "models.sha256"

        /** Reads phone names from the bundled asset, falling back to defaults with a warning. */
        fun loadFileNames(context: Context): ModelFileNames {
            return try {
                val text = context.assets.open(ASSET_NAME).bufferedReader(Charsets.UTF_8).use { it.readText() }
                ModelFileNames.fromJson(text)
            } catch (e: Exception) {
                warnLog("ModelStore: failed to load $ASSET_NAME, using defaults: ${e.message}", e)
                ModelFileNames.defaults()
            }
        }

        /** Reads expected hashes from the APK asset; empty when missing or empty, refusing all loads. */
        fun loadExpectedHashes(context: Context): Map<String, String> {
            return try {
                val text =
                    context.assets.open(HASHES_ASSET_NAME).bufferedReader(Charsets.UTF_8).use { it.readText() }
                parseManifestText(text)
            } catch (e: Exception) {
                warnLog("ModelStore: failed to load $HASHES_ASSET_NAME, refusing all: ${e.message}", e)
                emptyMap()
            }
        }

        /** Streams [file] through a digest and returns lowercase hex SHA-256. Never reads whole file. */
        fun sha256Hex(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buffer = ByteArray(BUFFER_SIZE)
                var read = input.read(buffer)
                while (read != -1) {
                    digest.update(buffer, 0, read)
                    read = input.read(buffer)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        /** Parses manifest text of lines "<hex sha256>  <file name>". Blank lines are ignored. */
        fun parseManifestText(text: String): Map<String, String> {
            val entries = linkedMapOf<String, String>()
            text.lineSequence().forEach { line ->
                val trimmed = line.trim()
                if (trimmed.isEmpty()) return@forEach
                val separatorIndex = trimmed.indexOf("  ")
                if (separatorIndex <= 0) {
                    throw IllegalArgumentException("models.sha256: malformed line (expected '<sha256>  <name>')")
                }
                val hash = trimmed.substring(0, separatorIndex).trim()
                val name = trimmed.substring(separatorIndex + 2).trim()
                if (hash.isEmpty() || name.isEmpty()) {
                    throw IllegalArgumentException("models.sha256: malformed line (expected '<sha256>  <name>')")
                }
                if (!hash.matches(Regex("[0-9a-f]{64}"))) {
                    throw IllegalArgumentException(
                        "models.sha256: invalid SHA-256 hash for $name (expected 64 lowercase hex characters)"
                    )
                }
                if (entries.containsKey(name)) {
                    throw IllegalArgumentException("models.sha256: duplicate entry for $name")
                }
                entries[name] = hash
            }
            return entries
        }

        /** Parses a manifest of lines "<hex sha256>  <file name>". Blank lines are ignored. */
        fun parseManifest(manifestFile: File): Map<String, String> {
            if (!manifestFile.exists()) return emptyMap()
            val text = try {
                manifestFile.readText(Charsets.UTF_8)
            } catch (e: Exception) {
                return emptyMap()
            }
            return parseManifestText(text)
        }

        /** Rejects names containing path separators or ".." (path traversal protection). */
        fun isValidModelFileName(name: String): Boolean {
            return name.indexOf('/') < 0 && name.indexOf('\\') < 0 && !name.contains("..")
        }
    }
}

/** True when the SMS files changed since [previous] (size or mtime); a null baseline counts as changed. */
internal fun smsSnapshotsChanged(
    previous: Map<String, ModelStore.SmsFileSnapshot>?,
    current: Map<String, ModelStore.SmsFileSnapshot>
): Boolean = previous == null || previous != current

/**
 * Pure retry decision: returns true when the SMS model is not yet loaded,
 * the status is uninstalled or failed, and the files have changed since the last failed load.
 */
fun shouldRetrySmsLoad(
    isLoaded: Boolean,
    smsStatus: String,
    previousSnapshot: Map<String, ModelStore.SmsFileSnapshot>?,
    currentSnapshot: Map<String, ModelStore.SmsFileSnapshot>
): Boolean {
    if (isLoaded) return false
    if (!smsStatus.startsWith("failed") && smsStatus != "not installed") return false
    return smsSnapshotsChanged(previousSnapshot, currentSnapshot)
}

/** Returns the first 8 hex characters of the SHA-256 of [text]. */
fun sha256Short(text: String): String {
    val digest = MessageDigest.getInstance("SHA-256")
    digest.update(text.toByteArray(Charsets.UTF_8))
    return digest.digest().joinToString("") { "%02x".format(it) }.substring(0, 8)
}

// Log.w is not available in plain JVM unit tests; warnings must never break model loading.
private fun warnLog(msg: String, tr: Throwable? = null) {
    try {
        if (tr != null) Log.w("PS3Sms", msg, tr) else Log.w("PS3Sms", msg)
    } catch (_: RuntimeException) {
    }
}
