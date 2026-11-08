package io.github.valerianarch.homelabhub.data

import java.net.URI
import java.net.URISyntaxException
import java.net.URLDecoder

/** What the Hub's pairing QR code contains: homelabhub://pair?url=<hub address>&code=ABCD-EFGH */
data class PairingLink(val hubUrl: String, val code: String)

object PairingLinks {

    fun parse(text: String): PairingLink? {
        val uri = try {
            URI(text.trim())
        } catch (e: URISyntaxException) {
            return null
        }
        if (!uri.scheme.equals("homelabhub", ignoreCase = true) || !uri.host.equals("pair", ignoreCase = true)) {
            return null
        }
        val params = (uri.rawQuery ?: "").split("&").mapNotNull { part ->
            val i = part.indexOf('=')
            if (i <= 0) null else decode(part.substring(0, i)) to decode(part.substring(i + 1))
        }.toMap()
        val url = params["url"]?.let { normalizeHubUrl(it) } ?: return null
        val code = params["code"]?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        return PairingLink(url, code)
    }

    /**
     * Cleans up a typed Hub address: adds http:// if missing, removes a trailing slash.
     * Returns null for anything that isn't a plain http(s) address (including user:password@).
     */
    fun normalizeHubUrl(input: String): String? {
        var text = input.trim().trimEnd('/')
        if (text.isEmpty()) return null
        if (!text.startsWith("http://", ignoreCase = true) && !text.startsWith("https://", ignoreCase = true)) {
            text = "http://$text"
        }
        val uri = try {
            URI(text)
        } catch (e: URISyntaxException) {
            return null
        }
        if (uri.host.isNullOrEmpty() || uri.userInfo != null) return null
        return text
    }

    fun isEncrypted(hubUrl: String): Boolean = hubUrl.startsWith("https://", ignoreCase = true)

    private fun decode(value: String): String = URLDecoder.decode(value, "UTF-8")
}
