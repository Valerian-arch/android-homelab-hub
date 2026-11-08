from __future__ import annotations

import asyncio
import re

import httpx

from app.forms import parse_service_form
from app.integrations import CheckResult
from app.integrations.proxmox import ProxmoxIntegration, summarize_resources

GIB = 1024**3

SAMPLE = [
    {"type": "node", "node": "pve-b", "status": "online", "cpu": 0.25, "maxcpu": 8, "mem": 4 * GIB, "maxmem": 16 * GIB, "uptime": 100},
    {"type": "node", "node": "pve-a", "status": "online", "cpu": 0.051, "maxcpu": 4, "mem": 8 * GIB, "maxmem": 16 * GIB, "uptime": 200},
    {"type": "qemu", "vmid": 100, "name": "docker", "node": "pve-a", "status": "running", "cpu": 0.1, "maxcpu": 4, "mem": 2 * GIB, "maxmem": 4 * GIB},
    {"type": "lxc", "vmid": 200, "name": "dash", "node": "pve-b", "status": "stopped", "cpu": 0, "maxcpu": 2, "mem": 0, "maxmem": 2 * GIB},
    {"type": "qemu", "vmid": 9000, "name": "tmpl", "node": "pve-a", "status": "stopped", "template": 1},
    {"type": "storage", "id": "storage/pve-a/local", "node": "pve-a", "status": "available"},
]


def test_summarize_resources():
    status, message, data = summarize_resources(SAMPLE)
    assert status == "up"
    assert message == "2/2 nodes online · 1/2 guests running"
    assert [n["name"] for n in data["nodes"]] == ["pve-a", "pve-b"]
    assert data["nodes"][0]["cpu_pct"] == 5.1
    assert data["nodes"][0]["mem_pct"] == 50.0
    assert [g["vmid"] for g in data["guests"]] == [100, 200]  # template excluded
    assert data["guests"][1]["type"] == "LXC"


def test_summarize_degraded_and_empty():
    offline = [dict(SAMPLE[0], status="offline"), SAMPLE[1]]
    assert summarize_resources(offline)[0] == "degraded"
    assert summarize_resources([])[0] == "unknown"


def test_summarize_flags_missing_permissions():
    # What Proxmox returns to a token without PVEAuditor: node names only, no metrics, no guests.
    bare = [{"type": "node", "node": n, "status": "online", "id": f"node/{n}"} for n in ("pve1", "pve2")]
    status, message, data = summarize_resources(bare)
    assert status == "degraded"
    assert "PVEAuditor" in message
    assert data["guests"] == []


def _client(status_code: int, payload: dict | None = None, seen: dict | None = None) -> ProxmoxIntegration:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["auth"] = request.headers.get("Authorization")
            seen["path"] = request.url.path
        return httpx.Response(status_code, json=payload or {})
    return ProxmoxIntegration(transport=httpx.MockTransport(handler))


CONFIG = {"url": "https://pve.test:8006/", "token_id": "hub@pve!dash", "verify_tls": False, "timeout": 5}


def test_check_sends_token_and_parses():
    seen: dict = {}
    result = asyncio.run(_client(200, {"data": SAMPLE}, seen).check(CONFIG, {"token_secret": "s3cret"}))
    assert seen["auth"] == "PVEAPIToken=hub@pve!dash=s3cret"
    assert seen["path"] == "/api2/json/cluster/resources"
    assert result.status == "up"
    assert len(result.data["guests"]) == 2
    assert "s3cret" not in result.message


def test_check_auth_errors():
    assert "401" in asyncio.run(_client(401).check(CONFIG, {"token_secret": "x"})).message
    assert "PVEAuditor" in asyncio.run(_client(403).check(CONFIG, {"token_secret": "x"})).message


def test_token_id_validation():
    base = {"name": "Cluster", "url": "https://pve.test:8006", "timeout": "10", "token_secret": "x"}
    bad = parse_service_form(ProxmoxIntegration, {**base, "token_id": "root"}, {})
    assert any("user@realm!tokenname" in e for e in bad.errors)
    good = parse_service_form(ProxmoxIntegration, {**base, "token_id": "homelab-hub@pve!hub"}, {})
    assert good.errors == []
    assert good.config["verify_tls"] is False


def test_admin_page_shows_proxmox_details(client, app, csrf):
    # Saved with "Monitor automatically" off, so no real network check runs.
    client.post(
        "/admin/services/new?type=proxmox",
        data={"csrf_token": csrf, "name": "Cluster", "url": "https://pve.invalid:8006",
              "token_id": "hub@pve!dash", "token_secret": "s3cret", "timeout": "5"},
    )
    service = app.state.store.list()[0]
    status, message, data = summarize_resources(SAMPLE)
    app.state.poller.results[service.id] = CheckResult(status, message, 12, data=data)

    page = client.get("/admin").text
    assert "Nodes and guests" in page
    assert "pve-a" in page and "docker" in page
    assert re.search(r"8\.0 / 16\.0 GiB", page)
    assert "s3cret" not in page
