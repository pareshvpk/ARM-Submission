/**
 * Pure Kotlin character vocabulary encoder for the 1D CNN URL classifier.
 * Encodes normalized URLs into fixed-length integer tensor buffers with padding and truncation.
 * Tested by UrlEncoderTest.
 */
package org.ps3.sentinel.core

import org.json.JSONObject
import java.io.File

/**
 * Character-level tokenizer that maps characters in normalized URLs to token ID sequences.
 *
 * @property pad Token ID used to pad sequences shorter than [maxLen].
 * @property unk Token ID used for characters absent from [chars].
 * @property maxLen Maximum sequence length of the encoded tensor buffer.
 * @property chars Mapping from characters to their assigned token IDs.
 */
class UrlEncoder(
    val pad: Long = 0L,
    val unk: Long = 1L,
    val maxLen: Int = 200,
    val chars: Map<Char, Long> = emptyMap()
) {
    /** Factory methods for constructing [UrlEncoder] from JSON vocabularies. */
    companion object {
        /**
         * Parses a JSON string containing vocabulary mappings and parameters into a [UrlEncoder].
         *
         * @param jsonStr JSON string with 'chars' map, 'pad', 'unk', and 'max_len'.
         * @return Initialized [UrlEncoder] instance.
         */
        fun fromJson(jsonStr: String): UrlEncoder {
            val root = JSONObject(jsonStr)
            val pad = root.optLong("pad", 0L)
            val unk = root.optLong("unk", 1L)
            val maxLen = root.optInt("max_len", 200)

            val charsMap = mutableMapOf<Char, Long>()
            val charsObj = root.optJSONObject("chars")
            if (charsObj != null) {
                val keys = charsObj.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    if (key.isNotEmpty()) {
                        charsMap[key[0]] = charsObj.getLong(key)
                    }
                }
            }

            return UrlEncoder(
                pad = pad,
                unk = unk,
                maxLen = maxLen,
                chars = charsMap
            )
        }

        /**
         * Loads character vocabulary configuration from a JSON file.
         *
         * @param file The JSON vocabulary file to read.
         * @return Initialized [UrlEncoder] instance.
         */
        fun fromFile(file: File): UrlEncoder {
            return fromJson(file.readText(Charsets.UTF_8))
        }
    }

    /**
     * Encodes a pre-normalized URL string into a fixed-length token ID buffer.
     *
     * @param normUrl Canonical normalized URL string.
     * @return [LongArray] of size [maxLen] containing token IDs, right-padded with [pad].
     */
    fun encode(normUrl: String): LongArray {
        // Pre-fill the buffer with pad ID so trailing entries need no extra pass.
        val result = LongArray(maxLen) { pad }
        var offset = 0
        var index = 0
        while (index < maxLen && offset < normUrl.length) {
            val codePoint = normUrl.codePointAt(offset)
            // Characters outside the Basic Multilingual Plane (> 0xFFFF) map directly to unk.
            val c = if (codePoint < 0x10000) codePoint.toChar() else null
            result[index] = if (c != null) (chars[c] ?: unk) else unk
            offset += Character.charCount(codePoint)
            index++
        }
        return result
    }

    /**
     * Normalizes a raw URL and encodes it into a fixed-length token ID buffer.
     *
     * @param rawUrl Raw URL string before normalization.
     * @return [LongArray] of size [maxLen] containing token IDs, right-padded with [pad].
     */
    fun encodeUrl(rawUrl: String): LongArray {
        return encode(normaliseUrl(rawUrl))
    }
}
