"""Phone API (v1): pairing and read-only dashboard. JSON only.

Auth: ``Authorization: Bearer <device token>``. Tokens come from ``POST /api/v1/pair``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import __version__
from .dashboard import build_dashboard
from .devices import DEFAULT_DEVICE_NAME, Device

router = APIRouter(prefix="/api/v1", tags=["phone"])


class PairRequest(BaseModel):
    code: str = Field(max_length=32)
    device_name: str = Field(default=DEFAULT_DEVICE_NAME, max_length=60)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def require_device(request: Request) -> Device:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("Missing device token. Pair this phone first.")
    device = request.app.state.devices.authenticate(token.strip())
    if device is None:
        raise _unauthorized("Invalid or revoked device token. Pair this phone again.")
    return device


@router.post("/pair")
def pair(request: Request, body: PairRequest) -> dict[str, Any]:
    state = request.app.state
    client_ip = request.client.host if request.client else "unknown"
    if state.pair_limiter.is_locked(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
    token = state.devices.redeem_pairing_code(body.code, body.device_name)
    if token is None:
        state.pair_limiter.record_failure(client_ip)
        raise HTTPException(status_code=400, detail="Invalid or expired pairing code. Create a new one on the Hub.")
    state.pair_limiter.reset(client_ip)
    return {"token": token, "hub": {"name": "Homelab Hub", "version": __version__}}


@router.get("/me")
def me(device: Device = Depends(require_device)) -> dict[str, Any]:
    return {"id": device.id, "name": device.name, "paired_at": device.created_at}


@router.post("/unpair")
def unpair(request: Request, device: Device = Depends(require_device)) -> dict[str, str]:
    request.app.state.devices.revoke(device.id)
    return {"status": "unpaired"}


@router.get("/dashboard")
def dashboard(request: Request, _device: Device = Depends(require_device)) -> dict[str, Any]:
    state = request.app.state
    return build_dashboard(state.store.list(), state.poller.results, state.settings.poll_interval)
