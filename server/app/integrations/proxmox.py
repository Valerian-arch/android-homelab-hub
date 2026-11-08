"""Proxmox VE: node and guest (VM/LXC) status, CPU, and memory.

Uses one API call, ``GET /api2/json/cluster/resources``, which any node in a
cluster answers for the whole cluster. A token with the built-in ``PVEAuditor``
role on ``/`` is enough (read-only).
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import make_client

TOKEN_ID_RE = re.compile(r"^[^@!\s]+@[^@!\s]+![A-Za-z][A-Za-z0-9._-]*$")


def _num(value: Any) -> float | None:
    """Numbers from Proxmox, defensively: anything unparsable becomes None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _pct(used: float | None, total: float | None) -> float | None:
    if not total:
        return None
    return round(100.0 * (used or 0) / total, 1)


def _metrics(item: dict[str, Any]) -> dict[str, Any]:
    mem, maxmem = _num(item.get("mem")), _num(item.get("maxmem"))
    return {
        "status": str(item.get("status") or "unknown"),
        "cpu_pct": round((_num(item.get("cpu")) or 0.0) * 100, 1),
        "cpus": _int(item.get("maxcpu")),
        "mem_used": mem,
        "mem_total": maxmem,
        "mem_pct": _pct(mem, maxmem),
    }


def summarize_resources(resources: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    """Turn /cluster/resources into (status, message, data)."""
    nodes: list[dict[str, Any]] = []
    guests: list[dict[str, Any]] = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "node":
            nodes.append({"name": str(item.get("node") or "?"), **_metrics(item), "uptime": _int(item.get("uptime"))})
        elif kind in ("qemu", "lxc") and not item.get("template"):
            vmid = _int(item.get("vmid"))
            guests.append({
                "vmid": vmid,
                "name": str(item.get("name") or f"{kind}-{vmid}"),
                "type": "VM" if kind == "qemu" else "LXC",
                "node": str(item.get("node") or "?"),
                **_metrics(item),
            })

    nodes.sort(key=lambda n: n["name"])
    guests.sort(key=lambda g: (g["node"], g["vmid"] or 0))

    online = sum(1 for n in nodes if n["status"] == "online")
    running = sum(1 for g in guests if g["status"] == "running")
    message = f"{online}/{len(nodes)} nodes online · {running}/{len(guests)} guests running"
    # Without Sys.Audit, Proxmox still lists node names but omits CPU/memory and hides guests.
    limited = bool(nodes) and all(n["mem_total"] is None for n in nodes)
    if not nodes:
        status = "unknown"
        message = "No nodes visible. Does the token have the PVEAuditor role on '/'?"
    elif limited:
        status = "degraded"
        message += (" · Limited data: the token can't read CPU/RAM or guests. Give it the PVEAuditor role on '/'"
                    " (if Privilege Separation is on, add an API Token Permission).")
    elif online < len(nodes):
        status = "degraded"
    else:
        status = "up"
    return status, message, {"nodes": nodes, "guests": guests}


class ProxmoxIntegration(Integration):
    type = "proxmox"
    label = "Proxmox VE"
    default_name = "Proxmox"
    description = "Nodes and VMs/LXCs with CPU and RAM usage. One entry covers a whole cluster."
    detail_template = "details/proxmox.html"
    fields = (
        Field("url", "Proxmox URL", "url", required=True,
              help="Any node's web address, e.g. https://192.168.1.20:8006"),
        Field("token_id", "API token ID", required=True,
              help="Format user@realm!tokenname, e.g. homelab-hub@pve!hub"),
        Field("token_secret", "API token secret", "secret", required=True,
              help="Shown once when the token is created. Use a token with the PVEAuditor role (read-only)."),
        Field("verify_tls", "Verify TLS certificate", "bool", default=False,
              help="Proxmox uses a self-signed certificate by default. Leave unticked unless you installed a trusted one."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> list[str]:
        if not TOKEN_ID_RE.match(str(config.get("token_id", ""))):
            return ["API token ID must look like user@realm!tokenname (e.g. homelab-hub@pve!hub)."]
        return []

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        base = str(config["url"]).rstrip("/")
        headers = {"Authorization": f"PVEAPIToken={config['token_id']}={secrets.get('token_secret', '')}"}
        start = time.perf_counter()
        async with make_client({"verify_tls": False, **config}, transport=self._transport) as client:
            response = await client.get(f"{base}/api2/json/cluster/resources", headers=headers)
        latency = int((time.perf_counter() - start) * 1000)

        if response.status_code == 401:
            return CheckResult("down", "Proxmox rejected the token (HTTP 401). Check the token ID and secret.", latency)
        if response.status_code == 403:
            return CheckResult("down", "Token lacks permission (HTTP 403). Give it the PVEAuditor role on '/'.", latency)
        if response.status_code != 200:
            return CheckResult("down", f"HTTP {response.status_code}", latency)

        status, message, data = summarize_resources(response.json().get("data") or [])
        return CheckResult(status, message, latency, data=data)
