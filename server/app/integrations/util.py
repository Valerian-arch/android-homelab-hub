"""Small formatting helpers shared by download-client integrations."""

from __future__ import annotations

INFINITE_ETA = 8_640_000  # qBittorrent's "unknown/infinite" ETA value


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
