/**
 * Kotlin parser and active container for detection rules shared with Python.
 * Loads rules.json bundled in assets and validates schema version and regular expressions.
 * Checked by ParityTest and Python rules tests.
 */
package org.ps3.sentinel.core

import android.content.res.AssetManager
import org.json.JSONArray
import org.json.JSONObject
import java.util.regex.Pattern

/** Cue keyword lists and extra precompiled regular expressions, shared with the Python pipeline. */
data class CueRules(
    val typeOrder: List<String>,
    val keywords: Map<String, List<String>>,
    /** Precompiled regexes, validated at load so a bad pattern fails startup, not mid-SMS. */
    val regexes: Map<String, List<Pattern>>
)

/** Every weight and threshold the fusion step uses, loaded from the shared rules file. */
data class FusionRules(
    val smsTemperature: Double,
    val smsScamWeight: Double,
    val smsUnwantedWeight: Double,
    val urlWeight: Double,
    val cueWeight: Double,
    val cueCap: Double,
    val comboScore: Double,
    val appInstallScore: Double,
    val collectPinScore: Double,
    val labelThreshold: Double,
    val highLevelThreshold: Double,
    val mediumLevelThreshold: Double,
    val trustedProbCap: Double,
    val urlPhishingLabelThreshold: Double,
    val riskRoundDecimals: Int,
    val smsHamConfidenceThreshold: Double
)

/** Plain-promotion detection shared with Python; verdict never changes, only presentation. */
data class PromotionRules(
    val level: String,
    val label: String,
    val blockedCueTypes: List<String>,
    val phoneDigitRunRegex: String,
    val phoneMinDigits: Int,
    val replyContactPhrases: List<String>,
    val domainLikeRegex: String,
    val atHandleRegex: String,
    val adviceText: String
)

/** One known scam script: every [all] pattern must be found and no [none] pattern. */
data class ScamScript(
    val name: String,
    val indicator: String,
    val all: List<Pattern>,
    val none: List<Pattern>
)

/**
 * The detection rules shared with the Python package.
 *
 * Both platforms read the same rules.json, which lives in sentinel/data and is
 * shipped into Android assets by the build. A missing or malformed file must
 * fail loudly so a stale copy cannot silently change verdicts.
 */
class Rules(
    val schemaVersion: Int,
    val cues: CueRules,
    val fusion: FusionRules,
    val detectorVersions: Map<String, String>,
    val promotion: PromotionRules,
    val scamScripts: List<ScamScript> = emptyList()
) {
    companion object {
        /** Only schema this reader understands; bump together with the writer. */
        private const val SUPPORTED_SCHEMA_VERSION = 1

        /** Asset name shared with the Python package. */
        const val ASSET_NAME = "rules.json"

        @Volatile
        private var activeRules: Rules? = null

        /** Parse rules from JSON text. Throws IllegalArgumentException naming the asset when malformed. */
        fun fromJson(text: String): Rules {
            val root = try {
                JSONObject(text)
            } catch (error: Exception) {
                throw IllegalArgumentException("$ASSET_NAME is not valid JSON: ${error.message}", error)
            }

            val schemaVersion = root.optInt("schema_version", -1)
            if (schemaVersion != SUPPORTED_SCHEMA_VERSION) {
                throw IllegalArgumentException(
                    "$ASSET_NAME: unsupported schema_version $schemaVersion, expected $SUPPORTED_SCHEMA_VERSION"
                )
            }

            return Rules(
                schemaVersion = schemaVersion,
                cues = parseCues(root.getJSONObject("cues")),
                fusion = parseFusion(root.getJSONObject("fusion")),
                detectorVersions = parseDetectorVersions(root.getJSONObject("detector_versions")),
                promotion = parsePromotion(root.getJSONObject("promotion_no_action")),
                scamScripts = parseScamScripts(root.getJSONObject("scam_scripts"))
            )
        }

        /** Read the bundled asset, make it available to Cues/Fusion and return it. */
        fun load(assets: AssetManager): Rules {
            val text = assets.open(ASSET_NAME).bufferedReader(Charsets.UTF_8).use { it.readText() }
            val rules = fromJson(text)
            activate(rules)
            return rules
        }

        /** Install the rules used by [smsCues] and [fuse]. Called at app startup or in tests. */
        fun activate(rules: Rules) {
            activeRules = rules
        }

        /** Return the active rules or fail with an actionable message. */
        fun active(): Rules {
            return activeRules ?: throw IllegalStateException(
                "Rules are not loaded. Call Rules.load(assets) during app startup."
            )
        }

        private fun parseCues(cues: JSONObject): CueRules {
            val orderArray = cues.getJSONArray("type_order")
            val typeOrder = readStringList(orderArray, "cues.type_order")

            val keywordsObject = cues.getJSONObject("keywords")
            val regexesObject = cues.getJSONObject("regexes")
            val keywords = LinkedHashMap<String, List<String>>()
            val regexes = LinkedHashMap<String, List<Pattern>>()
            for (cueType in typeOrder) {
                keywords[cueType] = readStringList(
                    keywordsObject.getJSONArray(cueType),
                    "cues.keywords.$cueType"
                )
                val rawPatterns = readStringList(
                    regexesObject.getJSONArray(cueType),
                    "cues.regexes.$cueType"
                )
                val compiled = mutableListOf<Pattern>()
                // Precompile regexes at load time so malformed patterns fail startup instead of mid-SMS.
                for (raw in rawPatterns) {
                    try {
                        compiled.add(Pattern.compile(raw, Pattern.CASE_INSENSITIVE))
                    } catch (error: Exception) {
                        throw IllegalArgumentException(
                            "$ASSET_NAME: cues.regexes.$cueType pattern '$raw' is not a valid regex: ${error.message}",
                            error
                        )
                    }
                }
                regexes[cueType] = compiled
            }
            return CueRules(typeOrder = typeOrder, keywords = keywords, regexes = regexes)
        }

        private fun parseFusion(fusion: JSONObject): FusionRules {
            val decimals = fusion.getInt("risk_round_decimals")
            if (decimals < 0) {
                throw IllegalArgumentException("$ASSET_NAME: fusion.risk_round_decimals must be non-negative")
            }
            return FusionRules(
                smsTemperature = fusion.getDouble("sms_temperature"),
                smsScamWeight = fusion.getDouble("sms_scam_weight"),
                smsUnwantedWeight = fusion.getDouble("sms_unwanted_weight"),
                urlWeight = fusion.getDouble("url_weight"),
                cueWeight = fusion.getDouble("cue_weight"),
                cueCap = fusion.getDouble("cue_cap"),
                comboScore = fusion.getDouble("combo_score"),
                appInstallScore = fusion.getDouble("app_install_score"),
                collectPinScore = fusion.getDouble("collect_pin_score"),
                labelThreshold = fusion.getDouble("label_threshold"),
                highLevelThreshold = fusion.getDouble("high_level_threshold"),
                mediumLevelThreshold = fusion.getDouble("medium_level_threshold"),
                trustedProbCap = fusion.getDouble("trusted_prob_cap"),
                urlPhishingLabelThreshold = fusion.getDouble("url_phishing_label_threshold"),
                riskRoundDecimals = decimals,
                smsHamConfidenceThreshold = fusion.getDouble("sms_ham_confidence_threshold")
            )
        }

        private fun parseDetectorVersions(section: JSONObject): Map<String, String> {
            val versionsObject = section.getJSONObject("versions")
            val versions = LinkedHashMap<String, String>()
            val keys = versionsObject.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                versions[key] = versionsObject.getString(key)
            }
            return versions
        }

        private fun parsePromotion(section: JSONObject): PromotionRules {
            val level = readRequiredString(section, "level", "promotion_no_action.level")
            val label = readRequiredString(section, "label", "promotion_no_action.label")
            val blocked = readStringList(
                section.getJSONArray("blocked_cue_types"),
                "promotion_no_action.blocked_cue_types"
            )
            val phoneRegex = readRequiredString(
                section,
                "phone_digit_run_regex",
                "promotion_no_action.phone_digit_run_regex"
            )
            try {
                java.util.regex.Pattern.compile(phoneRegex)
            } catch (error: Exception) {
                throw IllegalArgumentException(
                    "$ASSET_NAME: promotion_no_action.phone_digit_run_regex is not a valid regex: ${error.message}",
                    error
                )
            }
            val domainLike = readRequiredString(
                section,
                "domain_like_regex",
                "promotion_no_action.domain_like_regex"
            )
            try {
                java.util.regex.Pattern.compile(domainLike)
            } catch (error: Exception) {
                throw IllegalArgumentException(
                    "$ASSET_NAME: promotion_no_action.domain_like_regex is not a valid regex: ${error.message}",
                    error
                )
            }
            val atHandle = readRequiredString(
                section,
                "at_handle_regex",
                "promotion_no_action.at_handle_regex"
            )
            try {
                java.util.regex.Pattern.compile(atHandle)
            } catch (error: Exception) {
                throw IllegalArgumentException(
                    "$ASSET_NAME: promotion_no_action.at_handle_regex is not a valid regex: ${error.message}",
                    error
                )
            }

            val phoneMinDigits = section.optInt("phone_min_digits", -1)
            if (phoneMinDigits <= 0) {
                throw IllegalArgumentException("$ASSET_NAME: promotion_no_action.phone_min_digits must be a positive integer")
            }
            val phrases = readStringList(
                section.getJSONArray("reply_contact_phrases"),
                "promotion_no_action.reply_contact_phrases"
            )
            val adviceText = readRequiredString(section, "advice_text", "promotion_no_action.advice_text")
            return PromotionRules(
                level = level,
                label = label,
                blockedCueTypes = blocked,
                phoneDigitRunRegex = phoneRegex,
                phoneMinDigits = phoneMinDigits,
                replyContactPhrases = phrases,
                domainLikeRegex = domainLike,
                atHandleRegex = atHandle,
                adviceText = adviceText
            )
        }

        private fun parseScamScripts(section: JSONObject): List<ScamScript> {
            val scripts = section.getJSONArray("scripts")
            val result = ArrayList<ScamScript>(scripts.length())
            for (index in 0 until scripts.length()) {
                val where = "scam_scripts.scripts[$index]"
                val script = scripts.getJSONObject(index)
                val all = compileScriptPatterns(script.getJSONArray("all"), "$where.all")
                if (all.isEmpty()) {
                    throw IllegalArgumentException("$ASSET_NAME: $where.all must not be empty")
                }
                result.add(
                    ScamScript(
                        name = readRequiredString(script, "name", "$where.name"),
                        indicator = readRequiredString(script, "indicator", "$where.indicator"),
                        all = all,
                        none = compileScriptPatterns(script.getJSONArray("none"), "$where.none")
                    )
                )
            }
            return result
        }

        private fun compileScriptPatterns(array: JSONArray, label: String): List<Pattern> =
            readStringList(array, label).map { raw ->
                try {
                    Pattern.compile(raw, Pattern.CASE_INSENSITIVE)
                } catch (error: Exception) {
                    throw IllegalArgumentException(
                        "$ASSET_NAME: $label pattern '$raw' is not a valid regex: ${error.message}",
                        error
                    )
                }
            }

        private fun readRequiredString(obj: JSONObject, key: String, label: String): String {
            val value = obj.opt(key)
            if (value !is String || value.isEmpty()) {
                throw IllegalArgumentException("$ASSET_NAME: $label must be a non-empty string")
            }
            return value
        }

        private fun readStringList(array: JSONArray, label: String): List<String> {
            val result = ArrayList<String>(array.length())
            for (index in 0 until array.length()) {
                val value = array.opt(index)
                if (value !is String) {
                    throw IllegalArgumentException("$ASSET_NAME: $label[$index] must be a string")
                }
                result.add(value)
            }
            return result
        }
    }
}
