"""qui (autobrr/qui): a web UI that manages one or more qBittorrent instances.

One Hub entry covers every instance qui knows about. Uses qui's documented API:
``X-API-Key`` header, ``GET /api/instances`` and ``GET /api/instances/{id}/transfer-info``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import human_speed, make_client


class QuiIntegration(Integration):
    type = "qui"
    label = "qui"
    default_name = "qui"
    description = "qui (qBittorrent web UI): connection status and speeds for every qBittorrent instance it manages."
    detail_template = "details/qui.html"
    fields = (
        Field("url", "URL", "url", required=True, help="e.g. http://192.168.1.10:7476 (include any base path)"),
        Field("api_key", "API key", "secret", required=True, help="qui → Settings → API Keys → create a key"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        start = time.perf_counter()
        async with make_client(
            config, transport=self._transport, base_url=str(config["url"]).rstrip("/"),
            headers={"X-API-Key": secrets.get("api_key", "")},
        ) as client:
            response = await client.get("/api/instances")
            if response.status_code in (401, 403):
                return CheckResult("down", f"qui rejected the API key (HTTP {response.status_code}).",
                                   int((time.perf_counter() - start) * 1000))
            if response.status_code != 200:
                return CheckResult("down", f"HTTP {response.status_code}", int((time.perf_counter() - start) * 1000))
            raw = [i for i in response.json() or [] if i.get("isActive", True)]

            async def transfer(instance: dict[str, Any]) -> dict[str, Any]:
                if not instance.get("connected"):
                    return {}
                resp = await client.get(f"/api/instances/{instance.get('id')}/transfer-info")
                return resp.json() if resp.status_code == 200 else {}

            transfers = await asyncio.gather(*(transfer(i) for i in raw))
        latency = int((time.perf_counter() - start) * 1000)

        instances = []
        total_dl = total_ul = 0
        for inst, info in zip(raw, transfers, strict=True):
            dl, ul = int(info.get("dl_info_speed") or 0), int(info.get("up_info_speed") or 0)
            total_dl += dl
            total_ul += ul
            instances.append({
                "name": inst.get("name") or f"Instance {inst.get('id')}",
                "connected": bool(inst.get("connected")),
                "error": inst.get("connectionError") or "",
                "download_speed": human_speed(dl),
                "upload_speed": human_speed(ul),
                "connection": info.get("connection_status") or "",
            })

        connected = sum(1 for i in instances if i["connected"])
        data = {"instances": instances, "download_speed": human_speed(total_dl), "upload_speed": human_speed(total_ul)}
        if not instances:
            return CheckResult("unknown", "No active qBittorrent instances in qui.", latency, data=data)
        message = (f"{connected}/{len(instances)} instance{'s' if len(instances) != 1 else ''} connected"
                   f" · ↓ {data['download_speed']} ↑ {data['upload_speed']}")
        if connected == len(instances):
            status = "up"
        elif connected:
            status = "degraded"
        else:
            status = "down"
        return CheckResult(status, message, latency, data=data)
