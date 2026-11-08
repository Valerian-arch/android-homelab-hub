"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    """Holds hub.db and secret.key. Mount this as a persistent volume."""
    poll_interval: int
    """Seconds between status checks of all services."""
    secure_cookies: bool
    """Set true when the Hub is served over HTTPS."""
    session_hours: int
    """How long an admin login lasts."""
    initial_admin_password: str | None = None
    """First-run admin password. If unset, a random one is generated and printed to the log."""


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("HUB_DATA_DIR", "./data")).resolve(),
        poll_interval=max(10, int(os.environ.get("HUB_POLL_INTERVAL", "60"))),
        secure_cookies=_bool_env("HUB_SECURE_COOKIES", False),
        session_hours=max(1, int(os.environ.get("HUB_SESSION_HOURS", "12"))),
        initial_admin_password=os.environ.get("HUB_INITIAL_ADMIN_PASSWORD") or None,
    )
