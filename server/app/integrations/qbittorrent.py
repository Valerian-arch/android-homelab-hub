"""qBittorrent (WebUI API v2): speeds, active downloads, and errored torrents."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import human_eta, human_speed, make_client

QUEUE_LIMIT = 50
FAILED_LIMIT = 10


class QbittorrentIntegration(Integration):
    type = "qbittorrent"
    label = "qBittorrent"
    default_name = "qBittorrent"
    description = "Torrents: download/upload speed, active downloads, and errored torrents."
    detail_template = "details/downloader.html"
    fields = (
        Field("url", "WebUI URL", "url", required=True, help="e.g. http://192.168.1.10:8080"),
        Field("username", "Username",
              help="Leave blank only if qBittorrent bypasses login for the Hub's IP "
                   "(Options → WebUI → Bypass authentication for clients in whitelisted IP subnets)."),
        Field("password", "Password", "secret"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        base = str(config["url"]).rstrip("/")
        start = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - start) * 1000)

        async with make_client(
            config, transport=self._transport, base_url=base,
            headers={"Referer": base},  # qBittorrent's CSRF check compares Referer/Origin with the host
        ) as client:
            username = str(config.get("username") or "").strip()
            if username:
                login = await client.post(
                    "/api/v2/auth/login", data={"username": username, "password": secrets.get("password", "")}
                )
                if login.status_code == 403:
                    return CheckResult("down", "qBittorrent has temporarily banned the Hub's IP after failed logins. "
                                               "Fix the password, then wait or restart qBittorrent.", elapsed())
                if login.status_code != 200 or login.text.strip() != "Ok.":
                    return CheckResult("down", "qBittorrent rejected the username or password.", elapsed())

            info_resp = await client.get("/api/v2/transfer/info")
            if info_resp.status_code in (401, 403):
                return CheckResult("down", "Not logged in. Enter the WebUI username and password.", elapsed())
            if info_resp.status_code != 200:
                return CheckResult("down", f"HTTP {info_resp.status_code}", elapsed())

            version_resp, downloading_resp, errored_resp = await asyncio.gather(
                client.get("/api/v2/app/version"),
                client.get("/api/v2/torrents/info", params={"filter": "downloading", "sort": "dlspeed", "reverse": "true"}),
                client.get("/api/v2/torrents/info", params={"filter": "errored"}),
            )
        latency = elapsed()

        info = info_resp.json()
        downloading = downloading_resp.json() if downloading_resp.status_code == 200 else []
        errored = errored_resp.json() if errored_resp.status_code == 200 else []

        queue = [
            {
                "name": t.get("name") or "?",
                "status": t.get("state") or "",
                "progress": round(float(t.get("progress") or 0) * 100, 1),
                "speed": human_speed(t.get("dlspeed")),
                "timeleft": human_eta(t.get("eta")),
                "category": t.get("category") or "",
            }
            for t in downloading[:QUEUE_LIMIT]
        ]
        failed = [{"name": t.get("name") or "?", "reason": t.get("state") or "error"} for t in errored[:FAILED_LIMIT]]
        connection = str(info.get("connection_status") or "")
        data = {
            "version": version_resp.text.strip().lstrip("v") if version_resp.status_code == 200 else "",
            "download_speed": human_speed(info.get("dl_info_speed")),
            "upload_speed": human_speed(info.get("up_info_speed")),
            "connection": connection,
            "paused": False,
            "queue_total": len(downloading),
            "queue": queue,
            "failed_total": len(errored),
            "failed": failed,
            "failed_label": "Errored torrents",
        }

        parts = [f"↓ {data['download_speed']} ↑ {data['upload_speed']}", f"{len(downloading)} downloading"]
        if errored:
            parts.append(f"{len(errored)} errored")
        if connection == "disconnected":
            parts.append("no connection")
        elif connection == "firewalled":
            parts.append("firewalled")
        status = "degraded" if (errored or connection == "disconnected") else "up"
        return CheckResult(status, " · ".join(parts), latency, data=data)
