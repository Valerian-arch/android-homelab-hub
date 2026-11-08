from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.integrations import CheckResult
from app.integrations.arr import ProwlarrIntegration, RadarrIntegration, SonarrIntegration

NOW = datetime.now(timezone.utc)


def iso(days: float) -> str:
    return (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


SONARR = {
    "/api/v3/system/status": {"appName": "Sonarr", "version": "4.0.0"},
    "/api/v3/health": [
        {"source": "IndexerCheck", "type": "warning", "message": "Indexers unavailable due to failures"},
        {"source": "UpdateCheck", "type": "notice", "message": "ignored"},
    ],
    "/api/v3/queue": {
        "totalRecords": 2,
        "records": [
            {"size": 1000, "sizeleft": 250, "status": "downloading", "trackedDownloadStatus": "ok",
             "trackedDownloadState": "downloading", "timeleft": "00:05:00",
             "series": {"title": "Show A"}, "episode": {"seasonNumber": 1, "episodeNumber": 2, "title": "Pilot 2"}},
            {"size": 500, "sizeleft": 0, "status": "completed", "trackedDownloadStatus": "warning",
             "trackedDownloadState": "importPending",
             "statusMessages": [{"title": "x", "messages": ["No files found are eligible for import"]}],
             "series": {"title": "Show B"}, "episode": {"seasonNumber": 3, "episodeNumber": 10}},
        ],
    },
    "/api/v3/calendar": [
        {"seriesId": 2, "seasonNumber": 2, "episodeNumber": 1, "title": "Later", "airDateUtc": iso(3),
         "hasFile": False, "series": {"title": "Show C"}},
        {"seriesId": 1, "seasonNumber": 1, "episodeNumber": 3, "title": "Sooner", "airDateUtc": iso(1),
         "hasFile": True, "series": {"title": "Show A"}},
    ],
}

RADARR = {
    "/api/v3/system/status": {"appName": "Radarr", "version": "5.0.0"},
    "/api/v3/health": [],
    "/api/v3/queue": {"totalRecords": 0, "records": []},
    "/api/v3/calendar": [
        {"title": "Film One", "year": 2026, "digitalRelease": iso(2), "inCinemas": iso(-90), "hasFile": False},
        {"title": "Film Two", "year": 2026, "physicalRelease": iso(5), "hasFile": False},
        {"title": "Out of window", "year": 2025, "inCinemas": iso(-200)},
    ],
}

PROWLARR = {
    "/api/v1/system/status": {"appName": "Prowlarr", "version": "1.0.0"},
    "/api/v1/health": [],
    "/api/v1/indexer": [
        {"id": 1, "name": "Good", "enable": True, "protocol": "usenet"},
        {"id": 2, "name": "Broken", "enable": True, "protocol": "torrent"},
        {"id": 3, "name": "Off", "enable": False, "protocol": "torrent"},
    ],
    "/api/v1/indexerstatus": [
        {"indexerId": 2, "disabledTill": iso(0.1), "mostRecentFailure": iso(-0.1)},
        {"indexerId": 1, "disabledTill": iso(-1)},  # expired: not failing anymore
    ],
}


def fake(routes: dict, seen: dict | None = None, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.setdefault("keys", set()).add(request.headers.get("X-Api-Key"))
            seen.setdefault("paths", []).append(request.url.path)
        if status_code != 200:
            return httpx.Response(status_code)
        if request.url.path not in routes:
            return httpx.Response(404)
        return httpx.Response(200, json=routes[request.url.path])
    return httpx.MockTransport(handler)


CONFIG = {"url": "http://arr.test/", "upcoming_days": 7, "verify_tls": True, "timeout": 5}


def run(integration, secrets=None) -> CheckResult:
    return asyncio.run(integration.check(CONFIG, secrets or {"api_key": "k123"}))


def test_sonarr_queue_upcoming_health():
    seen: dict = {}
    result = run(SonarrIntegration(transport=fake(SONARR, seen)))
    assert seen["keys"] == {"k123"}
    assert "/api/v3/queue" in seen["paths"]
    assert result.status == "degraded"  # one warning-level health item
    assert result.message == "2 in queue · 2 upcoming · 1 need attention · 1 health warning"
    queue = result.data["queue"]
    assert queue[0]["title"] == "Show A S01E02 · Pilot 2"
    assert queue[0]["progress"] == 75.0
    assert queue[1]["problem"] == "No files found are eligible for import"
    assert [u["title"] for u in result.data["upcoming"]] == ["Show A S01E03 · Sooner", "Show C S02E01 · Later"]
    assert [h["message"] for h in result.data["health"]] == ["Indexers unavailable due to failures"]


def test_radarr_upcoming_picks_date_in_window():
    result = run(RadarrIntegration(transport=fake(RADARR)))
    assert result.status == "up"
    assert result.message == "0 in queue · 2 upcoming"
    titles = [(u["title"], u["kind"]) for u in result.data["upcoming"]]
    assert titles == [("Film One (2026)", "Digital"), ("Film Two (2026)", "Physical")]


def test_prowlarr_failing_indexers():
    result = run(ProwlarrIntegration(transport=fake(PROWLARR)))
    assert result.status == "degraded"
    assert result.message == "2 indexers enabled · 1 failing"
    assert result.data["indexers"][0]["name"] == "Broken"
    assert result.data["indexers"][0]["failing"] is True
    assert {i["name"]: i["failing"] for i in result.data["indexers"]}["Good"] is False


def test_bad_api_key():
    result = run(SonarrIntegration(transport=fake(SONARR, status_code=401)), {"api_key": "wrong"})
    assert result.status == "down"
    assert "API key" in result.message
    assert "wrong" not in result.message


def test_wrong_app_at_address():
    result = run(SonarrIntegration(transport=fake(RADARR)))
    assert result.status == "down"
    assert result.message == "This address is Radarr, not Sonarr."


def test_admin_page_renders_arr_details(client, app, csrf):
    client.post(
        "/admin/services/new?type=sonarr",
        data={"csrf_token": csrf, "name": "Sonarr", "url": "http://arr.invalid:8989",
              "api_key": "k123", "upcoming_days": "7", "timeout": "5"},
    )
    service = app.state.store.list()[0]
    app.state.poller.results[service.id] = run(SonarrIntegration(transport=fake(SONARR)))
    page = client.get("/admin").text
    assert "Queue, upcoming, and health" in page
    assert "Show A S01E02" in page
    assert "No files found are eligible for import" in page
    assert "k123" not in page
