package io.github.valerianarch.homelabhub

import io.github.valerianarch.homelabhub.data.num
import io.github.valerianarch.homelabhub.data.objects
import io.github.valerianarch.homelabhub.data.parseDashboard
import io.github.valerianarch.homelabhub.data.str
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DashboardParsingTest {

    // Shape documented in docs/API.md.
    private val sample = """
        {
          "hub": {"name": "Homelab Hub", "version": "0.1.0", "poll_interval": 60, "generated_at": "2026-11-08T17:00:00+00:00"},
          "summary": {"up": 1, "degraded": 0, "down": 0, "unknown": 0, "pending": 0, "paused": 1},
          "categories": ["Infrastructure", ""],
          "services": [
            {"id": 2, "name": "Proxmox", "type": "proxmox", "type_label": "Proxmox VE", "category": "Infrastructure",
             "link_url": "https://192.168.1.20:8006", "status": "up", "message": "4/4 nodes online",
             "latency_ms": 299, "checked_at": "2026-11-08T17:00:00+00:00",
             "data": {"nodes": [{"name": "pve1", "mem_total": 15600000000, "cpu_pct": 3.9}], "guests": []}},
            {"id": 3, "name": "Old", "type": "http", "type_label": "HTTP(S) check", "category": "",
             "link_url": "", "status": "paused", "message": "", "latency_ms": null, "checked_at": null, "data": {}}
          ]
        }
    """.trimIndent()

    @Test
    fun parsesServicesAndDetails() {
        val dashboard = parseDashboard(JSONObject(sample))
        assertEquals("0.1.0", dashboard.hubVersion)
        assertEquals(60, dashboard.pollIntervalSeconds)
        assertEquals(1, dashboard.summary["paused"])
        assertEquals(listOf("Infrastructure", ""), dashboard.categories)

        val proxmox = dashboard.services[0]
        assertEquals("Proxmox VE", proxmox.typeLabel)
        assertEquals(299, proxmox.latencyMs)
        assertEquals("pve1", proxmox.data.objects("nodes")[0].str("name"))
        assertEquals(3.9, proxmox.data.objects("nodes")[0].num("cpu_pct")!!, 0.001)

        val paused = dashboard.services[1]
        assertNull(paused.latencyMs)
        assertNull(paused.checkedAt)
        assertEquals("", paused.linkUrl)
    }

    @Test
    fun toleratesMissingAndOddValues() {
        val dashboard = parseDashboard(JSONObject("""{"services": [{"id": 1, "data": {"mem": "abc"}}]}"""))
        assertEquals(60, dashboard.pollIntervalSeconds)
        assertEquals("unknown", dashboard.services[0].status)
        assertNull(dashboard.services[0].data.num("mem"))
        assertNull(dashboard.services[0].data.num("missing"))
    }
}
