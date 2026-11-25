/**
 * Pure Kotlin multi-signal fusion and risk calculation engine.
 * Combines SMS classifier outputs, URL scoring, and cue patterns into consolidated Evidence.
 * Mirrored by sentinel/fusion.py and validated by ParityTest and FusionTest.
 */
package org.ps3.sentinel.core

import java.io.BufferedReader
import java.io.File
import java.io.InputStream
import java.io.InputStreamReader
import java.math.BigDecimal
import java.math.RoundingMode
import java.util.Locale
import kotlin.math.exp
import kotlin.math.ln

/**
 * Process-wide registry of legitimate organization and institution domain names.
 * Not synchronized: it is filled once while the app starts, before any message is analysed.
 * Loaded from trusted_domains.txt during initialization.
 */
object TrustedDomainStore {
    private val domains = mutableSetOf<String>()

    /**
     * Replaces the currently trusted domain set with [newDomains].
     *
     * @param newDomains Set of domain strings to trust.
     */
    fun setDomains(newDomains: Set<String>) {
        domains.clear()
        domains.addAll(newDomains.map { it.lowercase().trim() })
    }

    /**
     * Loads trusted domain names from an input stream, ignoring blank lines and comments ('#').
     *
     * @param inputStream Stream containing newline-separated domain entries.
     */
    fun loadFromStream(inputStream: InputStream) {
        val set = mutableSetOf<String>()
        BufferedReader(InputStreamReader(inputStream, Charsets.UTF_8)).useLines { lines ->
            for (line in lines) {
                val trimmed = line.trim().lowercase()
                if (trimmed.isNotEmpty() && !trimmed.startsWith("#")) {
                    set.add(trimmed)
                }
            }
        }
        setDomains(set)
    }

    /**
     * Loads trusted domain names from a line-delimited text file.
     *
     * @param file Text file containing domain entries.
     */
    fun loadFromFile(file: File) {
        if (file.exists()) {
            val set = mutableSetOf<String>()
            file.forEachLine(Charsets.UTF_8) { line ->
                val trimmed = line.trim().lowercase()
                if (trimmed.isNotEmpty() && !trimmed.startsWith("#")) {
                    set.add(trimmed)
                }
            }
            setDomains(set)
        }
    }

    /**
     * Returns an unmodifiable snapshot of currently registered trusted domain names.
     *
     * @return Set of lowercase trusted domain strings.
     */
    fun getDomains(): Set<String> = domains
}

// Readable evidence wording for cue types that are not named by their rule key.
private const val SENDER_MISMATCH_INDICATOR = "bank-style alert sent from a personal mobile number"
private const val BANK_ALERT_CREDENTIAL_INDICATOR = "bank alert asking for a secret code"

// The shared bank-alert shape: an amount, a debit/credit verb and a bank account marker.
private val BANK_ALERT_MONEY = Regex("(?:\\brs\\.?|\\binr|₹)\\s*[\\d,]+(?:\\.\\d+)?", RegexOption.IGNORE_CASE)
private val BANK_ALERT_MOVED = Regex(
    "\\b(?:debited|debit|credited|withdrawn|spent|transferred|received|deposited|paid)\\b",
    RegexOption.IGNORE_CASE
)
private val BANK_ALERT_ACCOUNT = Regex(
    "\\b(?:a/c|acct)\\b|[xX*]{2,}\\d{2,}|\\byour\\s+(?:a/c|acct|account|card)\\b",
    RegexOption.IGNORE_CASE
)

/** True when the text reads like a real bank debit/credit alert. */
fun isBankAlert(text: String): Boolean =
    BANK_ALERT_MONEY.containsMatchIn(text) &&
        BANK_ALERT_MOVED.containsMatchIn(text) &&
        BANK_ALERT_ACCOUNT.containsMatchIn(text)

// Clause-level secret request: a secret word plus an ask to transmit it, in the same clause.
val SECRET = Regex("\\b(?:otp|pin|mpin|cvv|passcode|password|code)\\b", RegexOption.IGNORE_CASE)
private val NEG = Regex(
    "\\b(?:never|not|don'?t|nobody|nothing|no\\s+one|no-one|none|neither|nor|mat|kabhi|nahi|nahin|na)\\b",
    RegexOption.IGNORE_CASE
)
private val EN_SEND = Regex(
    "\\b(?:reply|send|share|provide|give|tell|quote|forward|read|spell|repeat|dictate|reveal|disclose|inform|mention|show)\\b",
    RegexOption.IGNORE_CASE
)
private val HI_SEND = Regex(
    "\\b(?:batao|bata|bataye|bataiye|bhejo|bhej|bhejiye|daalo|daal|dedo|de)\\b",
    RegexOption.IGNORE_CASE
)
private val CHANNEL_SEND = Regex(
    "\\b(?:message|msg|sms|text|whatsapp)\\s+(?:(?:your|the|us|me|that|this)\\s+)?(?:otp|pin|mpin|cvv|passcode|password|(?:\\d[\\s-]?digit\\s+)?code)\\b",
    RegexOption.IGNORE_CASE
)
private val DEMAND = Regex(
    "\\b(?:enter|type|validate|confirm|submit|use|needed|required|mandatory)\\b",
    RegexOption.IGNORE_CASE
)
private val PURPOSE = Regex(
    "\\b(?:reverse|revert|reversal|cancel|stop|block|unblock|hold|prevent|" +
        "reactivate|activate|refund|avoid)\\b",
    RegexOption.IGNORE_CASE
)
private val STRONG_SECRET = Regex(
    "\\b(?:otp|pin|mpin|cvv|passcode|password)\\b|" +
        "\\b(?:verification|security|secret|otp|digit|one[\\s-]?time|login)\\s+code\\b",
    RegexOption.IGNORE_CASE
)
private val CODE_WORD = Regex("\\bcode\\b", RegexOption.IGNORE_CASE)
private val REASSURE = Regex(
    "\\b(?:don'?t|do\\s+not|not\\s+to)\\s+(?:worry|panic)\\b|" +
        "\\bno\\s+need\\s+to\\b|" +
        "\\bif\\s+not\\s+(?:you|done\\s+by\\s+you|by\\s+you|authori[sz]ed|initiated(?:\\s+by\\s+you)?)\\b|" +
        "\\bif\\s+(?:you\\s+)?(?:did\\s+not|didn'?t|have\\s+not|haven'?t)\\s+(?:authori[sz]e\\w*|initiate\\w*|do\\s+this|make\\s+this)\\b|" +
        "\\b(?:fikr|chinta|tension)\\s+(?:mat|na)\\s+(?:karo|karein|kijiye|lo)\\b|" +
        "\\bghabra\\w*\\s+mat\\b|" +
        "\\bif\\s+(?:you\\s+)?(?:have\\s+|had\\s+)?(?:not|n'?t)\\s+(?:done|made|authori[sz]ed|initiated|requested|recogni[sz]ed?)\\b|" +
        "\\bif\\s+(?:this|it|that)\\s+(?:is|was)\\s+not\\s+(?:you|done\\s+by\\s+you|by\\s+you)\\b|" +
        "\\bif\\s+not\\s+recogni[sz]ed\\b|" +
        "\\b(?:don'?t|do\\s+not)\\s+delay\\b|" +
        "\\bna\\b(?=\\W*$)",
    RegexOption.IGNORE_CASE
)
private val CLAUSE_SPLIT = Regex("[.!?;\n]+")
private val WHITESPACE = Regex("\\s+")

private fun tokenize(text: String): List<String> =
    WHITESPACE.split(text).filter { it.isNotEmpty() }

private fun hasSecret(tokens: List<String>, c: String): Boolean {
    if (tokens.isEmpty()) return false
    val span = tokens.joinToString(" ")
    return STRONG_SECRET.containsMatchIn(span) ||
        (CODE_WORD.containsMatchIn(span) && PURPOSE.containsMatchIn(c))
}

/** True when one clause asks the reader to transmit a secret code. */
fun secretRequest(text: String): Boolean {
    for (clause in CLAUSE_SPLIT.split(text)) {
        val c = REASSURE.replace(clause, " ")
        val hasSecretInClause = STRONG_SECRET.containsMatchIn(c) ||
            (CODE_WORD.containsMatchIn(c) && PURPOSE.containsMatchIn(c))
        if (!hasSecretInClause) {
            continue
        }
        if (NEG.containsMatchIn(c)) {
            continue
        }
        if (CHANNEL_SEND.containsMatchIn(c)) {
            return true
        }
        for (m in EN_SEND.findAll(c)) {
            val afterTokens = tokenize(c.substring(m.range.last + 1)).take(6)
            if (hasSecret(afterTokens, c)) {
                return true
            }
        }
        for (m in HI_SEND.findAll(c)) {
            val beforeTokens = tokenize(c.substring(0, m.range.first)).takeLast(6)
            if (hasSecret(beforeTokens, c)) {
                return true
            }
        }
        if (DEMAND.containsMatchIn(c) && PURPOSE.containsMatchIn(c)) {
            return true
        }
    }
    return false
}

val UNTRUSTED_HOSTING_PLATFORMS: Set<String> = setOf(
    "sites.google.com",
    "docs.google.com",
    "drive.google.com",
    "forms.gle",
    "firebaseapp.com",
    "web.app",
    "blogspot.com",
    "github.io",
    "sharepoint.com",
    "ipfs"
)

/**
 * Checks whether a hostname belongs to known shared hosting or user-generated content platforms.
 *
 * Free cloud and content hosts (Google Docs/Drive/Forms, Firebase, IPFS) frequently host phishing forms
 * and are disqualified from trusted domain status.
 *
 * @param rawHost Hostname string to check.
 * @return True if [rawHost] is hosted on an untrusted shared platform.
 */
fun isUntrustedHosting(rawHost: String): Boolean {
    val host = rawHost.lowercase().trim('.')
    for (platform in UNTRUSTED_HOSTING_PLATFORMS) {
        if (platform == "ipfs") {
            if (host == "ipfs" || "ipfs" in host.split(".")) {
                return true
            }
        } else {
            if (host == platform || host.endsWith(".$platform")) {
                return true
            }
        }
    }
    return false
}

/**
 * Checks whether a hostname belongs to an authorized institutional or banking domain.
 *
 * Automatically trusts Indian government domains (*.gov.in, *.nic.in) and RBI-restricted
 * banking domains (*.bank.in), provided they are not hosted on shared user-content platforms.
 *
 * @param rawHost Hostname string to inspect.
 * @param trustedDomains Set of explicitly allow-listed domains (defaults to [TrustedDomainStore.getDomains]).
 * @return True if the domain is verified as trusted.
 */
fun isTrusted(
    rawHost: String?,
    trustedDomains: Set<String> = TrustedDomainStore.getDomains()
): Boolean {
    if (rawHost.isNullOrEmpty()) return false

    var host = rawHost.lowercase().trim('.')
    if (":" in host) {
        host = host.split(":")[0]
    }

    if (isUntrustedHosting(host)) {
        return false
    }

    if (host.endsWith(".gov.in") || host.endsWith(".nic.in") || host == "gov.in" || host == "nic.in") {
        return true
    }

    // ".bank.in" is the RBI-mandated zone that only licensed Indian banks can register in.
    if (host.endsWith(".bank.in")) {
        return true
    }

    val regDom = getRegisteredDomain(host)
    if (host in trustedDomains || regDom in trustedDomains) {
        return true
    }

    return false
}

// Indian DLT sender header: XX-XXXXXX with an optional one-letter suffix (-S, -P, -T, -G).
private val DLT_HEADER = Regex("^[A-Za-z]{2}-([A-Za-z0-9]{3,8})(?:-[A-Za-z])?$")
// URL indicators that keep a link risky whoever sent it.
private val HARD_URL_INDICATORS = setOf("risky_tld", "ip_host", "unparseable_url")

/**
 * The indicator of the first known scam script (rules.json scam_scripts) the text follows, or null.
 * The SMS model calls some fixed scam scripts normal or promotional; a match floors the risk at high.
 */
fun scamScript(text: String): String? {
    for (script in Rules.active().scamScripts) {
        if (script.all.all { it.matcher(text).find() } && script.none.none { it.matcher(text).find() }) {
            return script.indicator
        }
    }
    return null
}

/** The upper-case entity code of a DLT header sender, or null for any other sender. */
fun senderHeader(sender: String?): String? {
    if (sender == null) return null
    return DLT_HEADER.matchEntire(sender.trim())?.groupValues?.get(1)?.uppercase(Locale.ROOT)
}

/**
 * Holds normalized analysis and safety classification for an individual URL.
 *
 * @property url Raw URL string as extracted from text.
 * @property normUrl Normalized canonical URL representation.
 * @property prob Evaluated probability of phishing after trust capping.
 * @property rawProb Raw model or heuristic probability prior to trust capping.
 * @property trusted True if the URL host matches an authorized trusted domain.
 * @property indicators List of risk indicator tags detected on this URL.
 * @property label Classification label ("phishing" or "benign").
 */
data class ProcessedUrl(
    val url: String,
    val normUrl: String,
    val prob: Double,
    val rawProb: Double,
    val trusted: Boolean,
    val indicators: List<String>,
    val label: String
)

/**
 * Raw detection result for an extracted URL from model or heuristic scoring.
 *
 * @property url Original URL string.
 * @property normUrl Canonical normalized URL representation.
 * @property prob Evaluated phishing probability.
 * @property label Classification verdict ("phishing" or "benign").
 * @property indicators Active structural risk indicator tags.
 */
data class UrlResult(
    val url: String,
    val normUrl: String,
    val prob: Double,
    val label: String,
    val indicators: List<String>
)

/**
 * Probability distribution and top verdict emitted by the SMS classifier.
 *
 * @property probs Map of class names ("ham", "unwanted", "scam") to predicted probabilities.
 * @property label Highest-scoring class label.
 */
data class SmsResult(
    val probs: Map<String, Double>,
    val label: String
)

/**
 * Consolidated multi-detector evidence report for a single message.
 *
 * @property label Primary verdict label ("ham", "unwanted", or "scam").
 * @property risk Overall risk score between 0.0 and 1.0.
 * @property level Risk tier string ("low", "medium", or "high").
 * @property threshold Decision boundary used to assign the "scam" label.
 * @property indicators Set of all active feature, cue, and detector indicators.
 * @property cueSpans Suspicious pattern spans identified in the message.
 * @property urls Processed URLs found within the text.
 * @property detectorVersions Mapping of component detector names to version strings.
 * @property extraDetectors Output parts from optional secondary detectors.
 * @property smsLabel Top class label directly from the SMS classifier.
 * @property registeredSender True if the message originated from a verified DLT enterprise header.
 */
data class Evidence(
    val label: String,
    val risk: Double,
    val level: String,
    val threshold: Double = 0.7,
    val indicators: List<String> = emptyList(),
    val cueSpans: List<CueSpan> = emptyList(),
    val urls: List<ProcessedUrl> = emptyList(),
    val detectorVersions: Map<String, String> = emptyMap(),
    val extraDetectors: List<DetectorPart> = emptyList(),
    // SMS model top class, used only by the alert policy and never serialised.
    val smsLabel: String? = null,
    // True when the sender is a DLT header and the SMS model gave an answer; used only by the
    // alert policy, never serialised.
    val registeredSender: Boolean = false
) {
    val cues: List<CueSpan> get() = cueSpans
}

/**
 * Temperature-scales class probabilities as in bench/heldout/calibrate.py.
 *
 * @param probs List of uncalibrated class probabilities.
 * @param temperature Softmax temperature scaling factor (> 0.0).
 * @return Calibrated probability distribution summing to 1.0.
 */
fun applyTemperature(probs: List<Double>, temperature: Double): List<Double> {
    if (temperature == 1.0) {
        return probs
    }
    val logs = probs.map { if (it > 0.0) ln(it) else Double.NEGATIVE_INFINITY }
    val top = (logs.maxOrNull() ?: Double.NEGATIVE_INFINITY) / temperature
    val weights = logs.map { if (it.isFinite()) exp(it / temperature - top) else 0.0 }
    val total = weights.sum()
    if (total <= 0.0) {
        return probs
    }
    return weights.map { it / total }
}

/**
 * Fuses detector outputs, URL assessments, and cue spans into a consolidated [Evidence] object.
 *
 * Evaluates individual model and heuristic scores, applies combo rules and scam script floors,
 * handles sender trust adjustments, and determines final risk and categorization.
 *
 * @param text Raw SMS message text.
 * @param smsResult Optional classification result from the SMS neural network.
 * @param urlResults Evaluation results for each URL present in the message.
 * @param cues Extracted suspicious cue spans.
 * @param trustedDomains Allow-list of domain names exempted from phishing scoring.
 * @param extraParts Optional contributions from plug-in detectors.
 * @param sender Originating sender address or phone number, if available.
 * @return Unified [Evidence] summary with calculated risk, level, and indicators.
 */
fun fuse(
    text: String,
    smsResult: SmsResult?,
    urlResults: List<UrlResult>,
    cues: List<CueSpan>,
    trustedDomains: Set<String> = TrustedDomainStore.getDomains(),
    extraParts: List<DetectorPart> = emptyList(),
    sender: String? = null
): Evidence {
    val fusionRules = Rules.active().fusion
    val processedUrls = mutableListOf<ProcessedUrl>()
    for (u in urlResults) {
        val rawUrl = u.url
        val host = extractHostname(rawUrl)
        val parseFailed = rawUrl.isNotEmpty() && host.isEmpty()

        val indicators = u.indicators.toMutableList()
        var rawProb = u.prob
        if (parseFailed) {
            if ("unparseable_url" !in indicators) {
                indicators.add("unparseable_url")
            }
            rawProb = maxOf(rawProb, fusionRules.urlPhishingLabelThreshold)
        }

        val trusted = isTrusted(host, trustedDomains) && !parseFailed
        val effectiveProb = if (trusted) minOf(rawProb, fusionRules.trustedProbCap) else rawProb
        val norm = if (u.normUrl.isNotEmpty()) u.normUrl else normaliseUrl(rawUrl)

        processedUrls.add(
            ProcessedUrl(
                url = rawUrl,
                normUrl = norm,
                prob = effectiveProb,
                rawProb = rawProb,
                trusted = trusted,
                indicators = indicators,
                label = if (effectiveProb >= fusionRules.urlPhishingLabelThreshold) "phishing" else "benign"
            )
        )
    }

    // SMS component: temperature-scaled scam plus part of the temperature-scaled unwanted probability.
    val scaledSmsProbs: List<Double>? = if (smsResult != null && smsResult.probs.isNotEmpty()) {
        val rawProbs = listOf(
            smsResult.probs["ham"] ?: 0.0,
            smsResult.probs["unwanted"] ?: 0.0,
            smsResult.probs["scam"] ?: 0.0
        )
        applyTemperature(rawProbs, fusionRules.smsTemperature)
    } else {
        null
    }
    val smsHamProb: Double? = scaledSmsProbs?.get(0)
    val smsScore = scaledSmsProbs?.let {
        fusionRules.smsScamWeight * it[2] + fusionRules.smsUnwantedWeight * it[1]
    } ?: 0.0

    val distinctCueTypes = cues.map { it.type }.toSet()

    // Cap link risk for a registered (DLT header) sender whose message the SMS model does not
    // call a scam. The URL model scores brand short links as phishing; on three real inboxes
    // 27 to 53 percent of genuine business SMS alerted, most with the link as the only strong
    // evidence. A link with a risky TLD, a bare IP host or an unparseable form is never capped.
    // Unknown and phone-number senders are untouched.
    // Without an SMS model answer the sender is ignored, so a message is never waved through
    // on the sender alone.
    val smsAnswered = smsResult != null && smsResult.probs.isNotEmpty()
    val smsSaysScam = smsAnswered && smsResult?.label == "scam"
    val registeredSender = smsAnswered && senderHeader(sender) != null
    if (registeredSender && !smsSaysScam) {
        for (i in processedUrls.indices) {
            val u = processedUrls[i]
            if (u.trusted || u.indicators.any { it in HARD_URL_INDICATORS }) continue
            val capped = minOf(u.prob, fusionRules.trustedProbCap)
            processedUrls[i] = u.copy(
                prob = capped,
                label = if (capped >= fusionRules.urlPhishingLabelThreshold) "phishing" else "benign"
            )
        }
    }

    // URL component: highest untrusted URL probability times the URL weight.
    val untrustedProbs = processedUrls.filter { !it.trusted }.map { it.prob }
    val urlScore = if (untrustedProbs.isNotEmpty()) {
        (untrustedProbs.maxOrNull() ?: 0.0) * fusionRules.urlWeight
    } else {
        0.0
    }

    // Cues component: a fixed weight per distinct cue type, capped.
    val cuesScore = minOf(fusionRules.cueCap, fusionRules.cueWeight * distinctCueTypes.size)

    // Classic scam pattern: urgency plus a threat or a credential/payment request.
    // A confident ham SMS result wins over generic words such as "today" and "pay".
    val combo = "urgency" in distinctCueTypes &&
            distinctCueTypes.any { it in setOf("threat", "credential_request", "payment_request") }
    val confidentHam = smsHamProb != null && smsHamProb >= fusionRules.smsHamConfidenceThreshold
    val comboScore = if (combo && !confidentHam) fusionRules.comboScore else 0.0

    val hasAppInstall = cues.any { it.type == "app_install" }
    val appInstallScore = if (hasAppInstall) fusionRules.appInstallScore else 0.0

    val hasCollectRequest = cues.any {
        it.type == "payment_request" && "collect request" in it.text.lowercase()
    }
    val hasPinCue = cues.any {
        it.type == "credential_request" && it.text.lowercase() == "pin"
    }
    val collectPinScore = if (hasCollectRequest && hasPinCue) fusionRules.collectPinScore else 0.0

    val extraRisk = extraParts.maxOfOrNull { clampRisk(it.risk) } ?: 0.0

    var risk = maxOf(smsScore, urlScore, cuesScore, comboScore, appInstallScore, collectPinScore, extraRisk)
    // A bank-style alert from a personal number is never routine: floor at medium.
    if ("sender_mismatch" in distinctCueTypes) {
        risk = maxOf(risk, fusionRules.mediumLevelThreshold)
    }
    // A bank alert that also asks for a secret code is a credential-phishing shape.
    val bankCredentialRequest = secretRequest(text) && isBankAlert(text)
    if (bankCredentialRequest) {
        risk = maxOf(risk, fusionRules.highLevelThreshold)
    }
    // A message that follows a known scam script is a scam whatever the model says.
    val scriptIndicator = scamScript(text)
    if (scriptIndicator != null) {
        risk = maxOf(risk, fusionRules.highLevelThreshold)
    }
    risk = minOf(1.0, maxOf(0.0, risk))
    risk = BigDecimal(risk).setScale(fusionRules.riskRoundDecimals, RoundingMode.HALF_UP).toDouble()

    val label = when {
        risk >= fusionRules.labelThreshold -> "scam"
        (smsResult != null && smsResult.label == "unwanted") || risk >= fusionRules.mediumLevelThreshold -> "unwanted"
        else -> "ham"
    }

    val level = when {
        risk >= fusionRules.highLevelThreshold || label == "scam" -> "high"
        risk >= fusionRules.mediumLevelThreshold -> "medium"
        else -> "low"
    }

    val allIndicators = mutableListOf<String>()
    for (u in processedUrls) {
        for (ind in u.indicators) {
            if (ind !in allIndicators) {
                allIndicators.add(ind)
            }
        }
    }
    for (cType in distinctCueTypes.sorted()) {
        val label = if (cType == "sender_mismatch") SENDER_MISMATCH_INDICATOR else cType
        if (label !in allIndicators) {
            allIndicators.add(label)
        }
    }
    if (bankCredentialRequest && BANK_ALERT_CREDENTIAL_INDICATOR !in allIndicators) {
        allIndicators.add(BANK_ALERT_CREDENTIAL_INDICATOR)
    }
    if (scriptIndicator != null && scriptIndicator !in allIndicators) {
        allIndicators.add(scriptIndicator)
    }

    return Evidence(
        label = label,
        risk = risk,
        level = level,
        threshold = fusionRules.labelThreshold,
        indicators = allIndicators,
        cueSpans = cues,
        urls = processedUrls,
        detectorVersions = Rules.active().detectorVersions,
        extraDetectors = extraParts,
        smsLabel = if (smsResult != null && smsResult.probs.isNotEmpty()) smsResult.label else null,
        registeredSender = registeredSender
    )
}
