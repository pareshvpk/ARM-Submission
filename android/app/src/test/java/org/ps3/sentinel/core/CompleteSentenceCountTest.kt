package org.ps3.sentinel.core

import org.junit.Assert.assertEquals
import org.junit.Test

class CompleteSentenceCountTest {

    @Test
    fun emptyTextIsZero() {
        assertEquals(0, completeSentenceCount(""))
    }

    @Test
    fun unfinishedSentenceIsZero() {
        assertEquals(0, completeSentenceCount("This message looks suspicious"))
    }

    @Test
    fun threeFinishedSentencesIsThree() {
        assertEquals(3, completeSentenceCount("This is one. This is two. This is three."))
    }

    @Test
    fun fourFinishedSentencesPlusFragmentIsFour() {
        assertEquals(
            4,
            completeSentenceCount("One thing. Two things. Three things. Four things. Five")
        )
    }

    @Test
    fun decimalInsideOneSentenceCountsAsOne() {
        assertEquals(1, completeSentenceCount("You paid Rs 1.5 lakh to a fraudster."))
    }
}