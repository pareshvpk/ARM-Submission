package org.ps3.sentinel.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CpuFeaturesTest {

    @Test
    fun testParseM31NoAtomicsNoDotProduct() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertFalse(flags.atomics)
        assertFalse(flags.asimddp)
        assertFalse(flags.fphp)
        assertFalse(flags.bf16)
        assertFalse(flags.i8mm)
        assertFalse(flags.sve)
        assertFalse(flags.sve2)
        assertFalse(flags.sme)
        assertFalse(flags.sme2)
        assertEquals("NEON", CpuFeatures.bestKernelPath(flags))
        assertTrue(CpuFeatures.shouldBlockExecutorch(flags, armv8Baseline = false))
        assertFalse(CpuFeatures.shouldBlockExecutorch(flags, armv8Baseline = true))
    }

    @Test
    fun testParseF12AtomicsNoDotProduct() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertTrue(flags.atomics)
        assertFalse(flags.asimddp)
        assertTrue(flags.fphp)
        assertFalse(flags.bf16)
        assertFalse(flags.i8mm)
        assertFalse(flags.sve)
        assertFalse(flags.sve2)
        assertEquals("NEON", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testParseMotoG73HasDotProduct() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertTrue(flags.atomics)
        assertTrue(flags.asimddp)
        assertEquals("DOTPROD", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testParseM32HasDotProduct() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertTrue(flags.atomics)
        assertTrue(flags.asimddp)
        assertEquals("DOTPROD", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testParseF14HasDotProductAndFp16() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertTrue(flags.atomics)
        assertTrue(flags.asimddp)
        assertTrue(flags.fphp)
        assertFalse(flags.i8mm)
        assertFalse(flags.sme2)
        assertEquals("DOTPROD", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testParseSyntheticArmv9Sme2AndI8mm() {
        val line = "Features\t\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp bf16 sve sve2 sme sme2 i8mm"
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\n$line\n")
        assertTrue(flags.atomics)
        assertTrue(flags.asimddp)
        assertTrue(flags.fphp)
        assertTrue(flags.bf16)
        assertTrue(flags.i8mm)
        assertTrue(flags.sve)
        assertTrue(flags.sve2)
        assertTrue(flags.sme)
        assertTrue(flags.sme2)
        assertEquals("SME2", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testParseFlagsLineDirect() {
        val flags = CpuFeatures.parseFeaturesLine("fp asimd atomics asimddp fphp bf16 i8mm sve sve2 sme sme2")
        assertTrue(flags.atomics)
        assertTrue(flags.asimddp)
        assertTrue(flags.fphp)
        assertTrue(flags.bf16)
        assertTrue(flags.i8mm)
        assertTrue(flags.sve)
        assertTrue(flags.sve2)
        assertTrue(flags.sme)
        assertTrue(flags.sme2)
        assertEquals("SME2", CpuFeatures.bestKernelPath(flags))
    }

    @Test
    fun testBestKernelPathOrder() {
        assertEquals("SME2", CpuFeatures.bestKernelPath(CpuFlags(sme2 = true, i8mm = true, asimddp = true)))
        assertEquals("I8MM", CpuFeatures.bestKernelPath(CpuFlags(i8mm = true, asimddp = true)))
        assertEquals("DOTPROD", CpuFeatures.bestKernelPath(CpuFlags(asimddp = true)))
        assertEquals("NEON", CpuFeatures.bestKernelPath(CpuFlags()))
    }

    @Test
    fun testParseClustersGroupsByFreq() {
        val freqByCpu = mapOf(
            0 to 2200000000L, 1 to 2200000000L,
            2 to 2000000000L, 3 to 2000000000L, 4 to 2000000000L, 5 to 2000000000L, 6 to 2000000000L, 7 to 2000000000L
        )
        val clusters = CpuFeatures.parseClusters(freqByCpu)
        assertEquals(2, clusters.size)
        assertEquals(2200000000L to 2, clusters[0])
        assertEquals(2000000000L to 6, clusters[1])
        assertEquals("2@2200000000+6@2000000000", CpuFeatures.formatClusters(clusters))
    }

    @Test
    fun testParseClustersEmpty() {
        assertTrue(CpuFeatures.parseClusters(emptyMap()).isEmpty())
        assertEquals("unknown", CpuFeatures.formatClusters(emptyList()))
    }

    @Test
    fun testProposeThreadCount() {
        assertEquals(2, CpuFeatures.proposeThreadCount(listOf(2200000000L to 2, 2000000000L to 6)))
        assertEquals(4, CpuFeatures.proposeThreadCount(listOf(2310000000L to 4, 1740000000L to 4)))
        assertEquals(4, CpuFeatures.proposeThreadCount(listOf(2000000000L to 8)))
        assertEquals(2, CpuFeatures.proposeThreadCount(emptyList()))
    }

    @Test
    fun testFormatAccelLine() {
        val flags = CpuFlags(asimddp = true)
        val line = CpuFeatures.formatAccelLine(flags, listOf(2200000000L to 2, 2000000000L to 6))
        assertTrue(line.startsWith("accel_path=DOTPROD"))
        assertTrue(line.contains("clusters=2@2200000000+6@2000000000"))
    }

    @Test
    fun testParseNullLineAllFalse() {
        val flags = CpuFeatures.parseFeaturesLine(null)
        assertFalse(flags.atomics)
        assertFalse(flags.asimddp)
    }

    @Test
    fun testParseUnreadableFallsBackConservative() {
        val flags = CpuFeatures.parseCpuInfo("")
        assertFalse(flags.atomics)
        assertFalse(flags.asimddp)
        assertFalse(flags.sme2)
        assertEquals("NEON", CpuFeatures.bestKernelPath(flags))
        assertEquals(CpuFeatures.Tier.LIGHT, CpuFeatures.tierForFlags(flags, 8L * 1024L * 1024L * 1024L))
        assertTrue(CpuFeatures.shouldBlockExecutorch(flags, armv8Baseline = false))
        val fallback = CpuFeatures.fallbackFlags()
        assertFalse(fallback.atomics)
        assertFalse(fallback.asimddp)
        assertEquals("NEON", CpuFeatures.bestKernelPath(fallback))
        val flags2 = CpuFeatures.parseCpuInfo(null)
        assertFalse(flags2.atomics)
        assertFalse(flags2.asimddp)
        assertEquals("NEON", CpuFeatures.bestKernelPath(flags2))
    }

    @Test
    fun testParseNoFeaturesLineFallsBackConservative() {
        val flags = CpuFeatures.parseCpuInfo("processor\t: 0\nmodel name\t: ARM\n")
        assertFalse(flags.atomics)
        assertFalse(flags.asimddp)
        assertEquals("NEON", CpuFeatures.bestKernelPath(flags))
        assertEquals(CpuFeatures.Tier.LIGHT, CpuFeatures.tierForFlags(flags, 8L * 1024L * 1024L * 1024L))
    }

    @Test
    fun testTierFullRequiresDotProductAnd5GB() {
        val flags = CpuFlags(atomics = true, asimddp = true)
        assertEquals(CpuFeatures.Tier.FULL, CpuFeatures.tierForFlags(flags, 6L * 1024L * 1024L * 1024L))
        assertEquals(CpuFeatures.Tier.FULL, CpuFeatures.tierForFlags(flags, 5L * 1024L * 1024L * 1024L))
    }

    @Test
    fun testTierLightWhenNoDotProduct() {
        val flags = CpuFlags(atomics = true, asimddp = false)
        assertEquals(CpuFeatures.Tier.LIGHT, CpuFeatures.tierForFlags(flags, 6L * 1024L * 1024L * 1024L))
    }

    @Test
    fun testTierLightWhenLowRam() {
        val flags = CpuFlags(atomics = true, asimddp = true)
        assertEquals(CpuFeatures.Tier.LIGHT, CpuFeatures.tierForFlags(flags, 4L * 1024L * 1024L * 1024L))
    }

    @Test
    fun testTierNoneBelow3GB() {
        val flags = CpuFlags(atomics = true, asimddp = true)
        assertEquals(CpuFeatures.Tier.NONE, CpuFeatures.tierForFlags(flags, 2L * 1024L * 1024L * 1024L))
        assertEquals(CpuFeatures.Tier.NONE, CpuFeatures.tierForFlags(flags, 2_900L * 1024L * 1024L))
        assertEquals(CpuFeatures.Tier.LIGHT, CpuFeatures.tierForFlags(flags, 3L * 1024L * 1024L * 1024L))
    }

    @Test
    fun testUnknownSuffixPrintsComputedTier() {
        assertEquals(
            " features=unknown fallback=NEON tier=NONE",
            CpuFeatures.unknownFeaturesSuffix(true, CpuFeatures.Tier.NONE)
        )
        assertEquals(
            " features=unknown fallback=NEON tier=FULL",
            CpuFeatures.unknownFeaturesSuffix(true, CpuFeatures.Tier.FULL)
        )
        assertEquals("", CpuFeatures.unknownFeaturesSuffix(false, CpuFeatures.Tier.NONE))
    }

    @Test
    fun testTotalRamFromMemoryInfo() {
        assertEquals(12345L, CpuFeatures.totalRamBytesFromMemoryInfo(12345L))
    }
}
