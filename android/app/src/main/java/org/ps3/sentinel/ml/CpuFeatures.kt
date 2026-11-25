// Inspects Linux /proc/cpuinfo and Android system APIs to detect Arm CPU features and memory tier.
// Classifies SoC capabilities into execution tiers (FULL, LIGHT, NONE) and selects
// optimal ExecuTorch kernel acceleration paths (DOTPROD, I8MM, SME2, NEON).

package org.ps3.sentinel.ml

import android.app.ActivityManager
import org.ps3.sentinel.BuildConfig
import android.content.Context
import android.util.Log
import java.io.File

/**
 * Detected Arm CPU architectural feature flags parsed from /proc/cpuinfo.
 */
data class CpuFlags(
    val atomics: Boolean = false,
    val asimddp: Boolean = false,
    val fphp: Boolean = false,
    val bf16: Boolean = false,
    val i8mm: Boolean = false,
    val sve: Boolean = false,
    val sve2: Boolean = false,
    val sme: Boolean = false,
    val sme2: Boolean = false
)

/**
 * Detects Arm hardware capabilities, CPU cluster topologies, RAM tiers, and ExecuTorch compatibility.
 */
object CpuFeatures {
    const val CPUINFO_PATH: String = "/proc/cpuinfo"
    const val CPU_FREQ_BASE: String = "/sys/devices/system/cpu"
    const val EXECUTORCH_BLOCKED_STATUS: String =
        "This phone's processor is older than the AI models need. Basic checks are on."
    private const val TIMING_TAG: String = "PS3Timing"
    private const val RAM_3GB_BYTES: Long = 3L * 1024L * 1024L * 1024L
    private const val RAM_5GB_BYTES: Long = 5L * 1024L * 1024L * 1024L
    private const val FALLBACK_RAM_BYTES: Long = 8L * 1024L * 1024L * 1024L
    // threads.auto — runtime opt-in file checked once at creation next to the models
    // (ModelStore models dir). Its presence enables the thread-count proposal without a rebuild.
    const val THREADS_AUTO_FLAG_FILE_NAME: String = "threads.auto"

    /** Device capability tiers governing Llama loading, token limits, and watchdog timeouts. */
    enum class Tier { FULL, LIGHT, NONE }

    @Volatile
    private var cachedFlags: CpuFlags? = null

    @Volatile
    private var cachedRamBytes: Long? = null

    @Volatile
    private var logged: Boolean = false

    /**
     * Parses the whitespace-delimited tokens from the /proc/cpuinfo Features line.
     *
     * @param line Raw features string value from cpuinfo.
     * @return [CpuFlags] representing detected hardware features.
     */
    fun parseFeaturesLine(line: String?): CpuFlags {
        if (line == null) {
            return CpuFlags()
        }
        val tokens = line.split(Regex("\\s+")).map { it.trim().lowercase() }.filter { it.isNotEmpty() }.toSet()
        return CpuFlags(
            atomics = "atomics" in tokens,
            asimddp = "asimddp" in tokens,
            fphp = "fphp" in tokens,
            bf16 = "bf16" in tokens,
            i8mm = "i8mm" in tokens,
            sve = "sve" in tokens,
            sve2 = "sve2" in tokens,
            sme = "sme" in tokens,
            sme2 = "sme2" in tokens
        )
    }

    /**
     * Identifies the optimal ExecuTorch kernel path supported by [flags].
     *
     * Priority order selects SME2, then I8MM, then DOTPROD, falling back to NEON.
     *
     * @param flags Detected CPU architecture flags.
     * @return Kernel acceleration name ("SME2", "I8MM", "DOTPROD", or "NEON").
     */
    fun bestKernelPath(flags: CpuFlags): String = when {
        flags.sme2 -> "SME2"
        flags.i8mm -> "I8MM"
        flags.asimddp -> "DOTPROD"
        else -> "NEON"
    }

    /**
     * Groups CPU cores by max frequency into cluster pairs sorted by frequency descending.
     *
     * @param freqByCpu Map of CPU index to maximum frequency in kHz.
     * @return List of frequency-to-core-count pairs (e.g., big cores first).
     */
    fun parseClusters(freqByCpu: Map<Int, Long>): List<Pair<Long, Int>> {
        if (freqByCpu.isEmpty()) return emptyList()
        val counts = freqByCpu.values.groupingBy { it }.eachCount()
        return counts.entries
            .map { (freq, count) -> freq to count }
            .sortedByDescending { (freq, _) -> freq }
    }

    /**
     * Formats cluster topology into a summary string like "2@2400000+6@1800000".
     *
     * @param clusters List of frequency-to-core-count pairs.
     * @return Formatted cluster representation, or "unknown" if empty.
     */
    fun formatClusters(clusters: List<Pair<Long, Int>>): String {
        if (clusters.isEmpty()) return "unknown"
        return clusters.joinToString("+") { (freq, count) -> "${count}@${freq}" }
    }

    /**
     * Inspects /sys/devices/system/cpu to determine active CPU core frequency clusters.
     *
     * @return List of frequency-to-core-count pairs, or empty list on read error.
     */
    fun currentClusters(): List<Pair<Long, Int>> {
        return try {
            val base = File(CPU_FREQ_BASE)
            val freqByCpu = mutableMapOf<Int, Long>()
            val entries = base.listFiles() ?: return emptyList()
            for (entry in entries) {
                val name = entry.name
                if (!name.startsWith("cpu")) continue
                val idStr = name.removePrefix("cpu")
                val id = idStr.toIntOrNull() ?: continue
                val freqFile = File(entry, "cpufreq/cpuinfo_max_freq")
                if (!freqFile.isFile) continue
                val text = freqFile.readText().trim()
                val freq = text.toLongOrNull() ?: continue
                freqByCpu[id] = freq
            }
            parseClusters(freqByCpu)
        } catch (_: Exception) {
            emptyList()
        }
    }

    /**
     * Proposes a thread pool size based on the core count of the fastest CPU cluster.
     *
     * @param clusters Detected CPU cluster topologies.
     * @return Recommended thread count clamped between 2 and 4.
     */
    fun proposeThreadCount(clusters: List<Pair<Long, Int>>): Int {
        if (clusters.isEmpty()) return 2
        val fastest = clusters.maxByOrNull { (freq, _) -> freq } ?: return 2
        val fastestCount = fastest.second
        return fastestCount.coerceIn(2, 4)
    }

    /**
     * Checks if the threads.auto flag file is present in [modelsDir].
     *
     * @param modelsDir Directory where model files and runtime flags reside.
     * @return True if threads.auto exists.
     */
    fun isThreadsAutoEnabled(modelsDir: File?): Boolean {
        if (modelsDir == null) return false
        return try {
            File(modelsDir, THREADS_AUTO_FLAG_FILE_NAME).exists()
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Formats acceleration path and cluster topology into a log line.
     *
     * @param flags Detected CPU flags.
     * @param clusters Detected CPU clusters.
     * @return Diagnostic string.
     */
    fun formatAccelLine(flags: CpuFlags, clusters: List<Pair<Long, Int>>): String {
        return "accel_path=${bestKernelPath(flags)} clusters=${formatClusters(clusters)}"
    }

    /**
     * Extracts and parses the "Features" entry from /proc/cpuinfo text.
     *
     * @param content Raw text contents of /proc/cpuinfo.
     * @return Parsed [CpuFlags], or fallback flags if unparseable.
     */
    fun parseCpuInfo(content: String?): CpuFlags {
        if (content.isNullOrEmpty()) return fallbackFlags()
        val featuresLine = content.lineSequence().firstOrNull { it.trimStart().startsWith("Features") }
            ?: return fallbackFlags()
        val colonIndex = featuresLine.indexOf(':')
        val value = if (colonIndex >= 0) featuresLine.substring(colonIndex + 1) else featuresLine
        return parseFeaturesLine(value)
    }

    /**
     * Returns conservative default flags with all optional extensions disabled.
     */
    fun fallbackFlags(): CpuFlags = CpuFlags(
        atomics = false,
        asimddp = false,
        fphp = false,
        bf16 = false,
        i8mm = false,
        sve = false,
        sve2 = false,
        sme = false,
        sme2 = false
    )

    /**
     * Reads /proc/cpuinfo once per process and caches detected [CpuFlags].
     *
     * @return Cached or freshly parsed [CpuFlags].
     */
    fun currentFlags(): CpuFlags {
        cachedFlags?.let { return it }
        val flags = try {
            val content = File(CPUINFO_PATH).readText(Charsets.UTF_8)
            parseCpuInfo(content)
        } catch (e: Exception) {
            fallbackFlags()
        }
        cachedFlags = flags
        return flags
    }

    /** Returns total memory bytes from ActivityManager.MemoryInfo. */
    fun totalRamBytesFromMemoryInfo(totalMem: Long): Long = totalMem

    /**
     * Queries total device RAM in bytes via ActivityManager, cached per process.
     *
     * @param context Android context used to obtain ActivityManager.
     * @return Total RAM in bytes, or fallback constant if unavailable.
     */
    fun totalRamBytes(context: Context?): Long {
        cachedRamBytes?.let { return it }
        val ram = try {
            if (context == null) {
                FALLBACK_RAM_BYTES
            } else {
                val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
                if (manager == null) {
                    FALLBACK_RAM_BYTES
                } else {
                    val info = ActivityManager.MemoryInfo()
                    manager.getMemoryInfo(info)
                    val total = info.totalMem
                    if (total > 0L) total else FALLBACK_RAM_BYTES
                }
            }
        } catch (e: Exception) {
            FALLBACK_RAM_BYTES
        }
        cachedRamBytes = ram
        return ram
    }

    /** Alias for [totalRamBytes]. */
    fun currentTotalRamBytes(context: Context?): Long = totalRamBytes(context)

    /**
     * Classifies device capability into [Tier.FULL], [Tier.LIGHT], or [Tier.NONE].
     *
     * @param flags Detected CPU flags.
     * @param ramBytes Total device RAM in bytes.
     * @return Assigned execution tier.
     */
    fun tierForFlags(flags: CpuFlags, ramBytes: Long): Tier {
        if (ramBytes < RAM_3GB_BYTES) return Tier.NONE
        if (flags.asimddp && ramBytes >= RAM_5GB_BYTES) return Tier.FULL
        return Tier.LIGHT
    }

    /** Returns the capability tier evaluated for the current device hardware. */
    fun currentTier(context: Context?): Tier = tierForFlags(currentFlags(), currentTotalRamBytes(context))

    /** Returns true if [tier] supports running Llama on-device. */
    fun shouldLoadLlama(tier: Tier): Boolean = tier != Tier.NONE

    /** Returns maximum generated token limit configured for [tier]. */
    fun maxNewTokensFor(tier: Tier): Int =
        if (tier == Tier.LIGHT) LlamaAdvisor.LIGHT_MAX_NEW_TOKENS else LlamaAdvisor.DEFAULT_MAX_NEW_TOKENS

    /** Returns initial token arrival timeout in milliseconds for [tier]. */
    fun firstTokenTimeoutMsFor(tier: Tier): Long =
        if (tier == Tier.LIGHT) {
            GenerationWatchdog.LIGHT_FIRST_TOKEN_TIMEOUT_MS
        } else {
            GenerationWatchdog.FIRST_TOKEN_TIMEOUT_MS
        }

    /** Returns overall generation deadline in milliseconds for [tier]. */
    fun totalGenerationTimeoutMsFor(tier: Tier): Long =
        if (tier == Tier.LIGHT) {
            GenerationWatchdog.LIGHT_TOTAL_GENERATION_TIMEOUT_MS
        } else {
            GenerationWatchdog.TOTAL_GENERATION_TIMEOUT_MS
        }

    /** Checks whether the app was compiled against the Armv8.0 baseline ExecuTorch AAR. */
    fun isArmv8BaselineLibrary(): Boolean = BuildConfig.EXECUTORCH_ARMV8_BASELINE

    /** Checks whether ExecuTorch should be blocked due to missing atomics on stock Maven AAR. */
    fun shouldBlockExecutorch(flags: CpuFlags): Boolean {
        return !flags.atomics && !isArmv8BaselineLibrary()
    }

    /** Determines whether ExecuTorch must be blocked given CPU flags and baseline AAR presence. */
    fun shouldBlockExecutorch(flags: CpuFlags, armv8Baseline: Boolean): Boolean {
        return !flags.atomics && !armv8Baseline
    }

    /** Checks whether ExecuTorch execution is blocked on this device. */
    fun isExecutorchBlocked(): Boolean = shouldBlockExecutorch(currentFlags())

    /** Checks whether ExecuTorch execution is blocked for [flags]. */
    fun isExecutorchBlocked(flags: CpuFlags): Boolean = shouldBlockExecutorch(flags)

    /** Formats CPU flags, RAM, and assigned tier for diagnostic logs. */
    fun formatFlags(flags: CpuFlags, ramBytes: Long, tier: Tier): String {
        return "cpu_features atomics=${flags.atomics} asimddp=${flags.asimddp} fphp=${flags.fphp} " +
            "bf16=${flags.bf16} " +
            "i8mm=${flags.i8mm} sve=${flags.sve} sve2=${flags.sve2} sme=${flags.sme} sme2=${flags.sme2} " +
            "ram_bytes=$ramBytes tier=$tier"
    }

    /** Checks whether /proc/cpuinfo lacked a Features line. */
    fun isFeaturesUnknown(): Boolean {
        return try {
            val content = File(CPUINFO_PATH).readText(Charsets.UTF_8)
            !content.lineSequence().any { it.trimStart().startsWith("Features") }
        } catch (_: Exception) {
            true
        }
    }

    /** Returns diagnostic suffix when CPU features could not be read. */
    internal fun unknownFeaturesSuffix(isUnknown: Boolean, tier: Tier): String =
        if (isUnknown) " features=unknown fallback=NEON tier=$tier" else ""

    /** Emits one-time system diagnostics logging detected CPU features and thread counts. */
    fun logOnce(context: Context?) {
        if (logged) return
        logged = true
        try {
            val flags = currentFlags()
            val ram = currentTotalRamBytes(context)
            val tier = tierForFlags(flags, ram)
            val unknownSuffix = unknownFeaturesSuffix(isFeaturesUnknown(), tier)
            Log.i(TIMING_TAG, formatFlags(flags, ram, tier) + unknownSuffix)
        } catch (e: Exception) {
        }
        try {
            val flags = currentFlags()
            val clusters = currentClusters()
            val proposal = proposeThreadCount(clusters)
            val usedDefault = ModelLoadPlan.selectThreadCount(Runtime.getRuntime().availableProcessors())
            val autoEnabled = try {
                val dir = try {
                    context?.let { File(it.getExternalFilesDir(null), "models") }
                } catch (_: Exception) {
                    null
                }
                isThreadsAutoEnabled(dir)
            } catch (_: Exception) {
                false
            }
            val used = if (autoEnabled) proposal else usedDefault
            val tier = tierForFlags(flags, currentTotalRamBytes(context))
            val unknownSuffix = unknownFeaturesSuffix(isFeaturesUnknown(), tier)
            Log.i(TIMING_TAG, formatAccelLine(flags, clusters) + unknownSuffix)
            Log.i(TIMING_TAG, "threads_proposal=$proposal threads_used=$used threads_auto=$autoEnabled")
        } catch (e: Exception) {
        }
    }

    /** Resets cached hardware detection state for test isolation. */
    internal fun resetForTest() {
        cachedFlags = null
        cachedRamBytes = null
        logged = false
    }
}
