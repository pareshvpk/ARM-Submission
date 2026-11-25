// Executes on-device character-level CNN inference for phishing URL detection.
// Uses an ExecuTorch Module loaded from url_cnn_v2.pte with heuristic fallback
// when native acceleration is unavailable or during CPU architecture blocks.

package org.ps3.sentinel.ml

import android.util.Log
import org.ps3.sentinel.core.UrlEncoder
import org.ps3.sentinel.core.UrlResult
import org.ps3.sentinel.core.normaliseUrl
import org.ps3.sentinel.core.urlIndicators
import org.pytorch.executorch.EValue
import org.pytorch.executorch.Module
import org.pytorch.executorch.Tensor
import java.io.File
import kotlin.math.exp

/**
 * Phishing URL detector backed by a character-level CNN ExecuTorch module.
 *
 * Falls back to heuristic URL indicator rules when the model file is missing,
 * unsupported on the current CPU, or fails native initialization.
 *
 * @property threshold Phishing probability cutoff above which a URL is labelled "phishing".
 */
class UrlClassifier(
    private val ptePath: String,
    private val encoder: UrlEncoder,
    // Source of truth: sentinel/data/rules.json fusion.url_phishing_label_threshold.
    // Keep this value in sync with Python; see MlConstantsTest.
    val threshold: Double = URL_PHISHING_THRESHOLD
) {
    /** Constants and logging tags for URL classification. */
    companion object {
        const val URL_PHISHING_THRESHOLD: Double = 0.5
        private const val TAG = "PS3Sms"
    }

    @Volatile
    private var module: Module? = null
    @Volatile
    var loadError: String? = null
        private set

    init {
        val file = File(ptePath)
        if (CpuFeatures.isExecutorchBlocked()) {
            Log.w(TAG, "UrlClassifier: ExecuTorch blocked on this CPU; using URL indicators only")
            module = null
        } else if (file.exists() && file.isFile) {
            try {
                // Explicit thread count matches ModelLoadPlan.selectThreadCount, so a
                // URL load after Llama re-asserts the shared pool instead of shrinking it.
                val threadCount = selectLoadThreadCount()
                module = ExecutorchGate.withExclusive {
                    Module.load(ptePath, Module.LOAD_MODE_FILE, threadCount)
                }
            } catch (e: Throwable) {
                // Native load can throw UnsatisfiedLinkError, an Error; survive it and use indicators.
                loadError = e.message ?: e.toString()
                Log.w(
                    TAG,
                    "UrlClassifier: failed to load URL model model=${sha256Short(ptePath)}: " +
                        "${e::class.simpleName}: ${e.message}",
                    e
                )
                module = null
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
            Log.i("PS3Timing", "url_threads=$threadCount threads_proposal=$proposal threads_used=$threadCount threads_auto=$auto")
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
                "UrlClassifier: rebind after pool reset failed model=${sha256Short(ptePath)}: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            false
        }
    }

    /** Returns true if the native ExecuTorch module was loaded successfully. */
    fun isLoaded(): Boolean = module != null

    /**
     * Scores [url] using the native CNN module or fallback indicator heuristics.
     *
     * Synchronized to serialize native inference between the SMS receiver thread
     * and UI analysis coroutines.
     *
     * @param url Raw input URL string.
     * @return [UrlResult] containing normalized URL, probability, label, and detected indicators.
     */
    @Synchronized // shared Module: SMS receiver thread and Analyse coroutine
    fun score(url: String): UrlResult {
        val norm = normaliseUrl(url)
        val indicators = urlIndicators(url)

        if (module == null) {
            val prob = if ("brand_lookalike" in indicators || "risky_tld" in indicators || "ip_host" in indicators) {
                0.85
            } else if (indicators.isNotEmpty()) {
                0.4
            } else {
                0.05
            }
            val label = if (prob >= 0.5) "phishing" else "benign"
            return UrlResult(
                url = url,
                normUrl = norm,
                prob = prob,
                label = label,
                indicators = indicators
            )
        }

        val encoded = encoder.encode(norm)
        // Detection gate: detection must not run concurrently with background prefix prefill (DT-15).
        // Re-read the field inside the gate so a rebind cannot leave a closed module here.
        val logit = ExecutorchGate.withDetection {
            val mod = module ?: throw IllegalStateException("URL classifier module is not loaded")
            val tensor = Tensor.fromBlob(encoded, longArrayOf(1, encoder.maxLen.toLong()))
            val inputEValue = EValue.from(tensor)
            val outputs = mod.forward(inputEValue)
            val outTensor = outputs[0].toTensor()
            outTensor.dataAsFloatArray[0].toDouble()
        }

        val prob = 1.0 / (1.0 + exp(-logit))
        val label = if (prob >= threshold) "phishing" else "benign"

        return UrlResult(
            url = url,
            normUrl = norm,
            prob = prob,
            label = label,
            indicators = indicators
        )
    }
}
