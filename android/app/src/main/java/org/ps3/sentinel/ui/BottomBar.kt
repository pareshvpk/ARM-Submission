package org.ps3.sentinel.ui

import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import org.ps3.sentinel.R

enum class Tab {
    HOME, ALERTS, CHECK, PROTECTION, SETTINGS
}

object BottomBar {

    /** System bar and display cutout insets, so the bar and screen padding clear both. */
    private val INSET_TYPES: Int =
        WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()

    /**
     * Draws the window edge-to-edge on every API level. Without this the platform consumes the
     * insets on Android 12 while targetSdk 35 forces edge-to-edge on Android 15, so the same
     * inset handling below would produce different results.
     */
    fun enableEdgeToEdge(activity: Activity) {
        WindowCompat.setDecorFitsSystemWindows(activity.window, false)
    }

    fun attach(activity: Activity, rootView: View, current: Tab) {
        val accentColor = ContextCompat.getColor(activity, R.color.brand)
        val inactiveColor = ContextCompat.getColor(activity, R.color.nav_inactive)

        val layoutHome = rootView.findViewById<View>(R.id.layoutNavHome)
        val ivHome = rootView.findViewById<ImageView>(R.id.ivNavHome)
        val tvHome = rootView.findViewById<TextView>(R.id.tvNavHome)

        val layoutAlerts = rootView.findViewById<View>(R.id.layoutNavAlerts)
        val ivAlerts = rootView.findViewById<ImageView>(R.id.ivNavAlerts)
        val tvAlerts = rootView.findViewById<TextView>(R.id.tvNavAlerts)

        val btnCheck = rootView.findViewById<View>(R.id.btnNavCheck)
        val tvCheck = rootView.findViewById<TextView>(R.id.tvNavCheck)

        val layoutProtection = rootView.findViewById<View>(R.id.layoutNavProtection)
        val ivProtection = rootView.findViewById<ImageView>(R.id.ivNavProtection)
        val tvProtection = rootView.findViewById<TextView>(R.id.tvNavProtection)

        val layoutSettings = rootView.findViewById<View>(R.id.layoutNavSettings)
        val ivSettings = rootView.findViewById<ImageView>(R.id.ivNavSettings)
        val tvSettings = rootView.findViewById<TextView>(R.id.tvNavSettings)

        fun applyTabState(isSelected: Boolean, iv: ImageView?, tv: TextView?) {
            if (iv != null) {
                iv.imageTintList = ColorStateList.valueOf(if (isSelected) accentColor else inactiveColor)
            }
            if (tv != null) {
                tv.setTextColor(if (isSelected) accentColor else inactiveColor)
                tv.typeface = if (isSelected) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
            }
        }

        applyTabState(current == Tab.HOME, ivHome, tvHome)
        applyTabState(current == Tab.ALERTS, ivAlerts, tvAlerts)
        applyTabState(current == Tab.PROTECTION, ivProtection, tvProtection)
        applyTabState(current == Tab.SETTINGS, ivSettings, tvSettings)

        if (tvCheck != null) {
            tvCheck.typeface = if (current == Tab.CHECK) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        }

        fun navigateTo(targetTab: Tab, targetClass: Class<*>) {
            if (targetTab == current) return
            val intent = Intent(activity, targetClass).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            activity.startActivity(intent)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                activity.overrideActivityTransition(Activity.OVERRIDE_TRANSITION_OPEN, 0, 0)
                activity.overrideActivityTransition(Activity.OVERRIDE_TRANSITION_CLOSE, 0, 0)
            } else {
                @Suppress("DEPRECATION")
                activity.overridePendingTransition(0, 0)
            }
        }

        layoutHome?.setOnClickListener { navigateTo(Tab.HOME, HomeActivity::class.java) }
        layoutAlerts?.setOnClickListener { navigateTo(Tab.ALERTS, AlertsActivity::class.java) }
        btnCheck?.setOnClickListener { navigateTo(Tab.CHECK, MainActivity::class.java) }
        layoutProtection?.setOnClickListener { navigateTo(Tab.PROTECTION, ProtectionActivity::class.java) }
        layoutSettings?.setOnClickListener { navigateTo(Tab.SETTINGS, SettingsActivity::class.java) }

        // The <include> id replaces the container id from view_bottom_bar.xml.
        val bar = rootView.findViewById<View>(R.id.bottomBar)
            ?: rootView.findViewById<View>(R.id.bottomBarContainer)
        if (bar != null) {
            applyBarInsets(bar)
        }
    }

    /**
     * Lifts the floating bar above the navigation bar by adding the bottom inset to its bottom
     * margin. The original margin is captured once, so repeated inset dispatches do not
     * accumulate. The pill keeps its own 16dp margin on top of the inset.
     */
    private fun applyBarInsets(bar: View) {
        val initialParams = bar.layoutParams as? ViewGroup.MarginLayoutParams ?: return
        val baseMarginBottom = initialParams.bottomMargin
        ViewCompat.setOnApplyWindowInsetsListener(bar) { v, insets ->
            val bars = insets.getInsets(INSET_TYPES)
            val params = v.layoutParams as? ViewGroup.MarginLayoutParams
            if (params != null) {
                val target = baseMarginBottom + bars.bottom
                if (params.bottomMargin != target) {
                    params.bottomMargin = target
                    v.layoutParams = params
                }
            }
            insets
        }
        ViewCompat.requestApplyInsets(bar)
    }

    /**
     * Adds the bottom inset to the scroll container's bottom padding, so the last content can
     * still scroll fully above the floating bar. The padding from XML is remembered so repeated
     * dispatches do not accumulate.
     */
    fun applyBottomInset(scrollView: View) {
        applyInsets(scrollView, applyTop = false, applyBottom = true)
    }

    /** Adds the top inset (and side insets) to a screen root's padding, keeping its own padding. */
    fun applyTopInset(rootView: View) {
        applyInsets(rootView, applyTop = true, applyBottom = false)
    }

    /** Adds top, bottom and side insets to a screen root, for screens without a floating bar. */
    fun applyScreenInsets(rootView: View) {
        applyInsets(rootView, applyTop = true, applyBottom = true)
    }

    private fun applyInsets(view: View, applyTop: Boolean, applyBottom: Boolean) {
        val baseLeft = view.paddingLeft
        val baseTop = view.paddingTop
        val baseRight = view.paddingRight
        val baseBottom = view.paddingBottom
        ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
            val bars = insets.getInsets(INSET_TYPES)
            val left = baseLeft + bars.left
            val top = baseTop + if (applyTop) bars.top else 0
            val right = baseRight + bars.right
            val bottom = baseBottom + if (applyBottom) bars.bottom else 0
            if (v.paddingLeft != left || v.paddingTop != top ||
                v.paddingRight != right || v.paddingBottom != bottom
            ) {
                v.setPadding(left, top, right, bottom)
            }
            insets
        }
        ViewCompat.requestApplyInsets(view)
    }
}
