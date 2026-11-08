package io.github.valerianarch.homelabhub.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.valerianarch.homelabhub.data.PairingLinks

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(hubUrl: String?, hubVersion: String?, onRepair: () -> Unit, onUnpair: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val appVersion = remember {
        runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "?"
    }
    var confirmUnpair by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings") },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Hub", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            Text(hubUrl ?: "Not paired")
            if (hubUrl != null && !PairingLinks.isEncrypted(hubUrl)) {
                Text(
                    "Connection is not encrypted (http://). Use it on your home Wi-Fi or over Tailscale.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!hubVersion.isNullOrEmpty()) Text("Hub version $hubVersion", style = MaterialTheme.typography.bodySmall)
            Text("App version $appVersion", style = MaterialTheme.typography.bodySmall)

            OutlinedButton(onClick = onRepair) { Text("Pair with a different Hub") }
            OutlinedButton(onClick = { confirmUnpair = true }) { Text("Unpair this phone") }
            Text(
                "Unpairing deletes this phone's token here and on the Hub. You can also remove phones on the Hub's Phones page.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    if (confirmUnpair) {
        AlertDialog(
            onDismissRequest = { confirmUnpair = false },
            title = { Text("Unpair this phone?") },
            text = { Text("You'll need a new pairing code from the Hub to connect again.") },
            confirmButton = {
                TextButton(onClick = { confirmUnpair = false; onUnpair() }) { Text("Unpair") }
            },
            dismissButton = { TextButton(onClick = { confirmUnpair = false }) { Text("Cancel") } },
        )
    }
}
