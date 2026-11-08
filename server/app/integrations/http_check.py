"""Generic HTTP(S) up/down check."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration


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


class HttpCheck(Integration):
    type = "http"
    label = "HTTP(S) check"
    description = "Up if the URL answers with an expected status code. Works for almost any web app."
    fields = (
        Field("url", "URL", "url", required=True, help="Address the Hub checks, e.g. http://192.168.1.10:8096"),
        Field("expected_status", "Expected status codes", default="200-399",
              help="Comma-separated codes or ranges, e.g. 200-399,401"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Turn off only for self-signed certificates."),
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
        headers: dict[str, str] = {}
        header_name = str(config.get("header_name") or "").strip()
        header_value = secrets.get("header_value")
        if header_name and header_value:
            headers[header_name] = header_value

        start = time.perf_counter()
        async with httpx.AsyncClient(
            verify=bool(config.get("verify_tls", True)),
            timeout=float(config.get("timeout") or 10),
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = await client.get(str(config["url"]), headers=headers)
        latency = int((time.perf_counter() - start) * 1000)

        ok = any(lo <= response.status_code <= hi for lo, hi in ranges)
        return CheckResult("up" if ok else "down", f"HTTP {response.status_code}", latency)
