/**
 * SharedPreferences keys tracking onboarding and user guide presentation state.
 * Used by MainActivity, SettingsActivity, and GuideActivity to control first-run overlays.
 * Internal constants with no external dependencies.
 */
package org.ps3.sentinel.ui

/**
 * Preference file and preference key constants for tracking first-run state.
 */
internal object FirstRun {
    const val PREFS_NAME = "ps3_sentinel_prefs"
    const val ONBOARDING_DONE = "onboarding_done"
    const val GUIDE_SHOWN = "guide_shown"
}
