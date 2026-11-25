package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import kotlinx.coroutines.runBlocking
import org.ps3.sentinel.core.SmsTokenizer
import java.io.File
import java.io.FileWriter
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger

class ModelStoreTest {

    /** Creates a fresh temporary directory for a model-store test. */
    private fun tempDir(): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "modelstore-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    /**
     * A cold start trusts a copy whose size and mtime match its persisted record; the background
     * re-hash is what refuses a tampered one. Runs both and returns the check after the re-hash.
     */
    private fun checkAfterBackgroundRehash(store: ModelStore, file: File): ModelCheck {
        store.checkFile(file)
        store.startBackgroundRehash()
        val deadline = System.currentTimeMillis() + 5000L
        while (file.exists() && System.currentTimeMillis() < deadline) {
            Thread.sleep(20L)
        }
        return store.checkFile(file)
    }

    @Test
    fun testValidModelFileNameRejectsTraversal() {
        assertTrue("plain name is valid", ModelStore.isValidModelFileName("sms_int8.pte"))
        assertTrue("plain name is valid", ModelStore.isValidModelFileName("vocab.json"))
        assertFalse("forward slash refused", ModelStore.isValidModelFileName("../sms_int8.pte"))
        assertFalse("backslash refused", ModelStore.isValidModelFileName("..\\sms_int8.pte"))
        assertFalse("dot-dot refused", ModelStore.isValidModelFileName("sms..pte"))
        assertFalse("absolute path refused", ModelStore.isValidModelFileName("/etc/sms_int8.pte"))
        assertFalse("subdir refused", ModelStore.isValidModelFileName("sub/sms_int8.pte"))
    }

    @Test
    fun testSha256ShortIsFirstEightHex() {
        // SHA-256 of "" = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assertEquals("e3b0c442", sha256Short(""))
        assertEquals(8, sha256Short("any text").length)
        assertTrue("hex only", sha256Short("any text").matches(Regex("[0-9a-f]{8}")))
    }

    @Test
    fun testSha256HexStreamsFile() {
        val dir = tempDir()
        val file = File(dir, "data.bin")
        file.writeText("hello world")
        val hash = ModelStore.sha256Hex(file)
        assertEquals(64, hash.length)
        assertTrue("hex only", hash.matches(Regex("[0-9a-f]{64}")))
        // Same content, same hash; different content, different hash.
        val other = File(dir, "other.bin")
        other.writeText("hello world!")
        assertNotEquals(hash, ModelStore.sha256Hex(other))
    }

    @Test
    fun testCheckFileManifestMissingIsUnverifiedButLoadable() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap()
        )
        val model = File(sourceDir, "url_cnn_v2.pte")
        model.writeText("model bytes")

        // No expected hash: refuse with clear message, never load unverified.
        val check = store.checkFile(model)
        assertFalse("should not be loadable when hash is absent", check.loadable)
        assertFalse("not verified when hash is absent", check.verified)
        assertNotNull("refusal message expected", check.message)
        assertTrue("refusal mentions refusing", check.message!!.contains("refusing to load"))
        assertFalse("no internal copy on refusal", File(modelsDir, "url_cnn_v2.pte").exists())

        // Cached once per app start: same instance returned.
        assertSame("hash result cached per app start", check, store.checkFile(model))
    }

    @Test
    fun testCheckFileMatchingManifestIsVerified() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val model = File(sourceDir, "sms_int8.pte")
        model.writeText("sms model content")
        val hash = ModelStore.sha256Hex(model)
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("sms_int8.pte" to hash)
        )

        val check = store.checkFile(model)
        assertTrue("verified when hash matches", check.verified)
        assertTrue("loadable when verified", check.loadable)
        assertNull("no error message when verified", check.message)
        val internal = File(modelsDir, "sms_int8.pte")
        assertTrue("internal copy created", internal.isFile)
        assertEquals("sms model content", internal.readText())
        assertFalse("verified external duplicate deleted", model.exists())
    }

    @Test
    fun testCheckFileMismatchedManifestRefuses() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val model = File(sourceDir, "llama.pte")
        model.writeText("llama model content")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null,
            mapOf("llama.pte" to "0000000000000000000000000000000000000000000000000000000000000000")
        )

        val check = store.checkFile(model)
        assertFalse("refused on hash mismatch", check.loadable)
        assertFalse("not verified on mismatch", check.verified)
        assertNotNull("refusal message expected", check.message)
        assertTrue("message mentions mismatch", check.message!!.contains("mismatch"))
        assertFalse("no internal copy on mismatch", File(modelsDir, "llama.pte").exists())
    }

    @Test
    fun testCheckFileMissingManifestEntryRefuses() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val model = File(sourceDir, "tokenizer.model")
        model.writeText("tokens")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("some_other.pte" to "aaaa")
        )

        val check = store.checkFile(model)
        assertFalse("refused when file has no manifest entry", check.loadable)
        assertTrue("message mentions no expected hash", check.message!!.contains("No expected hash"))
    }

    @Test
    fun testCheckFileParsesManifest() {
        val hash1 = "a".repeat(64)
        val hash2 = "b".repeat(64)
        val text = """
            $hash1  url_cnn_v2.pte

            $hash2  llama.pte
        """.trimIndent()
        val manifest = ModelStore.parseManifestText(text)
        assertEquals(hash1, manifest["url_cnn_v2.pte"])
        assertEquals(hash2, manifest["llama.pte"])
        assertEquals(2, manifest.size)
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, manifest
        )
        assertEquals(hash1, store.expectedHashes["url_cnn_v2.pte"])
        assertEquals(hash2, store.expectedHashes["llama.pte"])
    }

    @Test
    fun testParseManifestRejectsMalformedHash() {
        try {
            ModelStore.parseManifestText("deadbeef  url_cnn_v2.pte")
            fail("short hash must be rejected")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("invalid SHA-256 hash"))
        }
        try {
            ModelStore.parseManifestText("A".repeat(64) + "  url_cnn_v2.pte")
            fail("uppercase hash must be rejected")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("invalid SHA-256 hash"))
        }
        try {
            ModelStore.parseManifestText("xyz  url_cnn_v2.pte")
            fail("non-hex hash must be rejected")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("invalid SHA-256 hash"))
        }
    }

    @Test
    fun testParseManifestRejectsDuplicateName() {
        val hash = "a".repeat(64)
        try {
            ModelStore.parseManifestText("$hash  url_cnn_v2.pte\n$hash  url_cnn_v2.pte")
            fail("duplicate name must be rejected")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("duplicate entry"))
        }
        try {
            ModelStore.parseManifestText("$hash  url_cnn_v2.pte\n${"b".repeat(64)}  url_cnn_v2.pte")
            fail("duplicate name with different hash must be rejected")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message!!.contains("duplicate entry"))
        }
    }

    @Test
    fun testErrorsAndWarnings() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("sms_int8.pte" to "0000")
        )
        val bad = File(sourceDir, "sms_int8.pte")
        bad.writeText("x")
        store.checkFile(bad)
        assertTrue("mismatch is an error", store.errors().isNotEmpty())
        assertTrue("error mentions refusal", store.errors().first().contains("refusing to load"))

        val dir2Source = tempDir()
        val dir2Models = tempDir()
        val store2 = ModelStore(
            dir2Source, dir2Models, ModelFileNames.defaults(), null, emptyMap()
        )
        val good = File(dir2Source, "vocab.json")
        good.writeText("{}")
        store2.checkFile(good)
        assertTrue("missing hash is an error", store2.errors().isNotEmpty())
        assertTrue("no unverified-but-loadable warning", store2.warnings().isEmpty())
    }

    @Test
    fun testGoodExternalFileCopiedToInternalVerified() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val content = "good external model bytes for copy test"
        val sourceFile = File(sourceDir, "url_cnn_v2.pte")
        sourceFile.writeText(content)
        val hash = ModelStore.sha256Hex(sourceFile)
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("url_cnn_v2.pte" to hash)
        )
        val check = store.checkFile(store.urlModelFile)
        assertTrue("good external verified", check.verified)
        assertTrue("good external loadable", check.loadable)
        assertNull(check.message)
        val internal = File(modelsDir, "url_cnn_v2.pte")
        assertTrue("internal copy exists", internal.isFile)
        assertEquals(content, internal.readText())
        assertFalse("external duplicate deleted after verified import", sourceFile.exists())
    }

    @Test
    fun testTamperedExternalWithTamperedManifestRefused() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val name = "sms_int8.pte"
        val good = "good sms model content for tamper test!!"
        val bad = "evil sms model content for tamper test!!"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val goodHash = ModelStore.sha256Hex(sourceFile)
        // Attacker replaces the file and rewrites the external manifest to match.
        sourceFile.writeText(bad)
        val badHash = ModelStore.sha256Hex(sourceFile)
        File(sourceDir, "models.sha256").writeText("$badHash  $name\n")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf(name to goodHash)
        )
        val check = store.checkFile(sourceFile)
        assertFalse("tampered external refused", check.loadable)
        assertFalse("not verified", check.verified)
        assertTrue("mismatch message", check.message!!.contains("mismatch"))
        assertFalse("no internal file from tampered external", File(modelsDir, name).exists())
    }

    @Test
    fun testSameSizeSameMtimeSwapUsesInternal() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "llama.pte"
        val good = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        val bad = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)
        assertEquals(good, internal.readText())
        val sourceModified = sourceFile.lastModified()
        // Same-size same-mtime swap of the external file.
        sourceFile.writeText(bad)
        sourceFile.setLastModified(sourceModified)
        assertEquals(good.length.toLong(), sourceFile.length())
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val check = second.checkFile(File(sourceDir, name))
        assertTrue("internal still verified after swap", check.verified)
        assertTrue("still loadable", check.loadable)
        assertEquals(good, internal.readText())
    }

    @Test
    fun testTamperedInternalWithForgedCacheDeleted() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "sms_int8.pte"
        val good = "good-internal-bytes-0123456789-abcd"
        val bad = "bad--internal-bytes-0123456789-abcd"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)
        val internalModified = internal.lastModified()
        internal.writeText(bad)
        assertEquals(good.length.toLong(), internal.length())
        internal.setLastModified(internalModified)
        sourceFile.writeText(bad)
        assertEquals(good.length.toLong(), sourceFile.length())
        sourceFile.setLastModified(internalModified)
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val staleEntries = IntegrityCache.loadEntries(cacheFile).mapValues { (_, rec) ->
            rec.copy(lastVerifiedMs = System.currentTimeMillis() - 8L * 24L * 60L * 60L * 1000L)
        }
        assertTrue(IntegrityCache.saveEntries(cacheFile, staleEntries))
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val check = checkAfterBackgroundRehash(second, internal)
        assertFalse("cold start must re-hash and refuse tampered internal", check.loadable)
        assertFalse(check.verified)
        assertFalse("tampered internal deleted after cold hash", internal.exists())
    }

    @Test
    fun testCopyTimeHashStoresLastVerifiedMs() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "llama.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("copy-time verified bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val beforeMs = System.currentTimeMillis()
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, mapOf(name to hash)
        )
        assertTrue(store.checkFile(sourceFile).verified)
        val afterMs = System.currentTimeMillis()
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val entry = IntegrityCache.loadEntries(cacheFile)[name]
        assertNotNull(entry)
        assertTrue(
            "copy-time hash stores lastVerifiedMs in ${beforeMs..afterMs}, got ${entry!!.lastVerifiedMs}",
            entry.lastVerifiedMs in beforeMs..afterMs
        )
    }

    @Test
    fun testOldCacheFileWithoutFieldIsRehashed() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "sms_int8.pte"
        val good = "good-internal-bytes-0123456789-abcd"
        val bad = "bad--internal-bytes-0123456789-abcd"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)
        val internalModified = internal.lastModified()
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val fresh = IntegrityCache.loadEntries(cacheFile)[name]!!
        // Rewrite the cache like an old file without last_verified_ms.
        cacheFile.writeText(
            "[{\"name\":\"$name\",\"size\":${fresh.sizeBytes},\"last_modified_ms\":${fresh.lastModifiedMs}," +
                "\"sha256\":\"${fresh.sha256Hex}\"}]",
            Charsets.UTF_8
        )
        assertEquals(0L, IntegrityCache.loadEntries(cacheFile)[name]?.lastVerifiedMs)
        internal.writeText(bad)
        assertEquals(good.length.toLong(), internal.length())
        internal.setLastModified(internalModified)
        sourceFile.writeText(bad)
        assertEquals(good.length.toLong(), sourceFile.length())
        sourceFile.setLastModified(internalModified)
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val check = checkAfterBackgroundRehash(second, internal)
        assertFalse("cold start re-hashes and refuses tampered copy", check.loadable)
        assertFalse("old cache file without the field is re-hashed", internal.exists())
    }

    @Test
    fun testRecordVerifiedOneDayAgoIsNotQueued() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "sms_int8.pte"
        val good = "good-internal-bytes-0123456789-abcd"
        val bad = "bad--internal-bytes-0123456789-abcd"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        val internalModified = internal.lastModified()
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val recentEntries = IntegrityCache.loadEntries(cacheFile).mapValues { (_, rec) ->
            rec.copy(lastVerifiedMs = System.currentTimeMillis() - 24L * 60L * 60L * 1000L)
        }
        assertTrue(IntegrityCache.saveEntries(cacheFile, recentEntries))
        internal.writeText(bad)
        internal.setLastModified(internalModified)
        sourceFile.writeText(bad)
        assertEquals(good.length.toLong(), sourceFile.length())
        sourceFile.setLastModified(internalModified)
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val check = checkAfterBackgroundRehash(second, internal)
        assertFalse("cold start refuses tampered copy regardless of age", check.loadable)
        assertFalse("tampered copy deleted on cold hash", internal.exists())
    }

    @Test
    fun testRecordVerifiedEightDaysAgoIsQueued() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "sms_int8.pte"
        val good = "good-internal-bytes-0123456789-abcd"
        val bad = "bad--internal-bytes-0123456789-abcd"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        val internalModified = internal.lastModified()
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val staleEntries = IntegrityCache.loadEntries(cacheFile).mapValues { (_, rec) ->
            rec.copy(lastVerifiedMs = System.currentTimeMillis() - 8L * 24L * 60L * 60L * 1000L)
        }
        assertTrue(IntegrityCache.saveEntries(cacheFile, staleEntries))
        internal.writeText(bad)
        internal.setLastModified(internalModified)
        sourceFile.writeText(bad)
        assertEquals(good.length.toLong(), sourceFile.length())
        sourceFile.setLastModified(internalModified)
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val check = checkAfterBackgroundRehash(second, internal)
        assertFalse("cold start refuses tampered copy", check.loadable)
        assertFalse("record verified 8 days ago is re-hashed on cold start", internal.exists())
    }

    @Test
    fun testSuccessfulBackgroundRehashUpdatesLastVerifiedMs() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "llama.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("good background verified bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val staleMs = System.currentTimeMillis() - 8L * 24L * 60L * 60L * 1000L
        val staleEntries = IntegrityCache.loadEntries(cacheFile).mapValues { (_, rec) ->
            rec.copy(lastVerifiedMs = staleMs)
        }
        assertTrue(IntegrityCache.saveEntries(cacheFile, staleEntries))
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val beforeMs = System.currentTimeMillis()
        assertTrue(second.checkFile(internal).verified)
        second.startBackgroundRehash()
        val deadline = System.currentTimeMillis() + 5000L
        var now = 0L
        while (System.currentTimeMillis() < deadline) {
            now = IntegrityCache.loadEntries(cacheFile)[name]?.lastVerifiedMs ?: 0L
            if (now >= beforeMs) break
            Thread.sleep(20L)
        }
        assertTrue("background re-hash updates lastVerifiedMs", now in beforeMs..System.currentTimeMillis())
        assertTrue(internal.isFile)
    }

    @Test
    fun testFileQueuedAfterFirstRehashIsRehashedBySecondCall() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val smsName = "sms_int8.pte"
        val llamaName = "llama.pte"
        val goodSms = "good-internal-bytes-0123456789-abcd"
        val badSms = "bad--internal-bytes-0123456789-abcd"
        val goodLlama = "good-llama-bytes-0123456789-abcdef"
        val badLlama = "bad--llama-bytes-0123456789-abcdef"
        assertEquals(goodSms.length, badSms.length)
        assertEquals(goodLlama.length, badLlama.length)
        val smsSource = File(sourceDir, smsName)
        smsSource.writeText(goodSms)
        val llamaSource = File(sourceDir, llamaName)
        llamaSource.writeText(goodLlama)
        val hashes = mapOf(
            smsName to ModelStore.sha256Hex(smsSource),
            llamaName to ModelStore.sha256Hex(llamaSource)
        )
        val first = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        assertTrue(first.checkFile(smsSource).verified)
        assertTrue(first.checkFile(llamaSource).verified)
        val internalSms = File(modelsDir, smsName)
        val internalLlama = File(modelsDir, llamaName)
        assertTrue(internalSms.isFile)
        assertTrue(internalLlama.isFile)
        val smsModified = internalSms.lastModified()
        val llamaModified = internalLlama.lastModified()
        val cacheFile = IntegrityCache.cacheFile(cacheDir)!!
        val staleEntries = IntegrityCache.loadEntries(cacheFile).mapValues { (_, rec) ->
            rec.copy(lastVerifiedMs = System.currentTimeMillis() - 8L * 24L * 60L * 60L * 1000L)
        }
        assertTrue(IntegrityCache.saveEntries(cacheFile, staleEntries))
        internalSms.writeText(badSms)
        internalSms.setLastModified(smsModified)
        internalLlama.writeText(badLlama)
        internalLlama.setLastModified(llamaModified)
        smsSource.writeText(badSms)
        smsSource.setLastModified(smsModified)
        llamaSource.writeText(badLlama)
        llamaSource.setLastModified(llamaModified)
        val second = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes
        )
        val smsCheck = checkAfterBackgroundRehash(second, internalSms)
        assertFalse("cold start refuses tampered sms synchronously", smsCheck.loadable)
        assertFalse("tampered sms deleted on cold hash", internalSms.exists())
        val llamaCheck = checkAfterBackgroundRehash(second, internalLlama)
        assertFalse("cold start refuses tampered llama synchronously", llamaCheck.loadable)
        assertFalse("tampered llama deleted on cold hash", internalLlama.exists())
    }

    @Test
    fun testMissingHashEntryRefuses() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val name = "tokenizer.model"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("tokens")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null,
            mapOf("other.pte" to "aaaa")
        )
        val check = store.checkFile(sourceFile)
        assertFalse("missing hash refused", check.loadable)
        assertFalse("not verified", check.verified)
        assertTrue("message mentions no expected hash", check.message!!.contains("refusing to load"))
        assertFalse("no internal copy", File(modelsDir, name).exists())
    }

    @Test
    fun testLeftoverTmpFileRemovedAfterSuccessfulVerify() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val content = "good external model bytes for tmp cleanup test"
        val sourceFile = File(sourceDir, "url_cnn_v2.pte")
        sourceFile.writeText(content)
        val hash = ModelStore.sha256Hex(sourceFile)
        val leftover = File(modelsDir, "url_cnn_v2.pte.tmp")
        leftover.writeText("orphan from earlier kill")
        assertTrue(leftover.isFile)
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("url_cnn_v2.pte" to hash)
        )
        val check = store.checkFile(store.urlModelFile)
        assertTrue("verified", check.verified)
        assertFalse("leftover tmp gone", leftover.exists())
    }

    @Test
    fun testNoTmpFileAfterSuccessfulVerify() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val content = "good external model bytes for no tmp test"
        val sourceFile = File(sourceDir, "sms_int8.pte")
        sourceFile.writeText(content)
        val hash = ModelStore.sha256Hex(sourceFile)
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf("sms_int8.pte" to hash)
        )
        val check = store.checkFile(sourceFile)
        assertTrue("verified", check.verified)
        val tmpFiles = modelsDir.listFiles { f -> f.name.endsWith(".tmp") }?.toList() ?: emptyList()
        assertTrue("no .tmp files after verify, got $tmpFiles", tmpFiles.isEmpty())
    }

    @Test
    fun testSmsSnapshotUnchangedWhenFilesUnchanged() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val pte = File(modelsDir, "sms_int8.pte")
        pte.writeText("sms-bytes")
        pte.setLastModified(1_700_000_000_000L)
        val first = store.smsFileSnapshot()
        val second = store.smsFileSnapshot()
        assertFalse("unchanged files must not trigger a retry", smsSnapshotsChanged(first, second))
        assertEquals(first, second)
    }

    @Test
    fun testSmsSnapshotChangesWhenSizeChanges() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val pte = File(modelsDir, "sms_int8.pte")
        pte.writeText("sms-bytes")
        pte.setLastModified(1_700_000_000_000L)
        val first = store.smsFileSnapshot()
        pte.writeText("sms-bytes-reinstalled-longer")
        pte.setLastModified(1_700_000_000_000L)
        val second = store.smsFileSnapshot()
        assertTrue("size change must trigger a retry", smsSnapshotsChanged(first, second))
    }

    @Test
    fun testSmsSnapshotChangesWhenMtimeChanges() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val pte = File(modelsDir, "sms_int8.pte")
        pte.writeText("sms-bytes")
        pte.setLastModified(1_700_000_000_000L)
        val first = store.smsFileSnapshot()
        pte.setLastModified(1_700_000_100_000L)
        val second = store.smsFileSnapshot()
        assertTrue("mtime change must trigger a retry", smsSnapshotsChanged(first, second))
    }

    @Test
    fun testSmsSnapshotChangesWhenFileAppears() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val first = store.smsFileSnapshot()
        val pte = File(modelsDir, "sms_int8.pte")
        pte.writeText("sms-bytes")
        pte.setLastModified(1_700_000_000_000L)
        val second = store.smsFileSnapshot()
        assertTrue("a newly installed file must trigger a retry", smsSnapshotsChanged(first, second))
        assertTrue("a null baseline must trigger a retry", smsSnapshotsChanged(null, second))
    }

    @Test
    fun testShouldRetrySmsLoadDecision() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val baseline = store.smsFileSnapshot()

        // 1. Model already loaded: never retry even if files changed
        val pte = File(sourceDir, "sms_fp32.pte")
        pte.writeText("sms-fp32-bytes")
        val updated = store.smsFileSnapshot()
        assertFalse(
            "already loaded model must not retry",
            shouldRetrySmsLoad(isLoaded = true, smsStatus = "loaded (real length)", baseline, updated)
        )

        // 2. Status loaded: never retry
        assertFalse(
            "loaded status must not retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "loaded (padded 128)", baseline, updated)
        )

        // 3. Status failed but snapshot unchanged: no retry
        assertFalse(
            "failed status with unchanged snapshot must not retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "failed: no model file", baseline, baseline)
        )

        // 4. Status failed and external file appeared (Galaxy M31 install bug scenario): retry!
        assertTrue(
            "failed status with changed external file snapshot must retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "failed: model file not found for CPU (asimddp=false)", baseline, updated)
        )

        // 5. Status not installed and files appeared: retry!
        assertTrue(
            "not installed status with changed snapshot must retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "not installed", baseline, updated)
        )

        // 6. Null baseline (no previous attempt snapshot captured): retry!
        assertTrue(
            "null baseline snapshot must retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "failed: timeout", null, updated)
        )
    }

    @Test
    fun testSmsSnapshotChangesWhenExternalFileAppearsInSourceDir() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        val first = store.smsFileSnapshot()

        // Simulate adb push of sms_fp32.pte into external models folder
        val externalFp32 = File(sourceDir, "sms_fp32.pte")
        externalFp32.writeText("external fp32 model weights")
        externalFp32.setLastModified(1_700_000_000_000L)
        val second = store.smsFileSnapshot()

        assertTrue("external file appearing in sourceDir must change snapshot", smsSnapshotsChanged(first, second))
        assertTrue(
            "external file arrival must trigger retry decision",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "failed: model file not found", first, second)
        )

        // Snapshot updated: no further retry without new file changes
        assertFalse("same snapshot must not trigger retry", smsSnapshotsChanged(second, second))
        assertFalse(
            "unchanged external files must not trigger retry",
            shouldRetrySmsLoad(isLoaded = false, smsStatus = "failed: previous attempt", second, second)
        )
    }

    @Test
    fun testPersistedSmsRecordIsHashedSynchronously() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "sms_int8.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("sms model bytes hashed every start")
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        assertTrue(internal.isFile)

        val hashCalls = AtomicInteger(0)
        val second = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes) { file ->
            hashCalls.incrementAndGet()
            ModelStore.sha256Hex(file)
        }
        val check = second.checkFile(internal)
        assertTrue("persisted SMS copy still loads", check.loadable)
        assertTrue(check.verified)
        assertEquals("the SMS model must be hashed synchronously", 1L, hashCalls.get().toLong())
        assertFalse("the SMS model is never queued", second.isPendingRehash(name))
        assertTrue("a synchronous hash counts as verified", runBlocking { second.awaitVerified(name, 1000L) })
    }

    @Test
    fun testTamperedTrustedLlamaFailsAwaitVerified() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val cacheDir = tempDir()
        val name = "llama.pte"
        val good = "good llama bytes 0123456789abcdef"
        val bad = "bad--llama bytes 0123456789abcdef"
        assertEquals(good.length, bad.length)
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText(good)
        val hash = ModelStore.sha256Hex(sourceFile)
        val hashes = mapOf(name to hash)
        val first = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes)
        assertTrue(first.checkFile(sourceFile).verified)
        val internal = File(modelsDir, name)
        val trustedModified = internal.lastModified()
        internal.writeText(bad)
        assertEquals(good.length.toLong(), internal.length())
        internal.setLastModified(trustedModified)

        val gate = CountDownLatch(1)
        val second = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), cacheDir, hashes) { file ->
            gate.await()
            ModelStore.sha256Hex(file)
        }
        val check = second.checkFile(internal)
        assertTrue("a same size and mtime Llama copy loads before the re-hash", check.loadable)
        assertTrue("the trusted Llama copy is pending re-hash", second.isPendingRehash(name))
        assertFalse(second.rehashFailed(name))
        gate.countDown()
        assertFalse("a tampered Llama copy never verifies", runBlocking { second.awaitVerified(name, 5000L) })
        assertTrue("the mismatch is recorded", second.rehashFailed(name))
        assertFalse("the tampered Llama copy is deleted", internal.exists())
        assertFalse(second.isPendingRehash(name))
    }

    @Test
    fun testRepoModelHashesCoversDefaults() {
        val candidates = listOf(
            File("src/main/model_hashes/models.sha256"),
            File("app/src/main/model_hashes/models.sha256"),
            File("android/app/src/main/model_hashes/models.sha256"),
            File("../../src/main/model_hashes/models.sha256"),
            File("../src/main/model_hashes/models.sha256")
        )
        val hashesFile = candidates.firstOrNull { it.exists() && it.isFile }
            ?: throw AssertionError("repo model_hashes/models.sha256 not found; tried $candidates")
        val text = hashesFile.readText(Charsets.UTF_8)
        val parsed = ModelStore.parseManifestText(text)
        val defaults = ModelFileNames.defaults()
        val required = listOf(
            defaults.urlModel,
            defaults.urlVocab,
            defaults.smsModel,
            defaults.smsIdMap,
            defaults.smsVocab,
            defaults.llamaModel,
            defaults.llamaTokenizer,
            defaults.smsFp32
        ).distinct()
        for (needed in required) {
            assertTrue("models.sha256 must list $needed", parsed.containsKey(needed))
        }
    }

    @Test
    fun testStaleSmsVocabCacheRemovedAndCurrentKept() {
        val vocabDir = tempDir()
        val cacheDir = tempDir()
        val vocab = File(vocabDir, "sms_vocab.txt")
        vocab.writeText("# min_score=0.0\nhello\t-1.0\nworld\t-2.0\n")
        val stale = File(cacheDir, "sms_vocab_1_1.bin")
        stale.writeText("stale cache")
        val staleOther = File(cacheDir, "sms_vocab_2_2.bin")
        staleOther.writeText("other stale cache")
        val unrelated = File(cacheDir, "url_vocab_1_1.bin")
        unrelated.writeText("keep me")

        SmsTokenizer.fromFile(vocab, cacheDir = cacheDir)

        assertFalse("older sms_vocab cache removed", stale.exists())
        assertFalse("other stale sms_vocab cache removed", staleOther.exists())
        assertTrue("unrelated cache kept", unrelated.exists())
        val current = cacheDir.listFiles { file ->
            file.name.startsWith("sms_vocab_") && file.name.endsWith(".bin")
        } ?: emptyArray()
        assertEquals("only the current sms_vocab cache remains", 1, current.size)
        assertTrue("current cache exists", current[0].isFile)
    }

    @Test
    fun testExternalDuplicateDeletedAfterVerifiedImport() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val name = "url_cnn_v2.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("verified external bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf(name to hash)
        )

        val check = store.checkFile(sourceFile)

        assertTrue("import verified", check.verified)
        assertTrue("internal copy kept", File(modelsDir, name).isFile)
        assertFalse("external duplicate deleted", sourceFile.exists())
    }

    @Test
    fun testExternalDuplicateKeptWhenHashMismatches() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val name = "sms_int8.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("external bytes")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null,
            mapOf(name to "0000000000000000000000000000000000000000000000000000000000000000")
        )

        val check = store.checkFile(sourceFile)

        assertFalse("mismatched import refused", check.loadable)
        assertFalse("no internal copy from mismatch", File(modelsDir, name).exists())
        assertTrue("external file kept after mismatch", sourceFile.exists())
    }

    @Test
    fun testExternalDuplicateKeptWhenKeepFlagExists() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val name = "llama.pte"
        val sourceFile = File(sourceDir, name)
        sourceFile.writeText("llama bytes")
        val hash = ModelStore.sha256Hex(sourceFile)
        File(sourceDir, ModelStore.KEEP_EXTERNAL_FLAG_FILE_NAME).writeText("")
        val store = ModelStore(
            sourceDir, modelsDir, ModelFileNames.defaults(), null, mapOf(name to hash)
        )

        val check = store.checkFile(sourceFile)

        assertTrue("import verified", check.verified)
        assertTrue("internal copy kept", File(modelsDir, name).isFile)
        assertTrue("external file kept by developer flag", sourceFile.exists())
    }

    @Test
    fun testReadinessStaysTrueAfterExternalDuplicateDeleted() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        val names = listOf(
            "url_cnn_v2.pte", "vocab.json", "sms_int8.pte", "id_map.json",
            "sms_vocab.txt", "llama.pte", "tokenizer.model"
        )
        val hashes = linkedMapOf<String, String>()
        for (name in names) {
            val file = File(sourceDir, name)
            file.writeText("content for $name")
            hashes[name] = ModelStore.sha256Hex(file)
        }
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, hashes)

        assertTrue("URL ready before import", store.isUrlClassifierReady())
        assertTrue("Llama ready before import", store.isLlamaReady())
        assertTrue("SMS ready before import", store.isSmsClassifierReadyFor(CpuFlags(asimddp = true)))

        val failure = store.verifyForLoad(
            listOf(
                store.urlModelFile, store.vocabFile, store.llamaModelFile, store.tokenizerFile,
                store.smsModelFile, store.idMapFile, store.smsVocabFile
            )
        )
        assertNull("all imported files verified", failure)

        for (name in names) {
            assertFalse("external $name deleted", File(sourceDir, name).exists())
            assertTrue("internal $name kept", File(modelsDir, name).isFile)
        }
        assertTrue("URL ready after external deletion", store.isUrlClassifierReady())
        assertTrue("Llama ready after external deletion", store.isLlamaReady())
        assertTrue(
            "SMS ready after external deletion",
            store.isSmsClassifierReadyFor(CpuFlags(asimddp = true))
        )
    }
}
