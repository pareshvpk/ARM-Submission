// Coordinates concurrency across ExecuTorch native runtime executions in the app process.
// Uses read-write locks and fair mutexes to prevent concurrent module loading and forwards,
// preventing pthreadpool corruption and prioritizing SMS detection over background LLM prefill.

package org.ps3.sentinel.ml

import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.locks.ReentrantLock
import java.util.concurrent.locks.ReentrantReadWriteLock

/**
 * Purpose:  Serialises ExecuTorch native work because loading a module resets the shared
 *           thread pool under a running forward pass, which crashed on the Galaxy F14 with
 *           FORTIFY: pthread_mutex_lock called on a destroyed mutex (UrlClassifier.score on a
 *           Default thread while a UI-gated 453 ms Llama load reset the pool, 28 ms after the tap).
 * Owns:     The single process-wide read-write lock.
 * Lifetime: Process
 * Thread:   any — blocking lock; call it off the main thread.
 */
object ExecutorchGate {

    // 10000 ms — detection bound: a background prefix prefill takes about 3 s on the
    // Galaxy F14 and a forward takes tens of ms, so 10 s covers a healthy holder
    // several times over while still guaranteeing detection never hangs on CHECKING
    // forever (DT-17). On timeout the caller falls back to rule-only detection.
    const val DETECTION_WAIT_TIMEOUT_MS: Long = 10_000L

    // 10000 ms — prefill bound: waiting for pending detection or the mutex longer
    // than this aborts the prefill instead of blocking it forever under a detection
    // flood; the generation then uses the full-prompt path.
    const val PREFILL_WAIT_TIMEOUT_MS: Long = 10_000L

    // 15000 ms — DT-18: how long a prefix prefill may hold the detection mutex.
    // About 3 s on the Galaxy F14, longer on a LIGHT Armv8.0 phone without dot
    // product, so 15 s covers a slow healthy prefill while still bounding detection.
    const val PREFILL_RUN_TIMEOUT_MS: Long = 15_000L

    // 5000 ms — DT-18: extra time for the detector itself after a running prefill
    // releases, so detection does not fall back to rules merely because a prefill
    // was running. Detection waits up to prefill bound plus this margin.
    const val DETECTION_MARGIN_MS: Long = 5_000L

    // 20000 ms — DT-18: detection wait while a prefill holds the mutex: prefill
    // bounded duration plus margin. Kept separate from DETECTION_WAIT_TIMEOUT_MS
    // so the detector's own timeout is not consumed by the prefill wait.
    const val DETECTION_WAIT_TIMEOUT_WHILE_PREFILL_MS: Long = PREFILL_RUN_TIMEOUT_MS + DETECTION_MARGIN_MS

    // 5000 ms — DT-18: LIGHT-tier idle delay. On a LIGHT phone the re-prefill
    // starts only when no detection or advice is pending and this long has
    // passed since the last activity ended, so detection always wins the
    // next slot. FULL tier uses 0 (unchanged behaviour).
    const val LIGHT_PREFILL_IDLE_DELAY_MS: Long = 5_000L

    /**
     * Thrown when an SMS or URL detection forward pass exceeds its wait budget for the native gate.
     *
     * @property waitedMs Duration in milliseconds waited before giving up.
     */
    class DetectionTimeoutException(val waitedMs: Long) :
        IllegalStateException("detection wait timed out after $waitedMs ms")

    /**
     * Thrown when background prompt-prefix prefill times out waiting for higher-priority work or the mutex.
     *
     * @property waitedMs Duration in milliseconds waited before giving up.
     */
    class PrefillTimeoutException(val waitedMs: Long) :
        IllegalStateException("prefill wait timed out after $waitedMs ms")

    // Fair: without it, reader barging could starve a writer indefinitely under an SMS flood, but
    // Llama loads must start promptly after the UI opens (measured about 0.5 s). Fairness only
    // orders waiters; admitted readers still run together.
    private val gate = ReentrantReadWriteLock(true)

    // DT-15: detection must not run concurrently with background prefix prefill.
    // A single fair mutex serialises the two; fairness queues waiters in order so a
    // detection arriving after a queued prefill waits its turn instead of barging
    // (and vice versa). Detection increments the counter before acquiring the mutex
    // so a waiting prefill sees detection as pending and defers until it finishes.
    // A detection that arrives while a prefill already holds the mutex waits with a
    // bounded timeout and logs detect_waited_ms / detect_wait_timeout_ms.
    private val prefillDetectionMutex = ReentrantLock(true)
    private val detectionPending = AtomicInteger(0)
    // DT-18: true while a prefill holds the detection mutex, with its start time,
    // so detection knows the holder is a prefill and can wait up to its bound.
    private val prefillRunning = AtomicBoolean(false)
    private val prefillStartNanos = AtomicLong(0L)
    // DT-18: monotonic start of the most recent detection (including expected
    // detections marked before the model forward). LIGHT prefill idle delay is
    // measured from the later of this and the last activity end, so a detection
    // that is expected but has not ended yet still postpones a prefill, while a
    // detection that started about an advice duration ago and just ended does
    // not let a re-prefill start at once.
    private val lastDetectionStartNanos = AtomicLong(0L)
    // DT-18 second fix: monotonic time the last activity ended (a detection
    // finishing, an advice generation finishing or failing, or a template
    // advice being shown). LIGHT re-prefill idle delay is measured from this;
    // 0 means no activity has ended yet this process.
    private val lastActivityEndNanos = AtomicLong(0L)
    // DT-18 second fix: advice generations currently in flight. A prefill must
    // never start while an advice is pending, even on FULL tier idle delay 0.
    private val advicePending = AtomicInteger(0)

    /** Checks whether any detection forward pass is queued or actively running. */
    fun isDetectionPending(): Boolean = detectionPending.get() > 0

    /** Returns the count of concurrent detection forward passes queued or running. */
    fun detectionPendingCount(): Int = detectionPending.get()

    /** Checks whether any LLM advice generation task is currently in flight. */
    fun isAdvicePending(): Boolean = advicePending.get() > 0

    /** Returns the count of concurrent advice generation tasks in flight. */
    fun advicePendingCount(): Int = advicePending.get()

    /** Checks whether a prompt-prefix prefill holds the prefill mutex. */
    fun isPrefillRunning(): Boolean = prefillRunning.get()

    /** Monotonic start timestamp (in nanoseconds) of the most recent detection. */
    fun lastDetectionStartNanos(): Long = lastDetectionStartNanos.get()

    /** Monotonic start timestamp (in milliseconds) of the most recent detection, or 0 if none. */
    fun lastDetectionStartMs(): Long {
        val nanos = lastDetectionStartNanos.get()
        return if (nanos == 0L) 0L else nanos / 1_000_000L
    }

    /** Monotonic completion timestamp (in nanoseconds) of the last detection or advice task. */
    fun lastActivityEndNanos(): Long = lastActivityEndNanos.get()

    /** Monotonic completion timestamp (in milliseconds) of the last detection or advice task, or 0 if none. */
    fun lastActivityEndMs(): Long {
        val nanos = lastActivityEndNanos.get()
        return if (nanos == 0L) 0L else nanos / 1_000_000L
    }

    /**
     * Idle baseline: the later of the last detection start/expected mark and
     * the last activity end. For a finished detection the end is later, so the
     * delay counts from its end; for an expected or in-flight detection the
     * start is later than the previous end, so it still postpones the prefill.
     */
    fun lastActivityBaselineMs(): Long =
        maxOf(lastDetectionStartMs(), lastActivityEndMs())

    /** Marks a detection as expected now: resets the LIGHT prefill idle timer. */
    fun markDetectionExpected() {
        lastDetectionStartNanos.set(System.nanoTime())
    }

    /** Records that the last detection or advice activity has ended now. */
    fun markActivityEnded() {
        lastActivityEndNanos.set(System.nanoTime())
    }

    /** Alias for call sites that mean a detection just finished. */
    fun markDetectionEnded() = markActivityEnded()

    /** Marks an advice generation as in flight; pairs with [endAdvice]. */
    fun beginAdvice() {
        advicePending.incrementAndGet()
    }

    /** Marks an advice generation as finished or failed; records its end time. */
    fun endAdvice() {
        markActivityEnded()
        if (advicePending.decrementAndGet() < 0) {
            advicePending.set(0)
        }
    }

    /** True when no activity ended or started within [idleDelayMs] of [nowMs]. */
    internal fun isPrefillIdle(nowMs: Long, lastActivityMs: Long, idleDelayMs: Long): Boolean {
        if (lastActivityMs <= 0L) return true
        if (idleDelayMs <= 0L) return true
        return nowMs - lastActivityMs >= idleDelayMs
    }

    /** True when a prefill must defer: detection pending or idle delay not met. */
    internal fun shouldDeferPrefill(
        detectionPending: Boolean,
        nowMs: Long,
        lastActivityMs: Long,
        idleDelayMs: Long
    ): Boolean = shouldDeferPrefill(detectionPending, false, nowMs, lastActivityMs, idleDelayMs)

    /** True when a prefill must defer: detection or advice pending, or idle not met. */
    internal fun shouldDeferPrefill(
        detectionPending: Boolean,
        advicePending: Boolean,
        nowMs: Long,
        lastActivityMs: Long,
        idleDelayMs: Long
    ): Boolean =
        detectionPending || advicePending || !isPrefillIdle(nowMs, lastActivityMs, idleDelayMs)

    /** Clears timestamps and counter states for isolated unit test runs. */
    internal fun resetForTest() {
        lastDetectionStartNanos.set(0L)
        lastActivityEndNanos.set(0L)
        detectionPending.set(0)
        advicePending.set(0)
        prefillRunning.set(false)
        prefillStartNanos.set(0L)
    }

    /**
     * Executes [block] with priority over background prefill using [DETECTION_WAIT_TIMEOUT_MS].
     *
     * @param block Computation to run inside the shared gate under detection mutex.
     * @return Result of [block].
     * @throws DetectionTimeoutException if lock acquisition times out.
     */
    fun <T> withDetection(block: () -> T): T =
        withDetection(DETECTION_WAIT_TIMEOUT_MS, block)

    /**
     * Executes [block] with priority over background prefill, bounded by [timeoutMs].
     *
     * @param timeoutMs Maximum wait duration in milliseconds before timing out.
     * @param block Computation to run inside the shared gate under detection mutex.
     * @return Result of [block].
     * @throws DetectionTimeoutException if lock acquisition times out.
     */
    fun <T> withDetection(timeoutMs: Long, block: () -> T): T {
        val waitStartNanos = System.nanoTime()
        var deadlineNanos = waitStartNanos + timeoutMs * 1_000_000L
        detectionPending.incrementAndGet()
        markDetectionExpected()
        var mutexAcquired = false
        var waitedMs: Long = 0L
        try {
            // DT-18: a running prefill cannot be interrupted, so detection waits
            // for it up to the prefill's own bounded duration plus margin. Only a
            // real timeout of the detector itself falls back to rules.
            while (!mutexAcquired) {
                if (prefillRunning.get()) {
                    val prefStart = prefillStartNanos.get()
                    val prefDeadline = if (prefStart != 0L) {
                        prefStart + PREFILL_RUN_TIMEOUT_MS * 1_000_000L + DETECTION_MARGIN_MS * 1_000_000L
                    } else {
                        waitStartNanos + DETECTION_WAIT_TIMEOUT_WHILE_PREFILL_MS * 1_000_000L
                    }
                    if (prefDeadline > deadlineNanos) {
                        deadlineNanos = prefDeadline
                    }
                }
                val remaining = remainingMs(deadlineNanos)
                if (remaining <= 0L) {
                    val waited = elapsedMs(waitStartNanos)
                    logGateTimeout("detect_wait_timeout_ms=$waited timeout_ms=$timeoutMs")
                    throw DetectionTimeoutException(waited)
                }
                mutexAcquired = try {
                    prefillDetectionMutex.tryLock(minOf(50L, remaining), TimeUnit.MILLISECONDS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    false
                }
            }
            waitedMs = elapsedMs(waitStartNanos)
            try {
                return withSharedTimed(
                    deadlineNanos,
                    waitStartNanos,
                    { DetectionTimeoutException(elapsedMs(waitStartNanos)) }
                ) {
                    block()
                }
            } finally {
                if (mutexAcquired) prefillDetectionMutex.unlock()
            }
        } finally {
            detectionPending.decrementAndGet()
            markActivityEnded()
            if (mutexAcquired && waitedMs > 0) {
                try {
                    android.util.Log.i("PS3Timing", "detect_waited_ms=$waitedMs")
                } catch (_: Exception) {
                }
            }
        }
    }

    /**
     * Executes background prefill [block] using default prefill wait timeout.
     *
     * @param block Computation to run under the prefill mutex and shared gate.
     * @return Result of [block].
     */
    fun <T> withPrefill(block: () -> T): T =
        withPrefill(PREFILL_WAIT_TIMEOUT_MS, block)

    /**
     * Executes background prefill [block] bounded by [timeoutMs].
     *
     * @param timeoutMs Maximum wait duration in milliseconds.
     * @param block Computation to run under the prefill mutex and shared gate.
     * @return Result of [block].
     */
    fun <T> withPrefill(timeoutMs: Long, block: () -> T): T =
        withPrefillDelayed(0L, timeoutMs, block)

    /**
     * Executes prefill [block] after ensuring [idleDelayMs] has passed since last activity.
     *
     * @param idleDelayMs Required quiet period in milliseconds before prefill starts.
     * @param block Computation to run under the prefill mutex and shared gate.
     * @return Result of [block].
     */
    fun <T> withPrefillDelayed(idleDelayMs: Long, block: () -> T): T =
        withPrefillDelayed(idleDelayMs, PREFILL_WAIT_TIMEOUT_MS, block)

    /**
     * Executes prefill [block] enforcing both [idleDelayMs] quiet period and [timeoutMs] limit.
     *
     * @param idleDelayMs Required quiet period in milliseconds before prefill starts.
     * @param timeoutMs Maximum wait duration in milliseconds.
     * @param block Computation to run under the prefill mutex and shared gate.
     * @return Result of [block].
     */
    fun <T> withPrefillDelayed(idleDelayMs: Long, timeoutMs: Long, block: () -> T): T {
        val waitStartNanos = System.nanoTime()
        val deadlineNanos = waitStartNanos + timeoutMs * 1_000_000L
        // DT-18 second fix: never start while a detection or advice is pending,
        // and on LIGHT wait until the idle delay has passed since the last
        // activity ended. The idle baseline is re-read every iteration, so a
        // detection or advice arriving during the idle wait updates the
        // baseline (its start, and later its end) and postpones the prefill.
        // Bounded; an interrupt aborts instead of running anyway. A timer
        // that fires early re-arms: the re-check after the mutex is acquired
        // loops back to the idle wait instead of starting the prefill.
        var lastDeferReason = "idle_delay"
        var deferredLogged = false
        while (true) {
            while (true) {
                val nowMs = System.nanoTime() / 1_000_000L
                val deferReason = prefillDeferReason(nowMs, idleDelayMs)
                if (deferReason == null) break
                lastDeferReason = deferReason
                if (!deferredLogged) {
                    logPrefillDeferred(elapsedMs(waitStartNanos), deferReason)
                    deferredLogged = true
                }
                val remaining = remainingMs(deadlineNanos)
                if (remaining <= 0L) {
                    val deferred = elapsedMs(waitStartNanos)
                    logGateTimeout("prefill_wait_timeout_ms=$deferred pending=${detectionPending.get()} advice_pending=${advicePending.get()} timeout_ms=$timeoutMs")
                    logPrefillDeferred(deferred, deferReason)
                    throw PrefillTimeoutException(deferred)
                }
                try {
                    Thread.sleep(minOf(50L, remaining))
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    val deferred = elapsedMs(waitStartNanos)
                    logPrefillDeferred(deferred, deferReason)
                    throw PrefillTimeoutException(deferred)
                }
            }
            if (!tryAcquireMutex(deadlineNanos)) {
                val deferred = elapsedMs(waitStartNanos)
                logGateTimeout("prefill_wait_timeout_ms=$deferred timeout_ms=$timeoutMs")
                logPrefillDeferred(deferred, lastDeferReason)
                throw PrefillTimeoutException(deferred)
            }
            // Right before the native prefill starts, re-check: activity that
            // arrived while the mutex was being acquired re-arms the idle
            // wait instead of letting this prefill run.
            val recheckReason = prefillDeferReason(System.nanoTime() / 1_000_000L, idleDelayMs)
            if (recheckReason != null) {
                lastDeferReason = recheckReason
                val deferred = elapsedMs(waitStartNanos)
                logGateTimeout("prefill_wait_timeout_ms=$deferred pending=${detectionPending.get()} advice_pending=${advicePending.get()} timeout_ms=$timeoutMs")
                logPrefillDeferred(deferred, recheckReason)
                deferredLogged = true
                prefillDetectionMutex.unlock()
                if (remainingMs(deadlineNanos) <= 0L) {
                    throw PrefillTimeoutException(deferred)
                }
                continue
            }
            break
        }
        val idleWaitedMs = elapsedMs(waitStartNanos)
        if (idleWaitedMs > 0L) {
            logPrefillDeferred(idleWaitedMs, lastDeferReason)
        }
        prefillRunning.set(true)
        prefillStartNanos.set(System.nanoTime())
        try {
            return withSharedTimed(
                deadlineNanos,
                waitStartNanos,
                { PrefillTimeoutException(elapsedMs(waitStartNanos)) }
            ) {
                val reasonAtStart = prefillDeferReason(System.nanoTime() / 1_000_000L, idleDelayMs)
                if (reasonAtStart != null) {
                    val deferred = elapsedMs(waitStartNanos)
                    logPrefillDeferred(deferred, reasonAtStart)
                    throw PrefillTimeoutException(deferred)
                }
                block()
            }
        } finally {
            prefillRunning.set(false)
            prefillStartNanos.set(0L)
            prefillDetectionMutex.unlock()
        }
    }

    /** Null when a prefill may start now, otherwise the deferral reason. */
    private fun prefillDeferReason(nowMs: Long, idleDelayMs: Long): String? {
        val detectionNowPending = detectionPending.get() > 0
        val adviceNowPending = advicePending.get() > 0
        if (!shouldDeferPrefill(detectionNowPending, adviceNowPending, nowMs, lastActivityBaselineMs(), idleDelayMs)) {
            return null
        }
        return when {
            detectionNowPending -> "detection_pending"
            adviceNowPending -> "advice_pending"
            else -> "idle_delay"
        }
    }

    private fun tryAcquireMutex(deadlineNanos: Long): Boolean {
        val remaining = remainingMs(deadlineNanos)
        if (remaining <= 0L) return false
        return try {
            prefillDetectionMutex.tryLock(remaining, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
    }

    private fun <T> withSharedTimed(
        deadlineNanos: Long,
        waitStartNanos: Long,
        timeoutError: () -> RuntimeException,
        block: () -> T
    ): T {
        val remaining = remainingMs(deadlineNanos)
        val acquired = try {
            gate.readLock().tryLock(remaining.coerceAtLeast(0L), TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }
        if (!acquired) throw timeoutError()
        try {
            return block()
        } finally {
            gate.readLock().unlock()
        }
    }

    private fun remainingMs(deadlineNanos: Long): Long =
        (deadlineNanos - System.nanoTime()) / 1_000_000L

    private fun elapsedMs(startNanos: Long): Long =
        (System.nanoTime() - startNanos) / 1_000_000L

    private fun logGateTimeout(message: String) {
        try {
            android.util.Log.w("PS3Timing", message)
        } catch (_: Exception) {
        }
    }

    private fun logPrefillDeferred(deferredMs: Long, reason: String) {
        try {
            android.util.Log.i("PS3Timing", "prefill_deferred_ms=$deferredMs reason=$reason")
        } catch (_: Exception) {
        }
    }

    /**
     * Runs [block] with exclusive access to ExecuTorch native work.
     *
     * Covers every model load (URL Module, SMS Module, LlmModule creation plus pool restore as
     * one section) and the Llama close, because each of those touches or resets the shared thread
     * pool. While held, no shared block runs, so a load never overlaps a forward pass, a prefill
     * or a generation. The Llama load is about 0.5 s, so a UI analysis forward waits that long
     * instead of aborting. The Llama load plus pool restore is one exclusive section: LlmModule
     * creation resets the shared ExecuTorch thread pool, freeing the pthreadpool that every
     * earlier XNNPACK runtime still points at, so a forward allowed to run between the load and
     * the restore would block forever in native code (the Galaxy F14 deadlock 2026-11-07). After
     * every reset the URL and SMS modules are rebound to the live pool inside this same section.
     * No forward can run between them. LlamaAdvisor.close uses this after taking its own module
     * lock, so it additionally waits for any in-flight generation or prefill.
     */
    fun <T> withExclusive(block: () -> T): T {
        gate.writeLock().lock()
        try {
            return block()
        } finally {
            gate.writeLock().unlock()
        }
    }

    /**
     * Runs [block] with shared access to ExecuTorch native work.
     *
     * Covers every URL and SMS forward pass (including the SmsClassifier dynamic probe) and the
     * Llama native calls (resetContext, prefillPrompt, generate). The watchdog stop is not
     * gated: it runs on the generation thread that already holds the shared side, and
     * re-acquiring the fair gate would queue behind a queued exclusive writer. A shared
     * block cannot start while an exclusive load or close is running, and an exclusive block
     * cannot start while a shared block is running, so Llama prefill and generate never start
     * during a model load.
     * Shared blocks may overlap each other, because forwards and generations only dispatch work
     * to the pool without resetting it; same-Module concurrency is still prevented by the
     * existing per-class guards and LlamaAdvisor's module lock. Holding the shared side for a
     * whole generation (seconds) does not block forwards, which are also shared; it only makes
     * a later load or close wait for the generation to finish, which the close requires anyway.
     * Callback stop() calls are not gated directly; they run on the generation thread while it
     * holds the shared side, so a load or close still waits for them. Pure JVM work
     * (tokenisation, encoding, indicator heuristics, isLoaded checks) stays outside the gate to
     * keep the hold short. Acquire the gate after any per-instance or module lock, never before.
     */
    fun <T> withShared(block: () -> T): T {
        gate.readLock().lock()
        try {
            return block()
        } finally {
            gate.readLock().unlock()
        }
    }

    /**
     * Runs [block] with shared access to ExecuTorch native work, but gives up after
     * [timeoutMs] instead of waiting forever for an exclusive load or close to release
     * the gate. Used where a caller must fail fast to a template fallback (generation).
     */
    fun <T> withShared(timeoutMs: Long, block: () -> T): T {
        val acquired = try {
            gate.readLock().tryLock(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            logGateTimeout("gate_shared_wait_timeout_ms=$timeoutMs timeout_ms=$timeoutMs")
            throw IllegalStateException("gate shared wait interrupted after $timeoutMs ms")
        }
        if (!acquired) {
            logGateTimeout("gate_shared_wait_timeout_ms=$timeoutMs timeout_ms=$timeoutMs")
            throw IllegalStateException("gate shared wait timed out after $timeoutMs ms")
        }
        try {
            return block()
        } finally {
            gate.readLock().unlock()
        }
    }
}
