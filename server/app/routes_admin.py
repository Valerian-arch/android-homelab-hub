"""Admin web UI: login, account/recovery, phones, and service management."""

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


def require_login(request: Request) -> Session:
    """Logged in. Used by the few pages allowed before the first password change."""
    session = current_session(request)
    if session is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return session


def require_session(request: Request) -> Session:
    """Logged in AND the temporary password has been changed."""
    session = require_login(request)
    if request.app.state.auth.must_change_password():
        raise HTTPException(status_code=303, headers={"Location": "/account/password"})
    return session


def is_same_site(request: Request) -> bool:
    """Reject form posts coming from other websites (login lock-out / CSRF on public forms).

    Browsers send Sec-Fetch-Site. Because this app uses ``Referrer-Policy: no-referrer``,
    same-site form posts may carry ``Origin: null``, so Origin is only compared when it is real.
    """
    site = request.headers.get("sec-fetch-site")
    if site:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()
    return True


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def check_password(request: Request, password: str) -> bool:
    """Verify the admin password, at most two scrypt checks at a time."""
    stored = request.app.state.auth.get_admin_hash()
    if stored is None:
        return False
    async with request.app.state.password_check:
        return await asyncio.to_thread(verify_password, password, stored)


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=settings.session_hours * 3600,
        httponly=True, samesite="strict", secure=settings.secure_cookies, path="/",
    )


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
def setup_page() -> RedirectResponse:
    # Old first-run page. The admin password is now generated on first start (see the log).
    return redirect("/login")


LOGIN_NOTICES = {
    "recovered": "Password reset. Log in with your new password.",
    "changed": "Password changed. Log in again.",
}
LOCKED_MESSAGE = "Too many failed attempts. Try again in 15 minutes."
CROSS_SITE_MESSAGE = "This form must be submitted from the Hub's own page."


def render_login(request: Request, status_code: int = 200, error: str | None = None) -> Response:
    return render(
        request, "login.html", status_code=status_code, error=error,
        notice=LOGIN_NOTICES.get(request.query_params.get("msg", "")),
        first_start=request.app.state.auth.must_change_password(),
    )


@router.get("/login")
def login_page(request: Request) -> Response:
    if current_session(request):
        return redirect("/admin")
    return render_login(request)


@router.post("/login")
async def login_submit(request: Request) -> Response:
    state = request.app.state
    if not is_same_site(request):
        return render_login(request, 403, CROSS_SITE_MESSAGE)
    if not state.login_limiter.try_acquire(client_ip(request)):  # counted BEFORE checking
        return render_login(request, 429, LOCKED_MESSAGE)
    form = await request.form()
    if not await check_password(request, str(form.get("password") or "")):
        return render_login(request, 401, "Wrong password.")
    state.login_limiter.reset(client_ip(request))
    response = redirect("/account/password" if state.auth.must_change_password() else "/admin")
    set_session_cookie(request, response, state.auth.create_session())
    return response


@router.get("/recover")
def recover_page(request: Request) -> Response:
    return render(request, "recover.html", error=None)


@router.post("/recover")
async def recover_submit(request: Request) -> Response:
    """Forgot password: one recovery code + a new password."""
    state = request.app.state
    if not is_same_site(request):
        return render(request, "recover.html", status_code=403, error=CROSS_SITE_MESSAGE)
    form = await request.form()
    password = str(form.get("password") or "")
    error = validate_new_password(password, str(form.get("confirm") or ""))
    if error:
        return render(request, "recover.html", status_code=400, error=error)
    if not state.login_limiter.try_acquire(client_ip(request)):
        return render(request, "recover.html", status_code=429, error=LOCKED_MESSAGE)
    if not state.auth.use_recovery_code(str(form.get("code") or "")):
        return render(request, "recover.html", status_code=401,
                      error="That recovery code isn't valid or was already used.")
    state.login_limiter.reset(client_ip(request))
    state.auth.set_password(await asyncio.to_thread(hash_password, password), must_change=False)
    state.auth.delete_other_sessions(None)  # log out everywhere
    return redirect("/login?msg=recovered")


# --- account -------------------------------------------------------------------------

ACCOUNT_MESSAGES = {
    "password": "Password changed. Other browsers were logged out.",
    "others": "All other browser sessions were logged out.",
}


@router.get("/account")
def account_page(request: Request, session: Session = Depends(require_session)) -> Response:
    return render(
        request, "account.html", session=session,
        codes_left=request.app.state.auth.recovery_codes_left(),
        message=ACCOUNT_MESSAGES.get(request.query_params.get("msg", "")),
    )


@router.get("/account/password")
def password_page(request: Request, session: Session = Depends(require_login)) -> Response:
    return render(request, "setup.html", session=session,
                  forced=request.app.state.auth.must_change_password(), error=None)


@router.post("/account/password")
async def password_submit(request: Request, session: Session = Depends(require_login)) -> Response:
    state = request.app.state
    form = await csrf_form(request, session)
    forced = state.auth.must_change_password()

    def fail(status: int, error: str) -> Response:
        return render(request, "setup.html", status_code=status, session=session, forced=forced, error=error)

    current = str(form.get("current_password") or "")
    new = str(form.get("password") or "")
    error = validate_new_password(new, str(form.get("confirm") or ""))
    if error:
        return fail(400, error)
    if new == current:
        return fail(400, "The new password must be different from the current one.")
    if not state.login_limiter.try_acquire(client_ip(request)):
        return fail(429, LOCKED_MESSAGE)
    if not await check_password(request, current):
        return fail(401, "Current password is wrong.")
    state.login_limiter.reset(client_ip(request))

    state.auth.set_password(await asyncio.to_thread(hash_password, new), must_change=False)
    state.auth.delete_other_sessions(session.token_hash)
    if state.auth.recovery_codes_left() == 0:
        return render(request, "recovery_codes.html", session=session,
                      codes=state.auth.generate_recovery_codes(), first_time=True)
    return redirect("/account?msg=password")


@router.post("/account/recovery-codes")
async def new_recovery_codes(request: Request, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    return render(request, "recovery_codes.html", session=session,
                  codes=request.app.state.auth.generate_recovery_codes(), first_time=False)


@router.post("/account/logout-others")
async def logout_others(request: Request, session: Session = Depends(require_session)) -> Response:
    await csrf_form(request, session)
    request.app.state.auth.delete_other_sessions(session.token_hash)
    return redirect("/account?msg=others")


@router.post("/logout")
async def logout(request: Request, session: Session = Depends(require_login)) -> Response:
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
