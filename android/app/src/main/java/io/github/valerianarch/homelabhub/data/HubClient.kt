package io.github.valerianarch.homelabhub.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.MalformedURLException
import java.net.SocketTimeoutException
import java.net.URL

class HubException(message: String, val unauthorized: Boolean = false) : Exception(message)

/** Talks to the Hub's phone API (docs/API.md). Uses only Android's built-in HTTP client. */
object HubClient {

    private const val TIMEOUT_MS = 10_000
    private const val MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    suspend fun pair(hubUrl: String, code: String, deviceName: String): String = withContext(Dispatchers.IO) {
        val body = JSONObject().put("code", code).put("device_name", deviceName.take(60))
        val response = request("POST", "$hubUrl/api/v1/pair", token = null, body = body)
        response.optString("token").takeIf { it.isNotEmpty() }
            ?: throw HubException("The Hub didn't return a token. Is this a Homelab Hub?")
    }

    suspend fun dashboard(hubUrl: String, token: String): Dashboard = withContext(Dispatchers.IO) {
        parseDashboard(request("GET", "$hubUrl/api/v1/dashboard", token, body = null))
    }

    /** Best effort: tells the Hub to forget this phone. Local data is cleared either way. */
    suspend fun unpair(hubUrl: String, token: String) = withContext(Dispatchers.IO) {
        try {
            request("POST", "$hubUrl/api/v1/unpair", token, JSONObject())
        } catch (e: HubException) {
            // Hub unreachable or token already revoked: nothing else to do.
        }
        Unit
    }

    private fun request(method: String, url: String, token: String?, body: JSONObject?): JSONObject {
        val host = try {
            URL(url).host
        } catch (e: MalformedURLException) {
            throw HubException("That Hub address isn't valid.")
        }
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Accept", "application/json")
            if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                val bytes = body.toString().toByteArray()
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.setFixedLengthStreamingMode(bytes.size)
                connection.outputStream.use { it.write(bytes) }
            }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.use { readLimited(it) } ?: ""
            when {
                status == 401 -> throw HubException(detail(text) ?: "This phone isn't paired.", unauthorized = true)
                status == 429 -> throw HubException(detail(text) ?: "Too many attempts. Wait a few minutes.")
                status !in 200..299 -> throw HubException(detail(text) ?: "The Hub answered with HTTP $status.")
            }
            return try {
                JSONObject(text)
            } catch (e: JSONException) {
                throw HubException("Unexpected answer from $host. Is this the Homelab Hub address (including the port)?")
            }
        } catch (e: HubException) {
            throw e
        } catch (e: SocketTimeoutException) {
            throw HubException("$host didn't answer in time. Are you on your home Wi-Fi or Tailscale?")
        } catch (e: IOException) {
            throw HubException("Can't reach $host. Are you on your home Wi-Fi or Tailscale?")
        } finally {
            connection.disconnect()
        }
    }

    private fun readLimited(input: InputStream): String {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            out.write(buffer, 0, read)
            if (out.size() > MAX_RESPONSE_BYTES) throw HubException("The Hub's answer was too large.")
        }
        return out.toString("UTF-8")
    }

    /** The Hub's error JSON is {"detail": "..."}; validation errors use a list, which we skip. */
    private fun detail(text: String): String? = try {
        JSONObject(text).opt("detail") as? String
    } catch (e: JSONException) {
        null
    }
}
