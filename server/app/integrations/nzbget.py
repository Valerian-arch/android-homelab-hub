"""NZBGet (JSON-RPC): speed, queue, recent failures."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import human_eta, human_speed, make_client

QUEUE_LIMIT = 50
FAILED_LIMIT = 5


class NzbgetError(Exception):
    pass


async def _rpc(client: httpx.AsyncClient, method: str, params: list[Any] | None = None) -> Any:
    response = await client.post("/jsonrpc", json={"version": "1.1", "method": method, "params": params or [], "id": 1})
    if response.status_code == 401:
        raise NzbgetError("NZBGet rejected the username or password (HTTP 401).")
    if response.status_code != 200:
        raise NzbgetError(f"HTTP {response.status_code}")
    payload = response.json()
    if payload.get("error"):
        error = payload["error"]
        raise NzbgetError(str(error.get("message") if isinstance(error, dict) else error))
    return payload.get("result")


class NzbgetIntegration(Integration):
    type = "nzbget"
    label = "NZBGet"
    default_name = "NZBGet"
    description = "Usenet downloads: speed, queue, and recent failures."
    detail_template = "details/downloader.html"
    fields = (
        Field("url", "URL", "url", required=True, help="e.g. http://192.168.1.10:6789"),
        Field("username", "Username",
              help="Settings → Security. Best: the RestrictedUsername account. ControlUsername also works."),
        Field("password", "Password", "secret"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        username = str(config.get("username") or "").strip()
        auth = httpx.BasicAuth(username, secrets.get("password", "")) if username else None
        start = time.perf_counter()
        async with make_client(config, transport=self._transport, base_url=str(config["url"]).rstrip("/"), auth=auth) as client:
            try:
                status, groups, history, version = await asyncio.gather(
                    _rpc(client, "status"),
                    _rpc(client, "listgroups", [0]),
                    _rpc(client, "history", [False]),
                    _rpc(client, "version"),
                )
            except NzbgetError as exc:
                return CheckResult("down", str(exc), int((time.perf_counter() - start) * 1000))
        latency = int((time.perf_counter() - start) * 1000)

        rate = float(status.get("DownloadRate") or 0)  # bytes/second
        remaining_mb = float(status.get("RemainingSizeMB") or 0)
        paused = bool(status.get("DownloadPaused"))

        queue = []
        for group in (groups or [])[:QUEUE_LIMIT]:
            size = float(group.get("FileSizeMB") or 0)
            left = float(group.get("RemainingSizeMB") or 0)
            queue.append({
                "name": group.get("NZBName") or "?",
                "status": str(group.get("Status") or "").replace("_", " ").lower(),
                "progress": round(100.0 * (size - left) / size, 1) if size else 0.0,
                "speed": "",
                "timeleft": "",
                "category": group.get("Category") or "",
            })

        failures = [h for h in history or [] if str(h.get("Status") or "").startswith("FAILURE")]
        failures.sort(key=lambda h: h.get("HistoryTime") or 0, reverse=True)
        failed = [
            {"name": h.get("Name") or h.get("NZBName") or "?", "reason": str(h.get("Status") or "").split("/", 1)[-1].lower()}
            for h in failures[:FAILED_LIMIT]
        ]

        data = {
            "version": str(version or ""),
            "download_speed": human_speed(rate),
            "upload_speed": "",
            "paused": paused,
            "timeleft": human_eta(remaining_mb * 1024 * 1024 / rate) if rate > 0 and remaining_mb else "",
            "disk_free_gb": round(float(status.get("FreeDiskSpaceMB") or 0) / 1024, 1),
            "queue_total": len(groups or []),
            "queue": queue,
            "failed_total": len(failures),
            "failed": failed,
            "failed_label": "Recently failed",
        }

        parts = ["Paused" if paused else data["download_speed"], f"{data['queue_total']} in queue"]
        if failures:
            parts.append(f"{len(failures)} failed in history")
        return CheckResult("degraded" if paused else "up", " · ".join(parts), latency, data=data)
