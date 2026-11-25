package org.ps3.sentinel.ui

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.format.Formatter
import android.util.Log
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.os.LocaleListCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.ps3.sentinel.R
import org.ps3.sentinel.a11y.ScreenCheckService
import org.ps3.sentinel.databinding.ActivitySettingsBinding
import org.ps3.sentinel.sms.SmsReceiver
import org.ps3.sentinel.sms.notificationsUsable
import java.io.File

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private var storageJob: Job? = null
    private var lastNotificationsUsable: Boolean? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyTopInset(binding.root)
        BottomBar.applyBottomInset(binding.nestedScrollView)

        setupLanguage()
        showVersion()

        BottomBar.attach(this, binding.root, Tab.SETTINGS)

        binding.cardScreenCheck.setOnClickListener {
            handleOpenAccessibilitySettings()
        }

        binding.btnScreenCheckSettings.setOnClickListener {
            handleOpenAccessibilitySettings()
        }

        binding.cardUsageGuide.setOnClickListener {
            startActivity(Intent(this, GuideActivity::class.java))
        }

        binding.cardModels.setOnClickListener {
            startActivity(Intent(this, ModelsActivity::class.java))
        }

        binding.btnTurnOnNotifications.setOnClickListener {
            handleTurnOnNotifications()
        }

        binding.btnShowWelcomeGuide.setOnClickListener {
            getSharedPreferences(FirstRun.PREFS_NAME, MODE_PRIVATE)
                .edit()
                .putBoolean(FirstRun.ONBOARDING_DONE, false)
                .putBoolean(FirstRun.GUIDE_SHOWN, false)
                .apply()
            Toast.makeText(this, R.string.settings_guide_reset, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onResume() {
        super.onResume()
        computeStorage()
        updateNotificationCard()
        updateScreenCheckCard()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_CODE_NOTIFICATIONS) {
            updateNotificationCard()
        }
    }

    private fun updateScreenCheckCard() {
        val enabled = isScreenCheckEnabled(this)
        binding.tvScreenCheckStatus.text = if (enabled) {
            getString(R.string.settings_screen_check_status_on)
        } else {
            getString(R.string.settings_screen_check_status_off)
        }
    }

    private fun handleOpenAccessibilitySettings() {
        try {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            startActivity(intent)
        } catch (e: Exception) {
            Log.w("PS3Settings", "SettingsActivity: failed to open accessibility settings: ${e.message}", e)
        }
    }

    private fun updateNotificationCard() {
        val usable = notificationsUsable(this)
        binding.tvNotificationStatus.text = if (usable) {
            getString(R.string.settings_notifications_status_on)
        } else {
            getString(R.string.settings_notifications_status_off)
        }
        binding.btnTurnOnNotifications.visibility = if (usable) View.GONE else View.VISIBLE
        if (lastNotificationsUsable == false && usable) {
            SmsReceiver.requeueHeldAlerts(this)
        }
        lastNotificationsUsable = usable
    }

    private fun handleTurnOnNotifications() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            val askedBefore = prefs.getBoolean(KEY_NOTIF_REQUESTED, false)
            val canShowDialog = shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS) || !askedBefore
            if (canShowDialog) {
                prefs.edit().putBoolean(KEY_NOTIF_REQUESTED, true).apply()
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                    REQUEST_CODE_NOTIFICATIONS
                )
            } else {
                openAppNotificationSettings()
            }
        } else {
            openAppNotificationSettings()
        }
    }

    private fun openAppNotificationSettings() {
        try {
            val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            }
            startActivity(intent)
        } catch (e: Exception) {
            Log.w("PS3Settings", "SettingsActivity: failed to open notification settings: ${e.message}", e)
        }
    }

    private fun setupLanguage() {
        val current = AppCompatDelegate.getApplicationLocales()
        val currentTag = if (current.isEmpty) "" else current[0]?.language ?: ""
        when (currentTag) {
            "en" -> binding.rbEnglish.isChecked = true
            "hi" -> binding.rbHindi.isChecked = true
            "ta" -> binding.rbTamil.isChecked = true
            else -> binding.rbSystem.isChecked = true
        }
        binding.rgLanguage.setOnCheckedChangeListener { _, checkedId ->
            val tag = when (checkedId) {
                R.id.rbEnglish -> "en"
                R.id.rbHindi -> "hi"
                R.id.rbTamil -> "ta"
                else -> ""
            }
            val locales = LocaleListCompat.forLanguageTags(tag)
            if (AppCompatDelegate.getApplicationLocales() != locales) {
                AppCompatDelegate.setApplicationLocales(locales)
            }
        }
    }

    private fun showVersion() {
        val versionName = try {
            packageManager.getPackageInfo(packageName, 0).versionName
        } catch (e: Exception) {
            null
        }
        binding.tvVersion.text = getString(R.string.settings_version_format, versionName ?: "")
    }

    private fun computeStorage() {
        storageJob?.cancel()
        val calculating = getString(R.string.storage_calculating)
        binding.tvStorageApp.text = calculating
        binding.tvStorageModels.text = calculating
        binding.tvStorageOther.text = calculating
        binding.tvStorageTotal.text = calculating
        storageJob = lifecycleScope.launch {
            val usage = withContext(Dispatchers.IO) { calculateStorage() }
            if (!isActive) return@launch
            binding.tvStorageApp.text = Formatter.formatShortFileSize(this@SettingsActivity, usage.app)
            binding.tvStorageModels.text = Formatter.formatShortFileSize(this@SettingsActivity, usage.models)
            binding.tvStorageOther.text = Formatter.formatShortFileSize(this@SettingsActivity, usage.other)
            binding.tvStorageTotal.text = Formatter.formatShortFileSize(this@SettingsActivity, usage.total)
        }
    }

    private data class StorageTotals(
        val app: Long,
        val models: Long,
        val other: Long
    ) {
        val total: Long get() = app + models + other
    }

    private fun calculateStorage(): StorageTotals {
        val appBytes = try {
            val info = packageManager.getApplicationInfo(packageName, 0)
            val apks = mutableListOf(File(info.sourceDir))
            info.splitSourceDirs?.forEach { apks.add(File(it)) }
            StorageUsage.totalBytes(apks)
        } catch (e: Exception) {
            0L
        }

        val modelsInFiles = File(filesDir, MODELS_DIR)
        val externalRoot = getExternalFilesDir(null)
        val modelsInExternal = externalRoot?.let { File(it, MODELS_DIR) }
        val modelsBytes = StorageUsage.totalBytes(
            listOfNotNull(modelsInFiles, modelsInExternal)
        )

        val filesBytes = StorageUsage.totalBytes(listOf(filesDir))
        val filesModelsBytes = StorageUsage.totalBytes(listOf(modelsInFiles))
        var otherBytes = (filesBytes - filesModelsBytes).coerceAtLeast(0L)
        if (externalRoot != null && modelsInExternal != null) {
            val externalBytes = StorageUsage.totalBytes(listOf(externalRoot))
            val externalModelsBytes = StorageUsage.totalBytes(listOf(modelsInExternal))
            otherBytes += (externalBytes - externalModelsBytes).coerceAtLeast(0L)
        }
        otherBytes += StorageUsage.totalBytes(listOf(noBackupFilesDir, cacheDir))

        return StorageTotals(app = appBytes, models = modelsBytes, other = otherBytes)
    }

    companion object {
        const val MODELS_DIR = "models"
        const val PREFS_NAME = "ps3_settings"
        const val KEY_NOTIF_REQUESTED = "notif_permission_requested"
        const val REQUEST_CODE_NOTIFICATIONS = 2001

        fun isScreenCheckEnabled(context: Context): Boolean {
            val enabledServices = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            val myComponent = ComponentName(context, ScreenCheckService::class.java)
            val myShort = myComponent.flattenToShortString()
            val myFull = myComponent.flattenToString()
            return enabledServices.split(':').any { entry ->
                val trimmed = entry.trim()
                trimmed.equals(myShort, ignoreCase = true) ||
                    trimmed.equals(myFull, ignoreCase = true) ||
                    ComponentName.unflattenFromString(trimmed) == myComponent
            }
        }
    }
}
