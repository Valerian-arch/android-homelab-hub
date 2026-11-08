"""Registry of available service integrations."""

from __future__ import annotations

from .base import CheckResult, Field, Integration
from .http_check import HttpCheck
from .proxmox import ProxmoxIntegration
from .tcp_check import TcpCheck

REGISTRY: dict[str, type[Integration]] = {
    cls.type: cls for cls in (HttpCheck, TcpCheck, ProxmoxIntegration)
}

__all__ = ["REGISTRY", "CheckResult", "Field", "Integration"]
