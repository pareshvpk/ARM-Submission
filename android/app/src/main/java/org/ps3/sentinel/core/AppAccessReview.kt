/**
 * Pure Kotlin data models and risk ordering for installed app accessibility review.
 * Evaluates risk tiers based on screen-reading and SMS access permissions without Android classes.
 * Checked by AppAccessReviewTest.
 */
package org.ps3.sentinel.core

/**
 * Carries access capabilities and system status for an installed application.
 *
 * @property packageName Unique Android package identifier of the app.
 * @property label Human-readable application name.
 * @property canReadScreen True if the app has active accessibility window content retrieval.
 * @property canPerformGestures True if the app can dispatch touch or gesture events.
 * @property canReadSms True if SMS read permission is granted, false if not, or null if unreadable.
 * @property isSystem True if installed as an Android system application.
 */
data class AppAccessEntry(
    val packageName: String,
    val label: String,
    val canReadScreen: Boolean,
    val canPerformGestures: Boolean,
    val canReadSms: Boolean?,
    val isSystem: Boolean
)

/**
 * Calculates a numerical risk rank for an app access entry.
 *
 * @param entry The application access record to evaluate.
 * @return An integer risk score where higher values indicate higher relative risk.
 */
fun riskOrder(entry: AppAccessEntry): Int {
    val tier = when {
        // Tier 3: screen reading plus SMS read access allows intercepting 2FA credentials.
        entry.canReadScreen && entry.canReadSms == true -> 3
        // Tier 2: interactive screen inspection or gesture control alone.
        entry.canReadScreen || entry.canPerformGestures -> 2
        else -> 1
    }
    // Non-system apps receive +10 so user-installed apps always rank above system services.
    return if (entry.isSystem) tier else tier + 10
}

/**
 * Sorts application access records in descending order of evaluated risk.
 *
 * Ties in risk score are broken alphabetically by label, then by package name.
 *
 * @param entries Unordered list of application access records.
 * @return Sorted list from highest to lowest risk.
 */
fun sortEntries(entries: List<AppAccessEntry>): List<AppAccessEntry> {
    return entries.sortedWith(
        compareByDescending<AppAccessEntry> { riskOrder(it) }
            .thenBy { it.label }
            .thenBy { it.packageName }
    )
}

