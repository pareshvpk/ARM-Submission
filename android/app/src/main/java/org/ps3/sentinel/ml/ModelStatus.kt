// Formats model load states, integrity verification warnings, and error statuses.
// Pure Kotlin helper with no Android dependencies, producing single-line status summaries
// displayed across user-facing debug and home status indicators.

package org.ps3.sentinel.ml

/**
 * Inputs for the model status string.
 *
 * Bundled so the builder stays a one-argument pure function.
 */
data class ModelStatusInput(
    val missing: List<String>,
    val isUrlReady: Boolean,
    val loaded: List<String>,
    val refused: List<String>,
    val errors: List<String>,
    val warnings: List<String>,
    val isVerifying: Boolean,
    val rulesStatus: String?,
    val smsStatus: String
)

/**
 * Purpose:  Builds the model status string from plain inputs.
 * Owns:     Nothing. Borrows the input lists.
 * Lifetime: Process
 * Thread:   any — no Android or shared state is touched.
 */
object ModelStatus {
    /**
     * Builds the one-line model status. Never says All models available when a
     * model was refused, and prints each distinct warning once.
     *
     * @param input Aggregated status flags, missing lists, loaded models, and error descriptors.
     * @return Formatted human-readable status line.
     */
    fun build(input: ModelStatusInput): String {
        val distinctErrors = input.errors.distinct()
        val distinctWarnings = input.warnings.distinct()
        val base = if (input.refused.isNotEmpty()) {
            val loadedPart = if (input.loaded.isEmpty()) "none" else input.loaded.joinToString(", ")
            "Loaded: $loadedPart; Refused: ${input.refused.joinToString(", ")}"
        } else if (input.missing.isEmpty()) {
            "All models available (URL CNN + Llama 3.2)"
        } else if (input.isUrlReady) {
            val llamaMissing = input.missing.filter {
                it.startsWith("llama") || it.startsWith("tokenizer")
            }
            "URL CNN ready; Llama missing (${llamaMissing.joinToString(", ")})"
        } else {
            "Missing models: ${input.missing.joinToString(", ")}"
        }
        val status = buildString {
            append(base)
            if (input.rulesStatus != null) {
                append("; RULES ERROR: ")
                append(input.rulesStatus)
            }
            append("; SMS model: ")
            append(input.smsStatus.take(80))
            if (input.isVerifying) {
                append("; verifying model integrity")
            }
            if (distinctErrors.isNotEmpty()) {
                append("; MODEL ERRORS: ")
                append(distinctErrors.joinToString(" | "))
            }
            if (distinctWarnings.isNotEmpty()) {
                append("; UNVERIFIED: ")
                append(distinctWarnings.joinToString(" | "))
            }
        }
        return status
    }
}
