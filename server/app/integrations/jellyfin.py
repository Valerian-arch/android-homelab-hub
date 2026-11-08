"""Jellyfin: server status, active streams, and library counts."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import make_client

TICKS_PER_SECOND = 10_000_000


def _item_title(item: dict[str, Any]) -> str:
    name = item.get("Name") or "?"
    if item.get("SeriesName"):
        season, episode = item.get("ParentIndexNumber"), item.get("IndexNumber")
        code = f" S{int(season):02d}E{int(episode):02d}" if season is not None and episode is not None else ""
        return f"{item['SeriesName']}{code} · {name}"
    if item.get("ProductionYear"):
        return f"{name} ({item['ProductionYear']})"
    return name


def _streams(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    streams = []
    for session in sessions or []:
        item = session.get("NowPlayingItem")
        if not item:
            continue
        play_state = session.get("PlayState") or {}
        runtime = item.get("RunTimeTicks") or 0
        position = play_state.get("PositionTicks") or 0
        method = play_state.get("PlayMethod") or ""
        streams.append({
            "user": session.get("UserName") or "",
            "client": session.get("Client") or "",
            "device": session.get("DeviceName") or "",
            "title": _item_title(item),
            "type": item.get("Type") or "",
            "progress": round(100.0 * position / runtime, 1) if runtime else 0.0,
            "paused": bool(play_state.get("IsPaused")),
            "method": method,
            "transcoding": method.lower() == "transcode",
        })
    return streams


class JellyfinIntegration(Integration):
    type = "jellyfin"
    label = "Jellyfin"
    default_name = "Jellyfin"
    description = "Media server: who is watching what, transcoding, and library size."
    detail_template = "details/jellyfin.html"
    fields = (
        Field("url", "URL", "url", required=True, help="e.g. http://192.168.1.10:8096"),
        Field("api_key", "API key", "secret", required=True,
              help="Dashboard → API Keys → + (requires an admin account)"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        token = secrets.get("api_key", "")
        start = time.perf_counter()
        async with make_client(
            config, transport=self._transport,
            base_url=str(config["url"]).rstrip("/"),
            headers={"Authorization": f'MediaBrowser Token="{token}"'},
        ) as client:
            info_resp, sessions_resp, counts_resp = await asyncio.gather(
                client.get("/System/Info"),
                client.get("/Sessions", params={"activeWithinSeconds": 960}),
                client.get("/Items/Counts"),
            )
        latency = int((time.perf_counter() - start) * 1000)

        if info_resp.status_code == 401:
            return CheckResult("down", "Jellyfin rejected the API key (HTTP 401).", latency)
        if info_resp.status_code != 200:
            return CheckResult("down", f"HTTP {info_resp.status_code}", latency)

        info = info_resp.json()
        streams = _streams(sessions_resp.json()) if sessions_resp.status_code == 200 else []
        counts = counts_resp.json() if counts_resp.status_code == 200 else {}

        data = {
            "server": info.get("ServerName") or "",
            "version": info.get("Version") or "",
            "update_available": bool(info.get("HasUpdateAvailable")),
            "restart_pending": bool(info.get("HasPendingRestart")),
            "streams": streams,
            "counts": {
                "movies": counts.get("MovieCount", 0),
                "series": counts.get("SeriesCount", 0),
                "episodes": counts.get("EpisodeCount", 0),
                "albums": counts.get("AlbumCount", 0),
                "songs": counts.get("SongCount", 0),
            },
        }

        transcoding = sum(1 for s in streams if s["transcoding"])
        parts = [f"{len(streams)} streaming" + (f" ({transcoding} transcoding)" if transcoding else "")]
        if counts:
            parts.append(f"{data['counts']['movies']:,} movies · {data['counts']['series']:,} series")
        if data["restart_pending"]:
            parts.append("restart pending")
        elif data["update_available"]:
            parts.append("update available")
        return CheckResult("up", " · ".join(parts), latency, data=data)
