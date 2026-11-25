/**
 * Pure Kotlin routine alert bypass filter and sender mismatch cue detector.
 * Mirrored by sentinel/routine_filter.py and strictly verified against Python parity fixtures.
 * Filters genuine routine OTPs and bank transactions from registered DLT business headers.
 */
package org.ps3.sentinel.core

// 320 chars: standard 2-part SMS limit; legitimate routine transaction alerts rarely exceed this.
private const val MAX_CHARS = 320

private val PHONE_GAP = Regex("(?<=\\d)[ -](?=\\d)")
// A mobile or toll-free number, matched only after the gap removal. A plain 10+ digit
// run would also swallow 12-digit UPI references in genuine credit alerts.
private val MOBILE = Regex("(?<!\\d)(?:\\+?91|0)?[6-9]\\d{9}(?!\\d)")
private val TOLL_FREE = Regex("(?<!\\d)18[06]0\\d{7}(?!\\d)")
// A personal number as the sender: digits, spaces and hyphens, with an optional
// leading plus. A DLT header or a short code never matches.
private val SENDER_PHONE = Regex("^\\+?[\\d -]+$")
// The same mobile and toll-free numbers as MOBILE/TOLL_FREE, but matched on the
// original text with single gaps allowed so the cue can carry real offsets.
private val PHONE_SPAN = Regex(
    "(?<!\\d)(?:\\+?91[ -]?|0)?[6-9](?:[ -]?\\d){9}(?!\\d)" +
        "|(?<!\\d)18[06]0(?:[ -]?\\d){7}(?!\\d)"
)
private val OTP = Regex(
    "\\b(?:otp|one[\\s-]?time\\s+pass(?:word|code)|verification\\s+code|login\\s+code)\\b|ओटीपी|ஓடிபி",
    RegexOption.IGNORE_CASE
)
private val CODE = Regex("(?<![\\d,.])\\d{4,8}(?![\\d,.])")
private val MONEY = Regex("(?:\\brs\\.?|\\binr|₹)\\s*[\\d,]+(?:\\.\\d+)?", RegexOption.IGNORE_CASE)
private val MOVED = Regex(
    "\\b(?:debited|credited|withdrawn|spent|deposited|transferred|received|paid)\\b",
    RegexOption.IGNORE_CASE
)
private val ACCOUNT = Regex("\\b(?:a/c|acct?|account|card|upi|wallet)\\b|\\b[xX*]{2,}\\d{2,}", RegexOption.IGNORE_CASE)
// First-person wording marks a person-to-person message, never a bank alert.
private val FIRST_PERSON = Regex("\\b(?:i|my|me)\\b", RegexOption.IGNORE_CASE)
// Words that turn a routine alert into a request: any of these keeps the message in analysis.
private val ASK = Regex(
    "\\b(?:share|send|forward|tell|give|click|update|verify|kyc|blocked|suspend\\w*|expire\\w*|refund|" +
        "reward|won|prize|lottery|install|download|whatsapp|call|dial|contact|ring|missed\\s+call|" +
        "reply|enter|type|provide|confirm|submit|reverse|cancel|pin|mpin|cvv|passcode|" +
        "message|msg|sms|text|quote|validate|revert|reversal|pay|transfer|reach|phone|ping|callback|" +
        "helpline|batao|bhejo|bhej|daalo|dedo)\\b|" +
        "बताएं|शेयर|பகிர",
    RegexOption.IGNORE_CASE
)

private val WEBOTP_TAIL = Regex("\\s*@[\\w.-]+\\s+#\\w+\\s*$")

private fun hasPhoneNumber(text: String): Boolean {
    val flat = PHONE_GAP.replace(text, "")
    return MOBILE.containsMatchIn(flat) || TOLL_FREE.containsMatchIn(flat)
}

/**
 * Evaluates whether message text matches routine OTP or transactional patterns.
 *
 * @param rawText Unprocessed SMS message body.
 * @return "otp", "transaction", or null if the message contains requests, URLs, phone numbers, or anomalies.
 */
fun skipKind(rawText: String): String? {
    // The standard auto-fill ending of a real OTP ("@example.com #123456") is not a link to follow.
    val text = WEBOTP_TAIL.replace(rawText, "")
    if (text.length > MAX_CHARS || extractUrls(text).isNotEmpty() || hasPhoneNumber(text)) {
        return null
    }
    // ponytail: 'do not share' in genuine OTP texts hits ASK and keeps them in analysis;
    // the alert policy handles those. Loosen only with a measured recall check.
    if (ASK.containsMatchIn(text)) {
        return null
    }
    var kind: String? = null
    if (OTP.containsMatchIn(text) && CODE.containsMatchIn(text)) {
        kind = "otp"
    }
    if (kind == null && MONEY.containsMatchIn(text) && MOVED.containsMatchIn(text) && ACCOUNT.containsMatchIn(text)) {
        kind = "transaction"
    }
    if (kind == null) {
        return null
    }
    // A transaction that names a secret code is never routine.
    if (kind == "transaction" && SECRET.containsMatchIn(text)) {
        return null
    }
    // An OTP that also reports money movement is a scam shape, not a routine OTP.
    if (kind == "otp" && MONEY.containsMatchIn(text) && MOVED.containsMatchIn(text)) {
        return null
    }
    return kind
}

private fun isPhoneSender(sender: String): Boolean {
    val trimmed = sender.trim()
    if (trimmed.isEmpty() || !SENDER_PHONE.matches(trimmed)) return false
    return trimmed.count { it.isDigit() } >= 10
}

private fun lastTenDigits(value: String): String = value.filter { it.isDigit() }.takeLast(10)

/**
 * Returns a sender_mismatch cue when a personal number sends a bank-style alert
 * that carries a callback number. Genuine bank alerts arrive from a DLT header,
 * so the same wording never fires there.
 *
 * @param sender Originating SMS address or phone number.
 * @param text Message body to inspect.
 * @return A [CueSpan] marking the mismatched phone number, or null if benign.
 */
fun senderCue(sender: String, text: String): CueSpan? {
    if (!isPhoneSender(sender)) return null
    if (!isBankAlert(text)) return null
    if (FIRST_PERSON.containsMatchIn(text)) return null
    if (!hasPhoneNumber(text)) return null
    val match = PHONE_SPAN.find(text) ?: return null
    // If callback matches the sender's own number, there is no spoofing/mismatch indicator.
    if (lastTenDigits(match.value) == lastTenDigits(sender)) return null
    return CueSpan("sender_mismatch", match.range.first, match.range.last + 1, match.value)
}

/**
 * Checks whether [sender] matches the Indian DLT registered entity header format (XX-XXXXXX).
 *
 * @param sender Originating sender string.
 * @return True if [sender] represents a verified DLT enterprise header.
 */
fun isRegisteredSender(sender: String): Boolean {
    return senderHeader(sender) != null
}

/**
 * Determines whether a message can safely skip heavy ML model evaluation.
 *
 * Requires both a verified DLT registered sender and benign routine message structure.
 *
 * @param sender Originating SMS sender string.
 * @param text SMS message body.
 * @return True if the message is eligible to bypass full inference.
 */
fun shouldSkip(sender: String, text: String): Boolean {
    return isRegisteredSender(sender) && skipKind(text) != null
}
