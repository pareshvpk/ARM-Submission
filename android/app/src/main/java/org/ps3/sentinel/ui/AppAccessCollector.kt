/**
 * Collects third-party apps with sensitive accessibility services and SMS permissions.
 * Inspects enabled AccessibilityService capabilities (screen reading, gestures) to detect overlay or monitoring risks.
 * Adapted from pareshvpk/Phase AppReviewCollector under the MIT licence.
 */
// Adapted from pareshvpk/Phase AppReviewCollector (MIT licence).
package org.ps3.sentinel.ui

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.view.accessibility.AccessibilityManager
import org.ps3.sentinel.core.AppAccessEntry
import org.ps3.sentinel.core.sortEntries

/**
 * Scans installed apps for dangerous accessibility capabilities and SMS read permissions.
 *
 * @property context Application context used to query system package and accessibility managers.
 */
class AppAccessCollector(private val context: Context) {
    /**
     * Inspects enabled accessibility services and returns sorted entries for non-Sentinel apps.
     *
     * @return List of [AppAccessEntry] describing screen-reading, gesture, and SMS capabilities.
     */
    @Suppress("DEPRECATION")
    fun collect(): List<AppAccessEntry> {
        val pm = context.packageManager
        val manager = context.getSystemService(AccessibilityManager::class.java) ?: return emptyList()
        val services = manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK).orEmpty()
        val entries = services
            .groupBy { it.resolveInfo.serviceInfo.packageName }
            .filterKeys { it != context.packageName && it != "org.ps3.sentinel" }
            .mapNotNull { (pkgName, enabled) ->
                try {
                    val serviceInfo = enabled.first().resolveInfo.serviceInfo
                    val appInfo = serviceInfo.applicationInfo
                    val label = appInfo.loadLabel(pm).toString()
                    val capabilities = enabled.fold(0) { bits, service -> bits or service.capabilities }
                    val canReadScreen = (capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_RETRIEVE_WINDOW_CONTENT) != 0
                    val canPerformGestures = (capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_PERFORM_GESTURES) != 0
                    val sms: Boolean? = try {
                        val pkg = pm.getPackageInfo(pkgName, PackageManager.GET_PERMISSIONS)
                        val requested = pkg.requestedPermissions.orEmpty()
                        val flags = pkg.requestedPermissionsFlags
                        val index = requested.indexOf(Manifest.permission.READ_SMS)
                        when {
                            index < 0 -> false
                            flags == null || index >= flags.size -> null
                            else -> (flags[index] and PackageInfo.REQUESTED_PERMISSION_GRANTED) != 0
                        }
                    } catch (_: PackageManager.NameNotFoundException) {
                        null
                    } catch (_: SecurityException) {
                        null
                    }
                    val isSystem = (appInfo.flags and (ApplicationInfo.FLAG_SYSTEM or ApplicationInfo.FLAG_UPDATED_SYSTEM_APP)) != 0
                    AppAccessEntry(
                        packageName = pkgName,
                        label = label,
                        canReadScreen = canReadScreen,
                        canPerformGestures = canPerformGestures,
                        canReadSms = sms,
                        isSystem = isSystem
                    )
                } catch (_: PackageManager.NameNotFoundException) {
                    null
                } catch (_: SecurityException) {
                    null
                }
            }
        return sortEntries(entries)
    }
}
