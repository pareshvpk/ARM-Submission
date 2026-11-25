// Governs model startup sequencing, memory trim thresholds, and Llama gating.
// Pure Kotlin logic with no Android framework classes, ensuring SMS and URL models
// load before heavy LLM weights and managing thread-count heuristics.

package org.ps3.sentinel.ml

/**
 * Purpose:  Decides the model load order and the Llama start gate.
 * Owns:     Nothing. Pure ordering and gating rules.
 * Lifetime: Process
 * Thread:   any — no mutable state is touched.
 */
object ModelLoadPlan {
    // rules, url, sms, llama — alert path (rules to sms) loads first so a
    // broadcast-started process can alert without hashing or loading Llama.
    val LOAD_ORDER: List<String> = listOf("rules", "url", "sms", "llama")

    // 8000 ms — cold-open budget for a UI-gated Llama load. Detection is shown
    // immediately; advice waits this long for Llama before falling back so a
    // MEDIUM/HIGH message still gets Llama advice after a share-intent cold
    // start instead of the template that never waited for the load.
    const val LLAMA_LOAD_WAIT_MS: Long = 8000L

    // 100 ms — advise poll cadence while waiting for Llama: notifies quickly
    // once the load lands without spinning the little-core cpuset.
    const val LLAMA_ADVISE_POLL_INTERVAL_MS: Long = 100L

    // 30000 ms — ceiling for awaiting the background re-hash of a trusted Llama
    // file before advice may stream. The re-hash runs in parallel with the load
    // and prefill, so this only bounds a slow or stalled hash; on timeout advice
    // falls back to the template instead of using unverified bytes.
    const val LLAMA_VERIFY_TIMEOUT_MS: Long = 30_000L

    // 20 — ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN: first level where the UI is gone
    // but the process still lives. Releasing at this level keeps swapped XNNPACK
    // pages out of zram while the app sits in the background.
    const val TRIM_LEVEL_UI_HIDDEN: Int = 20

    // 40 — ComponentCallbacks2.TRIM_MEMORY_BACKGROUND: system backgrounding pressure.
    // Mirrors the UI-hidden threshold; the release check uses the lower bound so
    // either background level frees Llama without waiting for a critical trim.
    const val TRIM_LEVEL_BACKGROUND: Int = 40

    // Gate: Llama verify, load and prefix prefill start only after MainActivity
    // has been started at least once in this process. A broadcast-started
    // process has no visible UI, so its anonymous-weight pages would be swapped
    // to zram and every later token would decompress them (measured 30 s
    // prefill with 360 MB VmSwap). The SMS alert path never needs Llama.
    // deferredPending is required (no default) so a caller cannot omit it
    // and let Llama start while a deferred SMS analysis is still queued.
    /**
     * Evaluates whether background loading and prefix prefill of Llama should proceed.
     *
     * @param smsReady Whether SMS classifier model and tokenizer initialization completed.
     * @param uiOpened Whether MainActivity has been brought to the foreground in this process.
     * @param smsAnalysisWaiting Whether an SMS broadcast is awaiting fast-path analysis.
     * @param deferredPending Whether persistent deferred SMS analyses remain queued.
     * @return True if conditions allow loading Llama without risking memory swap or alert delay.
     */
    fun shouldLoadLlama(
        smsReady: Boolean,
        uiOpened: Boolean,
        smsAnalysisWaiting: Boolean,
        deferredPending: Boolean
    ): Boolean = smsReady && uiOpened && !smsAnalysisWaiting && !deferredPending

    // Release gate for onTrimMemory: free Llama once the UI is hidden when idle.
    // analysisRunning blocks release so an in-flight generation is never killed
    // mid-stream; llamaLoaded is required so a null advisor is not closed twice.
    // prefillRunning blocks release so a background prefix prefill (which holds the
    // Llama module lock for seconds) is never closed mid-prefill on the main thread.
    /**
     * Determines whether Llama runtime memory should be freed during system memory trim callbacks.
     *
     * @param trimLevel Memory pressure level reported by ComponentCallbacks2.
     * @param analysisRunning Whether an active UI or SMS analysis is currently in progress.
     * @param llamaLoaded Whether an instantiated LlamaAdvisor module is currently held.
     * @param prefillRunning Whether a background prompt-prefix prefill is active.
     * @return True if Llama weights and runtime buffers should be released.
     */
    fun shouldReleaseLlama(
        trimLevel: Int,
        analysisRunning: Boolean,
        llamaLoaded: Boolean,
        prefillRunning: Boolean = false
    ): Boolean = llamaLoaded && !analysisRunning && !prefillRunning && trimLevel >= TRIM_LEVEL_UI_HIDDEN

    // True when advise should keep waiting for a UI-gated Llama load. Only
    // MEDIUM/HIGH advice needs Llama; LOW uses the template without waiting.
    /**
     * Checks if advice generation should wait for an in-flight UI-gated Llama load.
     *
     * @param level Evaluated threat level ("low", "medium", or "high").
     * @param advisorLoaded Whether the LlamaAdvisor instance has finished loading.
     * @param elapsedMs Duration in milliseconds already spent waiting for model load.
     * @return True if the request requires Llama and wait duration is under [LLAMA_LOAD_WAIT_MS].
     */
    fun shouldWaitForLlama(level: String, advisorLoaded: Boolean, elapsedMs: Long): Boolean =
        level in setOf("medium", "high") && !advisorLoaded && elapsedMs < LLAMA_LOAD_WAIT_MS

    // Matches the ExecuTorch Module default (cpuinfo processors / 2) so every
    // Module.load after Llama re-asserts the same pool the Llama generation
    // needs; the Llama native ctor itself has no thread knob and resets the
    // shared singleton pool to performant-cores minus one (1 on the F14).
    /**
     * Determines the fallback thread pool size for ExecuTorch modules.
     *
     * @param availableProcessors Number of logical processor cores returned by the runtime.
     * @return Selected thread count, defaulting to at least 1 and half the available cores.
     */
    fun selectThreadCount(availableProcessors: Int): Int =
        maxOf(1, availableProcessors / 2)

    // threads.auto is read once per process (DT-17): the first caller with a
    // non-null models dir fixes the value for every later caller, so URL, SMS and
    // Llama always agree on the thread count even when they pass different dirs
    // (external vs internal) or the file appears after the first load.
    @Volatile
    private var cachedThreadsAuto: Boolean? = null

    private val cachedThreadsAutoLock = Any()

    /**
     * Checks if dynamic CPU cluster-based thread assignment is enabled via flag file.
     *
     * Result is cached in memory per process after first query with a non-null directory.
     *
     * @param modelsDir Directory where model assets and opt-in flags reside.
     * @return True if threads.auto flag is present.
     */
    fun isThreadsAutoEnabled(modelsDir: java.io.File?): Boolean {
        cachedThreadsAuto?.let { return it }
        if (modelsDir == null) return false
        synchronized(cachedThreadsAutoLock) {
            cachedThreadsAuto?.let { return it }
            val result = try {
                CpuFeatures.isThreadsAutoEnabled(modelsDir)
            } catch (_: Exception) {
                false
            }
            cachedThreadsAuto = result
            return result
        }
    }

    /**
     * Clears the cached threads.auto flag decision for unit test isolation.
     */
    internal fun resetThreadsAutoCacheForTest() {
        synchronized(cachedThreadsAutoLock) {
            cachedThreadsAuto = null
        }
    }

    /**
     * Selects ExecuTorch execution thread count, honoring threads.auto if enabled.
     *
     * @param availableProcessors Fallback logical core count.
     * @param clusters Detected CPU core clusters (frequency to core count pairs).
     * @param modelsDir Directory checked for threads.auto opt-in flag.
     * @return Recommended thread count based on cluster topology or fallback ratio.
     */
    fun selectThreadCountWithAuto(
        availableProcessors: Int,
        clusters: List<Pair<Long, Int>>,
        modelsDir: java.io.File?
    ): Int {
        val proposal = CpuFeatures.proposeThreadCount(clusters)
        val autoEnabled = try {
            isThreadsAutoEnabled(modelsDir)
        } catch (_: Exception) {
            false
        }
        return if (autoEnabled) proposal else selectThreadCount(availableProcessors)
    }
}
