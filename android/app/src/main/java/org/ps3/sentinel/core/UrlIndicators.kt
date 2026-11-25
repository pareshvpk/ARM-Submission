/**
 * Pure Kotlin heuristic URL indicator and host parsing utilities.
 * Mirrored by sentinel/detectors.py (url_indicators) and checked by ParityTest and UrlIndicatorsTest.
 * Performs offline risk checks (IP hosts, Punycode, suspicious TLDs, brand lookalikes) without network access.
 */
package org.ps3.sentinel.core

import java.net.URI

val BRAND_DOMAINS: Map<String, Set<String>> = mapOf(
    "sbi" to setOf("onlinesbi.sbi", "sbi.co.in"),
    "hdfc" to setOf("hdfcbank.com"),
    "icici" to setOf("icicibank.com"),
    "axis" to setOf("axisbank.com"),
    "kotak" to setOf("kotak.com"),
    "paytm" to setOf("paytm.com"),
    "phonepe" to setOf("phonepe.com"),
    "gpay" to setOf("google.com", "pay.google.com"),
    "amazon" to setOf("amazon.in", "amazon.com"),
    "flipkart" to setOf("flipkart.com"),
    "irctc" to setOf("irctc.co.in"),
    "indiapost" to setOf("indiapost.gov.in"),
    "uidai" to setOf("uidai.gov.in"),
    "aadhaar" to setOf("uidai.gov.in"),
    "npci" to setOf("npci.org.in", "bhimupi.org.in")
)

val RISKY_TLDS: Set<String> = setOf(
    "xyz", "top", "site", "online", "live", "click", "icu", "buzz", "shop", "info"
)

val SHORTENERS: Set<String> = setOf(
    "bit.ly", "tinyurl.com", "tinyurl", "goo.gl", "t.co", "cutt.ly", "rb.gy", "is.gd"
)

val TWO_PART_SUFFIXES: Set<String> = setOf(
    "co.in", "gov.in", "org.in", "nic.in", "net.in", "ac.in",
    "co.uk", "org.uk", "com.au", "net.au", "org.au"
)

/**
 * Extracts the effective registered domain (eTLD+1) from a hostname string.
 *
 * Accounts for two-part country code top-level domains such as '.co.in' and '.gov.uk'.
 *
 * @param rawHost Raw hostname string, with or without port.
 * @return Effective registered domain, or empty string if [rawHost] is null or blank.
 */
fun getRegisteredDomain(rawHost: String?): String {
    if (rawHost.isNullOrEmpty()) return ""
    var host = rawHost.lowercase().trim('.')
    if (":" in host) {
        host = host.split(":")[0]
    }
    val parts = host.split(".")
    if (parts.size <= 2) {
        return host
    }
    val secondLast = parts[parts.size - 2]
    val last = parts[parts.size - 1]
    val suffix2 = "$secondLast.$last"
    // Handle 2-part ccTLDs where registered domain requires 3 parts (e.g. sbi.co.in).
    if (suffix2 in TWO_PART_SUFFIXES && parts.size >= 3) {
        return parts.takeLast(3).joinToString(".")
    }
    return parts.takeLast(2).joinToString(".")
}

/**
 * Checks whether [rawHost] is a valid IPv4 or IPv6 numeric literal address.
 *
 * Pure syntax parser that never invokes DNS resolver lookups (satisfies privacy/offline guarantee).
 *
 * @param rawHost Hostname string to validate, possibly bracketed if IPv6.
 * @return True if [rawHost] is an IPv4 dotted-quad or IPv6 hexadecimal literal.
 */
fun isIpAddress(rawHost: String): Boolean {
    val host = stripIpv6Brackets(rawHost.trim().lowercase())
    if (isValidIpv4(host)) return true
    if (host.contains(":")) {
        // Pure check only: no resolver and no DNS lookup is ever performed.
        return isValidIpv6Literal(host)
    }
    return false
}

private fun isValidIpv4(host: String): Boolean {
    val parts = host.split(".")
    if (parts.size != 4) return false
    return parts.all { part ->
        if (part.isEmpty() || part.length > 3) return@all false
        if (part.length > 1 && part.startsWith("0")) return@all false
        if (!part.all { it in '0'..'9' }) return@all false
        val num = part.toIntOrNull()
        num != null && num in 0..255
    }
}

private fun isValidHexGroup(group: String): Boolean {
    if (group.isEmpty() || group.length > 4) return false
    return group.all { it in '0'..'9' || it in 'a'..'f' }
}

private fun isValidIpv6Literal(host: String): Boolean {
    if (host.isEmpty() || '[' in host || ']' in host || '%' in host) return false
    if (!host.contains(":")) return false
    var h = host
    if ('.' in h) {
        val lastColon = h.lastIndexOf(':')
        if (lastColon < 0) return false
        val ipv4Part = h.substring(lastColon + 1)
        if (!isValidIpv4(ipv4Part)) return false
        val prefix = h.substring(0, lastColon)
        if ('.' in prefix) return false
        h = prefix + ":0:0"
    }
    val firstDouble = h.indexOf("::")
    if (firstDouble >= 0 && h.indexOf("::", firstDouble + 1) >= 0) return false
    if (firstDouble >= 0) {
        val left = h.substring(0, firstDouble)
        val right = h.substring(firstDouble + 2)
        val leftGroups = if (left.isEmpty()) emptyList() else left.split(":")
        val rightGroups = if (right.isEmpty()) emptyList() else right.split(":")
        if (leftGroups.any { it.isEmpty() } || rightGroups.any { it.isEmpty() }) return false
        if (leftGroups.any { !isValidHexGroup(it) } || rightGroups.any { !isValidHexGroup(it) }) return false
        val total = leftGroups.size + rightGroups.size
        return total <= 7
    } else {
        if (h.startsWith(":") || h.endsWith(":")) return false
        val groups = h.split(":")
        if (groups.size != 8) return false
        if (groups.any { !isValidHexGroup(it) }) return false
        return true
    }
}

/**
 * Extracts and cleans the hostname component from a URL string.
 *
 * Falls back to manual authority parsing when java.net.URI rejects special characters (e.g. '|', '{').
 *
 * @param rawUrl Raw URL string.
 * @return Extracted lowercased hostname without brackets or port, or empty string if unparseable.
 */
fun extractHostname(rawUrl: String): String {
    if (rawUrl.isEmpty()) return ""

    val withScheme = if ("://" in rawUrl) rawUrl else "http://$rawUrl"
    val host = try {
        val uri = URI(withScheme)
        val parsedHost = uri.host
        if (parsedHost != null) parsedHost else uri.authority?.let { hostFromAuthority(it) }
    } catch (_: Exception) {
        // java.net.URI rejects unencoded | { } ^ and backtick, which Python's
        // urlparse accepts, so read the authority by hand instead of calling
        // the URL unparseable.
        hostFromRawUrl(withScheme)
    }

    if (host.isNullOrEmpty()) return ""
    return stripIpv6Brackets(host.lowercase())
}

/**
 * Return the host of a URL that java.net.URI refused, or null when it has none.
 *
 * The authority runs from after the scheme to the first /, ? or #. A bracketed
 * IPv6 literal without its closing bracket is malformed, as in Python.
 */
private fun hostFromRawUrl(withScheme: String): String? {
    val afterScheme = withScheme.substringAfter("://", withScheme)
    val authority = afterScheme.substringBefore('/').substringBefore('?').substringBefore('#')
    if (authority.isEmpty()) return null
    if (authority.startsWith("[") && ']' !in authority) return null
    return hostFromAuthority(authority)
}

/** Return the host part of an authority, honouring userinfo and bracketed IPv6 literals. */
private fun hostFromAuthority(rawAuthority: String): String {
    val authority = if ("@" in rawAuthority) rawAuthority.substringAfterLast("@") else rawAuthority
    if (authority.startsWith("[")) {
        val closingBracket = authority.indexOf(']')
        if (closingBracket >= 0) {
            return authority.substring(1, closingBracket)
        }
        return authority
    }
    return if (":" in authority) authority.substringBefore(":") else authority
}

/** Remove the brackets that a URI literal uses around an IPv6 address. */
private fun stripIpv6Brackets(host: String): String {
    if (host.startsWith("[") && host.endsWith("]")) {
        return host.substring(1, host.length - 1)
    }
    return host
}

/**
 * Scans a URL and returns a list of risk indicators triggering on suspicious structure.
 *
 * Evaluates IP hosts, Punycode, embedded credentials, excessive subdomains, risky TLDs,
 * link shorteners, and brand lookalike mismatches.
 *
 * @param url Raw URL string to analyze.
 * @return List of indicator identifier strings (e.g. "ip_host", "risky_tld", "brand_lookalike").
 */
fun urlIndicators(url: String?): List<String> {
    if (url.isNullOrEmpty()) return emptyList()

    val host = extractHostname(url)
    if (host.isEmpty()) return listOf("unparseable_url")

    val indicators = mutableListOf<String>()

    // 1. ip_host
    if (host.isNotEmpty() && isIpAddress(host)) {
        indicators.add("ip_host")
    }

    // 2. punycode
    if (host.contains("xn--")) {
        indicators.add("punycode")
    }

    // 3. at_sign
    if (url.contains("@")) {
        indicators.add("at_sign")
    }

    // 4. many_subdomains (>= 4 labels) - deep nesting often disguises target domain
    val labels = host.split(".").filter { it.isNotEmpty() }
    if (labels.size >= 4) {
        indicators.add("many_subdomains")
    }

    // 5. risky_tld
    val tld = labels.lastOrNull() ?: ""
    if (tld in RISKY_TLDS) {
        indicators.add("risky_tld")
    }

    // 6. shortener
    val regDom = getRegisteredDomain(host)
    if (host in SHORTENERS || regDom in SHORTENERS) {
        indicators.add("shortener")
    }

    // 7. brand_lookalike - brand keyword present on unapproved domain
    for ((brand, officialDomains) in BRAND_DOMAINS) {
        if (host.contains(brand)) {
            if (regDom !in officialDomains && host !in officialDomains) {
                indicators.add("brand_lookalike")
                break
            }
        }
    }

    return indicators
}
