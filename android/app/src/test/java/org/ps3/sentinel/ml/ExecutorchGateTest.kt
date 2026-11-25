package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.Before
import org.junit.After
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

class ExecutorchGateTest {

    @Before
    fun setUp() {
        ExecutorchGate.resetForTest()
    }

    @After
    fun tearDown() {
        ExecutorchGate.resetForTest()
    }

    @Test
    fun testLoadAndForwardNeverOverlap() {
        val loadStarted = CountDownLatch(1)
        val loadEndNs = AtomicLong(0L)
        val forwardStartNs = AtomicLong(0L)
        val overlapped = AtomicBoolean(false)
        var loadThread: Thread? = null
        var forwardThread: Thread? = null
        try {
            loadThread = Thread {
                ExecutorchGate.withExclusive {
                    loadStarted.countDown()
                    Thread.sleep(150L)
                    loadEndNs.set(System.nanoTime())
                }
            }
            loadThread.start()
            assertTrue("load must start", loadStarted.await(5, TimeUnit.SECONDS))
            forwardThread = Thread {
                ExecutorchGate.withShared {
                    forwardStartNs.set(System.nanoTime())
                    if (loadEndNs.get() == 0L) overlapped.set(true)
                    Thread.sleep(50L)
                }
            }
            forwardThread.start()
            loadThread.join(5_000L)
            forwardThread.join(5_000L)
        } finally {
            loadThread?.join(1_000L)
            forwardThread?.join(1_000L)
        }
        assertTrue("load thread must finish", loadThread != null && !loadThread.isAlive)
        assertTrue("forward thread must finish", forwardThread != null && !forwardThread.isAlive)
        assertTrue("forward must wait for the load to finish", !overlapped.get())
        assertTrue(
            "forward start must be after load end",
            forwardStartNs.get() >= loadEndNs.get()
        )
    }

    @Test
    fun testForwardAndLoadNeverOverlap() {
        val forwardStarted = CountDownLatch(1)
        val forwardEndNs = AtomicLong(0L)
        val loadStartNs = AtomicLong(0L)
        val overlapped = AtomicBoolean(false)
        var forwardThread: Thread? = null
        var loadThread: Thread? = null
        try {
            forwardThread = Thread {
                ExecutorchGate.withShared {
                    forwardStarted.countDown()
                    Thread.sleep(150L)
                    forwardEndNs.set(System.nanoTime())
                }
            }
            forwardThread.start()
            assertTrue("forward must start", forwardStarted.await(5, TimeUnit.SECONDS))
            loadThread = Thread {
                ExecutorchGate.withExclusive {
                    loadStartNs.set(System.nanoTime())
                    if (forwardEndNs.get() == 0L) overlapped.set(true)
                    Thread.sleep(50L)
                }
            }
            loadThread.start()
            forwardThread.join(5_000L)
            loadThread.join(5_000L)
        } finally {
            forwardThread?.join(1_000L)
            loadThread?.join(1_000L)
        }
        assertTrue("forward thread must finish", forwardThread != null && !forwardThread.isAlive)
        assertTrue("load thread must finish", loadThread != null && !loadThread.isAlive)
        assertTrue("load must wait for the forward to finish", !overlapped.get())
        assertTrue(
            "load start must be after forward end",
            loadStartNs.get() >= forwardEndNs.get()
        )
    }

    @Test
    fun testTwoLoadsNeverOverlap() {
        val firstStarted = CountDownLatch(1)
        val firstEndNs = AtomicLong(0L)
        val secondStartNs = AtomicLong(0L)
        val overlapped = AtomicBoolean(false)
        var firstThread: Thread? = null
        var secondThread: Thread? = null
        try {
            firstThread = Thread {
                ExecutorchGate.withExclusive {
                    firstStarted.countDown()
                    Thread.sleep(100L)
                    firstEndNs.set(System.nanoTime())
                }
            }
            firstThread.start()
            assertTrue("first load must start", firstStarted.await(5, TimeUnit.SECONDS))
            secondThread = Thread {
                ExecutorchGate.withExclusive {
                    secondStartNs.set(System.nanoTime())
                    if (firstEndNs.get() == 0L) overlapped.set(true)
                    Thread.sleep(30L)
                }
            }
            secondThread.start()
            firstThread.join(5_000L)
            secondThread.join(5_000L)
        } finally {
            firstThread?.join(1_000L)
            secondThread?.join(1_000L)
        }
        assertTrue("first load must finish", firstThread != null && !firstThread.isAlive)
        assertTrue("second load must finish", secondThread != null && !secondThread.isAlive)
        assertTrue("second load must wait for the first load", !overlapped.get())
        assertTrue(
            "second load start must be after first load end",
            secondStartNs.get() >= firstEndNs.get()
        )
    }

    @Test
    fun testSharedQueuedDuringLlamaLoadCannotRunBeforePoolRestore() {
        val loadStarted = CountDownLatch(1)
        val forwardReady = CountDownLatch(1)
        val releaseLoad = CountDownLatch(1)
        val restoreDoneNs = AtomicLong(0L)
        val forwardStartNs = AtomicLong(0L)
        val forwardRanBeforeRestore = AtomicBoolean(false)
        var loadThread: Thread? = null
        var forwardThread: Thread? = null
        try {
            loadThread = Thread {
                withLlamaLoadAndPoolRestore(
                    load = {
                        loadStarted.countDown()
                        releaseLoad.await(5, TimeUnit.SECONDS)
                        "loaded"
                    },
                    restore = { restoreDoneNs.set(System.nanoTime()) }
                )
            }
            loadThread.start()
            assertTrue("load must start", loadStarted.await(5, TimeUnit.SECONDS))
            forwardThread = Thread {
                forwardReady.countDown()
                ExecutorchGate.withShared {
                    forwardStartNs.set(System.nanoTime())
                    if (restoreDoneNs.get() == 0L) forwardRanBeforeRestore.set(true)
                }
            }
            forwardThread.start()
            assertTrue("forward must be ready", forwardReady.await(5, TimeUnit.SECONDS))
            Thread.sleep(50L)
            releaseLoad.countDown()
            loadThread.join(5_000L)
            forwardThread.join(5_000L)
        } finally {
            releaseLoad.countDown()
            loadThread?.join(1_000L)
            forwardThread?.join(1_000L)
        }
        assertTrue("load thread must finish", loadThread != null && !loadThread.isAlive)
        assertTrue("forward thread must finish", forwardThread != null && !forwardThread.isAlive)
        assertTrue("forward must not run before pool restore", !forwardRanBeforeRestore.get())
        assertTrue(
            "forward start must be after restore done",
            forwardStartNs.get() >= restoreDoneNs.get()
        )
    }

    @Test
    fun testTwoForwardsCanOverlap() {
        val firstEntered = CountDownLatch(1)
        val secondEntered = CountDownLatch(1)
        val bothEntered = AtomicBoolean(false)
        var firstThread: Thread? = null
        var secondThread: Thread? = null
        try {
            firstThread = Thread {
                ExecutorchGate.withShared {
                    firstEntered.countDown()
                    if (secondEntered.await(5, TimeUnit.SECONDS)) bothEntered.set(true)
                }
            }
            secondThread = Thread {
                ExecutorchGate.withShared {
                    secondEntered.countDown()
                    firstEntered.await(5, TimeUnit.SECONDS)
                }
            }
            firstThread.start()
            secondThread.start()
            firstThread.join(6_000L)
            secondThread.join(6_000L)
        } finally {
            firstThread?.join(1_000L)
            secondThread?.join(1_000L)
        }
        assertTrue("first forward must finish", firstThread != null && !firstThread.isAlive)
        assertTrue("second forward must finish", secondThread != null && !secondThread.isAlive)
        assertTrue("forwards must overlap on the shared side", bothEntered.get())
    }

    @Test
    fun testDetectionAndPrefillNeverOverlap() {
        val prefillStarted = CountDownLatch(1)
        val prefillEndNs = AtomicLong(0L)
        val detectionStartNs = AtomicLong(0L)
        val overlapped = AtomicBoolean(false)
        var prefillThread: Thread? = null
        var detectionThread: Thread? = null
        try {
            prefillThread = Thread {
                ExecutorchGate.withPrefill {
                    prefillStarted.countDown()
                    Thread.sleep(150L)
                    prefillEndNs.set(System.nanoTime())
                }
            }
            prefillThread.start()
            assertTrue("prefill must start", prefillStarted.await(5, TimeUnit.SECONDS))
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionStartNs.set(System.nanoTime())
                    if (prefillEndNs.get() == 0L) overlapped.set(true)
                    Thread.sleep(30L)
                }
            }
            detectionThread.start()
            prefillThread.join(5_000L)
            detectionThread.join(5_000L)
        } finally {
            prefillThread?.join(1_000L)
            detectionThread?.join(1_000L)
        }
        assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
        assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
        assertTrue("detection must wait for the prefill to finish", !overlapped.get())
        assertTrue(
            "detection start must be after prefill end",
            detectionStartNs.get() >= prefillEndNs.get()
        )
    }

    @Test
    fun testPrefillWaitsForPendingDetectionThenRuns() {
        val detectionStarted = CountDownLatch(1)
        val detectionEndNs = AtomicLong(0L)
        val prefillStartNs = AtomicLong(0L)
        val overlapped = AtomicBoolean(false)
        var detectionThread: Thread? = null
        var prefillThread: Thread? = null
        try {
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionStarted.countDown()
                    Thread.sleep(150L)
                    detectionEndNs.set(System.nanoTime())
                }
            }
            detectionThread.start()
            assertTrue("detection must start", detectionStarted.await(5, TimeUnit.SECONDS))
            prefillThread = Thread {
                ExecutorchGate.withPrefill {
                    prefillStartNs.set(System.nanoTime())
                    if (detectionEndNs.get() == 0L) overlapped.set(true)
                    Thread.sleep(30L)
                }
            }
            prefillThread.start()
            detectionThread.join(5_000L)
            prefillThread.join(5_000L)
        } finally {
            detectionThread?.join(1_000L)
            prefillThread?.join(1_000L)
        }
        assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
        assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
        assertTrue("prefill must wait for the pending detection to finish", !overlapped.get())
        assertTrue(
            "prefill start must be after detection end",
            prefillStartNs.get() >= detectionEndNs.get()
        )
    }

    @Test
    fun testDetectionBoundedWaitTimesOutWhilePrefillHolds() {
        // DT-18: detection arriving while a prefill is already running waits
        // for the prefill up to its bounded duration plus margin; it must not
        // fall back to rules merely because the prefill was running. The first
        // detection after launch therefore completes with the model verdict.
        val prefillStarted = CountDownLatch(1)
        val detectionBlockRan = AtomicBoolean(false)
        val detectionTimedOut = AtomicBoolean(false)
        var prefillThread: Thread? = null
        var detectionThread: Thread? = null
        try {
            prefillThread = Thread {
                ExecutorchGate.withPrefill {
                    prefillStarted.countDown()
                    Thread.sleep(600L)
                }
            }
            prefillThread.start()
            assertTrue("prefill must start", prefillStarted.await(5, TimeUnit.SECONDS))
            assertTrue("prefill is running", ExecutorchGate.isPrefillRunning())
            detectionThread = Thread {
                try {
                    ExecutorchGate.withDetection(250L) {
                        detectionBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.DetectionTimeoutException) {
                    detectionTimedOut.set(true)
                } catch (e: IllegalStateException) {
                    detectionTimedOut.set(true)
                }
            }
            detectionThread.start()
            prefillThread.join(5_000L)
            detectionThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
            assertFalse("detection must not fall back while the prefill runs within the bound", detectionTimedOut.get())
            assertTrue("detection block must run after the prefill (model verdict)", detectionBlockRan.get())
            assertEquals(0, ExecutorchGate.detectionPendingCount())
            assertFalse("no prefill may be running after both finish", ExecutorchGate.isPrefillRunning())
        } finally {
            prefillThread?.join(1_000L)
            detectionThread?.join(1_000L)
        }
    }

    @Test
    fun testPrefillBoundedWaitTimesOutWhileDetectionPending() {
        val detectionStarted = CountDownLatch(1)
        val releaseDetection = CountDownLatch(1)
        val prefillBlockRan = AtomicBoolean(false)
        val prefillTimedOut = AtomicBoolean(false)
        var detectionThread: Thread? = null
        var prefillThread: Thread? = null
        try {
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionStarted.countDown()
                    releaseDetection.await(5, TimeUnit.SECONDS)
                    Thread.sleep(50L)
                }
            }
            detectionThread.start()
            assertTrue("detection must start", detectionStarted.await(5, TimeUnit.SECONDS))
            val startNs = System.nanoTime()
            prefillThread = Thread {
                try {
                    ExecutorchGate.withPrefill(250L) {
                        prefillBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.PrefillTimeoutException) {
                    prefillTimedOut.set(true)
                } catch (e: IllegalStateException) {
                    prefillTimedOut.set(true)
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must time out instead of waiting forever", prefillTimedOut.get())
            assertFalse("prefill block must not run on timeout", prefillBlockRan.get())
            assertTrue(
                "prefill timeout must be bounded",
                elapsedMs < 5_000L
            )
            releaseDetection.countDown()
            detectionThread.join(5_000L)
        } finally {
            releaseDetection.countDown()
            detectionThread?.join(1_000L)
            prefillThread?.join(1_000L)
        }
        assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
    }

    @Test
    fun testWatchdogStopNotBlockedByQueuedExclusiveWriter() {
        val generationStarted = CountDownLatch(1)
        val releaseGeneration = CountDownLatch(1)
        val writerReady = CountDownLatch(1)
        val stopped = AtomicBoolean(false)
        var generationThread: Thread? = null
        var writerThread: Thread? = null
        try {
            generationThread = Thread {
                ExecutorchGate.withShared {
                    generationStarted.countDown()
                    releaseGeneration.await(5, TimeUnit.SECONDS)
                }
            }
            generationThread.start()
            assertTrue("generation must start", generationStarted.await(5, TimeUnit.SECONDS))
            writerThread = Thread {
                writerReady.countDown()
                ExecutorchGate.withExclusive { }
            }
            writerThread.start()
            assertTrue("writer must be ready", writerReady.await(5, TimeUnit.SECONDS))
            Thread.sleep(150L)
            val startNs = System.nanoTime()
            val ran = runWatchdogStop(true) { stopped.set(true) }
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("watchdog stop must reach the native module", ran && stopped.get())
            assertTrue(
                "watchdog stop must not wait on the fair gate behind the queued writer, took ${elapsedMs} ms",
                elapsedMs < 2_000L
            )
            val skipped = AtomicBoolean(false)
            assertFalse("stale module must not be stopped", runWatchdogStop(false) { skipped.set(true) })
            assertFalse("stale module stop must not run", skipped.get())
            releaseGeneration.countDown()
            generationThread.join(5_000L)
            writerThread.join(5_000L)
        } finally {
            releaseGeneration.countDown()
            generationThread?.join(1_000L)
            writerThread?.join(1_000L)
        }
        assertTrue("generation thread must finish", generationThread != null && !generationThread.isAlive)
        assertTrue("writer thread must finish", writerThread != null && !writerThread.isAlive)
    }

    @Test
    fun testInterruptedPrefillAbortsWithoutRunning() {
        val detectionStarted = CountDownLatch(1)
        val releaseDetection = CountDownLatch(1)
        val prefillBlockRan = AtomicBoolean(false)
        val prefillAborted = AtomicBoolean(false)
        var detectionThread: Thread? = null
        var prefillThread: Thread? = null
        try {
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionStarted.countDown()
                    releaseDetection.await(5, TimeUnit.SECONDS)
                    Thread.sleep(50L)
                }
            }
            detectionThread.start()
            assertTrue("detection must start", detectionStarted.await(5, TimeUnit.SECONDS))
            prefillThread = Thread {
                try {
                    ExecutorchGate.withPrefill(5_000L) {
                        prefillBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.PrefillTimeoutException) {
                    prefillAborted.set(true)
                } catch (e: IllegalStateException) {
                    prefillAborted.set(true)
                }
            }
            prefillThread.start()
            Thread.sleep(100L)
            prefillThread.interrupt()
            prefillThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("interrupted prefill must abort", prefillAborted.get())
            assertFalse("interrupted prefill must not run its block", prefillBlockRan.get())
            releaseDetection.countDown()
            detectionThread.join(5_000L)
        } finally {
            releaseDetection.countDown()
            detectionThread?.join(1_000L)
            prefillThread?.join(1_000L)
        }
        assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
    }

    @Test
    fun testLightIdleDelayConstantAndDetectionBound() {
        assertEquals(5_000L, ExecutorchGate.LIGHT_PREFILL_IDLE_DELAY_MS)
        assertEquals(
            ExecutorchGate.PREFILL_RUN_TIMEOUT_MS + ExecutorchGate.DETECTION_MARGIN_MS,
            ExecutorchGate.DETECTION_WAIT_TIMEOUT_WHILE_PREFILL_MS
        )
        assertTrue(ExecutorchGate.DETECTION_WAIT_TIMEOUT_WHILE_PREFILL_MS > ExecutorchGate.DETECTION_WAIT_TIMEOUT_MS)
    }

    @Test
    fun testIdleDelayHelper() {
        assertTrue(ExecutorchGate.isPrefillIdle(100L, 0L, 5_000L))
        assertFalse(ExecutorchGate.isPrefillIdle(100L, 50L, 5_000L))
        assertTrue(ExecutorchGate.isPrefillIdle(6_000L, 50L, 5_000L))
        assertTrue(ExecutorchGate.isPrefillIdle(100L, 50L, 0L))
        assertTrue(ExecutorchGate.shouldDeferPrefill(true, 100L, 0L, 0L))
        assertTrue(ExecutorchGate.shouldDeferPrefill(false, 100L, 50L, 5_000L))
        assertFalse(ExecutorchGate.shouldDeferPrefill(false, 6_000L, 50L, 5_000L))
    }

    @Test
    fun testPrefillNeverStartsWhileDetectionPendingDelayed() {
        val detectionStarted = CountDownLatch(1)
        val releaseDetection = CountDownLatch(1)
        val prefillBlockRan = AtomicBoolean(false)
        val prefillTimedOut = AtomicBoolean(false)
        var detectionThread: Thread? = null
        var prefillThread: Thread? = null
        try {
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionStarted.countDown()
                    releaseDetection.await(5, TimeUnit.SECONDS)
                }
            }
            detectionThread.start()
            assertTrue("detection must start", detectionStarted.await(5, TimeUnit.SECONDS))
            prefillThread = Thread {
                try {
                    ExecutorchGate.withPrefillDelayed(0L, 300L) {
                        prefillBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.PrefillTimeoutException) {
                    prefillTimedOut.set(true)
                } catch (e: IllegalStateException) {
                    prefillTimedOut.set(true)
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must defer while detection is pending", prefillTimedOut.get())
            assertFalse("prefill must never start while detection is pending", prefillBlockRan.get())
        } finally {
            releaseDetection.countDown()
            detectionThread?.join(1_000L)
            prefillThread?.join(1_000L)
    
        }
        assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
    }

    @Test
    fun testDetectionDuringIdleDelayPostponesPrefill() {
    
        // Simulate a detection that just started: idle delay not yet met.
        ExecutorchGate.markDetectionExpected()
        val prefillBlockRan = AtomicBoolean(false)
        val prefillTimedOut = AtomicBoolean(false)
        var prefillThread: Thread? = null
        try {
            val startNs = System.nanoTime()
            prefillThread = Thread {
                try {
                    ExecutorchGate.withPrefillDelayed(500L, 300L) {
                        prefillBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.PrefillTimeoutException) {
                    prefillTimedOut.set(true)
                } catch (e: IllegalStateException) {
                    prefillTimedOut.set(true)
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("idle-delay prefill must defer when detection is recent", prefillTimedOut.get())
            assertFalse("idle-delay prefill must not run before the idle period", prefillBlockRan.get())
            assertTrue("deferral is bounded", elapsedMs < 5_000L)
        } finally {
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testDetectionDuringIdleDelayRunsAfterIdle() {
        ExecutorchGate.markDetectionExpected()
        val prefillBlockRan = AtomicBoolean(false)
        var prefillThread: Thread? = null
        try {
            val startNs = System.nanoTime()
            prefillThread = Thread {
                ExecutorchGate.withPrefillDelayed(400L, 5_000L) {
                    prefillBlockRan.set(true)
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must run once idle (postponed, not cancelled)", prefillBlockRan.get())
            assertTrue("prefill must wait the idle period, took ${elapsedMs} ms", elapsedMs >= 300L)
        } finally {
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testIdleDelayMeasuredFromLastActivityEnd() {
        ExecutorchGate.markActivityEnded()
        assertTrue(ExecutorchGate.lastActivityEndMs() > 0L)
        val prefillStartNs = AtomicLong(0L)
        var prefillThread: Thread? = null
        try {
            val startNs = System.nanoTime()
            prefillThread = Thread {
                ExecutorchGate.withPrefillDelayed(400L, 5_000L) {
                    prefillStartNs.set(System.nanoTime())
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must run after the idle delay", prefillStartNs.get() != 0L)
            assertTrue(
                "idle delay must count from the activity end (just now), not an old start, took ${elapsedMs} ms",
                elapsedMs >= 300L
            )
        } finally {
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testDetectionArrivingDuringIdleDelayPostponesPrefill() {
        ExecutorchGate.markActivityEnded()
        val prefillStartNs = AtomicLong(0L)
        val detectionEndNs = AtomicLong(0L)
        var prefillThread: Thread? = null
        try {
            val startNs = System.nanoTime()
            prefillThread = Thread {
                ExecutorchGate.withPrefillDelayed(400L, 5_000L) {
                    prefillStartNs.set(System.nanoTime())
                }
            }
            prefillThread.start()
            Thread.sleep(100L)
            ExecutorchGate.withDetection {
                Thread.sleep(100L)
                detectionEndNs.set(System.nanoTime())
            }
            prefillThread.join(5_000L)
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must run once the new idle period passes", prefillStartNs.get() != 0L)
            assertTrue(
                "prefill must be postponed past the original idle deadline, took ${elapsedMs} ms",
                elapsedMs >= 500L
            )
            assertTrue(
                "prefill must start at least 300 ms after the arriving detection ended",
                prefillStartNs.get() >= detectionEndNs.get() + 300_000_000L
            )
        } finally {
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testPrefillNeverStartsWhileAdvicePending() {
    
        ExecutorchGate.beginAdvice()
        val prefillBlockRan = AtomicBoolean(false)
        val prefillTimedOut = AtomicBoolean(false)
        var prefillThread: Thread? = null
        try {
            prefillThread = Thread {
                try {
                    ExecutorchGate.withPrefillDelayed(0L, 300L) {
                        prefillBlockRan.set(true)
                    }
                } catch (e: ExecutorchGate.PrefillTimeoutException) {
                    prefillTimedOut.set(true)
                } catch (e: IllegalStateException) {
                    prefillTimedOut.set(true)
                }
            }
            prefillThread.start()
            prefillThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must defer while advice is pending", prefillTimedOut.get())
            assertFalse("prefill must never start while advice is pending", prefillBlockRan.get())
        } finally {
            ExecutorchGate.endAdvice()
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testPrefillWaitsAfterAdviceEndsUnlessIdlePassed() {
    
        ExecutorchGate.beginAdvice()
        val prefillStartNs = AtomicLong(0L)
        val adviceEndNs = AtomicLong(0L)
        var prefillThread: Thread? = null
        try {
            prefillThread = Thread {
                ExecutorchGate.withPrefillDelayed(400L, 5_000L) {
                    prefillStartNs.set(System.nanoTime())
                }
            }
            prefillThread.start()
            Thread.sleep(100L)
            ExecutorchGate.endAdvice()
            adviceEndNs.set(System.nanoTime())
            prefillThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("prefill must run after the advice idle period", prefillStartNs.get() != 0L)
            assertTrue(
                "prefill must wait the idle delay from the advice end",
                prefillStartNs.get() >= adviceEndNs.get() + 300_000_000L
            )
        } finally {
            if (ExecutorchGate.isAdvicePending()) ExecutorchGate.endAdvice()
            prefillThread?.join(1_000L)
    
        }
    }

    @Test
    fun testFullTierIdleDelayZeroIgnoresRecentActivityEnd() {
    
        ExecutorchGate.markActivityEnded()
        assertEquals(0L, prefillIdleDelayMs(false))
        assertFalse(
            ExecutorchGate.shouldDeferPrefill(
                false, false, ExecutorchGate.lastActivityBaselineMs(),
                ExecutorchGate.lastActivityBaselineMs(), 0L
            )
        )
        val startNs = System.nanoTime()
        val prefillBlockRan = AtomicBoolean(false)
        try {
            ExecutorchGate.withPrefillDelayed(prefillIdleDelayMs(false), 5_000L) {
                prefillBlockRan.set(true)
            }
            val elapsedMs = (System.nanoTime() - startNs) / 1_000_000L
            assertTrue("FULL tier prefill must run despite a recent activity end", prefillBlockRan.get())
            assertTrue("FULL tier prefill must not wait, took ${elapsedMs} ms", elapsedMs < 300L)
        } finally {
    
        }
    }

    @Test
    fun testFirstDetectionAfterLaunchWithSimulatedPrefill() {
    
        val prefillStarted = CountDownLatch(1)
        val detectionBlockRan = AtomicBoolean(false)
        var prefillThread: Thread? = null
        var detectionThread: Thread? = null
        try {
            prefillThread = Thread {
                ExecutorchGate.withPrefill {
                    prefillStarted.countDown()
                    Thread.sleep(800L)
                }
            }
            prefillThread.start()
            assertTrue("prefill must start", prefillStarted.await(5, TimeUnit.SECONDS))
            detectionThread = Thread {
                ExecutorchGate.withDetection {
                    detectionBlockRan.set(true)
                }
            }
            detectionThread.start()
            prefillThread.join(5_000L)
            detectionThread.join(5_000L)
            assertTrue("prefill thread must finish", prefillThread != null && !prefillThread.isAlive)
            assertTrue("detection thread must finish", detectionThread != null && !detectionThread.isAlive)
            assertTrue("first detection after launch completes with the model verdict", detectionBlockRan.get())
        } finally {
            prefillThread?.join(1_000L)
            detectionThread?.join(1_000L)
        }
    }
}
