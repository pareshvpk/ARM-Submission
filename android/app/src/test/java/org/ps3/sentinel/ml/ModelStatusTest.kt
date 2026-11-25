package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class ModelStatusTest {

    private fun tempDir(): File {
        val dir = File(
            System.getProperty("java.io.tmpdir"),
            "modelstatus-${System.nanoTime()}-${Thread.currentThread().id}"
        )
        check(dir.mkdirs()) { "Could not create temp directory ${dir.absolutePath}" }
        return dir
    }

    private fun createModelFiles(dir: File) {
        File(dir, "url_cnn_v2.pte").writeText("url model")
        File(dir, "vocab.json").writeText("{}")
        File(dir, "llama.pte").writeText("llama model")
        File(dir, "tokenizer.model").writeText("tokens")
    }

    private fun writeManifest(dir: File, files: List<String>): MutableMap<String, String> {
        val hashes = linkedMapOf<String, String>()
        for (name in files) {
            hashes[name] = ModelStore.sha256Hex(File(dir, name))
        }
        return hashes
    }

    private fun countOccurrences(text: String, needle: String): Int {
        var count = 0
        var index = 0
        while (true) {
            val pos = text.indexOf(needle, index)
            if (pos < 0) break
            count += 1
            index = pos + needle.length
        }
        return count
    }

    private fun baseInput(
        missing: List<String> = emptyList(),
        loaded: List<String> = listOf("url_cnn_v2.pte", "vocab.json", "llama.pte", "tokenizer.model"),
        refused: List<String> = emptyList(),
        errors: List<String> = emptyList(),
        warnings: List<String> = emptyList(),
        isVerifying: Boolean = false,
        smsStatus: String = "not installed"
    ) = ModelStatusInput(
        missing = missing,
        isUrlReady = true,
        loaded = loaded,
        refused = refused,
        errors = errors,
        warnings = warnings,
        isVerifying = isVerifying,
        rulesStatus = null,
        smsStatus = smsStatus
    )

    @Test
    fun testVerifyingThenVerifiedClearsVerifyingText() {
        val verifying = ModelStatus.build(baseInput(isVerifying = true))
        assertTrue("shows verifying while hashing", verifying.contains("verifying model integrity"))

        val verified = ModelStatus.build(baseInput(isVerifying = false))
        assertFalse("verifying text gone after verification", verified.contains("verifying model integrity"))
        assertTrue("all models available when verified", verified.contains("All models available"))
        assertFalse("no unverified section when verified", verified.contains("UNVERIFIED"))
        assertFalse("no errors section when verified", verified.contains("MODEL ERRORS"))
    }

    @Test
    fun testVerificationFinishedListenerFires() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        createModelFiles(sourceDir)
        val hashes = writeManifest(sourceDir, listOf("url_cnn_v2.pte", "vocab.json", "llama.pte", "tokenizer.model"))
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, hashes)
        val fired = AtomicBoolean(false)
        store.onVerificationFinished = { fired.set(true) }

        val failure = store.verifyForLoad(listOf(store.urlModelFile, store.vocabFile))
        assertTrue("listener fired when verification ended", fired.get())
        assertFalse("not verifying after verifyForLoad", store.isVerifying)
        assertEquals(null, failure?.message)
        val summary = store.statusSummary("not installed")
        assertFalse("status no longer says verifying", summary.contains("verifying model integrity"))
    }

    @Test
    fun testVerifyingThenMismatchDoesNotSayAllModelsAvailable() {
        val mismatch = "SHA-256 mismatch for url_cnn_v2.pte; refusing to load"
        val during = ModelStatus.build(baseInput(isVerifying = true, refused = emptyList()))
        assertTrue(during.contains("verifying model integrity"))

        val finalStatus = ModelStatus.build(
            baseInput(
                loaded = listOf("vocab.json", "llama.pte", "tokenizer.model"),
                refused = listOf("url_cnn_v2.pte"),
                errors = listOf(mismatch)
            )
        )
        assertFalse("must not claim all models available on mismatch", finalStatus.startsWith("All models available"))
        assertFalse("must not claim all models available anywhere", finalStatus.contains("All models available"))
        assertTrue("names loaded models", finalStatus.contains("Loaded: vocab.json, llama.pte, tokenizer.model"))
        assertTrue("names refused model", finalStatus.contains("Refused: url_cnn_v2.pte"))
        assertTrue("shows mismatch error", finalStatus.contains("MODEL ERRORS"))
        assertFalse("no longer verifying after mismatch", finalStatus.contains("verifying model integrity"))
    }

    @Test
    fun testStoreMismatchStatusNamesLoadedAndRefused() {
        val sourceDir = tempDir()
        val modelsDir = tempDir()
        createModelFiles(sourceDir)
        val hashes = writeManifest(
            sourceDir,
            listOf("url_cnn_v2.pte", "vocab.json", "llama.pte", "tokenizer.model")
        )
        // Corrupt one entry so url_cnn_v2.pte mismatches.
        hashes["url_cnn_v2.pte"] = "0000000000000000000000000000000000000000000000000000000000000000"
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, hashes)
        store.checkFile(store.urlModelFile)
        store.checkFile(store.vocabFile)
        store.checkFile(store.llamaModelFile)
        store.checkFile(store.tokenizerFile)
        val summary = store.statusSummary("not installed")
        assertFalse("store status must not start with All models available", summary.startsWith("All models available"))
        assertTrue("store names refused model", summary.contains("url_cnn_v2.pte"))
        assertTrue("store says Refused", summary.contains("Refused:"))
        assertTrue("store says Loaded", summary.contains("Loaded:"))
        assertFalse("mismatch is not unverified", summary.contains("UNVERIFIED"))
    }

    @Test
    fun testDuplicateWarningsCollapsed() {
        val warning = "Unverified models: models.sha256 manifest is missing"
        val status = ModelStatus.build(baseInput(warnings = List(8) { warning }))
        assertEquals("each distinct warning shown once", 1, countOccurrences(status, "Unverified models"))
        assertEquals("unverified section shown once", 1, countOccurrences(status, "UNVERIFIED:"))

        val sourceDir = tempDir()
        val modelsDir = tempDir()
        createModelFiles(sourceDir)
        val store = ModelStore(sourceDir, modelsDir, ModelFileNames.defaults(), null, emptyMap())
        store.checkFile(store.urlModelFile)
        store.checkFile(store.vocabFile)
        store.checkFile(store.llamaModelFile)
        store.checkFile(store.tokenizerFile)
        assertEquals("store warnings empty for refused", 0, store.warnings().size)
        assertTrue("store errors non-empty for missing hash", store.errors().isNotEmpty())
        val summary = store.statusSummary("not installed")
        assertFalse("store shows no unverified section", summary.contains("UNVERIFIED:"))
    }
}
