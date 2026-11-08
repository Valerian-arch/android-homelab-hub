from __future__ import annotations

import asyncio
import base64
import json

import httpx

from app.integrations.nzbget import NzbgetIntegration
from app.integrations.qbittorrent import QbittorrentIntegration
from app.integrations.qui import QuiIntegration
from app.integrations.util import human_eta, human_speed


def run(integration, config, secrets):
    return asyncio.run(integration.check(config, secrets))


def test_formatters():
    assert human_speed(0) == "0 B/s"
    assert human_speed(300 * 1024) == "300 KB/s"
    assert human_speed(2.5 * 1024 * 1024) == "2.5 MB/s"
    assert human_eta(300) == "5m 00s"
    assert human_eta(3 * 3600 + 120) == "3h 02m"
    assert human_eta(8_640_000) == "∞"


# --- qBittorrent --------------------------------------------------------------

QB_CONFIG = {"url": "http://qb.test:8080", "username": "admin", "verify_tls": True, "timeout": 5}


def qb_transport(seen: dict, *, login_ok: bool = True, banned: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.setdefault("paths", []).append(path)
        if path == "/api/v2/auth/login":
            seen["login_body"] = request.content.decode()
            seen["referer"] = request.headers.get("Referer")
            if banned:
                return httpx.Response(403, text="Your IP address has been banned")
            if not login_ok:
                return httpx.Response(200, text="Fails.")
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=abc; HttpOnly; path=/"})
        if request.headers.get("cookie") != "SID=abc":
            return httpx.Response(403, text="Forbidden")
        if path == "/api/v2/transfer/info":
            return httpx.Response(200, json={"dl_info_speed": 2621440, "up_info_speed": 307200, "connection_status": "connected"})
        if path == "/api/v2/app/version":
            return httpx.Response(200, text="v5.1.2")
        if path == "/api/v2/torrents/info":
            if request.url.params.get("filter") == "downloading":
                return httpx.Response(200, json=[{"name": "linux.iso", "state": "downloading", "progress": 0.5,
                                                  "dlspeed": 1048576, "eta": 300, "category": "tv"}])
            return httpx.Response(200, json=[{"name": "broken.torrent", "state": "missingFiles"}])
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_qbittorrent_logs_in_and_reports():
    seen: dict = {}
    result = run(QbittorrentIntegration(transport=qb_transport(seen)), QB_CONFIG, {"password": "pw"})
    assert seen["paths"][0] == "/api/v2/auth/login"
    assert "username=admin" in seen["login_body"] and "password=pw" in seen["login_body"]
    assert seen["referer"] == "http://qb.test:8080"
    assert result.status == "degraded"  # one errored torrent
    assert result.message == "↓ 2.5 MB/s ↑ 300 KB/s · 1 downloading · 1 errored"
    assert result.data["version"] == "5.1.2"
    assert result.data["queue"][0] == {"name": "linux.iso", "status": "downloading", "progress": 50.0,
                                        "speed": "1.0 MB/s", "timeleft": "5m 00s", "category": "tv"}
    assert result.data["failed"][0]["reason"] == "missingFiles"


def test_qbittorrent_bad_login_and_ban():
    bad = run(QbittorrentIntegration(transport=qb_transport({}, login_ok=False)), QB_CONFIG, {"password": "x"})
    assert bad.status == "down" and "rejected" in bad.message
    banned = run(QbittorrentIntegration(transport=qb_transport({}, banned=True)), QB_CONFIG, {"password": "x"})
    assert banned.status == "down" and "banned" in banned.message


def test_qbittorrent_without_credentials_needs_login():
    result = run(QbittorrentIntegration(transport=qb_transport({})), {**QB_CONFIG, "username": ""}, {})
    assert result.status == "down" and "Not logged in" in result.message


# --- NZBGet -------------------------------------------------------------------

NZB_RESULTS = {
    "status": {"DownloadRate": 5 * 1024 * 1024, "RemainingSizeMB": 600, "DownloadPaused": False, "FreeDiskSpaceMB": 204800},
    "listgroups": [
        {"NZBName": "Show.S01E01", "Status": "DOWNLOADING", "FileSizeMB": 1000, "RemainingSizeMB": 400, "Category": "tv"},
        {"NZBName": "Movie.2024", "Status": "QUEUED", "FileSizeMB": 200, "RemainingSizeMB": 200, "Category": "movies"},
    ],
    "history": [
        {"Name": "Old.OK", "Status": "SUCCESS/ALL", "HistoryTime": 100},
        {"Name": "Old.Fail", "Status": "FAILURE/PAR", "HistoryTime": 200},
        {"Name": "New.Fail", "Status": "FAILURE/UNPACK", "HistoryTime": 300},
    ],
    "version": "24.3",
}


def nzb_transport(seen: dict, *, status_code: int = 200, paused: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        if status_code != 200:
            return httpx.Response(status_code)
        method = json.loads(request.content)["method"]
        result = NZB_RESULTS[method]
        if method == "status" and paused:
            result = {**result, "DownloadPaused": True}
        return httpx.Response(200, json={"version": "1.1", "result": result})
    return httpx.MockTransport(handler)


NZB_CONFIG = {"url": "http://nzb.test:6789", "username": "viewer", "verify_tls": True, "timeout": 5}


def test_nzbget_queue_and_failures():
    seen: dict = {}
    result = run(NzbgetIntegration(transport=nzb_transport(seen)), NZB_CONFIG, {"password": "pw"})
    assert seen["path"] == "/jsonrpc"
    assert seen["auth"] == "Basic " + base64.b64encode(b"viewer:pw").decode()
    assert result.status == "up"
    assert result.message == "5.0 MB/s · 2 in queue · 2 failed in history"
    assert result.data["queue"][0]["progress"] == 60.0
    assert result.data["queue"][0]["status"] == "downloading"
    assert [f["name"] for f in result.data["failed"]] == ["New.Fail", "Old.Fail"]
    assert result.data["failed"][0]["reason"] == "unpack"
    assert result.data["timeleft"] == "2m 00s"  # 600 MB at 5 MB/s
    assert result.data["disk_free_gb"] == 200.0


def test_nzbget_paused_and_bad_auth():
    paused = run(NzbgetIntegration(transport=nzb_transport({}, paused=True)), NZB_CONFIG, {"password": "pw"})
    assert paused.status == "degraded" and paused.message.startswith("Paused")
    denied = run(NzbgetIntegration(transport=nzb_transport({}, status_code=401)), NZB_CONFIG, {"password": "bad"})
    assert denied.status == "down" and "401" in denied.message


# --- qui ----------------------------------------------------------------------

def qui_transport(seen: dict, instances: list, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-API-Key")
        if status_code != 200:
            return httpx.Response(status_code)
        if request.url.path == "/api/instances":
            return httpx.Response(200, json=instances)
        if request.url.path == "/api/instances/1/transfer-info":
            return httpx.Response(200, json={"dl_info_speed": 1048576, "up_info_speed": 2048, "connection_status": "firewalled"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


QUI_CONFIG = {"url": "http://qui.test:7476", "verify_tls": True, "timeout": 5}


def test_qui_instances():
    instances = [
        {"id": 1, "name": "Main", "connected": True, "isActive": True},
        {"id": 2, "name": "Seedbox", "connected": False, "isActive": True, "connectionError": "dial tcp: timeout"},
        {"id": 3, "name": "Old", "connected": False, "isActive": False},  # inactive: ignored
    ]
    seen: dict = {}
    result = run(QuiIntegration(transport=qui_transport(seen, instances)), QUI_CONFIG, {"api_key": "quikey"})
    assert seen["key"] == "quikey"
    assert result.status == "degraded"
    assert result.message == "1/2 instances connected · ↓ 1.0 MB/s ↑ 2 KB/s"
    main, seedbox = result.data["instances"]
    assert main["connection"] == "firewalled"
    assert seedbox["error"] == "dial tcp: timeout"


def test_qui_bad_key_and_empty():
    bad = run(QuiIntegration(transport=qui_transport({}, [], status_code=401)), QUI_CONFIG, {"api_key": "x"})
    assert bad.status == "down" and "API key" in bad.message
    empty = run(QuiIntegration(transport=qui_transport({}, [])), QUI_CONFIG, {"api_key": "x"})
    assert empty.status == "unknown"


def test_admin_page_renders_downloaders(client, app, csrf):
    from app.integrations import CheckResult  # noqa: F401

    for type_, extra in (("qbittorrent", {"username": "admin", "password": "pw1234"}),
                         ("nzbget", {"username": "viewer", "password": "pw1234"}),
                         ("qui", {"api_key": "pw1234"})):
        client.post(f"/admin/services/new?type={type_}",
                    data={"csrf_token": csrf, "name": type_, "url": "http://x.invalid:1", "timeout": "5", **extra})
    by_type = {s.type: s for s in app.state.store.list()}
    poller = app.state.poller
    poller.results[by_type["qbittorrent"].id] = run(QbittorrentIntegration(transport=qb_transport({})), QB_CONFIG, {"password": "pw"})
    poller.results[by_type["nzbget"].id] = run(NzbgetIntegration(transport=nzb_transport({})), NZB_CONFIG, {"password": "pw"})
    poller.results[by_type["qui"].id] = run(
        QuiIntegration(transport=qui_transport({}, [{"id": 1, "name": "Main", "connected": True}])), QUI_CONFIG, {"api_key": "k"})
    page = client.get("/admin").text
    assert "linux.iso" in page and "broken.torrent" in page
    assert "Show.S01E01" in page and "New.Fail" in page
    assert "qBittorrent instances" in page and "Main" in page
    assert "pw1234" not in page
