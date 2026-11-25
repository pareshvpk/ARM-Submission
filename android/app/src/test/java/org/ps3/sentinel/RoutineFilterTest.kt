package org.ps3.sentinel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.ps3.sentinel.core.isRegisteredSender
import org.ps3.sentinel.core.senderCue
import org.ps3.sentinel.core.shouldSkip
import org.ps3.sentinel.core.skipKind

class RoutineFilterTest {

    private val otpText = "123456 is your OTP for login. Valid for 10 minutes."

    @Test
    fun testOtpIsSkipped() {
        assertEquals("otp", skipKind(otpText))
    }

    @Test
    fun testTransactionIsSkipped() {
        assertEquals(
            "transaction",
            skipKind("Rs.500.00 debited from A/c XX1234 on 12-11-26. Avl bal Rs 2,000.")
        )
    }

    @Test
    fun testPhoneNumberInTextKeepsMessage() {
        assertNull(skipKind("Your A/c is debited Rs 5000. Not you? Call 9876543210"))
    }

    @Test
    fun testRequestWordsKeepMessage() {
        assertNull(skipKind("Share OTP 123456 with our agent to get refund"))
    }

    @Test
    fun testUrlKeepsMessage() {
        assertNull(skipKind("Your OTP is 4455. Verify at http://bit.ly/x"))
    }

    @Test
    fun testOtpAutofillEndingIsNotALink() {
        assertEquals("otp", skipKind("123456 is your OTP for login. Valid for 10 minutes.\n\n@example.com #123456"))
        assertNull(skipKind("Your OTP is 4455. Login at example.com/x now @example.com #4455"))
    }

    @Test
    fun testRegisteredHeaderWithOtpIsSkipped() {
        assertTrue(shouldSkip("AD-HDFCBK-S", otpText))
    }

    @Test
    fun testPhoneSenderWithOtpIsNotSkipped() {
        assertFalse(shouldSkip("+919876543210", otpText))
    }

    @Test
    fun testEmptySenderIsNotSkipped() {
        assertFalse(shouldSkip("", otpText))
    }

    @Test
    fun testRegisteredSenderDetection() {
        assertTrue(isRegisteredSender("AD-HDFCBK-S"))
        assertFalse(isRegisteredSender("+91 98765-43210"))
        assertFalse(isRegisteredSender("Unknown"))
    }

    @Test
    fun testDltHeaderTrueExamples() {
        for (sender in listOf("AD-HDFCBK", "VM-HDFCBK-S", "JM-JioPay", "AX-123456", "AD-123456-P", " ad-hdfcbk-s ")) {
            assertTrue(sender, isRegisteredSender(sender))
        }
    }

    @Test
    fun testDltHeaderFalseExamples() {
        for (sender in listOf("HDFCBK", "Google", "+919876543210", "9876543210", "Unknown", "", "HDFC-BANK-LTD", "A-HDFCBK")) {
            assertFalse(sender, isRegisteredSender(sender))
        }
    }

    @Test
    fun testTollFreeNumberKeepsMessage() {
        assertFalse(
            shouldSkip("AD-HDFCBK-S", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.")
        )
    }

    @Test
    fun testSpacedMobileKeepsMessage() {
        assertFalse(
            shouldSkip("AD-HDFCBK-S", "Rs 5,000 debited from A/c XX1234. Not you? Call 98765 43210")
        )
    }

    @Test
    fun testPlainDebitIsSkipped() {
        assertTrue(
            shouldSkip("AD-HDFCBK-S", "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000")
        )
    }

    @Test
    fun testNonDltSenderIsNotSkipped() {
        assertFalse(
            shouldSkip("HDFCBK", "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000")
        )
    }

    @Test
    fun testOtpFromDltHeaderIsSkipped() {
        assertTrue(shouldSkip("AD-HDFCBK", "482913 is your OTP for login. Valid 10 min."))
    }

    @Test
    fun testUpiCreditWithReferenceIsSkipped() {
        assertTrue(
            shouldSkip(
                "AD-HDFCBK-S",
                "Rs.500.00 credited to HDFC Bank A/c XX1234 on 12-11-26 from VPA user@okaxis (UPI 512345678901)"
            )
        )
    }

    @Test
    fun testCredentialRequestsFromDltHeaderAreNotSkipped() {
        val texts = listOf(
            "Rs 4,999 debited from A/c XX9012. Reply with your UPI PIN to reverse it.",
            "A/c XX9012 debited Rs 4,999. Reply with OTP 4821 to reverse the debit.",
            "Rs 4,999 debited from A/c XX9012. Enter the 6 digit code we sent to cancel the debit.",
            "Rs 4,999 debited from A/c XX9012. Provide your card CVV to reverse."
        )
        for (text in texts) {
            assertFalse(text, shouldSkip("AD-HDFCBK-S", text))
        }
    }

    @Test
    fun testGenuineOtpFromDltHeaderIsStillSkipped() {
        assertTrue(
            shouldSkip(
                "AD-HDFCBK",
                "482913 is your One Time Password (OTP) for login at Example. " +
                    "This OTP will only be valid for 10 minutes"
            )
        )
    }

    @Test
    fun testGenuineCreditAlertFromDltHeaderIsStillSkipped() {
        assertTrue(
            shouldSkip(
                "AD-HDFCBK",
                "Rs.500.00 credited to HDFC Bank A/c XX1234 on 12-11-26 from VPA user@okaxis " +
                    "(UPI 512345678901)"
            )
        )
    }

    @Test
    fun testMobileWithCountryCodeKeepsMessage() {
        assertFalse(
            shouldSkip("AD-HDFCBK-S", "Rs 5,000 debited from A/c XX1234. Call +91 98765 43210")
        )
    }

    @Test
    fun testSenderCueFiresForPersonalNumberAlert() {
        val cue = senderCue(
            "+919876543210",
            "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now."
        )
        assertEquals("sender_mismatch", cue?.type)
        assertEquals(39, cue?.start)
        assertEquals(52, cue?.end)
        assertEquals("1800 123 4567", cue?.text)
    }

    @Test
    fun testSenderCueFiresForSpacedMobileSender() {
        assertTrue(
            senderCue("98765 43210", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.") != null
        )
    }

    @Test
    fun testSenderCueIgnoresDltHeader() {
        assertNull(
            senderCue("AD-HDFCBK-S", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.")
        )
    }

    @Test
    fun testSenderCueRequiresACallbackNumber() {
        assertNull(
            senderCue(
                "+919876543210",
                "Rs 5,000 debited from A/c XX1234 on 12-Nov. Avl bal Rs 20,000"
            )
        )
    }

    @Test
    fun testSenderCueIgnoresNonTransactionText() {
        assertNull(senderCue("+919876543210", "Hi, call me on 98765 43210 when free"))
    }

    @Test
    fun testSenderCueIgnoresPaidViaUpiMessage() {
        assertNull(senderCue("+919876543210", "Rs 500 paid via UPI, call me on 98765 43210"))
    }

    @Test
    fun testSenderCueIgnoresPersonToPersonAccountPayment() {
        assertNull(senderCue("+919876543210", "I paid Rs 500 to your account, call me on 98765 43210"))
    }

    @Test
    fun testSenderCueFiresForCardDebitFromPersonalNumber() {
        assertTrue(
            senderCue("+919876543210", "Rs 5,000 debited from card XX1234. Not you? Call 98111 22333") != null
        )
    }

    @Test
    fun testSenderCueIgnoresShortCode() {
        assertNull(
            senderCue("56161", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.")
        )
    }

    @Test
    fun testSenderCueIgnoresEmptySender() {
        assertNull(
            senderCue("", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now.")
        )
    }

    @Test
    fun testRequestWordsFromDltHeaderAreNotSkipped() {
        val texts = listOf(
            "Rs 4,999 debited from A/c XX9012. Message OTP 4821 to stop debit.",
            "Rs 4,999 debited from A/c XX9012. Text OTP 4821 to block.",
            "Rs 4,999 debited from A/c XX9012. Quote the 6 digit code 482193 to stop the debit.",
            "Rs 4999 debit hua A/c XX9012 se. OTP 4821 bhejo.",
            "Rs 4,999 debited from A/c XX9012. Reach our helpline 011 2345 6789 to dispute.",
            "A/c XX9012 debited Rs 499. Pay Rs 99 via UPI to reactivate."
        )
        for (text in texts) {
            assertFalse(text, shouldSkip("AD-HDFCBK-S", text))
        }
    }

    @Test
    fun testSecretRequestBankAlertsFromDltHeaderAreNotSkipped() {
        val texts = listOf(
            "Rs 4,999 debited from A/c XX9012. Read out OTP 4821 to the officer.",
            "Rs 4,999 debited from A/c XX9012. Spell out the 6 digit code 482193.",
            "Rs 4,999 debited from A/c XX9012. Repeat the code 482193 to cancel the debit.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 bata do.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 bataye.",
            "Rs 4,999 debited from A/c XX9012. OTP 4821 daal do.",
            "Rs 5,000 debited from A/c XX1234. OTP 4821 required to stop the debit.",
            "Rs 5,000 debited from your account. Code 4821 required to stop the debit.",
            "Rs 5,000 debited from card 1234. Code 4821 required to stop the debit.",
            "Rs 500 paid from A/c XX1234. Code 1234 required to stop the payment."
        )
        for (text in texts) {
            assertFalse(text, shouldSkip("AD-HDFCBK-S", text))
        }
    }

    @Test
    fun testAsciiDigitsIgnoreDevanagariMoney() {
        assertNull(skipKind("Rs ५,००० debited from A/c XX1234"))
    }

    @Test
    fun testAsciiDigitsIgnoreDevanagariCode() {
        assertNull(skipKind("आपका OTP ४८२१ है"))
    }

    @Test
    fun testAsciiDigitsIgnoreDevanagariSender() {
        assertNull(senderCue("९८७६५४३२१०", "Rs 5,000 debited from A/c XX1234. Call 1800 123 4567 now."))
    }

    @Test
    fun testSenderCueFiresForTransferredAlertWithDifferentCallback() {
        assertTrue(
            senderCue(
                "+919876543210",
                "Rs 5,000 transferred from A/c XX1234 to VPA x@okaxis. Call 98111 22333 if not you."
            ) != null
        )
    }

    @Test
    fun testSenderCueIgnoresOwnNumberOnDebitAlert() {
        assertNull(
            senderCue(
                "+919876543210",
                "Rs 5,000 debited from A/c XX1234. Call 98765 43210 if not you."
            )
        )
    }

    @Test
    fun testSenderCueIgnoresFirstPersonCredit() {
        assertNull(senderCue("9876543210", "Rs 2,000 credited to my a/c, call me on 98765 43210"))
    }

    @Test
    fun testSenderCueIgnoresOwnNumberOnCreditAlert() {
        assertNull(
            senderCue(
                "+919876543210",
                "Rs 500 credited to a/c XX1234. Call 98765 43210 for queries."
            )
        )
    }

    @Test
    fun testRegisteredSenderRegressionCases() {
        val messagesNotSkipped = listOf(
            "AD-HDFCBK-S" to "Your OTP is 482913. Share this OTP with our agent to stop account block.",
            "AD-SBIINB-S" to "Congratulations! You won Rs 25000 prize. Claim: http://sbi-prize.xyz",
            "AD-HDFCBK-S" to "Refund of Rs 4999 pending. Enter UPI PIN to receive refund: http://bit.ly/rf",
            "AD-JIOINF-S" to "Activate your eSIM now or service stops today. Click http://jio-esim.top",
            "AD-SBIINB-S" to "Your account will be blocked today. Update KYC: http://sbi-kyc.xyz",
            "AD-HDFCBK-S" to "Rs 500 debited from a/c XX1234. Not you? call 9123456789 now"
        )
        for ((sender, text) in messagesNotSkipped) {
            assertFalse(text, shouldSkip(sender, text))
        }
        assertTrue(
            shouldSkip("AD-HDFCBK-S", "Rs 500 debited from a/c XX1234 on 23-11. Avl bal Rs 10000.")
        )
    }
}
