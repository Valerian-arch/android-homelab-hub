"""Generic TCP port check (SSH, databases, anything without a web page)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from .base import CheckResult, Field, Integration


class TcpCheck(Integration):
    type = "tcp"
    label = "TCP port check"
    description = "Up if a TCP connection to host:port succeeds. Good for SSH, databases, and devices without a web page."
    fields = (
        Field("host", "Host", required=True, help="IP address or hostname"),
        Field("port", "Port", "int", required=True, min_value=1, max_value=65535),
        Field("timeout", "Timeout (seconds)", "int", default=5, min_value=1, max_value=120),
    )

    async def check(self, config: dict[str, Any], secrets: dict[str, str]) -> CheckResult:
        host = str(config["host"])
        port = int(config["port"])
        start = time.perf_counter()
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=float(config.get("timeout") or 5)
        )
        latency = int((time.perf_counter() - start) * 1000)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return CheckResult("up", f"Port {port} open", latency)
