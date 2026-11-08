"""Builds the JSON the phone app shows. Never includes credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import __version__
from .integrations import REGISTRY, CheckResult
from .services import Service

STATES = ("up", "degraded", "down", "unknown", "pending", "paused")


def service_entry(service: Service, result: CheckResult | None) -> dict[str, Any]:
    if not service.enabled:
        state = "paused"
    elif result is None:
        state = "pending"
    else:
        state = result.status
    cls = REGISTRY.get(service.type)
    return {
        "id": service.id,
        "name": service.name,
        "type": service.type,
        "type_label": cls.label if cls else service.type,
        "category": service.category,
        "link_url": service.link_url,
        "status": state,
        "message": result.message if result else "",
        "latency_ms": result.latency_ms if result else None,
        "checked_at": result.checked_at.isoformat(timespec="seconds") if result else None,
        "data": result.data if result else {},
    }


def build_dashboard(services: list[Service], results: dict[int, CheckResult], poll_interval: int) -> dict[str, Any]:
    entries = [service_entry(s, results.get(s.id)) for s in services]
    summary = {state: 0 for state in STATES}
    for entry in entries:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    return {
        "hub": {
            "name": "Homelab Hub",
            "version": __version__,
            "poll_interval": poll_interval,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "summary": summary,
        # Order in which categories first appear (services are sorted by category, then name).
        "categories": list(dict.fromkeys(e["category"] for e in entries)),
        "services": entries,
    }
