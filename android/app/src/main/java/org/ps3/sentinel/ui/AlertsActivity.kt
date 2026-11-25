package org.ps3.sentinel.ui

import android.content.Intent
import android.os.Bundle
import android.text.format.DateUtils
import android.view.LayoutInflater
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import org.ps3.sentinel.R
import org.ps3.sentinel.databinding.ActivityAlertsBinding
import org.ps3.sentinel.databinding.ItemAlertEntryBinding
import org.ps3.sentinel.sms.AlertEntry
import org.ps3.sentinel.sms.AlertLog
import org.ps3.sentinel.sms.PendingMessageStore

class AlertsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAlertsBinding
    private var selectedKind: String = AlertLog.KIND_SCAM

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivityAlertsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyTopInset(binding.root)
        BottomBar.applyBottomInset(binding.nestedScrollView)

        BottomBar.attach(this, binding.root, Tab.ALERTS)

        binding.btnToggleScam.setOnClickListener {
            if (selectedKind != AlertLog.KIND_SCAM) {
                selectedKind = AlertLog.KIND_SCAM
                updateToggleUi()
                populateAlerts()
            }
        }

        binding.btnToggleSafe.setOnClickListener {
            if (selectedKind != AlertLog.KIND_SAFE) {
                selectedKind = AlertLog.KIND_SAFE
                updateToggleUi()
                populateAlerts()
            }
        }

        binding.btnClearAll.setOnClickListener {
            showClearAllDialog()
        }
    }

    override fun onResume() {
        super.onResume()
        updateToggleUi()
        populateAlerts()
    }

    private fun updateToggleUi() {
        val scamCount = AlertLog.listScam(this).size
        val safeCount = AlertLog.listSafe(this).size

        binding.btnToggleScam.text = getString(R.string.alerts_tab_scam, scamCount)
        binding.btnToggleSafe.text = getString(R.string.alerts_tab_safe, safeCount)

        if (selectedKind == AlertLog.KIND_SCAM) {
            binding.btnToggleScam.setBackgroundResource(R.drawable.bg_liquid_button)
            binding.btnToggleScam.setTextColor(ContextCompat.getColor(this, R.color.text))
            binding.btnToggleSafe.background = null
            binding.btnToggleSafe.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        } else {
            binding.btnToggleSafe.setBackgroundResource(R.drawable.bg_liquid_button)
            binding.btnToggleSafe.setTextColor(ContextCompat.getColor(this, R.color.text))
            binding.btnToggleScam.background = null
            binding.btnToggleScam.setTextColor(ContextCompat.getColor(this, R.color.text_2))
        }
    }

    private fun populateAlerts() {
        val allScam = AlertLog.listScam(this)
        val allSafe = AlertLog.listSafe(this)

        binding.btnToggleScam.text = getString(R.string.alerts_tab_scam, allScam.size)
        binding.btnToggleSafe.text = getString(R.string.alerts_tab_safe, allSafe.size)

        val alerts = if (selectedKind == AlertLog.KIND_SCAM) allScam else allSafe
        val container = binding.layoutAlertsContainer
        container.removeAllViews()

        if (alerts.isEmpty()) {
            binding.layoutEmptyState.visibility = View.VISIBLE
            binding.btnClearAll.visibility = View.GONE
            if (selectedKind == AlertLog.KIND_SAFE) {
                binding.tvEmptyTitle.setText(R.string.alerts_empty_safe_title)
                binding.tvEmptyDesc.setText(R.string.alerts_empty_safe_desc)
            } else {
                binding.tvEmptyTitle.setText(R.string.alerts_empty_title)
                binding.tvEmptyDesc.setText(R.string.alerts_empty_desc)
            }
        } else {
            binding.layoutEmptyState.visibility = View.GONE
            binding.btnClearAll.visibility = View.VISIBLE

            val store = try {
                PendingMessageStore.instance(this)
            } catch (_: Exception) {
                null
            }

            for (entry in alerts) {
                val itemBinding = ItemAlertEntryBinding.inflate(LayoutInflater.from(this), container, false)
                val (chipBg, textColor) = if (entry.kind == AlertLog.KIND_SAFE) {
                    Pair(R.drawable.bg_chip_risk_low, ContextCompat.getColor(this, R.color.risk_low_text))
                } else {
                    when (entry.level.lowercase()) {
                        "high" -> Pair(R.drawable.bg_chip_risk_high, ContextCompat.getColor(this, R.color.risk_high_text))
                        "medium" -> Pair(R.drawable.bg_chip_risk_medium, ContextCompat.getColor(this, R.color.risk_medium_text))
                        else -> Pair(R.drawable.bg_chip_risk_low, ContextCompat.getColor(this, R.color.risk_low_text))
                    }
                }

                itemBinding.tvAlertLevelChip.text = entry.level.uppercase()
                itemBinding.tvAlertLevelChip.backgroundTintList = null
                itemBinding.tvAlertLevelChip.setBackgroundResource(chipBg)
                itemBinding.tvAlertLevelChip.setTextColor(textColor)
                itemBinding.tvAlertLabel.text = entry.label.uppercase()
                itemBinding.tvAlertSender.text = entry.sender
                itemBinding.tvAlertTime.text = DateUtils.getRelativeTimeSpanString(
                    entry.timeMillis,
                    System.currentTimeMillis(),
                    DateUtils.MINUTE_IN_MILLIS
                )

                val msg = entry.message ?: store?.peek(entry.id)
                if (!msg.isNullOrBlank()) {
                    itemBinding.tvAlertMessage.text = msg
                    itemBinding.tvAlertMessage.visibility = View.VISIBLE
                    itemBinding.tvAlertExpired.visibility = View.GONE
                    itemBinding.root.isClickable = true
                    itemBinding.root.setOnClickListener {
                        val intent = Intent(this, MainActivity::class.java).apply {
                            action = Intent.ACTION_SEND
                            type = "text/plain"
                            putExtra(Intent.EXTRA_TEXT, msg)
                        }
                        startActivity(intent)
                    }
                } else {
                    itemBinding.tvAlertMessage.visibility = View.GONE
                    itemBinding.tvAlertExpired.visibility = View.VISIBLE
                    itemBinding.root.isClickable = false
                    itemBinding.root.setOnClickListener(null)
                }

                container.addView(itemBinding.root)
            }
        }
    }

    private fun showClearAllDialog() {
        val (titleRes, msgRes) = if (selectedKind == AlertLog.KIND_SAFE) {
            Pair(R.string.alerts_clear_safe_dialog_title, R.string.alerts_clear_safe_dialog_msg)
        } else {
            Pair(R.string.alerts_clear_scam_dialog_title, R.string.alerts_clear_scam_dialog_msg)
        }

        AlertDialog.Builder(this)
            .setTitle(titleRes)
            .setMessage(msgRes)
            .setPositiveButton(R.string.alerts_clear_confirm) { _, _ ->
                AlertLog.clear(this, selectedKind)
                updateToggleUi()
                populateAlerts()
            }
            .setNegativeButton(R.string.alerts_clear_cancel, null)
            .show()
    }
}
