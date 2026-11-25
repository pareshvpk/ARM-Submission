/**
 * Application singleton initializing native libraries, shared rules, models, and notification channels.
 * Coordinates model loading, memory trim responses, and concurrency gating between SMS analysis and Llama generation.
 * Maintains process-wide singletons for ModelStore, Pipeline, and active classifier modules.
 */
package org.ps3.sentinel

import android.app.Application
import android.content.ComponentCallbacks2
import android.util.Log
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.SystemClock
import com.facebook.soloader.SoLoader
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.core.TrustedDomainStore
import org.ps3.sentinel.core.UrlEncoder
import org.ps3.sentinel.ml.CpuFeatures
import org.ps3.sentinel.ml.ExecutorchGate
import org.ps3.sentinel.ml.LlamaAdvisor
import org.ps3.sentinel.ml.ModelLoadPlan
import org.ps3.sentinel.ml.ModelStore
import org.ps3.sentinel.ml.UrlClassifier
import org.ps3.sentinel.sms.MmsWatcher
import org.ps3.sentinel.sms.PendingMessageStore
import org.ps3.sentinel.sms.SmsReceiver
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Purpose:  Boots rules, models and the analysis pipeline.
 * Owns:     The shared ModelStore and the published Pipeline.
 * Lifetime: Process
 * Thread:   any — flags below are atomic or volatile.
 */
class SentinelApp : Application() {

    companion object {
        const val CHANNEL_ID_ALERTS = "scam_alerts"
        private const val TIMING_TAG = "PS3Timing"
        // 100 ms — Llama gate wait while an SMS analysis is waiting: short
        // fallback so a missed end-of-analysis signal re-checks promptly;
        // normally woken by notify.
        private const val LLAMA_GATE_POLL_INTERVAL_MS: Long = 100L
        // 30000 ms — idle Llama gate wait fallback: while no SMS analysis is
        // waiting the gate can only open on a UI open, SMS analysis change,
        // warm-up finish or deferred-queue change, all of which notify; the
        // timeout only guards a lost wake-up so a broadcast-started process
        // does not poll at 1 Hz.
        private const val LLAMA_GATE_IDLE_POLL_INTERVAL_MS: Long = 30000L
        // Captured when the class is first loaded, the earliest point Kotlin can
        // timestamp the process; onCreate logs the delta to it.
        val processStartElapsedMs: Long = SystemClock.elapsedRealtime()
        lateinit var instance: SentinelApp
            private set
    }

    lateinit var modelStore: ModelStore
        private set

    // @Volatile: the ps3-model-init background thread writes these while the UI thread and the SMS
    // receiver thread read them; without volatility a reader could keep a stale null reference.
    @Volatile var pipeline: Pipeline? = null
        private set

    @Volatile var urlClassifier: UrlClassifier? = null
        private set

    @Volatile var llamaAdvisor: LlamaAdvisor? = null
        private set

    // Non-null when the shared rules failed to load at startup; analysis must not run without them.
    @Volatile var rulesLoadError: String? = null
        private set

    private val uiOpened = AtomicBoolean(false)
    private val smsAnalysisWaiting = AtomicInteger(0)
    private val uiAnalysisRunning = AtomicBoolean(false)
    private val llamaLoadInProgress = AtomicBoolean(false)
    private val llamaReleased = AtomicBoolean(false)
    private val llamaLock = Any()
    private val llamaGateLock = Any()
    @Volatile private var reloadStartMs: Long = 0L
    @Volatile private var smsWarmUpFinished = false

    /** Signals that the UI is open, waking the Llama gate and triggering deferred background loading. */
    fun markUiOpened() {
        uiOpened.set(true)
        notifyLlamaGateWaiters()
        startLlamaLoadIfNeeded()
    }

    /**
     * Re-checks model presence when the UI resumes so files that arrived while the
     * process was alive are picked up without a restart. Blocking: call off the main
     * thread. Presence checks only; the integrity hashes are still cached per process.
     */
    fun refreshModelsOnResume() {
        if (CpuFeatures.isExecutorchBlocked()) return
        if (shouldRefreshUrlClassifier(modelStore.isUrlClassifierReady(), urlClassifier?.isLoaded())) {
            loadUrlClassifier()
        }
        val p = pipeline
        if (p != null) {
            try {
                p.retrySmsLoadIfFilesChanged()
            } catch (e: Exception) {
                Log.w("PS3Sentinel", "SentinelApp: SMS retry on resume failed: ${e::class.simpleName}: ${e.message}", e)
            }
        }
        startLlamaLoadIfNeeded()
    }

    /** Increments active SMS analysis count and notifies the Llama gate to pause prefill operations. */
    fun beginSmsAnalysis() {
        smsAnalysisWaiting.incrementAndGet()
        // DT-18 cold-start priority: a detection is expected now, so a
        // background prefill must not start ahead of it.
        try {
            ExecutorchGate.markDetectionExpected()
        } catch (_: Exception) {
        }
        notifyLlamaGateWaiters()
    }

    /** Decrements active SMS analysis count and updates the activity timestamp for the Llama gate. */
    fun endSmsAnalysis() {
        smsAnalysisWaiting.decrementAndGet()
        if (smsAnalysisWaiting.get() < 0) {
            smsAnalysisWaiting.set(0)
        }
        // DT-18 second fix: SMS analysis activity has ended; the LIGHT
        // re-prefill idle delay counts from this end, not from its start.
        try {
            ExecutorchGate.markActivityEnded()
        } catch (_: Exception) {
        }
        notifyLlamaGateWaiters()
    }

    /** Wakes any threads waiting on [llamaGateLock] when analysis state or model readiness changes. */
    fun notifyLlamaGateWaiters() {
        synchronized(llamaGateLock) {
            (llamaGateLock as java.lang.Object).notifyAll()
        }
    }

    /** Marks that an on-demand analysis initiated by the UI is running. */
    fun beginUiAnalysis() {
        uiAnalysisRunning.set(true)
    }

    /** Marks that on-demand UI analysis has finished. */
    fun endUiAnalysis() {
        uiAnalysisRunning.set(false)
    }

    /** Returns true if UI analysis, SMS analysis, or background Llama prefill is actively executing. */
    fun isAnalysisRunning(): Boolean =
        uiAnalysisRunning.get() || smsAnalysisWaiting.get() > 0 || (llamaAdvisor?.isPrefillRunning() == true)

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        val advisor = llamaAdvisor
        if (advisor == null) return
        if (!ModelLoadPlan.shouldReleaseLlama(level, isAnalysisRunning(), advisor.isLoaded(), advisor.isPrefillRunning())) return
        postLlamaRelease("trim_level=$level", requireIdle = true)
    }

    /**
     * Releases the loaded Llama advisor after its file failed the background re-hash.
     *
     * Its bytes were trusted on size/mtime at load time, so a mismatch here must end
     * the advisor's life in this process; Pipeline additionally refuses to stream
     * advice until the file is verified.
     */
    fun releaseLlamaAfterIntegrityFailure() {
        postLlamaRelease("integrity_mismatch", requireIdle = false)
    }

    /**
     * Closes the loaded Llama advisor on a background thread, then detaches it.
     *
     * Shared by [onTrimMemory] (requireIdle = true) and [releaseLlamaAfterIntegrityFailure]
     * (requireIdle = false). Never block the main thread (A1-3): close() takes the module
     * lock then the exclusive gate (seconds during a prefill or generation), so the release
     * runs on a background thread and the caller returns at once. When requireIdle is true an
     * in-flight analysis skips the release so the UI keeps its advisor; an integrity failure
     * ignores that and waits for close() to finish instead.
     */
    private fun postLlamaRelease(reason: String, requireIdle: Boolean) {
        try {
            Thread({
                synchronized(llamaLock) {
                    val current = llamaAdvisor
                    if (current == null || !current.isLoaded()) return@synchronized
                    if (requireIdle && isAnalysisRunning()) return@synchronized
                    // close() takes the module lock then the exclusive gate, so this never runs while a
                    // generation, a prefill or a forward pass is running, even if the flag check above
                    // misses a deferred SMS analysis. Do not acquire the gate here: that would invert
                    // the lock order and deadlock against generate.
                    try {
                        current.close()
                    } catch (e: Exception) {
                        Log.w("PS3Sentinel", "SentinelApp: Llama close failed: ${e::class.simpleName}: ${e.message}", e)
                    }
                    llamaAdvisor = null
                    try {
                        pipeline?.attachLlamaAdvisor(null)
                    } catch (e: Exception) {
                        Log.w("PS3Sentinel", "SentinelApp: detach failed: ${e::class.simpleName}: ${e.message}", e)
                    }
                    reloadStartMs = 0L
                    llamaReleased.set(true)
                    Log.i(TIMING_TAG, "llama_released $reason")
                }
            }, "ps3-llama-release").start()
        } catch (e: Exception) {
            Log.w("PS3Sentinel", "SentinelApp: Llama release post failed: ${e::class.simpleName}: ${e.message}", e)
        }
    }

    private fun startLlamaLoadIfNeeded() {
        if (llamaAdvisor != null) return
        if (CpuFeatures.isExecutorchBlocked()) return
        if (!CpuFeatures.shouldLoadLlama(CpuFeatures.currentTier(this))) return
        val p = pipeline ?: return
        if (!llamaLoadInProgress.compareAndSet(false, true)) return
        val wasReload = llamaReleased.getAndSet(false)
        if (wasReload) {
            reloadStartMs = SystemClock.elapsedRealtime()
        }
        try {
            Thread({
                try {
                    loadLlamaWhenAllowed(p, wasReload)
                } finally {
                    llamaLoadInProgress.set(false)
                }
            }, "ps3-llama-load").start()
        } catch (e: Exception) {
            llamaLoadInProgress.set(false)
            if (wasReload) {
                llamaReleased.set(true)
            }
            Log.w("PS3Sentinel", "SentinelApp: Llama load start failed: ${e::class.simpleName}: ${e.message}", e)
        }
    }

    override fun onCreate() {
        super.onCreate()
        val processToOnCreateMs = SystemClock.elapsedRealtime() - processStartElapsedMs
        Log.i(TIMING_TAG, "process_start_to_onCreate_ms=$processToOnCreateMs")
        instance = this
        CpuFeatures.logOnce(this)

        // 1. Initialize native libraries with SoLoader
        try {
            SoLoader.init(this, false)
        } catch (e: UnsatisfiedLinkError) {
            // SoLoader loads native libraries and can throw an Error (not an Exception) when one is
            // missing or incompatible; catch that specific type so startup survives on such devices.
            Log.w("PS3Sentinel", "SentinelApp: SoLoader init failed: ${e::class.simpleName}: ${e.message}", e)
        } catch (e: Exception) {
            Log.w("PS3Sentinel", "SentinelApp: SoLoader init failed: ${e::class.simpleName}: ${e.message}", e)
        }

        // 2. Load bundled trusted domains asset
        try {
            assets.open("trusted_domains.txt").use { stream ->
                TrustedDomainStore.loadFromStream(stream)
            }
        } catch (e: Exception) {
            Log.w("PS3Sentinel", "SentinelApp: trusted domains load failed: ${e::class.simpleName}: ${e.message}", e)
        }

        // 3. Load the shared rules once before anything else uses cues or fusion. Both platforms
        //    read sentinel/data/rules.json, so a missing or malformed file must fail loudly here
        //    instead of letting a stale copy silently change verdicts (FRAG-01/FRAG-02).
        try {
            Rules.load(assets)
        } catch (e: Exception) {
            // Missing/malformed rules are fatal for correct verdicts: record the error so the UI shows
            // it and analysis is not run with an incomplete rule set.
            rulesLoadError = "${e::class.simpleName}: ${e.message}"
            Log.w("PS3Sentinel", "SentinelApp: Rules.load failed: ${e::class.simpleName}: ${e.message}", e)
        }
        // 4. Create notification channel for SMS scam alerts
        createNotificationChannel()

        // 5. Initialize model store and pipeline. Loading the pte files and hashing them against
        //    models.sha256 can take seconds (the Llama model is about 1 GB), so keep the whole
        //    initialization off the main thread or start-up would freeze and risk an ANR.
        modelStore = ModelStore(this)
        modelStore.ensureDirExists()
        rulesLoadError?.let { modelStore.rulesStatus = "RULES ERROR: $it" }
        // Do not load models or run analysis when the shared rules are missing.
        if (rulesLoadError == null) {
            Thread({ initPipeline() }, "ps3-model-init").start()
        }

        // Schedule MMS watcher at app start when permissions are already granted
        if (MmsWatcher.allowed(this)) {
            MmsWatcher.schedule(this)
        }
    }

    /**
     * Initializes the detection pipeline, warms up classifiers, and triggers deferred message retry.
     *
     * Runs off the main thread during application startup.
     */
    fun initPipeline() {
        // DT-18 cold-start: process started for an incoming SMS must run
        // detection before any prefill. Mark the expected detection before
        // warm-up so the initial prefill is delayed until the drain finishes.
        try {
            if (hasDeferredPending() || smsAnalysisWaiting.get() > 0) {
                ExecutorchGate.markDetectionExpected()
            }
        } catch (_: Exception) {
        }
        loadUrlClassifier()
        val p = Pipeline(urlClassifier = urlClassifier, llamaAdvisor = null)
        pipeline = p
        modelStore.notifyVerificationFinished()
        try {
            p.warmUp()
        } finally {
            smsWarmUpFinished = true
            notifyLlamaGateWaiters()
            try {
                val store = PendingMessageStore.instance(this)
                for (id in store.deferredIds()) {
                    SmsReceiver.enqueueDeferred(id)
                }
            } catch (e: Exception) {
                Log.w("PS3Sentinel", "SentinelApp: deferred re-queue failed: " +
                    "${e::class.simpleName}: ${e.message}", e)
            }
            try {
                SmsReceiver.retryPendingAnalysis()
            } catch (e: Exception) {
                Log.w("PS3Sentinel", "SentinelApp: deferred retry trigger failed: " +
                    "${e::class.simpleName}: ${e.message}", e)
            }
            notifyLlamaGateWaiters()
        }
        modelStore.startBackgroundRehash()
        modelStore.notifyVerificationFinished()
        startLlamaLoadIfNeeded()
    }

    private fun loadUrlClassifier() {
        // Never create an ExecuTorch Module on an Armv8.0 CPU without the stock baseline
        // library: libexecutorch_jni.so contains inline LSE atomics and crashes with SIGILL.
        if (CpuFeatures.isExecutorchBlocked()) {
            urlClassifier = null
            Log.w("PS3Sentinel", "SentinelApp: URL classifier skipped, ExecuTorch blocked on this CPU")
            return
        }
        // Verify integrity before the first load rather than in the cheap readiness checks, because
        // this method runs on the ps3-model-init background thread.
        if (!modelStore.isUrlClassifierReady()) {
            urlClassifier = null
            return
        }
        val verifyStartMs = SystemClock.elapsedRealtime()
        val failure = modelStore.verifyForLoad(
            listOf(modelStore.urlModelFile, modelStore.vocabFile)
        )
        Log.i(TIMING_TAG, "integrity_verify_model=url ms=${SystemClock.elapsedRealtime() - verifyStartMs}")
        if (failure != null) {
            urlClassifier = null
            return
        }
        val loadStartMs = SystemClock.elapsedRealtime()
        try {
            val encoder = UrlEncoder.fromFile(modelStore.vocabFile)
            urlClassifier = UrlClassifier(
                ptePath = modelStore.urlModelFile.absolutePath,
                encoder = encoder
            )
        } catch (e: Exception) {
            urlClassifier = null
            modelStore.recordModelLoadError("URL classifier failed to load: ${e::class.simpleName}: ${e.message}")
            Log.w("PS3Sentinel", "SentinelApp: URL classifier failed to load: ${e::class.simpleName}: ${e.message}", e)
        }
        Log.i(TIMING_TAG, "model_load_model=url ms=${SystemClock.elapsedRealtime() - loadStartMs}")
    }

    private fun loadLlamaWhenAllowed(pipeline: Pipeline, wasReload: Boolean = false) {
        if (CpuFeatures.isExecutorchBlocked()) {
            llamaAdvisor = null
            Log.w(TIMING_TAG, "llama_skipped=executorch_blocked")
            modelStore.notifyVerificationFinished()
            return
        }
        val tier = CpuFeatures.currentTier(this)
        if (!CpuFeatures.shouldLoadLlama(tier)) {
            llamaAdvisor = null
            Log.i(TIMING_TAG, "llama_skipped=low_ram tier=$tier")
            modelStore.notifyVerificationFinished()
            return
        }
        waitForLlamaGate()
        if (!modelStore.isLlamaReady()) {
            llamaAdvisor = null
            modelStore.notifyVerificationFinished()
            return
        }
        val verifyStartMs = SystemClock.elapsedRealtime()
        val failure = modelStore.verifyForLoad(
            listOf(modelStore.llamaModelFile, modelStore.tokenizerFile)
        )
        Log.i(TIMING_TAG, "integrity_verify_model=llama ms=${SystemClock.elapsedRealtime() - verifyStartMs}")
        if (failure != null) {
            llamaAdvisor = null
            modelStore.notifyVerificationFinished()
            return
        }
        modelStore.startBackgroundRehash()
        // Only a file that passed verifyForLoad may be native-loaded to restore the
        // thread pool (A1-4): picking by isFile alone would load an unverified model
        // the classifiers refused. Candidates are checked in preference order; if
        // none passes verification the pool restore is skipped (Llama may run
        // single-threaded) rather than loading unverified bytes.
        val poolRestoreFile = listOf(modelStore.urlModelFile, modelStore.smsModelFile)
            .firstOrNull { candidate ->
                if (!candidate.isFile) {
                    false
                } else {
                    val restoreFailure = modelStore.verifyForLoad(listOf(candidate))
                    if (restoreFailure == null) {
                        true
                    } else {
                        Log.w(
                            "PS3Sentinel",
                            "SentinelApp: pool restore file not verified ${candidate.name}: " +
                                "${restoreFailure.message}"
                        )
                        false
                    }
                }
            }
        if (poolRestoreFile == null) {
            Log.w(TIMING_TAG, "llama_pool_restore_skipped=no_verified_file")
        }
        val loadStartMs = SystemClock.elapsedRealtime()
        try {
            val advisor = LlamaAdvisor(
                modelPath = modelStore.llamaModelFile.absolutePath,
                tokenizerPath = modelStore.tokenizerFile.absolutePath,
                temperature = 0.0f,
                modelsDir = modelStore.sourceDir,
                poolRestoreFile = poolRestoreFile,
                maxNewTokens = CpuFeatures.maxNewTokensFor(tier),
                firstTokenTimeoutMs = CpuFeatures.firstTokenTimeoutMsFor(tier),
                totalTimeoutMs = CpuFeatures.totalGenerationTimeoutMsFor(tier),
                isLightTier = tier == CpuFeatures.Tier.LIGHT,
                onPoolReset = {
                    // LlmModule already reset the shared pthreadpool; rebuild the URL and
                    // SMS modules here, still inside the exclusive section, so their
                    // XNNPACK runtimes bind to the live pool instead of the freed one.
                    val rebindStartMs = SystemClock.elapsedRealtime()
                    val urlStatus = try {
                        val classifier = urlClassifier
                        if (classifier == null) {
                            "none"
                        } else if (classifier.rebindAfterPoolReset()) {
                            "ok"
                        } else {
                            "fail"
                        }
                    } catch (e: Throwable) {
                        Log.w(
                            "PS3Sentinel",
                            "SentinelApp: URL rebind after pool reset failed: " +
                                "${e::class.simpleName}: ${e.message}",
                            e
                        )
                        "fail"
                    }
                    val smsStatus = try {
                        pipeline.rebindClassifiersAfterPoolReset()
                    } catch (e: Throwable) {
                        Log.w(
                            "PS3Sentinel",
                            "SentinelApp: SMS rebind after pool reset failed: " +
                                "${e::class.simpleName}: ${e.message}",
                            e
                        )
                        "fail"
                    }
                    Log.i(
                        TIMING_TAG,
                        "pool_rebind ms=${SystemClock.elapsedRealtime() - rebindStartMs} " +
                            "url=$urlStatus sms=$smsStatus"
                    )
                }
            )
            Log.i(
                TIMING_TAG,
                "llama_tier=$tier max_new_tokens=${CpuFeatures.maxNewTokensFor(tier)} " +
                    "first_token_timeout_ms=${CpuFeatures.firstTokenTimeoutMsFor(tier)} " +
                    "total_timeout_ms=${CpuFeatures.totalGenerationTimeoutMsFor(tier)}"
            )
            synchronized(llamaLock) {
                llamaAdvisor = advisor
            }
            pipeline.attachLlamaAdvisor(advisor)
            // A parallel background re-hash may have failed before the native load finished.
            // Release the advisor immediately then; Pipeline also refuses to stream advice
            // until the file is verified in this process.
            if (modelStore.rehashFailed(modelStore.fileNames.llamaModel)) {
                releaseLlamaAfterIntegrityFailure()
            }
        } catch (e: Exception) {
            synchronized(llamaLock) {
                llamaAdvisor = null
            }
            pipeline.attachLlamaAdvisor(null)
            modelStore.recordModelLoadError("Llama advisor failed to load: ${e::class.simpleName}: ${e.message}")
            Log.w("PS3Sentinel", "SentinelApp: Llama advisor failed to load: ${e::class.simpleName}: ${e.message}", e)
        }
        Log.i(TIMING_TAG, "model_load_model=llama ms=${SystemClock.elapsedRealtime() - loadStartMs}")
        if (wasReload && reloadStartMs != 0L) {
            Log.i(TIMING_TAG, "llama_reloaded_ms=${SystemClock.elapsedRealtime() - reloadStartMs}")
            reloadStartMs = 0L
        }
        modelStore.notifyVerificationFinished()
    }

    private fun hasDeferredPending(): Boolean {
        return try {
            SmsReceiver.hasPendingAnalysis()
        } catch (e: Exception) {
            Log.w("PS3Sentinel", "SentinelApp: deferred pending check failed: ${e::class.simpleName}: ${e.message}", e)
            false
        }
    }

    private fun drainDeferred(): Boolean {
        return try {
            SmsReceiver.retryPendingAnalysis()
            true
        } catch (e: Exception) {
            Log.w("PS3Sentinel", "SentinelApp: deferred drain failed: ${e::class.simpleName}: ${e.message}", e)
            false
        }
    }

    private fun waitForLlamaGate() {
        while (true) {
            if (smsWarmUpFinished) drainDeferred()
            val smsWaiting = smsAnalysisWaiting.get() > 0
            if (ModelLoadPlan.shouldLoadLlama(
                    smsWarmUpFinished,
                    uiOpened.get(),
                    smsWaiting,
                    hasDeferredPending()
                )
            ) break
            val timeoutMs = llamaGatePollIntervalMs(
                uiOpened.get(),
                smsWaiting,
                LLAMA_GATE_POLL_INTERVAL_MS,
                LLAMA_GATE_IDLE_POLL_INTERVAL_MS
            )
            try {
                synchronized(llamaGateLock) {
                    val smsWaitingNow = smsAnalysisWaiting.get() > 0
                    if (!ModelLoadPlan.shouldLoadLlama(
                            smsWarmUpFinished,
                            uiOpened.get(),
                            smsWaitingNow,
                            hasDeferredPending()
                        )
                    ) {
                        (llamaGateLock as java.lang.Object).wait(timeoutMs)
                    }
                }
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val name = getString(R.string.channel_name)
            val descriptionText = getString(R.string.channel_desc)
            val importance = NotificationManager.IMPORTANCE_HIGH
            val channel = NotificationChannel(CHANNEL_ID_ALERTS, name, importance).apply {
                description = descriptionText
                enableVibration(true)
            }
            val notificationManager = getSystemService(NotificationManager::class.java)
            notificationManager?.createNotificationChannel(channel)
        }
    }
}

/**
 * Pure choice of the Llama gate wait timeout: the fast interval only while an
 * SMS analysis is waiting, otherwise the idle fallback interval. The UI-open
 * flag is kept for the call-site signature; a UI open notifies the gate waiter
 * directly, so it does not need the fast timeout. Kept top-level (not in the
 * Application companion) so unit tests can call it without loading the
 * Application class.
 */
internal fun llamaGatePollIntervalMs(
    uiOpened: Boolean,
    smsAnalysisWaiting: Boolean,
    fastIntervalMs: Long,
    idleIntervalMs: Long
): Long = if (smsAnalysisWaiting) fastIntervalMs else idleIntervalMs

/**
 * Pure decision for whether resume should (re)load the URL classifier: load
 * when the files are present and the current classifier is missing or its
 * native load failed (isLoaded false). Kept top-level so unit tests can call
 * it without loading the Application class.
 */
internal fun shouldRefreshUrlClassifier(isReady: Boolean, classifierLoaded: Boolean?): Boolean =
    isReady && classifierLoaded != true
