from __future__ import annotations

import asyncio

import httpx
import pytest

from app.forms import parse_service_form
from app.integrations.http_check import HttpCheck, parse_expected_status
from app.integrations.tcp_check import TcpCheck


def test_parse_expected_status():
    assert parse_expected_status("200-399, 401") == [(200, 399), (401, 401)]
    for bad in ("", "abc", "99", "500-400", "200-700"):
        with pytest.raises(ValueError):
            parse_expected_status(bad)


def test_http_check_sends_header_and_reports_status():
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-Api-Key")
        return httpx.Response(401)

    check = HttpCheck(transport=httpx.MockTransport(handler))
    config = {"url": "http://service.test", "expected_status": "200-399", "verify_tls": True,
              "timeout": 5, "header_name": "X-Api-Key"}

    result = asyncio.run(check.check(config, {"header_value": "secret-value"}))
    assert result.status == "down"
    assert result.message == "HTTP 401"
    assert seen["key"] == "secret-value"
    assert "secret-value" not in result.message

    config["expected_status"] = "200-399,401"
    assert asyncio.run(check.check(config, {"header_value": "secret-value"})).status == "up"


def test_tcp_check_up_then_refused():
    async def scenario() -> None:
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        result = await TcpCheck().check({"host": "127.0.0.1", "port": port, "timeout": 2}, {})
        assert result.status == "up"
        server.close()
        await server.wait_closed()
        with pytest.raises(OSError):
            await TcpCheck().check({"host": "127.0.0.1", "port": port, "timeout": 2}, {})

    asyncio.run(scenario())


def test_form_validation_and_secret_handling():
    form = {"name": "NAS", "url": "ftp://nope", "expected_status": "200", "timeout": "500",
            "header_name": "", "enabled": "on"}
    parsed = parse_service_form(HttpCheck, form, existing_secrets={})
    assert any("http://" in e for e in parsed.errors)
    assert any("Timeout" in e for e in parsed.errors)

    # Blank secret keeps the existing value; "clear" removes it.
    ok_form = {"name": "NAS", "url": "http://nas.local", "expected_status": "200-399", "timeout": "10"}
    kept = parse_service_form(HttpCheck, ok_form, existing_secrets={"header_value": "old"})
    assert kept.errors == [] and kept.secrets == {"header_value": "old"}
    cleared = parse_service_form(HttpCheck, {**ok_form, "clear__header_value": "on"}, {"header_value": "old"})
    assert cleared.secrets == {}
    replaced = parse_service_form(HttpCheck, {**ok_form, "header_value": "new"}, {"header_value": "old"})
    assert replaced.secrets == {"header_value": "new"}
    assert kept.config["verify_tls"] is False  # unchecked checkbox
