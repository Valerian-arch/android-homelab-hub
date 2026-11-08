"""Registry of available service integrations."""

from __future__ import annotations

from .base import CheckResult, Field, Integration
from .arr import ProwlarrIntegration, RadarrIntegration, SonarrIntegration
from .http_check import HttpCheck
from .jellyfin import JellyfinIntegration
from .proxmox import ProxmoxIntegration
from .sabnzbd import SabnzbdIntegration
from .tcp_check import TcpCheck

REGISTRY: dict[str, type[Integration]] = {
    cls.type: cls
    for cls in (
        HttpCheck, TcpCheck, ProxmoxIntegration,
        SonarrIntegration, RadarrIntegration, ProwlarrIntegration,
        SabnzbdIntegration, JellyfinIntegration,
    )
}

__all__ = ["REGISTRY", "CheckResult", "Field", "Integration"]
