// Runs multilingual MiniLM SMS classification on-device via ExecuTorch.
// Encodes input text with SmsTokenizer, executes the int8/fp32 exported model graph,
// and produces calibrated probabilities across ham, unwanted, and scam classes.

package org.ps3.sentinel.ml

import android.os.SystemClock
import android.util.Log
import org.ps3.sentinel.core.SmsResult
import org.ps3.sentinel.core.SmsTokenizer
import org.pytorch.executorch.EValue
import org.pytorch.executorch.Module
import org.pytorch.executorch.Tensor
import java.io.BufferedReader
import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.io.InputStreamReader
import kotlin.math.exp

private fun nowMs(): Long {
    return try {
        SystemClock.elapsedRealtime()
    } catch (_: Exception) {
        System.nanoTime() / 1_000_000L
    }
}

private class SmsInitParts(
    val tokenizer: SmsTokenizer,
    val idMap: IntArray?,
    val tokenizerMs: Long,
    val idMapMs: Long
)

/**
 * Multilingual SMS threat classifier running on-device via ExecuTorch.
 *
 * Runs tokenized SMS text through an int8 or fp32 MiniLM model to estimate
 * probabilities for ham, unwanted promotion, and scam categories.
 *
 * @property tokenizer Subword tokenizer producing token sequences and attention masks.
 * @property idMap Optional vocabulary remapping array for optimized token indices.
 */
class SmsClassifier private constructor(
    private val ptePath: String,
    parts: SmsInitParts
) {
    val tokenizer: SmsTokenizer = parts.tokenizer
    val idMap: IntArray? = parts.idMap
    @Volatile
    private var module: Module? = null
    @Volatile
    var loadError: String? = null
        private set

    private val tokenizerMs: Long = parts.tokenizerMs
    private val idMapMs: Long = parts.idMapMs
    private var moduleLoadMs: Long = 0L
    private var gateWaitMs: Long = 0L

    /**
     * Constructs a classifier with pre-loaded tokenizer and optional idMap.
     *
     * @param ptePath File path to the exported ExecuTorch .pte model file.
     * @param tokenizer Configured tokenizer instance.
     * @param idMap Optional token ID mapping table.
     */
    constructor(
        ptePath: String,
        tokenizer: SmsTokenizer,
        idMap: IntArray? = null
    ) : this(ptePath, SmsInitParts(tokenizer, idMap, 0L, 0L))

    /**
     * Constructs a classifier, initializing the tokenizer and idMap from files.
     *
     * @param ptePath File path to the exported ExecuTorch .pte model file.
     * @param idMapPath Optional path to id_map.json file.
     * @param vocabPath Path to vocabulary text file.
     * @param cacheDir Optional cache directory for pre-tokenized binary assets.
     */
    constructor(
        ptePath: String,
        idMapPath: String?,
        vocabPath: String,
        cacheDir: File? = null
    ) : this(ptePath, loadTimedParts(idMapPath, vocabPath, cacheDir))

    init {
        val file = File(ptePath)
        if (CpuFeatures.isExecutorchBlocked()) {
            loadError = CpuFeatures.EXECUTORCH_BLOCKED_STATUS
            module = null
            warnLog("SmsClassifier load blocked: ${CpuFeatures.EXECUTORCH_BLOCKED_STATUS}")
        } else if (!file.exists()) {
            loadError = "Model file does not exist: $ptePath"
            warnLog("SmsClassifier load failed: file does not exist ($ptePath)")
        } else if (!file.isFile) {
            loadError = "Model path is not a file: $ptePath"
            warnLog("SmsClassifier load failed: path is not a file ($ptePath)")
        } else {
            try {
                // Explicit thread count matches ModelLoadPlan.selectThreadCount, so an
                // SMS load after Llama re-asserts the shared pool instead of shrinking it.
                val threadCount = selectLoadThreadCount()
                val loadStart = nowMs()
                var acquiredMs = loadStart
                try {
                    module = ExecutorchGate.withExclusive {
                        acquiredMs = nowMs()
                        Module.load(ptePath, Module.LOAD_MODE_FILE, threadCount)
                    }
                } finally {
                    val afterMs = nowMs()
                    moduleLoadMs = afterMs - loadStart
                    gateWaitMs = acquiredMs - loadStart
                }
            } catch (e: Throwable) {
                // Native load can throw UnsatisfiedLinkError, an Error; survive it and record loadError.
                module = null
                loadError = e.message ?: e.toString()
                warnLog("SmsClassifier load failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }
    }

    private fun selectLoadThreadCount(): Int {
        val modelsDir = try { File(ptePath).parentFile } catch (_: Exception) { null }
        val clusters = try { CpuFeatures.currentClusters() } catch (_: Exception) { emptyList() }
        val proposal = try { CpuFeatures.proposeThreadCount(clusters) } catch (_: Exception) { 4 }
        val available = Runtime.getRuntime().availableProcessors()
        val threadCount = ModelLoadPlan.selectThreadCountWithAuto(available, clusters, modelsDir)
        try {
            val auto = ModelLoadPlan.isThreadsAutoEnabled(modelsDir)
            Log.i("PS3Timing", "sms_threads=$threadCount threads_proposal=$proposal threads_used=$threadCount threads_auto=$auto")
        } catch (_: Exception) {
        }
        return threadCount
    }

    /**
     * Rebuilds the native Module after a shared-pool reset so its XNNPACK runtime binds to the
     * live pthreadpool. The caller must already hold ExecutorchGate.withExclusive. Returns true
     * when the module was already null (nothing to rebind) or the reload succeeded.
     */
    fun rebindAfterPoolReset(): Boolean {
        val old = module
        if (old == null) return true
        return try {
            val threadCount = selectLoadThreadCount()
            val fresh = Module.load(ptePath, Module.LOAD_MODE_FILE, threadCount)
            module = fresh
            try {
                old.close()
            } catch (_: Throwable) {
            }
            true
        } catch (e: Throwable) {
            // The old runtime points at the freed pool, so it is never kept.
            module = null
            loadError = e.message ?: e.toString()
            Log.w(
                TAG,
                "SmsClassifier: rebind after pool reset failed model=${sha256Short(ptePath)}: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            false
        }
    }

    /** Returns true if the underlying ExecuTorch module is currently loaded. */
    fun isLoaded(): Boolean = module != null

    /**
     * True when the pte was exported with a dynamic sequence dim (export_sms.py --dynamic-seq),
     * so messages run at their real token length instead of padded to 128. Probed once.
     */
    val isDynamic: Boolean by lazy {
        if (module == null) return@lazy false
        val probeStart = nowMs()
        var probeMsLocal = 0L
        var result = false
        try {
            // Shared gate: this probe forward runs on the shared pool a load can reset.
            // Re-read the field inside the gate so a rebind cannot leave a closed module here.
            ExecutorchGate.withShared {
                val mod = module ?: throw IllegalStateException("SMS classifier module is not loaded")
                val probe = Tensor.fromBlob(LongArray(16) { 1L }, longArrayOf(1, 16))
                mod.forward(EValue.from(probe), EValue.from(probe))
            }
            result = true
        } catch (e: Throwable) {
            // Native forward can throw UnsatisfiedLinkError, an Error; survive it and use padded input.
            Log.w(
                TAG,
                "SmsClassifier: dynamic probe failed model=${sha256Short(ptePath)}: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            result = false
        } finally {
            probeMsLocal = nowMs() - probeStart
        }
        try {
            Log.i("PS3Timing", "sms_init_split tokenizer_ms=$tokenizerMs idmap_ms=$idMapMs module_load_ms=$moduleLoadMs probe_ms=$probeMsLocal gate_wait_ms=$gateWaitMs")
        } catch (_: Exception) {
            // Logging must not break the classifier on stubbed platforms (JVM unit tests).
        }
        result
    }

    // One ExecuTorch Module, two callers (SMS receiver thread, Analyse coroutine): forward is not thread-safe.
    /**
     * Classifies [text] into ham, unwanted, or scam categories.
     *
     * Synchronized to prevent concurrent ExecuTorch module forward evaluations.
     *
     * @param text Raw SMS message body.
     * @return [SmsResult] containing calibrated category probabilities and dominant label.
     * @throws IllegalStateException if the model module failed to load.
     */
    @Synchronized
    fun predict(text: String): SmsResult {
        if (module == null) throw IllegalStateException("SMS classifier module is not loaded")

        val encoded = tokenizer.encode(text, pad = !isDynamic)
        val inputIds = if (idMap != null && idMap.isNotEmpty()) {
            val mapped = LongArray(encoded.inputIds.size)
            val fallback = idMap[0].toLong()
            for (i in encoded.inputIds.indices) {
                val orig = encoded.inputIds[i]
                mapped[i] = if (orig >= 0 && orig < idMap.size) {
                    idMap[orig.toInt()].toLong()
                } else {
                    fallback
                }
            }
            mapped
        } else {
            encoded.inputIds
        }

        val shape = longArrayOf(1, encoded.inputIds.size.toLong())
        // Detection gate: detection must not run concurrently with background prefix prefill (DT-15).
        // Re-read the field inside the gate so a rebind cannot leave a closed module here.
        val floatData = ExecutorchGate.withDetection {
            val mod = module ?: throw IllegalStateException("SMS classifier module is not loaded")
            val inIdsTensor = Tensor.fromBlob(inputIds, shape)
            val inMaskTensor = Tensor.fromBlob(encoded.attentionMask, shape)
            val outputs = mod.forward(EValue.from(inIdsTensor), EValue.from(inMaskTensor))
            outputs[0].toTensor().dataAsFloatArray
        }

        val logitHam = floatData[SMS_LABEL_HAM].toDouble()
        val logitUnwanted = floatData[SMS_LABEL_UNWANTED].toDouble()
        val logitScam = floatData[SMS_LABEL_SCAM].toDouble()

        val maxLogit = maxOf(logitHam, maxOf(logitUnwanted, logitScam))
        val e0 = exp(logitHam - maxLogit)
        val e1 = exp(logitUnwanted - maxLogit)
        val e2 = exp(logitScam - maxLogit)
        val sumExp = e0 + e1 + e2

        val probs = mapOf(
            "ham" to (e0 / sumExp),
            "unwanted" to (e1 / sumExp),
            "scam" to (e2 / sumExp)
        )

        val label = probs.maxByOrNull { it.value }?.key ?: "ham"
        return SmsResult(probs = probs, label = label)
    }

    /** Companion constants and vocabulary mapping loaders for SMS classification. */
    companion object {
        private const val TAG = "PS3Sms"
        // Source of truth: sentinel/detectors.py predict() builds probs as
        // {ham: index 0, unwanted: index 1, scam: index 2}. Keep these in sync with Python; see MlConstantsTest.
        const val SMS_LABEL_HAM: Int = 0
        const val SMS_LABEL_UNWANTED: Int = 1
        const val SMS_LABEL_SCAM: Int = 2

        private fun loadTimedParts(idMapPath: String?, vocabPath: String, cacheDir: File? = null): SmsInitParts {
            val tokenizerStart = nowMs()
            val vocabFile = File(vocabPath)
            val effectiveCacheDir = cacheDir ?: try { vocabFile.parentFile } catch (_: Exception) { null }
            val tokenizer = SmsTokenizer.fromFile(vocabFile, cacheDir = effectiveCacheDir)
            val tokenizerMs = nowMs() - tokenizerStart
            var idMap: IntArray? = null
            var idMapMs = 0L
            if (idMapPath != null) {
                val idFile = File(idMapPath)
                if (idFile.exists()) {
                    val idStart = nowMs()
                    idMap = loadIdMap(idFile)
                    idMapMs = nowMs() - idStart
                }
            }
            return SmsInitParts(tokenizer, idMap, tokenizerMs, idMapMs)
        }

        /**
         * Loads a token remapping array from [file].
         *
         * @param file JSON or text file containing token ID integers.
         * @return Array of mapped token IDs.
         */
        fun loadIdMap(file: File): IntArray {
            return FileInputStream(file).use { loadIdMapFromStream(it) }
        }

        /**
         * Parses a token remapping array from an [InputStream].
         *
         * @param stream Input stream containing integer token mappings.
         * @return Array of mapped token IDs.
         */
        fun loadIdMapFromStream(stream: InputStream): IntArray {
            val ints = ArrayList<Int>(260000)
            BufferedReader(InputStreamReader(stream, Charsets.UTF_8), 65536).use { reader ->
                var num = 0
                var inNum = false
                var sign = 1
                var ch = reader.read()
                while (ch != -1) {
                    val c = ch.toChar()
                    if (c in '0'..'9') {
                        num = num * 10 + (c - '0')
                        inNum = true
                    } else if (c == '-') {
                        sign = -1
                    } else {
                        if (inNum) {
                            ints.add(sign * num)
                            num = 0
                            sign = 1
                            inNum = false
                        }
                    }
                    ch = reader.read()
                }
                if (inNum) {
                    ints.add(sign * num)
                }
            }
            return ints.toIntArray()
        }
    }
}

// Log.w is not available in plain JVM unit tests; warnings must never break model loading.
private fun warnLog(msg: String, tr: Throwable? = null) {
    try {
        if (tr != null) Log.w("PS3Sms", msg, tr) else Log.w("PS3Sms", msg)
    } catch (_: RuntimeException) {
    }
}
