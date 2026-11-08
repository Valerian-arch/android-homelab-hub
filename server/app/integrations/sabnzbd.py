"""SABnzbd: download speed, queue, recent failures, and warnings.

SABnzbd's API takes the key as a URL parameter (``apikey=``), so this module never
calls ``raise_for_status()`` (its error text includes the full URL, key and all).
The poller also scrubs saved secrets from any error message as a second safety net.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .base import CheckResult, Field, Integration
from .util import make_client

QUEUE_LIMIT = 50
FAILED_LIMIT = 5


class SabnzbdError(Exception):
    pass


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _speed_label(kbps: float) -> str:
    if kbps >= 1024:
        return f"{kbps / 1024:.1f} MB/s"
    return f"{kbps:.0f} KB/s"


def _warnings(payload: Any) -> list[str]:
    """Handle both the old (list of strings) and new (list of dicts) formats."""
    items = payload.get("warnings", []) if isinstance(payload, dict) else payload or []
    texts = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("text") or ""
        else:
            text = str(item)
        if text:
            texts.append(text)
    return texts


class SabnzbdIntegration(Integration):
    type = "sabnzbd"
    label = "SABnzbd"
    default_name = "SABnzbd"
    description = "Usenet downloads: speed, queue, recent failures, and warnings."
    detail_template = "details/sabnzbd.html"
    fields = (
        Field("url", "URL", "url", required=True,
              help="e.g. http://192.168.1.10:8080 (include any URL base, e.g. /sabnzbd)"),
        Field("api_key", "API key", "secret", required=True,
              help="Config → General → Security → API Key (the full key, not the NZB key)"),
        Field("verify_tls", "Verify TLS certificate", "bool", default=True,
              help="Only matters for https:// addresses."),
        Field("timeout", "Timeout (seconds)", "int", default=10, min_value=1, max_value=120),
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def _call(self, client: httpx.AsyncClient, api_key: str, mode: str, **params: Any) -> Any:
        response = await client.get("/api", params={"mode": mode, "output": "json", "apikey": api_key, **params})
        if response.status_code != 200:
            raise SabnzbdError(f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            # Older versions answer some errors in plain text. (The poller redacts, then shortens.)
            raise SabnzbdError(response.text.strip() or "Unexpected response") from None
        if isinstance(payload, dict) and payload.get("status") is False:
            raise SabnzbdError(str(payload.get("error") or "API error"))
        return payload

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        api_key = secrets.get("api_key", "")
        start = time.perf_counter()
        async with make_client(config, transport=self._transport, base_url=str(config["url"]).rstrip("/")) as client:
            try:
                queue_payload, history_payload, warnings_payload = await asyncio.gather(
                    self._call(client, api_key, "queue", limit=QUEUE_LIMIT),
                    self._call(client, api_key, "history", limit=FAILED_LIMIT, failed_only=1),
                    self._call(client, api_key, "warnings"),
                )
            except SabnzbdError as exc:
                latency = int((time.perf_counter() - start) * 1000)
                text = str(exc)
                if "key" in text.lower():
                    text = "SABnzbd rejected the API key. Use the full API key, not the NZB key."
                return CheckResult("down", text, latency)
        latency = int((time.perf_counter() - start) * 1000)

        queue = queue_payload.get("queue") or {}
        history = history_payload.get("history") or {}
        kbps = _float(queue.get("kbpersec"))
        slots = [
            {
                "name": s.get("filename") or "?",
                "status": s.get("status") or "",
                "progress": _float(s.get("percentage")),
                "size_mb": _float(s.get("mb")),
                "timeleft": s.get("timeleft") or "",
                "category": s.get("cat") or "",
            }
            for s in queue.get("slots") or []
        ]
        failed = [
            {"name": s.get("name") or "?", "reason": s.get("fail_message") or ""}
            for s in history.get("slots") or []
        ]
        warnings = _warnings(warnings_payload)
        paused = bool(queue.get("paused"))
        data = {
            "version": queue.get("version") or "",
            "paused": paused,
            "speed_kbps": kbps,
            "speed": _speed_label(kbps),
            "timeleft": queue.get("timeleft") or "",
            "queue_total": int(_float(queue.get("noofslots_total") or queue.get("noofslots") or len(slots))),
            "queue": slots,
            "failed_total": int(_float(history.get("noofslots") or len(failed))),
            "failed": failed,
            "warnings": warnings,
            "disk_free_gb": _float(queue.get("diskspace1")),
        }

        parts = ["Paused" if paused else data["speed"], f"{data['queue_total']} in queue"]
        if data["failed_total"]:
            parts.append(f"{data['failed_total']} failed")
        if warnings:
            parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
        status = "degraded" if (paused or warnings) else "up"
        return CheckResult(status, " · ".join(parts), latency, data=data)
