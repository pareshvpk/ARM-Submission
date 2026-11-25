package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Test

class UrlFeaturesTest {

    @Test
    fun testNormaliseUrl() {
        val testCases = listOf(
            Pair("https://www.example.com/path/", "example.com/path"),
            Pair("http://EXAMPLE.com", "example.com"),
            Pair("www.test.co.in/foo/bar/", "test.co.in/foo/bar"),
            Pair("hxxp://www.phish.org/login", "phish.org/login"),
            Pair("bad[.]com/x?a=1", "bad.com/x?a=1"),
            Pair("bare-domain.com", "bare-domain.com"),
            Pair("http://[bad-host", "http://[bad-host"),
            Pair("", "")
        )

        for ((input, expected) in testCases) {
            assertEquals("normaliseUrl failed for: $input", expected, normaliseUrl(input))
        }
    }

    @Test
    fun testExtractUrlsNegatives() {
        val negatives = listOf(
            "Hello. World is fine",
            "Your bill is Rs.500 pay now",
            "Call me. Thanks",
            "Score was 3.5 today",
            "e.g. this",
            "I am ok.See you",
            "Version v1.2 released",
            "mail me at ravi@gmail.com"
        )

        for (text in negatives) {
            val extracted = extractUrls(text)
            assertEquals("Expected empty list for '$text', got $extracted", emptyList<String>(), extracted)
        }
    }

    @Test
    fun testExtractUrlsPositives() {
        val positives = listOf(
            Pair("Go to https://example.com.", listOf("https://example.com")),
            Pair("Use www.google.com today", listOf("www.google.com")),
            Pair("visit hxxp://bad[.]com/x", listOf("http://bad.com/x")),
            Pair("Update KYC at sbi-kyc.co.in/verify now", listOf("sbi-kyc.co.in/verify")),
            Pair("Click bit.ly/3abc", listOf("bit.ly/3abc")),
            Pair("Update at paytm-help.xyz now", listOf("paytm-help.xyz")),
            Pair("Offer amazon(.)in/offer", listOf("amazon.in/offer")),
            Pair("a.com and a.com again", listOf("a.com"))
        )

        for ((text, expected) in positives) {
            val extracted = extractUrls(text)
            assertEquals("extractUrls failed for '$text'", expected, extracted)
        }
    }
}
