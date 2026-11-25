/**
 * Primary UI activity for manual message inspection, permission onboarding, and scam alert display.
 * Handles paste, text-selection, and share intents, coordinates background pipeline runs, and streams advice.
 * Renders risk meters, highlighted cues, link indicators, and localized recommendations.
 */
package org.ps3.sentinel.ui

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.ps3.sentinel.R
import org.ps3.sentinel.SentinelApp
import org.ps3.sentinel.core.Evidence
import org.ps3.sentinel.core.PROMOTION_ADVICE
import org.ps3.sentinel.core.SmsResult
import org.ps3.sentinel.core.ProcessedUrl
import org.ps3.sentinel.core.composeStreamingAdvice
import org.ps3.sentinel.core.isPlainPromotion
import org.ps3.sentinel.core.templateAdvice
import org.ps3.sentinel.core.templateSteps
import org.ps3.sentinel.ml.CpuFeatures
import org.ps3.sentinel.sms.MmsWatcher
import org.ps3.sentinel.sms.PendingMessageStore
import org.ps3.sentinel.sms.SmsReceiver
import org.ps3.sentinel.databinding.ActivityMainBinding
import org.ps3.sentinel.databinding.ItemLinkBinding
import java.util.Locale

/**
 * Main application screen providing message input, analysis status, and scam risk visualization.
 *
 * Manages onboarding and loading overlays, initiates pipeline execution, and displays
 * risk scores, cue highlights, URL classifications, and streaming safety recommendations.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val app get() = SentinelApp.instance

    private var isAnalysing = false
    private var loadingStartElapsedMs: Long = 0L
    private var isLoadingOverlayShown = false
    private var pendingOnboarding = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        if (savedInstanceState == null) {
            retainedResult = null
        }
        BottomBar.attach(this, binding.root, Tab.CHECK)
        updateBottomBarVisibility()
        applySystemBarInsets()
        setGlowColor(R.color.brand)
        loadingStartElapsedMs = SystemClock.elapsedRealtime()
        setupLoadingOverlay(savedInstanceState == null && !intent.hasExtra(EXTRA_SMS_ID))
        if (isLoadingOverlayShown) {
            lifecycleScope.launch {
                delay(4000L)
                hideLoadingOverlay()
            }
        }

        val store = app.modelStore
        store.onVerificationFinished = {
            runOnUiThread { updateModelStatus() }
        }
        app.markUiOpened()
        updateModelStatus()
        // The SMS model loads in the background (SentinelApp); refresh the status line once it is ready.
        lifecycleScope.launch {
            withContext(Dispatchers.Default) { app.pipeline?.warmUp() }
            updateModelStatus()
            if (isLoadingOverlayShown) {
                val elapsedMs = SystemClock.elapsedRealtime() - loadingStartElapsedMs
                if (elapsedMs < 600L) {
                    delay(600L - elapsedMs)
                }
                hideLoadingOverlay()
            }
        }

        val isSmsAlertIntent = intent.hasExtra(EXTRA_SMS_ID)
        if (!isOnboardingDone() && isSmsAlertIntent) {
            setOnboardingDone()
        }
        val showOnboarding = !isOnboardingDone() && !isSmsAlertIntent
        setupOnboardingOverlay(showOnboarding)
        if (!showOnboarding) {
            checkAndRequestPermissions()
        }

        binding.btnAnalyse.setOnClickListener {
            val text = binding.etMessage.text?.toString()?.trim() ?: ""
            if (text.isNotEmpty()) {
                val (capped, wasCut) = capManualInput(text)
                if (wasCut) {
                    binding.etMessage.setText(capped)
                    binding.etMessage.setSelection(capped.length)
                    showShortMessage(R.string.input_text_too_long)
                }
                analyseMessage(capped)
            }
        }

        binding.btnPaste.setOnClickListener {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            val clip = clipboard?.primaryClip
            if (clip != null && clip.itemCount > 0) {
                val pasted = clip.getItemAt(0)?.text?.toString()
                if (!pasted.isNullOrEmpty()) {
                    val (capped, wasCut) = capManualInput(pasted)
                    binding.etMessage.setText(capped)
                    binding.etMessage.setSelection(capped.length)
                    if (wasCut) showShortMessage(R.string.input_text_too_long)
                }
            }
        }

        binding.btnCheckAgain.setOnClickListener {
            val text = binding.etMessage.text?.toString()?.trim() ?: ""
            if (text.isNotEmpty() && !isAnalysing) {
                val (capped, wasCut) = capManualInput(text)
                if (wasCut) {
                    binding.etMessage.setText(capped)
                    binding.etMessage.setSelection(capped.length)
                    showShortMessage(R.string.input_text_too_long)
                }
                analyseMessage(capped)
            }
        }

        if (savedInstanceState == null) {
            handleIntent(intent)
        } else {
            restoreAfterRecreate(savedInstanceState)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_MESSAGE, binding.etMessage.text?.toString())
        outState.putBoolean(STATE_ANALYSING, isAnalysing)
    }

    private fun restoreAfterRecreate(state: Bundle) {
        val text = state.getString(STATE_MESSAGE)
        if (!text.isNullOrEmpty()) {
            binding.etMessage.setText(text)
            binding.etMessage.setSelection(text.length)
        }
        // Never re-run analysis after a recreate: the previous native Llama generation may still
        // be running under ExecutorchGate, and a second run would contend with it. Restore the
        // text only and leave the screen idle so the user can tap Check message again.
        val rendered = retainedResult
        if (rendered != null) {
            renderResults(
                rendered.text,
                rendered.evidence,
                rendered.advice,
                rendered.adviceSource,
                rendered.timings,
                rendered.smsResult
            )
        }
    }

    private fun isOverlayVisible(): Boolean {
        val onboarding = findViewById<View>(R.id.onboardingOverlay)?.visibility == View.VISIBLE
        val loading = findViewById<View>(R.id.loadingOverlay)?.visibility == View.VISIBLE
        return onboarding || loading
    }

    private fun updateBottomBarVisibility() {
        val bottomBar = findViewById<View>(R.id.bottomBar) ?: return
        bottomBar.visibility = if (isOverlayVisible()) View.GONE else View.VISIBLE
    }

    private fun maybeOpenGuide() {
        val prefs = getSharedPreferences(FirstRun.PREFS_NAME, Context.MODE_PRIVATE)
        if (!prefs.getBoolean(FirstRun.GUIDE_SHOWN, false)) {
            startActivity(Intent(this, GuideActivity::class.java))
        }
    }

    override fun onResume() {
        super.onResume()
        app.markUiOpened()
        updateModelStatus()
        // Re-check files that arrived while the process was alive. Presence checks only;
        // loaded models are not re-hashed, and warmUp is a no-op once the classifier is up.
        lifecycleScope.launch {
            withContext(Dispatchers.Default) {
                app.refreshModelsOnResume()
                app.pipeline?.warmUp()
            }
            updateModelStatus()
        }
    }

    override fun onDestroy() {
        app.modelStore.onVerificationFinished = null
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.hasExtra(EXTRA_SMS_ID) && !isOnboardingDone()) {
            setOnboardingDone()
            hideOnboardingOverlay()
            checkAndRequestPermissions()
        }
        handleIntent(intent)
    }

    private fun isOnboardingDone(): Boolean {
        return getSharedPreferences(FirstRun.PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(FirstRun.ONBOARDING_DONE, false)
    }

    private fun setOnboardingDone() {
        getSharedPreferences(FirstRun.PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(FirstRun.ONBOARDING_DONE, true)
            .apply()
    }

    private fun applySystemBarInsets() {
        val overlay = findViewById<View>(R.id.onboardingOverlay)
        if (overlay != null) {
            ViewCompat.setOnApplyWindowInsetsListener(overlay) { v, insets ->
                val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }
        val loadingOverlay = findViewById<View>(R.id.loadingOverlay)
        if (loadingOverlay != null) {
            ViewCompat.setOnApplyWindowInsetsListener(loadingOverlay) { v, insets ->
                val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }
        val scroll = binding.nestedScrollView
        BottomBar.applyScreenInsets(scroll)
    }

    private fun setupOnboardingOverlay(show: Boolean) {
        val overlay = findViewById<View>(R.id.onboardingOverlay)
        if (overlay == null) {
            updateBottomBarVisibility()
            return
        }
        setGlowColor(R.color.brand)
        findViewById<View>(R.id.viewOnboardingGlow)?.let { applyCenteredGlow(it, R.color.brand) }
        val page1 = findViewById<View>(R.id.onboardingPage1)
        val page2 = findViewById<View>(R.id.onboardingPage2)
        val dot1 = findViewById<View>(R.id.onboardingDot1)
        val dot2 = findViewById<View>(R.id.onboardingDot2)
        findViewById<View>(R.id.btnAllowSmsAccess)?.setOnClickListener {
            page1?.visibility = View.GONE
            page2?.visibility = View.VISIBLE
            dot1?.setBackgroundTintList(ColorStateList.valueOf(ContextCompat.getColor(this, R.color.text_3)))
            dot2?.setBackgroundTintList(ColorStateList.valueOf(ContextCompat.getColor(this, R.color.brand)))
        }
        findViewById<View>(R.id.btnNotNow)?.setOnClickListener {
            setOnboardingDone()
            hideOnboardingOverlay()
            maybeOpenGuide()
        }
        findViewById<View>(R.id.btnOnboardingContinue)?.setOnClickListener {
            setOnboardingDone()
            hideOnboardingOverlay()
            checkAndRequestPermissions()
            maybeOpenGuide()
        }
        if (show && isLoadingOverlayShown) {
            pendingOnboarding = true
            overlay.visibility = View.GONE
        } else if (show) {
            pendingOnboarding = false
            overlay.visibility = View.VISIBLE
            page1?.visibility = View.VISIBLE
            page2?.visibility = View.GONE
            dot1?.setBackgroundTintList(ColorStateList.valueOf(ContextCompat.getColor(this, R.color.brand)))
            dot2?.setBackgroundTintList(ColorStateList.valueOf(ContextCompat.getColor(this, R.color.text_3)))
        } else {
            pendingOnboarding = false
            overlay.visibility = View.GONE
        }
        updateBottomBarVisibility()
    }

    private fun setupLoadingOverlay(show: Boolean) {
        val overlay = findViewById<View>(R.id.loadingOverlay)
        if (overlay == null) {
            updateBottomBarVisibility()
            return
        }
        findViewById<View>(R.id.viewLoadingGlow)?.let { applyCenteredGlow(it, R.color.brand) }
        if (show) {
            isLoadingOverlayShown = true
            overlay.visibility = View.VISIBLE
            overlay.alpha = 1f
            updateLoadingRows()
        } else {
            isLoadingOverlayShown = false
            overlay.visibility = View.GONE
        }
        updateBottomBarVisibility()
    }

    private fun updateLoadingRows() {
        val urlState = findViewById<TextView>(R.id.tvLoadingUrlState) ?: return
        val smsState = findViewById<TextView>(R.id.tvLoadingSmsState) ?: return
        val llamaState = findViewById<TextView>(R.id.tvLoadingLlamaState) ?: return
        val store = try {
            app.modelStore
        } catch (e: Exception) {
            return
        }
        val urlReady = store.isUrlClassifierReady() && (app.urlClassifier?.isLoaded() == true)
        val smsStatusText = try {
            app.pipeline?.smsStatus
        } catch (e: Exception) {
            null
        } ?: store.smsStatus
        val smsReady = app.pipeline?.isSmsModelLoaded() == true || smsStatusText?.startsWith("loaded", ignoreCase = true) == true
        val llamaReady = store.isLlamaReady() && (app.llamaAdvisor?.isLoaded() == true)
        setLoadingRow(urlState, R.id.ivLoadingUrlIcon, urlReady)
        setLoadingRow(smsState, R.id.ivLoadingSmsIcon, smsReady)
        setLoadingRow(llamaState, R.id.ivLoadingLlamaIcon, llamaReady)
    }

    private fun setLoadingRow(stateView: TextView, iconResId: Int, ready: Boolean) {
        if (ready) {
            stateView.text = getString(R.string.loading_ready)
            stateView.setTextColor(ContextCompat.getColor(this, R.color.safe))
        } else {
            stateView.text = getString(R.string.loading_loading)
            stateView.setTextColor(ContextCompat.getColor(this, R.color.brand))
        }
        findViewById<ImageView>(iconResId)?.setColorFilter(ContextCompat.getColor(this, if (ready) R.color.safe else R.color.brand))
    }

    private fun hideLoadingOverlay() {
        if (!isLoadingOverlayShown) {
            return
        }
        isLoadingOverlayShown = false
        val overlay = findViewById<View>(R.id.loadingOverlay)
        if (overlay == null) {
            updateBottomBarVisibility()
            return
        }
        overlay.animate().alpha(0f).setDuration(200L).withEndAction {
            overlay.visibility = View.GONE
            overlay.alpha = 1f
            if (pendingOnboarding) {
                pendingOnboarding = false
                setupOnboardingOverlay(true)
            }
            updateBottomBarVisibility()
        }.start()
    }

    private fun hideOnboardingOverlay() {
        findViewById<View>(R.id.onboardingOverlay)?.visibility = View.GONE
        updateBottomBarVisibility()
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return
        lifecycleScope.launch {
            val intentReceivedMs = SystemClock.elapsedRealtime()
            var fromNotification = false
            var pendingMessageId: String? = null

            var messageToAnalyse: String? = null

            // 1. Opened from SmsReceiver notification: body comes from the durable
            // PendingMessageStore (cold start) or the in-memory fast path. Peek
            // without deleting so a rejected analysis keeps the stored body.
            if (intent.hasExtra(EXTRA_SMS_ID)) {
                val messageId = intent.getStringExtra(EXTRA_SMS_ID)
                if (messageId == null) {
                    showMissingPendingMessage()
                    return@launch
                }
                if (intent.getStringExtra(EXTRA_SMS_UNSAVED) == "true") {
                    showMissingPendingMessage(getString(R.string.pending_message_unsaved))
                    return@launch
                }
                val body = peekPendingBody(messageId)
                if (body == null) {
                    showMissingPendingMessage()
                    return@launch
                }
                messageToAnalyse = body
                pendingMessageId = messageId
                fromNotification = true
            }

            // 2. Share target (ACTION_SEND with text/plain)
            if (messageToAnalyse == null && Intent.ACTION_SEND == intent.action && intent.type == "text/plain") {
                messageToAnalyse = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            }

            // 3. Text-selection menu ("Check with Sentinel" on selected text in any app)
            if (messageToAnalyse == null && Intent.ACTION_PROCESS_TEXT == intent.action && intent.type == "text/plain") {
                messageToAnalyse = intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)?.toString()
            }

            // SEC-04: ignore blank/oversized shares and new shares while an analysis is running.
            // Evaluated before any delete so a rejected notification text stays stored.
            val reason = sharedTextRejectionReason(messageToAnalyse, isAnalysing)
            if (reason != null) {
                showShortMessage(when (reason) {
                    "busy" -> R.string.analysis_in_progress
                    "blank" -> R.string.share_text_blank
                    else -> R.string.share_text_too_long
                })
                return@launch
            }

            val acceptedText = messageToAnalyse ?: return@launch
            if (fromNotification) {
                val deltaMs = SystemClock.elapsedRealtime() - intentReceivedMs
                Log.i("PS3Timing", "intent_to_analysis_start_ms=$deltaMs")
            }
            binding.etMessage.setText(acceptedText)
            analyseMessage(acceptedText, pendingMessageId)
        }
    }

    private suspend fun peekPendingBody(messageId: String): String? = withContext(Dispatchers.IO) {
        val persistent = try {
            PendingMessageStore.instance(this@MainActivity).peek(messageId)
        } catch (e: Exception) {
            Log.w("PS3Sms", "MainActivity: pending store read failed: ${e::class.simpleName}: ${e.message}", e)
            null
        }
        persistent ?: SmsReceiver.messageStore[messageId]
    }

    private suspend fun deletePendingBody(messageId: String) = withContext(Dispatchers.IO) {
        try {
            PendingMessageStore.instance(this@MainActivity).delete(messageId)
        } catch (e: Exception) {
            Log.w("PS3Sms", "MainActivity: pending store delete failed: ${e::class.simpleName}: ${e.message}", e)
        }
        SmsReceiver.messageStore.remove(messageId)
    }

    private fun showMissingPendingMessage(messageText: String = getString(R.string.pending_message_missing)) {
        binding.progressBar.visibility = View.GONE
        binding.btnAnalyse.isEnabled = true
        isAnalysing = false
        binding.cardResults.visibility = View.VISIBLE
        binding.tvRiskLevel.text = getString(R.string.pill_unavailable)
        binding.tvRiskLevel.backgroundTintList = null
        binding.tvRiskLevel.setBackgroundResource(R.drawable.bg_chip)
        binding.tvRiskLevel.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        binding.tvRiskLabel.text = getString(R.string.headline_expired)
        binding.tvRiskLabel.setTextColor(ContextCompat.getColor(this, R.color.text))
        binding.tvEvidenceLabel.visibility = View.GONE
        binding.tvRiskScore.text = ""
        setGlowColor(R.color.text_3)
        renderMeter(0, ContextCompat.getColor(this, R.color.text_3))
        binding.btnCheckAgain.visibility = View.GONE
        binding.tvSmsModel.visibility = View.GONE
        binding.tvHighlightedMessage.text = messageText
        binding.tvAdvice.text = messageText
        binding.tvAdviceSource.text = ""
        binding.tvTimings.text = ""
        binding.layoutLinksContainer.removeAllViews()
        binding.tvLinksHeader.visibility = View.GONE
        scrollResultsIntoView()
    }

    private fun showModelsStillLoading() {
        binding.tvRiskLevel.text = getString(R.string.pill_not_checked)
        binding.tvRiskLevel.backgroundTintList = null
        binding.tvRiskLevel.setBackgroundResource(R.drawable.bg_chip)
        binding.tvRiskLevel.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        binding.tvRiskLabel.text = getString(R.string.headline_not_checked)
        binding.tvRiskLabel.setTextColor(ContextCompat.getColor(this, R.color.text))
        binding.tvEvidenceLabel.visibility = View.GONE
        binding.tvRiskScore.text = ""
        setGlowColor(R.color.text_3)
        renderMeter(0, ContextCompat.getColor(this, R.color.text_3))
        binding.btnCheckAgain.visibility = View.VISIBLE
        binding.tvSmsModel.visibility = View.GONE
        binding.tvHighlightedMessage.text = ""
        binding.tvAdvice.text = getString(R.string.models_still_loading)
        binding.tvAdviceSource.text = ""
        binding.tvTimings.text = ""
        binding.layoutLinksContainer.removeAllViews()
        binding.tvLinksHeader.visibility = View.GONE
    }

    private fun setGlowColor(@androidx.annotation.ColorRes colorRes: Int) {
        val color = ContextCompat.getColor(this, colorRes)
        val start = Color.argb(115, Color.red(color), Color.green(color), Color.blue(color))
        val drawable = GradientDrawable()
        drawable.setShape(GradientDrawable.RECTANGLE)
        drawable.setGradientType(GradientDrawable.RADIAL_GRADIENT)
        drawable.setGradientCenter(0.5f, 0f)
        drawable.setColors(intArrayOf(start, Color.TRANSPARENT))
        val glow = binding.viewGlow
        glow.background = drawable
        glow.post {
            drawable.setGradientRadius((glow.width * 0.8f).toFloat())
            glow.invalidate()
        }
    }

    private fun applyCenteredGlow(view: View, @androidx.annotation.ColorRes colorRes: Int) {
        val color = ContextCompat.getColor(this, colorRes)
        val start = Color.argb(115, Color.red(color), Color.green(color), Color.blue(color))
        val drawable = GradientDrawable()
        drawable.setShape(GradientDrawable.RECTANGLE)
        drawable.setGradientType(GradientDrawable.RADIAL_GRADIENT)
        drawable.setGradientCenter(0.5f, 0.5f)
        drawable.setColors(intArrayOf(start, Color.TRANSPARENT))
        view.background = drawable
        view.post {
            drawable.setGradientRadius((view.width * 0.5f).toFloat())
            view.invalidate()
        }
    }

    private fun renderMeter(filledCount: Int, levelColor: Int) {
        val container = binding.layoutRiskMeter
        container.removeAllViews()
        val emptyColor = ContextCompat.getColor(this, R.color.surface_2)
        val density = resources.displayMetrics.density
        for (i in 0 until 10) {
            val segment = View(this)
            val params = LinearLayout.LayoutParams(0, (8 * density).toInt(), 1f)
            if (i < 9) {
                params.marginEnd = (4 * density).toInt()
            }
            segment.layoutParams = params
            val drawable = GradientDrawable()
            drawable.cornerRadius = 4 * density
            drawable.setColor(if (i < filledCount) levelColor else emptyColor)
            segment.background = drawable
            container.addView(segment)
        }
    }

    companion object {
        const val EXTRA_SMS_ID = "extra_sms_id"
        private const val STATE_MESSAGE = "state_message"
        private const val STATE_ANALYSING = "state_analysing"
        private var retainedResult: RenderedResult? = null
        const val EXTRA_SMS_UNSAVED = "extra_sms_unsaved"
        const val MISSING_PENDING_MESSAGE_TEXT: String =
            "This message is no longer stored. Paste it to check it again."
        const val UNSAVED_PENDING_MESSAGE_TEXT: String =
            "This message could not be saved. Paste it to check it again."
        private const val PERMISSION_REQUEST_CODE = 1001
        private const val PREFS_SETTINGS = "ps3_settings"
        const val KEY_NOTIF_DISCLAIMER_DISMISSED = "notif_disclaimer_dismissed"
        // About 12 SMS segments; caps shared text so a malicious or buggy share target cannot
        // drive repeated URL extraction, cue matching and Llama inference (SEC-04).
        const val MAX_SHARED_TEXT_LENGTH = 2000

        private data class RenderedResult(
            val text: String,
            val evidence: Evidence,
            val smsResult: SmsResult?,
            val timings: org.ps3.sentinel.PipelineTimings,
            val advice: String,
            val adviceSource: String
        )

        /**
         * Returns a short reason why [text] should not be analysed, or null when it is acceptable.
         * Pure and testable: blank or over MAX_SHARED_TEXT_LENGTH, or a share while analysing (SEC-04).
         */
        fun sharedTextRejectionReason(text: String?, isAnalysing: Boolean): String? {
            if (isAnalysing) return "busy"
            // No text at all (for example the launcher intent) is not an error; there is nothing to analyse.
            if (text == null) return null
            if (text.isBlank()) return "blank"
            if (text.length > MAX_SHARED_TEXT_LENGTH) return "too_long"
            return null
        }

        /**
         * Truncates manual input to [MAX_SHARED_TEXT_LENGTH] if necessary.
         *
         * @param text Raw input text from the input field or clipboard.
         * @return Pair containing the capped string and a boolean indicating if truncation occurred.
         */
        fun capManualInput(text: String): Pair<String, Boolean> {
            return if (text.length > MAX_SHARED_TEXT_LENGTH) {
                text.take(MAX_SHARED_TEXT_LENGTH) to true
            } else {
                text to false
            }
        }

        /**
         * Checks whether the pending body should be deleted from persistent store after rendering.
         *
         * Delete only after detection is rendered; rejected or unrendered texts stay stored.
         */
        fun shouldDeletePendingBodyAfterRender(pendingMessageId: String?): Boolean {
            return !pendingMessageId.isNullOrBlank()
        }

        /**
         * Headline resource for the verdict pill. A plain promotion keeps the
         * amber MEDIUM pill but gets [R.string.headline_promotion].
         * Pure and testable: [isPromotion] is isPlainPromotion(text, evidence).
         */
        fun headlineResFor(level: String, isPromotion: Boolean): Int {
            return when {
                level == "high" -> R.string.headline_scam
                level == "medium" && isPromotion -> R.string.headline_promotion
                level == "medium" -> R.string.headline_suspicious
                else -> R.string.headline_safe
            }
        }

        /** Headline resource for the message and evidence. Pure and testable. */
        fun headlineResFor(text: String?, evidence: Evidence): Int {
            return headlineResFor(evidence.level, isPlainPromotion(text, evidence))
        }
    }

    private fun updateModelStatus() {
        updateLoadingRows()
    }

    private fun hideKeyboard() {
        val token = currentFocus?.windowToken ?: binding.etMessage.windowToken
        binding.etMessage.clearFocus()
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
        imm?.hideSoftInputFromWindow(token, 0)
    }

    /**
     * Returns "ta" or "hi" when the fixed advice must replace Llama, else null.
     * Uses the per-app language when one is set, otherwise the resolved resources locale.
     */
    private fun fixedAdviceLanguage(): String? {
        val locales = AppCompatDelegate.getApplicationLocales()
        val tags = (0 until locales.size()).mapNotNull { index -> locales[index]?.toLanguageTag() }
        return AdviceText.fixedAdviceLanguage(tags, resources.configuration.locales[0].language)
    }

    private fun scrollResultsIntoView() {
        binding.nestedScrollView.post {
            binding.nestedScrollView.smoothScrollTo(0, binding.cardResults.top)
        }
    }

    private fun analyseMessage(text: String, pendingMessageId: String? = null) {
        // Refuse to analyse when the shared rules are missing: verdicts would be meaningless.
        if (app.rulesLoadError != null) {
            updateModelStatus()
            return
        }
        hideKeyboard()

        binding.progressBar.visibility = View.VISIBLE
        binding.btnAnalyse.isEnabled = false
        binding.cardResults.visibility = View.GONE
        binding.layoutLinksContainer.removeAllViews()
        binding.tvSmsModel.visibility = View.GONE

        isAnalysing = true
        retainedResult = null
        scrollResultsIntoView()
        lifecycleScope.launch {
            app.beginUiAnalysis()
            try {
                binding.tvAdvice.text = getString(R.string.analysing_message)
                binding.tvRiskLevel.text = getString(R.string.pill_checking)
                binding.tvRiskLevel.backgroundTintList = null
                binding.tvRiskLevel.setBackgroundResource(R.drawable.bg_chip)
                binding.tvRiskLevel.setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_2))
                binding.tvRiskLabel.text = getString(R.string.headline_checking)
                binding.tvRiskLabel.setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text))
                binding.tvEvidenceLabel.visibility = View.GONE
                binding.tvRiskScore.text = ""
                setGlowColor(R.color.text_3)
                renderMeter(0, ContextCompat.getColor(this@MainActivity, R.color.text_3))
                binding.btnCheckAgain.visibility = View.GONE
                binding.tvHighlightedMessage.text = ""
                binding.cardResults.visibility = View.VISIBLE
                scrollResultsIntoView()

                val pipeline = withContext(Dispatchers.Default) {
                    var nextPipeline = app.pipeline
                    val deadlineMs = SystemClock.elapsedRealtime() + 10000L
                    while (nextPipeline == null && SystemClock.elapsedRealtime() < deadlineMs) {
                        try {
                            Thread.sleep(100L)
                        } catch (e: InterruptedException) {
                            Thread.currentThread().interrupt()
                            break
                        }
                        nextPipeline = app.pipeline
                    }
                    nextPipeline
                }
                if (pipeline == null) {
                    showModelsStillLoading()
                    updateModelStatus()
                    return@launch
                }

                // detect() forwards wait on the exclusive gate while a Llama load runs (about 0.5 s),
                // so starting analysis on open never overlaps the UI-gated load.
                val detection = withContext(Dispatchers.Default) { pipeline.detect(text) }
                renderDetection(text, detection.evidence, detection.smsResult, detection.timingsMs)
                pendingMessageId?.let { id ->
                    if (shouldDeletePendingBodyAfterRender(id)) {
                        deletePendingBody(id)
                    }
                }
                scrollResultsIntoView()

                // Light-tier phones show the deterministic template immediately, then
                // generate with a smaller budget and a longer timeout. Tokens are not
                // streamed for them: the template is replaced only when Llama finishes.
                // Plain promotions never call Llama, so they skip this.
                val isPromotion = isPlainPromotion(text, detection.evidence)
                val tier = CpuFeatures.currentTier(this@MainActivity)
                // Tamil and Hindi show fixed localized advice and never call Llama.
                val localizedAdvice = if (fixedAdviceLanguage() != null) {
                    AdviceText.localizedAdvice(detection.evidence, isPromotion) { resId -> getString(resId) }
                } else {
                    null
                }
                val templateWhileGenerating =
                    localizedAdvice == null &&
                    !isPromotion &&
                    tier == CpuFeatures.Tier.LIGHT &&
                        detection.evidence.level in setOf("medium", "high")
                if (localizedAdvice != null) {
                    binding.tvAdvice.text = localizedAdvice
                    binding.tvAdviceSource.text = getString(R.string.advice_source_template)
                } else if (templateWhileGenerating) {
                    binding.tvAdvice.text = templateAdvice(detection.evidence)
                    binding.tvAdviceSource.text = getString(R.string.advice_ai_still_writing)
                } else if (isPromotion) {
                    binding.tvAdvice.text = PROMOTION_ADVICE
                    binding.tvAdviceSource.text = getString(R.string.advice_source_template)
                }
                // Non-LIGHT tiers show the fixed steps at once, so the user never
                // waits for Llama to decode generic steps that guard() would
                // otherwise backfill anyway.
                val stepsWhileStreaming =
                    localizedAdvice == null &&
                    !isPromotion &&
                        tier != CpuFeatures.Tier.LIGHT &&
                        detection.evidence.level in setOf("medium", "high")
                val fixedSteps = if (stepsWhileStreaming) templateSteps(detection.evidence) else emptyList()
                if (stepsWhileStreaming) {
                    binding.tvAdvice.text = composeStreamingAdvice("", fixedSteps, getString(R.string.analysing_message))
                }
                // Tokens arrive pre-filtered: Pipeline releases only sentences
                // that pass guard() for this evidence, so tvAdvice never shows
                // unguarded Llama text.
                val streamedText = StringBuilder()
                val streamToken: ((String) -> Unit)? = if (templateWhileGenerating || localizedAdvice != null) {
                    null
                } else {
                    { filteredText ->
                        lifecycleScope.launch(Dispatchers.Main) {
                            if (stepsWhileStreaming) {
                                streamedText.append(filteredText)
                                binding.tvAdvice.text = composeStreamingAdvice(
                                    streamedText.toString(), fixedSteps, getString(R.string.analysing_message)
                                )
                            } else if (binding.tvAdvice.text == getString(R.string.analysing_message)) {
                                binding.tvAdvice.text = filteredText
                            } else {
                                binding.tvAdvice.append(filteredText)
                            }
                        }
                    }
                }
                val adviceResult = withContext(Dispatchers.Default) {
                    pipeline.advise(text, detection.evidence, streamToken, localizedAdvice)
                }
                val timings = detection.timingsMs.copy(
                    advisorMs = adviceResult.advisorMs,
                    totalMs = detection.timingsMs.totalMs + adviceResult.advisorMs,
                    decodeTokensPerSec = adviceResult.decodeTokensPerSec
                )
                retainedResult = RenderedResult(
                    text = text,
                    evidence = detection.evidence,
                    smsResult = detection.smsResult,
                    timings = timings,
                    advice = adviceResult.advice,
                    adviceSource = adviceResult.adviceSource
                )
                renderAdvice(adviceResult.advice, adviceResult.adviceSource, timings)
                scrollResultsIntoView()
                updateModelStatus()
            } finally {
                app.endUiAnalysis()
                binding.progressBar.visibility = View.GONE
                binding.btnAnalyse.isEnabled = true
                isAnalysing = false
            }
        }
    }

    private fun showShortMessage(@StringRes resId: Int) {
        Toast.makeText(this, resId, Toast.LENGTH_SHORT).show()
    }

    private fun renderDetection(
        text: String,
        evidence: Evidence,
        smsResult: SmsResult?,
        timings: org.ps3.sentinel.PipelineTimings
    ) {
        val isPromotion = isPlainPromotion(text, evidence)
        val headlineRes = headlineResFor(evidence.level, isPromotion)
        val (levelText, levelColorRes) = when (evidence.level) {
            "high" -> Pair(
                getString(R.string.pill_high_risk),
                R.color.danger
            )
            "medium" -> Pair(
                getString(R.string.pill_suspicious),
                R.color.warn
            )
            else -> Pair(
                getString(R.string.pill_looks_safe),
                R.color.safe
            )
        }
        val (chipBg, chipTextColor) = when (evidence.level) {
            "high" -> Pair(R.drawable.bg_chip_risk_high, ContextCompat.getColor(this, R.color.risk_high_text))
            "medium" -> Pair(R.drawable.bg_chip_risk_medium, ContextCompat.getColor(this, R.color.risk_medium_text))
            else -> Pair(R.drawable.bg_chip_risk_low, ContextCompat.getColor(this, R.color.risk_low_text))
        }
        val levelColor = ContextCompat.getColor(this, levelColorRes)
        binding.tvRiskLevel.text = levelText
        binding.tvRiskLevel.backgroundTintList = null
        binding.tvRiskLevel.setBackgroundResource(chipBg)
        binding.tvRiskLevel.setTextColor(chipTextColor)
        binding.tvRiskLabel.text = getString(headlineRes)
        binding.tvRiskLabel.setTextColor(ContextCompat.getColor(this, R.color.text))
        val evidenceLabelRes = ResultTextLabels.evidenceLabelRes(evidence.label)
        binding.tvEvidenceLabel.text = if (evidenceLabelRes != null) {
            getString(evidenceLabelRes)
        } else {
            evidence.label.uppercase(Locale.US)
        }
        binding.tvEvidenceLabel.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        binding.tvEvidenceLabel.visibility = View.VISIBLE
        binding.tvRiskScore.text = getString(R.string.risk_score_format, evidence.risk)
        binding.tvRiskScore.setTextColor(levelColor)
        setGlowColor(levelColorRes)
        renderMeter(maxOf(1, Math.round(evidence.risk * 10).toInt()), levelColor)
        binding.btnCheckAgain.visibility = View.GONE
        if (smsResult != null && smsResult.probs.isNotEmpty()) {
            val prob = smsResult.probs[smsResult.label] ?: smsResult.probs.values.maxOrNull() ?: 0.0
            val smsClassRes = ResultTextLabels.evidenceLabelRes(smsResult.label)
            val smsClassLabel = if (smsClassRes != null) getString(smsClassRes) else smsResult.label
            binding.tvSmsModel.text = getString(R.string.sms_model_format, smsClassLabel, prob)
            binding.tvSmsModel.visibility = View.VISIBLE
        } else {
            binding.tvSmsModel.visibility = View.GONE
        }
        binding.tvHighlightedMessage.text = CueHighlighter.highlight(text, evidence.cueSpans) { levelColor }
        binding.layoutLinksContainer.removeAllViews()
        if (evidence.urls.isEmpty()) {
            binding.tvLinksHeader.visibility = View.GONE
        } else {
            binding.tvLinksHeader.visibility = View.VISIBLE
            val inflater = LayoutInflater.from(this)
            for (u in evidence.urls) {
                val linkBinding = ItemLinkBinding.inflate(inflater, binding.layoutLinksContainer, false)
                renderLinkItem(linkBinding, u)
                binding.layoutLinksContainer.addView(linkBinding.root)
            }
        }
        binding.tvAdvice.text = getString(R.string.analysing_message)
        binding.tvAdviceSource.text = ""
        val detectMs = timings.urlDetectionMs + timings.cuesMs + timings.smsDetectionMs + timings.fusionMs
        binding.tvTimings.text = getString(
            R.string.timings_detect_format,
            detectMs,
            timings.smsDetectionMs
        )
    }

    private fun renderAdvice(
        advice: String,
        adviceSource: String,
        timings: org.ps3.sentinel.PipelineTimings
    ) {
        binding.tvAdvice.text = advice
        binding.tvAdviceSource.text = when (adviceSource) {
            "llm" -> getString(R.string.advice_source_llama)
            "template_timeout" -> getString(R.string.advice_source_template_timeout)
            else -> getString(R.string.advice_source_template)
        }
        val tpsStr = timings.decodeTokensPerSec?.let {
            val stats = app.llamaAdvisor?.lastStats ?: org.ps3.sentinel.ml.LlamaAdvisor.lastStats
            val ttft = stats?.ttftMs?.let { t -> getString(R.string.ttft_suffix_format, t.toLong()) } ?: ""
            getString(R.string.decode_suffix_format, it, ttft)
        } ?: ""
        val detectMs = timings.urlDetectionMs + timings.cuesMs + timings.smsDetectionMs + timings.fusionMs
        binding.tvTimings.text = getString(
            R.string.timings_full_format,
            detectMs,
            timings.smsDetectionMs,
            timings.advisorMs,
            tpsStr,
            timings.totalMs
        )
    }

    private fun renderResults(
        text: String,
        evidence: Evidence,
        advice: String,
        adviceSource: String,
        timings: org.ps3.sentinel.PipelineTimings,
        smsResult: SmsResult? = null
    ) {
        renderDetection(text, evidence, smsResult, timings)
        renderAdvice(advice, adviceSource, timings)
    }

    private fun renderLinkItem(linkBinding: ItemLinkBinding, u: ProcessedUrl) {
        linkBinding.tvLinkUrl.text = u.url
        if (u.trusted) {
            linkBinding.tvLinkStatus.text = getString(R.string.link_trusted)
            linkBinding.tvLinkStatus.backgroundTintList = null
            linkBinding.tvLinkStatus.setBackgroundResource(R.drawable.bg_chip_risk_low)
            linkBinding.tvLinkStatus.setTextColor(ContextCompat.getColor(this, R.color.risk_low_text))
        } else {
            linkBinding.tvLinkStatus.text = getString(R.string.link_untrusted)
            linkBinding.tvLinkStatus.backgroundTintList = null
            linkBinding.tvLinkStatus.setBackgroundResource(R.drawable.bg_chip_risk_high)
            linkBinding.tvLinkStatus.setTextColor(ContextCompat.getColor(this, R.color.risk_high_text))
        }

        val labelText = ResultTextLabels.urlLabelRes(u.label)?.let { getString(it) } ?: u.label
        linkBinding.tvLinkProb.text = getString(
            R.string.link_prob_format,
            u.prob,
            labelText
        )

        if (u.indicators.isNotEmpty()) {
            linkBinding.tvLinkIndicators.visibility = View.VISIBLE
            val indicatorText = u.indicators.joinToString(", ") { indicator ->
                ResultTextLabels.urlIndicatorRes(indicator)?.let { getString(it) } ?: indicator
            }
            linkBinding.tvLinkIndicators.text = getString(
                R.string.link_indicators_format,
                indicatorText
            )
        } else {
            linkBinding.tvLinkIndicators.visibility = View.GONE
        }
    }

    private fun checkAndRequestPermissions() {
        val permissionsToRequest = mutableListOf<String>()

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) != PackageManager.PERMISSION_GRANTED) {
            permissionsToRequest.add(Manifest.permission.RECEIVE_SMS)
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_MMS) != PackageManager.PERMISSION_GRANTED) {
            permissionsToRequest.add(Manifest.permission.RECEIVE_MMS)
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS) != PackageManager.PERMISSION_GRANTED) {
            permissionsToRequest.add(Manifest.permission.READ_SMS)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                permissionsToRequest.add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        if (permissionsToRequest.isNotEmpty()) {
            ActivityCompat.requestPermissions(
                this,
                permissionsToRequest.toTypedArray(),
                PERMISSION_REQUEST_CODE
            )
        } else if (MmsWatcher.allowed(this)) {
            MmsWatcher.schedule(this)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (MmsWatcher.allowed(this)) {
                MmsWatcher.schedule(this)
            }
            val postNotifIndex = permissions.indexOf(Manifest.permission.POST_NOTIFICATIONS)
            if (postNotifIndex >= 0 && grantResults.getOrNull(postNotifIndex) != PackageManager.PERMISSION_GRANTED) {
                val prefs = getSharedPreferences(PREFS_SETTINGS, Context.MODE_PRIVATE)
                if (!prefs.getBoolean(KEY_NOTIF_DISCLAIMER_DISMISSED, false)) {
                    showNotificationPermissionDeniedDialog()
                }
            }
        }
    }

    private fun showNotificationPermissionDeniedDialog() {
        val prefs = getSharedPreferences(PREFS_SETTINGS, Context.MODE_PRIVATE)
        if (prefs.getBoolean(KEY_NOTIF_DISCLAIMER_DISMISSED, false)) {
            return
        }
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setMessage(R.string.settings_notifications_disclaimer)
            .setPositiveButton(R.string.dialog_open_settings) { _, _ ->
                prefs.edit().putBoolean(KEY_NOTIF_DISCLAIMER_DISMISSED, true).apply()
                startActivity(Intent(this, SettingsActivity::class.java))
            }
            .setNegativeButton(R.string.dialog_not_now) { _, _ ->
                prefs.edit().putBoolean(KEY_NOTIF_DISCLAIMER_DISMISSED, true).apply()
            }
            .setOnCancelListener {
                prefs.edit().putBoolean(KEY_NOTIF_DISCLAIMER_DISMISSED, true).apply()
            }
            .show()
    }
}
