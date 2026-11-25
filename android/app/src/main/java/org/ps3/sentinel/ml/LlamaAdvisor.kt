// Orchestrates on-device Llama 3.2 1B Instruct text generation for threat explanation and advice.
// Manages prefix KV-cache reuse, token streaming via callbacks, execution watchdog timeouts,
// and safety guard filtering.

package org.ps3.sentinel.ml

import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.FIXED_PROMPT_PREFIX
import org.ps3.sentinel.core.LLAMA_STOP_AFTER_SENTENCES
import org.ps3.sentinel.core.buildPrompt
import org.ps3.sentinel.core.completeSentenceCount
import org.ps3.sentinel.core.firstStepIndex
import org.ps3.sentinel.core.guard
import org.ps3.sentinel.core.splitPrompt
import org.ps3.sentinel.core.templateAdvice
import org.pytorch.executorch.Module
import org.pytorch.executorch.extension.llm.LlmCallback
import org.pytorch.executorch.extension.llm.LlmGenerationConfig
import org.pytorch.executorch.extension.llm.LlmModule
import org.pytorch.executorch.extension.llm.LlmModuleConfig
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.locks.ReentrantLock

/**
 * Diagnostic execution performance metrics emitted by the ExecuTorch LLM runner.
 */
data class LlamaStats(
    val promptTokens: Int = 0,
    val generatedTokens: Int = 0,
    val prefillTokensPerSec: Double = 0.0,
    val decodeTokensPerSec: Double = 0.0,
    val totalTimeMs: Double = 0.0,
    val ttftMs: Double = 0.0,
    val promptPath: String = "full_prompt"
)

/**
 * Complete advice generation output, combining guarded text, raw tokens, flags, and timings.
 */
data class AdvisorResult(
    val advice: String,
    val rawAdvice: String,
    val flags: List<String>,
    val stats: LlamaStats?,
    val source: String
)

/**
 * On-device Llama 3.2 1B advisor generating structured scam warnings and protective recommendations.
 *
 * Implements prefix KV-cache optimization to minimize time-to-first-token while enforcing
 * watchdog timeouts, thread-pool integrity restores, and strict advice guard filters.
 */
class LlamaAdvisor(
    private val modelPath: String,
    private val tokenizerPath: String,
    private val temperature: Float = 0.0f,
    usePrefixCache: Boolean? = null,
    modelsDir: File? = null,
    private val poolRestoreFile: File? = null,
    private val maxNewTokens: Int = DEFAULT_MAX_NEW_TOKENS,
    private val firstTokenTimeoutMs: Long = GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS,
    private val totalTimeoutMs: Long = GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS,
    private val isLightTier: Boolean = false,
    // Invoked at the end of every pool restore, inside the same exclusive section, so
    // callers can rebuild the URL/SMS modules against the live shared pthreadpool.
    private val onPoolReset: () -> Unit = {}
) : AutoCloseable {

    @Volatile
    var lastStats: LlamaStats? = null
        private set

    /** Companion constants, shared performance state, and default configuration budgets. */
    companion object {
        @Volatile
        var lastStats: LlamaStats? = null
        private const val TAG = "PS3Sms"
        private const val BENCH_TAG = "PS3Bench"
        private const val TIMING_TAG = "PS3Timing"
        private val coldStartPrefillLogged = AtomicBoolean(false)
        // prefix_cache.on — runtime opt-in file checked once at creation next to the models
        // (ModelStore models dir). Its presence enables the prefix path without a rebuild.
        const val PREFIX_CACHE_FLAG_FILE_NAME: String = "prefix_cache.on"
        // prefix_cache.off — runtime opt-out file. Its presence disables the prefix path
        // without a rebuild and wins over USE_PREFIX_CACHE when both files exist.
        const val PREFIX_CACHE_OFF_FLAG_FILE_NAME: String = "prefix_cache.off"
        // true — on by default: bench/results/f14_prefix_20261106_151141/summary.txt (TTFT p50 5548 to 4280 ms,
        // prompt tokens 312 to 127, advice identical forward vs reversed 12/12, byte-identical 5/12 via rounding).
        const val USE_PREFIX_CACHE: Boolean = true
        // 130 — normal full answer budget (about 10.5 s decode at 12.3 tok/s on the Arm Linux).
        const val DEFAULT_MAX_NEW_TOKENS: Int = 130
        // 78 — light tier requests about 60 percent of the normal budget so a
        // slow phone without dot-product support finishes inside its timeout.
        const val LIGHT_MAX_NEW_TOKENS: Int = 78
        // 5000 ms — DT-18 LIGHT-tier idle delay for the deferred re-prefill. FIX 1
        // (2026-11-24) means LIGHT no longer schedules a background prefill at all,
        // so the delay is no longer reached on LIGHT; it stays for the gate's
        // deferral rules and their tests. FULL tier uses 0 (unchanged).
        const val LIGHT_PREFILL_IDLE_DELAY_MS: Long = 5_000L
        internal const val PATH_PREFIX_CACHE: String = "prefix_cache"
        internal const val PATH_FULL_PROMPT: String = "full_prompt"
        // DT-18 second fix: LIGHT advice that arrives while the deferred
        // re-prefill has not run yet prefills the prefix in the foreground
        // (prefix then tail) instead of waiting for the background prefill
        // or silently running the full prompt.
        internal const val PATH_PREFIX_ON_DEMAND: String = "prefix_on_demand"
        // 5000 ms — a prefix prefill of roughly 150 tokens at about 55 tok/s takes about 3 s on
        // the Galaxy F14; waiting longer for a background prefill would erase the saving, so
        // fall back to the full-prompt path once this wait has expired.
        private const val PREFIX_PREFILL_WAIT_TIMEOUT_MS: Long = 5000L
        // 10000 ms — separate bound for waiting on the module lock before a generation
        // may start (CXB-3): waiting must not consume the first-token budget, so the
        // watchdog starts only after this wait (and the shared gate wait) succeed.
        private const val GENERATION_LOCK_WAIT_TIMEOUT_MS: Long = 10_000L
        // 10000 ms — separate bound for waiting on the shared ExecuTorch gate before a
        // generation starts; a load or close that holds the gate longer than this
        // fails the generation fast to the template answer instead of hanging.
        private const val GENERATION_GATE_WAIT_TIMEOUT_MS: Long = 10_000L
    }

    @Volatile
    private var llmModule: LlmModule? = null
    private val moduleLock = ReentrantLock()
    private val prefillExecutor = Executors.newSingleThreadExecutor { task -> Thread(task, "PS3PrefixPrefill") }
    private val effectiveModelsDir: File? = modelsDir ?: runCatching { File(modelPath).parentFile }.getOrNull()
    private val prefixCacheDecision: PrefixCacheDecision = resolvePrefixCacheDecision(effectiveModelsDir, usePrefixCache)
    @Volatile
    private var prefixCacheActive: Boolean = prefixCacheDecision.enabled
    @Volatile
    private var prefixReady: Boolean = false
    @Volatile
    private var prefillFuture: Future<*>? = null
    // DT-18: LIGHT also inferred from the token budget, so an explicit flag and
    // the LIGHT budget agree even if one call site omits the flag.
    private val lightTier: Boolean = isLightTier || maxNewTokens == LIGHT_MAX_NEW_TOKENS

    init {
        val state = if (prefixCacheDecision.enabled) "enabled" else "disabled"
        Log.i(TAG, "LlamaAdvisor: prefix cache $state (${prefixCacheDecision.reason})")
        if (CpuFeatures.isExecutorchBlocked()) {
            Log.w(TAG, "LlamaAdvisor: ExecuTorch blocked on this CPU; template advice only")
            llmModule = null
        } else {
            loadModule()
        }
    }

    private fun loadModule() {
        val mFile = File(modelPath)
        val tFile = File(tokenizerPath)
        if (!(mFile.exists() && tFile.exists())) {
            return
        }
        try {
            // LOAD_MODE_MMAP by default; NOT MMAP_USE_MLOCK_IGNORE_ERRORS. On Android
            // RLIMIT_MEMLOCK caps unprivileged mlock at 64 KB (init.rc 65536 65536),
            // so an mlock of the 1.2 GB weights fails with ENOMEM and
            // MmapDataLoader falls back to plain mmap anyway (safe, but useless).
            // Pinning would only succeed if an OEM raised the limit, risking the
            // OOM that upstream removed in #18398. Swap risk is handled by the
            // UI-gated load, not mlock.
            // Llama load plus pool restore in one exclusive section: LlmModule creation
            // resets the shared pool, so a forward must not slip between them.
            llmModule = withLlamaLoadAndPoolRestore(
                load = {
                    val config = LlmModuleConfig.create()
                        .modulePath(modelPath)
                        .tokenizerPath(tokenizerPath)
                        .temperature(temperature)
                        .loadMode(LlmModuleConfig.LOAD_MODE_MMAP)
                        .build()
                    LlmModule(config)
                },
                restore = { restoreThreadPoolAfterLlamaLoad() }
            )
        } catch (e: Throwable) {
            // Native load can throw UnsatisfiedLinkError, an Error; survive it and use template fallback.
            Log.w(
                TAG,
                "LlamaAdvisor: failed to load Llama module model=${sha256Short(modelPath)}: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            llmModule = null
        }
        val loaded = llmModule
        if (loaded != null && prefixCacheActive) {
            schedulePrefixPrefill(loaded, FIXED_PROMPT_PREFIX)
        }
    }

    // Caller must already hold ExecutorchGate.withExclusive: Llama load plus pool restore is one
    // exclusive section, so a forward cannot run between LlmModule creation and this restore.
    // Do not wrap this in ExecutorchGate.withExclusive again; the caller holds the exclusive
    // side for both steps via withLlamaLoadAndPoolRestore.
    private fun restoreThreadPoolAfterLlamaLoad() {
        // LlmModule has no thread-count knob at 1.5.1: its JNI ctor always resets the
        // shared singleton pool to performant-cores minus one (1 on the F14), which
        // would leave prefill and decode single-threaded. A later Module.load with
        // the URL/SMS thread count re-asserts the pool before any prefill runs.
        val clusters = try { CpuFeatures.currentClusters() } catch (_: Exception) { emptyList() }
        val proposal = try { CpuFeatures.proposeThreadCount(clusters) } catch (_: Exception) { 4 }
        val available = Runtime.getRuntime().availableProcessors()
        val threadCount = ModelLoadPlan.selectThreadCountWithAuto(available, clusters, effectiveModelsDir)
        try {
            val restoreFile = poolRestoreFile
            if (restoreFile != null && restoreFile.isFile) {
                Module.load(restoreFile.absolutePath, Module.LOAD_MODE_MMAP, threadCount)
                    .use { }
            } else {
                Log.w(TAG, "LlamaAdvisor: pool restore skipped, no restore file")
            }
            Log.i(TIMING_TAG, "llama_threads=$threadCount threads_proposal=$proposal threads_used=$threadCount threads_auto=${ModelLoadPlan.isThreadsAutoEnabled(effectiveModelsDir)}")
        } catch (e: Throwable) {
            Log.w(
                TAG,
                "LlamaAdvisor: pool restore failed, Llama may run single-threaded: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            Log.i(TIMING_TAG, "llama_threads=$threadCount threads_proposal=$proposal threads_used=$threadCount threads_auto=${ModelLoadPlan.isThreadsAutoEnabled(effectiveModelsDir)}")
        }
        // The LlmModule constructor reset the pool even when the restore above was
        // skipped or failed, so always rebuild downstream modules against the live pool.
        try {
            onPoolReset()
        } catch (e: Throwable) {
            Log.w(
                TAG,
                "LlamaAdvisor: pool reset callback failed: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
        }
    }

    /** Returns true if the native LlmModule has been successfully initialized. */
    fun isLoaded(): Boolean = llmModule != null

    /** Checks whether background prefix prefill is currently running on the worker executor. */
    fun isPrefillRunning(): Boolean {
        val future = prefillFuture
        return future != null && !future.isDone
    }

    /** Generates guarded advice, using the template answer when the module is unavailable or fails. */
    suspend fun generate(
        text: String,
        evidence: Evidence,
        onToken: ((String) -> Unit)? = null
    ): AdvisorResult = withContext(Dispatchers.Default) {
        val mod = llmModule
        if (mod == null) {
            return@withContext templateResult(evidence, templateAdvice(evidence), emptyList())
        }
        val fullPrompt = buildPrompt(text, evidence)
        val (fixedPrefix, perMessageTail) = splitPrompt(fullPrompt)
        val prefixWasActive = prefixCacheActive
        try {
            val promptSelection = choosePrompt(fullPrompt, perMessageTail, prefixWasActive, fixedPrefix)
            val output = generateWithPrefixRetry(mod, promptSelection, buildGenerationConfig(), text, onToken)
            // Advice activity has ended (success, empty failure or timeout):
            // record that before scheduling the re-prefill so its LIGHT idle
            // delay counts from now, not from the detection that started it.
            ExecutorchGate.markActivityEnded()
            if (output == null) {
                if (prefixWasActive) schedulePrefixPrefill(mod, fixedPrefix)
                return@withContext templateResult(evidence, "", listOf("generate_error"))
            }
            if (output.watchdogReason != null) {
                val reason = output.watchdogReason
                Log.w(TAG, "LlamaAdvisor: generation timeout reason=$reason message=${sha256Short(text)}")
                if (prefixWasActive) schedulePrefixPrefill(mod, fixedPrefix)
                return@withContext timeoutResult(evidence, reason)
            }
            if (prefixWasActive) {
                // Restore the end-of-prefix state on the background thread while the user reads.
                schedulePrefixPrefill(mod, fixedPrefix)
            }
            return@withContext buildAdvisorResult(output, evidence)
        } catch (e: kotlinx.coroutines.CancellationException) {
            ExecutorchGate.markActivityEnded()
            throw e
        } catch (e: Throwable) {
            ExecutorchGate.markActivityEnded()
            Log.w(
                TAG,
                "LlamaAdvisor: generate failed message=${sha256Short(text)}: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
            return@withContext templateResult(evidence, "", listOf("generate_error"))
        }
    }

    /** Chooses the prompt sent to the module for one message. */
    private fun choosePrompt(
        fullPrompt: String,
        perMessageTail: String,
        prefixWasActive: Boolean,
        fixedPrefix: String = ""
    ): PromptSelection {
        val path = selectPromptPath(prefixWasActive, prefixReady, lightTier)
        return when (path) {
            PATH_PREFIX_CACHE -> PromptSelection(
                fullPrompt, perMessageTail, PATH_PREFIX_CACHE,
                needsReset = needsResetBeforeGenerate(PATH_PREFIX_CACHE),
                perMessageTail = perMessageTail,
                fixedPrefix = fixedPrefix
            )
            PATH_PREFIX_ON_DEMAND -> {
                // LIGHT and the deferred re-prefill has not run yet: do not
                // wait for that background prefill and do not silently run
                // the full prompt. Cancel its idle wait so the foreground
                // prefill below can take the module lock promptly, then
                // prefill the prefix in the foreground (prefix then tail)
                // inside runGeneration. Detection never waits for this:
                // it runs inside the advice, after the detection verdict,
                // under the module lock and shared gate only, never the
                // detection/prefill mutex.
                cancelDeferredPrefill()
                PromptSelection(
                    fullPrompt, perMessageTail, PATH_PREFIX_ON_DEMAND,
                    needsReset = needsResetBeforeGenerate(PATH_PREFIX_ON_DEMAND),
                    perMessageTail = perMessageTail,
                    fixedPrefix = fixedPrefix
                )
            }
            else -> {
                // FULL tier unchanged, and any non-LIGHT fallback: wait a
                // bounded time for a running prefill, otherwise this message
                // uses the full prompt; the reset inside the lock clears any
                // partial prefix before the generation runs. The bounded
                // wait happens only on FULL tier (see selectPromptPath).
                if (prefixWasActive && !lightTier) {
                    awaitPrefixReady(PREFIX_PREFILL_WAIT_TIMEOUT_MS)
                }
                val resolvedPath = if (prefixReady && prefixWasActive) PATH_PREFIX_CACHE else PATH_FULL_PROMPT
                if (resolvedPath == PATH_PREFIX_CACHE) {
                    PromptSelection(
                        fullPrompt, perMessageTail, PATH_PREFIX_CACHE,
                        needsReset = needsResetBeforeGenerate(PATH_PREFIX_CACHE),
                        perMessageTail = perMessageTail,
                        fixedPrefix = fixedPrefix
                    )
                } else {
                    PromptSelection(
                        fullPrompt, fullPrompt, PATH_FULL_PROMPT,
                        needsReset = needsResetBeforeGenerate(PATH_FULL_PROMPT),
                        perMessageTail = perMessageTail,
                        fixedPrefix = fixedPrefix
                    )
                }
            }
        }
    }

    /** Interrupts a still-idle-waiting background prefill so advice is not queued behind it. */
    private fun cancelDeferredPrefill() {
        val future = prefillFuture ?: return
        try {
            // Interrupting aborts the gate idle wait (it throws
            // PrefillTimeoutException and releases the module lock). A
            // native prefill already running cannot be interrupted; the
            // foreground generation then simply waits for the module lock
            // under its existing bounded wait and re-checks prefixReady.
            future.cancel(true)
        } catch (_: Exception) {
        }
        prefillFuture = null
    }

    /** Builds the fixed generation config used for advice. */
    private fun buildGenerationConfig(): LlmGenerationConfig =
        LlmGenerationConfig.create()
            .maxNewTokens(maxNewTokens)
            .temperature(0.0f)
            .echo(false)
            .build()

    /** Runs generation, retrying once on the full prompt after a prefix-path failure. */
    private fun generateWithPrefixRetry(
        mod: LlmModule,
        promptSelection: PromptSelection,
        config: LlmGenerationConfig,
        text: String,
        onToken: ((String) -> Unit)?
    ): GenerationOutput? {
        var currentSelection = promptSelection
        while (true) {
            val attemptPath = AtomicReference(currentSelection.usedPath)
            try {
                return runGeneration(mod, currentSelection, config, onToken, attemptPath)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Throwable) {
                val failedPath = attemptPath.get()
                Log.w(
                    TAG,
                    "LlamaAdvisor: generate failed message=${sha256Short(text)} path=$failedPath: " +
                        "${e::class.simpleName}: ${e.message}",
                    e
                )
                if (failedPath == PATH_PREFIX_CACHE || failedPath == PATH_PREFIX_ON_DEMAND) {
                    // Prefix path failed: disable for this instance and retry the full prompt once.
                    prefixCacheActive = false
                    prefixReady = false
                    currentSelection = PromptSelection(
                        currentSelection.fullPrompt,
                        currentSelection.fullPrompt,
                        PATH_FULL_PROMPT,
                        needsReset = needsResetBeforeGenerate(PATH_FULL_PROMPT),
                        perMessageTail = currentSelection.perMessageTail,
                        fixedPrefix = currentSelection.fixedPrefix
                    )
                    continue
                }
                return null
            }
        }
    }

    /** Runs one generation under the module lock. */
    private fun runGeneration(
        mod: LlmModule,
        promptSelection: PromptSelection,
        config: LlmGenerationConfig,
        onToken: ((String) -> Unit)?,
        attemptPath: AtomicReference<String>
    ): GenerationOutput {
        val callback = GenerationCallback(mod, onToken)
        var effectiveSelection = promptSelection
        // Bounded wait for the module lock, separate from the watchdog budget (CXB-3):
        // the generation must fail fast to the template when another generation or a
        // prefill holds the lock, not consume the first-token budget while queueing.
        val locked = try {
            moduleLock.tryLock(GENERATION_LOCK_WAIT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
        if (!locked) {
            Log.w(TAG, "LlamaAdvisor: generation lock wait timeout_ms=$GENERATION_LOCK_WAIT_TIMEOUT_MS")
            throw IllegalStateException("generation lock wait timed out after $GENERATION_LOCK_WAIT_TIMEOUT_MS ms")
        }
        try {
            // Shared gate: generate must not start during a model load; the shared side
            // also makes a load or close wait for the generation to finish. Bounded
            // wait, separate from the watchdog budget.
            ExecutorchGate.withShared(GENERATION_GATE_WAIT_TIMEOUT_MS) {
                // The watchdog starts only once this generation owns the module and the
                // gate (CXB-3/A1-9), so lock and gate waiting never consume the
                // first-token budget and stop() cannot land before generate().
                val handles = startWatchdog(mod, callback)
                try {
                    if (llmModule !== mod) throw IllegalStateException("Llama module closed")
                    val actualPath = resolvePathUnderLock(
                        effectiveSelection.usedPath, prefixReady, prefixCacheActive, lightTier
                    )
                    if (actualPath != effectiveSelection.usedPath) {
                        effectiveSelection = effectiveSelection.copy(
                            promptToUse = if (actualPath == PATH_PREFIX_CACHE || actualPath == PATH_PREFIX_ON_DEMAND) {
                                effectiveSelection.perMessageTail
                            } else {
                                effectiveSelection.fullPrompt
                            },
                            usedPath = actualPath,
                            needsReset = needsResetBeforeGenerate(actualPath)
                        )
                    }
                    if (actualPath == PATH_PREFIX_CACHE) {
                        prefixReady = false
                    }
                    attemptPath.set(effectiveSelection.usedPath)
                    resetIfNeeded(mod, effectiveSelection)
                    if (effectiveSelection.usedPath == PATH_PREFIX_ON_DEMAND) {
                        // Foreground prefix prefill as part of this advice
                        // request: reset above cleared the context, now
                        // prefill the prefix, then generate the tail below.
                        // This runs under the module lock and shared gate
                        // only (no detection/prefill mutex), so detection
                        // never waits for it, and the watchdog started above
                        // keeps the existing first-token/total timeouts.
                        try {
                            if (effectiveSelection.fixedPrefix.isNotEmpty()) {
                                mod.prefillPrompt(effectiveSelection.fixedPrefix)
                            }
                            prefixReady = false
                        } catch (e: kotlinx.coroutines.CancellationException) {
                            throw e
                        } catch (e: Throwable) {
                            prefixReady = false
                            prefixCacheActive = false
                            Log.w(
                                TAG,
                                "LlamaAdvisor: foreground prefix prefill failed, falling back to $PATH_FULL_PROMPT: " +
                                    "${e::class.simpleName}: ${e.message}",
                                e
                            )
                            throw e
                        }
                    }
                    try {
                        mod.generate(effectiveSelection.promptToUse, config, callback)
                    } catch (e: kotlinx.coroutines.CancellationException) {
                        throw e
                    } catch (e: Throwable) {
                        if (callback.watchdogReason == null) throw e
                        Log.w(
                            TAG,
                            "LlamaAdvisor: generate stopped by watchdog ${callback.watchdogReason}: " +
                                "${e::class.simpleName}: ${e.message}"
                        )
                    }
                } finally {
                    stopWatchdog(handles)
                }
            }
        } finally {
            moduleLock.unlock()
        }
        return GenerationOutput(
            callback.capturedText, callback.statsJson, effectiveSelection.usedPath, callback.watchdogReason
        )
    }

    private fun resetIfNeeded(mod: LlmModule, promptSelection: PromptSelection) {
        if (promptSelection.needsReset || needsResetBeforeGenerate(promptSelection.usedPath)) {
            // Llama KV cache persists across generate calls, so a full prompt without
            // a reset continues the previous SMS: advice depends on order and the
            // context fills within a few messages (prompt_tokens 0, silent template
            // fallback). The prefix_cache path must keep its prefilled prefix, so it
            // must not reset here. The on-demand path resets here and then
            // prefills its prefix in the foreground before generating.
            try {
                mod.resetContext()
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Throwable) {
                prefixReady = false
                Log.w(
                    TAG,
                    "LlamaAdvisor: resetContext failed, prefix cache invalid: " +
                        "${e::class.simpleName}: ${e.message}",
                    e
                )
                throw e
            }
        }
    }

    private data class WatchdogHandles(
        val firstToken: Future<*>,
        val total: Future<*>,
        val executor: java.util.concurrent.ScheduledExecutorService,
        val generationId: Long
    )

    private val generationCounter = AtomicLong(0L)
    private val currentGenerationId = AtomicLong(0L)

    private fun startWatchdog(mod: LlmModule, callback: GenerationCallback): WatchdogHandles {
        val generationId = generationCounter.incrementAndGet()
        currentGenerationId.set(generationId)
        val executor = Executors.newSingleThreadScheduledExecutor { task ->
            Thread(task, "PS3LlamaWatchdog").apply { isDaemon = true }
        }
        val first = executor.schedule({
            if (!callback.hasReceivedToken()) {
                callback.markWatchdog(GenerationWatchdog.REASON_FIRST_TOKEN_TIMEOUT)
                stopModule(mod, GenerationWatchdog.REASON_FIRST_TOKEN_TIMEOUT, generationId)
            }
        }, firstTokenTimeoutMs, TimeUnit.MILLISECONDS)
        val total = executor.schedule({
            callback.markWatchdog(GenerationWatchdog.REASON_TOTAL_TIMEOUT)
            stopModule(mod, GenerationWatchdog.REASON_TOTAL_TIMEOUT, generationId)
        }, totalTimeoutMs, TimeUnit.MILLISECONDS)
        return WatchdogHandles(first, total, executor, generationId)
    }

    private fun stopModule(mod: LlmModule, reason: String, generationId: Long) {
        if (currentGenerationId.get() != generationId) {
            return
        }
        try {
            runWatchdogStop(llmModule === mod && currentGenerationId.get() == generationId) { mod.stop() }
        } catch (e: Throwable) {
            Log.w(TAG, "LlamaAdvisor: watchdog stop failed reason=$reason: ${e::class.simpleName}: ${e.message}", e)
        }
        Log.w(TAG, "LlamaAdvisor: generation watchdog $reason")
    }

    private fun stopWatchdog(handles: WatchdogHandles) {
        currentGenerationId.compareAndSet(handles.generationId, 0L)
        handles.firstToken.cancel(false)
        handles.total.cancel(false)
        handles.executor.shutdownNow()
    }

    /** Builds the guarded AdvisorResult with recorded Llama stats. */
    private fun buildAdvisorResult(output: GenerationOutput, evidence: Evidence): AdvisorResult {
        ExecutorchGate.markActivityEnded()
        var rawGenerated = output.text
        val assistantMarker = "<|start_header_id|>assistant<|end_header_id|>"
        if (rawGenerated.contains(assistantMarker)) {
            rawGenerated = rawGenerated.substringAfterLast(assistantMarker)
        }
        for (tok in listOf("<|eot_id|>", "<|begin_of_text|>", "<|end_of_text|>")) {
            rawGenerated = rawGenerated.replace(tok, "")
        }
        rawGenerated = rawGenerated.replace("**", "").trim()
        val recordedStats = parseLlamaStats(output.statsJson)?.copy(promptPath = output.promptPath)
        Log.i(TAG, "LlamaAdvisor prompt_path=${output.promptPath} prompt_tokens=${recordedStats?.promptTokens ?: 0}")
        try {
            Log.i("PS3Llama", "prompt_path=${output.promptPath}")
        } catch (_: Exception) {
            // Best-effort path logging must never break advice delivery, so failures are ignored here.
        }
        this@LlamaAdvisor.lastStats = recordedStats
        LlamaAdvisor.lastStats = recordedStats
        val (guardedAdvice, flags) = guard(rawGenerated, evidence)
        val source = resolveAdviceSource(flags)
        val result = AdvisorResult(
            advice = guardedAdvice,
            rawAdvice = rawGenerated,
            flags = flags,
            stats = recordedStats,
            source = source
        )
        logBenchLine(output.promptPath, recordedStats, guardedAdvice)
        return result
    }

    /** Builds the template fallback AdvisorResult. */
    private fun templateResult(evidence: Evidence, rawAdvice: String, flags: List<String>): AdvisorResult {
        ExecutorchGate.markActivityEnded()
        val advised = templateAdvice(evidence)
        logBenchLine(PATH_FULL_PROMPT, null, advised)
        return AdvisorResult(
            advice = advised,
            rawAdvice = rawAdvice,
            flags = flags,
            stats = null,
            source = "template"
        )
    }

    private fun timeoutResult(evidence: Evidence, reason: String): AdvisorResult {
        ExecutorchGate.markActivityEnded()
        val advised = templateAdvice(evidence)
        logBenchLine(PATH_FULL_PROMPT, null, advised)
        return AdvisorResult(
            advice = advised,
            rawAdvice = "",
            flags = listOf(reason),
            stats = null,
            source = "template_timeout"
        )
    }

    /** Logs one benchmark line per advice; never logs SMS or advice text, only its hash. */
    private fun logBenchLine(promptPath: String, stats: LlamaStats?, advice: String) {
        Log.i(BENCH_TAG, formatBenchLine(promptPath, stats, advice))
    }

    /** Holds the prompt chosen for one generation attempt. */
    private data class PromptSelection(
        val fullPrompt: String, val promptToUse: String,
        val usedPath: String, val needsReset: Boolean,
        val perMessageTail: String, val fixedPrefix: String = ""
    )

    /** Holds the text, stats, prompt path captured by one generation attempt. */
    private data class GenerationOutput(
        val text: String, val statsJson: String?, val promptPath: String, val watchdogReason: String? = null
    )

    /** Collects generated tokens, forwarded tokens, stats for one generation. */
    private inner class GenerationCallback(
        private val mod: LlmModule,
        private val onToken: ((String) -> Unit)?
    ) : LlmCallback {
        private val textBuilder = StringBuilder()
        var statsJson: String? = null
        var stoppedAtSteps: Boolean = false
            private set
        private var stopped = false
        private var forwardedLength = 0
        @Volatile var watchdogReason: String? = null
        @Volatile private var hasToken: Boolean = false
        val capturedText: String get() = textBuilder.toString()

        fun hasReceivedToken(): Boolean = hasToken

        fun markWatchdog(reason: String) {
            if (watchdogReason == null || reason == GenerationWatchdog.REASON_TOTAL_TIMEOUT) {
                watchdogReason = reason
            }
        }

        override fun onResult(token: String) {
            if (stopped) return
            if (token.contains("<|eot_id|>") || token.contains("<|end_of_text|>")) {
                val clean = token.replace("<|eot_id|>", "").replace("<|end_of_text|>", "")
                if (clean.isNotEmpty()) {
                    hasToken = true
                    textBuilder.append(clean)
                    val stepIndex = firstStepIndex(textBuilder.toString())
                    if (stepIndex >= 0) {
                        stopAtFirstStep(stepIndex)
                        return
                    }
                    flushAll()
                }
                stopped = true
                stopModuleForCallback()
                return
            }
            hasToken = true
            textBuilder.append(token)
            val stepIndex = firstStepIndex(textBuilder.toString())
            if (stepIndex >= 0) {
                stopAtFirstStep(stepIndex)
                return
            }
            if (completeSentenceCount(textBuilder.toString()) >= LLAMA_STOP_AFTER_SENTENCES) {
                stopAtSentenceLimit()
                return
            }
            forwardReady()
        }

        /**
         * Cuts the captured text at the first step, forwards the explanation and
         * stops the module the same way the end-of-text branch does.
         */
        private fun stopAtFirstStep(stepIndex: Int) {
            textBuilder.setLength(stepIndex)
            forwardReady()
            stopped = true
            if (!stoppedAtSteps) {
                stoppedAtSteps = true
                Log.i(TAG, "LlamaAdvisor: stopped at first step")
            }
            stopModuleForCallback()
        }

        /**
         * Stops generation once enough sentences are buffered, forwarding what is
         * ready without cutting the text the same way the first-step stop does.
         */
        private fun stopAtSentenceLimit() {
            flushAll()
            stopped = true
            Log.i(TAG, "LlamaAdvisor: stopped after sentence limit")
            stopModuleForCallback()
        }

        /** Forwards everything except a trailing fragment that may still become a step marker. */
        private fun forwardReady() {
            val end = holdbackStart(textBuilder)
            if (end <= forwardedLength) return
            val chunk = textBuilder.substring(forwardedLength, end)
            forwardedLength = end
            onToken?.invoke(chunk)
        }

        /** Forwards the whole captured text once generation has ended. */
        private fun flushAll() {
            if (textBuilder.length <= forwardedLength) return
            val chunk = textBuilder.substring(forwardedLength)
            forwardedLength = textBuilder.length
            onToken?.invoke(chunk)
        }

        /**
         * Returns the index up to which text is safe to forward: trailing
         * whitespace and a possible "1", "1." or "1)" marker are held back
         * until the next token shows whether a step starts.
         */
        private fun holdbackStart(text: CharSequence): Int {
            var i = text.length
            while (i > 0 && text[i - 1].isWhitespace()) i--
            if (i == 0) return 0
            val last = text[i - 1]
            if (last == '.' || last == ')') {
                if (i >= 2 && text[i - 2] == '1') {
                    i -= 2
                } else {
                    return i
                }
            } else if (last == '1') {
                i -= 1
            } else {
                return i
            }
            while (i > 0 && text[i - 1].isWhitespace()) i--
            return i
        }

        private fun stopModuleForCallback() {
            if (llmModule === mod) {
                try {
                    mod.stop()
                } catch (e: Throwable) {
                    Log.w(
                        TAG,
                        "LlamaAdvisor: failed to stop Llama module: " +
                            "${e::class.simpleName}: ${e.message}",
                        e
                    )
                }
            }
        }

        override fun onStats(stats: String) {
            statsJson = stats
            try {
                Log.i("PS3Llama", stats)
            } catch (_: Exception) {
                // Best-effort stats logging must never break the generation callback.
            }
        }

        override fun onError(code: Int, message: String) {
            // error handled via fallback
        }
    }

    private fun schedulePrefixPrefill(mod: LlmModule, prefix: String) {
        // FIX 1 (2026-11-24, owner decision): LIGHT tier never runs a background
        // prefix prefill. On a LIGHT phone the prefill takes 11-25 s and holds the
        // ExecuTorch gate, so an SMS arriving in that window waited 7-12 s for its
        // verdict (detect_waited_ms 7273-12712 on the Galaxy M31). LIGHT advice
        // prefills its prefix in the foreground instead (PATH_PREFIX_ON_DEMAND).
        if (!shouldScheduleBackgroundPrefill(lightTier)) {
            prefixReady = false
            Log.i(TIMING_TAG, "prefill_skipped reason=light_tier")
            return
        }
        if (!prefixCacheActive) return
        prefixReady = false
        try {
            prefillFuture?.cancel(false)
            val future = prefillExecutor.submit {
                // A previous on-demand cancel may have left this reused
                // prefill thread interrupted; clear it so the idle wait
                // below does not abort immediately.
                Thread.interrupted()
                moduleLock.lock()
                try {
                    if (llmModule === mod) runPrefixPrefill(mod, prefix)
                } finally {
                    moduleLock.unlock()
                }
            }
            prefillFuture = future
        } catch (e: Exception) {
            prefixCacheActive = false
            Log.w(
                TAG,
                "LlamaAdvisor: prefix prefill scheduling failed, falling back to $PATH_FULL_PROMPT: " +
                    "${e::class.simpleName}: ${e.message}",
                e
            )
        }
    }

    /** Runs the prefix prefill on the detection gate; caller must hold the module lock. */
    private fun runPrefixPrefill(mod: LlmModule, prefix: String) {
        // DT-18 detection priority: never start while a detection or advice is
        // pending, and on LIGHT delay until the idle period has passed since
        // the last activity ended. A detection arriving during the idle wait
        // postpones this prefill; the gate re-checks right before this block.
        val idleDelayMs = prefillIdleDelayMs(lightTier)
        val deferStartMs = System.nanoTime() / 1_000_000L
        try {
            ExecutorchGate.withPrefillDelayed(idleDelayMs) {
                // Right before the native prefill starts: if activity arrived
                // since the gate re-check, abort this prefill (the next
                // advice takes the on-demand path) instead of competing
                // with that detection or advice.
                val nowMs = System.nanoTime() / 1_000_000L
                val reason = prefillDeferReason(
                    ExecutorchGate.isDetectionPending(),
                    ExecutorchGate.isAdvicePending(),
                    nowMs,
                    ExecutorchGate.lastActivityBaselineMs(),
                    idleDelayMs
                )
                if (reason != null) {
                    val deferredMs = nowMs - deferStartMs
                    Log.i(TIMING_TAG, "prefill_deferred_ms=$deferredMs reason=$reason")
                    throw ExecutorchGate.PrefillTimeoutException(deferredMs)
                }
                prefixReady = false
                try {
                    mod.resetContext()
                    val prefillStartMs = SystemClock.elapsedRealtime()
                    mod.prefillPrompt(prefix)
                    val prefillMs = SystemClock.elapsedRealtime() - prefillStartMs
                    if (coldStartPrefillLogged.compareAndSet(false, true)) {
                        Log.i(TIMING_TAG, "prefix_prefill_ms=$prefillMs")
                    }
                    prefixReady = true
                    Log.i(TAG, "LlamaAdvisor: prefix prefill ready path=$PATH_PREFIX_CACHE")
                } catch (e: Throwable) {
                    prefixReady = false
                    prefixCacheActive = false
                    Log.w(
                        TAG,
                        "LlamaAdvisor: prefix prefill failed, falling back to $PATH_FULL_PROMPT: " +
                            "${e::class.simpleName}: ${e.message}",
                        e
                    )
                    try {
                        mod.resetContext()
                    } catch (resetError: Throwable) {
                        Log.w(
                            TAG,
                            "LlamaAdvisor: resetContext after prefill failure failed: " +
                                "${resetError::class.simpleName}: ${resetError.message}",
                            resetError
                        )
                    }
                }
            }
        } catch (e: ExecutorchGate.PrefillTimeoutException) {
            Thread.interrupted()
            val deferredMs = System.nanoTime() / 1_000_000L - deferStartMs
            val reason = prefillDeferReason(
                ExecutorchGate.isDetectionPending(),
                ExecutorchGate.isAdvicePending(),
                System.nanoTime() / 1_000_000L,
                ExecutorchGate.lastActivityBaselineMs(),
                idleDelayMs
            ) ?: "prefill_timeout"
            prefixReady = false
            Log.i(TIMING_TAG, "prefill_deferred_ms=$deferredMs reason=$reason")
        }
    }

    private fun awaitPrefixReady(timeoutMs: Long): Boolean {
        if (prefixReady) return true
        val future = prefillFuture ?: return false
        return try {
            future.get(timeoutMs, TimeUnit.MILLISECONDS)
            prefixReady
        } catch (_: Exception) {
            // Timeout or prefill failure: the caller falls back to the full-prompt path.
            prefixReady
        }
    }

    /**
     * Shuts down the prefill executor and releases native LlmModule memory under exclusive lock.
     */
    override fun close() {
        try {
            prefillExecutor.shutdownNow()
        } catch (_: Exception) {
            // Cleanup must complete even when the prefill executor fails to stop, so this is ignored.
        }
        // Module lock first, then the exclusive gate: the lock order matches generate and prefill,
        // so close waits for any in-flight generation or prefill while the gate blocks forwards.
        moduleLock.lock()
        try {
            val toClose = llmModule
            llmModule = null
            if (toClose != null) {
                try {
                    ExecutorchGate.withExclusive { toClose.close() }
                } catch (_: Exception) {
                    // Cleanup must complete even when the native module fails to close, so this is deliberately ignored.
                }
            }
        } finally {
            moduleLock.unlock()
        }
    }
}

/**
 * Runs the watchdog stop without acquiring the fair shared gate.
 *
 * The generation already holds the shared side for its whole run, and the
 * watchdog starts only after that acquisition, so re-acquiring the fair gate
 * here would queue a new reader behind any queued exclusive writer and could
 * wait indefinitely while the hung generation it must abort still holds the
 * read side. stop() does not reset the shared pool, so — like the ungated
 * stop in GenerationCallback.onResult — it is safe to call directly and the
 * stop always reaches the native module.
 */
internal fun runWatchdogStop(isCurrent: Boolean, stop: () -> Unit): Boolean {
    if (!isCurrent) return false
    stop()
    return true
}

/** Checks if the running generation matches the target generation ID. */
internal fun isWatchdogGenerationCurrent(currentId: Long, capturedId: Long): Boolean =
    currentId != 0L && currentId == capturedId

/** Runs Llama load then pool restore inside one exclusive section, so no forward can run between them. */
internal fun <T> withLlamaLoadAndPoolRestore(load: () -> T, restore: () -> Unit): T =
    ExecutorchGate.withExclusive {
        val loaded = load()
        restore()
        loaded
    }

/** Decision result indicating whether the fixed prompt prefix KV-cache is enabled. */
internal data class PrefixCacheDecision(val enabled: Boolean, val reason: String)

/** Resolves prefix cache enablement from runtime flags, override parameters, and defaults. */
internal fun resolvePrefixCacheDecision(modelsDir: File?, overrideEnabled: Boolean?): PrefixCacheDecision {
    if (overrideEnabled != null) {
        return PrefixCacheDecision(overrideEnabled, "explicit usePrefixCache=$overrideEnabled")
    }
    if (modelsDir != null && File(modelsDir, LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME).exists()) {
        return PrefixCacheDecision(false, "flag file ${LlamaAdvisor.PREFIX_CACHE_OFF_FLAG_FILE_NAME} present")
    }
    if (modelsDir != null && File(modelsDir, LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME).exists()) {
        return PrefixCacheDecision(true, "flag file ${LlamaAdvisor.PREFIX_CACHE_FLAG_FILE_NAME} present")
    }
    return PrefixCacheDecision(
        LlamaAdvisor.USE_PREFIX_CACHE,
        "constant USE_PREFIX_CACHE=${LlamaAdvisor.USE_PREFIX_CACHE}, no flag file"
    )
}

/** Checks whether the KV-cache context must be reset before generating for [usedPath]. */
internal fun needsResetBeforeGenerate(usedPath: String): Boolean =
    usedPath == LlamaAdvisor.PATH_FULL_PROMPT || usedPath == LlamaAdvisor.PATH_PREFIX_ON_DEMAND

/** Resolves prompt path given runtime cache state, tier, and lock conditions. */
internal fun resolvePathUnderLock(
    selectedPath: String, prefixReady: Boolean, prefixCacheActive: Boolean
): String = resolvePathUnderLock(selectedPath, prefixReady, prefixCacheActive, false)

/** Resolves prompt path given runtime cache state, tier, and lock conditions. */
internal fun resolvePathUnderLock(
    selectedPath: String, prefixReady: Boolean, prefixCacheActive: Boolean, isLightTier: Boolean
): String =
    when {
        selectedPath == LlamaAdvisor.PATH_PREFIX_ON_DEMAND && prefixCacheActive && prefixReady ->
            LlamaAdvisor.PATH_PREFIX_CACHE
        selectedPath == LlamaAdvisor.PATH_PREFIX_ON_DEMAND && !prefixCacheActive ->
            LlamaAdvisor.PATH_FULL_PROMPT
        selectedPath == LlamaAdvisor.PATH_PREFIX_CACHE && !prefixReady && isLightTier && prefixCacheActive ->
            LlamaAdvisor.PATH_PREFIX_ON_DEMAND
        selectedPath == LlamaAdvisor.PATH_PREFIX_CACHE && !prefixReady ->
            LlamaAdvisor.PATH_FULL_PROMPT
        selectedPath == LlamaAdvisor.PATH_FULL_PROMPT && prefixCacheActive && prefixReady ->
            LlamaAdvisor.PATH_PREFIX_CACHE
        else -> selectedPath
    }

/**
 * DT-18 second fix: prompt path chosen before the generation lock is taken.
 * LIGHT with no ready prefix takes the foreground on-demand path (never a
 * silent full prompt, never a wait for the deferred background prefill);
 * FULL tier keeps the previous behaviour (caller may still wait bounded
 * for a running prefill and then fall back to the full prompt).
 */
internal fun selectPromptPath(
    prefixCacheActive: Boolean, prefixReady: Boolean, isLightTier: Boolean
): String =
    when {
        !prefixCacheActive -> LlamaAdvisor.PATH_FULL_PROMPT
        prefixReady -> LlamaAdvisor.PATH_PREFIX_CACHE
        isLightTier -> LlamaAdvisor.PATH_PREFIX_ON_DEMAND
        else -> LlamaAdvisor.PATH_FULL_PROMPT
    }

/** DT-18: LIGHT-tier idle delay for the re-prefill; 0 on FULL tier. */
internal fun prefillIdleDelayMs(isLightTier: Boolean): Long =
    if (isLightTier) LlamaAdvisor.LIGHT_PREFILL_IDLE_DELAY_MS else 0L

/**
 * FIX 1: background prefix prefill is a FULL-tier optimisation only.
 *
 * A LIGHT phone pays 11-25 s of gate time for one prefill and stalls an SMS that
 * arrives meanwhile by 7-12 s (measured on the Galaxy M31, 2026-11-24), so LIGHT
 * never schedules it: advice prefills the prefix on demand inside its own
 * request (PATH_PREFIX_ON_DEMAND) and detection never queues behind a prefill.
 */
internal fun shouldScheduleBackgroundPrefill(isLightTier: Boolean): Boolean = !isLightTier

/** DT-18: true when no activity ended or started within [idleDelayMs] of [nowMs]. */
internal fun isPrefillIdle(nowMs: Long, lastActivityMs: Long, idleDelayMs: Long): Boolean =
    ExecutorchGate.isPrefillIdle(nowMs, lastActivityMs, idleDelayMs)

/** DT-18: true when a prefill must defer: detection pending or idle delay not met. */
internal fun shouldDeferPrefill(
    detectionPending: Boolean,
    nowMs: Long,
    lastActivityMs: Long,
    idleDelayMs: Long
): Boolean = ExecutorchGate.shouldDeferPrefill(detectionPending, nowMs, lastActivityMs, idleDelayMs)

/** DT-18: true when a prefill must defer: detection or advice pending, or idle not met. */
internal fun shouldDeferPrefill(
    detectionPending: Boolean,
    advicePending: Boolean,
    nowMs: Long,
    lastActivityMs: Long,
    idleDelayMs: Long
): Boolean =
    ExecutorchGate.shouldDeferPrefill(detectionPending, advicePending, nowMs, lastActivityMs, idleDelayMs)

/** Null when a prefill may start now, otherwise the deferral reason. */
internal fun prefillDeferReason(
    detectionPending: Boolean,
    advicePending: Boolean,
    nowMs: Long,
    lastActivityMs: Long,
    idleDelayMs: Long
): String? {
    if (!shouldDeferPrefill(detectionPending, advicePending, nowMs, lastActivityMs, idleDelayMs)) {
        return null
    }
    return when {
        detectionPending -> "detection_pending"
        advicePending -> "advice_pending"
        else -> "idle_delay"
    }
}

/** Formats standardized benchmark log output with prompt path, tokens, TTFT, and advice hash. */
internal fun formatBenchLine(promptPath: String, stats: LlamaStats?, advice: String): String {
    val promptTokens = stats?.promptTokens ?: 0
    val ttft = stats?.ttftMs ?: 0.0
    val decode = stats?.decodeTokensPerSec ?: 0.0
    val ttftStr = String.format(Locale.US, "%.1f", ttft)
    val decodeStr = String.format(Locale.US, "%.1f", decode)
    return "prompt_path=$promptPath prompt_tokens=$promptTokens ttft_ms=$ttftStr " +
        "decode_tok_s=$decodeStr advice_sha8=${sha256Short(advice)}"
}

/** Parses JSON stats string from ExecuTorch LlmModule callback into structured [LlamaStats]. */
internal fun parseLlamaStats(jsonStr: String?): LlamaStats? {
    if (jsonStr.isNullOrEmpty()) return null
    return try {
        val json = JSONObject(jsonStr)
        val promptTokens = json.optInt("prompt_tokens", json.optInt("num_prompt_tokens", 0))
        val generatedTokens = json.optInt("generated_tokens", json.optInt("num_generated_tokens", 0))

        val hasTimestamps = json.has("inference_start_ms") ||
            json.has("prompt_eval_end_ms") ||
            json.has("first_token_ms") ||
            json.has("inference_end_ms")

        return if (hasTimestamps) {
            parseLlamaStatsWithTimestamps(json, promptTokens, generatedTokens)
        } else {
            parseLlamaStatsDirectFields(json, promptTokens, generatedTokens)
        }
    } catch (_: Exception) {
        // Malformed stats JSON is non-fatal: timing stats are optional, so return null without failing generation.
        null
    }
}

/** Parses timestamp-based Llama stats JSON (ExecuTorch LlmModule callback format). */
internal fun parseLlamaStatsWithTimestamps(
    json: JSONObject,
    promptTokens: Int,
    generatedTokens: Int
): LlamaStats {
    val scaleRaw = json.optDouble("SCALING_FACTOR_UNITS_PER_SECOND", 1000.0)
    val scale = if (scaleRaw > 0.0 && scaleRaw.isFinite()) scaleRaw else 1000.0

    val inferenceStartMs = json.optDouble("inference_start_ms", 0.0)
    val promptEvalEndMs = json.optDouble("prompt_eval_end_ms", 0.0)
    val firstTokenMs = json.optDouble("first_token_ms", 0.0)
    val inferenceEndMs = json.optDouble("inference_end_ms", 0.0)

    val prefillInterval = (promptEvalEndMs - inferenceStartMs) / scale
    val prefillTps = if (promptTokens > 0 && prefillInterval > 0.0 && prefillInterval.isFinite()) {
        val rate = promptTokens / prefillInterval
        if (rate.isFinite() && rate > 0.0) rate else 0.0
    } else 0.0

    val decodeInterval = (inferenceEndMs - firstTokenMs) / scale
    val decodeTps = if (generatedTokens > 1 && decodeInterval > 0.0 && decodeInterval.isFinite()) {
        val rate = (generatedTokens - 1) / decodeInterval
        if (rate.isFinite() && rate > 0.0) rate else 0.0
    } else 0.0

    val ttftMs = if (firstTokenMs >= inferenceStartMs && json.has("first_token_ms") && json.has("inference_start_ms")) {
        val diff = firstTokenMs - inferenceStartMs
        if (diff.isFinite()) diff else 0.0
    } else 0.0

    val totalTimeMs = if (inferenceEndMs >= inferenceStartMs && json.has("inference_end_ms") && json.has("inference_start_ms")) {
        val diff = inferenceEndMs - inferenceStartMs
        if (diff.isFinite()) diff else 0.0
    } else 0.0

    return LlamaStats(
        promptTokens = promptTokens,
        generatedTokens = generatedTokens,
        prefillTokensPerSec = prefillTps,
        decodeTokensPerSec = decodeTps,
        totalTimeMs = totalTimeMs,
        ttftMs = ttftMs
    )
}

/** Parses direct-field Llama stats JSON (prefill_tokens_per_sec / decode_tokens_per_sec / total_time_ms / ttft_ms). */
internal fun parseLlamaStatsDirectFields(
    json: JSONObject,
    promptTokens: Int,
    generatedTokens: Int
): LlamaStats {
    val prefillTps = json.optDouble("prefill_tokens_per_sec", json.optDouble("prompt_eval_tok_per_sec", 0.0))
    val decodeTps = json.optDouble("decode_tokens_per_sec", json.optDouble("eval_tok_per_sec", 0.0))
    val totalTime = json.optDouble("total_time_ms", 0.0)
    val ttft = json.optDouble("ttft_ms", 0.0)

    return LlamaStats(
        promptTokens = promptTokens,
        generatedTokens = generatedTokens,
        prefillTokensPerSec = if (prefillTps.isFinite()) prefillTps else 0.0,
        decodeTokensPerSec = if (decodeTps.isFinite()) decodeTps else 0.0,
        totalTimeMs = if (totalTime.isFinite()) totalTime else 0.0,
        ttftMs = if (ttft.isFinite()) ttft else 0.0
    )
}

/**
 * Maps advice guard flags to the source attribution ("template" vs "llm").
 * Contradictions, empty output, and safety refusals all trigger fallback to template.
 */
internal fun resolveAdviceSource(flags: Collection<String>): String =
    if ("contradiction_fallback" in flags || "empty_fallback" in flags || "refusal_fallback" in flags) "template" else "llm"

