package org.ps3.sentinel.core

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import java.io.BufferedReader
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStreamReader

class SmsTokenizerTest {

    companion object {
        private lateinit var tokenizer: SmsTokenizer
        private lateinit var fixtureArray: JSONArray

        @BeforeClass
        @JvmStatic
        fun setUp() {
            val vocabCandidates = listOf(
                File("../../models/sms_v5q/sms_vocab.txt"),
                File("../models/sms_v5q/sms_vocab.txt"),
                File("models/sms_v5q/sms_vocab.txt"),
                File("src/test/resources/sms_vocab.txt"),
                File("app/src/test/resources/sms_vocab.txt")
            )
            val vocabFile = vocabCandidates.firstOrNull { it.exists() && it.isFile }
            tokenizer = if (vocabFile != null) {
                SmsTokenizer.fromFile(vocabFile)
            } else {
                val stream = SmsTokenizerTest::class.java.getResourceAsStream("/sms_vocab.txt")
                    ?: error("sms_vocab.txt not found in candidate paths or classpath resources")
                SmsTokenizer.fromStream(stream)
            }

            val fixtureCandidates = listOf(
                File("src/test/resources/sms_tok_fixture.json"),
                File("app/src/test/resources/sms_tok_fixture.json"),
                File("../../android/app/src/test/resources/sms_tok_fixture.json")
            )
            val fixtureFile = fixtureCandidates.firstOrNull { it.exists() && it.isFile }
            val jsonText = if (fixtureFile != null) {
                fixtureFile.readText(Charsets.UTF_8)
            } else {
                val stream = SmsTokenizerTest::class.java.getResourceAsStream("/sms_tok_fixture.json")
                    ?: error("sms_tok_fixture.json not found in candidate paths or classpath resources")
                stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            }
            fixtureArray = JSONArray(jsonText)
        }
    }

    @Test
    fun testFixtureParityAgainstPythonTokenizer() {
        val total = fixtureArray.length()
        var exactMatches = 0
        val mismatches = mutableListOf<String>()

        for (i in 0 until total) {
            val obj = fixtureArray.getJSONObject(i)
            val text = obj.getString("text")
            val expIdsJson = obj.getJSONArray("input_ids")
            val expMaskJson = obj.getJSONArray("attention_mask")

            val expIds = LongArray(expIdsJson.length()) { idx -> expIdsJson.getLong(idx) }
            val expMask = LongArray(expMaskJson.length()) { idx -> expMaskJson.getLong(idx) }

            val actual = tokenizer.encode(text)

            val idsMatch = actual.inputIds.contentEquals(expIds)
            val maskMatch = actual.attentionMask.contentEquals(expMask)

            if (idsMatch && maskMatch) {
                exactMatches++
            } else {
                if (mismatches.size < 5) {
                    mismatches.add(
                        "Index $i: '${text.take(80)}'\n" +
                            "  exp ids: ${expIds.take(15)}\n" +
                            "  got ids: ${actual.inputIds.take(15)}"
                    )
                }
            }
        }

        println("Exact matches: $exactMatches / $total (${"%.2f".format(exactMatches.toDouble() / total * 100.0)}%)")
        if (mismatches.isNotEmpty()) {
            println("Mismatches sample:\n" + mismatches.joinToString("\n---\n"))
        }

        assertEquals(
            "All $total fixture messages must tokenise exactly like the Python tokenizer; got $exactMatches / $total exact",
            total, exactMatches
        )
    }

    @Test
    fun testSpecialTokensAndLengths() {
        val outEmpty = tokenizer.encode("")
        assertEquals(128, outEmpty.inputIds.size)
        assertEquals(128, outEmpty.attentionMask.size)
        assertEquals(0L, outEmpty.inputIds[0]) // <s>
        assertEquals(2L, outEmpty.inputIds[1]) // </s>
        assertEquals(1L, outEmpty.inputIds[2]) // <pad>
        assertEquals(1L, outEmpty.attentionMask[0])
        assertEquals(1L, outEmpty.attentionMask[1])
        assertEquals(0L, outEmpty.attentionMask[2])
    }

    @Test
    fun testUnpaddedEqualsPaddedWithoutPadPositions() {
        val total = fixtureArray.length()
        for (i in 0 until total) {
            val obj = fixtureArray.getJSONObject(i)
            val text = obj.getString("text")

            val padded = tokenizer.encode(text, pad = true)
            val unpadded = tokenizer.encode(text, pad = false)

            val paddedStripped = padded.inputIds.filterIndexed { idx, _ ->
                padded.attentionMask[idx] == 1L
            }

            assertEquals("Unpadded ids mismatch for fixture $i: '$text'", paddedStripped, unpadded.inputIds.toList())
            assertEquals("Unpadded mask should be all 1s", List(unpadded.inputIds.size) { 1L }, unpadded.attentionMask.toList())
        }

        val paddedEmpty = tokenizer.encode("", pad = true)
        val unpaddedEmpty = tokenizer.encode("", pad = false)
        val emptyStripped = paddedEmpty.inputIds.filterIndexed { idx, _ -> paddedEmpty.attentionMask[idx] == 1L }
        assertEquals(emptyStripped, unpaddedEmpty.inputIds.toList())
        assertEquals(2, unpaddedEmpty.inputIds.size)
        assertEquals(listOf(1L, 1L), unpaddedEmpty.attentionMask.toList())
    }

    @Test
    fun testFromStreamParsesHeaderScoresAndFallback() {
        val vocabText = buildString {
            appendLine("# unk_id=7 bos_id=8 eos_id=9 pad_id=10 mask_id=11 min_score=-5.0")
            appendLine("hello\t-1.5")
            appendLine("world\t-1.5e-3")
            appendLine("bad\tnot-a-number")
            appendLine("lowest\t-6.25")
        }
        val tok = SmsTokenizer.fromStream(ByteArrayInputStream(vocabText.toByteArray(Charsets.UTF_8)))
        assertEquals(7, tok.unkId)
        assertEquals(8, tok.bosId)
        assertEquals(9, tok.eosId)
        assertEquals(10, tok.padId)
        assertEquals(11, tok.maskId)
        assertEquals(-6.25, tok.minScore, 1e-9)
        val vocabMapField = SmsTokenizer::class.java.getDeclaredField("vocabMap")
        vocabMapField.isAccessible = true
        val vocabMap = vocabMapField.get(tok) as Map<String, SmsTokenizer.TokenEntry>
        assertEquals(0, vocabMap.getValue("hello").id)
        assertEquals(-1.5, vocabMap.getValue("hello").score, 1e-9)
        assertEquals(1, vocabMap.getValue("world").id)
        assertEquals(-1.5e-3, vocabMap.getValue("world").score, 1e-9)
        assertEquals(2, vocabMap.getValue("bad").id)
        assertEquals(0.0, vocabMap.getValue("bad").score, 1e-9)
        assertEquals(3, vocabMap.getValue("lowest").id)
        assertEquals(-6.25, vocabMap.getValue("lowest").score, 1e-9)
    }

    private fun loadOldTokenizerFromFile(vocabFile: File): SmsTokenizer {
        val map = HashMap<String, SmsTokenizer.TokenEntry>(260000)
        var unk = 3
        var bos = 0
        var eos = 2
        var pad = 1
        var mask = 250001
        var minScore = 0.0
        val reader = BufferedReader(InputStreamReader(vocabFile.inputStream(), Charsets.UTF_8), 65536)
        var lineIndex = 0
        var currentId = 0
        reader.forEachLine { line ->
            if (lineIndex == 0 && line.startsWith("#")) {
                val parts = line.removePrefix("#").trim().split("\\s+".toRegex())
                for (p in parts) {
                    val kv = p.split("=")
                    if (kv.size == 2) {
                        val k = kv[0].trim()
                        val v = kv[1].trim()
                        when (k) {
                            "unk_id" -> unk = v.toIntOrNull() ?: unk
                            "bos_id" -> bos = v.toIntOrNull() ?: bos
                            "eos_id" -> eos = v.toIntOrNull() ?: eos
                            "pad_id" -> pad = v.toIntOrNull() ?: pad
                            "mask_id" -> mask = v.toIntOrNull() ?: mask
                            "min_score" -> minScore = v.toDoubleOrNull() ?: minScore
                        }
                    }
                }
            } else if (!line.startsWith("#") || line.contains("\t")) {
                val tabIdx = line.indexOf('\t')
                if (tabIdx >= 0) {
                    val piece = line.substring(0, tabIdx)
                    val score = try {
                        java.lang.Double.parseDouble(line.substring(tabIdx + 1))
                    } catch (_: NumberFormatException) {
                        0.0
                    }
                    map[piece] = SmsTokenizer.TokenEntry(currentId, score)
                    if (score < minScore) minScore = score
                    currentId++
                }
            }
            lineIndex++
        }
        reader.close()
        return SmsTokenizer(map, unk, bos, eos, pad, mask, minScore, 128)
    }

    @Test
    fun testFastLoaderMatchesOldLoaderOnFixture() {
        val vocabCandidates = listOf(
            File("../../models/sms_v5q/sms_vocab.txt"),
            File("../models/sms_v5q/sms_vocab.txt"),
            File("models/sms_v5q/sms_vocab.txt"),
            File("src/test/resources/sms_vocab.txt"),
            File("app/src/test/resources/sms_vocab.txt")
        )
        val vocabFile = vocabCandidates.firstOrNull { it.exists() && it.isFile }
        requireNotNull(vocabFile) { "sms_vocab.txt not found for fast-vs-old loader test" }
        val oldTokenizer = loadOldTokenizerFromFile(vocabFile)
        assertEquals(tokenizer.unkId, oldTokenizer.unkId)
        assertEquals(tokenizer.bosId, oldTokenizer.bosId)
        assertEquals(tokenizer.eosId, oldTokenizer.eosId)
        assertEquals(tokenizer.padId, oldTokenizer.padId)
        assertEquals(tokenizer.maskId, oldTokenizer.maskId)
        assertEquals(tokenizer.minScore, oldTokenizer.minScore, 1e-9)
        val total = fixtureArray.length()
        for (i in 0 until total) {
            val text = fixtureArray.getJSONObject(i).getString("text")
            val fast = tokenizer.encode(text)
            val old = oldTokenizer.encode(text)
            assertTrue("Fast vs old loader mismatch at fixture $i", fast.inputIds.contentEquals(old.inputIds))
            assertTrue("Fast vs old loader mask mismatch at fixture $i", fast.attentionMask.contentEquals(old.attentionMask))
        }
    }
}
