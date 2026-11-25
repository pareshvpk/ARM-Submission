package org.ps3.sentinel.core

/**
 * Pure model capturing the state of all on-device protection mechanisms.
 *
 * The core items are SMS, MMS and notifications. [screenCheck] is an optional
 * convenience feature, so it never makes protection count as partly on.
 */
data class ProtectionStatus(
    val sms: Boolean,
    val mms: Boolean,
    val notifications: Boolean,
    val screenCheck: Boolean
) {
    /** Returns true if all core protection features are enabled. */
    fun allOn(): Boolean = sms && mms && notifications

    /** Returns stable keys of disabled core protection features in fixed evaluation order. */
    fun offItems(): List<String> {
        val list = mutableListOf<String>()
        if (!sms) list.add(ITEM_SMS)
        if (!mms) list.add(ITEM_MMS)
        if (!notifications) list.add(ITEM_NOTIFICATIONS)
        return list
    }

    companion object {
        const val ITEM_SMS = "sms"
        const val ITEM_MMS = "mms"
        const val ITEM_NOTIFICATIONS = "notifications"
        const val ITEM_SCREEN_CHECK = "screen_check"
    }
}
