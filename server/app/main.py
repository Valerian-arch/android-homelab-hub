"""Application factory.

Run locally:  uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .auth import AuthStore, LoginLimiter
from .bootstrap import ensure_admin
from .config import Settings, load_settings
from .crypto import SecretBox, load_or_create_key
from .db import Database
from .devices import DeviceStore
from .poller import Poller
from .routes_admin import router as admin_router
from .routes_api import router as api_router
from .services import ServiceStore

BASE_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 64 * 1024  # admin forms and phone requests are tiny


def _gib(value: object) -> str:
    try:
        return f"{float(value or 0) / 1024**3:.1f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    db = Database(settings.data_dir / "hub.db")
    db.init()
    box = SecretBox(load_or_create_key(settings.data_dir / "secret.key"))
    store = ServiceStore(db)
    poller = Poller(store, box, settings.poll_interval)
    auth = AuthStore(db, settings.session_hours)
    ensure_admin(auth, settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(poller.run_forever())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await poller.stop()

    app = FastAPI(
        title="Homelab Hub", version=__version__, lifespan=lifespan,
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.settings = settings
    app.state.db = db
    app.state.box = box
    app.state.store = store
    app.state.poller = poller
    app.state.auth = auth
    app.state.login_limiter = LoginLimiter()  # 3 attempts, 15-minute lockout
    app.state.password_check = asyncio.Semaphore(2)  # scrypt uses ~32 MiB per check
    app.state.devices = DeviceStore(db)
    app.state.pair_limiter = LoginLimiter(max_failures=10, window_seconds=600)
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    templates.env.filters["gib"] = _gib
    app.state.templates = templates

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in ("POST", "PUT", "PATCH"):
            length = request.headers.get("content-length")
            if length is None:
                if "chunked" in request.headers.get("transfer-encoding", "").lower():
                    return PlainTextResponse("Length Required", status_code=411)
            elif not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return PlainTextResponse("Request too large", status_code=413)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(admin_router)
    app.include_router(api_router)
    return app
