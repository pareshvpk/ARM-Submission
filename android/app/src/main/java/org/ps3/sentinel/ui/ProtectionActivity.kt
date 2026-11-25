package org.ps3.sentinel.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.ps3.sentinel.R
import org.ps3.sentinel.databinding.ActivityProtectionBinding
import org.ps3.sentinel.sms.MmsWatcher
import org.ps3.sentinel.sms.SmsReceiver
import org.ps3.sentinel.sms.notificationsUsable

class ProtectionActivity : AppCompatActivity() {

    private lateinit var binding: ActivityProtectionBinding
    private var lastNotificationsUsable: Boolean? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivityProtectionBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyTopInset(binding.root)
        BottomBar.applyBottomInset(binding.nestedScrollView)

        BottomBar.attach(this, binding.root, Tab.PROTECTION)

        binding.btnRequestSmsPermissions.setOnClickListener {
            handleRequestSmsPermissions()
        }

        binding.btnTurnOnNotifications.setOnClickListener {
            handleTurnOnNotifications()
        }

        binding.btnScreenCheckSettings.setOnClickListener {
            handleOpenAccessibilitySettings()
        }

        binding.btnCheckAppAccess.setOnClickListener {
            handleCheckAppAccess()
        }
    }

    override fun onResume() {
        super.onResume()
        updateSmsCard()
        updateNotificationCard()
        updateScreenCheckCard()
    }

    private fun updateSmsCard() {
        val smsGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED
        val mmsGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_MMS) == PackageManager.PERMISSION_GRANTED

        val allGranted = smsGranted && mmsGranted
        if (allGranted) {
            binding.tvSmsMmsStatus.text = getString(R.string.protection_permissions_granted)
            binding.btnRequestSmsPermissions.visibility = View.GONE
        } else {
            binding.tvSmsMmsStatus.text = getString(R.string.status_off)
            binding.btnRequestSmsPermissions.visibility = View.VISIBLE
        }
    }

    private fun handleRequestSmsPermissions() {
        val permissions = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.RECEIVE_SMS)
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_MMS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.RECEIVE_MMS)
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(Manifest.permission.READ_SMS)
        }

        if (permissions.isEmpty()) {
            updateSmsCard()
            return
        }

        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val askedBefore = prefs.getBoolean(KEY_SMS_REQUESTED, false)

        val anyCanShowRationale = permissions.any { ActivityCompat.shouldShowRequestPermissionRationale(this, it) }
        if (!anyCanShowRationale && askedBefore) {
            // Permanently denied: open app settings
            try {
                val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.fromParts("package", packageName, null)
                }
                startActivity(intent)
            } catch (e: Exception) {
                Log.w("PS3Protection", "Failed to open app settings: ${e.message}", e)
            }
        } else {
            prefs.edit().putBoolean(KEY_SMS_REQUESTED, true).apply()
            ActivityCompat.requestPermissions(
                this,
                permissions.toTypedArray(),
                REQUEST_CODE_SMS
            )
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
            val prefs = getSharedPreferences(SettingsActivity.PREFS_NAME, MODE_PRIVATE)
            val askedBefore = prefs.getBoolean(SettingsActivity.KEY_NOTIF_REQUESTED, false)
            val canShowDialog = shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS) || !askedBefore
            if (canShowDialog) {
                prefs.edit().putBoolean(SettingsActivity.KEY_NOTIF_REQUESTED, true).apply()
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
            Log.w("PS3Protection", "Failed to open notification settings: ${e.message}", e)
        }
    }

    private fun updateScreenCheckCard() {
        val enabled = SettingsActivity.isScreenCheckEnabled(this)
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
            Log.w("PS3Protection", "Failed to open accessibility settings: ${e.message}", e)
        }
    }

    private fun handleCheckAppAccess() {
        lifecycleScope.launch {
            try {
                val entries = withContext(Dispatchers.IO) {
                    AppAccessCollector(this@ProtectionActivity).collect()
                }
                if (entries.isEmpty()) {
                    binding.tvAppAccessResults.text = getString(R.string.app_access_none)
                } else {
                    val lines = entries.map { entry ->
                        val flags = mutableListOf<String>()
                        if (entry.canReadScreen) {
                            flags.add(getString(R.string.app_access_flag_screen))
                        }
                        if (entry.canPerformGestures) {
                            flags.add(getString(R.string.app_access_flag_gestures))
                        }
                        if (entry.canReadSms == true) {
                            flags.add(getString(R.string.app_access_flag_sms))
                        } else if (entry.canReadSms == null) {
                            flags.add(getString(R.string.app_access_flag_sms_unknown))
                        }
                        if (entry.isSystem) {
                            flags.add(getString(R.string.app_access_flag_system))
                        }
                        if (flags.isNotEmpty()) {
                            "${entry.label} — ${flags.joinToString(", ")}"
                        } else {
                            entry.label
                        }
                    }
                    binding.tvAppAccessResults.text = lines.joinToString("\n")
                }
                binding.tvAppAccessResults.visibility = View.VISIBLE
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w("PS3Protection", "Failed to collect app access review: ${e.message}", e)
                binding.tvAppAccessResults.text = getString(R.string.app_access_error)
                binding.tvAppAccessResults.visibility = View.VISIBLE
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        when (requestCode) {
            REQUEST_CODE_SMS -> {
                updateSmsCard()
                if (MmsWatcher.allowed(this)) {
                    MmsWatcher.schedule(this)
                }
            }
            REQUEST_CODE_NOTIFICATIONS -> updateNotificationCard()
        }
    }

    companion object {
        private const val PREFS_NAME = "ps3_protection"
        private const val KEY_SMS_REQUESTED = "sms_permissions_requested"
        private const val REQUEST_CODE_SMS = 3001
        private const val REQUEST_CODE_NOTIFICATIONS = 3002
    }
}
