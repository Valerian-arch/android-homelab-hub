"""Shared helpers: a size-limited HTTP client and formatting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

INFINITE_ETA = 8_640_000  # qBittorrent's "unknown/infinite" ETA value
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class ResponseTooLarge(Exception):
    def __init__(self) -> None:
        super().__init__(f"Response larger than {MAX_RESPONSE_BYTES // (1024 * 1024)} MB. Ignored for safety.")


class _CappedStream(httpx.AsyncByteStream):
    def __init__(self, inner: Any, limit: int) -> None:
        self._inner = inner
        self._limit = limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._inner:
            total += len(chunk)
            if total > self._limit:
                raise ResponseTooLarge()
            yield chunk

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class CappedTransport(httpx.AsyncBaseTransport):
    """Wraps a transport so no response body can exceed ``limit`` bytes."""

    def __init__(self, inner: httpx.AsyncBaseTransport, limit: int = MAX_RESPONSE_BYTES) -> None:
        self._inner = inner
        self._limit = limit

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > self._limit:
            await response.aclose()
            raise ResponseTooLarge()
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_CappedStream(response.stream, self._limit),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


def make_client(
    config: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """HTTP client for talking to a monitored service.

    * Response bodies are capped at MAX_RESPONSE_BYTES.
    * ``Accept-Encoding: identity`` so the cap applies to real (uncompressed) size.
    * TLS verification and timeout come from the service's config.
    * Redirects are NOT followed unless the caller handles them explicitly.
    """
    inner = transport or httpx.AsyncHTTPTransport(verify=bool(config.get("verify_tls", True)))
    return httpx.AsyncClient(
        transport=CappedTransport(inner),
        timeout=float(config.get("timeout") or 10),
        headers={"Accept-Encoding": "identity", **(headers or {})},
        follow_redirects=False,
        **kwargs,
    )


def human_speed(bytes_per_second: float | int | None) -> str:
    value = float(bytes_per_second or 0)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024 or unit == "GB/s":
            return f"{value:.0f} {unit}" if unit in ("B/s", "KB/s") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB/s"  # pragma: no cover


def human_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0 or seconds >= INFINITE_ETA:
        return "∞"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
