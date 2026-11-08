from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

INITIAL_PASSWORD = "temporary-pass-123"
PASSWORD = "correct horse battery"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
CODE_RE = re.compile(r"<code>([A-Z0-9]{5}-[A-Z0-9]{5})</code>")


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        data_dir=tmp_path, poll_interval=3600, secure_cookies=False, session_hours=1,
        initial_admin_password=INITIAL_PASSWORD,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def first_login(client) -> tuple[str, list[str]]:
    """Log in with the temporary password, set PASSWORD, return (csrf, recovery codes)."""
    response = client.post("/login", data={"password": INITIAL_PASSWORD})
    assert response.url.path == "/account/password", response.text
    csrf = CSRF_RE.search(response.text).group(1)
    response = client.post(
        "/account/password",
        data={"csrf_token": csrf, "current_password": INITIAL_PASSWORD, "password": PASSWORD, "confirm": PASSWORD},
    )
    assert response.status_code == 200 and "Your recovery codes" in response.text, response.text
    return csrf, CODE_RE.findall(response.text)


@pytest.fixture
def csrf(client) -> str:
    """Admin logged in with a real password; returns the session's CSRF token."""
    return first_login(client)[0]
