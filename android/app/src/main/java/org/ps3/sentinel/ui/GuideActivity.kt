/**
 * User guide screen displaying step-by-step usage instructions and security tips.
 * Populates a scrollable list of guide sections from localized string resources.
 * Marks the guide as viewed in SharedPreferences upon launch.
 */
package org.ps3.sentinel.ui

import android.os.Bundle
import android.view.LayoutInflater
import androidx.appcompat.app.AppCompatActivity
import org.ps3.sentinel.R
import org.ps3.sentinel.databinding.ActivityGuideBinding
import org.ps3.sentinel.databinding.ItemGuideSectionBinding

/**
 * Activity rendering the full user guide and safety checklist.
 *
 * Inflates numbered sections explaining how Sentinel detects scams and verifies links.
 */
class GuideActivity : AppCompatActivity() {

    private lateinit var binding: ActivityGuideBinding

    private val sections = listOf(
        R.string.guide_section_title_1 to R.string.guide_section_body_1,
        R.string.guide_section_title_2 to R.string.guide_section_body_2,
        R.string.guide_section_title_3 to R.string.guide_section_body_3,
        R.string.guide_section_title_4 to R.string.guide_section_body_4,
        R.string.guide_section_title_5 to R.string.guide_section_body_5,
        R.string.guide_section_title_6 to R.string.guide_section_body_6,
        R.string.guide_section_title_7 to R.string.guide_section_body_7
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        BottomBar.enableEdgeToEdge(this)
        binding = ActivityGuideBinding.inflate(layoutInflater)
        setContentView(binding.root)

        BottomBar.applyScreenInsets(binding.root)

        markGuideShown()

        binding.toolbar.setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }
        binding.btnGotIt.setOnClickListener { finish() }

        val inflater = LayoutInflater.from(this)
        sections.forEachIndexed { index, section ->
            val item = ItemGuideSectionBinding.inflate(inflater, binding.layoutGuideSections, false)
            item.tvGuideNumber.text = getString(R.string.guide_section_number, index + 1)
            item.tvGuideTitle.setText(section.first)
            item.tvGuideBody.setText(section.second)
            binding.layoutGuideSections.addView(item.root)
        }
    }

    private fun markGuideShown() {
        getSharedPreferences(FirstRun.PREFS_NAME, MODE_PRIVATE)
            .edit()
            .putBoolean(FirstRun.GUIDE_SHOWN, true)
            .apply()
    }
}
