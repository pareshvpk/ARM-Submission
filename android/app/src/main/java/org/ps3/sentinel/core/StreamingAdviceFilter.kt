/**
 * Pure Kotlin token buffer for on-device streaming LLM advice.
 * Holds streamed tokens and releases complete sentences only after validation against safety guards.
 * Verified by StreamingAdviceFilterTest.
 */
package org.ps3.sentinel.core

/**
 * Purpose:  Holds generated tokens until each sentence passes the guard.
 * Owns:     The pending token buffer for one generation.
 * Lifetime: Screen
 * Thread:   any — methods are synchronized.
 *
 * @param evidence Structured evidence used by safety guards to evaluate generated advice.
 */
class StreamingAdviceFilter(private val evidence: Evidence) {

    private var buffer: String = ""
    private var fullRaw: String = ""

    /**
     * Appends a newly generated token and yields any completed, validated sentences.
     *
     * @param token The next token emitted by the language model.
     * @return Zero or more validated sentences with leading separators ready for UI display.
     */
    @Synchronized
    fun onToken(token: String): String {
        if (token.isEmpty()) {
            return ""
        }
        fullRaw += token
        buffer += token
        val display = StringBuilder()
        while (true) {
            val sepEnd = buffer.indexOfFirst { !it.isWhitespace() }
            if (sepEnd < 0) {
                break
            }
            // Retain leading whitespace/newlines before the sentence to preserve UI paragraph spacing.
            val separator = buffer.substring(0, sepEnd)
            val rest = buffer.substring(sepEnd)
            val end = findSentenceEnd(rest)
            if (end < 0) {
                break
            }
            val sentence = rest.substring(0, end + 1)
            buffer = rest.substring(end + 1)
            if (passes(sentence)) {
                display.append(separator)
                display.append(sentence)
            }
        }
        return display.toString()
    }

    /**
     * Flushes and completes advice generation, evaluating all accumulated tokens with full-text guards.
     *
     * @return Guarded full advice string including fallback or template steps if needed.
     */
    @Synchronized
    fun finish(): String = guard(fullRaw, evidence).first

    private fun passes(sentence: String): Boolean {
        val (_, flags) = guard(sentence, evidence)
        if ("refusal_fallback" in flags) {
            return false
        }
        if ("contradiction_fallback" in flags) {
            return false
        }
        if ("empty_fallback" in flags) {
            return false
        }
        // Reusing guard() per sentence handles the click, callback and threat
        // filters without copying them; a dropped sentence also yields the
        // template fallback, so the sentence is suppressed.
        if (flags.any { it.startsWith("dropped_") }) {
            return false
        }
        return true
    }

    private fun findSentenceEnd(text: String): Int {
        for (index in text.indices) {
            val current = text[index]
            if (current == '\n') {
                return index
            }
            if (isSentenceTerminator(current, text, index)) {
                return index
            }
        }
        return -1
    }

    private fun isSentenceTerminator(current: Char, text: String, index: Int): Boolean {
        if (current != '.' && current != '!' && current != '?') {
            return false
        }
        if (index == 0) {
            return false
        }
        val prev = text[index - 1]
        if (prev.isLetter()) {
            if (index == text.length - 1) {
                return true
            }
            return text[index + 1].isWhitespace()
        }
        if (prev.isDigit()) {
            // Numbered steps start with a digit dot ("1.") but end with a
            // digit dot after the words, so only the later dot ends a sentence.
            val hasWord = text.substring(0, index).any { it.isLetter() }
            if (!hasWord) {
                return false
            }
            if (index == text.length - 1) {
                return true
            }
            return text[index + 1].isWhitespace()
        }
        return false
    }
}
