package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.coroutines.runBlocking
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger

class IntegrityCacheTest {
    private fun tempDir(prefix: String): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "$prefix-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    private fun record(hash: String = "abc"): IntegrityRecord =
        IntegrityRecord(name = "llama.pte", sizeBytes = 11L, lastModifiedMs = 1234L, sha256Hex = hash)

    @Test
    fun testCacheHitWhenSizeTimestampAndHashMatch() {
        assertTrue(IntegrityCache.shouldTrust(record(), sizeBytes = 11L, lastModifiedMs = 1234L, manifestHash = "ABC"))
    }

    @Test
    fun testCacheMissWhenSizeChanges() {
        assertFalse(IntegrityCache.shouldTrust(record(), sizeBytes = 12L, lastModifiedMs = 1234L, manifestHash = "abc"))
    }

    @Test
    fun testCacheMissWhenTimestampChanges() {
        assertFalse(IntegrityCache.shouldTrust(record(), sizeBytes = 11L, lastModifiedMs = 1235L, manifestHash = "abc"))
    }

    @Test
    fun testCacheMissWhenHashOrRecordMissing() {
        assertFalse(IntegrityCache.shouldTrust(record(), sizeBytes = 11L, lastModifiedMs = 1234L, manifestHash = "def"))
        assertFalse(IntegrityCache.shouldTrust(null, sizeBytes = 11L, lastModifiedMs = 1234L, manifestHash = "abc"))
    }

    @Test
    fun testOldCacheFileWithoutFieldLoadsWithZeroAndIsRehashed() {
        val cacheDir = tempDir("integrity-old-cache")
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        cacheFile.parentFile?.mkdirs()
        cacheFile.writeText(
            "[{\"name\":\"llama.pte\",\"size\":11,\"last_modified_ms\":1234,\"sha256\":\"abc\"}]",
            Charsets.UTF_8
        )
        val loaded = IntegrityCache.loadEntries(cacheFile)
        val record = loaded["llama.pte"]
        assertEquals("old cache file without the field loads with 0", 0L, record?.lastVerifiedMs)
        assertTrue(
            "old cache file without the field is re-hashed",
            IntegrityCache.shouldRehash(record)
        )
    }

    @Test
    fun testRecordVerifiedOneDayAgoIsRehashedOnColdStart() {
        val nowMs = System.currentTimeMillis()
        val oneDayMs = 24L * 60L * 60L * 1000L
        val record = IntegrityRecord(
            name = "llama.pte",
            sizeBytes = 11L,
            lastModifiedMs = 1234L,
            sha256Hex = "abc",
            lastVerifiedMs = nowMs - oneDayMs
        )
        assertTrue(
            "record verified 1 day ago is re-hashed on cold start",
            IntegrityCache.shouldRehash(record)
        )
        assertEquals(0L, IntegrityCache.REHASH_INTERVAL_MS)
    }

    @Test
    fun testRecordVerifiedEightDaysAgoIsRehashed() {
        val nowMs = System.currentTimeMillis()
        val eightDaysMs = 8L * 24L * 60L * 60L * 1000L
        val record = IntegrityRecord(
            name = "llama.pte",
            sizeBytes = 11L,
            lastModifiedMs = 1234L,
            sha256Hex = "abc",
            lastVerifiedMs = nowMs - eightDaysMs
        )
        assertTrue(
            "record verified 8 days ago is queued",
            IntegrityCache.shouldRehash(record)
        )
        assertEquals(0L, IntegrityCache.REHASH_INTERVAL_MS)
    }

    @Test
    fun testSaveThenLoadLeavesNoTempFile() {
        val cacheDir = tempDir("integrity-atomic-save")
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val entries = mapOf("llama.pte" to record())
        assertTrue(IntegrityCache.saveEntries(cacheFile, entries))
        val loaded = IntegrityCache.loadEntries(cacheFile)
        assertEquals("abc", loaded["llama.pte"]?.sha256Hex)
        val tempFile = File(cacheDir, IntegrityCache.CACHE_FILE_NAME + ".tmp")
        assertFalse("no temp file left after save", tempFile.exists())
        assertTrue("cache file written", cacheFile.isFile)
    }

    @Test
    fun testColdStartTrustsUnchangedCopyAndBackgroundRehashCatchesTamper() {
        val sourceDir = tempDir("integrity-source")
        val modelsDir = tempDir("integrity-models")
        val cacheDir = tempDir("integrity-cache")
        val sourceFile = File(sourceDir, "llama.pte")
        sourceFile.writeText("llama bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf("llama.pte" to hash)

        val first = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, "llama.pte")
        assertTrue(internal.isFile)
        val originalModified = internal.lastModified()

        // Unchanged copy: the next process loads it without a synchronous hash.
        val unchangedGate = CountDownLatch(1)
        val second = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes) { file ->
            unchangedGate.await()
            ModelStore.sha256Hex(file)
        }
        assertTrue("unchanged copy is trusted on cold start", second.checkFile(internal).loadable)
        unchangedGate.countDown()
        assertTrue(
            "background re-hash confirms the unchanged copy",
            runBlocking { second.awaitVerified("llama.pte", 5000L) }
        )

        // Changed timestamp: not trusted, hashed before load, and the bytes still match.
        internal.setLastModified(originalModified + 5000L)
        val third = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        assertTrue("changed timestamp is re-hashed and passes", third.checkFile(internal).verified)

        // Same size and mtime tamper: loads at start, then the background re-hash removes it.
        val trustedModified = internal.lastModified()
        internal.writeText("llama bytez")
        assertEquals(11L, internal.length())
        internal.setLastModified(trustedModified)
        val gate = CountDownLatch(1)
        val fourth = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes) { file ->
            gate.await()
            ModelStore.sha256Hex(file)
        }
        assertTrue("tampered copy with same size and mtime passes the start check", fourth.checkFile(internal).loadable)
        gate.countDown()
        assertFalse(
            "background re-hash refutes the tampered copy",
            runBlocking { fourth.awaitVerified("llama.pte", 5000L) }
        )
        assertFalse("background re-hash deletes the tampered copy", internal.exists())
        assertFalse("and marks it not loadable", fourth.checkFile(internal).loadable)
    }

    @Test
    fun testTrustedLlamaIsPendingUntilBackgroundRehashPasses() {
        val sourceDir = tempDir("integrity-trust-source")
        val modelsDir = tempDir("integrity-trust-models")
        val cacheDir = tempDir("integrity-trust-cache")
        val name = "llama.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("llama trusted bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)

        val gate = CountDownLatch(1)
        val hashCalls = AtomicInteger(0)
        val second = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes) { file ->
            gate.await()
            hashCalls.incrementAndGet()
            ModelStore.sha256Hex(file)
        }
        val check = second.checkFile(internal)
        assertTrue("a trusted Llama copy loads without a synchronous hash", check.loadable)
        assertEquals("no synchronous hash ran before load", 0L, hashCalls.get().toLong())
        assertTrue("the trusted Llama copy awaits its re-hash", second.isPendingRehash(name))

        gate.countDown()
        assertTrue(
            "awaitVerified passes once the background re-hash matches",
            runBlocking { second.awaitVerified(name, 5000L) }
        )
        assertFalse(second.isPendingRehash(name))
        assertFalse(second.rehashFailed(name))
        assertEquals("the background re-hash ran exactly once", 1L, hashCalls.get().toLong())
    }

    @Test
    fun testVerificationCacheInvalidatedOnSizeOrMtimeChange() {
        val sourceDir = tempDir("integrity-invalidate-source")
        val modelsDir = tempDir("integrity-invalidate-models")
        val cacheDir = tempDir("integrity-invalidate-cache")
        val sourceFile = File(sourceDir, "llama.pte")
        sourceFile.writeText("llama bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf("llama.pte" to hash)
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        val firstCheck = store.checkFile(sourceFile)
        assertTrue(firstCheck.verified)
        assertSame(firstCheck, store.checkFile(sourceFile))
        val internal = File(modelsDir, "llama.pte")
        val originalModified = internal.lastModified()
        internal.writeText("llama bytez")
        internal.setLastModified(originalModified + 1000L)
        sourceFile.writeText("llama bytez")
        sourceFile.setLastModified(originalModified + 1000L)
        val secondCheck = store.checkFile(internal)
        assertNotSame(firstCheck, secondCheck)
        assertFalse("mtime change must re-hash and refuse", secondCheck.loadable)
    }
}
