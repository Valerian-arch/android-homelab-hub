package io.github.valerianarch.homelabhub.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.valerianarch.homelabhub.data.HubService
import io.github.valerianarch.homelabhub.data.num
import io.github.valerianarch.homelabhub.data.objects
import io.github.valerianarch.homelabhub.data.str
import io.github.valerianarch.homelabhub.data.strings
import org.json.JSONObject

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(service: HubService?, onBack: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(service?.name ?: "Service") },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (service == null) {
                Text("This service no longer exists on the Hub.")
                return@Column
            }
            Header(service)
            when (service.type) {
                "proxmox" -> Proxmox(service.data)
                "sonarr", "radarr" -> MediaArr(service.data)
                "prowlarr" -> Prowlarr(service.data)
                "sabnzbd", "nzbget", "qbittorrent" -> Downloader(service.data)
                "qui" -> Qui(service.data)
                "jellyfin" -> Jellyfin(service.data)
                else -> {}
            }
        }
    }
}

@Composable
private fun Header(service: HubService) {
    val context = LocalContext.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        StatusDot(statusColor(service.status), 14.dp)
        Text(
            statusLabel(service.status),
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(start = 10.dp),
        )
    }
    if (service.message.isNotEmpty()) Text(service.message, style = MaterialTheme.typography.bodyMedium)
    val meta = listOfNotNull(
        service.typeLabel.ifEmpty { null },
        service.latencyMs?.let { "$it ms" },
        localTime(service.checkedAt).ifEmpty { null }?.let { "checked $it" },
    ).joinToString(" · ")
    if (meta.isNotEmpty()) {
        Text(meta, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    // Only open real web addresses (the Hub already validates this; double-check anyway).
    val link = service.linkUrl
    if (link.startsWith("http://", ignoreCase = true) || link.startsWith("https://", ignoreCase = true)) {
        Button(
            onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(link))) },
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        ) { Text("Open ${service.name}") }
    }
}

@Composable
private fun Health(data: JSONObject, key: String = "health") {
    val items = if (key == "warnings") data.strings(key).map { it to "warning" }
    else data.objects(key).map { it.str("message") to it.str("level") }
    if (items.isEmpty()) return
    Section(if (key == "warnings") "Warnings" else "Health") {
        items.forEach { (message, level) ->
            InfoRow(message, dot = if (level == "error") StatusDown else StatusDegraded)
        }
    }
}

@Composable
private fun Proxmox(data: JSONObject) {
    Section("Nodes") {
        data.objects("nodes").forEach { n ->
            val total = n.num("mem_total")
            InfoRow(
                title = n.str("name"),
                subtitle = "CPU ${pct(n.num("cpu_pct"))}" +
                    if (total != null) " · RAM ${gib(n.num("mem_used"))} / ${gib(total)} GiB (${pct(n.num("mem_pct"))})" else "",
                trailing = n.str("status"),
                dot = statusColor(n.str("status")),
            )
        }
    }
    val guests = data.objects("guests")
    Section("VMs and containers (${guests.size})") {
        if (guests.isEmpty()) EmptyLine("No VMs or containers visible to this token.")
        guests.forEach { g ->
            val total = g.num("mem_total")
            InfoRow(
                title = "${g.optInt("vmid")} ${g.str("name")}",
                subtitle = "${g.str("type")} on ${g.str("node")} · CPU ${pct(g.num("cpu_pct"))}" +
                    if (total != null) " · RAM ${gib(g.num("mem_used"))} / ${gib(total)} GiB" else "",
                trailing = g.str("status"),
                dot = statusColor(g.str("status")),
            )
        }
    }
}

@Composable
private fun MediaArr(data: JSONObject) {
    Health(data)
    val queue = data.objects("queue")
    val total = data.optInt("queue_total", queue.size)
    Section(if (total > queue.size) "Queue (first ${queue.size} of $total)" else "Queue ($total)") {
        if (queue.isEmpty()) EmptyLine("Nothing in the queue.")
        queue.forEach { q ->
            val problem = q.str("problem")
            InfoRow(
                title = q.str("title"),
                subtitle = if (problem.isNotEmpty()) "⚠ $problem" else listOf(q.str("state").ifEmpty { q.str("status") }, q.str("timeleft"))
                    .filter { it.isNotEmpty() }.joinToString(" · "),
                subtitleColor = if (problem.isNotEmpty()) StatusDegraded else androidx.compose.ui.graphics.Color.Unspecified,
                trailing = pct(q.num("progress")),
            )
        }
    }
    val upcoming = data.objects("upcoming")
    Section("Upcoming") {
        if (upcoming.isEmpty()) EmptyLine("Nothing upcoming.")
        upcoming.forEach { u ->
            InfoRow(
                title = u.str("title"),
                subtitle = "${u.str("kind")} ${localDate(u.str("date"))}".trim(),
                trailing = if (u.optBoolean("has_file")) "✓" else "",
            )
        }
    }
}

@Composable
private fun Prowlarr(data: JSONObject) {
    Health(data)
    val indexers = data.objects("indexers")
    Section("Indexers (${indexers.size})") {
        indexers.forEach { ix ->
            val state = when {
                ix.optBoolean("failing") -> "failing"
                ix.optBoolean("enabled") -> "enabled"
                else -> "disabled"
            }
            InfoRow(ix.str("name"), subtitle = ix.str("protocol"), trailing = state, dot = statusColor(state))
        }
    }
}

@Composable
private fun Downloader(data: JSONObject) {
    Health(data, "warnings")
    val speed = data.str("download_speed").ifEmpty { data.str("speed") }
    val parts = listOfNotNull(
        if (data.optBoolean("paused")) "Paused" else speed.ifEmpty { null }?.let { "↓ $it" },
        data.str("upload_speed").ifEmpty { null }?.let { "↑ $it" },
        data.str("timeleft").ifEmpty { null }?.let { "$it left" },
        data.num("disk_free_gb")?.let { String.format(java.util.Locale.US, "%.1f GB free", it) },
        data.str("connection").ifEmpty { null },
    )
    if (parts.isNotEmpty()) Text(parts.joinToString(" · "), style = MaterialTheme.typography.bodyMedium)

    val queue = data.objects("queue")
    val total = data.optInt("queue_total", queue.size)
    Section(if (total > queue.size) "Queue (first ${queue.size} of $total)" else "Queue ($total)") {
        if (queue.isEmpty()) EmptyLine("Nothing downloading.")
        queue.forEach { q ->
            InfoRow(
                title = q.str("name"),
                subtitle = listOf(q.str("status"), q.str("speed"), q.str("timeleft"), q.str("category"))
                    .filter { it.isNotEmpty() }.joinToString(" · "),
                trailing = pct(q.num("progress")),
            )
        }
    }
    val failed = data.objects("failed")
    if (failed.isNotEmpty()) {
        Section("Failed (${data.optInt("failed_total", failed.size)})") {
            failed.forEach { f -> InfoRow(f.str("name"), subtitle = f.str("reason"), subtitleColor = StatusDown) }
        }
    }
}

@Composable
private fun Qui(data: JSONObject) {
    Section("qBittorrent instances") {
        data.objects("instances").forEach { i ->
            val connected = i.optBoolean("connected")
            InfoRow(
                title = i.str("name"),
                subtitle = if (connected) "↓ ${i.str("download_speed")} ↑ ${i.str("upload_speed")}" else i.str("error"),
                trailing = if (connected) i.str("connection").ifEmpty { "connected" } else "disconnected",
                dot = if (connected) StatusUp else StatusDown,
            )
        }
    }
}

@Composable
private fun Jellyfin(data: JSONObject) {
    val counts = data.optJSONObject("counts") ?: JSONObject()
    Text(
        listOf(
            "${counts.optInt("movies")} movies",
            "${counts.optInt("series")} series",
            "${counts.optInt("episodes")} episodes",
        ).joinToString(" · ") + if (counts.optInt("songs") > 0) " · ${counts.optInt("songs")} songs" else "",
        style = MaterialTheme.typography.bodyMedium,
    )
    val streams = data.objects("streams")
    Section("Now playing (${streams.size})") {
        if (streams.isEmpty()) EmptyLine("Nobody is watching right now.")
        streams.forEach { s ->
            InfoRow(
                title = s.str("title"),
                subtitle = listOf(s.str("user"), s.str("device"), if (s.optBoolean("paused")) "paused" else "")
                    .filter { it.isNotEmpty() }.joinToString(" · "),
                trailing = (if (s.optBoolean("transcoding")) "Transcode · " else "") + pct(s.num("progress")),
            )
        }
    }
}
