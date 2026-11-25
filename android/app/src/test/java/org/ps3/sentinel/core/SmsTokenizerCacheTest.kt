package org.ps3.sentinel.core

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class SmsTokenizerCacheTest {

    private fun resolveVocabSource(): File {
        val candidates = listOf(
            File("../../models/sms_v5q/sms_vocab.txt"),
            File("../models/sms_v5q/sms_vocab.txt"),
            File("models/sms_v5q/sms_vocab.txt"),
            File("src/test/resources/sms_vocab.txt"),
            File("app/src/test/resources/sms_vocab.txt")
        )
        val found = candidates.firstOrNull { it.exists() && it.isFile }
        if (found != null) return found
        val stream = SmsTokenizerCacheTest::class.java.getResourceAsStream("/sms_vocab.txt")
            ?: error("sms_vocab.txt not found in candidate paths or classpath resources")
        val tmp = Files.createTempFile("sms_vocab_src", ".txt").toFile()
        tmp.deleteOnExit()
        stream.use { input -> tmp.outputStream().use { output -> input.copyTo(output) } }
        return tmp
    }

    private fun loadFixtureTexts(): List<String> {
        val candidates = listOf(
            File("src/test/resources/sms_tok_fixture.json"),
            File("app/src/test/resources/sms_tok_fixture.json"),
            File("../../android/app/src/test/resources/sms_tok_fixture.json")
        )
        val jsonText = candidates.firstOrNull { it.exists() && it.isFile }?.let { it.readText(Charsets.UTF_8) }
            ?: SmsTokenizerCacheTest::class.java.getResourceAsStream("/sms_tok_fixture.json")?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
            ?: error("sms_tok_fixture.json not found")
        val arr = JSONArray(jsonText)
        return List(arr.length()) { idx -> arr.getJSONObject(idx).getString("text") }
    }

    private fun loadBenchTexts(): List<String> {
        val candidates = listOf(
            File("../../bench/bench_messages.txt"),
            File("../bench/bench_messages.txt"),
            File("bench/bench_messages.txt"),
            File("src/test/resources/bench_messages.txt"),
            File("app/src/test/resources/bench_messages.txt"),
            File("../../android/app/src/test/resources/bench_messages.txt")
        )
        val raw = candidates.firstOrNull { it.exists() && it.isFile }?.let { it.readText(Charsets.UTF_8) }
            ?: SmsTokenizerCacheTest::class.java.getResourceAsStream("/bench_messages.txt")?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
            ?: return emptyList()
        var parts = raw.split("\n")
        if (parts.isNotEmpty() && parts.last() == "") parts = parts.dropLast(1)
        return parts.map { it.removeSuffix("\r") }.filter { it.trim().isNotEmpty() }
    }

    private fun assertEncodeEqual(a: SmsTokenizer, b: SmsTokenizer, text: String) {
        val encA = a.encode(text)
        val encB = b.encode(text)
        assertTrue("padded ids mismatch for text: ${text.take(80)}", encA.inputIds.contentEquals(encB.inputIds))
        assertTrue("padded mask mismatch for text: ${text.take(80)}", encA.attentionMask.contentEquals(encB.attentionMask))
        val plainA = a.encode(text, pad = false)
        val plainB = b.encode(text, pad = false)
        assertTrue("unpadded ids mismatch for text: ${text.take(80)}", plainA.inputIds.contentEquals(plainB.inputIds))
        assertTrue("unpadded mask mismatch for text: ${text.take(80)}", plainA.attentionMask.contentEquals(plainB.attentionMask))
        assertEquals(a.tokenize(text), b.tokenize(text))
    }

    private fun copyVocab(source: File, destDir: File): File {
        val copy = File(destDir, source.name)
        source.copyTo(copy, overwrite = true)
        return copy
    }

    @Test
    fun testTextVsBinaryCacheParity() {
        val root = Files.createTempDirectory("smsTokParity").toFile()
        try {
            val source = resolveVocabSource()
            val vocabDir = File(root, "vocab")
            val cacheDir = File(root, "cache")
            vocabDir.mkdirs()
            cacheDir.mkdirs()
            val copy = copyVocab(source, vocabDir)
            val texts = loadFixtureTexts()
            val benchTexts = loadBenchTexts()
            val extraTexts = listOf("", "Hello world", "  \u2581Hello,  how are you?", "\uD83D\uDE00 emoji test \uFFFD \u009F end", "a".repeat(500))
            val allTexts = texts + benchTexts + extraTexts

            val textTok = SmsTokenizer.fromFile(copy)
            val firstTok = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            val cacheFiles = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") } ?: emptyArray()
            assertTrue("cache file must be written on first load, dir=${cacheDir.absolutePath}", cacheFiles.isNotEmpty())
            val cachedTok = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)

            assertEquals(textTok.unkId, cachedTok.unkId)
            assertEquals(textTok.bosId, cachedTok.bosId)
            assertEquals(textTok.eosId, cachedTok.eosId)
            assertEquals(textTok.padId, cachedTok.padId)
            assertEquals(textTok.maskId, cachedTok.maskId)
            assertEquals(textTok.minScore, cachedTok.minScore, 0.0)
            assertEquals(textTok.unkId, firstTok.unkId)
            assertEquals(textTok.minScore, firstTok.minScore, 0.0)

            for (text in allTexts) {
                assertEncodeEqual(textTok, firstTok, text)
                assertEncodeEqual(textTok, cachedTok, text)
            }
            println("Cache parity: checked ${allTexts.size} texts text==first-write==cache-load")
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun testCorruptCacheIgnored() {
        val root = Files.createTempDirectory("smsTokCorrupt").toFile()
        try {
            val source = resolveVocabSource()
            val vocabDir = File(root, "vocab")
            val cacheDir = File(root, "cache")
            vocabDir.mkdirs()
            cacheDir.mkdirs()
            val copy = copyVocab(source, vocabDir)
            val texts = loadFixtureTexts().take(20) + listOf("Hello corrupt world", "", "emoji \uD83D\uDE00")

            val textTok = SmsTokenizer.fromFile(copy)
            SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            val cacheFiles = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") } ?: emptyArray()
            assertTrue(cacheFiles.isNotEmpty())
            for (f in cacheFiles) {
                f.writeBytes("NOT A VALID CACHE".toByteArray(Charsets.UTF_8))
            }

            val afterCorrupt = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            for (text in texts) {
                assertEncodeEqual(textTok, afterCorrupt, text)
            }

            val rewritten = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") } ?: emptyArray()
            assertTrue("corrupt cache must be rewritten", rewritten.isNotEmpty())
            val reloaded = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            for (text in texts) {
                assertEncodeEqual(textTok, reloaded, text)
            }
            println("Corrupt cache ignored: fallback to text and cache rewritten")
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun testStaleCacheIgnored() {
        val root = Files.createTempDirectory("smsTokStale").toFile()
        try {
            val source = resolveVocabSource()
            val vocabDir = File(root, "vocab")
            val cacheDir = File(root, "cache")
            vocabDir.mkdirs()
            cacheDir.mkdirs()
            val copy = copyVocab(source, vocabDir)
            val texts = loadFixtureTexts().take(20) + listOf("Hello stale world")

            val originalTok = SmsTokenizer.fromFile(copy)
            SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            val beforeFiles = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") } ?: emptyArray()
            assertTrue(beforeFiles.isNotEmpty())

            copy.appendText("zzzstaletest\t-1.0\n")
            copy.setLastModified(copy.lastModified() + 5000L)

            val newTextTok = SmsTokenizer.fromFile(copy)
            val newCachedTok = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            for (text in texts) {
                assertEncodeEqual(newTextTok, newCachedTok, text)
            }
            assertEncodeEqual(newTextTok, newCachedTok, "zzzstaletest")
            val afterFiles = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") } ?: emptyArray()
            assertTrue("stale cache must not be reused; new cache required", afterFiles.size > beforeFiles.size || afterFiles.any { it.name != beforeFiles[0].name })
            println("Stale cache ignored: modified vocab parsed fresh and new cache written")
            val stillOk = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            assertEncodeEqual(newTextTok, stillOk, "Hello stale world")
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun testLoadTimingsReport() {
        val root = Files.createTempDirectory("smsTokTiming").toFile()
        try {
            val source = resolveVocabSource()
            val vocabDir = File(root, "vocab")
            val cacheDir = File(root, "cache")
            vocabDir.mkdirs()
            cacheDir.mkdirs()
            val copy = copyVocab(source, vocabDir)

            val readStart = System.nanoTime()
            val bytes = copy.readBytes()
            val readMs = (System.nanoTime() - readStart) / 1_000_000.0

            var t0 = System.nanoTime()
            val textTok = SmsTokenizer.fromFile(copy)
            val textMs = (System.nanoTime() - t0) / 1_000_000.0

            cacheDir.listFiles()?.forEach { it.delete() }
            t0 = System.nanoTime()
            val firstTok = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            val firstMs = (System.nanoTime() - t0) / 1_000_000.0
            val cacheBytes = cacheDir.listFiles { f: File -> f.name.endsWith(".bin") }?.firstOrNull()?.length() ?: -1L

            t0 = System.nanoTime()
            val cachedTok = SmsTokenizer.fromFile(copy, cacheDir = cacheDir)
            val cacheLoadMs = (System.nanoTime() - t0) / 1_000_000.0

            val sample = "Hello cache timing check 123"
            assertEncodeEqual(textTok, firstTok, sample)
            assertEncodeEqual(textTok, cachedTok, sample)
            println(
                "DT-7 timing vocab_bytes=${bytes.size} read_ms=${"%.1f".format(readMs)} " +
                    "text_parse_ms=${"%.1f".format(textMs)} first_load_with_cache_write_ms=${"%.1f".format(firstMs)} " +
                    "cache_load_ms=${"%.1f".format(cacheLoadMs)} cache_file_bytes=$cacheBytes"
            )
        } finally {
            root.deleteRecursively()
        }
    }
}
