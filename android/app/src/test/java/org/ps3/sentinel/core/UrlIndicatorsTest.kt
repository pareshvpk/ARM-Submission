package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlIndicatorsTest {

    @Test
    fun testUrlIndicatorsIpHost() {
        val ind = urlIndicators("http://192.168.1.1/login")
        assertTrue("Expected ip_host in $ind", "ip_host" in ind)
    }

    @Test
    fun testUrlIndicatorsPunycode() {
        val ind = urlIndicators("http://xn--80ak6aa92e.com/page")
        assertTrue("Expected punycode in $ind", "punycode" in ind)
    }

    @Test
    fun testUrlIndicatorsAtSign() {
        val ind = urlIndicators("http://user:pass@phish.com")
        assertTrue("Expected at_sign in $ind", "at_sign" in ind)
    }

    @Test
    fun testUrlIndicatorsManySubdomains() {
        val ind = urlIndicators("http://a.b.c.example.com/test")
        assertTrue("Expected many_subdomains in $ind", "many_subdomains" in ind)
    }

    @Test
    fun testUrlIndicatorsRiskyTld() {
        val ind = urlIndicators("http://secure-update.xyz/login")
        assertTrue("Expected risky_tld in $ind", "risky_tld" in ind)
    }

    @Test
    fun testUrlIndicatorsShortener() {
        val ind1 = urlIndicators("https://bit.ly/3xYz12")
        assertTrue("Expected shortener for bit.ly in $ind1", "shortener" in ind1)

        val ind2 = urlIndicators("http://tinyurl.com/abc")
        assertTrue("Expected shortener for tinyurl.com in $ind2", "shortener" in ind2)
    }

    @Test
    fun testUrlIndicatorsBrandLookalike() {
        // SBI lookalike: contains sbi, registered domain is not onlinesbi.sbi or sbi.co.in
        val indSbi = urlIndicators("http://sbi-kyc-update.xyz/login")
        assertTrue("Expected brand_lookalike for sbi-kyc-update.xyz in $indSbi", "brand_lookalike" in indSbi)

        // Official SBI domains: must NOT have brand_lookalike
        val indOff1 = urlIndicators("https://sbi.co.in/portal")
        assertFalse("Official sbi.co.in should not trigger brand_lookalike", "brand_lookalike" in indOff1)

        val indOff2 = urlIndicators("https://onlinesbi.sbi")
        assertFalse("Official onlinesbi.sbi should not trigger brand_lookalike", "brand_lookalike" in indOff2)

        // Official HDFC domain
        val indHdfc = urlIndicators("https://hdfcbank.com")
        assertFalse("Official hdfcbank.com should not trigger brand_lookalike", "brand_lookalike" in indHdfc)
    }

    @Test
    fun testGetRegisteredDomain() {
        assertEquals("sbi.co.in", getRegisteredDomain("sbi.co.in"))
        assertEquals("sbi.co.in", getRegisteredDomain("login.sbi.co.in"))
        assertEquals("example.com", getRegisteredDomain("example.com"))
        assertEquals("example.com", getRegisteredDomain("a.b.c.example.com"))
        assertEquals("uidai.gov.in", getRegisteredDomain("sub.uidai.gov.in"))
    }

    @Test
    fun testGetRegisteredDomainMatchesPythonForUnlistedTwoLetterSuffixes() {
        // Python only promotes a three-label domain when the two-part suffix is in its set.
        assertEquals("co.zz", getRegisteredDomain("secure.co.zz"))
        assertEquals("gov.zz", getRegisteredDomain("foo.gov.zz"))
        assertEquals("example.de", getRegisteredDomain("login.example.de"))
        assertEquals("b.co.in", getRegisteredDomain("a.b.co.in"))
    }

    @Test
    fun testMalformedUrlIsUnparseableInsteadOfThrowing() {
        assertEquals(listOf("unparseable_url"), urlIndicators("http://[bad-host"))
    }

    @Test
    fun testIpv6LiteralIsIpHost() {
        val indicators = urlIndicators("http://[2001:db8::1]/login")
        assertTrue("Expected ip_host for an IPv6 literal, found $indicators", "ip_host" in indicators)
    }

    @Test
    fun testIpAddressParsingMatchesPythonForEdgeCases() {
        assertTrue(isIpAddress("::1"))
        assertTrue(isIpAddress("2001:db8::1"))
        assertFalse(isIpAddress("1:2:3"))
        assertFalse(isIpAddress("12345::1"))
        assertFalse(isIpAddress("example.com"))
        assertTrue(isIpAddress("192.168.1.1"))
        assertFalse(isIpAddress("192.168.1.999"))
        assertFalse(isIpAddress("192.168.01.1"))
    }

    @Test
    fun testIpv6ValidLiterals() {
        assertTrue(isIpAddress("fe80::1"))
        assertTrue(isIpAddress("1:2:3:4:5:6:7:8"))
        assertTrue(isIpAddress("2001:0db8:0000:0000:0000:ff00:0042:8329"))
        assertTrue(isIpAddress("::"))
        assertTrue(isIpAddress("2001:db8:85a3::8a2e:370:7334"))
        assertTrue(isIpAddress("::ffff:192.0.2.128"))
        assertTrue(isIpAddress("2001:db8::192.0.2.1"))
        assertTrue(isIpAddress("1:2:3:4:5:6:192.168.1.1"))
        assertTrue(isIpAddress("[2001:db8::1]"))
    }

    @Test
    fun testIpv6InvalidLiterals() {
        assertFalse(isIpAddress("foo:bar"))
        assertFalse(isIpAddress("foo::bar"))
        assertFalse(isIpAddress("gggg::1"))
        assertFalse(isIpAddress("12:34::56::78"))
        assertFalse(isIpAddress("1:2:3:4:5:6:7:8:9"))
        assertFalse(isIpAddress("1:2:3:4:5:6:7"))
        assertFalse(isIpAddress("::ffff:999.1.1.1"))
        assertFalse(isIpAddress("::ffff:192.168.01.1"))
        assertFalse(isIpAddress("2001:db8::g1"))
        assertFalse(isIpAddress(":::"))
        assertFalse(isIpAddress(":"))
        assertFalse(isIpAddress("1:2:3:4:5:6:7:192.168.1.1"))
    }

    @Test
    fun testFooBarHostIsNotIpHost() {
        assertFalse(isIpAddress("foo:bar"))
        assertFalse("ip_host" in urlIndicators("http://[foo:bar]/login"))
    }
}
