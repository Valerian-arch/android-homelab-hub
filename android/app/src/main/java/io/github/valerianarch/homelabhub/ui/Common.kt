package io.github.valerianarch.homelabhub.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

val StatusUp = Color(0xFF2E9E5B)
val StatusDegraded = Color(0xFFD69E2E)
val StatusDown = Color(0xFFD64545)
val StatusIdle = Color(0xFF8A94A1)

fun statusColor(status: String): Color = when (status) {
    "up", "online", "running", "connected", "enabled" -> StatusUp
    "degraded" -> StatusDegraded
    "down", "offline", "failing", "error" -> StatusDown
    else -> StatusIdle
}

fun statusLabel(status: String): String = when (status) {
    "up" -> "Up"
    "degraded" -> "Needs attention"
    "down" -> "Down"
    "paused" -> "Paused"
    "pending" -> "Checking…"
    else -> "Unknown"
}

@Composable
fun StatusDot(color: Color, size: Dp = 12.dp) {
    Box(Modifier.size(size).background(color, CircleShape))
}

@Composable
fun Banner(text: String, color: Color, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.15f)),
    ) {
        Text(text, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
    }
}

/** A section with a heading, used on the detail screen. */
@Composable
fun Section(title: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
        content()
    }
}

/** One line in a detail list: optional dot, main text, small second line, value on the right. */
@Composable
fun InfoRow(
    title: String,
    subtitle: String = "",
    trailing: String = "",
    dot: Color? = null,
    subtitleColor: Color = Color.Unspecified,
) {
    Card(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            if (dot != null) {
                StatusDot(dot, 10.dp)
                Box(Modifier.size(10.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (subtitle.isNotEmpty()) {
                    Text(subtitle, style = MaterialTheme.typography.bodySmall,
                        color = if (subtitleColor == Color.Unspecified) MaterialTheme.colorScheme.onSurfaceVariant else subtitleColor,
                        maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
            }
            if (trailing.isNotEmpty()) {
                Text(trailing, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 8.dp))
            }
        }
    }
}

@Composable
fun EmptyLine(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

fun gib(bytes: Double?): String = if (bytes == null) "?" else String.format(Locale.US, "%.1f", bytes / (1024.0 * 1024 * 1024))

fun pct(value: Double?): String = if (value == null) "–" else String.format(Locale.US, "%.0f%%", value)

/** "2026-11-08T17:00:00+00:00" → "11:00:00" in the phone's time zone. */
fun localTime(iso: String?): String = try {
    if (iso == null) "" else OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("HH:mm:ss"))
} catch (e: Exception) {
    ""
}

/** Upcoming dates: "2026-11-10T01:00:00Z" → "Tue 10 Nov 01:00" local. */
fun localDate(iso: String?): String = try {
    if (iso.isNullOrEmpty()) "" else OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("EEE d MMM HH:mm", Locale.getDefault()))
} catch (e: Exception) {
    iso ?: ""
}
