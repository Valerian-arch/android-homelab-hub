"""First-start password, forced change, lockout, cross-site protection, recovery codes."""

from __future__ import annotations

from app.auth import AuthStore
from app.bootstrap import ensure_admin, reset_admin_password
from app.config import Settings
from app.crypto import verify_password
from app.db import Database
from tests.conftest import CSRF_RE, INITIAL_PASSWORD, PASSWORD, first_login

NEW_PASSWORD = "an even better passphrase"


# --- first start ------------------------------------------------------------------

def test_random_password_printed_once(tmp_path, capsys):
    settings = Settings(data_dir=tmp_path, poll_interval=60, secure_cookies=False, session_hours=1)
    db = Database(tmp_path / "hub.db")
    db.init()
    auth = AuthStore(db, 1)
    ensure_admin(auth, settings)
    printed = capsys.readouterr().err
    assert "Admin password:" in printed
    password = printed.split("Admin password:")[1].split()[0]
    assert len(password) >= 16
    assert verify_password(password, auth.get_admin_hash())
    assert auth.must_change_password()
    ensure_admin(auth, settings)  # second start: nothing printed, password unchanged
    assert capsys.readouterr().err == ""
    assert verify_password(password, auth.get_admin_hash())


def test_old_setup_page_redirects_to_login(client):
    assert client.get("/setup").url.path == "/login"
    assert client.post("/setup", data={"password": "x" * 20, "confirm": "x" * 20}).status_code == 405


def test_login_page_explains_first_start(client):
    assert "docker logs homelab-hub" in client.get("/login").text


def test_must_change_password_before_anything_else(client):
    response = client.post("/login", data={"password": INITIAL_PASSWORD})
    assert response.url.path == "/account/password"
    assert "Choose your admin password" in response.text
    # Every admin page bounces back to the password page until it is changed.
    for path in ("/admin", "/admin/phones", "/account", "/admin/services/new"):
        assert client.get(path).url.path == "/account/password"


def test_password_change_shows_recovery_codes(client, app):
    csrf, codes = first_login(client)
    assert len(codes) == 5 and len(set(codes)) == 5
    assert not app.state.auth.must_change_password()
    assert client.get("/admin").url.path == "/admin"
    assert "5</strong> unused recovery codes" in client.get("/account").text


def test_password_change_validation(client):
    response = client.post("/login", data={"password": INITIAL_PASSWORD})
    csrf = CSRF_RE.search(response.text).group(1)
    same = client.post("/account/password", data={"csrf_token": csrf, "current_password": INITIAL_PASSWORD,
                                                  "password": INITIAL_PASSWORD, "confirm": INITIAL_PASSWORD})
    assert same.status_code == 400 and "different" in same.text
    wrong = client.post("/account/password", data={"csrf_token": csrf, "current_password": "not it at all",
                                                   "password": PASSWORD, "confirm": PASSWORD})
    assert wrong.status_code == 401
    short = client.post("/account/password", data={"csrf_token": csrf, "current_password": INITIAL_PASSWORD,
                                                   "password": "short", "confirm": "short"})
    assert short.status_code == 400


# --- lockout ------------------------------------------------------------------------

def test_three_failures_lock_out(client):
    for _ in range(3):
        assert client.post("/login", data={"password": "wrong password!"}).status_code == 401
    locked = client.post("/login", data={"password": INITIAL_PASSWORD})  # even the right password
    assert locked.status_code == 429 and "15 minutes" in locked.text


def test_lockout_counts_before_checking(app):
    limiter = app.state.login_limiter
    # Three attempts "in flight" (none finished yet) already use up the allowance.
    assert all(limiter.try_acquire("1.2.3.4") for _ in range(3))
    assert limiter.try_acquire("1.2.3.4") is False
    assert limiter.window == 15 * 60
    limiter.reset("1.2.3.4")
    assert limiter.try_acquire("1.2.3.4")


def test_success_clears_failures(client):
    for _ in range(2):
        client.post("/login", data={"password": "wrong password!"})
    assert client.post("/login", data={"password": INITIAL_PASSWORD}).url.path == "/account/password"


# --- cross-site protection ------------------------------------------------------------

def test_cross_site_login_rejected_without_counting(client):
    for _ in range(5):
        response = client.post("/login", data={"password": "wrong"}, headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403
    # Those attempts didn't count, so the admin is not locked out.
    assert client.post("/login", data={"password": INITIAL_PASSWORD}).url.path == "/account/password"


def test_foreign_origin_rejected_but_null_origin_allowed(client):
    evil = client.post("/login", data={"password": INITIAL_PASSWORD}, headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    # Same-site posts may carry "Origin: null" because of Referrer-Policy: no-referrer.
    ok = client.post("/login", data={"password": INITIAL_PASSWORD},
                     headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert ok.url.path == "/account/password"


def test_cross_site_recover_rejected(client):
    response = client.post("/recover", data={"code": "x", "password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
                           headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


# --- recovery codes ---------------------------------------------------------------------

def test_recovery_code_resets_password_once(client, app):
    csrf, codes = first_login(client)
    client.post("/logout", data={"csrf_token": csrf})

    response = client.post("/recover", data={"code": codes[0].lower(), "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert response.url.path == "/login" and "Password reset" in response.text
    assert client.post("/login", data={"password": NEW_PASSWORD}).url.path == "/admin"
    assert app.state.auth.recovery_codes_left() == 4

    reused = client.post("/recover", data={"code": codes[0], "password": PASSWORD, "confirm": PASSWORD})
    assert reused.status_code == 401


def test_recovery_logs_out_everyone(client, app, csrf):
    assert client.get("/admin").url.path == "/admin"
    code = app.state.auth.generate_recovery_codes()[0]
    client.post("/recover", data={"code": code, "password": NEW_PASSWORD, "confirm": NEW_PASSWORD})
    assert client.get("/admin").url.path == "/login"


def test_new_recovery_codes_replace_old(client, app, csrf):
    old = app.state.auth.generate_recovery_codes()
    page = client.post("/account/recovery-codes", data={"csrf_token": csrf}).text
    assert "previous recovery codes no longer work" in page
    assert not app.state.auth.use_recovery_code(old[0])


def test_logout_other_sessions(app, client, csrf):
    from fastapi.testclient import TestClient

    with TestClient(app) as other:
        assert other.post("/login", data={"password": PASSWORD}).url.path == "/admin"
        client.post("/account/logout-others", data={"csrf_token": csrf})
        assert other.get("/admin").url.path == "/login"   # other browser logged out
    assert client.get("/admin").url.path == "/admin"       # this one still logged in


def test_emergency_cli_reset(tmp_path):
    db = Database(tmp_path / "hub.db")
    db.init()
    auth = AuthStore(db, 1)
    password = reset_admin_password(auth)  # works even when no admin exists yet
    assert verify_password(password, auth.get_admin_hash()) and auth.must_change_password()
    second = reset_admin_password(auth)
    assert second != password and verify_password(second, auth.get_admin_hash())
