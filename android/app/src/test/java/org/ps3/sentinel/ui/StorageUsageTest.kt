package org.ps3.sentinel.ui

import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class StorageUsageTest {

    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun sumsNestedFiles() {
        val root = temp.newFolder("root")
        File(root, "a.bin").writeBytes(ByteArray(10))
        val nested = File(root, "nested").apply { mkdirs() }
        File(nested, "b.bin").writeBytes(ByteArray(25))
        File(nested, "c.bin").writeBytes(ByteArray(5))

        assertEquals(40L, StorageUsage.totalBytes(listOf(root)))
    }

    @Test
    fun missingRootCountsZero() {
        val missing = File(temp.root, "does-not-exist")

        assertEquals(0L, StorageUsage.totalBytes(listOf(missing)))
    }

    @Test
    fun emptyDirectoryCountsZero() {
        val empty = temp.newFolder("empty")

        assertEquals(0L, StorageUsage.totalBytes(listOf(empty)))
    }

    @Test
    fun sumsMultipleRootsAndSkipsMissing() {
        val first = temp.newFolder("first")
        File(first, "one.bin").writeBytes(ByteArray(7))
        val second = temp.newFolder("second")
        File(second, "two.bin").writeBytes(ByteArray(3))
        val missing = File(temp.root, "missing")

        assertEquals(
            10L,
            StorageUsage.totalBytes(listOf(first, missing, second))
        )
    }
}
