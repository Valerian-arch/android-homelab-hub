"""Admin web UI: first-run setup, login, and service management."""

from __future__ import annotations

import asyncio
import hmac
from typing import Any
from urllib.parse import urlencode, urlsplit

import segno
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from starlette.datastructures import FormData

from .auth import SESSION_COOKIE, Session, validate_new_password
from .crypto import hash_password, verify_password
from .devices import PAIRING_MINUTES
from .forms import default_config, is_http_url, parse_service_form
from .integrations import REGISTRY, Integration
from .services import Service

router = APIRouter()

MESSAGES = {
    "created": "Service added.",
    "updated": "Service saved.",
    "deleted": "Service deleted.",
    "tested": "Check finished. See the result below.",
}


# --- helpers -----------------------------------------------------------------

def render(request: Request, template: str, status_code: int = 200, **context: Any) -> Response:
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


def render_form(request: Request, status_code: int = 200, **context: Any) -> Response:
    """Render the add/edit service form with the existing categories for the dropdown."""
    return render(
        request, "service_form.html", status_code=status_code,
        categories=request.app.state.store.categories(), **context,
    )


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def current_session(request: Request) -> Session | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return request.app.state.auth.get_session(token)


def require_session(request: Request) -> Session:
    session = current_session(request)
    if session is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return session


async def csrf_form(request: Request, session: Session) -> FormData:
    form = await request.form()
    token = form.get("csrf_token")
    if not isinstance(token, str) or not hmac.compare_digest(token, session.csrf_token):
        raise HTTPException(status_code=400, detail="Invalid or missing CSRF token. Reload the page and try again.")
    return form


def get_integration_or_404(type_: str | None) -> type[Integration]:
    cls = REGISTRY.get(type_ or "")
    if cls is None:
        raise HTTPException(status_code=404, detail="Unknown service type")
    return cls


def get_service_or_404(request: Request, service_id: int) -> Service:
    service = request.app.state.store.get(service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


def existing_secrets(request: Request, service: Service) -> tuple[dict[str, str], str | None]:
    try:
        return request.app.state.box.decrypt_json(service.secrets_enc), None
    except InvalidToken:
        return {}, ("Saved credentials for this service could not be decrypted "
                    "(was the secret key replaced?). Re-enter them and save.")


def group_services(services: list[Service]) -> list[tuple[str, list[Service]]]:
    groups: dict[str, list[Service]] = {}
    for service in services:
        groups.setdefault(service.category or "Uncategorized", []).append(service)
    return list(groups.items())


# --- public ------------------------------------------------------------------

@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def root() -> RedirectResponse:
    return redirect("/admin")


@router.get("/setup")
def setup_page(request: Request) -> Response:
    if request.app.state.auth.admin_exists():
        return redirect("/login")
    return render(request, "setup.html", error=None)


@router.post("/setup")
async def setup_submit(request: Request) -> Response:
    auth = request.app.state.auth
    if auth.admin_exists():
        return redirect("/login")
    form = await request.form()
    password = str(form.get("password") or "")
    error = validate_new_password(password, str(form.get("confirm") or ""))
    if error:
        return render(request, "setup.html", status_code=400, error=error)
    password_hash = await asyncio.to_thread(hash_password, password)
    auth.create_admin(password_hash)
    return redirect("/login?setup=1")


@router.get("/login")
def login_page(request: Request) -> Response:
    if not request.app.state.auth.admin_exists():
        return redirect("/setup")
    if current_session(request):
        return redirect("/admin")
    return render(request, "login.html", error=None, setup_done=request.query_params.get("setup") == "1")


@router.post("/login")
async def login_submit(request: Request) -> Response:
    state = request.app.state
    client_ip = request.client.host if request.client else "unknown"
    if state.login_limiter.is_locked(client_ip):
        return render(request, "login.html", status_code=429, setup_done=False,
                      error="Too many failed attempts. Wait a few minutes and try again.")
    form = await request.form()
    password = str(form.get("password") or "")
    stored = state.auth.get_admin_hash()
    ok = stored is not None and await asyncio.to_thread(verify_password, password, stored)
    if not ok:
        state.login_limiter.record_failure(client_ip)
        return render(request, "login.html", status_code=401, setup_done=False, error="Wrong password.")
    state.login_limiter.reset(client_ip)
    token = state.auth.create_session()
    response = redirect("/admin")
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=state.settings.session_hours * 3600,
        httponly=True, samesite="strict", secure=state.settings.secure_cookies, path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    request.app.state.auth.delete_session(request.cookies[SESSION_COOKIE])
    response = redirect("/login")
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# --- services ------------------------------------------------------------------

@router.get("/admin")
def admin_home(request: Request, session: Session = Depends(require_session)) -> Response:
    services = request.app.state.store.list()
    return render(
        request, "services.html",
        session=session,
        groups=group_services(services),
        results=request.app.state.poller.results,
        labels={t: cls.label for t, cls in REGISTRY.items()},
        detail_templates={t: cls.detail_template for t, cls in REGISTRY.items() if cls.detail_template},
        message=MESSAGES.get(request.query_params.get("msg", "")),
    )


@router.get("/admin/services/new")
def new_service(
    request: Request,
    type_: str | None = Query(None, alias="type"),
    session: Session = Depends(require_session),
) -> Response:
    if not type_:
        return render(request, "choose_type.html", session=session, integrations=list(REGISTRY.values()))
    cls = get_integration_or_404(type_)
    return render_form(
        request,
        session=session, cls=cls, service=None,
        action=f"/admin/services/new?type={cls.type}",
        values=default_config(cls),
        common={"name": cls.default_name, "category": "", "link_url": "", "enabled": True},
        saved_secrets=set(), errors=[],
    )


@router.post("/admin/services/new")
async def create_service(
    request: Request,
    type_: str = Query(..., alias="type"),
    session: Session = Depends(require_session),
) -> Response:
    cls = get_integration_or_404(type_)
    form = await csrf_form(request, session)
    parsed = parse_service_form(cls, form, existing_secrets={})
    if parsed.errors:
        return render_form(
            request, status_code=400,
            session=session, cls=cls, service=None,
            action=f"/admin/services/new?type={cls.type}",
            values=parsed.config, common=parsed.common, saved_secrets=set(), errors=parsed.errors,
        )
    state = request.app.state
    new_id = state.store.create(
        type=cls.type, config=parsed.config, secrets_enc=state.box.encrypt_json(parsed.secrets),
        **parsed.common,
    )
    service = state.store.get(new_id)
    if service and service.enabled:
        state.poller.trigger(service)
    return redirect("/admin?msg=created")


@router.get("/admin/services/{service_id}/edit")
def edit_service(request: Request, service_id: int, session: Session = Depends(require_session)) -> Response:
    service = get_service_or_404(request, service_id)
    cls = get_integration_or_404(service.type)
    secrets, warning = existing_secrets(request, service)
    return render_form(
        request,
        session=session, cls=cls, service=service,
        action=f"/admin/services/{service.id}/edit",
        values={**default_config(cls), **service.config},
        common={"name": service.name, "category": service.category,
                "link_url": service.link_url, "enabled": service.enabled},
        saved_secrets=set(secrets), errors=[warning] if warning else [],
    )


@router.post("/admin/services/{service_id}/edit")
async def update_service(request: Request, service_id: int, session: Session = Depends(require_session)) -> Response:
    service = get_service_or_404(request, service_id)
    cls = get_integration_or_404(service.type)
    form = await csrf_form(request, session)
    secrets, _warning = existing_secrets(request, service)
    parsed = parse_service_form(cls, form, secrets)
    if parsed.errors:
        return render_form(
            request, status_code=400,
            session=session, cls=cls, service=service,
            action=f"/admin/services/{service.id}/edit",
            values=parsed.config, common=parsed.common, saved_secrets=set(secrets), errors=parsed.errors,
        )
    state = request.app.state
    state.store.update(
        service.id, config=parsed.config, secrets_enc=state.box.encrypt_json(parsed.secrets),
        **parsed.common,
    )
    updated = state.store.get(service.id)
    if updated and updated.enabled:
        state.poller.trigger(updated)
    else:
        state.poller.forget(service.id)
    return redirect("/admin?msg=updated")


@router.post("/admin/services/{service_id}/delete")
async def delete_service(request: Request, service_id: int, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    service = get_service_or_404(request, service_id)
    request.app.state.store.delete(service.id)
    request.app.state.poller.forget(service.id)
    return redirect("/admin?msg=deleted")


# --- phones ------------------------------------------------------------------------

PHONE_MESSAGES = {"revoked": "Phone removed. Its token no longer works."}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def default_hub_url(request: Request) -> str:
    saved = request.app.state.devices.get_setting("hub_url")
    return saved or str(request.base_url).rstrip("/")


@router.get("/admin/phones")
def phones_page(request: Request, session: Session = Depends(require_session)) -> Response:
    return render(
        request, "phones.html",
        session=session,
        devices=request.app.state.devices.list(),
        hub_url=default_hub_url(request),
        message=PHONE_MESSAGES.get(request.query_params.get("msg", "")),
        error=None,
    )


@router.post("/admin/phones/pair")
async def pair_phone(request: Request, session: Session = Depends(require_session)) -> Response:
    form = await csrf_form(request, session)
    devices = request.app.state.devices
    hub_url = str(form.get("hub_url") or "").strip().rstrip("/")
    if not is_http_url(hub_url):
        return render(
            request, "phones.html", status_code=400,
            session=session, devices=devices.list(), hub_url=hub_url, message=None,
            error="Enter the Hub address your phone will use, starting with http:// or https://.",
        )
    devices.set_setting("hub_url", hub_url)
    code, expires = devices.create_pairing_code()
    pair_uri = "homelabhub://pair?" + urlencode({"url": hub_url, "code": code})
    qr = segno.make(pair_uri, error="m").svg_data_uri(scale=6, border=2, dark="#000000", light="#ffffff")
    return render(
        request, "pair.html",
        session=session, code=code, expires=expires, hub_url=hub_url, qr=qr,
        minutes=PAIRING_MINUTES, warn_local=urlsplit(hub_url).hostname in LOCAL_HOSTS,
    )


@router.post("/admin/phones/{device_id}/revoke")
async def revoke_phone(request: Request, device_id: int, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    request.app.state.devices.revoke(device_id)
    return redirect("/admin/phones?msg=revoked")


@router.post("/admin/services/{service_id}/test")
async def test_service(request: Request, service_id: int, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    service = get_service_or_404(request, service_id)
    await request.app.state.poller.check_now(service)
    return redirect("/admin?msg=tested")
