package org.ps3.sentinel.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.os.Bundle
import android.text.format.DateUtils
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.ps3.sentinel.R
import org.ps3.sentinel.SentinelApp
import org.ps3.sentinel.core.ProtectionStatus
import org.ps3.sentinel.databinding.ActivityHomeBinding
import org.ps3.sentinel.ml.CpuFeatures
import org.ps3.sentinel.sms.AlertLog
import org.ps3.sentinel.sms.PendingMessageStore
import org.ps3.sentinel.sms.SmsReceiver

class HomeActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHomeBinding
    private val app get() = SentinelApp.instance

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val onboardingDone = getSharedPreferences(FirstRun.PREFS_NAME, Context.MODE_PRIVATE)
            .getBoolean(FirstRun.ONBOARDING_DONE, false)
        if (!onboardingDone) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }

        BottomBar.enableEdgeToEdge(this)

        binding = ActivityHomeBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyTopInset(binding.root)
        BottomBar.applyBottomInset(binding.nestedScrollView)

        BottomBar.attach(this, binding.root, Tab.HOME)

        binding.tileCheckMessage.setOnClickListener {
            val intent = Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.tileAlerts.setOnClickListener {
            val intent = Intent(this, AlertsActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.tileSmsMms.setOnClickListener {
            val intent = Intent(this, ProtectionActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.tileAppAccess.setOnClickListener {
            val intent = Intent(this, ProtectionActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.tileNotifications.setOnClickListener {
            val intent = Intent(this, ProtectionActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.tileModels.setOnClickListener {
            startActivity(Intent(this, ModelsActivity::class.java))
        }

        binding.cardProtectionStatus.setOnClickListener {
            val intent = Intent(this, ProtectionActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }

        binding.cardLastAlert.setOnClickListener {
            val intent = Intent(this, AlertsActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
            }
            startActivity(intent)
        }
    }

    override fun onResume() {
        super.onResume()
        app.markUiOpened()
        updateModelsTile()
        lifecycleScope.launch {
            withContext(Dispatchers.Default) {
                app.refreshModelsOnResume()
                app.pipeline?.warmUp()
            }
            updateModelsTile()
        }
        updateProtectionStatus()
        updateAlerts()
    }

    private fun updateProtectionStatus() {
        val smsGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED
        val mmsGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_MMS) == PackageManager.PERMISSION_GRANTED
        val notifsUsable = SmsReceiver.notificationsUsable(this)
        val screenCheckEnabled = SettingsActivity.isScreenCheckEnabled(this)

        val status = ProtectionStatus(smsGranted, mmsGranted, notifsUsable, screenCheckEnabled)

        // The sub-line doubles as the healthy summary and the list of core features that are off.
        if (status.allOn()) {
            binding.tvStatusTitle.text = getString(R.string.status_protection_on)
            binding.tvStatusSub.text = getString(R.string.home_status_all_on_sub)
        } else {
            binding.tvStatusTitle.text = getString(R.string.status_protection_partly_on)
            binding.tvStatusSub.text = getString(
                R.string.status_off_prefix,
                status.offItems().joinToString(", ") { offItemLabel(it) }
            )
        }
        binding.tvStatusSub.visibility = View.VISIBLE

        binding.tvStatusSmsMms.text = if (smsGranted && mmsGranted) {
            getString(R.string.status_on)
        } else {
            getString(R.string.status_off)
        }

        binding.tvStatusNotifications.text = if (notifsUsable) {
            getString(R.string.status_on)
        } else {
            getString(R.string.status_off)
        }
    }

    /** Maps a pure [ProtectionStatus] core item key to its localized label. */
    private fun offItemLabel(key: String): String = when (key) {
        ProtectionStatus.ITEM_SMS -> getString(R.string.off_item_sms)
        ProtectionStatus.ITEM_MMS -> getString(R.string.off_item_mms)
        ProtectionStatus.ITEM_NOTIFICATIONS -> getString(R.string.tile_notifications)
        else -> key
    }

    private fun updateModelsTile() {
        val store = try {
            app.modelStore
        } catch (_: Exception) {
            null
        }
        val isReady = !CpuFeatures.isExecutorchBlocked() &&
            store?.isUrlClassifierReady() == true &&
            (app.pipeline?.isSmsModelLoaded() == true || store?.isSmsClassifierReady() == true) &&
            !(store?.isVerifying == true)
        binding.tvStatusModels.text = if (isReady) {
            getString(R.string.models_status_ready)
        } else {
            getString(R.string.models_status_loading)
        }
    }

    private fun updateAlerts() {
        val alerts = AlertLog.listScam(this)
        binding.tvAlertsCount.text = if (alerts.isNotEmpty()) "${alerts.size}" else ""

        val newest = alerts.firstOrNull()
        if (newest != null) {
            binding.tvLastAlertEmpty.visibility = View.GONE
            binding.layoutLastAlertContent.visibility = View.VISIBLE

            val (chipBg, textColor) = when (newest.level.lowercase()) {
                "high" -> Pair(R.drawable.bg_chip_risk_high, ContextCompat.getColor(this, R.color.risk_high_text))
                "medium" -> Pair(R.drawable.bg_chip_risk_medium, ContextCompat.getColor(this, R.color.risk_medium_text))
                else -> Pair(R.drawable.bg_chip_risk_low, ContextCompat.getColor(this, R.color.risk_low_text))
            }
            binding.tvLastAlertLevelChip.text = newest.level.uppercase()
            binding.tvLastAlertLevelChip.backgroundTintList = null
            binding.tvLastAlertLevelChip.setBackgroundResource(chipBg)
            binding.tvLastAlertLevelChip.setTextColor(textColor)
            binding.tvLastAlertLabel.text = newest.label.uppercase()
            binding.tvLastAlertSender.text = newest.sender
            binding.tvLastAlertTime.text = DateUtils.getRelativeTimeSpanString(
                newest.timeMillis,
                System.currentTimeMillis(),
                DateUtils.MINUTE_IN_MILLIS
            )

            val store = try {
                PendingMessageStore.instance(this)
            } catch (_: Exception) {
                null
            }
            val msg = newest.message ?: store?.peek(newest.id)
            if (!msg.isNullOrBlank()) {
                binding.tvLastAlertMessage.text = msg
                binding.tvLastAlertMessage.visibility = View.VISIBLE
                binding.cardLastAlert.isClickable = true
                binding.cardLastAlert.setOnClickListener {
                    val intent = Intent(this, MainActivity::class.java).apply {
                        action = Intent.ACTION_SEND
                        type = "text/plain"
                        putExtra(Intent.EXTRA_TEXT, msg)
                    }
                    startActivity(intent)
                }
            } else {
                binding.tvLastAlertMessage.visibility = View.GONE
                binding.cardLastAlert.isClickable = true
                binding.cardLastAlert.setOnClickListener {
                    val intent = Intent(this, AlertsActivity::class.java).apply {
                        flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
                    }
                    startActivity(intent)
                }
            }
        } else {
            binding.tvLastAlertEmpty.visibility = View.VISIBLE
            binding.layoutLastAlertContent.visibility = View.GONE
            binding.tvLastAlertMessage.visibility = View.GONE
            binding.cardLastAlert.setOnClickListener(null)
        }
    }
}
