from __future__ import annotations

import asyncio

import httpx
from cryptography.fernet import Fernet

from app.crypto import SecretBox
from app.integrations import REGISTRY, CheckResult, Integration
from app.integrations.jellyfin import JellyfinIntegration
from app.integrations.sabnzbd import SabnzbdIntegration
from app.poller import Poller, redact
from app.services import Service

# --- SABnzbd ------------------------------------------------------------------

SAB_QUEUE = {"queue": {
    "version": "4.4.0", "paused": False, "kbpersec": "2560.0", "timeleft": "0:05:00",
    "noofslots_total": 2, "diskspace1": "512.25",
    "slots": [
        {"filename": "Album One", "status": "Downloading", "percentage": "40", "mb": "300", "timeleft": "0:03:00", "cat": "music"},
        {"filename": "Album Two", "status": "Queued", "percentage": "0", "mb": "200", "timeleft": "0:02:00", "cat": "music"},
    ],
}}
SAB_HISTORY = {"history": {"noofslots": 1, "slots": [{"name": "Bad Album", "fail_message": "Aborted, cannot be completed"}]}}
SAB_WARNINGS = {"warnings": [{"text": "Server news.example.com failed", "type": "WARNING", "time": 0}]}


def sab_transport(seen: dict | None = None, bad_key: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if seen is not None:
            seen.setdefault("modes", []).append(params.get("mode"))
            seen["apikey"] = params.get("apikey")
            seen["path"] = request.url.path
        if bad_key:
            return httpx.Response(200, json={"status": False, "error": "API Key Incorrect"})
        payload = {"queue": SAB_QUEUE, "history": SAB_HISTORY, "warnings": SAB_WARNINGS}[params["mode"]]
        return httpx.Response(200, json=payload)
    return httpx.MockTransport(handler)


SAB_CONFIG = {"url": "http://sab.test:8085/", "verify_tls": True, "timeout": 5}


def test_sabnzbd_queue_failures_warnings():
    seen: dict = {}
    result = asyncio.run(SabnzbdIntegration(transport=sab_transport(seen)).check(SAB_CONFIG, {"api_key": "sabkey123"}))
    assert seen["path"] == "/api"
    assert seen["apikey"] == "sabkey123"
    assert sorted(seen["modes"]) == ["history", "queue", "warnings"]
    assert result.status == "degraded"  # has a warning
    assert result.message == "2.5 MB/s · 2 in queue · 1 failed · 1 warning"
    assert result.data["queue"][0]["progress"] == 40.0
    assert result.data["failed"][0]["reason"] == "Aborted, cannot be completed"
    assert result.data["disk_free_gb"] == 512.25


def test_sabnzbd_bad_key_message_has_no_key():
    result = asyncio.run(SabnzbdIntegration(transport=sab_transport(bad_key=True)).check(SAB_CONFIG, {"api_key": "sabkey123"}))
    assert result.status == "down"
    assert "full API key" in result.message
    assert "sabkey123" not in result.message


def test_sabnzbd_old_warning_format():
    from app.integrations.sabnzbd import _warnings
    assert _warnings(["plain text warning"]) == ["plain text warning"]


# --- Jellyfin -------------------------------------------------------------------

JF_INFO = {"ServerName": "media", "Version": "10.11.0", "HasUpdateAvailable": True, "HasPendingRestart": False}
JF_SESSIONS = [
    {"UserName": "alice", "Client": "Android TV", "DeviceName": "Living room",
     "NowPlayingItem": {"Name": "Pilot", "SeriesName": "Show A", "ParentIndexNumber": 1, "IndexNumber": 1,
                        "Type": "Episode", "RunTimeTicks": 1000},
     "PlayState": {"PositionTicks": 250, "IsPaused": False, "PlayMethod": "Transcode"}},
    {"UserName": "bob", "Client": "Web", "DeviceName": "Firefox",
     "NowPlayingItem": {"Name": "Film", "ProductionYear": 2024, "Type": "Movie", "RunTimeTicks": 2000},
     "PlayState": {"PositionTicks": 1000, "IsPaused": True, "PlayMethod": "DirectPlay"}},
    {"UserName": "idle", "Client": "Web", "DeviceName": "Chrome"},  # connected, not playing
]
JF_COUNTS = {"MovieCount": 1234, "SeriesCount": 56, "EpisodeCount": 7890, "AlbumCount": 0, "SongCount": 0}


def jf_transport(seen: dict | None = None, status_code: int = 200) -> httpx.MockTransport:
    routes = {"/System/Info": JF_INFO, "/Sessions": JF_SESSIONS, "/Items/Counts": JF_COUNTS}

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["auth"] = request.headers.get("Authorization")
        if status_code != 200:
            return httpx.Response(status_code)
        return httpx.Response(200, json=routes[request.url.path])
    return httpx.MockTransport(handler)


JF_CONFIG = {"url": "http://jf.test:8096", "verify_tls": True, "timeout": 5}


def test_jellyfin_streams_and_counts():
    seen: dict = {}
    result = asyncio.run(JellyfinIntegration(transport=jf_transport(seen)).check(JF_CONFIG, {"api_key": "jfkey"}))
    assert seen["auth"] == 'MediaBrowser Token="jfkey"'
    assert result.status == "up"
    assert result.message == "2 streaming (1 transcoding) · 1,234 movies · 56 series · update available"
    streams = result.data["streams"]
    assert streams[0]["title"] == "Show A S01E01 · Pilot"
    assert streams[0]["progress"] == 25.0 and streams[0]["transcoding"] is True
    assert streams[1]["title"] == "Film (2024)" and streams[1]["paused"] is True


def test_jellyfin_bad_key():
    result = asyncio.run(JellyfinIntegration(transport=jf_transport(status_code=401)).check(JF_CONFIG, {"api_key": "x"}))
    assert result.status == "down" and "401" in result.message


# --- Secret scrubbing ---------------------------------------------------------------

def test_redact():
    assert redact("failed for key=abcd1234!", {"api_key": "abcd1234"}) == "failed for key=***!"
    assert redact("short ab", {"k": "ab"}) == "short ab"  # too short to scrub safely


def test_poller_scrubs_secret_from_errors(monkeypatch):
    class Leaky(Integration):
        type = "leaky"
        label = "Leaky"

        async def check(self, config, secrets):
            raise RuntimeError(f"GET http://x/api?apikey={secrets['api_key']} failed")

    monkeypatch.setitem(REGISTRY, "leaky", Leaky)
    box = SecretBox(Fernet.generate_key())
    poller = Poller(store=None, box=box, interval=60)  # store unused here
    service = Service(id=1, name="L", type="leaky", secrets_enc=box.encrypt_json({"api_key": "topsecret99"}))
    result: CheckResult = asyncio.run(poller.check_and_store(service))
    assert result.status == "down"
    assert "topsecret99" not in result.message
    assert "***" in result.message


def test_admin_page_renders_sab_and_jellyfin(client, app, csrf):
    for type_, name in (("sabnzbd", "SAB"), ("jellyfin", "JF")):
        client.post(
            f"/admin/services/new?type={type_}",
            data={"csrf_token": csrf, "name": name, "url": "http://x.invalid:1", "api_key": "k1234", "timeout": "5"},
        )
    sab, jf = sorted(app.state.store.list(), key=lambda s: s.name, reverse=True)
    app.state.poller.results[sab.id] = asyncio.run(SabnzbdIntegration(transport=sab_transport()).check(SAB_CONFIG, {"api_key": "k1234"}))
    app.state.poller.results[jf.id] = asyncio.run(JellyfinIntegration(transport=jf_transport()).check(JF_CONFIG, {"api_key": "k1234"}))
    page = client.get("/admin").text
    assert "Queue, failures, and warnings" in page and "Album One" in page and "512.2 GB free" in page
    assert "Streams and library" in page and "Show A S01E01" in page and "1,234 movies" in page
    assert "k1234" not in page
