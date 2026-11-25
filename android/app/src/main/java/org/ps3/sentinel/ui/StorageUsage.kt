/**
 * Calculates total disk space used by application binaries, caches, and AI model files.
 * Recursively sums directory and file sizes across internal and external storage roots.
 * Stateless utility called from background coroutines in SettingsActivity.
 */
package org.ps3.sentinel.ui

import java.io.File

/**
 * Purpose:  Sums on-disk sizes for the Storage used screen.
 * Owns:     Nothing.
 * Lifetime: Stateless.
 * Thread:   Safe to call from any thread; callers use a background thread.
 */
object StorageUsage {

    /**
     * Recursively computes the total size in bytes for all existing files under [roots].
     *
     * @param roots List of files or directories to measure. Non-existent roots are skipped.
     * @return Cumulative size in bytes.
     */
    fun totalBytes(roots: List<File>): Long {
        var total = 0L
        for (root in roots) {
            total += sizeOf(root)
        }
        return total
    }

    private fun sizeOf(file: File): Long {
        if (!file.exists()) return 0L
        if (file.isFile) return file.length()
        val children = file.listFiles() ?: return 0L
        var total = 0L
        for (child in children) {
            total += sizeOf(child)
        }
        return total
    }
}
