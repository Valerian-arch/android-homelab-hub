package io.github.valerianarch.homelabhub.data

import org.json.JSONObject

/** One service on the dashboard. [data] depends on [type]; see docs/API.md in the repo. */
data class HubService(
    val id: Int,
    val name: String,
    val type: String,
    val typeLabel: String,
    val category: String,
    val linkUrl: String,
    val status: String,
    val message: String,
    val latencyMs: Int?,
    val checkedAt: String?,
    val data: JSONObject,
)

data class Dashboard(
    val hubVersion: String,
    val pollIntervalSeconds: Int,
    val summary: Map<String, Int>,
    val categories: List<String>,
    val services: List<HubService>,
)

fun JSONObject.str(key: String): String = if (isNull(key)) "" else optString(key, "")

fun JSONObject.objects(key: String): List<JSONObject> {
    val array = optJSONArray(key) ?: return emptyList()
    return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
}

fun JSONObject.strings(key: String): List<String> {
    val array = optJSONArray(key) ?: return emptyList()
    return (0 until array.length()).mapNotNull { i -> array.optString(i).takeIf { !array.isNull(i) } }
}

/** Number or null, tolerating strings and missing values. */
fun JSONObject.num(key: String): Double? =
    if (isNull(key)) null else optDouble(key).takeIf { !it.isNaN() }

fun parseDashboard(json: JSONObject): Dashboard {
    val hub = json.optJSONObject("hub") ?: JSONObject()
    val summaryJson = json.optJSONObject("summary") ?: JSONObject()
    val summary = summaryJson.keys().asSequence().associateWith { summaryJson.optInt(it) }
    val services = json.objects("services").map { s ->
        HubService(
            id = s.optInt("id"),
            name = s.str("name"),
            type = s.str("type"),
            typeLabel = s.str("type_label"),
            category = s.str("category"),
            linkUrl = s.str("link_url"),
            status = s.str("status").ifEmpty { "unknown" },
            message = s.str("message"),
            latencyMs = if (s.isNull("latency_ms")) null else s.optInt("latency_ms"),
            checkedAt = s.str("checked_at").ifEmpty { null },
            data = s.optJSONObject("data") ?: JSONObject(),
        )
    }
    return Dashboard(
        hubVersion = hub.str("version"),
        pollIntervalSeconds = hub.optInt("poll_interval", 60).coerceAtLeast(10),
        summary = summary,
        categories = json.strings("categories"),
        services = services,
    )
}
