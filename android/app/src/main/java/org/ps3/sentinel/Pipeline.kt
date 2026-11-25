/**
 * Orchestrates end-to-end SMS message detection and actionable safety advice.
 * Coordinates URL extraction, character-CNN scoring, regex cue matching, and ExecuTorch SMS classification.
 * Integrates on-device Llama 3.2 1B generation with streaming sentence filtering and template fallback.
 */
package org.ps3.sentinel

import org.ps3.sentinel.core.CueSpan
import org.ps3.sentinel.core.Detector
import org.ps3.sentinel.core.DetectorPart
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.PROMOTION_ADVICE
import org.ps3.sentinel.core.SmsResult
import org.ps3.sentinel.core.StreamingAdviceFilter
import org.ps3.sentinel.core.UrlResult
import org.ps3.sentinel.core.extractUrls
import org.ps3.sentinel.core.fuse
import org.ps3.sentinel.core.isPlainPromotion
import org.ps3.sentinel.core.normaliseUrl
import org.ps3.sentinel.core.runExtraDetectors
import org.ps3.sentinel.core.senderCue
import org.ps3.sentinel.core.smsCues
import org.ps3.sentinel.core.templateAdvice
import org.ps3.sentinel.core.urlIndicators
import org.ps3.sentinel.ml.CpuFeatures
import org.ps3.sentinel.ml.ExecutorchGate
import org.ps3.sentinel.ml.LlamaAdvisor
import org.ps3.sentinel.ml.ModelLoadPlan
import org.ps3.sentinel.ml.UrlClassifier
import org.ps3.sentinel.ml.ModelStore
import org.ps3.sentinel.ml.SmsClassifier
import org.ps3.sentinel.ml.sha256Short
import org.ps3.sentinel.ml.smsSnapshotsChanged
import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/** Execution timings across detection, cue extraction, model inference, and Llama generation. */
data class PipelineTimings(
    val urlExtractionMs: Double,
    val urlDetectionMs: Double,
    val cuesMs: Double,
    val smsDetectionMs: Double,
    val fusionMs: Double,
    val advisorMs: Double,
    val totalMs: Double,
    val decodeTokensPerSec: Double? = null
) {
    /** Serializes timings into a map representation for logging and debugging. */
    fun toMap(): Map<String, Any?> = mapOf(
        "url_extraction_ms" to urlExtractionMs,
        "url_detection_ms" to urlDetectionMs,
        "cues_ms" to cuesMs,
        "sms_detection_ms" to smsDetectionMs,
        "fusion_ms" to fusionMs,
        "advisor_ms" to advisorMs,
        "total_ms" to totalMs,
        "decode_tokens_per_sec" to decodeTokensPerSec
    )
}

/** Full output of message analysis containing evidence, advice, source label, and performance timings. */
data class PipelineResult(
    val evidence: Evidence,
    val advice: String,
    val adviceSource: String, // "llm", "template", or "template_timeout"
    val timingsMs: PipelineTimings,
    val smsResult: SmsResult? = null,
    val isPlainPromotion: Boolean = false
)

/** Intermediate output from the detection phase prior to advice generation. */
data class DetectionResult(
    val evidence: Evidence,
    val timingsMs: PipelineTimings,
    val smsResult: SmsResult? = null
)

/** Generated safety advice along with source indicator and decoding metrics. */
data class AdviceResult(
    val advice: String,
    val adviceSource: String,
    val advisorMs: Double,
    val decodeTokensPerSec: Double? = null
)

/**
 * Purpose:  Orchestrates detection and advice for one message.
 * Owns:     The SMS classifier handle after warm-up.
 * Lifetime: Process
 * Thread:   any — SMS predict is synchronized inside SmsClassifier.
 */
class Pipeline(
    @Volatile private var urlClassifier: UrlClassifier? = null,
    @Volatile private var llamaAdvisor: LlamaAdvisor? = null,
    @Volatile private var smsClassifier: SmsClassifier? = null
) {
    @Volatile
    private var smsWarmUpDone: Boolean = false
    private val warmUpRunning = java.util.concurrent.atomic.AtomicBoolean(false)
    // Size/mtime snapshot of the SMS files at the last failed load, or null when
    // no baseline was captured. A resume retry happens only when this differs
    // from the current snapshot, so unchanged files are never re-hashed.
    @Volatile
    private var failedSmsSnapshot: Map<String, ModelStore.SmsFileSnapshot>? = null
    @Volatile
    private var _smsStatus: String = "not installed"
    var smsStatus: String
        get() = _smsStatus
        private set(value) {
            _smsStatus = value
            if (value.startsWith("failed") || value == "not installed") {
                failedSmsSnapshot = try {
                    SentinelApp.instance.modelStore.smsFileSnapshot()
                } catch (e: Exception) {
                    logWarning("Pipeline: SMS failure snapshot failed: ${e::class.simpleName}: ${e.message}", e)
                    null
                }
            }
            try {
                SentinelApp.instance.modelStore.smsStatus = value
            } catch (e: Exception) {
                Log.w(TAG, "Pipeline: modelStore.smsStatus update failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }

    companion object {
        private const val TAG = "PS3Sms"
        private const val TIMING_TAG = "PS3Timing"
        private const val INTEGRITY_TAG = "PS3Integrity"
        // 50 ms — poll cadence for awaitSmsReady: short enough to notice a
        // warm SMS model promptly without spinning the little-core cpuset.
        private const val SMS_READY_POLL_INTERVAL_MS: Long = 50L
    }

    init {
        // No model loading here: Pipeline is built in Application.onCreate on the main thread, and loading
        // the SMS model there (51 MB pte + 6 MB vocab + probe) added about 3.9 s to cold start on the F14.
        // Call warmUp() from a background thread instead.
        if (CpuFeatures.isExecutorchBlocked()) {
            smsStatus = CpuFeatures.EXECUTORCH_BLOCKED_STATUS
        } else if (smsClassifier != null) {
            if (smsClassifier!!.isLoaded()) {
                smsStatus = if (smsClassifier!!.isDynamic) "loaded (real length)" else "loaded (padded 128)"
            } else {
                val err = smsClassifier!!.loadError ?: "model failed to load"
                smsStatus = "failed: $err"
                logWarning("SMS classifier failed to load: $err")
            }
        } else {
            smsStatus = try {
                if (SentinelApp.instance.modelStore.isSmsClassifierReady()) "loading" else "not installed"
            } catch (e: Exception) {
                Log.w(TAG, "Pipeline: SMS readiness check failed: ${e::class.simpleName}: ${e.message}", e)
                "not installed"
            }
        }
    }

    /** Loads the SMS model if needed. Blocking and synchronized: call it off the main thread. */
    fun warmUp() {
        if (!warmUpRunning.compareAndSet(false, true)) {
            return
        }
        smsWarmUpDone = false
        try {
            getOrInitSmsClassifier()
        } finally {
            smsWarmUpDone = true
            warmUpRunning.set(false)
        }
        try {
            org.ps3.sentinel.sms.SmsReceiver.retryPendingAnalysis()
        } catch (e: Exception) {
            logWarning("Pipeline: deferred retry trigger failed: ${e::class.simpleName}: ${e.message}", e)
        }
        try {
            SentinelApp.instance.modelStore.notifyVerificationFinished()
        } catch (e: Exception) {
            Log.w(TAG, "Pipeline: verification listener failed: ${e::class.simpleName}: ${e.message}", e)
        }
    }

    /**
     * Retries a failed SMS load when its files changed (size or mtime) since
     * the failure. Blocking: call it off the main thread. Returns true when a
     * retry was attempted. Unchanged files are never re-hashed: the snapshot
     * check is metadata only, and verifyForLoad reuses its per-process cache
     * for files whose size/mtime are unchanged.
     */
    @Synchronized
    @JvmOverloads
    fun retrySmsLoadIfFilesChanged(async: Boolean = false): Boolean {
        if (isSmsModelLoaded()) return false
        if (!smsStatus.startsWith("failed") && smsStatus != "not installed") return false
        if (warmUpRunning.get()) return false
        val store = try {
            SentinelApp.instance.modelStore
        } catch (e: Exception) {
            logWarning("Pipeline: SMS retry skipped, modelStore unavailable: ${e::class.simpleName}: ${e.message}", e)
            return false
        }
        if (!store.isSmsClassifierReady()) return false
        val currentSnapshot = store.smsFileSnapshot()
        if (!org.ps3.sentinel.ml.shouldRetrySmsLoad(isSmsModelLoaded(), smsStatus, failedSmsSnapshot, currentSnapshot)) return false
        logWarning("Pipeline: retrying SMS model load (files changed since last attempt)")
        failedSmsSnapshot = null
        smsStatus = "loading"
        smsWarmUpDone = false
        if (async) {
            Thread({ warmUp() }, "ps3-sms-warmup").apply { isDaemon = true }.start()
        } else {
            warmUp()
        }
        return true
    }

    /** Retries a failed SMS load asynchronously on a background thread when files changed. */
    fun retrySmsLoadIfFilesChangedAsync(): Boolean = retrySmsLoadIfFilesChanged(async = true)

    /** Attaches the Llama advisor once the deferred load finishes. */
    fun attachLlamaAdvisor(advisor: LlamaAdvisor?) {
        llamaAdvisor = advisor
    }

    /** Attaches the URL classifier once a deferred load finishes. */
    fun attachUrlClassifier(classifier: UrlClassifier?) {
        urlClassifier = classifier
    }

    /**
     * Rebinds the SMS classifier to the live ExecuTorch pool after a Llama load reset it.
     * The caller already holds ExecutorchGate.withExclusive. Returns ok, fail or none for logging.
     */
    fun rebindClassifiersAfterPoolReset(): String {
        val classifier = smsClassifier ?: return "none"
        return try {
            if (classifier.rebindAfterPoolReset()) "ok" else "fail"
        } catch (e: Throwable) {
            logWarning(
                "Pipeline: SMS rebind after pool reset failed: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            "fail"
        }
    }

    /** Returns the live URL classifier, picking up models loaded after construction. */
    private fun currentUrlClassifier(): UrlClassifier? {
        return try {
            SentinelApp.instance.urlClassifier
        } catch (e: Exception) {
            urlClassifier
        }
    }

    /** True once a warm-up attempt has settled, loaded or failed. */
    fun isSmsWarmUpDone(): Boolean = smsWarmUpDone

    /** Waits up to timeoutMs for the SMS model to load; never longer. */
    fun awaitSmsReady(timeoutMs: Long): Boolean {
        val deadlineMs = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadlineMs) {
            if (isSmsModelLoaded()) {
                return true
            }
            if (smsWarmUpDone) {
                return isSmsModelLoaded()
            }
            try {
                Thread.sleep(SMS_READY_POLL_INTERVAL_MS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return isSmsModelLoaded()
            }
        }
        return isSmsModelLoaded()
    }

    private fun logWarning(msg: String, tr: Throwable? = null) {
        try {
            if (tr != null) {
                Log.w(TAG, msg, tr)
            } else {
                Log.w(TAG, msg)
            }
        } catch (e: Exception) {
            // Logging itself failed; nothing more to do, but avoid swallowing silently without a trace.
            // (No further logging is possible here.)
        }
    }

    @Synchronized
    private fun getOrInitSmsClassifier(): SmsClassifier? {
        if (smsClassifier != null) {
            return if (smsClassifier!!.isLoaded()) smsClassifier else null
        }
        if (CpuFeatures.isExecutorchBlocked()) {
            smsStatus = CpuFeatures.EXECUTORCH_BLOCKED_STATUS
            return null
        }
        val store = try {
            SentinelApp.instance.modelStore
        } catch (e: Exception) {
            Log.w(TAG, "Pipeline: modelStore access failed: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        if (store == null) {
            val err = "modelStore unavailable"
            smsStatus = "failed: $err"
            logWarning("SMS classifier load failed: $err")
            Log.i(TIMING_TAG, "sms_load_failed reason=model_store_unavailable")
            return null
        }
        if (smsStatus.startsWith("failed")) {
            // Retry a failed load only when the SMS files changed (size or
            // mtime) since the failure; unchanged files are never re-hashed.
            if (!store.isSmsClassifierReady()) return null
            if (!smsSnapshotsChanged(failedSmsSnapshot, store.smsFileSnapshot())) return null
            failedSmsSnapshot = null
            smsStatus = "loading"
        }
        val cpuFlags = CpuFeatures.currentFlags()
        var pteFile: java.io.File? = store.smsModelFileFor(cpuFlags)
        if (pteFile == null) {
            val err = "model file not found for CPU (asimddp=${cpuFlags.asimddp})"
            smsStatus = "failed: $err"
            logWarning("SMS classifier load failed: $err")
            Log.i(TIMING_TAG, "sms_load_failed reason=no_model_file asimddp=${cpuFlags.asimddp}")
            return null
        }
        // Hash the SMS files before the first load. getOrInitSmsClassifier runs inside warmUp on a
        // background thread, so the integrity check never blocks the main thread. Never load an
        // unverified model: an fp32 model with no expected hash or a failed verification falls back
        // to the verified int8 model.
        var isFp32 = pteFile!!.name == store.fileNames.smsFp32
        if (isFp32 && !store.expectedHashes.containsKey(pteFile!!.name)) {
            Log.w(TAG, "Pipeline: ${pteFile!!.name} has no expected hash; trying verified ${store.fileNames.smsModel}")
            val fallback = store.smsModelFileFor(cpuFlags.copy(asimddp = true))
            if (fallback == null || fallback.name == pteFile!!.name) {
                val err = "SMS classifier refused: ${pteFile!!.name} has no expected hash and no verified fallback"
                smsStatus = "failed: $err"
                logWarning("SMS classifier refused: $err")
                return null
            }
            Log.w(TAG, "Pipeline: falling back from ${pteFile!!.name} to ${fallback.name} (unverified fp32)")
            pteFile = fallback
            isFp32 = false
        }
        Log.i(
            TIMING_TAG,
            "sms_model_choice=${pteFile!!.name} dot_product=${cpuFlags.asimddp} fp32_available=${store.isSmsFp32Available()}"
        )
        val verifyStartMs = SystemClock.elapsedRealtime()
        var failure = store.verifyForLoad(listOf(pteFile!!, store.idMapFile, store.smsVocabFile))
        Log.i(TIMING_TAG, "integrity_verify_model=sms ms=${SystemClock.elapsedRealtime() - verifyStartMs}")
        if (failure != null && isFp32 && failure.fileName == pteFile!!.name) {
            Log.w(TAG, "Pipeline: ${pteFile!!.name} failed verification; trying verified ${store.fileNames.smsModel}")
            val fallback = store.smsModelFileFor(cpuFlags.copy(asimddp = true))
            if (fallback != null && fallback.name != pteFile!!.name) {
                Log.w(TAG, "Pipeline: falling back from ${pteFile!!.name} to ${fallback.name} (fp32 verification failed)")
                pteFile = fallback
                isFp32 = false
                failure = store.verifyForLoad(listOf(pteFile!!, store.idMapFile, store.smsVocabFile))
            }
        }
        if (failure != null) {
            val err = failure.message ?: "model failed integrity verification"
            smsStatus = "failed: $err"
            logWarning("SMS classifier refused: $err")
            return null
        }
        val loadStartMs = SystemClock.elapsedRealtime()
        try {
            val classifier = SmsClassifier(
                ptePath = pteFile!!.absolutePath,
                idMapPath = store.idMapFile.absolutePath,
                vocabPath = store.smsVocabFile.absolutePath
            )
            if (classifier.isLoaded()) {
                smsClassifier = classifier
                smsStatus = if (classifier.isDynamic) "loaded (real length)" else "loaded (padded 128)"
                return classifier
            } else {
                val err = classifier.loadError ?: "model failed to load"
                smsStatus = "failed: $err"
                logWarning("SMS classifier failed to load: $err")
                return null
            }
        } catch (e: UnsatisfiedLinkError) {
            // Native library missing or incompatible: this is an Error, not an Exception, but loading must
            // not crash the receiver path, so catch this specific type.
            val err = e.message ?: e.toString()
            smsStatus = "failed: $err"
            logWarning("SMS classifier failed to load: $err", e)
            return null
        } catch (e: Exception) {
            val err = e.message ?: e.toString()
            smsStatus = "failed: $err"
            logWarning("SMS classifier failed to load: $err", e)
            return null
        } finally {
            Log.i(TIMING_TAG, "model_load_model=sms ms=${SystemClock.elapsedRealtime() - loadStartMs}")
        }
    }

    private fun runSms(text: String): SmsResult? {
        val result = runSmsDetailed(text)
        return result.first
    }

    /** Runs the SMS classifier, reporting whether predict threw (second = error). */
    private fun runSmsDetailed(text: String): Pair<SmsResult?, Boolean> {
        val classifier = getOrInitSmsClassifier()
        if (classifier == null || !classifier.isLoaded()) {
            return Pair(null, false)
        }
        return try {
            Pair(classifier.predict(text), false)
        } catch (e: UnsatisfiedLinkError) {
            // Native inference can throw an Error; survive it so one bad message does not kill the receiver.
            logWarning("SMS prediction failed: ${e::class.simpleName}: ${e.message}", e)
            Pair(null, true)
        } catch (e: Exception) {
            logWarning("SMS prediction failed: ${e::class.simpleName}: ${e.message}", e)
            Pair(null, true)
        }
    }

    /** Fuse without ever throwing, retrying rule-only and never returning confident low on total failure. */
    private fun safeFuse(
        text: String,
        smsResult: SmsResult?,
        urlResults: List<UrlResult>,
        cues: List<CueSpan>,
        extraParts: List<DetectorPart> = emptyList(),
        sender: String? = null
    ): Evidence {
        return try {
            fuse(text, smsResult, urlResults, cues, extraParts = extraParts, sender = sender)
        } catch (e: Exception) {
            Log.w(TAG, "safe_fuse: fusion attempt failed (${e::class.simpleName}); trying fallback")
            try {
                val evidence = fuse(text, null, urlResults, cues, extraParts = extraParts, sender = sender)
                return if ("analysis_error" in evidence.indicators) evidence
                    else evidence.copy(indicators = evidence.indicators + "analysis_error")
            } catch (e2: Exception) {
                Log.w(TAG, "safe_fuse: fusion attempt failed (${e2::class.simpleName}); trying fallback")
                try {
                    val evidence = fuse(text, null, emptyList(), cues, extraParts = extraParts, sender = sender)
                    return if ("analysis_error" in evidence.indicators) evidence
                        else evidence.copy(indicators = evidence.indicators + "analysis_error")
                } catch (e3: Exception) {
                    Log.w(TAG, "safe_fuse: fusion attempt failed (${e3::class.simpleName}); trying fallback")
                    return Evidence(
                        label = "unwanted",
                        risk = 0.4,
                        level = "medium",
                        threshold = 0.7,
                        indicators = listOf("analysis_error")
                    )
                }
            }
        }
    }

    /** Appends SMS failure indicators to evidence when the SMS model threw. */
    private fun withSmsErrorIndicators(evidence: Evidence, smsError: Boolean): Evidence {
        if (!smsError) return evidence
        val indicators = evidence.indicators.toMutableList()
        if ("sms_model_error" !in indicators) indicators.add("sms_model_error")
        if ("analysis_error" !in indicators) indicators.add("analysis_error")
        return evidence.copy(indicators = indicators)
    }
    /** URL model when loaded, else indicator heuristics. A model error is logged and surfaced, never silent. */
    private fun scoreUrls(urls: List<String>): List<UrlResult> {
        val classifier = currentUrlClassifier()
        return urls.map { u ->
        var urlModelError = false
        if (classifier != null && classifier.isLoaded()) {
            try {
                return@map classifier.score(u)
            } catch (e: UnsatisfiedLinkError) {
                urlModelError = true
                logWarning("URL model failed on ${shortDigest(u)}, using indicators: ${e.message}", e)
            } catch (e: Exception) {
                urlModelError = true
                logWarning("URL model failed on ${shortDigest(u)}, using indicators: ${e.message}", e)
            }
        }
        val ind = urlIndicators(u)
        val prob = when {
            "brand_lookalike" in ind || "risky_tld" in ind || "ip_host" in ind -> 0.85
            ind.isNotEmpty() -> 0.4
            else -> 0.05
        }
        UrlResult(u, normaliseUrl(u), prob, if (prob >= 0.5) "phishing" else "benign", urlFallbackIndicators(ind, urlModelError))
        }
    }

    /** Cues plus the sender_mismatch cue when the sender is a personal number. */
    private fun cuesWithSender(text: String, sender: String?): List<CueSpan> {
        val cues = smsCues(text)
        if (sender == null) return cues
        val cue = senderCue(sender, text) ?: return cues
        return cues + cue
    }

    /**
     * Executes the detection phase: extracts URLs, calculates cues, runs SMS classification, and fuses evidence.
     *
     * @param text Raw SMS text to evaluate.
     * @param extraDetectors Optional additional detectors to run.
     * @param sender Optional sender address for mismatch checking.
     * @return [DetectionResult] containing fused evidence and phase timings.
     */
    fun detect(text: String, extraDetectors: List<Detector> = emptyList(), sender: String? = null): DetectionResult {
        // DT-18: detection has started, so the LIGHT re-prefill idle timer restarts.
        ExecutorchGate.markDetectionExpected()
        val tStart = System.nanoTime()

        val t0 = System.nanoTime()
        val extractedUrls = extractUrls(text)
        val urlExtractionMs = (System.nanoTime() - t0) / 1_000_000.0

        val t1 = System.nanoTime()
        val urlResults = scoreUrls(extractedUrls)
        val urlDetectionMs = (System.nanoTime() - t1) / 1_000_000.0

        val t2 = System.nanoTime()
        val cues = cuesWithSender(text, sender)
        val cuesMs = (System.nanoTime() - t2) / 1_000_000.0

        val t3 = System.nanoTime()
        val smsDetailed = runSmsDetailed(text)
        val smsResult: SmsResult? = smsDetailed.first
        val smsError = smsDetailed.second
        val smsDetectionMs = (System.nanoTime() - t3) / 1_000_000.0

        val t4 = System.nanoTime()
        val extraParts = runExtraDetectors(text, extraDetectors)
        val evidence = withSmsErrorIndicators(safeFuse(text, smsResult, urlResults, cues, extraParts, sender), smsError)
        val fusionMs = (System.nanoTime() - t4) / 1_000_000.0

        val timings = PipelineTimings(
            urlExtractionMs = round3(urlExtractionMs),
            urlDetectionMs = round3(urlDetectionMs),
            cuesMs = round3(cuesMs),
            smsDetectionMs = round3(smsDetectionMs),
            fusionMs = round3(fusionMs),
            advisorMs = round3(0.0),
            totalMs = round3((System.nanoTime() - tStart) / 1_000_000.0),
            decodeTokensPerSec = null
        )
        ExecutorchGate.markActivityEnded()
        return DetectionResult(evidence, timings, smsResult)
    }

    /**
     * Produces localized or Llama-generated advice for the given [evidence].
     *
     * @param text Original message text.
     * @param evidence Fused detection evidence.
     * @param onLlamaToken Optional callback invoked for each filtered token emitted by Llama.
     * @param fixedAdvice Optional pre-rendered advice (e.g. Tamil or Hindi) to bypass Llama.
     * @return [AdviceResult] containing advice text and generation performance metrics.
     */
    suspend fun advise(
        text: String,
        evidence: Evidence,
        onLlamaToken: ((String) -> Unit)? = null,
        fixedAdvice: String? = null
    ): AdviceResult {
        // DT-18 second fix: advice is pending until it finishes or fails, so
        // a background re-prefill must not start during it; ending it
        // records the activity end the LIGHT idle delay counts from. This
        // also covers a template advice being shown without Llama.
        ExecutorchGate.beginAdvice()
        try {
            val t5 = System.nanoTime()
            var advice: String
            var adviceSource: String
            var decodeTps: Double? = null

            if (fixedAdvice != null) {
                // Tamil/Hindi: fixed localized advice replaces Llama entirely.
                advice = fixedAdvice
                adviceSource = "template"
            } else if (isPlainPromotion(text, evidence)) {
                advice = PROMOTION_ADVICE
                adviceSource = "template"
            } else {
                val advisor = awaitLlamaAdvisor(evidence.level)
                if (advisor != null && advisor.isLoaded() && evidence.level in setOf("medium", "high")) {
                    // Gate every token on SHA-256 for this process: a Llama file
                    // trusted on size/mtime is still being re-hashed in the
                    // background, so no output may stream before that passes.
                    if (awaitLlamaVerified()) {
                        val filteredToken = streamToken(evidence, onLlamaToken)
                        val advRes = advisor.generate(text, evidence, filteredToken)
                        advice = advRes.advice
                        adviceSource = advRes.source
                        decodeTps = advRes.stats?.decodeTokensPerSec
                    } else {
                        advice = templateAdvice(evidence)
                        adviceSource = "template"
                    }
                } else {
                    advice = templateAdvice(evidence)
                    adviceSource = "template"
                }
            }
            val advisorMs = (System.nanoTime() - t5) / 1_000_000.0
            return AdviceResult(advice, adviceSource, round3(advisorMs), decodeTps?.let { round3(it) })
        } finally {
            ExecutorchGate.endAdvice()
        }
    }

    private suspend fun awaitLlamaAdvisor(level: String): LlamaAdvisor? {
        // Cold open: detection is already shown by the caller; only MEDIUM/HIGH
        // waits here, so LOW never pays for a Llama load it does not use.
        val startMs = SystemClock.elapsedRealtime()
        while (true) {
            val current = readLlamaAdvisor()
            if (current != null && current.isLoaded()) {
                if (llamaAdvisor == null) {
                    llamaAdvisor = current
                }
                return current
            }
            val elapsedMs = SystemClock.elapsedRealtime() - startMs
            if (!ModelLoadPlan.shouldWaitForLlama(level, current?.isLoaded() == true, elapsedMs)) {
                return current?.takeIf { it.isLoaded() }
            }
            delay(ModelLoadPlan.LLAMA_ADVISE_POLL_INTERVAL_MS)
        }
    }

    private fun readLlamaAdvisor(): LlamaAdvisor? {
        llamaAdvisor?.let { return it }
        return try {
            SentinelApp.instance.llamaAdvisor
        } catch (e: Exception) {
            Log.w(TAG, "Pipeline: Llama advisor lookup failed: ${e::class.simpleName}: ${e.message}", e)
            null
        }
    }

    /**
     * True only when the Llama model passed SHA-256 in this process.
     *
     * A Llama file trusted on size/mtime at load is still being re-hashed in the
     * background, so advice waits for that up to [ModelLoadPlan.LLAMA_VERIFY_TIMEOUT_MS].
     * A mismatch, a timeout or a missing store refuses the LLM; the caller uses the
     * template and the reason is logged under PS3Integrity. Never throws: fails closed.
     */
    private suspend fun awaitLlamaVerified(): Boolean {
        val store = try {
            SentinelApp.instance.modelStore
        } catch (e: Exception) {
            logIntegrityFailure("ModelStore unavailable: ${e::class.simpleName}: ${e.message}")
            return false
        } catch (e: LinkageError) {
            logIntegrityFailure("ModelStore unavailable: ${e::class.simpleName}: ${e.message}")
            return false
        }
        val name = store.fileNames.llamaModel
        val verified = try {
            store.awaitVerified(name, ModelLoadPlan.LLAMA_VERIFY_TIMEOUT_MS)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logIntegrityFailure("verification wait failed: ${e::class.simpleName}: ${e.message}")
            return false
        }
        if (!verified) {
            val reason = if (store.rehashFailed(name)) {
                "SHA-256 mismatch"
            } else {
                "re-hash not finished within ${ModelLoadPlan.LLAMA_VERIFY_TIMEOUT_MS} ms"
            }
            logIntegrityFailure("$reason for $name; using template advice")
        }
        return verified
    }

    /** Logs a withheld Llama advice under PS3Integrity; logging can never crash the gate. */
    private fun logIntegrityFailure(message: String) {
        try {
            Log.w(INTEGRITY_TAG, "Pipeline: Llama advice withheld: $message")
        } catch (_: Exception) {
            // Logging must never turn a verification refusal into a failure of its own.
        }
    }

    /**
     * Runs both detection and advice generation sequentially for the given message.
     *
     * @param text Raw message text.
     * @param onLlamaToken Optional callback for streaming advice tokens.
     * @param extraDetectors Optional extra detectors.
     * @param sender Optional sender ID or phone number.
     * @param fixedAdvice Optional pre-determined advice string.
     * @return Consolidated [PipelineResult].
     */
    suspend fun analyse(
        text: String,
        onLlamaToken: ((String) -> Unit)? = null,
        extraDetectors: List<Detector> = emptyList(),
        sender: String? = null,
        fixedAdvice: String? = null
    ): PipelineResult {
        val detection = detect(text, extraDetectors, sender)
        val adviceResult = advise(text, detection.evidence, onLlamaToken, fixedAdvice)
        val timings = detection.timingsMs.copy(
            advisorMs = adviceResult.advisorMs,
            totalMs = round3(detection.timingsMs.totalMs + adviceResult.advisorMs),
            decodeTokensPerSec = adviceResult.decodeTokensPerSec
        )
        return PipelineResult(
            evidence = detection.evidence,
            advice = adviceResult.advice,
            adviceSource = adviceResult.adviceSource,
            timingsMs = timings,
            smsResult = detection.smsResult,
            isPlainPromotion = isPlainPromotion(text, detection.evidence)
        )
    }

    private fun streamToken(evidence: Evidence, callback: ((String) -> Unit)?): ((String) -> Unit)? {
        if (callback == null) {
            return null
        }
        val filter = StreamingAdviceFilter(evidence)
        return { token ->
            val display = filter.onToken(token)
            if (display.isNotEmpty()) {
                callback(display)
            }
        }
    }

    /** True when the SMS classifier is already loaded (warmed up); false while warming or unavailable. */
    fun isSmsModelLoaded(): Boolean = smsClassifier != null && smsClassifier!!.isLoaded()

    /**
     * Rule-only detection: cues + URL model, no SMS model. Fast and safe to call inside the SMS
     * receiver deadline; never loads the 51 MB SMS model.
     */
    fun analyseFastRulesOnly(text: String, sender: String? = null): Evidence =
        safeFuse(text, null, scoreUrls(extractUrls(text)), cuesWithSender(text, sender), sender = sender)

    /** Detection for the SMS receiver: cues + URL model + SMS model, no LLM. Never call on the main thread or the receiver path unless the SMS model is already warmed up. */
    fun analyseFast(text: String, sender: String? = null): Evidence {
        // DT-18: cold-start SMS detection has started; delay the prefill.
        ExecutorchGate.markDetectionExpected()
        val smsDetailed = runSmsDetailed(text)
        val result = withSmsErrorIndicators(
            safeFuse(text, smsDetailed.first, scoreUrls(extractUrls(text)), cuesWithSender(text, sender), sender = sender),
            smsDetailed.second
        )
        ExecutorchGate.markActivityEnded()
        return result
    }

    private fun round3(value: Double): Double {
        return Math.round(value * 1000.0) / 1000.0
    }

    /**
     * Returns the first 8 hex characters of the SHA-256 of [text].
     * Used so raw URLs and SMS text are never written to logcat (SEC-05).
     */
    private fun shortDigest(text: String): String = sha256Short(text)
}

/** Appends url_model_error to the fallback indicators when the URL classifier threw. */
internal fun urlFallbackIndicators(indicators: List<String>, urlModelError: Boolean): List<String> =
    if (urlModelError && "url_model_error" !in indicators) indicators + "url_model_error" else indicators
