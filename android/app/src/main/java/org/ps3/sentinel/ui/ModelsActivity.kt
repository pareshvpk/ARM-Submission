package org.ps3.sentinel.ui

import android.content.res.ColorStateList
import android.os.Bundle
import android.text.format.Formatter
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.ps3.sentinel.R
import org.ps3.sentinel.SentinelApp
import org.ps3.sentinel.core.Rules
import org.ps3.sentinel.databinding.ActivityModelsBinding
import org.ps3.sentinel.ml.CpuFeatures
import java.io.File

/**
 * Detailed overview of on-device machine learning models and hardware acceleration.
 *
 * Displays individual status cards for:
 * 1. Multilingual MiniLM SMS classifier (file name, load state, sequence length mode)
 * 2. Character-level CNN URL classifier (file name, load state)
 * 3. Llama 3.2 1B Instruct SpinQuant INT4 via ExecuTorch (load state, size)
 * 4. Model integrity verification results against APK manifest hashes
 * 5. Arm CPU architectural features and selected ExecuTorch kernel path
 */
class ModelsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityModelsBinding
    private val app get() = SentinelApp.instance

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivityModelsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyScreenInsets(binding.root)

        binding.toolbar.setNavigationOnClickListener {
            onBackPressedDispatcher.onBackPressed()
        }

        renderModels()
    }

    override fun onResume() {
        super.onResume()
        renderModels()
        lifecycleScope.launch {
            withContext(Dispatchers.Default) {
                app.refreshModelsOnResume()
                app.pipeline?.warmUp()
            }
            renderModels()
        }
    }

    private fun renderModels() {
        val store = try {
            app.modelStore
        } catch (_: Exception) {
            null
        }
        val pipeline = app.pipeline
        val flags = CpuFeatures.currentFlags()

        // Shared rules detector versions if available
        val rules = try {
            Rules.active()
        } catch (_: Exception) {
            null
        }

        // 1. SMS Classifier Card
        val smsFile = store?.smsModelFileFor(flags)
        val smsFileName = smsFile?.name ?: store?.fileNames?.smsModel ?: "sms_int8.pte"
        val smsDiskFile = store?.let { File(it.modelsDir, smsFileName) }
        val smsLoaded = pipeline?.isSmsModelLoaded() == true
        val smsStatusText = pipeline?.smsStatus ?: store?.smsStatus ?: ""

        val lengthMode = when {
            smsStatusText.contains("real length", ignoreCase = true) -> "Sequence length: dynamic length (real length)"
            smsStatusText.contains("padded", ignoreCase = true) -> "Sequence length: padded (128 tokens)"
            smsLoaded -> "Sequence length: loaded"
            else -> "Sequence length: not loaded"
        }

        binding.tvSmsFile.text = "Model file: $smsFileName"
        if (smsDiskFile != null && smsDiskFile.isFile && smsDiskFile.length() > 0L) {
            binding.tvSmsSize.text = "File size: ${Formatter.formatFileSize(this, smsDiskFile.length())}"
            binding.tvSmsSize.visibility = View.VISIBLE
        } else {
            binding.tvSmsSize.visibility = View.GONE
        }
        binding.tvSmsLengthMode.text = lengthMode
        setBadge(binding.tvSmsStatusBadge, smsLoaded)

        val smsVersion = rules?.detectorVersions?.get("sms_detector")
        if (!smsVersion.isNullOrEmpty()) {
            binding.tvSmsVersion.text = "Detector version: $smsVersion"
            binding.tvSmsVersion.visibility = View.VISIBLE
        } else {
            binding.tvSmsVersion.visibility = View.GONE
        }

        // 2. URL Classifier Card
        val urlFileName = store?.fileNames?.urlModel ?: "url_cnn_v2.pte"
        val urlDiskFile = store?.let { File(it.modelsDir, urlFileName) }
        val urlLoaded = app.urlClassifier?.isLoaded() == true || (store?.isUrlClassifierReady() == true)

        binding.tvUrlFile.text = "Model file: $urlFileName"
        if (urlDiskFile != null && urlDiskFile.isFile && urlDiskFile.length() > 0L) {
            binding.tvUrlSize.text = "File size: ${Formatter.formatFileSize(this, urlDiskFile.length())}"
            binding.tvUrlSize.visibility = View.VISIBLE
        } else {
            binding.tvUrlSize.visibility = View.GONE
        }
        setBadge(binding.tvUrlStatusBadge, urlLoaded)

        val urlVersion = rules?.detectorVersions?.get("url_detector")
        if (!urlVersion.isNullOrEmpty()) {
            binding.tvUrlVersion.text = "Detector version: $urlVersion"
            binding.tvUrlVersion.visibility = View.VISIBLE
        } else {
            binding.tvUrlVersion.visibility = View.GONE
        }

        // 3. Llama 3.2 1B Instruct Card
        val llamaFileName = store?.fileNames?.llamaModel ?: "llama.pte"
        val llamaDiskFile = store?.let { File(it.modelsDir, llamaFileName) }
        val llamaLoaded = app.llamaAdvisor?.isLoaded() == true

        binding.tvLlamaFile.text = "Model file: $llamaFileName"
        if (llamaDiskFile != null && llamaDiskFile.isFile && llamaDiskFile.length() > 0L) {
            binding.tvLlamaSize.text = "File size: ${Formatter.formatFileSize(this, llamaDiskFile.length())}"
            binding.tvLlamaSize.visibility = View.VISIBLE
        } else {
            binding.tvLlamaSize.visibility = View.GONE
        }
        setBadge(binding.tvLlamaStatusBadge, llamaLoaded)

        // 4. Model Integrity Card
        val isVerifying = store?.isVerifying == true
        val errors = store?.errors().orEmpty()
        val warnings = store?.warnings().orEmpty()
        val rehashFailed = store != null && store.rehashFailed(llamaFileName)

        when {
            isVerifying -> {
                binding.tvIntegrityStatusBadge.text = getString(R.string.models_status_verifying)
                binding.tvIntegrityStatusBadge.backgroundTintList = null
                binding.tvIntegrityStatusBadge.setBackgroundResource(R.drawable.bg_chip_brand)
                binding.tvIntegrityStatusBadge.setTextColor(ContextCompat.getColor(this, R.color.brand))
                binding.tvIntegrityDetails.text = "Verifying model SHA-256 integrity against APK hashesâ€¦"
            }
            errors.isNotEmpty() || rehashFailed -> {
                binding.tvIntegrityStatusBadge.text = getString(R.string.models_status_error)
                binding.tvIntegrityStatusBadge.backgroundTintList = null
                binding.tvIntegrityStatusBadge.setBackgroundResource(R.drawable.bg_chip_risk_high)
                binding.tvIntegrityStatusBadge.setTextColor(ContextCompat.getColor(this, R.color.risk_high_text))
                val detail = if (errors.isNotEmpty()) errors.joinToString("\n") else "Llama model failed SHA-256 verification"
                binding.tvIntegrityDetails.text = detail
            }
            warnings.isNotEmpty() -> {
                binding.tvIntegrityStatusBadge.text = getString(R.string.models_status_unverified)
                binding.tvIntegrityStatusBadge.backgroundTintList = null
                binding.tvIntegrityStatusBadge.setBackgroundResource(R.drawable.bg_chip_risk_medium)
                binding.tvIntegrityStatusBadge.setTextColor(ContextCompat.getColor(this, R.color.risk_medium_text))
                binding.tvIntegrityDetails.text = warnings.joinToString("\n")
            }
            else -> {
                binding.tvIntegrityStatusBadge.text = getString(R.string.models_status_verified)
                binding.tvIntegrityStatusBadge.backgroundTintList = null
                binding.tvIntegrityStatusBadge.setBackgroundResource(R.drawable.bg_chip_risk_low)
                binding.tvIntegrityStatusBadge.setTextColor(ContextCompat.getColor(this, R.color.risk_low_text))
                binding.tvIntegrityDetails.text = "All verified against expected APK manifest hashes."
            }
        }

        // 5. Arm CPU Card
        val onText = getString(R.string.cpu_on)
        val offText = getString(R.string.cpu_off)
        binding.tvCpuDotProduct.text = if (flags.asimddp) onText else offText
        binding.tvCpuI8mm.text = if (flags.i8mm) onText else offText
        binding.tvCpuSme2.text = if (flags.sme2) onText else offText

        val bestKernel = CpuFeatures.bestKernelPath(flags)
        binding.tvCpuKernelPath.text = bestKernel
    }

    private fun setBadge(badge: android.widget.TextView, loaded: Boolean) {
        if (loaded) {
            badge.text = getString(R.string.models_status_loaded)
            badge.backgroundTintList = null
            badge.setBackgroundResource(R.drawable.bg_chip_risk_low)
            badge.setTextColor(ContextCompat.getColor(this, R.color.risk_low_text))
        } else {
            badge.text = getString(R.string.models_status_not_loaded)
            badge.backgroundTintList = null
            badge.setBackgroundResource(R.drawable.bg_chip)
            badge.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        }
    }
}
