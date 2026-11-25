package org.ps3.sentinel.a11y

import android.accessibilityservice.AccessibilityButtonController
import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Toast
import org.ps3.sentinel.R
import org.ps3.sentinel.ui.MainActivity

/**
 * Scoped, on-demand accessibility service that allows the user to inspect visible screen text
 * in any app (WhatsApp, Telegram, email, browser) by tapping the system accessibility button.
 *
 * Events are intentionally ignored so that nothing is ever read in the background.
 * Screen text is never stored, logged, or sent anywhere; logcat records only character count
 * and elapsed milliseconds under tag PS3A11y.
 */
class ScreenCheckService : AccessibilityService() {

    private var buttonCallback: AccessibilityButtonController.AccessibilityButtonCallback? = null

    override fun onServiceConnected() {
        super.onServiceConnected()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val controller = accessibilityButtonController
            if (buttonCallback == null) {
                val callback = object : AccessibilityButtonController.AccessibilityButtonCallback() {
                    override fun onClicked(controller: AccessibilityButtonController) {
                        checkActiveScreen()
                    }
                }
                buttonCallback = callback
                controller.registerAccessibilityButtonCallback(callback)
            }
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Events are ignored on purpose. Screen checking is strictly on-demand
        // via the system accessibility button, never in the background.
    }

    override fun onInterrupt() {
        // No-op.
    }

    override fun onDestroy() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            buttonCallback?.let {
                try {
                    accessibilityButtonController.unregisterAccessibilityButtonCallback(it)
                } catch (_: Exception) {
                }
            }
            buttonCallback = null
        }
        super.onDestroy()
    }

    private fun checkActiveScreen() {
        val startMs = SystemClock.elapsedRealtime()
        val root = rootInActiveWindow
        val items = mutableListOf<ScreenNodeItem>()
        val shouldRecycle = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU

        if (root != null) {
            try {
                traverse(root, null, items, shouldRecycle)
            } catch (e: Exception) {
                Log.w(TAG, "Screen check node traversal encountered an error: ${e.message}")
            }
        }

        val text = collectCleanScreenText(items, packageName)
        val elapsedMs = SystemClock.elapsedRealtime() - startMs

        // Never store, log or send the screen text. Log only counts: chars read, ms taken.
        Log.i(TAG, "chars read: ${text.length}, ms taken: $elapsedMs")

        if (text.isBlank()) {
            Toast.makeText(this, R.string.screen_check_no_text, Toast.LENGTH_SHORT).show()
            return
        }

        val intent = Intent(this, MainActivity::class.java).apply {
            action = Intent.ACTION_SEND
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        startActivity(intent)
    }

    private fun traverse(
        node: AccessibilityNodeInfo?,
        inheritedPackage: CharSequence?,
        items: MutableList<ScreenNodeItem>,
        shouldRecycle: Boolean
    ) {
        if (node == null) return
        try {
            val pkg = node.packageName ?: inheritedPackage
            if (node.isVisibleToUser) {
                val isPw = node.isPassword
                val text = node.text
                if (!text.isNullOrBlank()) {
                    items.add(ScreenNodeItem(pkg, text, isPw))
                }
                val desc = node.contentDescription
                if (!desc.isNullOrBlank() && desc.toString() != text?.toString()) {
                    items.add(ScreenNodeItem(pkg, desc, isPw))
                }
            }
            val count = node.childCount
            for (i in 0 until count) {
                val child = node.getChild(i)
                traverse(child, pkg, items, shouldRecycle)
            }
        } finally {
            if (shouldRecycle) {
                node.recycle()
            }
        }
    }

    companion object {
        private const val TAG = "PS3A11y"
    }
}
