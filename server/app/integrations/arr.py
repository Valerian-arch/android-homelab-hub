"""Sonarr, Radarr, and Prowlarr (the "*arr" apps).

All three share the same API style: an ``X-Api-Key`` header and JSON endpoints
under ``/api/v3`` (Sonarr, Radarr) or ``/api/v1`` (Prowlarr). Everything here is
read-only GET requests.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import httpx

from .base import CheckResult, Field, Integration
from .util import make_client

QUEUE_LIMIT = 50
UPCOMING_LIMIT = 25
HEALTH_LEVELS = ("warning", "error")  # "notice"/"ok" are ignored


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _get_json(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> Any:
    response = await client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def _health(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"level": str(h.get("type", "")).lower(), "source": h.get("source") or "", "message": h.get("message") or ""}
        for h in items or []
        if str(h.get("type", "")).lower() in HEALTH_LEVELS
    ]


def _queue_item(record: dict[str, Any], title: str) -> dict[str, Any]:
    size = record.get("size") or 0
    left = record.get("sizeleft") or 0
    progress = round(100.0 * (size - left) / size, 1) if size else 0.0
    problem = None
    if str(record.get("trackedDownloadStatus", "")).lower() in ("warning", "error"):
        problem = record.get("errorMessage")
        for status_message in record.get("statusMessages") or []:
            messages = status_message.get("messages") or []
            if messages:
                problem = messages[0]
                break
        problem = problem or "Needs attention"
    return {
        "title": title,
        "status": record.get("status") or "unknown",
        "state": record.get("trackedDownloadState") or "",
        "progress": progress,
        "size": size,
        "timeleft": record.get("timeleft") or "",
        "client": record.get("downloadClient") or "",
        "problem": problem,
    }


def _episode_label(series: str, episode: dict[str, Any]) -> str:
    season = episode.get("seasonNumber")
    number = episode.get("episodeNumber")
    label = series
    if season is not None and number is not None:
        label += f" S{int(season):02d}E{int(number):02d}"
    if episode.get("title"):
        label += f" · {episode['title']}"
    return label


class _ArrBase(Integration):
    api_version: ClassVar[str] = "v3"
    app_name: ClassVar[str] = ""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "app_name", ""):
            cls.default_name = cls.app_name

    async def collect(self, client: httpx.AsyncClient, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def summarize(self, data: dict[str, Any]) -> tuple[str, str]:
        raise NotImplementedError

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        base = str(config["url"]).rstrip("/")
        start = time.perf_counter()
        async with make_client(
            config, transport=self._transport,
            base_url=f"{base}/api/{self.api_version}",
            headers={"X-Api-Key": secrets.get("api_key", "")},
        ) as client:
            response = await client.get("/system/status")
            latency = int((time.perf_counter() - start) * 1000)
            if response.status_code == 401:
                return CheckResult("down", f"{self.app_name} rejected the API key (HTTP 401).", latency)
            if response.status_code != 200:
                return CheckResult("down", f"HTTP {response.status_code}", latency)
            info = response.json()
            actual = str(info.get("appName") or "")
            if actual and actual.lower() != self.app_name.lower():
                return CheckResult("down", f"This address is {actual}, not {self.app_name}.", latency)

            data: dict[str, Any] = {"app": self.type, "version": info.get("version") or ""}
            data.update(await self.collect(client, config))

        status, message = self.summarize(data)
        return CheckResult(status, message, latency, data=data)


def _fields(example_port: int, upcoming: bool) -> tuple[Field, ...]:
    fields = [
        Field("url", "URL", "url", required=True,
              help=f"e.g. http://192.168.1.10:{example_port} (include any URL base, e.g. /sonarr)"),
        Field("api_key", "API key", "secret", required=True,
              help="Settings → General → Security → API Key"),
    ]
    if upcoming:
        fields.append(Field("upcoming_days", "Upcoming window (days)", "int", default=7, min_value=1, max_value=60))
    fields += [
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    ]
    return tuple(fields)


class _MediaArr(_ArrBase):
    """Shared summary for Sonarr and Radarr."""

    detail_template = "details/arr.html"

    def summarize(self, data: dict[str, Any]) -> tuple[str, str]:
        parts = [f"{data['queue_total']} in queue", f"{len(data['upcoming'])} upcoming"]
        problems = sum(1 for q in data["queue"] if q["problem"])
        if problems:
            parts.append(f"{problems} need attention")
        if data["health"]:
            parts.append(f"{len(data['health'])} health warning{'s' if len(data['health']) != 1 else ''}")
        return ("degraded" if data["health"] else "up"), " · ".join(parts)


class SonarrIntegration(_MediaArr):
    type = "sonarr"
    label = "Sonarr"
    app_name = "Sonarr"
    description = "TV shows: download queue, upcoming episodes, and health warnings."
    fields = _fields(8989, upcoming=True)

    async def collect(self, client: httpx.AsyncClient, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=int(config.get("upcoming_days") or 7))
        health, queue, calendar = await asyncio.gather(
            _get_json(client, "/health"),
            _get_json(client, "/queue", {"page": 1, "pageSize": QUEUE_LIMIT,
                                         "includeSeries": "true", "includeEpisode": "true"}),
            _get_json(client, "/calendar", {"start": _iso(now), "end": _iso(end), "includeSeries": "true"}),
        )
        queue_items = []
        for record in queue.get("records") or []:
            series = (record.get("series") or {}).get("title") or record.get("title") or "?"
            queue_items.append(_queue_item(record, _episode_label(series, record.get("episode") or {})))
        upcoming = []
        for episode in sorted(calendar or [], key=lambda e: e.get("airDateUtc") or ""):
            series = (episode.get("series") or {}).get("title") or "?"
            upcoming.append({
                "title": _episode_label(series, episode),
                "date": episode.get("airDateUtc") or "",
                "kind": "Airs",
                "has_file": bool(episode.get("hasFile")),
            })
        return {
            "health": _health(health),
            "queue": queue_items,
            "queue_total": int(queue.get("totalRecords") or len(queue_items)),
            "upcoming": upcoming[:UPCOMING_LIMIT],
        }


class RadarrIntegration(_MediaArr):
    type = "radarr"
    label = "Radarr"
    app_name = "Radarr"
    description = "Movies: download queue, upcoming releases, and health warnings."
    fields = _fields(7878, upcoming=True)

    async def collect(self, client: httpx.AsyncClient, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=int(config.get("upcoming_days") or 7))
        health, queue, calendar = await asyncio.gather(
            _get_json(client, "/health"),
            _get_json(client, "/queue", {"page": 1, "pageSize": QUEUE_LIMIT, "includeMovie": "true"}),
            _get_json(client, "/calendar", {"start": _iso(now), "end": _iso(end)}),
        )
        queue_items = []
        for record in queue.get("records") or []:
            movie = record.get("movie") or {}
            title = movie.get("title") or record.get("title") or "?"
            if movie.get("year"):
                title += f" ({movie['year']})"
            queue_items.append(_queue_item(record, title))

        upcoming = []
        for movie in calendar or []:
            # A movie can have several release dates; show the first one inside the window.
            candidates = []
            for key, kind in (("inCinemas", "In cinemas"), ("digitalRelease", "Digital"), ("physicalRelease", "Physical")):
                when = _parse_dt(movie.get(key))
                if when and now - timedelta(days=1) <= when <= end:
                    candidates.append((when, kind))
            if not candidates:
                continue
            when, kind = min(candidates)
            title = movie.get("title") or "?"
            if movie.get("year"):
                title += f" ({movie['year']})"
            upcoming.append({"title": title, "date": _iso(when), "kind": kind, "has_file": bool(movie.get("hasFile"))})
        upcoming.sort(key=lambda u: u["date"])
        return {
            "health": _health(health),
            "queue": queue_items,
            "queue_total": int(queue.get("totalRecords") or len(queue_items)),
            "upcoming": upcoming[:UPCOMING_LIMIT],
        }


class ProwlarrIntegration(_ArrBase):
    type = "prowlarr"
    label = "Prowlarr"
    app_name = "Prowlarr"
    api_version = "v1"
    description = "Indexers: which are enabled or failing, plus health warnings."
    detail_template = "details/prowlarr.html"
    fields = _fields(9696, upcoming=False)

    async def collect(self, client: httpx.AsyncClient, config: dict[str, Any]) -> dict[str, Any]:
        health, indexers, statuses = await asyncio.gather(
            _get_json(client, "/health"),
            _get_json(client, "/indexer"),
            _get_json(client, "/indexerstatus"),
        )
        now = datetime.now(timezone.utc)
        failing: dict[int, str] = {}
        for status in statuses or []:
            until = _parse_dt(status.get("disabledTill"))
            if until and until > now:
                failing[status.get("indexerId")] = _iso(until)
        items = [
            {
                "name": ix.get("name") or "?",
                "enabled": bool(ix.get("enable")),
                "protocol": ix.get("protocol") or "",
                "failing": ix.get("id") in failing,
                "disabled_until": failing.get(ix.get("id"), ""),
            }
            for ix in indexers or []
        ]
        items.sort(key=lambda i: (not i["failing"], not i["enabled"], i["name"].lower()))
        return {"health": _health(health), "indexers": items}

    def summarize(self, data: dict[str, Any]) -> tuple[str, str]:
        enabled = sum(1 for i in data["indexers"] if i["enabled"])
        failing = sum(1 for i in data["indexers"] if i["failing"])
        parts = [f"{enabled} indexer{'s' if enabled != 1 else ''} enabled", f"{failing} failing"]
        if data["health"]:
            parts.append(f"{len(data['health'])} health warning{'s' if len(data['health']) != 1 else ''}")
        status = "degraded" if (failing or data["health"]) else "up"
        return status, " · ".join(parts)
