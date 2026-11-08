"""Background loop that checks every enabled service and caches the results."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from cryptography.fernet import InvalidToken

from .crypto import SecretBox
from .integrations import REGISTRY, CheckResult, Integration
from .services import Service, ServiceStore

log = logging.getLogger("homelab_hub.poller")


def describe_error(exc: BaseException) -> str:
    """Short, user-facing error text. Never includes credentials."""
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "Timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused"
    if isinstance(exc, httpx.ConnectError):
        detail = str(exc)[:160]
        return f"Connection failed: {detail}" if detail else "Connection failed"
    if isinstance(exc, OSError):
        return f"Network error: {exc.strerror or exc}"[:200]
    return (str(exc) or type(exc).__name__)[:200]


class Poller:
    def __init__(self, store: ServiceStore, box: SecretBox, interval: int, concurrency: int = 20) -> None:
        self.store = store
        self.box = box
        self.interval = interval
        self.results: dict[int, CheckResult] = {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._instances: dict[str, Integration] = {}
        self._tasks: set[asyncio.Task[CheckResult]] = set()
        # IDs deleted/disabled since their check started; late results are dropped.
        self._forgotten: set[int] = set()

    def _integration(self, type_: str) -> Integration | None:
        if type_ not in self._instances:
            cls = REGISTRY.get(type_)
            if cls is None:
                return None
            self._instances[type_] = cls()
        return self._instances[type_]

    async def _run_check(self, service: Service) -> CheckResult:
        integration = self._integration(service.type)
        if integration is None:
            return CheckResult("unknown", f"Unknown service type '{service.type}'")
        try:
            secrets = self.box.decrypt_json(service.secrets_enc)
        except InvalidToken:
            return CheckResult("unknown", "Saved credentials can't be decrypted (secret key changed?). Re-enter them.")
        try:
            return await integration.check(service.config, secrets)
        except Exception as exc:  # noqa: BLE001 - any failure means "down"
            return CheckResult("down", describe_error(exc))

    async def check_and_store(self, service: Service) -> CheckResult:
        async with self._semaphore:
            result = await self._run_check(service)
        if service.id not in self._forgotten:
            self.results[service.id] = result
        return result

    async def check_now(self, service: Service) -> CheckResult:
        """Check one service immediately (the admin "Test" button)."""
        self._forgotten.discard(service.id)
        return await self.check_and_store(service)

    def trigger(self, service: Service) -> None:
        """Check one service in the background (e.g. right after it is saved)."""
        self._forgotten.discard(service.id)
        task = asyncio.create_task(self.check_and_store(service))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def forget(self, service_id: int) -> None:
        self._forgotten.add(service_id)
        self.results.pop(service_id, None)

    async def poll_all(self) -> None:
        services = await asyncio.to_thread(self.store.list, True)
        live = {s.id for s in services}
        self._forgotten -= live
        for service_id in list(self.results):
            if service_id not in live:
                del self.results[service_id]
        await asyncio.gather(*(self.check_and_store(s) for s in services))

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_all()
            except Exception:  # noqa: BLE001 - keep polling no matter what
                log.exception("Poll cycle failed")
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
