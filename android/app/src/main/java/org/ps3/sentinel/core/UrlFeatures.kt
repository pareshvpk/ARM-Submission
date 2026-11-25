/**
 * Pure Kotlin URL extraction and canonical normalization functions.
 * Mirrored by sentinel/url_features.py (normalise_url, extract_urls).
 * Checked by ParityTest and UrlFeaturesTest.
 */
package org.ps3.sentinel.core

import java.net.URI
import java.util.regex.Pattern

private val SCHEME_REGEX = Pattern.compile("^[a-z][a-z0-9+.-]*://", Pattern.CASE_INSENSITIVE)
private const val EXPLICIT_PATTERN = "(?:h(?:tt|xx)ps?://|www\\.)[^\\s<>\"']+"
private const val DOT_PATTERN = "(?:\\.|\\[\\.\\]|\\(\\.\\))"
private const val LABEL_PATTERN = "[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
private const val BARE_PATTERN = "(?<![\\w@.])(?:" + LABEL_PATTERN + DOT_PATTERN + ")+[a-z]{2,24}(?![\\w-])(?:/[^\\s<>\"']*)?"
private val URL_REGEX = Pattern.compile("$EXPLICIT_PATTERN|$BARE_PATTERN", Pattern.CASE_INSENSITIVE)

private val NOT_DOMAINS = setOf("e.g", "i.e", "a.m", "p.m")

private val BARE_TLDS = (
    "com net org info biz xyz top site online store shop club live app dev io co ai me cc tk ml ga cf gq " +
    "buzz link click icu vip win bid loan work fun space website tech pro cloud email support help " +
    "in uk us ca au de fr ru cn jp br pk bd lk np ae sg my id ph th vn ng ke za eu ly to gl gd sh"
).split("\\s+".toRegex()).toSet()

/**
 * Normalizes a raw URL into a canonical format for model evaluation and comparisons.
 *
 * Strips default ports, unescapes defanged schemes ('hxxp') and dots, lowercases the hostname,
 * removes trailing slashes, and handles bracketed IPv6 literals.
 *
 * @param rawUrl Raw URL string before canonicalization, or null/empty.
 * @return Canonical normalized URL string, or empty string if input is null or blank.
 */
fun normaliseUrl(rawUrl: String?): String {
    if (rawUrl.isNullOrEmpty()) return ""
    // Defanged protocol and dot notations (hxxp, [.], (.)) are restored to standard form.
    var url = rawUrl.trim().replaceFirst(Regex("^hxxp", RegexOption.IGNORE_CASE), "http")
    url = url.replace("[.]", ".").replace("(.)", ".")

    val hasScheme = SCHEME_REGEX.matcher(url).find()
    val urlWithScheme = if (hasScheme) url else "http://$url"

    return try {
        val parsed = URI(urlWithScheme)
        var host = parsed.host
        val port = parsed.port
        var username: String? = null

        if (host == null) {
            val authority = parsed.authority
            if (authority != null) {
                var hostPart = authority
                if (hostPart.contains("@")) {
                    val userPart = hostPart.substringBefore("@")
                    username = if (userPart.contains(":")) userPart.substringBefore(":") else userPart
                    hostPart = hostPart.substringAfter("@")
                }
                host = if (hostPart.startsWith("[")) {
                    val closingBracket = hostPart.indexOf(']')
                    if (closingBracket >= 0) hostPart.substring(0, closingBracket + 1) else hostPart
                } else if (hostPart.contains(":")) {
                    hostPart.substringBefore(":")
                } else {
                    hostPart
                }
            } else {
                return url.lowercase()
            }
        } else {
            val userInfo = parsed.userInfo
            if (userInfo != null) {
                username = if (userInfo.contains(":")) userInfo.substringBefore(":") else userInfo
            }
        }

        host = host.lowercase()
        if (host.startsWith("[") && host.endsWith("]")) {
            host = host.substring(1, host.length - 1)
        }
        if (host.startsWith("www.")) {
            host = host.substring(4)
        }

        // Python omits port 0, so match that here as well.
        var netloc = host + if (port > 0) ":$port" else ""
        if (username != null) {
            netloc = "$username@$netloc"
        }

        var path = parsed.rawPath ?: ""
        while (path.endsWith("/")) {
            path = path.substring(0, path.length - 1)
        }

        val query = if (!parsed.rawQuery.isNullOrEmpty()) "?${parsed.rawQuery}" else ""
        val frag = if (!parsed.rawFragment.isNullOrEmpty()) "#${parsed.rawFragment}" else ""

        netloc + path + query + frag
    } catch (_: Exception) {
        manualNormaliseUrl(url, urlWithScheme)
    }
}

/**
 * Fallback parser when java.net.URI throws on characters like |, {, }, ^, or `.
 * Extracts authority, path, query, and fragment directly to match Python normalise_url.
 */
private fun manualNormaliseUrl(url: String, urlWithScheme: String): String {
    return try {
        val afterScheme = urlWithScheme.substringAfter("://", urlWithScheme)
        val authorityDelim = afterScheme.indexOfAny(charArrayOf('/', '?', '#'))
        val rawAuthority = if (authorityDelim >= 0) afterScheme.substring(0, authorityDelim) else afterScheme
        val rest = if (authorityDelim >= 0) afterScheme.substring(authorityDelim) else ""

        if (rawAuthority.isEmpty()) return url.lowercase()
        if (rawAuthority.startsWith("[") && ']' !in rawAuthority) return url.lowercase()

        var authority = rawAuthority
        var username: String? = null
        if ("@" in authority) {
            val userPart = authority.substringBeforeLast("@")
            username = if (userPart.contains(":")) userPart.substringBefore(":") else userPart
            authority = authority.substringAfterLast("@")
        }

        var host: String
        var port = -1
        if (authority.startsWith("[")) {
            val closingBracket = authority.indexOf(']')
            if (closingBracket < 0) return url.lowercase()
            host = authority.substring(1, closingBracket)
            val afterBracket = authority.substring(closingBracket + 1)
            if (afterBracket.startsWith(":")) {
                port = afterBracket.substring(1).toIntOrNull() ?: return url.lowercase()
            } else if (afterBracket.isNotEmpty()) {
                return url.lowercase()
            }
        } else if (":" in authority) {
            host = authority.substringBefore(":")
            val portStr = authority.substringAfter(":")
            port = portStr.toIntOrNull() ?: return url.lowercase()
        } else {
            host = authority
        }

        if (host.isEmpty()) return url.lowercase()

        host = host.lowercase()
        if (host.startsWith("[") && host.endsWith("]")) {
            host = host.substring(1, host.length - 1)
        }
        if (host.startsWith("www.")) {
            host = host.substring(4)
        }

        var netloc = host + if (port > 0) ":$port" else ""
        if (username != null) {
            netloc = "$username@$netloc"
        }

        val frag = if ("#" in rest) "#" + rest.substringAfter("#") else ""
        val withoutFrag = rest.substringBefore("#")
        val query = if ("?" in withoutFrag) "?" + withoutFrag.substringAfter("?") else ""
        var path = withoutFrag.substringBefore("?")
        while (path.endsWith("/")) {
            path = path.substring(0, path.length - 1)
        }

        netloc + path + query + frag
    } catch (_: Exception) {
        url.lowercase()
    }
}

/**
 * Scans message text and extracts all explicit and bare web URLs.
 *
 * Matches explicit schemes (http, https, hxxp), www-prefixed links, and bare domains ending
 * in recognized TLDs while ignoring common abbreviations (e.g. 'e.g.', 'p.m.').
 *
 * @param text Message body to scan for URLs, or null/empty.
 * @return List of unique extracted URL strings in first-seen order.
 */
fun extractUrls(text: String?): List<String> {
    if (text.isNullOrEmpty()) return emptyList()
    val urls = mutableListOf<String>()
    val matcher = URL_REGEX.matcher(text)
    val explicitPrefixPattern = Pattern.compile("^(h(tt|xx)ps?://|www\\.)", Pattern.CASE_INSENSITIVE)

    while (matcher.find()) {
        val matchStr = matcher.group()
        var u = matchStr.trimEnd('.', ',', ';', ':', '!', '?', ')', ']', '}', '\'', '"')
        u = u.replaceFirst(Regex("^hxxp", RegexOption.IGNORE_CASE), "http")
            .replace("[.]", ".")
            .replace("(.)", ".")

        val noScheme = u.replaceFirst(Regex("^[a-zA-Z]+://"), "")
        val host = noScheme.split('/', '?', '#')[0].lowercase()
        val isBare = !explicitPrefixPattern.matcher(matchStr).find()
        val tld = host.substringAfterLast('.', "")

        // Bare domains must match recognized TLDs to avoid false positives on abbreviations.
        if (host in NOT_DOMAINS || (isBare && tld !in BARE_TLDS)) {
            continue
        }

        if (u !in urls) {
            urls.add(u)
        }
    }
    return urls
}
