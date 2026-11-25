/**
 * Pure Kotlin SentencePiece Unigram / Viterbi subword tokenizer for SMS models.
 * Compatible with HuggingFace MiniLM and XLM-RoBERTa multilingual vocabularies.
 * Verified by SmsTokenizerTest and ParityTest.
 */
package org.ps3.sentinel.core

import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.text.Normalizer
import java.util.logging.Logger

/**
 * Container for tensor inputs produced by tokenizing text for the SMS classifier.
 *
 * @property inputIds LongArray of vocabulary token IDs, including special tokens (BOS, EOS, PAD).
 * @property attentionMask LongArray indicating active (1L) vs padding (0L) positions.
 */
data class SmsTokenizerOutput(
    val inputIds: LongArray,
    val attentionMask: LongArray
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as SmsTokenizerOutput
        if (!inputIds.contentEquals(other.inputIds)) return false
        if (!attentionMask.contentEquals(other.attentionMask)) return false
        return true
    }

    override fun hashCode(): Int {
        var result = inputIds.contentHashCode()
        result = 31 * result + attentionMask.contentHashCode()
        return result
    }
}

private class FastVocab(
    val pieceBytes: ByteArray,
    val offsets: IntArray,
    val ids: IntArray,
    val scores: DoubleArray,
    val charLengths: IntArray,
    val pieceHashes: IntArray,
    val table: IntArray,
    val maxPieceLen: Int
)

/**
 * Unigram Viterbi tokenizer implementing subword segmentation for transformer models.
 *
 * @property unkId Unknown token ID (default 3).
 * @property bosId Beginning-of-sequence token ID (default 0).
 * @property eosId End-of-sequence token ID (default 2).
 * @property padId Padding token ID (default 1).
 * @property maskId Mask token ID (default 250001).
 * @property minScore Minimum Unigram log-probability score in the vocabulary.
 * @property maxLength Maximum token sequence length (default 128).
 */
class SmsTokenizer(
    private val vocabMap: Map<String, TokenEntry>,
    val unkId: Int = 3,
    val bosId: Int = 0,
    val eosId: Int = 2,
    val padId: Int = 1,
    val maskId: Int = 250001,
    val minScore: Double = -20.36475182,
    val maxLength: Int = 128
) {
    /** Vocabulary record associating a token piece ID with its Unigram log-likelihood score. */
    data class TokenEntry(val id: Int, val score: Double)

    private var fastVocab: FastVocab? = null
    private var fastMaxPieceLen: Int? = null
    private val maxPieceLen: Int by lazy {
        fastMaxPieceLen ?: (vocabMap.keys.maxOfOrNull { it.length } ?: 16)
    }
    private val unkScore: Double = minScore - 10.0

    /**
     * Constructs a tokenizer by loading a text vocabulary file from [vocabPath].
     *
     * @param vocabPath Path to the tab-separated vocabulary file.
     * @param maxLength Sequence length limit for encoded tensors.
     */
    constructor(vocabPath: String, maxLength: Int = 128) : this(
        loadVocab(File(vocabPath)),
        maxLength = maxLength
    )

    private constructor(builder: VocabData, maxLength: Int) : this(
        vocabMap = builder.vocabMap,
        unkId = builder.unkId,
        bosId = builder.bosId,
        eosId = builder.eosId,
        padId = builder.padId,
        maskId = builder.maskId,
        minScore = builder.minScore,
        maxLength = maxLength
    )

    private constructor(builder: VocabData, fast: FastVocab, maxLength: Int) : this(
        vocabMap = emptyMap(),
        unkId = builder.unkId,
        bosId = builder.bosId,
        eosId = builder.eosId,
        padId = builder.padId,
        maskId = builder.maskId,
        minScore = builder.minScore,
        maxLength = maxLength
    ) {
        this.fastVocab = fast
        this.fastMaxPieceLen = fast.maxPieceLen
    }

    /** Factory methods and binary cache persistence for [SmsTokenizer]. */
    companion object {
        /**
         * Loads a tokenizer from [file], reading from or writing to binary cache in [cacheDir] if provided.
         *
         * @param file Source vocabulary file.
         * @param maxLength Sequence length limit.
         * @param cacheDir Optional directory for caching binary vocab tables.
         * @return Initialized [SmsTokenizer].
         */
        fun fromFile(file: File, maxLength: Int = 128, cacheDir: File? = null): SmsTokenizer {
            if (cacheDir != null) {
                val cached = tryLoadCache(file, cacheDir, maxLength)
                if (cached != null) return cached
                val data = loadVocab(file)
                val tokenizer = SmsTokenizer(data, maxLength)
                try {
                    val fast = buildFastVocab(data.vocabMap)
                    if (fast != null) writeCache(file, cacheDir, data, fast)
                } catch (_: Exception) {
                }
                return tokenizer
            }
            return SmsTokenizer(loadVocab(file), maxLength)
        }

        /**
         * Loads a tokenizer from an open vocabulary [stream].
         *
         * @param stream Input stream containing vocabulary entries.
         * @param maxLength Sequence length limit.
         * @return Initialized [SmsTokenizer].
         */
        fun fromStream(stream: InputStream, maxLength: Int = 128): SmsTokenizer {
            return SmsTokenizer(loadVocabFromStream(stream), maxLength)
        }

        private class VocabData(
            val vocabMap: Map<String, TokenEntry>,
            val unkId: Int,
            val bosId: Int,
            val eosId: Int,
            val padId: Int,
            val maskId: Int,
            val minScore: Double
        )

        private fun loadVocab(file: File): VocabData {
            return loadVocabFromBytes(file.readBytes())
        }

        private fun loadVocabFromStream(stream: InputStream): VocabData {
            return loadVocabFromBytes(stream.readBytes())
        }

        private fun parseHeader(
            data: ByteArray,
            start: Int,
            end: Int,
            current: VocabData,
        ): VocabData {
            var unk = current.unkId
            var bos = current.bosId
            var eos = current.eosId
            var pad = current.padId
            var mask = current.maskId
            var minScore = current.minScore
            var p = start
            while (p < end) {
                while (p < end && (data[p] == 0x20.toByte() || data[p] == 0x09.toByte() || data[p] == 0x0D.toByte())) {
                    p++
                }
                if (p >= end) break
                val tokenStart = p
                while (p < end && data[p] != 0x20.toByte() && data[p] != 0x09.toByte() && data[p] != 0x0D.toByte()) {
                    p++
                }
                val tokenEnd = p
                var eq = -1
                var secondEq = -1
                for (j in tokenStart until tokenEnd) {
                    if (data[j] == 0x3D.toByte()) {
                        if (eq == -1) eq = j else secondEq = j
                    }
                }
                if (eq == -1 || secondEq != -1) continue
                val key = String(data, tokenStart, eq - tokenStart, Charsets.UTF_8).trim()
                val value = String(data, eq + 1, tokenEnd - eq - 1, Charsets.UTF_8).trim()
                when (key) {
                    "unk_id" -> unk = value.toIntOrNull() ?: unk
                    "bos_id" -> bos = value.toIntOrNull() ?: bos
                    "eos_id" -> eos = value.toIntOrNull() ?: eos
                    "pad_id" -> pad = value.toIntOrNull() ?: pad
                    "mask_id" -> mask = value.toIntOrNull() ?: mask
                    "min_score" -> minScore = value.toDoubleOrNull() ?: minScore
                }
            }
            return VocabData(current.vocabMap, unk, bos, eos, pad, mask, minScore)
        }

        private fun loadVocabFromBytes(data: ByteArray): VocabData {
            val map = HashMap<String, TokenEntry>(260000)
            var unk = 3
            var bos = 0
            var eos = 2
            var pad = 1
            var mask = 250001
            var minScore = 0.0
            var currentId = 0
            var lineIndex = 0
            var lineStart = 0
            var i = 0
            val n = data.size
            while (i <= n) {
                if (i == n || data[i] == 0x0A.toByte()) {
                    var lineEnd = i
                    if (lineEnd > lineStart && data[lineEnd - 1] == 0x0D.toByte()) {
                        lineEnd--
                    }
                    val isLastEmptyAfterTrailingNewline = lineStart == n && n > 0 && data[n - 1] == 0x0A.toByte()
                    if (!isLastEmptyAfterTrailingNewline && lineStart < lineEnd) {
                        val first = data[lineStart]
                        if (lineIndex == 0 && first == 0x23.toByte()) {
                            val header = parseHeader(data, lineStart + 1, lineEnd, VocabData(map, unk, bos, eos, pad, mask, minScore))
                            unk = header.unkId
                            bos = header.bosId
                            eos = header.eosId
                            pad = header.padId
                            mask = header.maskId
                            minScore = header.minScore
                        } else {
                            var tabIdx = -1
                            for (j in lineStart until lineEnd) {
                                if (data[j] == 0x09.toByte()) {
                                    tabIdx = j
                                    break
                                }
                            }
                            val isCommentWithoutTab = first == 0x23.toByte() && tabIdx == -1
                            if (!isCommentWithoutTab && tabIdx != -1) {
                                val pieceLen = tabIdx - lineStart
                                val piece = String(data, lineStart, pieceLen, Charsets.UTF_8)
                                val score = String(data, tabIdx + 1, lineEnd - tabIdx - 1, Charsets.UTF_8).toDoubleOrNull() ?: 0.0
                                map[piece] = TokenEntry(currentId, score)
                                if (score < minScore) {
                                    minScore = score
                                }
                                currentId++
                            }
                        }
                    }
                    lineStart = i + 1
                    lineIndex++
                }
                i++
            }
            return VocabData(map, unk, bos, eos, pad, mask, minScore)
        }

        private const val CACHE_MAGIC = 0x534D5331
        private const val CACHE_VERSION = 2
        private const val CACHE_SUFFIX = ".bin"
        private val cleanupLogger: Logger = Logger.getLogger("PS3Sms")

        // A vocab file's size and mtime are part of the cache name, so every
        // vocab update leaves the previous cache behind. Deleting the others in
        // the same directory keeps the two 10.7 MB copies from accumulating.
        private fun deleteOtherCaches(cacheDir: File, current: File, base: String) {
            val prefix = "${base}_"
            val others = cacheDir.listFiles { file ->
                file.isFile && file.name != current.name &&
                    file.name.startsWith(prefix) && file.name.endsWith(CACHE_SUFFIX)
            } ?: return
            for (file in others) {
                try {
                    if (!file.delete()) {
                        cleanupLogger.warning("SmsTokenizer: could not delete stale cache ${file.name}")
                    }
                } catch (e: Exception) {
                    cleanupLogger.warning(
                        "SmsTokenizer: failed to delete stale cache ${file.name}: ${e.message}"
                    )
                }
            }
        }

        private fun buildFastVocab(vocabMap: Map<String, TokenEntry>): FastVocab? {
            if (vocabMap.isEmpty()) return null
            val n = vocabMap.size
            var minId = Int.MAX_VALUE
            var maxId = Int.MIN_VALUE
            for (e in vocabMap.values) {
                if (e.id < minId) minId = e.id
                if (e.id > maxId) maxId = e.id
            }
            val dense = minId == 0 && maxId == n - 1
            val pieces = Array<String?>(n) { null }
            val ids = IntArray(n)
            val scores = DoubleArray(n)
            if (dense) {
                for ((piece, entry) in vocabMap) {
                    pieces[entry.id] = piece
                    ids[entry.id] = entry.id
                    scores[entry.id] = entry.score
                }
                var i = 0
                while (i < n) {
                    if (pieces[i] == null) return null
                    i++
                }
            } else {
                val sorted = vocabMap.entries.sortedBy { it.value.id }
                for (i in 0 until n) {
                    pieces[i] = sorted[i].key
                    ids[i] = sorted[i].value.id
                    scores[i] = sorted[i].value.score
                }
            }
            val charLengths = IntArray(n)
            val pieceHashes = IntArray(n)
            var maxLen = 0
            for (i in 0 until n) {
                val p = pieces[i]!!
                charLengths[i] = p.length
                pieceHashes[i] = p.hashCode()
                if (p.length > maxLen) maxLen = p.length
            }
            val offsets = IntArray(n + 1)
            val out = ByteArrayOutputStream()
            for (i in 0 until n) {
                offsets[i] = out.size()
                out.write(pieces[i]!!.toByteArray(Charsets.UTF_8))
            }
            offsets[n] = out.size()
            val pieceBytes = out.toByteArray()
            var cap = 1
            while (cap < n * 2) cap *= 2
            if (cap < 16) cap = 16
            val table = IntArray(cap) { -1 }
            val mask = cap - 1
            for (pos in 0 until n) {
                var idx = pieceHashes[pos] and mask
                while (table[idx] != -1) {
                    idx = (idx + 1) and mask
                }
                table[idx] = pos
            }
            return FastVocab(
                pieceBytes = pieceBytes,
                offsets = offsets,
                ids = ids,
                scores = scores,
                charLengths = charLengths,
                pieceHashes = pieceHashes,
                table = table,
                maxPieceLen = maxLen
            )
        }

        private fun writeCache(vocabFile: File, cacheDir: File, data: VocabData, fast: FastVocab) {
            val size = vocabFile.length()
            val mtime = vocabFile.lastModified()
            val base = vocabFile.nameWithoutExtension.ifEmpty { "sms_vocab" }
            val cacheFile = File(cacheDir, "${base}_${size}_${mtime}$CACHE_SUFFIX")
            val tmpFile = File(cacheDir, cacheFile.name + ".tmp")
            try {
                if (!cacheDir.exists()) cacheDir.mkdirs()
            } catch (_: Exception) {
            }
            deleteOtherCaches(cacheDir, cacheFile, base)
            try {
                DataOutputStream(BufferedOutputStream(FileOutputStream(tmpFile))).use { out ->
                    out.writeInt(CACHE_MAGIC)
                    out.writeInt(CACHE_VERSION)
                    out.writeLong(size)
                    out.writeLong(mtime)
                    out.writeInt(fast.ids.size)
                    out.writeInt(fast.maxPieceLen)
                    out.writeInt(data.unkId)
                    out.writeInt(data.bosId)
                    out.writeInt(data.eosId)
                    out.writeInt(data.padId)
                    out.writeInt(data.maskId)
                    out.writeDouble(data.minScore)
                    out.writeInt(fast.pieceBytes.size)
                    for (v in fast.offsets) out.writeInt(v)
                    out.write(fast.pieceBytes)
                    for (v in fast.ids) out.writeInt(v)
                    for (v in fast.scores) out.writeDouble(v)
                    for (v in fast.charLengths) out.writeInt(v)
                    for (v in fast.pieceHashes) out.writeInt(v)
                    out.writeInt(fast.table.size)
                    for (v in fast.table) out.writeInt(v)
                    out.flush()
                }
                if (cacheFile.exists()) cacheFile.delete()
                if (!tmpFile.renameTo(cacheFile)) {
                    try {
                        tmpFile.delete()
                    } catch (_: Exception) {
                    }
                }
            } catch (_: Exception) {
                try {
                    tmpFile.delete()
                } catch (_: Exception) {
                }
            }
        }

        private fun tryLoadCache(vocabFile: File, cacheDir: File, maxLength: Int): SmsTokenizer? {
            return try {
                val size = vocabFile.length()
                val mtime = vocabFile.lastModified()
                val base = vocabFile.nameWithoutExtension.ifEmpty { "sms_vocab" }
                val cacheFile = File(cacheDir, "${base}_${size}_${mtime}$CACHE_SUFFIX")
                deleteOtherCaches(cacheDir, cacheFile, base)
                if (!cacheFile.isFile) return null
                DataInputStream(BufferedInputStream(FileInputStream(cacheFile))).use { input ->
                    val magic = input.readInt()
                    if (magic != CACHE_MAGIC) return null
                    val version = input.readInt()
                    if (version != CACHE_VERSION) return null
                    val vocabSize = input.readLong()
                    val vocabMtime = input.readLong()
                    if (vocabSize != size || vocabMtime != mtime) return null
                    val count = input.readInt()
                    if (count <= 0 || count > 1000000) return null
                    val maxPieceLen = input.readInt()
                    if (maxPieceLen <= 0 || maxPieceLen > 10000) return null
                    val unkId = input.readInt()
                    val bosId = input.readInt()
                    val eosId = input.readInt()
                    val padId = input.readInt()
                    val maskId = input.readInt()
                    val minScore = input.readDouble()
                    val totalBytes = input.readInt()
                    if (totalBytes < 0 || totalBytes > 50000000) return null
                    val offsets = IntArray(count + 1)
                    for (i in 0..count) offsets[i] = input.readInt()
                    if (offsets[0] != 0 || offsets[count] != totalBytes) return null
                    for (i in 1..count) {
                        if (offsets[i] < offsets[i - 1]) return null
                    }
                    val pieceBytes = ByteArray(totalBytes)
                    input.readFully(pieceBytes)
                    val ids = IntArray(count)
                    for (i in 0 until count) ids[i] = input.readInt()
                    val scores = DoubleArray(count)
                    for (i in 0 until count) scores[i] = input.readDouble()
                    val charLengths = IntArray(count)
                    for (i in 0 until count) {
                        val v = input.readInt()
                        if (v < 0 || v > 10000) return null
                        charLengths[i] = v
                    }
                    val pieceHashes = IntArray(count)
                    for (i in 0 until count) pieceHashes[i] = input.readInt()
                    val tableSize = input.readInt()
                    if (tableSize < count || tableSize > 8000000) return null
                    if ((tableSize and (tableSize - 1)) != 0) return null
                    val table = IntArray(tableSize)
                    for (i in 0 until tableSize) {
                        val v = input.readInt()
                        if (v != -1 && (v < 0 || v >= count)) return null
                        table[i] = v
                    }
                    val fast = FastVocab(
                        pieceBytes = pieceBytes,
                        offsets = offsets,
                        ids = ids,
                        scores = scores,
                        charLengths = charLengths,
                        pieceHashes = pieceHashes,
                        table = table,
                        maxPieceLen = maxPieceLen
                    )
                    val data = VocabData(emptyMap(), unkId, bosId, eosId, padId, maskId, minScore)
                    SmsTokenizer(data, fast, maxLength)
                }
            } catch (_: Exception) {
                null
            }
        }
    }

    /**
     * Normalizes raw text using NFKC normalization and whitespace sanitization.
     *
     * Replaces invisible whitespace and control characters with spaces before
     * and after Unicode NFKC normalization.
     *
     * @param text Raw input string.
     * @return Cleaned, normalized string ready for pre-tokenization.
     */
    fun normalize(text: String): String {
        val cleaned = replaceWhitespaceChars(text)
        val nfkc = Normalizer.normalize(cleaned, Normalizer.Form.NFKC)
        return replaceWhitespaceChars(nfkc)
    }

    // Replaces zero-width, directional, and special whitespace characters with standard spaces,
    // and strips application program command characters (\u009F).
    private fun replaceWhitespaceChars(s: String): String {
        val sb = StringBuilder(s.length)
        for (i in s.indices) {
            val c = s[i]
            when (c) {
                '\u009F' -> { }
                '\t', '\n', '\r', '\u000c',
                '\u200b', '\u200c', '\u200d', '\u200e', '\u200f', '\ufeff',
                '\uFFFD' -> sb.append(' ')
                else -> sb.append(c)
            }
        }
        return sb.toString()
    }

    /**
     * Splits normalized text on whitespace into words prefixed with SentencePiece meta-symbol (U+2581).
     *
     * @param normalizedText Pre-normalized text string.
     * @return List of word pieces with leading lower-one-eighth block characters.
     */
    fun preTokenize(normalizedText: String): List<String> {
        val result = mutableListOf<String>()
        var start = 0
        val len = normalizedText.length
        while (start < len) {
            while (start < len && Character.isWhitespace(normalizedText[start])) {
                start++
            }
            if (start >= len) break
            var end = start
            while (end < len && !Character.isWhitespace(normalizedText[end])) {
                end++
            }
            val word = normalizedText.substring(start, end)
            result.add("\u2581$word")
            start = end
        }
        return result
    }

    // Epsilon tie-breaker for floating-point comparison during Viterbi dynamic programming.
    private val viterbiEps: Double = 1e-7

    // Viterbi dynamic programming segmentation using open-addressing hash table in flat arrays
    // to avoid per-node allocations on mobile devices.
    private fun viterbiTokenizePieceFast(piece: String, fast: FastVocab): List<Int> {
        val n = piece.length
        if (n == 0) return emptyList()
        val bestScore = DoubleArray(n + 1) { Double.NEGATIVE_INFINITY }
        val bestPrev = IntArray(n + 1) { -1 }
        val bestId = IntArray(n + 1) { -1 }
        bestScore[0] = 0.0
        val cap = fast.table.size
        val mask = cap - 1
        for (i in 0 until n) {
            if (bestScore[i] == Double.NEGATIVE_INFINITY) continue
            val charLen = if (Character.isHighSurrogate(piece[i]) && i + 1 < n && Character.isLowSurrogate(piece[i + 1])) 2 else 1
            var hasSingleNode = false
            val maxL = minOf(maxPieceLen, n - i)
            var rolling = 0
            for (len in 1..maxL) {
                rolling = 31 * rolling + piece[i + len - 1].code
                var idx = rolling and mask
                var foundPos = -1
                var probes = 0
                while (probes < cap) {
                    val pos = fast.table[idx]
                    if (pos == -1) break
                    if (fast.pieceHashes[pos] == rolling && fast.charLengths[pos] == len) {
                        var equal = true
                        val stored = String(fast.pieceBytes, fast.offsets[pos], fast.offsets[pos + 1] - fast.offsets[pos], Charsets.UTF_8)
                        if (stored.length != len) {
                            equal = false
                        } else {
                            var k = 0
                            while (k < len) {
                                if (stored[k] != piece[i + k]) {
                                    equal = false
                                    break
                                }
                                k++
                            }
                        }
                        if (equal) {
                            foundPos = pos
                            break
                        }
                    }
                    idx = (idx + 1) and mask
                    probes++
                }
                if (foundPos != -1) {
                    val s = bestScore[i] + fast.scores[foundPos]
                    if (s > bestScore[i + len] + viterbiEps) {
                        bestScore[i + len] = s
                        bestPrev[i + len] = i
                        bestId[i + len] = fast.ids[foundPos]
                    }
                    if (!hasSingleNode && len == charLen) {
                        hasSingleNode = true
                    }
                }
            }
            if (!hasSingleNode) {
                val s = bestScore[i] + unkScore
                if (s > bestScore[i + charLen] + viterbiEps) {
                    bestScore[i + charLen] = s
                    bestPrev[i + charLen] = i
                    bestId[i + charLen] = unkId
                }
            }
        }
        var curr = n
        val wordIds = mutableListOf<Int>()
        while (curr > 0) {
            val p = bestPrev[curr]
            wordIds.add(bestId[curr])
            curr = p
        }
        wordIds.reverse()
        val fused = mutableListOf<Int>()
        for (id in wordIds) {
            if (id == unkId && fused.isNotEmpty() && fused.last() == unkId) {
                continue
            }
            fused.add(id)
        }
        return fused
    }

    // Fallback Viterbi token segmentation using HashMap lookup when flat array cache is unavailable.
    private fun viterbiTokenizePiece(piece: String): List<Int> {
        val fast = fastVocab
        if (fast != null) return viterbiTokenizePieceFast(piece, fast)
        val n = piece.length
        if (n == 0) return emptyList()

        val bestScore = DoubleArray(n + 1) { Double.NEGATIVE_INFINITY }
        val bestPrev = IntArray(n + 1) { -1 }
        val bestId = IntArray(n + 1) { -1 }
        bestScore[0] = 0.0

        for (i in 0 until n) {
            if (bestScore[i] == Double.NEGATIVE_INFINITY) continue

            val charLen = if (Character.isHighSurrogate(piece[i]) && i + 1 < n && Character.isLowSurrogate(piece[i + 1])) 2 else 1
            var hasSingleNode = false
            val maxL = minOf(maxPieceLen, n - i)

            for (len in 1..maxL) {
                val sub = piece.substring(i, i + len)
                val entry = vocabMap[sub]
                if (entry != null) {
                    val s = bestScore[i] + entry.score
                    if (s > bestScore[i + len] + viterbiEps) {
                        bestScore[i + len] = s
                        bestPrev[i + len] = i
                        bestId[i + len] = entry.id
                    }
                    if (!hasSingleNode && len == charLen) {
                        hasSingleNode = true
                    }
                }
            }

            if (!hasSingleNode) {
                val s = bestScore[i] + unkScore
                if (s > bestScore[i + charLen] + viterbiEps) {
                    bestScore[i + charLen] = s
                    bestPrev[i + charLen] = i
                    bestId[i + charLen] = unkId
                }
            }
        }

        var curr = n
        val wordIds = mutableListOf<Int>()
        while (curr > 0) {
            val p = bestPrev[curr]
            wordIds.add(bestId[curr])
            curr = p
        }
        wordIds.reverse()

        // Collapse adjacent unknown token IDs to match SentencePiece behavior.
        val fused = mutableListOf<Int>()
        for (id in wordIds) {
            if (id == unkId && fused.isNotEmpty() && fused.last() == unkId) {
                continue
            }
            fused.add(id)
        }
        return fused
    }

    /**
     * Tokenizes raw text into SentencePiece vocabulary IDs.
     *
     * Chains normalization, whitespace pre-tokenization, and Viterbi segmentation.
     *
     * @param text Raw input text.
     * @return List of vocabulary token IDs.
     */
    fun tokenize(text: String): List<Int> {
        val normalized = normalize(text)
        val pieces = preTokenize(normalized)
        val tokens = mutableListOf<Int>()
        for (p in pieces) {
            tokens.addAll(viterbiTokenizePiece(p))
        }
        return tokens
    }

    /**
     * Encodes raw text into model input IDs and an attention mask.
     *
     * Prepends BOS token, appends EOS token, truncates to [maxLength] - 2, and optionally
     * pads to [maxLength] with [padId].
     *
     * @param text Raw input text to encode.
     * @param pad Whether to pad output arrays to [maxLength].
     * @return [SmsTokenizerOutput] containing input IDs and attention mask arrays.
     */
    fun encode(text: String, pad: Boolean = true): SmsTokenizerOutput {
        val tokens = tokenize(text)

        // Reserve 2 slots for BOS and EOS tokens.
        val maxSeqLen = maxOf(0, maxLength - 2)
        val truncatedTokens = if (tokens.size > maxSeqLen) {
            tokens.subList(0, maxSeqLen)
        } else {
            tokens
        }

        val totalLen = truncatedTokens.size + 2
        val targetLen = if (pad) maxLength else totalLen
        val inputIds = LongArray(targetLen) { padId.toLong() }
        val attentionMask = LongArray(targetLen) { 0L }

        inputIds[0] = bosId.toLong()
        attentionMask[0] = 1L

        for (i in truncatedTokens.indices) {
            inputIds[1 + i] = truncatedTokens[i].toLong()
            attentionMask[1 + i] = 1L
        }

        inputIds[totalLen - 1] = eosId.toLong()
        attentionMask[totalLen - 1] = 1L

        return SmsTokenizerOutput(inputIds, attentionMask)
    }
}
