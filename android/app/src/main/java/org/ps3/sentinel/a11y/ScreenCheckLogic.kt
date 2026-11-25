package org.ps3.sentinel.a11y

const val MAX_SCREEN_TEXT_LENGTH = 2000

/**
 * Representation of a visible accessibility node's textual content for screen checking.
 */
data class ScreenNodeItem(
    val packageName: CharSequence?,
    val text: CharSequence?,
    val isPassword: Boolean = false
)

/**
 * Pure function that filters, cleans, collapses whitespace, joins with newlines,
 * and cuts visible screen texts to [maxChars].
 *
 * Filters out:
 * - Items marked with [ScreenNodeItem.isPassword] = true
 * - Items originating from [ownPackage]
 * - Blank or whitespace-only texts
 */
fun collectCleanScreenText(
    items: List<ScreenNodeItem>,
    ownPackage: String = "org.ps3.sentinel",
    maxChars: Int = MAX_SCREEN_TEXT_LENGTH
): String {
    val lines = items.asSequence()
        .filterNot { it.isPassword }
        .filterNot { it.packageName?.toString() == ownPackage }
        .mapNotNull { it.text?.toString() }
        .flatMap { it.lines().asSequence() }
        .map { it.trim().replace(Regex("\\s+"), " ") }
        .filter { it.isNotEmpty() }
        .toList()
    val joined = lines.joinToString("\n")
    return if (joined.length > maxChars) joined.substring(0, maxChars) else joined
}

/**
 * Overload accepting triples of (packageName, text, isPassword) for JVM tests and generic callers.
 */
fun collectCleanScreenTextFromTriples(
    items: List<Triple<CharSequence?, CharSequence?, Boolean>>,
    ownPackage: String = "org.ps3.sentinel",
    maxChars: Int = MAX_SCREEN_TEXT_LENGTH
): String = collectCleanScreenText(
    items.map { ScreenNodeItem(it.first, it.second, it.third) },
    ownPackage,
    maxChars
)
