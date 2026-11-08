"""Generic HTTP(S) up/down check."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import make_client

MAX_REDIRECTS = 5
DEFAULT_PORTS = {"http": 80, "https": 443}

FOLLOW_REDIRECTS_WARNING = (
    "Following redirects is not recommended.\n\n"
    "A redirect can send the Hub to a different server, which could be malicious. "
    "Your auth header is never sent to a different server, but the Hub will still contact it.\n\n"
    "Only enable this for a service you trust. Continue?"
)


def parse_expected_status(spec: str) -> list[tuple[int, int]]:
    """Parse "200-399,401" into [(200, 399), (401, 401)]."""
    ranges: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
            else:
                lo = hi = int(part)
        except ValueError:
            raise ValueError(f"Invalid status code or range: {part!r}") from None
        if not 100 <= lo <= hi <= 599:
            raise ValueError(f"Invalid status code or range: {part!r}")
        ranges.append((lo, hi))
    if not ranges:
        raise ValueError("Enter at least one expected status code.")
    return ranges


def origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port or DEFAULT_PORTS.get(url.scheme)


class HttpCheck(Integration):
    type = "http"
    label = "HTTP(S) check"
    description = "Up if the URL answers with an expected status code. Works for almost any web app."
    fields = (
        Field("url", "URL", "url", required=True, help="Address the Hub checks, e.g. http://192.168.1.10:8096"),
        Field("expected_status", "Expected status codes", default="200-399",
              help="Comma-separated codes or ranges, e.g. 200-399,401. Redirects (3xx) count as up by default."),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Turn off only for self-signed certificates."),
        Field("follow_redirects", "Follow redirects (not recommended)", "bool", default=False,
              help="Off: a redirect (3xx) is reported as-is. On: follow up to 5 redirects. "
                   "The auth header is only ever sent to the server in the URL above.",
              confirm=FOLLOW_REDIRECTS_WARNING),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
        Field("header_name", "Auth header name (optional)", help="e.g. X-Api-Key"),
        Field("header_value", "Auth header value (optional)", "secret"),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # injectable for tests

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> list[str]:
        try:
            parse_expected_status(str(config.get("expected_status") or "200-399"))
        except ValueError as exc:
            return [str(exc)]
        return []

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        ranges = parse_expected_status(str(config.get("expected_status") or "200-399"))
        auth_headers: dict[str, str] = {}
        header_name = str(config.get("header_name") or "").strip()
        header_value = secrets.get("header_value")
        if header_name and header_value:
            auth_headers[header_name] = header_value

        url = httpx.URL(str(config["url"]))
        home = origin(url)
        follow = bool(config.get("follow_redirects", False))
        redirected_away = False

        start = time.perf_counter()
        async with make_client(config, transport=self._transport) as client:
            for hop in range(MAX_REDIRECTS + 1):
                # The auth header only ever goes to the server the user entered.
                same_server = origin(url) == home
                redirected_away = redirected_away or not same_server
                response = await client.get(url, headers=auth_headers if same_server else {})
                if follow and response.is_redirect and hop < MAX_REDIRECTS:
                    url = response.url.join(response.headers["location"])
                    continue
                break
        latency = int((time.perf_counter() - start) * 1000)

        ok = any(lo <= response.status_code <= hi for lo, hi in ranges)
        message = f"HTTP {response.status_code}"
        if response.is_redirect and not follow:
            message += " (redirect not followed)"
        elif redirected_away:
            message += " (after redirect to another server)"
        return CheckResult("up" if ok else "down", message, latency)
