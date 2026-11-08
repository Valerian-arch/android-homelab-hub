"""Common interface every integration implements.

To add a new service type:
1. Subclass ``Integration``, set ``type``, ``label``, ``description`` and ``fields``.
2. Implement ``check()``; raise on network errors (the poller turns them into "down").
3. Register the class in ``integrations/__init__.py``.

Fields with ``kind="secret"`` are encrypted at rest and never shown again in the UI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"  # text | url | int | bool | secret
    required: bool = False
    default: Any = ""
    help: str = ""
    min_value: int | None = None
    max_value: int | None = None
    confirm: str = ""
    """For bool fields: warning the user must confirm before ticking the box."""

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


@dataclass
class CheckResult:
    status: str  # "up" | "degraded" | "down" | "unknown"
    message: str = ""
    latency_ms: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)


class Integration(ABC):
    type: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str] = ""
    fields: ClassVar[tuple[Field, ...]] = ()
    default_name: ClassVar[str] = ""
    """Pre-filled service name on the add form (editable). Empty for generic checks."""
    detail_template: ClassVar[str | None] = None
    """Optional Jinja template (under templates/) that renders ``CheckResult.data``."""

    @classmethod
    def config_fields(cls) -> tuple[Field, ...]:
        return tuple(f for f in cls.fields if not f.secret)

    @classmethod
    def secret_fields(cls) -> tuple[Field, ...]:
        return tuple(f for f in cls.fields if f.secret)

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> list[str]:
        """Extra validation after per-field parsing. Return error messages."""
        return []

    @abstractmethod
    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        """Contact the service and report its status."""
