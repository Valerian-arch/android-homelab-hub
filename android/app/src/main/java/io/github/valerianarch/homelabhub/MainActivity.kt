package io.github.valerianarch.homelabhub

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import io.github.valerianarch.homelabhub.data.PairingLinks
import io.github.valerianarch.homelabhub.ui.DashboardScreen
import io.github.valerianarch.homelabhub.ui.DetailScreen
import io.github.valerianarch.homelabhub.ui.PairScreen
import io.github.valerianarch.homelabhub.ui.SettingsScreen
import io.github.valerianarch.homelabhub.ui.theme.HomelabHubTheme

class MainActivity : ComponentActivity() {

    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handlePairingLink(intent)
        setContent {
            HomelabHubTheme {
                HomelabApp(viewModel)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handlePairingLink(intent)
    }

    /** homelabhub://pair?... opened from the camera app or a browser: pre-fill, never auto-pair. */
    private fun handlePairingLink(intent: Intent?) {
        val link = intent?.dataString?.let(PairingLinks::parse) ?: return
        viewModel.offerPairing(link)
    }
}

@Composable
fun HomelabApp(vm: AppViewModel) {
    val context = LocalContext.current
    val screen = vm.screen

    BackHandler(enabled = screen !is Screen.Dashboard && !(screen is Screen.Pair && vm.hubUrl == null)) {
        vm.back()
    }

    when (screen) {
        Screen.Pair -> PairScreen(
            savedHubUrl = vm.hubUrl,
            prefill = vm.prefill,
            notice = vm.notice,
            error = vm.error,
            pairing = vm.pairing,
            onPair = { url, code -> vm.pair(url, code, deviceName(context)) },
        )
        Screen.Dashboard -> DashboardScreen(
            dashboard = vm.dashboard,
            loading = vm.loading,
            error = vm.error,
            load = vm::load,
            onRefresh = vm::refresh,
            onOpenService = { vm.open(Screen.Detail(it)) },
            onOpenSettings = { vm.open(Screen.Settings) },
        )
        is Screen.Detail -> DetailScreen(
            service = vm.dashboard?.services?.firstOrNull { it.id == screen.serviceId },
            onBack = { vm.back() },
        )
        Screen.Settings -> SettingsScreen(
            hubUrl = vm.hubUrl,
            hubVersion = vm.dashboard?.hubVersion,
            onRepair = { vm.open(Screen.Pair) },
            onUnpair = vm::unpair,
            onBack = { vm.back() },
        )
    }
}

/** The name shown on the Hub's Phones page, e.g. "Galaxy S26 Ultra". */
private fun deviceName(context: android.content.Context): String =
    Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME)?.takeIf { it.isNotBlank() }
        ?: "${Build.MANUFACTURER} ${Build.MODEL}"
