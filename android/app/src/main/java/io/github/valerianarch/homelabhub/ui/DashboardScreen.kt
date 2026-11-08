package io.github.valerianarch.homelabhub.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import io.github.valerianarch.homelabhub.data.Dashboard
import io.github.valerianarch.homelabhub.data.HubService
import kotlinx.coroutines.delay

private val SUMMARY_ORDER = listOf("down", "degraded", "up", "unknown", "pending", "paused")

@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun DashboardScreen(
    dashboard: Dashboard?,
    loading: Boolean,
    error: String?,
    load: suspend () -> Unit,
    onRefresh: () -> Unit,
    onOpenService: (Int) -> Unit,
    onOpenSettings: () -> Unit,
) {
    // Refresh now, then every poll interval, but only while the app is on screen (saves battery).
    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                load()
                delay((dashboard?.pollIntervalSeconds ?: 60) * 1000L)
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Homelab Hub") },
                actions = { TextButton(onClick = onOpenSettings) { Text("Settings") } },
            )
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = loading && dashboard != null,
            onRefresh = onRefresh,
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            when {
                dashboard == null && error == null -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                    CircularProgressIndicator()
                }
                dashboard == null -> LazyColumn(Modifier.fillMaxSize().padding(16.dp)) {
                    item { Banner(error ?: "", StatusDown) }
                    item { Text("Pull down to try again.", Modifier.padding(top = 12.dp)) }
                }
                else -> ServiceList(dashboard, error, onOpenService)
            }
        }
    }
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun ServiceList(dashboard: Dashboard, error: String?, onOpenService: (Int) -> Unit) {
    val groups = dashboard.services.groupBy { it.category }
    val order = (dashboard.categories + groups.keys).distinct().filter { it in groups }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (error != null) {
            item { Banner("Showing the last known status. $error", StatusDegraded) }
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SUMMARY_ORDER.forEach { state ->
                    val count = dashboard.summary[state] ?: 0
                    if (count > 0) {
                        AssistChip(
                            onClick = {},
                            label = { Text("$count ${statusLabel(state).lowercase()}") },
                            leadingIcon = { StatusDot(statusColor(state), 10.dp) },
                        )
                    }
                }
            }
        }
        if (dashboard.services.isEmpty()) {
            item {
                Text(
                    "No services yet. Add some on the Hub's admin page and they'll appear here.",
                    Modifier.padding(top = 24.dp),
                )
            }
        }
        order.forEach { category ->
            item(key = "header-$category") {
                Text(
                    category.ifEmpty { "Other" },
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 12.dp, bottom = 4.dp),
                )
            }
            items(groups.getValue(category), key = { it.id }) { service ->
                ServiceCard(service) { onOpenService(service.id) }
            }
        }
    }
}

@Composable
private fun ServiceCard(service: HubService, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            StatusDot(statusColor(service.status))
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(service.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(
                    service.message.ifEmpty { statusLabel(service.status) },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                service.typeLabel,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 8.dp).widthIn(max = 96.dp),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
