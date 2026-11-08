package io.github.valerianarch.homelabhub.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.valerianarch.homelabhub.data.PairingLink
import io.github.valerianarch.homelabhub.data.PairingLinks

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PairScreen(
    savedHubUrl: String?,
    prefill: PairingLink?,
    notice: String?,
    error: String?,
    pairing: Boolean,
    onPair: (url: String, code: String) -> Unit,
) {
    var url by rememberSaveable { mutableStateOf(prefill?.hubUrl ?: savedHubUrl ?: "") }
    var code by rememberSaveable { mutableStateOf(prefill?.code ?: "") }
    var scanError by remember { mutableStateOf<String?>(null) }

    // A link opened from outside the app (e.g. the camera app) fills in the form.
    LaunchedEffect(prefill) {
        if (prefill != null) {
            url = prefill.hubUrl
            code = prefill.code
        }
    }

    val scanner = rememberLauncherForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@rememberLauncherForActivityResult // cancelled
        val link = PairingLinks.parse(text)
        if (link == null) {
            scanError = "That QR code isn't a Homelab Hub pairing code."
        } else {
            scanError = null
            url = link.hubUrl
            code = link.code
            onPair(link.hubUrl, link.code) // scanned in the app on purpose: pair right away
        }
    }

    Scaffold(topBar = { TopAppBar(title = { Text("Pair with your Hub") }) }) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            notice?.let { Banner(it, StatusDegraded) }
            if (prefill != null) {
                Banner("A pairing link was opened. Check the Hub address below, then tap Pair.", StatusIdle)
            }

            Text(
                "On your Hub's admin page, open Phones → Create pairing code. Then scan the QR code, " +
                    "or type the address and code below.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = {
                    scanner.launch(
                        ScanOptions()
                            .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("Scan the QR code on the Hub's Phones page")
                            .setBeepEnabled(false)
                            .setOrientationLocked(false)
                    )
                },
                enabled = !pairing,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Scan QR code") }

            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            Text("Or enter it manually", style = MaterialTheme.typography.titleSmall)

            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Hub address") },
                placeholder = { Text("http://192.168.1.50:8080") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = code,
                onValueChange = { code = it.take(16) },
                label = { Text("Pairing code") },
                placeholder = { Text("ABCD-EFGH") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                modifier = Modifier.fillMaxWidth(),
            )

            val normalized = PairingLinks.normalizeHubUrl(url)
            if (normalized != null && !PairingLinks.isEncrypted(normalized)) {
                Text(
                    "This address uses http:// (not encrypted). That's fine on your own Wi-Fi or over a VPN " +
                        "such as Tailscale, but avoid it on public networks.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            (scanError ?: error)?.let { Banner(it, StatusDown) }

            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = { onPair(url, code) }, enabled = !pairing) { Text("Pair") }
                if (pairing) {
                    CircularProgressIndicator(Modifier.padding(start = 16.dp).size(24.dp), strokeWidth = 2.dp)
                }
            }
            Text(
                "The phone only receives a read-only token. Your services' API keys and passwords stay on the Hub.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
