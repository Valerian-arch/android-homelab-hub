"""Tests for the fixes from the 2026-11 independent security review."""

from __future__ import annotations

import asyncio
import stat

import httpx
from cryptography.fernet import Fernet

from app.crypto import SecretBox
from app.forms import parse_service_form
from app.integrations import REGISTRY, CheckResult, Integration
from app.integrations.http_check import HttpCheck
from app.integrations.proxmox import summarize_resources
from app.integrations.util import MAX_RESPONSE_BYTES, ResponseTooLarge
from app.poller import MAX_MESSAGE, Poller, clean, redact
from app.services import Service

KEY = "header-secret-123"


# --- #3 HTTP check redirects --------------------------------------------------------------

def redirect_transport(seen: list, location: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("X-Api-Key")))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200)
    return httpx.MockTransport(handler)


def http_config(**extra):
    return {"url": "http://svc.test/start", "expected_status": "200-399", "verify_tls": True,
            "timeout": 5, "header_name": "X-Api-Key", **extra}


def test_redirects_not_followed_by_default():
    seen: list = []
    result = asyncio.run(HttpCheck(transport=redirect_transport(seen, "http://evil.test/steal")).check(
        http_config(), {"header_value": KEY}))
    assert len(seen) == 1  # never contacted evil.test
    assert result.status == "up" and result.message == "HTTP 302 (redirect not followed)"


def test_follow_redirect_never_forwards_header_to_other_server():
    seen: list = []
    result = asyncio.run(HttpCheck(transport=redirect_transport(seen, "http://evil.test/steal")).check(
        http_config(follow_redirects=True), {"header_value": KEY}))
    assert seen == [("http://svc.test/start", KEY), ("http://evil.test/steal", None)]
    assert result.status == "up" and "another server" in result.message


def test_follow_redirect_same_server_keeps_header():
    seen: list = []
    asyncio.run(HttpCheck(transport=redirect_transport(seen, "/home")).check(
        http_config(follow_redirects=True), {"header_value": KEY}))
    assert seen == [("http://svc.test/start", KEY), ("http://svc.test/home", KEY)]


def test_https_to_http_downgrade_drops_header():
    seen: list = []
    asyncio.run(HttpCheck(transport=redirect_transport(seen, "http://svc.test/home")).check(
        http_config(url="https://svc.test/start", follow_redirects=True), {"header_value": KEY}))
    assert seen[1] == ("http://svc.test/home", None)


def test_follow_redirects_checkbox_asks_for_confirmation(client, csrf):
    page = client.get("/admin/services/new?type=http").text
    assert 'name="follow_redirects"' in page and "data-confirm=" in page and "not recommended" in page


# --- #4 response size limits -------------------------------------------------------------

def big_transport(with_length: bool) -> httpx.MockTransport:
    body = b"x" * (MAX_RESPONSE_BYTES + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if with_length:
            return httpx.Response(200, content=body)

        async def chunks():
            for i in range(0, len(body), 65536):
                yield body[i:i + 65536]
        return httpx.Response(200, content=chunks())  # streamed, no Content-Length
    return httpx.MockTransport(handler)


def test_oversized_responses_rejected():
    for with_length in (True, False):
        check = HttpCheck(transport=big_transport(with_length))
        try:
            asyncio.run(check.check(http_config(url="http://svc.test/"), {}))
        except ResponseTooLarge:
            continue
        raise AssertionError("expected ResponseTooLarge")


def test_service_data_is_capped_and_redacted():
    data = {"name": "a" * 5000, "items": list(range(1000)), "leak": f"token={KEY}", "nested": {"k": [KEY]}}
    cleaned = clean(data, {"api_key": KEY})
    assert len(cleaned["name"]) == 500
    assert len(cleaned["items"]) == 200
    assert KEY not in str(cleaned)


# --- #8 redact before shortening -----------------------------------------------------------

def test_secret_cut_by_truncation_is_still_hidden():
    secret = "S3CRET-VALUE-0123456789"
    message = "x" * (MAX_MESSAGE - 10) + secret  # the cut would land inside the secret
    cleaned = clean(message, {"k": secret}, max_string=MAX_MESSAGE)
    for i in range(len(secret) - 5):
        assert secret[i:i + 6] not in cleaned


def test_url_encoded_secret_is_hidden():
    secret = "p@ss+word/with=chars"
    assert redact("GET /api?apikey=p%40ss%2Bword%2Fwith%3Dchars", {"k": secret}) == "GET /api?apikey=***"


def test_poller_scrubs_long_error(monkeypatch):
    secret = "abcdefghij0123456789"

    class Leaky(Integration):
        type = "leaky2"
        label = "Leaky"

        async def check(self, config, secrets):
            raise RuntimeError("y" * (MAX_MESSAGE - 5) + secrets["api_key"])

    monkeypatch.setitem(REGISTRY, "leaky2", Leaky)
    box = SecretBox(Fernet.generate_key())
    poller = Poller(store=None, box=box, interval=60)
    service = Service(id=1, name="L", type="leaky2", secrets_enc=box.encrypt_json({"api_key": secret}))
    result = asyncio.run(poller.check_and_store(service))
    assert "abcdef" not in result.message and len(result.message) <= MAX_MESSAGE


# --- #9 malformed Proxmox data ----------------------------------------------------------------

def test_proxmox_malformed_numbers_do_not_crash(client, app, csrf):
    weird = [
        {"type": "node", "node": "pve1", "status": "online", "cpu": "0.5", "mem": "123", "maxmem": "abc"},
        {"type": "qemu", "vmid": "100", "name": None, "node": "pve1", "status": "running", "mem": [], "maxmem": {}},
    ]
    status, _message, data = summarize_resources(weird)
    assert data["nodes"][0]["cpu_pct"] == 50.0
    assert data["nodes"][0]["mem_total"] is None
    assert data["guests"][0]["vmid"] == 100

    client.post("/admin/services/new?type=proxmox",
                data={"csrf_token": csrf, "name": "PVE", "url": "https://pve.invalid:8006",
                      "token_id": "a@pve!b", "token_secret": "s3cret", "timeout": "5"})
    service = app.state.store.list()[0]
    app.state.poller.results[service.id] = CheckResult(status, "x", 1, data=data)
    assert client.get("/admin").status_code == 200


# --- credentials in URLs ----------------------------------------------------------------

def test_urls_with_credentials_rejected():
    base = {"name": "X", "expected_status": "200-399", "timeout": "5"}
    in_link = parse_service_form(HttpCheck, {**base, "url": "http://h.test", "link_url": "http://u:p@h.test"}, {})
    in_url = parse_service_form(HttpCheck, {**base, "url": "http://admin:pw@h.test"}, {})
    assert any("must not contain a username or password" in e for e in in_link.errors)
    assert any("must not contain a username or password" in e for e in in_url.errors)


# --- escaping, body size, file permissions ------------------------------------------------------

def test_html_in_service_data_is_escaped(client, app, csrf):
    client.post("/admin/services/new?type=tcp",
                data={"csrf_token": csrf, "name": "<script>alert(1)</script>", "host": "h", "port": "1", "timeout": "1"})
    service = app.state.store.list()[0]
    app.state.poller.results[service.id] = CheckResult("up", "<img src=x onerror=alert(2)>", 1)
    page = client.get("/admin").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "<img src=x" not in page


def test_oversized_request_body_rejected(client):
    response = client.post("/login", content=b"password=" + b"x" * (100 * 1024),
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 413


def test_database_file_is_private(app):
    mode = stat.S_IMODE((app.state.settings.data_dir / "hub.db").stat().st_mode)
    assert mode == 0o600
