"""Registry of available service integrations."""

from __future__ import annotations

from .base import CheckResult, Field, Integration
from .arr import ProwlarrIntegration, RadarrIntegration, SonarrIntegration
from .http_check import HttpCheck
from .jellyfin import JellyfinIntegration
from .nzbget import NzbgetIntegration
from .proxmox import ProxmoxIntegration
from .qbittorrent import QbittorrentIntegration
from .qui import QuiIntegration
from .sabnzbd import SabnzbdIntegration
from .tcp_check import TcpCheck

REGISTRY: dict[str, type[Integration]] = {
    cls.type: cls
    for cls in (
        HttpCheck, TcpCheck, ProxmoxIntegration,
        SonarrIntegration, RadarrIntegration, ProwlarrIntegration,
        SabnzbdIntegration, NzbgetIntegration, QbittorrentIntegration, QuiIntegration,
        JellyfinIntegration,
    )
}

__all__ = ["REGISTRY", "CheckResult", "Field", "Integration"]
