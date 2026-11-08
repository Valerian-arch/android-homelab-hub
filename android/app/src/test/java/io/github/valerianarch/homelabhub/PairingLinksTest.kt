package io.github.valerianarch.homelabhub

import io.github.valerianarch.homelabhub.data.PairingLink
import io.github.valerianarch.homelabhub.data.PairingLinks
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingLinksTest {

    @Test
    fun parsesHubQrCode() {
        // Exactly what the Hub's Phones page encodes (urlencode of url + code).
        val link = PairingLinks.parse("homelabhub://pair?url=http%3A%2F%2F192.168.1.50%3A8080&code=ABCD-EFGH")
        assertEquals(PairingLink("http://192.168.1.50:8080", "ABCD-EFGH"), link)
    }

    @Test
    fun rejectsOtherQrCodes() {
        assertNull(PairingLinks.parse("https://example.com"))
        assertNull(PairingLinks.parse("homelabhub://other?url=http%3A%2F%2Fa&code=X"))
        assertNull(PairingLinks.parse("homelabhub://pair?code=ABCD-EFGH")) // no url
        assertNull(PairingLinks.parse("homelabhub://pair?url=http%3A%2F%2Fa.b")) // no code
        assertNull(PairingLinks.parse("not a url at all %%%"))
    }

    @Test
    fun normalizesTypedAddresses() {
        assertEquals("http://192.168.1.50:8080", PairingLinks.normalizeHubUrl(" 192.168.1.50:8080/ "))
        assertEquals("https://hub.example.lan", PairingLinks.normalizeHubUrl("https://hub.example.lan"))
        assertNull(PairingLinks.normalizeHubUrl(""))
        assertNull(PairingLinks.normalizeHubUrl("http://user:pass@hub.lan")) // no credentials in URLs
    }

    @Test
    fun detectsEncryption() {
        assertTrue(PairingLinks.isEncrypted("https://hub.lan"))
        assertFalse(PairingLinks.isEncrypted("http://hub.lan"))
    }
}
