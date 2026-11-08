package io.github.valerianarch.homelabhub

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.valerianarch.homelabhub.data.Dashboard
import io.github.valerianarch.homelabhub.data.HubClient
import io.github.valerianarch.homelabhub.data.HubException
import io.github.valerianarch.homelabhub.data.PairingLink
import io.github.valerianarch.homelabhub.data.PairingLinks
import io.github.valerianarch.homelabhub.data.SecureStore
import kotlinx.coroutines.launch

sealed interface Screen {
    data object Pair : Screen
    data object Dashboard : Screen
    data class Detail(val serviceId: Int) : Screen
    data object Settings : Screen
}

class AppViewModel(app: Application) : AndroidViewModel(app) {

    private val store = SecureStore(app)

    var screen by mutableStateOf<Screen>(if (store.isPaired) Screen.Dashboard else Screen.Pair)
        private set
    var dashboard by mutableStateOf<Dashboard?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var pairing by mutableStateOf(false)
        private set
    /** One-off message shown on the pairing screen (e.g. "This phone was removed on the Hub"). */
    var notice by mutableStateOf<String?>(null)
        private set
    /** Values from a scanned/opened pairing link, waiting for the user to confirm. */
    var prefill by mutableStateOf<PairingLink?>(null)
        private set

    val hubUrl: String? get() = store.hubUrl

    fun open(target: Screen) {
        screen = target
    }

    /** Handles the system back button. Returns false when the app should close. */
    fun back(): Boolean = when (screen) {
        is Screen.Detail, Screen.Settings -> {
            screen = Screen.Dashboard
            true
        }
        Screen.Pair -> if (store.isPaired) {
            screen = Screen.Dashboard
            true
        } else {
            false
        }
        Screen.Dashboard -> false
    }

    /** A homelabhub://pair link opened from outside the app: show it, but let the user confirm. */
    fun offerPairing(link: PairingLink) {
        prefill = link
        notice = null
        error = null
        screen = Screen.Pair
    }

    fun pair(urlInput: String, codeInput: String, deviceName: String) {
        val url = PairingLinks.normalizeHubUrl(urlInput)
        if (url == null) {
            error = "Enter the Hub address, e.g. http://192.168.1.50:8080"
            return
        }
        if (codeInput.isBlank()) {
            error = "Enter the pairing code shown on the Hub's Phones page."
            return
        }
        viewModelScope.launch {
            pairing = true
            error = null
            try {
                val token = HubClient.pair(url, codeInput.trim(), deviceName)
                store.hubUrl = url
                store.token = token
                prefill = null
                notice = null
                dashboard = null
                screen = Screen.Dashboard
                load()
            } catch (e: HubException) {
                error = e.message
            } finally {
                pairing = false
            }
        }
    }

    fun refresh() {
        viewModelScope.launch { load() }
    }

    /** Fetches the dashboard. Called on open, on pull-to-refresh, and every poll interval while visible. */
    suspend fun load() {
        val url = store.hubUrl
        val token = store.token
        if (url == null || token == null) {
            screen = Screen.Pair
            return
        }
        if (loading) return
        loading = true
        try {
            dashboard = HubClient.dashboard(url, token)
            error = null
        } catch (e: HubException) {
            if (e.unauthorized) {
                forget("This phone was removed on the Hub (or the Hub was reset). Pair it again.")
            } else {
                error = e.message
            }
        } finally {
            loading = false
        }
    }

    fun unpair() {
        viewModelScope.launch {
            val url = store.hubUrl
            val token = store.token
            if (url != null && token != null) HubClient.unpair(url, token)
            forget("This phone is unpaired.")
        }
    }

    private fun forget(message: String) {
        store.token = null
        dashboard = null
        error = null
        notice = message
        screen = Screen.Pair
    }
}
